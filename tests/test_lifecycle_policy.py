"""KPR-03 typed-surface tests.

Covers:
1. Enum closure (membership-pin) for `LifecyclePhase` + `PromotionPredicateKind`.
2. `PromotionPredicate` cross-field invariants per kind.
3. `LifecyclePolicy` field invariants.
4. `LifecycleDecision`, `ConsolidationRunSummary`, `ConsolidationJob` invariants.
5. `evaluate_policy` table-driven over 7 paths.
6. Purity regression (inputs not mutated).
7. Determinism regression (same inputs → same output).
8. Anti-LLM source-token grep over the new module.
"""

from __future__ import annotations

import copy
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.models.namespace import MemoryNamespace
from sophiagraph.models.record import MemoryRecord
from sophiagraph.storage.lifecycle_policy import (
    ConsolidationJob,
    ConsolidationRunSummary,
    LifecycleDecision,
    LifecyclePhase,
    LifecyclePolicy,
    PromotionPredicate,
    PromotionPredicateKind,
    derive_default_policy,
    evaluate_policy,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_record(
    *,
    updated_at: str,
    created_at: str | None = None,
    access_count: int = 0,
    event_time: str | None = None,
    meta: dict | None = None,
    valid_to: str | None = None,
    superseded_by_id: str | None = None,
    namespace: MemoryNamespace | None = None,
) -> MemoryRecord:
    return MemoryRecord(
        id="rec-1",
        scope="session:sess-1",
        type="fact",
        content="x",
        created_at=created_at or updated_at,
        updated_at=updated_at,
        access_count=access_count,
        event_time=event_time,
        meta=meta or {},
        valid_to=valid_to,
        superseded_by_id=superseded_by_id,
        namespace=namespace,
    )


def _policy(
    *,
    ttl_active_iso: str | None = None,
    ttl_cooling_iso: str | None = None,
    predicates: tuple[PromotionPredicate, ...] = (),
    namespace: MemoryNamespace | None = None,
) -> LifecyclePolicy:
    return LifecyclePolicy(
        policy_id="p-1",
        namespace_filter=namespace or MemoryNamespace(session_id="sess-1"),
        created_at_iso="2026-05-28T00:00:00+00:00",
        ttl_active_iso=ttl_active_iso,
        ttl_cooling_iso=ttl_cooling_iso,
        promotion_predicates=predicates,
    )


def _iso(dt: datetime) -> str:
    return dt.isoformat()


# ---------------------------------------------------------------------------
# 1. Enum closure (membership-pin)
# ---------------------------------------------------------------------------


def test_lifecycle_phase_is_exact_four_members() -> None:
    assert {p.value for p in LifecyclePhase} == {
        "active",
        "cooling",
        "archived",
        "superseded",
    }


def test_promotion_predicate_kind_is_exact_four_members() -> None:
    assert {k.value for k in PromotionPredicateKind} == {
        "access_count_above_threshold",
        "tier_transition_count_above_threshold",
        "event_time_within_window",
        "namespace_dimension_match",
    }


# ---------------------------------------------------------------------------
# 2. PromotionPredicate cross-field invariants
# ---------------------------------------------------------------------------


def test_predicate_access_count_requires_threshold() -> None:
    PromotionPredicate(
        kind=PromotionPredicateKind.ACCESS_COUNT_ABOVE_THRESHOLD,
        threshold=3,
    )
    with pytest.raises(InvalidArgumentError):
        PromotionPredicate(kind=PromotionPredicateKind.ACCESS_COUNT_ABOVE_THRESHOLD)
    with pytest.raises(InvalidArgumentError):
        PromotionPredicate(
            kind=PromotionPredicateKind.ACCESS_COUNT_ABOVE_THRESHOLD,
            threshold=-1,
        )
    with pytest.raises(InvalidArgumentError):
        PromotionPredicate(
            kind=PromotionPredicateKind.ACCESS_COUNT_ABOVE_THRESHOLD,
            threshold=1,
            window_iso="P1D",
        )


def test_predicate_tier_transition_requires_threshold_only() -> None:
    PromotionPredicate(
        kind=PromotionPredicateKind.TIER_TRANSITION_COUNT_ABOVE_THRESHOLD,
        threshold=2,
    )
    with pytest.raises(InvalidArgumentError):
        PromotionPredicate(
            kind=PromotionPredicateKind.TIER_TRANSITION_COUNT_ABOVE_THRESHOLD,
            threshold=1,
            namespace_dimension="agent_id",
            namespace_dimension_value="a",
        )


def test_predicate_event_time_requires_window_iso() -> None:
    PromotionPredicate(
        kind=PromotionPredicateKind.EVENT_TIME_WITHIN_WINDOW,
        window_iso="P7D",
    )
    with pytest.raises(InvalidArgumentError):
        PromotionPredicate(kind=PromotionPredicateKind.EVENT_TIME_WITHIN_WINDOW)
    with pytest.raises(InvalidArgumentError):
        PromotionPredicate(
            kind=PromotionPredicateKind.EVENT_TIME_WITHIN_WINDOW,
            window_iso="P7D",
            threshold=3,
        )
    with pytest.raises(InvalidArgumentError):
        PromotionPredicate(
            kind=PromotionPredicateKind.EVENT_TIME_WITHIN_WINDOW,
            window_iso="garbage",
        )


def test_predicate_namespace_dimension_requires_pair() -> None:
    PromotionPredicate(
        kind=PromotionPredicateKind.NAMESPACE_DIMENSION_MATCH,
        namespace_dimension="agent_id",
        namespace_dimension_value="agent-a",
    )
    with pytest.raises(InvalidArgumentError):
        PromotionPredicate(
            kind=PromotionPredicateKind.NAMESPACE_DIMENSION_MATCH,
            namespace_dimension="agent_id",
        )
    with pytest.raises(InvalidArgumentError):
        PromotionPredicate(
            kind=PromotionPredicateKind.NAMESPACE_DIMENSION_MATCH,
            namespace_dimension="agent_id",
            namespace_dimension_value="agent-a",
            threshold=1,
        )


def test_predicate_rejects_non_enum_kind() -> None:
    with pytest.raises(InvalidArgumentError):
        PromotionPredicate(kind="access_count_above_threshold", threshold=1)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 3. LifecyclePolicy invariants
# ---------------------------------------------------------------------------


def test_policy_requires_non_empty_policy_id() -> None:
    with pytest.raises(InvalidArgumentError):
        LifecyclePolicy(
            policy_id="",
            namespace_filter=MemoryNamespace(session_id="s"),
            created_at_iso="2026-05-28T00:00:00+00:00",
        )


def test_policy_requires_memory_namespace_instance() -> None:
    with pytest.raises(InvalidArgumentError):
        LifecyclePolicy(
            policy_id="p",
            namespace_filter={"session_id": "s"},  # type: ignore[arg-type]
            created_at_iso="2026-05-28T00:00:00+00:00",
        )


def test_policy_validates_iso_duration_fields() -> None:
    LifecyclePolicy(
        policy_id="p",
        namespace_filter=MemoryNamespace(session_id="s"),
        created_at_iso="2026-05-28T00:00:00+00:00",
        ttl_active_iso="P30D",
        ttl_cooling_iso="P7D",
    )
    with pytest.raises(InvalidArgumentError):
        LifecyclePolicy(
            policy_id="p",
            namespace_filter=MemoryNamespace(session_id="s"),
            created_at_iso="2026-05-28T00:00:00+00:00",
            ttl_active_iso="garbage",
        )


def test_policy_promotion_predicates_must_be_tuple_of_predicates() -> None:
    with pytest.raises(InvalidArgumentError):
        LifecyclePolicy(
            policy_id="p",
            namespace_filter=MemoryNamespace(session_id="s"),
            created_at_iso="2026-05-28T00:00:00+00:00",
            promotion_predicates=[  # type: ignore[arg-type]
                PromotionPredicate(
                    kind=PromotionPredicateKind.ACCESS_COUNT_ABOVE_THRESHOLD,
                    threshold=1,
                )
            ],
        )


# ---------------------------------------------------------------------------
# 4. LifecycleDecision + ConsolidationRunSummary + ConsolidationJob
# ---------------------------------------------------------------------------


def test_decision_promotion_reason_requires_matched_kind() -> None:
    with pytest.raises(InvalidArgumentError):
        LifecycleDecision(
            current_phase=LifecyclePhase.COOLING,
            next_phase=LifecyclePhase.ACTIVE,
            transition_reason="promotion_predicate_matched",
        )


def test_decision_matched_kind_requires_promotion_reason() -> None:
    with pytest.raises(InvalidArgumentError):
        LifecycleDecision(
            current_phase=LifecyclePhase.ACTIVE,
            next_phase=LifecyclePhase.ACTIVE,
            transition_reason="no_transition",
            matched_predicate_kind=PromotionPredicateKind.ACCESS_COUNT_ABOVE_THRESHOLD,
        )


def test_decision_rejects_unknown_transition_reason() -> None:
    with pytest.raises(InvalidArgumentError):
        LifecycleDecision(
            current_phase=LifecyclePhase.ACTIVE,
            next_phase=LifecyclePhase.ACTIVE,
            transition_reason="oh_no",  # type: ignore[arg-type]
        )


def test_run_summary_rejects_negative_counts() -> None:
    ConsolidationRunSummary(
        records_examined=1,
        records_transitioned=0,
        transition_counts={},
        completed_at_iso="2026-05-28T00:00:00+00:00",
    )
    with pytest.raises(InvalidArgumentError):
        ConsolidationRunSummary(
            records_examined=-1,
            records_transitioned=0,
            transition_counts={},
            completed_at_iso="2026-05-28T00:00:00+00:00",
        )
    with pytest.raises(InvalidArgumentError):
        ConsolidationRunSummary(
            records_examined=1,
            records_transitioned=0,
            transition_counts={"weird": 1},
            completed_at_iso="2026-05-28T00:00:00+00:00",
        )


def test_consolidation_job_requires_non_empty_strings() -> None:
    policy = _policy()
    ConsolidationJob(
        job_id="j",
        policy=policy,
        schedule_spec="@daily",
        next_run_at_iso="2026-05-29T00:00:00+00:00",
    )
    with pytest.raises(InvalidArgumentError):
        ConsolidationJob(
            job_id="",
            policy=policy,
            schedule_spec="@daily",
            next_run_at_iso="2026-05-29T00:00:00+00:00",
        )
    with pytest.raises(InvalidArgumentError):
        ConsolidationJob(
            job_id="j",
            policy=policy,
            schedule_spec="",
            next_run_at_iso="2026-05-29T00:00:00+00:00",
        )


# ---------------------------------------------------------------------------
# 5. evaluate_policy — table-driven over 7 paths
# ---------------------------------------------------------------------------


NOW = datetime(2026, 5, 28, 12, 0, 0, tzinfo=timezone.utc)


def test_evaluate_active_no_ttl_yields_no_transition() -> None:
    record = _make_record(updated_at=_iso(NOW - timedelta(days=100)))
    policy = _policy()
    decision = evaluate_policy(record, policy, _iso(NOW))
    assert decision.current_phase == LifecyclePhase.ACTIVE
    assert decision.next_phase == LifecyclePhase.ACTIVE
    assert decision.transition_reason == "no_transition"


def test_evaluate_ttl_active_elapsed_to_cooling_when_cooling_ttl_set() -> None:
    record = _make_record(updated_at=_iso(NOW - timedelta(days=40)))
    policy = _policy(ttl_active_iso="P30D", ttl_cooling_iso="P7D")
    decision = evaluate_policy(record, policy, _iso(NOW))
    assert decision.next_phase == LifecyclePhase.COOLING
    assert decision.transition_reason == "ttl_active_elapsed"


def test_evaluate_ttl_active_elapsed_direct_to_archived_when_no_cooling_ttl() -> None:
    record = _make_record(updated_at=_iso(NOW - timedelta(days=40)))
    policy = _policy(ttl_active_iso="P30D", ttl_cooling_iso=None)
    decision = evaluate_policy(record, policy, _iso(NOW))
    assert decision.next_phase == LifecyclePhase.ARCHIVED
    assert decision.transition_reason == "ttl_active_elapsed"


def test_evaluate_ttl_cooling_elapsed_to_archived() -> None:
    # Cooling record (phase via meta) updated 40 days ago; ttl_active P30D + ttl_cooling P7D = 37D total
    record = _make_record(
        updated_at=_iso(NOW - timedelta(days=40)),
        meta={"lifecycle_phase": "cooling"},
    )
    policy = _policy(ttl_active_iso="P30D", ttl_cooling_iso="P7D")
    decision = evaluate_policy(record, policy, _iso(NOW))
    assert decision.current_phase == LifecyclePhase.COOLING
    assert decision.next_phase == LifecyclePhase.ARCHIVED
    assert decision.transition_reason == "ttl_cooling_elapsed"


def test_evaluate_promotion_predicate_match_cooling_to_active() -> None:
    record = _make_record(
        updated_at=_iso(NOW - timedelta(days=32)),
        access_count=10,
        meta={"lifecycle_phase": "cooling"},
    )
    predicates = (
        PromotionPredicate(
            kind=PromotionPredicateKind.ACCESS_COUNT_ABOVE_THRESHOLD,
            threshold=5,
        ),
    )
    policy = _policy(
        ttl_active_iso="P30D", ttl_cooling_iso="P7D", predicates=predicates
    )
    decision = evaluate_policy(record, policy, _iso(NOW))
    assert decision.current_phase == LifecyclePhase.COOLING
    assert decision.next_phase == LifecyclePhase.ACTIVE
    assert decision.transition_reason == "promotion_predicate_matched"
    assert (
        decision.matched_predicate_kind
        == PromotionPredicateKind.ACCESS_COUNT_ABOVE_THRESHOLD
    )


def test_evaluate_promotion_predicate_no_match_no_transition() -> None:
    record = _make_record(
        updated_at=_iso(NOW - timedelta(days=32)),
        access_count=1,
        meta={"lifecycle_phase": "cooling"},
    )
    predicates = (
        PromotionPredicate(
            kind=PromotionPredicateKind.ACCESS_COUNT_ABOVE_THRESHOLD,
            threshold=5,
        ),
    )
    policy = _policy(
        ttl_active_iso="P30D", ttl_cooling_iso="P7D", predicates=predicates
    )
    decision = evaluate_policy(record, policy, _iso(NOW))
    assert decision.current_phase == LifecyclePhase.COOLING
    assert decision.next_phase == LifecyclePhase.COOLING
    assert decision.transition_reason == "no_transition"


def test_evaluate_archived_is_terminal() -> None:
    record = _make_record(
        updated_at=_iso(NOW - timedelta(days=100)),
        valid_to=_iso(NOW - timedelta(days=10)),
    )
    policy = _policy(ttl_active_iso="P1D")
    decision = evaluate_policy(record, policy, _iso(NOW))
    assert decision.current_phase == LifecyclePhase.ARCHIVED
    assert decision.next_phase == LifecyclePhase.ARCHIVED
    assert decision.transition_reason == "no_transition"


def test_evaluate_superseded_is_terminal() -> None:
    record = _make_record(
        updated_at=_iso(NOW - timedelta(days=100)),
        superseded_by_id="rec-2",
    )
    policy = _policy(ttl_active_iso="P1D")
    decision = evaluate_policy(record, policy, _iso(NOW))
    assert decision.current_phase == LifecyclePhase.SUPERSEDED
    assert decision.next_phase == LifecyclePhase.SUPERSEDED
    assert decision.transition_reason == "no_transition"


def test_evaluate_event_time_within_window_predicate() -> None:
    record = _make_record(
        updated_at=_iso(NOW - timedelta(days=32)),
        event_time=_iso(NOW - timedelta(days=2)),
        meta={"lifecycle_phase": "cooling"},
    )
    predicates = (
        PromotionPredicate(
            kind=PromotionPredicateKind.EVENT_TIME_WITHIN_WINDOW,
            window_iso="P7D",
        ),
    )
    policy = _policy(
        ttl_active_iso="P30D", ttl_cooling_iso="P30D", predicates=predicates
    )
    decision = evaluate_policy(record, policy, _iso(NOW))
    assert decision.next_phase == LifecyclePhase.ACTIVE
    assert (
        decision.matched_predicate_kind
        == PromotionPredicateKind.EVENT_TIME_WITHIN_WINDOW
    )


def test_evaluate_namespace_dimension_match_predicate() -> None:
    namespace = MemoryNamespace(agent_id="agent-a", session_id="sess-1")
    record = _make_record(
        updated_at=_iso(NOW - timedelta(days=32)),
        namespace=namespace,
        meta={"lifecycle_phase": "cooling"},
    )
    predicates = (
        PromotionPredicate(
            kind=PromotionPredicateKind.NAMESPACE_DIMENSION_MATCH,
            namespace_dimension="agent_id",
            namespace_dimension_value="agent-a",
        ),
    )
    policy = _policy(
        ttl_active_iso="P30D",
        ttl_cooling_iso="P30D",
        predicates=predicates,
        namespace=namespace,
    )
    decision = evaluate_policy(record, policy, _iso(NOW))
    assert decision.next_phase == LifecyclePhase.ACTIVE


def test_evaluate_tier_transition_predicate_reads_meta_key() -> None:
    record = _make_record(
        updated_at=_iso(NOW - timedelta(days=32)),
        meta={"lifecycle_phase": "cooling", "tier_transition_count": 5},
    )
    predicates = (
        PromotionPredicate(
            kind=PromotionPredicateKind.TIER_TRANSITION_COUNT_ABOVE_THRESHOLD,
            threshold=3,
        ),
    )
    policy = _policy(
        ttl_active_iso="P30D", ttl_cooling_iso="P30D", predicates=predicates
    )
    decision = evaluate_policy(record, policy, _iso(NOW))
    assert decision.next_phase == LifecyclePhase.ACTIVE


# ---------------------------------------------------------------------------
# 6. Purity regression
# ---------------------------------------------------------------------------


def test_evaluate_policy_does_not_mutate_record() -> None:
    record = _make_record(
        updated_at=_iso(NOW - timedelta(days=40)),
        access_count=3,
        meta={"lifecycle_phase": "cooling", "tier_transition_count": 2},
    )
    snapshot_meta = copy.deepcopy(record.meta)
    snapshot_access_count = record.access_count
    snapshot_updated_at = record.updated_at
    policy = _policy(ttl_active_iso="P30D", ttl_cooling_iso="P7D")
    evaluate_policy(record, policy, _iso(NOW))
    assert record.meta == snapshot_meta
    assert record.access_count == snapshot_access_count
    assert record.updated_at == snapshot_updated_at


def test_evaluate_policy_does_not_mutate_policy() -> None:
    record = _make_record(updated_at=_iso(NOW - timedelta(days=40)))
    policy = _policy(ttl_active_iso="P30D", ttl_cooling_iso="P7D")
    snapshot_predicates = policy.promotion_predicates
    snapshot_ttl_active = policy.ttl_active_iso
    evaluate_policy(record, policy, _iso(NOW))
    assert policy.promotion_predicates is snapshot_predicates
    assert policy.ttl_active_iso == snapshot_ttl_active


# ---------------------------------------------------------------------------
# 7. Determinism regression
# ---------------------------------------------------------------------------


def test_evaluate_policy_is_deterministic() -> None:
    record = _make_record(updated_at=_iso(NOW - timedelta(days=40)))
    policy = _policy(ttl_active_iso="P30D", ttl_cooling_iso="P7D")
    a = evaluate_policy(record, policy, _iso(NOW))
    b = evaluate_policy(record, policy, _iso(NOW))
    assert a == b


# ---------------------------------------------------------------------------
# 8. derive_default_policy
# ---------------------------------------------------------------------------


def test_derive_default_policy_returns_typed_policy() -> None:
    namespace = MemoryNamespace(session_id="s1")
    policy = derive_default_policy(namespace, ttl_active_iso="P30D")
    assert isinstance(policy, LifecyclePolicy)
    assert policy.namespace_filter == namespace
    assert policy.ttl_active_iso == "P30D"
    assert policy.ttl_cooling_iso is None
    assert policy.promotion_predicates == ()
    assert policy.policy_id.startswith("default:")


def test_derive_default_policy_rejects_non_namespace() -> None:
    with pytest.raises(InvalidArgumentError):
        derive_default_policy({"session_id": "s1"})  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 9. Anti-LLM source-token regression
# ---------------------------------------------------------------------------


def test_lifecycle_policy_module_contains_no_llm_call_tokens() -> None:
    module_path = (
        Path(__file__).parent.parent
        / "src"
        / "sophiagraph"
        / "storage"
        / "lifecycle_policy.py"
    )
    source = module_path.read_text(encoding="utf-8")
    banned = [
        r"\bcomplete\(",
        r"\bllm_call\b",
        r"\bllm_complete\b",
        r"\bllm\.complete\b",
        r"\bopenai\b",
        r"\banthropic\b",
        r"\bChatCompletion\b",
        r"\bClaude\b",
        r"\bsummarize\(",
        r"\bclassify\(",
    ]
    for pattern in banned:
        assert re.search(pattern, source) is None, (
            f"banned LLM-call token {pattern!r} found in lifecycle_policy.py"
        )
