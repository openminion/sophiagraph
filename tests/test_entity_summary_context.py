"""Entity summary context assembly coverage."""

from __future__ import annotations

from pathlib import Path

import pytest

from sophiagraph.audit import PolicyDecision
from sophiagraph.models import (
    ConsentState,
    EntitySummary,
    MemoryNamespace,
    PrivacyPolicyState,
)
from sophiagraph.models.entity_fact import EntityFactProvenance
from sophiagraph.query import (
    ContextBudget,
    SummaryContextRequest,
    assemble_entity_summary_context,
)
from sophiagraph.storage import SophiaGraphMemoryStore, SophiaGraphSqliteStore


def _ns() -> MemoryNamespace:
    return MemoryNamespace(tenant_id="acme", agent_id="alpha", graph_id="main")


def _prov() -> EntityFactProvenance:
    return EntityFactProvenance(
        source_kind="tool_observation",
        source_id="tool-1",
        actor="agent",
    )


def _policy(
    *,
    retrieval_visibility: str,
    reason: str = "explicit_allow",
) -> PrivacyPolicyState:
    return PrivacyPolicyState(
        policy_id=f"policy-{retrieval_visibility}",
        consent=ConsentState(status="granted", granted_at="2026-06-15T00:00:00+00:00"),
        retrieval_visibility=retrieval_visibility,  # type: ignore[arg-type]
        export_visibility="visible",
        retention_class="retain",
        erase_intent="none",
        decision_reason=reason,  # type: ignore[arg-type]
        source_owner="openminion",
        applied_at="2026-06-15T00:00:00+00:00",
    )


def _summary(
    summary_id: str,
    *,
    entity_id: str = "entity-1",
    summary_text: str = "Summary text",
    updated_at: str = "2026-06-15T00:00:00+00:00",
    invalidated_at: str | None = None,
    invalidation_reason: str | None = None,
    privacy_policy: PrivacyPolicyState | None = None,
) -> EntitySummary:
    return EntitySummary(
        summary_id=summary_id,
        entity_id=entity_id,
        namespace=_ns(),
        summary_text=summary_text,
        provenance=_prov(),
        source_record_ids=("rec-1",),
        created_at="2026-06-14T00:00:00+00:00",
        updated_at=updated_at,
        invalidated_at=invalidated_at,
        invalidation_reason=invalidation_reason,  # type: ignore[arg-type]
        privacy_policy=privacy_policy,
    )


@pytest.fixture(params=["memory", "sqlite"])
def store(request, tmp_path: Path):
    if request.param == "memory":
        return SophiaGraphMemoryStore()
    return SophiaGraphSqliteStore(tmp_path / "entity-summary-context.sqlite3")


def test_summary_context_request_requires_ids() -> None:
    with pytest.raises(Exception):
        SummaryContextRequest()


def test_summary_context_assembles_explicit_ids_in_order(store) -> None:
    store.put_entity_summary(_summary("sum-b", summary_text="Second"))
    store.put_entity_summary(_summary("sum-a", summary_text="First"))

    result = assemble_entity_summary_context(
        store,
        SummaryContextRequest(summary_ids=["sum-a", "sum-b"]),
    )

    assert [item.summary_id for item in result.items] == ["sum-a", "sum-b"]
    assert result.omitted == []
    assert result.items[0].provenance["source_record_ids"] == ["rec-1"]


def test_summary_context_entity_mode_uses_deterministic_latest_first_order(store) -> None:
    store.put_entity_summary(
        _summary("sum-older", updated_at="2026-06-14T00:00:00+00:00")
    )
    store.put_entity_summary(
        _summary("sum-newer", updated_at="2026-06-15T00:00:00+00:00")
    )

    result = assemble_entity_summary_context(
        store,
        SummaryContextRequest(entity_ids=["entity-1"]),
    )

    assert [item.summary_id for item in result.items] == ["sum-newer", "sum-older"]


def test_summary_context_surfaces_invalidated_and_missing_as_omissions(store) -> None:
    store.put_entity_summary(
        _summary(
            "sum-old",
            invalidated_at="2026-06-15T01:00:00+00:00",
            invalidation_reason="source_record_changed",
        )
    )

    result = assemble_entity_summary_context(
        store,
        SummaryContextRequest(summary_ids=["sum-missing", "sum-old"]),
    )

    assert [item.summary_id for item in result.items] == []
    assert [(item.summary_id, item.reason) for item in result.omitted] == [
        ("sum-missing", "not_found"),
        ("sum-old", "invalidated"),
    ]


@pytest.mark.parametrize(
    ("visibility", "reason"),
    [
        ("hidden", "hidden_by_visibility"),
        ("audit_only", "audit_only"),
        ("redacted", "redacted_by_policy"),
    ],
)
def test_summary_context_surfaces_visibility_omissions(
    store,
    visibility: str,
    reason: str,
) -> None:
    store.put_entity_summary(
        _summary(
            f"sum-{visibility}",
            privacy_policy=_policy(
                retrieval_visibility=visibility,
                reason="visibility_hidden"
                if visibility != "redacted"
                else "redaction_required",
            ),
        )
    )

    result = assemble_entity_summary_context(
        store,
        SummaryContextRequest(summary_ids=[f"sum-{visibility}"]),
    )

    assert result.items == []
    assert [item.reason for item in result.omitted] == [reason]


def test_summary_context_reuses_policy_hook_denial_path(store) -> None:
    store.put_entity_summary(_summary("sum-1"))

    def deny_hook(request):
        return PolicyDecision(
            action="deny",
            policy_id="privacy-hook",
            reason_code="POLICY_DENIED_BY_HOOK",
            details={"rule": "deny-entity-summary"},
        )

    result = assemble_entity_summary_context(
        store,
        SummaryContextRequest(summary_ids=["sum-1"]),
        source_owner="openminion",
        hooks=[deny_hook],
    )

    assert result.items == []
    assert [item.reason for item in result.omitted] == ["denied_by_policy_hook"]
    assert len(result.denial_events) == 1
    assert result.denial_events[0].target_kind == "entity_summary"
    assert result.denial_events[0].surface == "retrieval"


def test_summary_context_applies_item_budget(store) -> None:
    store.put_entity_summary(_summary("sum-1"))
    store.put_entity_summary(_summary("sum-2", updated_at="2026-06-16T00:00:00+00:00"))

    result = assemble_entity_summary_context(
        store,
        SummaryContextRequest(
            entity_ids=["entity-1"],
            budget=ContextBudget(max_items=1, max_record_chars=7),
        ),
    )

    assert [item.summary_id for item in result.items] == ["sum-2"]
    assert result.items[0].summary_text == "Summary"
    assert result.items[0].detail["truncated"] is True
    assert [item.reason for item in result.omitted] == ["budget_exceeded"]
