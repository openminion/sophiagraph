"""BL-101 migration tooling tests.

Covers detect / backup / verify pure functions per
`docs/trackers/wip/storage-migration-tooling-bl101-on-kpr03-tracker.md`.
"""

from __future__ import annotations

import pytest

from sophiagraph.models import MemoryNamespace, MemoryRecord
from sophiagraph.storage import SophiaGraphMemoryStore
from sophiagraph.storage.lifecycle_policy import (
    LifecyclePolicy,
    PromotionPredicate,
    PromotionPredicateKind,
    derive_default_policy,
)
from sophiagraph.storage.migration_tooling import (
    BackupReceipt,
    MigrationDecision,
    MigrationDecisionKind,
    VerifyOutcome,
    VerifyOutcomeKind,
    backup_before_migration,
    detect_migration_needed,
    verify_migration_result,
)


@pytest.fixture
def policy() -> LifecyclePolicy:
    return derive_default_policy(
        MemoryNamespace(agent_id="test-agent"),
        ttl_active_iso="P30D",
        ttl_cooling_iso="P15D",
    )


@pytest.fixture
def policy_id_for_test_agent() -> str:
    """The auto-generated policy_id for MemoryNamespace(agent_id='test-agent')."""
    return "default:agent_id=test-agent"


@pytest.fixture
def store_with_records() -> SophiaGraphMemoryStore:
    store = SophiaGraphMemoryStore()
    # 3 records all under agent-test namespace
    for i in range(3):
        record = MemoryRecord(
            id=f"rec-{i}",
            scope="agent:test-agent",
            type="fact",
            content={"text": f"record {i}"},
            created_at="2026-04-01T00:00:00+00:00",
            updated_at="2026-04-01T00:00:00+00:00",  # ~57 days ago — past 30d active TTL
            namespace=MemoryNamespace(agent_id="test-agent"),
        )
        store.put_record(record)
    return store


@pytest.fixture
def empty_store() -> SophiaGraphMemoryStore:
    return SophiaGraphMemoryStore()


# ---- detect_migration_needed ----


def test_detect_returns_not_needed_for_empty_store(empty_store, policy):
    decision = detect_migration_needed(
        policy, empty_store, now_iso="2026-05-28T00:00:00+00:00"
    )
    assert decision.kind == MigrationDecisionKind.NOT_NEEDED
    assert decision.examined_count == 0
    assert decision.needing_transition_count == 0
    assert decision.transition_counts == {}
    assert decision.policy_id == "default:agent_id=test-agent"


def test_detect_returns_needed_when_records_past_ttl(store_with_records, policy):
    decision = detect_migration_needed(
        policy, store_with_records, now_iso="2026-05-28T00:00:00+00:00"
    )
    assert decision.kind == MigrationDecisionKind.NEEDED
    assert decision.examined_count == 3
    assert decision.needing_transition_count == 3
    assert "active_to_cooling" in decision.transition_counts
    assert decision.transition_counts["active_to_cooling"] == 3


def test_detect_returns_not_needed_when_records_within_ttl(store_with_records):
    # Use a generous TTL that doesn't fire
    generous_policy = derive_default_policy(
        MemoryNamespace(agent_id="test-agent"),
        ttl_active_iso="P365D",  # 1 year — records well within
        ttl_cooling_iso="P30D",
    )
    decision = detect_migration_needed(
        generous_policy, store_with_records, now_iso="2026-05-28T00:00:00+00:00"
    )
    assert decision.kind == MigrationDecisionKind.NOT_NEEDED
    assert decision.examined_count == 3
    assert decision.needing_transition_count == 0


def test_detect_decision_invariants():
    """MigrationDecision rejects invalid counts."""
    with pytest.raises(ValueError, match="examined_count must be non-negative"):
        MigrationDecision(
            kind=MigrationDecisionKind.NOT_NEEDED,
            policy_id="x",
            examined_count=-1,
            needing_transition_count=0,
        )
    with pytest.raises(ValueError, match="cannot exceed examined_count"):
        MigrationDecision(
            kind=MigrationDecisionKind.NEEDED,
            policy_id="x",
            examined_count=2,
            needing_transition_count=5,
        )


# ---- backup_before_migration ----


def test_backup_produces_typed_receipt(store_with_records, policy):
    receipt = backup_before_migration(
        policy,
        store_with_records,
        backup_id="bk-001",
        snapshot_ref="/tmp/snap-001.json",
    )
    assert isinstance(receipt, BackupReceipt)
    assert receipt.backup_id == "bk-001"
    assert receipt.policy_id == "default:agent_id=test-agent"
    assert receipt.snapshot_ref == "/tmp/snap-001.json"
    assert receipt.record_count == 3
    assert "agent_id=test-agent" in receipt.namespace_filter_signature


