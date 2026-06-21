"""Entity, fact, contradiction, and summary coverage."""

from __future__ import annotations

from pathlib import Path

import pytest

from sophiagraph import SophiaGraphMemoryStore, SophiaGraphSqliteStore
from sophiagraph.contracts.errors import (
    InvalidArgumentError,
    InvalidSupersessionError,
)
from sophiagraph.models import (
    ConsentState,
    Contradiction,
    Entity,
    EntityAlias,
    EntitySummary,
    Fact,
    MemoryNamespace,
    PrivacyPolicyState,
)
from sophiagraph.models.entity_fact import EntityFactProvenance
from sophiagraph.storage.graph_helpers import entity_summary_from_dict


def _ns_a() -> MemoryNamespace:
    return MemoryNamespace(tenant_id="acme", agent_id="alpha")


def _ns_b() -> MemoryNamespace:
    return MemoryNamespace(tenant_id="acme", agent_id="beta")


def _prov() -> EntityFactProvenance:
    return EntityFactProvenance(
        source_kind="tool_observation", source_id="t-1", actor="agent"
    )


@pytest.fixture(params=["memory", "sqlite"])
def store(request, tmp_path: Path):
    if request.param == "memory":
        return SophiaGraphMemoryStore()
    return SophiaGraphSqliteStore(tmp_path / "sg.sqlite3")


# SEFT-01: DTO validation


def test_entity_requires_canonical_name() -> None:
    with pytest.raises(InvalidArgumentError):
        Entity(
            entity_id="e-1", canonical_name="", namespace=_ns_a(), provenance=_prov()
        )


def test_fact_requires_either_object_entity_or_literal() -> None:
    with pytest.raises(InvalidArgumentError):
        Fact(
            fact_id="f-1",
            namespace=_ns_a(),
            subject_entity_id="e-1",
            predicate="lives_in",
        )


def test_fact_validates_temporal_range() -> None:
    with pytest.raises(InvalidArgumentError):
        Fact(
            fact_id="f-1",
            namespace=_ns_a(),
            subject_entity_id="e-1",
            predicate="lives_in",
            object_literal="Berlin",
            valid_from="2026-01-02",
            valid_to="2026-01-01",
            provenance=_prov(),
        )


def test_provenance_requires_known_source_kind() -> None:
    with pytest.raises(InvalidArgumentError):
        EntityFactProvenance(
            source_kind="rumor",
            source_id="x",
            actor="agent",  # type: ignore[arg-type]
        )


def test_entity_summary_requires_summary_text() -> None:
    with pytest.raises(InvalidArgumentError):
        EntitySummary(
            summary_id="s-1",
            entity_id="e-1",
            namespace=_ns_a(),
            summary_text="",
            provenance=_prov(),
        )


def test_entity_summary_validates_authorship_and_invalidation_reason() -> None:
    with pytest.raises(InvalidArgumentError):
        EntitySummary(
            summary_id="s-1",
            entity_id="e-1",
            namespace=_ns_a(),
            summary_text="Summary",
            provenance=_prov(),
            authorship="guessed",  # type: ignore[arg-type]
        )
    with pytest.raises(InvalidArgumentError):
        EntitySummary(
            summary_id="s-1",
            entity_id="e-1",
            namespace=_ns_a(),
            summary_text="Summary",
            provenance=_prov(),
            invalidation_reason="maybe_stale",  # type: ignore[arg-type]
        )


def test_entity_summary_legacy_payload_hydrates_new_fields_with_defaults() -> None:
    summary = entity_summary_from_dict(
        {
            "summary_id": "sum-legacy",
            "entity_id": "e-1",
            "namespace": _ns_a().as_dict(),
            "summary_text": "Legacy summary",
            "provenance": {
                "source_kind": "tool_observation",
                "source_id": "t-1",
                "actor": "agent",
                "extra": {},
            },
            "created_at": "2026-06-15T00:00:00+00:00",
            "updated_at": "2026-06-15T00:00:00+00:00",
        }
    )

    assert summary.authorship == "model_authored"
    assert summary.invalidation_reason is None
    assert summary.superseded_by_summary_id is None
    assert summary.source_record_ids == ()
    assert summary.privacy_policy is None


