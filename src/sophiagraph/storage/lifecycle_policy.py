"""KPR-03 typed surface: background-consolidation lifecycle policy contracts.

This module ships the 9 typed symbols declared by the KPR-03 design spec
(`docs/specs/sophiagraph-background-consolidation-lifecycle-spec.md`) and
the implementation-discipline companion spec
(`docs/specs/sophiagraph-kpr-03-typed-surface-spec.md`):

1. `LifecyclePhase` (StrEnum)
2. `PromotionPredicateKind` (StrEnum)
3. `PromotionPredicate` (frozen dataclass)
4. `LifecyclePolicy` (frozen dataclass)
5. `LifecycleDecision` (frozen dataclass)
6. `ConsolidationRunSummary` (frozen dataclass)
7. `ConsolidationJob` (frozen dataclass)
8. `evaluate_policy` (pure function)
9. `derive_default_policy` (structural helper)

Typing mechanism: `@dataclass(frozen=True)` with manual `__post_init__`
validation. This diverges from the parent spec wording ("Pydantic v2
BaseModel") to preserve sophiagraph's `dependencies = []` posture and
match the KPR-02 `MemoryNamespace` dataclass precedent at
`sophiagraph/src/sophiagraph/models/namespace.py:93`. Rationale lives in
the companion spec §"Locked decisions" §1.

Anti-LLM boundary: this module performs no LLM calls, no content
classification, no summarization. Phase decisions are deterministic and
structural per closed-enum predicates.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Literal

from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.models.namespace import MemoryNamespace
from sophiagraph.models.record import MemoryRecord
from sophiagraph.storage.record_lifecycle import utc_now_iso


class LifecyclePhase(StrEnum):
    """Closed 4-enum phase taxonomy per KPR-03 Locked Decision 3."""

    ACTIVE = "active"
    COOLING = "cooling"
    ARCHIVED = "archived"
    SUPERSEDED = "superseded"


class PromotionPredicateKind(StrEnum):
    """Closed 4-enum predicate taxonomy per KPR-03 §PromotionPredicateKind."""

    ACCESS_COUNT_ABOVE_THRESHOLD = "access_count_above_threshold"
    TIER_TRANSITION_COUNT_ABOVE_THRESHOLD = "tier_transition_count_above_threshold"
    EVENT_TIME_WITHIN_WINDOW = "event_time_within_window"
    NAMESPACE_DIMENSION_MATCH = "namespace_dimension_match"


TransitionReason = Literal[
    "ttl_active_elapsed",
    "ttl_cooling_elapsed",
    "promotion_predicate_matched",
    "no_transition",
]


_TIER_TRANSITION_COUNT_META_KEY = "tier_transition_count"
"""Documented key the host runtime stashes tier-transition counts under
on `MemoryRecord.meta` for `TIER_TRANSITION_COUNT_ABOVE_THRESHOLD`
evaluation. Per companion spec §"Locked decisions" §4."""


# ---------------------------------------------------------------------------
# ISO 8601 duration parsing (stdlib-only, scoped to KPR-03 needs)
# ---------------------------------------------------------------------------

_ISO_DURATION_PATTERN = re.compile(
    r"^P"
    r"(?:(?P<years>\d+)Y)?"
    r"(?:(?P<months>\d+)M)?"
    r"(?:(?P<weeks>\d+)W)?"
    r"(?:(?P<days>\d+)D)?"
    r"(?:T"
    r"(?:(?P<hours>\d+)H)?"
    r"(?:(?P<minutes>\d+)M)?"
    r"(?:(?P<seconds>\d+)S)?"
    r")?$"
)


def _parse_iso_duration(duration: str) -> timedelta:
    """Parse a bounded ISO 8601 duration string into a timedelta.

    Supports `PnY`, `PnM`, `PnW`, `PnD`, `PTnH`, `PTnM`, `PTnS`, and
    combinations (`P1Y2M3DT4H5M6S`). Approximation rules: year = 365 days,
    month = 30 days. Per companion spec §"Locked decisions" §3.
    """

    if not isinstance(duration, str) or not duration:
        raise InvalidArgumentError("duration must be a non-empty ISO 8601 string")
    match = _ISO_DURATION_PATTERN.match(duration)
    if match is None:
        raise InvalidArgumentError(f"unparseable ISO 8601 duration: {duration!r}")
    groups = {
        key: int(value) if value else 0 for key, value in match.groupdict().items()
    }
    if not any(groups.values()):
        raise InvalidArgumentError(f"duration has zero magnitude: {duration!r}")
    total_days = (
        groups["years"] * 365
        + groups["months"] * 30
        + groups["weeks"] * 7
        + groups["days"]
    )
    return timedelta(
        days=total_days,
        hours=groups["hours"],
        minutes=groups["minutes"],
        seconds=groups["seconds"],
    )


def _parse_iso_datetime(value: str) -> datetime:
    """Parse an ISO 8601 datetime; ensure tz-aware (assume UTC if naive)."""

    if not isinstance(value, str) or not value:
        raise InvalidArgumentError("datetime must be a non-empty ISO 8601 string")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


# ---------------------------------------------------------------------------
# Frozen record types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PromotionPredicate:
    """One operator-named structural check; cross-field invariants enforced
    in `__post_init__` per companion spec §"Cross-field invariants"."""

    kind: PromotionPredicateKind
    threshold: int | None = None
    window_iso: str | None = None
    namespace_dimension: str | None = None
    namespace_dimension_value: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, PromotionPredicateKind):
            raise InvalidArgumentError("kind must be a PromotionPredicateKind")
        threshold_kinds = {
            PromotionPredicateKind.ACCESS_COUNT_ABOVE_THRESHOLD,
            PromotionPredicateKind.TIER_TRANSITION_COUNT_ABOVE_THRESHOLD,
        }
        if self.kind in threshold_kinds:
            if self.threshold is None or self.threshold < 0:
                raise InvalidArgumentError(
                    f"{self.kind.value} requires non-negative integer threshold"
                )
            if self.window_iso is not None:
                raise InvalidArgumentError(f"{self.kind.value} forbids window_iso")
            if (
                self.namespace_dimension is not None
                or self.namespace_dimension_value is not None
            ):
                raise InvalidArgumentError(
                    f"{self.kind.value} forbids namespace fields"
                )
        elif self.kind == PromotionPredicateKind.EVENT_TIME_WITHIN_WINDOW:
            if not self.window_iso:
                raise InvalidArgumentError(
                    "event_time_within_window requires window_iso"
                )
            _parse_iso_duration(self.window_iso)
            if self.threshold is not None:
                raise InvalidArgumentError("event_time_within_window forbids threshold")
            if (
                self.namespace_dimension is not None
                or self.namespace_dimension_value is not None
            ):
                raise InvalidArgumentError(
                    "event_time_within_window forbids namespace fields"
                )
        elif self.kind == PromotionPredicateKind.NAMESPACE_DIMENSION_MATCH:
            if not self.namespace_dimension or not self.namespace_dimension_value:
                raise InvalidArgumentError(
                    "namespace_dimension_match requires namespace_dimension and "
                    "namespace_dimension_value"
                )
            if self.threshold is not None or self.window_iso is not None:
                raise InvalidArgumentError(
                    "namespace_dimension_match forbids threshold/window_iso"
                )


@dataclass(frozen=True)
class LifecyclePolicy:
    """Operator-config TTL + promotion policy scoped to a `MemoryNamespace`."""

    policy_id: str
    namespace_filter: MemoryNamespace
    created_at_iso: str
    ttl_active_iso: str | None = None
    ttl_cooling_iso: str | None = None
    promotion_predicates: tuple[PromotionPredicate, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not isinstance(self.policy_id, str) or not self.policy_id:
            raise InvalidArgumentError("policy_id must be a non-empty string")
        if not isinstance(self.namespace_filter, MemoryNamespace):
            raise InvalidArgumentError(
                "namespace_filter must be a MemoryNamespace instance"
            )
        if not isinstance(self.created_at_iso, str) or not self.created_at_iso:
            raise InvalidArgumentError("created_at_iso must be a non-empty string")
        if self.ttl_active_iso is not None:
            _parse_iso_duration(self.ttl_active_iso)
        if self.ttl_cooling_iso is not None:
            _parse_iso_duration(self.ttl_cooling_iso)
        if not isinstance(self.promotion_predicates, tuple):
            raise InvalidArgumentError("promotion_predicates must be a tuple")
        for predicate in self.promotion_predicates:
            if not isinstance(predicate, PromotionPredicate):
                raise InvalidArgumentError(
                    "promotion_predicates must contain PromotionPredicate instances"
                )


@dataclass(frozen=True)
class LifecycleDecision:
    """Result of `evaluate_policy`; phase transition is structural and
    deterministic per KPR-03 Anti-LLM Boundary §3."""

    current_phase: LifecyclePhase
    next_phase: LifecyclePhase
    transition_reason: TransitionReason
    matched_predicate_kind: PromotionPredicateKind | None = None
    next_evaluation_at_iso: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.current_phase, LifecyclePhase):
            raise InvalidArgumentError("current_phase must be a LifecyclePhase")
        if not isinstance(self.next_phase, LifecyclePhase):
            raise InvalidArgumentError("next_phase must be a LifecyclePhase")
        if self.transition_reason not in (
            "ttl_active_elapsed",
            "ttl_cooling_elapsed",
            "promotion_predicate_matched",
            "no_transition",
        ):
            raise InvalidArgumentError(
                f"unknown transition_reason: {self.transition_reason!r}"
            )
        if (
            self.transition_reason == "promotion_predicate_matched"
            and self.matched_predicate_kind is None
        ):
            raise InvalidArgumentError(
                "promotion_predicate_matched requires matched_predicate_kind"
            )
        if (
            self.transition_reason != "promotion_predicate_matched"
            and self.matched_predicate_kind is not None
        ):
            raise InvalidArgumentError(
                "matched_predicate_kind set without promotion_predicate_matched reason"
            )


@dataclass(frozen=True)
class ConsolidationRunSummary:
    """Typed summary returned by host runtime after a consolidation pass."""

    records_examined: int
    records_transitioned: int
    transition_counts: dict[str, int]
    completed_at_iso: str

    def __post_init__(self) -> None:
        if self.records_examined < 0:
            raise InvalidArgumentError("records_examined must be non-negative")
        if self.records_transitioned < 0:
            raise InvalidArgumentError("records_transitioned must be non-negative")
        if not isinstance(self.transition_counts, dict):
            raise InvalidArgumentError("transition_counts must be a dict")
        allowed_keys = {
            "active_to_cooling",
            "cooling_to_active",
            "cooling_to_archived",
        }
        for key, value in self.transition_counts.items():
            if key not in allowed_keys:
                raise InvalidArgumentError(
                    f"transition_counts has unknown key: {key!r}"
                )
            if not isinstance(value, int) or value < 0:
                raise InvalidArgumentError(
                    f"transition_counts[{key!r}] must be non-negative int"
                )
        if not isinstance(self.completed_at_iso, str) or not self.completed_at_iso:
            raise InvalidArgumentError("completed_at_iso must be a non-empty string")


@dataclass(frozen=True)
class ConsolidationJob:
    """Declarative descriptor; execution is host-runtime concern per KPR-03
    Locked Decision 7."""

    job_id: str
    policy: LifecyclePolicy
    schedule_spec: str
    next_run_at_iso: str
    last_run_at_iso: str | None = None
    last_run_summary: ConsolidationRunSummary | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.job_id, str) or not self.job_id:
            raise InvalidArgumentError("job_id must be a non-empty string")
        if not isinstance(self.policy, LifecyclePolicy):
            raise InvalidArgumentError("policy must be a LifecyclePolicy")
        if not isinstance(self.schedule_spec, str) or not self.schedule_spec:
            raise InvalidArgumentError("schedule_spec must be a non-empty string")
        if not isinstance(self.next_run_at_iso, str) or not self.next_run_at_iso:
            raise InvalidArgumentError("next_run_at_iso must be a non-empty string")
        if self.last_run_summary is not None and not isinstance(
            self.last_run_summary, ConsolidationRunSummary
        ):
            raise InvalidArgumentError(
                "last_run_summary must be a ConsolidationRunSummary"
            )


# ---------------------------------------------------------------------------
# Pure evaluation
# ---------------------------------------------------------------------------


def _record_phase(record: MemoryRecord) -> LifecyclePhase:
    """Derive the current phase from existing MemoryRecord fields.

    KPR-03 backward-compat §1: records without an explicit phase default
    to ACTIVE. Once a record is superseded (`superseded_by_id` set) it
    reads as SUPERSEDED. Phase persistence is a host-runtime concern out
    of v1 scope; for v1, callers MAY stash a phase under
    `record.meta["lifecycle_phase"]`, and this function reads it
    structurally.
    """

    if record.superseded_by_id:
        return LifecyclePhase.SUPERSEDED
    if record.valid_to:
        # An invalidated record without a successor reads as archived.
        return LifecyclePhase.ARCHIVED
    persisted = (
        record.meta.get("lifecycle_phase") if isinstance(record.meta, dict) else None
    )
    if isinstance(persisted, str):
        try:
            return LifecyclePhase(persisted)
        except ValueError:
            return LifecyclePhase.ACTIVE
    return LifecyclePhase.ACTIVE


def _predicate_matches(
    predicate: PromotionPredicate,
    record: MemoryRecord,
    now: datetime,
) -> bool:
    if predicate.kind == PromotionPredicateKind.ACCESS_COUNT_ABOVE_THRESHOLD:
        return int(record.access_count) >= int(predicate.threshold or 0)
    if predicate.kind == PromotionPredicateKind.TIER_TRANSITION_COUNT_ABOVE_THRESHOLD:
        count = 0
        if isinstance(record.meta, dict):
            raw = record.meta.get(_TIER_TRANSITION_COUNT_META_KEY, 0)
            if isinstance(raw, int):
                count = raw
        return count >= int(predicate.threshold or 0)
    if predicate.kind == PromotionPredicateKind.EVENT_TIME_WITHIN_WINDOW:
        if not record.event_time:
            return False
        try:
            event_time = _parse_iso_datetime(record.event_time)
            window = _parse_iso_duration(predicate.window_iso or "")
        except InvalidArgumentError:
            return False
        return (now - event_time) <= window
    if predicate.kind == PromotionPredicateKind.NAMESPACE_DIMENSION_MATCH:
        namespace = record.effective_namespace
        value = namespace.as_dict().get(predicate.namespace_dimension or "")
        return value == predicate.namespace_dimension_value
    return False


def evaluate_policy(
    record: MemoryRecord,
    policy: LifecyclePolicy,
    now_iso: str,
) -> LifecycleDecision:
    """Pure, deterministic, side-effect-free policy evaluation.

    Honors KPR-03 §"TTL semantics" and §"Promotion semantics". Does NOT
    call the store, does NOT mutate inputs, does NOT call any LLM.
    """

    if not isinstance(record, MemoryRecord):
        raise InvalidArgumentError("record must be a MemoryRecord")
    if not isinstance(policy, LifecyclePolicy):
        raise InvalidArgumentError("policy must be a LifecyclePolicy")
    now = _parse_iso_datetime(now_iso)
    current_phase = _record_phase(record)

    # Terminal phases stay terminal (KPR-03 Locked Decision 9).
    if current_phase in (LifecyclePhase.ARCHIVED, LifecyclePhase.SUPERSEDED):
        return LifecycleDecision(
            current_phase=current_phase,
            next_phase=current_phase,
            transition_reason="no_transition",
        )

    updated_at = _parse_iso_datetime(record.updated_at)
    age = now - updated_at

    if current_phase == LifecyclePhase.ACTIVE:
        if policy.ttl_active_iso is None:
            return LifecycleDecision(
                current_phase=current_phase,
                next_phase=current_phase,
                transition_reason="no_transition",
                next_evaluation_at_iso=None,
            )
        ttl_active = _parse_iso_duration(policy.ttl_active_iso)
        if age >= ttl_active:
            if policy.ttl_cooling_iso is None:
                return LifecycleDecision(
                    current_phase=current_phase,
                    next_phase=LifecyclePhase.ARCHIVED,
                    transition_reason="ttl_active_elapsed",
                )
            return LifecycleDecision(
                current_phase=current_phase,
                next_phase=LifecyclePhase.COOLING,
                transition_reason="ttl_active_elapsed",
            )
        next_eval = updated_at + ttl_active
        return LifecycleDecision(
            current_phase=current_phase,
            next_phase=current_phase,
            transition_reason="no_transition",
            next_evaluation_at_iso=next_eval.isoformat(),
        )

    # COOLING phase: predicate match → ACTIVE, else TTL-cooling check.
    for predicate in policy.promotion_predicates:
        if _predicate_matches(predicate, record, now):
            return LifecycleDecision(
                current_phase=current_phase,
                next_phase=LifecyclePhase.ACTIVE,
                transition_reason="promotion_predicate_matched",
                matched_predicate_kind=predicate.kind,
            )
    if policy.ttl_cooling_iso is not None and policy.ttl_active_iso is not None:
        ttl_active = _parse_iso_duration(policy.ttl_active_iso)
        ttl_cooling = _parse_iso_duration(policy.ttl_cooling_iso)
        if age >= (ttl_active + ttl_cooling):
            return LifecycleDecision(
                current_phase=current_phase,
                next_phase=LifecyclePhase.ARCHIVED,
                transition_reason="ttl_cooling_elapsed",
            )
        next_eval = updated_at + ttl_active + ttl_cooling
        return LifecycleDecision(
            current_phase=current_phase,
            next_phase=current_phase,
            transition_reason="no_transition",
            next_evaluation_at_iso=next_eval.isoformat(),
        )
    return LifecycleDecision(
        current_phase=current_phase,
        next_phase=current_phase,
        transition_reason="no_transition",
    )


def derive_default_policy(
    namespace: MemoryNamespace,
    *,
    ttl_active_iso: str | None = None,
    ttl_cooling_iso: str | None = None,
) -> LifecyclePolicy:
    """Structural helper for operator-config defaults.

    Constructs a `LifecyclePolicy` with no promotion predicates, the
    supplied namespace as filter, and the supplied TTL values. Per
    companion spec §"Locked decisions" §6.
    """

    if not isinstance(namespace, MemoryNamespace):
        raise InvalidArgumentError("namespace must be a MemoryNamespace")
    namespace_dict = namespace.as_dict()
    policy_id = "default:" + ",".join(
        f"{key}={value}" for key, value in sorted(namespace_dict.items())
    )
    return LifecyclePolicy(
        policy_id=policy_id,
        namespace_filter=namespace,
        created_at_iso=utc_now_iso(),
        ttl_active_iso=ttl_active_iso,
        ttl_cooling_iso=ttl_cooling_iso,
        promotion_predicates=(),
    )


__all__ = [
    "ConsolidationJob",
    "ConsolidationRunSummary",
    "LifecycleDecision",
    "LifecyclePhase",
    "LifecyclePolicy",
    "PromotionPredicate",
    "PromotionPredicateKind",
    "derive_default_policy",
    "evaluate_policy",
]