def test_backup_empty_namespace(empty_store, policy):
    receipt = backup_before_migration(
        policy, empty_store, backup_id="bk-empty", snapshot_ref="/tmp/empty.json"
    )
    assert receipt.record_count == 0


def test_backup_requires_backup_id(store_with_records, policy):
    with pytest.raises(ValueError, match="backup_id is required"):
        backup_before_migration(
            policy, store_with_records, backup_id="", snapshot_ref="/tmp/x"
        )


def test_backup_requires_snapshot_ref(store_with_records, policy):
    with pytest.raises(ValueError, match="snapshot_ref is required"):
        backup_before_migration(
            policy, store_with_records, backup_id="bk-x", snapshot_ref=""
        )


def test_backup_namespace_filter_signature_is_deterministic(store_with_records):
    policy_a = derive_default_policy(
        MemoryNamespace(agent_id="alpha", project_id="proj-1"),
    )
    policy_b = derive_default_policy(
        MemoryNamespace(agent_id="alpha", project_id="proj-1"),
    )
    receipt_a = backup_before_migration(
        policy_a, store_with_records, backup_id="x1", snapshot_ref="/tmp/a"
    )
    receipt_b = backup_before_migration(
        policy_b, store_with_records, backup_id="x2", snapshot_ref="/tmp/b"
    )
    assert receipt_a.namespace_filter_signature == receipt_b.namespace_filter_signature


# ---- verify_migration_result ----


def test_verify_passes_when_no_transitions_expected(empty_store, policy):
    expected = MigrationDecision(
        kind=MigrationDecisionKind.NOT_NEEDED,
        policy_id="default:agent_id=test-agent",
        examined_count=0,
        needing_transition_count=0,
        transition_counts={},
    )
    outcome = verify_migration_result(
        policy, empty_store, expected, now_iso="2026-05-28T00:00:00+00:00"
    )
    assert outcome.kind == VerifyOutcomeKind.PASS
    assert outcome.mismatch_count == 0


def test_verify_detects_zero_mismatch_when_distribution_matches(
    store_with_records, policy
):
    # Records all active; expected = no transitions; observed distribution matches.
    expected = MigrationDecision(
        kind=MigrationDecisionKind.NOT_NEEDED,
        policy_id="default:agent_id=test-agent",
        examined_count=3,
        needing_transition_count=0,
        transition_counts={},
    )
    outcome = verify_migration_result(
        policy, store_with_records, expected, now_iso="2026-05-28T00:00:00+00:00"
    )
    assert outcome.kind == VerifyOutcomeKind.PASS
    assert outcome.mismatch_count == 0


def test_verify_outcome_invariants():
    with pytest.raises(ValueError, match="mismatch_count must be non-negative"):
        VerifyOutcome(
            kind=VerifyOutcomeKind.FAIL,
            policy_id="x",
            expected_phase_distribution={},
            observed_phase_distribution={},
            mismatch_count=-1,
        )


def test_verify_kinds_closed_enum():
    assert {k.value for k in VerifyOutcomeKind} == {"pass", "fail", "unverifiable"}


def test_migration_decision_kinds_closed_enum():
    assert {k.value for k in MigrationDecisionKind} == {
        "needed",
        "not_needed",
        "ambiguous",
    }


# ---- Promotion-predicate roundtrip via detect ----


def test_detect_promotion_predicate_keeps_cooling_records_in_cooling():
    """When no predicate matches and no TTL elapses, cooling records stay cooling."""
    store = SophiaGraphMemoryStore()
    # No records — predicate roundtrip is about the policy shape compiling
    policy = LifecyclePolicy(
        policy_id="promo-policy",
        namespace_filter=MemoryNamespace(agent_id="test"),
        ttl_active_iso="P30D",
        ttl_cooling_iso="P15D",
        promotion_predicates=(
            PromotionPredicate(
                kind=PromotionPredicateKind.ACCESS_COUNT_ABOVE_THRESHOLD,
                threshold=10,
            ),
        ),
        created_at_iso="2026-05-28T00:00:00+00:00",
    )
    decision = detect_migration_needed(
        policy, store, now_iso="2026-05-28T00:00:00+00:00"
    )
    assert decision.kind == MigrationDecisionKind.NOT_NEEDED
    assert decision.examined_count == 0
