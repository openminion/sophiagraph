"""Structural detect, backup, and verify helpers for lifecycle migrations."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

from sophiagraph.query import ListQueryOptions
from sophiagraph.storage.lifecycle_policy import (
    LifecyclePhase,
    LifecyclePolicy,
    evaluate_policy,
)
from sophiagraph.temporal import utc_now_iso

if TYPE_CHECKING:
    from sophiagraph.storage.base import SophiaGraphStore


__all__ = [
    "MigrationDecisionKind",
    "MigrationDecision",
    "BackupReceipt",
    "VerifyOutcomeKind",
    "VerifyOutcome",
    "detect_migration_needed",
    "backup_before_migration",
    "verify_migration_result",
]


class MigrationDecisionKind(StrEnum):
    """Closed migration decision enum."""

    NEEDED = "needed"
    NOT_NEEDED = "not_needed"
    AMBIGUOUS = "ambiguous"


class VerifyOutcomeKind(StrEnum):
    """Closed verification outcome enum."""

    PASS = "pass"
    FAIL = "fail"
    UNVERIFIABLE = "unverifiable"


@dataclass(frozen=True)
class MigrationDecision:
    """Typed result of `detect_migration_needed`."""

    kind: MigrationDecisionKind
    policy_id: str
    examined_count: int
    needing_transition_count: int
    transition_counts: dict[str, int] = field(default_factory=dict)
    """Counts keyed by `<current>_to_<next>` (e.g., `active_to_cooling`)."""
    evaluated_at_iso: str = ""

    def __post_init__(self) -> None:
        if self.examined_count < 0:
            raise ValueError("examined_count must be non-negative")
        if self.needing_transition_count < 0:
            raise ValueError("needing_transition_count must be non-negative")
        if self.needing_transition_count > self.examined_count:
            raise ValueError("needing_transition_count cannot exceed examined_count")


@dataclass(frozen=True)
class BackupReceipt:
    """Typed metadata about a backup snapshot. No inline payload."""

    backup_id: str
    policy_id: str
    namespace_filter_signature: str
    """Stable structural signature of the namespace filter for audit."""
    record_count: int
    snapshot_ref: str
    """Operator-supplied reference to the persisted snapshot (path / URL /
    storage handle). The snapshot payload itself is NOT inlined."""
    created_at_iso: str

    def __post_init__(self) -> None:
        if self.record_count < 0:
            raise ValueError("record_count must be non-negative")
        if not self.backup_id:
            raise ValueError("backup_id is required")
        if not self.policy_id:
            raise ValueError("policy_id is required")


@dataclass(frozen=True)
class VerifyOutcome:
    """Typed diff result of `verify_migration_result`."""

    kind: VerifyOutcomeKind
    policy_id: str
    expected_phase_distribution: dict[str, int]
    observed_phase_distribution: dict[str, int]
    mismatch_count: int
    verified_at_iso: str = ""

    def __post_init__(self) -> None:
        if self.mismatch_count < 0:
            raise ValueError("mismatch_count must be non-negative")


def _namespace_filter_signature(policy: LifecyclePolicy) -> str:
    """Return a deterministic signature of the policy namespace filter."""
    ns = policy.namespace_filter
    parts = []
    for key in (
        "tenant_id",
        "org_id",
        "user_id",
        "agent_id",
        "session_id",
        "conversation_id",
        "project_id",
        "graph_id",
    ):
        value = getattr(ns, key, None)
        if value:
            parts.append(f"{key}={value}")
    return "|".join(parts) if parts else "empty"


def _derive_scopes_for_namespace(namespace) -> list[str]:
    """Derive candidate legacy scope strings for a namespace filter."""
    scopes: list[str] = []
    if getattr(namespace, "agent_id", None):
        scopes.append(f"agent:{namespace.agent_id}")
    if getattr(namespace, "session_id", None):
        scopes.append(f"session:{namespace.session_id}")
    if getattr(namespace, "project_id", None):
        scopes.append(f"project:{namespace.project_id}")
    if getattr(namespace, "graph_id", None):
        scopes.append(f"global:{namespace.graph_id}")
    return scopes


def _list_records_for_policy(
    policy: LifecyclePolicy,
    store: "SophiaGraphStore",
) -> list:
    """List records matching the policy namespace filter."""
    scopes = _derive_scopes_for_namespace(policy.namespace_filter)
    if not scopes:
        # No scope-bridgeable dimension on the filter — nothing to list
        return []
    options = ListQueryOptions(
        scopes=scopes,
        namespaces=[policy.namespace_filter],
        include_invalidated=False,
    )
    return list(store.list_records(options))


def _compute_phase_distribution(records: list) -> dict[str, int]:
    """Tally records by current phase (closed-enum keys)."""
    distribution: dict[str, int] = {phase.value: 0 for phase in LifecyclePhase}
    for record in records:
        phase = getattr(record, "phase", None) or LifecyclePhase.ACTIVE.value
        phase_str = str(phase)
        distribution[phase_str] = distribution.get(phase_str, 0) + 1
    return distribution


def detect_migration_needed(
    policy: LifecyclePolicy,
    store: "SophiaGraphStore",
    *,
    now_iso: str | None = None,
) -> MigrationDecision:
    """Detect whether records under ``policy`` need phase transitions."""
    evaluation_time = now_iso or utc_now_iso()
    try:
        records = _list_records_for_policy(policy, store)
    except Exception:
        return MigrationDecision(
            kind=MigrationDecisionKind.AMBIGUOUS,
            policy_id=policy.policy_id,
            examined_count=0,
            needing_transition_count=0,
            transition_counts={},
            evaluated_at_iso=evaluation_time,
        )

    transition_counts: dict[str, int] = {}
    needing = 0
    ambiguous = False
    for record in records:
        try:
            decision = evaluate_policy(record, policy, evaluation_time)
        except Exception:
            ambiguous = True
            continue
        if decision.next_phase != decision.current_phase:
            needing += 1
            key = f"{decision.current_phase.value}_to_{decision.next_phase.value}"
            transition_counts[key] = transition_counts.get(key, 0) + 1

    if ambiguous and needing == 0:
        kind = MigrationDecisionKind.AMBIGUOUS
    elif needing > 0:
        kind = MigrationDecisionKind.NEEDED
    else:
        kind = MigrationDecisionKind.NOT_NEEDED

    return MigrationDecision(
        kind=kind,
        policy_id=policy.policy_id,
        examined_count=len(records),
        needing_transition_count=needing,
        transition_counts=transition_counts,
        evaluated_at_iso=evaluation_time,
    )


def backup_before_migration(
    policy: LifecyclePolicy,
    store: "SophiaGraphStore",
    *,
    backup_id: str,
    snapshot_ref: str,
) -> BackupReceipt:
    """Produce a typed backup receipt for the policy namespace."""
    if not backup_id:
        raise ValueError("backup_id is required")
    if not snapshot_ref:
        raise ValueError("snapshot_ref is required")
    records = _list_records_for_policy(policy, store)
    return BackupReceipt(
        backup_id=backup_id,
        policy_id=policy.policy_id,
        namespace_filter_signature=_namespace_filter_signature(policy),
        record_count=len(records),
        snapshot_ref=snapshot_ref,
        created_at_iso=utc_now_iso(),
    )


def verify_migration_result(
    policy: LifecyclePolicy,
    store: "SophiaGraphStore",
    expected_decision: MigrationDecision,
    *,
    now_iso: str | None = None,
) -> VerifyOutcome:
    """Verify post-migration phase distribution structurally."""
    evaluation_time = now_iso or utc_now_iso()
    try:
        records = _list_records_for_policy(policy, store)
    except Exception:
        return VerifyOutcome(
            kind=VerifyOutcomeKind.UNVERIFIABLE,
            policy_id=policy.policy_id,
            expected_phase_distribution={},
            observed_phase_distribution={},
            mismatch_count=0,
            verified_at_iso=evaluation_time,
        )

    observed = _compute_phase_distribution(records)

    # Compute expected post-migration distribution: start from a pre-migration
    # snapshot derived from the expected decision's transitions.
    pre_migration = dict(observed)
    for transition_key, count in expected_decision.transition_counts.items():
        from_phase, _, to_phase = transition_key.partition("_to_")
        if from_phase and to_phase:
            # Add back the count to the from-phase (pre-migration state)
            pre_migration[from_phase] = pre_migration.get(from_phase, 0) + count
            pre_migration[to_phase] = pre_migration.get(to_phase, 0) - count

    expected_distribution = dict(pre_migration)
    for transition_key, count in expected_decision.transition_counts.items():
        from_phase, _, to_phase = transition_key.partition("_to_")
        if from_phase and to_phase:
            expected_distribution[from_phase] = (
                expected_distribution.get(from_phase, 0) - count
            )
            expected_distribution[to_phase] = (
                expected_distribution.get(to_phase, 0) + count
            )

    # Compute mismatch: sum of absolute differences across phases
    all_phases = set(observed) | set(expected_distribution)
    mismatch = sum(
        abs(observed.get(phase, 0) - expected_distribution.get(phase, 0))
        for phase in all_phases
    )

    if mismatch == 0:
        kind = VerifyOutcomeKind.PASS
    else:
        kind = VerifyOutcomeKind.FAIL

    return VerifyOutcome(
        kind=kind,
        policy_id=policy.policy_id,
        expected_phase_distribution=expected_distribution,
        observed_phase_distribution=observed,
        mismatch_count=mismatch,
        verified_at_iso=evaluation_time,
    )
