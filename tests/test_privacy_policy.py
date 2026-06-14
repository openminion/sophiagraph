"""Privacy, consent, redaction, retention, and export gating tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from sophiagraph.audit import PolicyDecision
from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.models import (
    ConsentState,
    MemoryNamespace,
    MemoryRecord,
    MemoryRelation,
    PrivacyPolicyState,
    RedactionPlan,
    RedactionTarget,
)
from sophiagraph.portability.models import (
    MemoryBundleExportOptions,
    MemoryBundleImportOptions,
    MemoryBundleSnapshot,
)
from sophiagraph.privacy import (
    PRIVACY_META_KEY,
    apply_retention_policy,
    filter_records_for_retrieval,
    filter_snapshot_for_export,
    privacy_policy_from_record,
    record_with_privacy_policy,
    retention_outcome_for_record,
)
from sophiagraph.storage import SophiaGraphMemoryStore, SophiaGraphSqliteStore
from sophiagraph.storage.record_lifecycle import utc_now_iso


def _ns() -> MemoryNamespace:
    return MemoryNamespace(agent_id="agent", session_id="session", graph_id="graph")


def _record(
    record_id: str,
    *,
    content: str | dict[str, object] = "secret value",
) -> MemoryRecord:
    now = utc_now_iso()
    return MemoryRecord(
        id=record_id,
        scope="agent:session",
        type="fact",
        content=content,
        created_at=now,
        updated_at=now,
        namespace=_ns(),
        title=record_id,
        meta={},
    )


def _policy(
    *,
    retrieval_visibility: str = "visible",
    export_visibility: str = "visible",
    retention_class: str = "retain",
    erase_intent: str = "none",
    reason: str = "explicit_allow",
    redaction_plan: RedactionPlan | None = None,
) -> PrivacyPolicyState:
    return PrivacyPolicyState(
        policy_id=f"policy-{retrieval_visibility}-{export_visibility}-{retention_class}",
        consent=ConsentState(status="granted", granted_at=utc_now_iso()),
        retrieval_visibility=retrieval_visibility,  # type: ignore[arg-type]
        export_visibility=export_visibility,  # type: ignore[arg-type]
        retention_class=retention_class,  # type: ignore[arg-type]
        erase_intent=erase_intent,  # type: ignore[arg-type]
        decision_reason=reason,  # type: ignore[arg-type]
        source_owner="openminion",
        applied_at=utc_now_iso(),
        redaction_plan=redaction_plan,
    )


def _store(kind: str, tmp_path: Path):
    if kind == "memory":
        return SophiaGraphMemoryStore()
    return SophiaGraphSqliteStore(tmp_path / "privacy.sqlite3")


def test_privacy_policy_round_trips_through_record_meta() -> None:
    plan = RedactionPlan(
        plan_id="plan-1",
        reason="privacy_request",
        targets=(
            RedactionTarget(kind="record_content"),
            RedactionTarget(kind="metadata_key", key="email"),
        ),
        applied_by="operator",
    )
    record = _record("rec-1", content={"body": "secret"})
    record = record_with_privacy_policy(
        record,
        _policy(
            retrieval_visibility="redacted",
            export_visibility="redacted",
            retention_class="redact_and_retain",
            reason="redaction_required",
            redaction_plan=plan,
        ),
    )

    raw = record.meta[PRIVACY_META_KEY]
    assert isinstance(raw, dict)
    policy = privacy_policy_from_record(record)
    assert policy is not None
    assert policy.redaction_plan is not None
    assert policy.redaction_plan.targets[1].key == "email"
    assert policy.retrieval_visibility == "redacted"
    assert policy.retention_class == "redact_and_retain"


@pytest.mark.parametrize("backend", ["memory", "sqlite"])
def test_privacy_policy_storage_and_bundle_round_trip(
    backend: str, tmp_path: Path
) -> None:
    store = _store(backend, tmp_path)
    original = record_with_privacy_policy(
        _record("rec-1", content={"body": "secret", "email": "user@example.com"}),
        _policy(
            retrieval_visibility="redacted",
            export_visibility="hidden",
            retention_class="retain_hidden",
            reason="export_restricted",
            redaction_plan=RedactionPlan(
                plan_id="plan-2",
                reason="export_minimization",
                targets=(RedactionTarget(kind="metadata_key", key="email"),),
            ),
        ),
    )
    store.put_record(original)

    fetched = store.get_record("rec-1")
    assert fetched is not None
    policy = privacy_policy_from_record(fetched)
    assert policy is not None
    assert policy.export_visibility == "hidden"
    assert policy.redaction_plan is not None
    assert policy.redaction_plan.plan_id == "plan-2"

    snapshot = store.export_snapshot(
        MemoryBundleExportOptions(scopes=["agent:session"], namespaces=[_ns()])
    )
    imported = SophiaGraphMemoryStore()
    imported.import_snapshot(snapshot, MemoryBundleImportOptions())
    restored = imported.get_record("rec-1")
    assert restored is not None
    restored_policy = privacy_policy_from_record(restored)
    assert restored_policy is not None
    assert restored_policy.export_visibility == "hidden"


def test_filter_records_for_retrieval_applies_visibility_redaction_and_hooks() -> None:
    redacted = record_with_privacy_policy(
        _record(
            "rec-redacted", content={"body": "secret", "email": "user@example.com"}
        ),
        _policy(
            retrieval_visibility="redacted",
            export_visibility="visible",
            retention_class="retain",
            reason="redaction_required",
            redaction_plan=RedactionPlan(
                plan_id="plan-redacted",
                reason="privacy_request",
                targets=(
                    RedactionTarget(kind="record_content"),
                    RedactionTarget(kind="metadata_key", key="email"),
                ),
            ),
        ),
    )
    hidden = record_with_privacy_policy(
        _record("rec-hidden"),
        _policy(
            retrieval_visibility="hidden",
            export_visibility="hidden",
            retention_class="retain_hidden",
            reason="visibility_hidden",
        ),
    )
    allowed = _record("rec-allowed")
    denied = _record("rec-denied")

    def hook(request):
        if request.target_id == "rec-denied":
            return PolicyDecision(
                action="deny",
                policy_id="privacy-hook",
                reason_code="POLICY_DENIED_BY_HOOK",
                details={"rule": "deny-rec-denied"},
            )
        return PolicyDecision(action="allow", policy_id="allow-all")

    result = filter_records_for_retrieval(
        [allowed, redacted, hidden, denied],
        source_owner="openminion",
        hooks=[hook],
    )

    assert [record.id for record in result.records] == ["rec-allowed", "rec-redacted"]
    assert len(result.redactions) == 1
    assert isinstance(result.records[1].content, dict)
    assert result.records[1].content["_redacted"] is True
    assert [item.record_id for item in result.omitted] == ["rec-hidden", "rec-denied"]
    assert [item.reason for item in result.omitted] == [
        "hidden_by_visibility",
        "denied_by_policy_hook",
    ]
    assert len(result.denial_events) == 1
    assert result.denial_events[0].surface == "retrieval"


def test_filter_snapshot_for_export_redacts_and_drops_hidden_relations() -> None:
    visible = _record("rec-visible")
    hidden = record_with_privacy_policy(
        _record("rec-hidden"),
        _policy(
            retrieval_visibility="visible",
            export_visibility="hidden",
            retention_class="retain_hidden",
            reason="export_restricted",
        ),
    )
    redacted = record_with_privacy_policy(
        _record("rec-redacted", content={"body": "secret", "token": "abc"}),
        _policy(
            retrieval_visibility="visible",
            export_visibility="redacted",
            retention_class="retain",
            reason="redaction_required",
            redaction_plan=RedactionPlan(
                plan_id="plan-export",
                reason="export_minimization",
                targets=(RedactionTarget(kind="record_content"),),
            ),
        ),
    )
    relation = MemoryRelation(
        relation_id="rel-1",
        source_record_id="rec-visible",
        target_record_id="rec-hidden",
        relation_type="related_to",
        created_at=utc_now_iso(),
    )
    snapshot = MemoryBundleSnapshot(
        manifest={},
        records=[visible, hidden, redacted],
        relations=[relation],
    )
    result = filter_snapshot_for_export(snapshot, source_owner="openminion")

    assert [record.id for record in result.snapshot.records] == [
        "rec-visible",
        "rec-redacted",
    ]
    assert result.snapshot.relations == []
    assert [item.record_id for item in result.omitted] == ["rec-hidden"]
    assert result.redactions[0].record_id == "rec-redacted"


def test_retention_outcome_and_apply_policy_distinguish_all_states() -> None:
    store = SophiaGraphMemoryStore()
    keep = record_with_privacy_policy(
        _record("rec-keep"),
        _policy(retention_class="retain", reason="explicit_allow"),
    )
    hide = record_with_privacy_policy(
        _record("rec-hide"),
        _policy(
            retrieval_visibility="visible",
            export_visibility="visible",
            retention_class="retain_hidden",
            reason="visibility_hidden",
        ),
    )
    redact = record_with_privacy_policy(
        _record("rec-redact", content={"body": "secret", "email": "user@example.com"}),
        _policy(
            retrieval_visibility="redacted",
            export_visibility="redacted",
            retention_class="redact_and_retain",
            reason="redaction_required",
            redaction_plan=RedactionPlan(
                plan_id="plan-retain",
                reason="privacy_request",
                targets=(RedactionTarget(kind="record_content"),),
            ),
        ),
    )
    tombstone = record_with_privacy_policy(
        _record("rec-tombstone"),
        _policy(retention_class="tombstone", reason="retention_hold"),
    )
    erase = record_with_privacy_policy(
        _record("rec-erase"),
        _policy(
            retention_class="erase_requested",
            erase_intent="user_requested",
            reason="erase_requested",
        ),
    )
    dependent = _record("rec-dependent")

    for record in [keep, hide, redact, tombstone, erase, dependent]:
        store.put_record(record)
    store.put_relation(
        MemoryRelation(
            relation_id="rel-erase",
            source_record_id="rec-erase",
            target_record_id="rec-dependent",
            relation_type="related_to",
            created_at=utc_now_iso(),
        )
    )

    assert retention_outcome_for_record(keep).kind == "retain"
    assert retention_outcome_for_record(hide).kind == "hide"
    assert retention_outcome_for_record(redact).kind == "redact_and_retain"
    assert retention_outcome_for_record(tombstone).kind == "tombstone"
    assert retention_outcome_for_record(erase).kind == "erase"

    apply_retention_policy(
        store, hide, deleted_at=utc_now_iso(), reason="hide for retention"
    )
    hidden_record = store.get_record("rec-hide")
    assert hidden_record is not None
    hidden_policy = privacy_policy_from_record(hidden_record)
    assert hidden_policy is not None
    assert hidden_policy.retrieval_visibility == "hidden"
    assert hidden_policy.export_visibility == "hidden"

    apply_retention_policy(
        store, redact, deleted_at=utc_now_iso(), reason="redact for retention"
    )
    redacted_record = store.get_record("rec-redact")
    assert redacted_record is not None
    assert isinstance(redacted_record.content, dict)
    assert redacted_record.content["_redacted"] is True

    apply_retention_policy(
        store,
        tombstone,
        deleted_at="2026-06-14T00:00:00Z",
        reason="policy tombstone",
    )
    tombstoned_record = store.get_record("rec-tombstone")
    assert tombstoned_record is not None
    assert tombstoned_record.is_deleted is True

    apply_retention_policy(
        store,
        erase,
        deleted_at="2026-06-14T00:00:01Z",
        reason="policy erase",
    )
    erased_record = store.get_record("rec-erase")
    assert erased_record is not None
    assert erased_record.is_deleted is True
    assert store.list_relations("rec-erase") == []


def test_privacy_policy_validation_rejects_invalid_visibility() -> None:
    with pytest.raises(InvalidArgumentError):
        _policy(retrieval_visibility="guess")  # type: ignore[arg-type]