def test_entity_summary_can_carry_typed_privacy_state() -> None:
    summary = EntitySummary(
        summary_id="sum-1",
        entity_id="e-1",
        namespace=_ns_a(),
        summary_text="Summary",
        provenance=_prov(),
        privacy_policy=PrivacyPolicyState(
            policy_id="policy-1",
            consent=ConsentState(
                status="granted", granted_at="2026-06-15T00:00:00+00:00"
            ),
            retrieval_visibility="visible",
            export_visibility="visible",
            retention_class="retain",
            erase_intent="none",
            decision_reason="explicit_allow",
            source_owner="openminion",
            applied_at="2026-06-15T00:00:00+00:00",
        ),
    )
    assert summary.privacy_policy is not None
    assert summary.privacy_policy.policy_id == "policy-1"


def test_anti_llm_no_inference_helpers_on_module_surface() -> None:
    """The entity/fact module must not expose prose-inference symbols."""
    from sophiagraph.models import entity_fact as mod

    forbidden = {
        "extract_entities_from_prose",
        "summarize_entity",
        "classify_fact",
        "infer_aliases",
    }
    assert set(mod.__all__) & forbidden == set()


# SEFT-02: persistence + namespace isolation


def test_entity_round_trip(store) -> None:
    e = Entity(
        entity_id="e-1", canonical_name="Alice", namespace=_ns_a(), provenance=_prov()
    )
    store.put_entity(e)
    loaded = store.get_entity("e-1")
    assert loaded is not None
    assert loaded.canonical_name == "Alice"
    assert loaded.namespace == _ns_a()


def test_list_entities_namespace_isolation(store) -> None:
    store.put_entity(
        Entity(
            entity_id="e-a", canonical_name="A", namespace=_ns_a(), provenance=_prov()
        )
    )
    store.put_entity(
        Entity(
            entity_id="e-b", canonical_name="B", namespace=_ns_b(), provenance=_prov()
        )
    )
    only_a = store.list_entities(namespaces=[_ns_a()])
    only_b = store.list_entities(namespaces=[_ns_b()])
    assert {e.entity_id for e in only_a} == {"e-a"}
    assert {e.entity_id for e in only_b} == {"e-b"}


def test_entity_aliases_round_trip(store) -> None:
    store.put_entity_alias(
        EntityAlias(
            alias_id="a-1",
            alias_name="Al",
            entity_id="e-1",
            original_entity_id="e-1",
            namespace=_ns_a(),
            provenance=_prov(),
        )
    )
    rows = store.list_entity_aliases(entity_id="e-1")
    assert len(rows) == 1
    assert rows[0].alias_name == "Al"


def test_entity_summary_round_trip_preserves_metadata_and_order(store) -> None:
    store.put_entity_summary(
        EntitySummary(
            summary_id="sum-older",
            entity_id="e-1",
            namespace=_ns_a(),
            summary_text="Older summary",
            provenance=_prov(),
            authorship="operator_authored",
            source_record_ids=("rec-1",),
            created_at="2026-06-14T00:00:00+00:00",
            updated_at="2026-06-14T00:00:00+00:00",
        )
    )
    store.put_entity_summary(
        EntitySummary(
            summary_id="sum-newer",
            entity_id="e-1",
            namespace=_ns_a(),
            summary_text="Newer summary",
            provenance=_prov(),
            authorship="system_derived",
            source_record_ids=("rec-2", "rec-3"),
            created_at="2026-06-15T00:00:00+00:00",
            updated_at="2026-06-15T00:00:00+00:00",
        )
    )

    loaded = store.get_entity_summary("sum-newer")
    assert loaded is not None
    assert loaded.authorship == "system_derived"
    assert loaded.source_record_ids == ("rec-2", "rec-3")

    rows = store.list_entity_summaries(entity_id="e-1")
    assert [row.summary_id for row in rows] == ["sum-newer", "sum-older"]


def test_fact_persists_with_temporal_filter(store) -> None:
    store.put_fact(
        Fact(
            fact_id="f-1",
            namespace=_ns_a(),
            subject_entity_id="e-1",
            predicate="lives_in",
            object_literal="Berlin",
            valid_from="2020-01-01",
            valid_to="2022-12-31",
            observed_at="2020-01-01",
            provenance=_prov(),
        )
    )
    store.put_fact(
        Fact(
            fact_id="f-2",
            namespace=_ns_a(),
            subject_entity_id="e-1",
            predicate="lives_in",
            object_literal="Paris",
            valid_from="2023-01-01",
            observed_at="2023-01-01",
            provenance=_prov(),
        )
    )
    in_2021 = store.list_facts(subject_entity_id="e-1", valid_at="2021-06-01")
    assert [f.fact_id for f in in_2021] == ["f-1"]
    in_2024 = store.list_facts(subject_entity_id="e-1", valid_at="2024-06-01")
    assert [f.fact_id for f in in_2024] == ["f-2"]


# SEFT-03: contradiction preserves both facts; invalid refs fail loudly


def _seed_two_facts(store) -> tuple[str, str]:
    store.put_fact(
        Fact(
            fact_id="f-a",
            namespace=_ns_a(),
            subject_entity_id="e-1",
            predicate="role",
            object_literal="manager",
            observed_at="2026-01-01",
            provenance=_prov(),
        )
    )
    store.put_fact(
        Fact(
            fact_id="f-b",
            namespace=_ns_a(),
            subject_entity_id="e-1",
            predicate="role",
            object_literal="ic",
            observed_at="2026-05-01",
            provenance=_prov(),
        )
    )
    return "f-a", "f-b"


def test_contradiction_supersedes_preserves_target_fact(store) -> None:
    a, b = _seed_two_facts(store)
    store.record_contradiction(
        Contradiction(
            contradiction_id="c-1",
            namespace=_ns_a(),
            target_fact_id=a,
            contradicting_fact_id=b,
            decision="supersedes",
            deciding_actor="user",
            decided_at="2026-05-01",
        )
    )
    target = store.get_fact(a)
    assert target is not None
    # Evidence retained.
    assert target.predicate == "role"
    assert target.object_literal == "manager"
    # But now closed.
    assert target.is_invalidated is True
    assert target.superseded_by_fact_id == b


def test_contradiction_both_valid_keeps_both_open(store) -> None:
    a, b = _seed_two_facts(store)
    store.record_contradiction(
        Contradiction(
            contradiction_id="c-1",
            namespace=_ns_a(),
            target_fact_id=a,
            contradicting_fact_id=b,
            decision="both_valid",
            deciding_actor="user",
            decided_at="2026-05-01",
        )
    )
    target = store.get_fact(a)
    other = store.get_fact(b)
    assert target.is_invalidated is False
    assert other.is_invalidated is False


def test_contradiction_with_unknown_fact_raises_typed_error(store) -> None:
    a, _b = _seed_two_facts(store)
    with pytest.raises(InvalidSupersessionError) as info:
        store.record_contradiction(
            Contradiction(
                contradiction_id="c-bad",
                namespace=_ns_a(),
                target_fact_id=a,
                contradicting_fact_id="f-missing",
                decision="supersedes",
                deciding_actor="user",
                decided_at="2026-05-01",
            )
        )
    assert info.value.code == "INVALID_SUPERSESSION"


def test_list_contradictions_round_trip(store) -> None:
    a, b = _seed_two_facts(store)
    store.record_contradiction(
        Contradiction(
            contradiction_id="c-1",
            namespace=_ns_a(),
            target_fact_id=a,
            contradicting_fact_id=b,
            decision="invalidates_target",
            deciding_actor="user",
            decided_at="2026-05-01",
        )
    )
    rows = store.list_contradictions(target_fact_id=a)
    assert len(rows) == 1
    assert rows[0].decision == "invalidates_target"


# SEFT-04: entity summaries are caller-supplied only


def test_entity_summary_round_trip(store) -> None:
    store.put_entity_summary(
        EntitySummary(
            summary_id="s-1",
            entity_id="e-1",
            namespace=_ns_a(),
            summary_text="Alice is a senior engineer (operator-curated).",
            provenance=_prov(),
        )
    )
    rows = store.list_entity_summaries(entity_id="e-1")
    assert len(rows) == 1
    assert rows[0].summary_text.startswith("Alice is a senior engineer")


def test_entity_summary_namespace_isolation(store) -> None:
    store.put_entity_summary(
        EntitySummary(
            summary_id="s-a",
            entity_id="e-1",
            namespace=_ns_a(),
            summary_text="A",
            provenance=_prov(),
        )
    )
    store.put_entity_summary(
        EntitySummary(
            summary_id="s-b",
            entity_id="e-1",
            namespace=_ns_b(),
            summary_text="B",
            provenance=_prov(),
        )
    )
    only_a = store.list_entity_summaries(entity_id="e-1", namespaces=[_ns_a()])
    assert {s.summary_id for s in only_a} == {"s-a"}
