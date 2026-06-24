"""Pure evaluation helpers for lifecycle policies."""

from __future__ import annotations

from datetime import datetime

from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.models.record import MemoryRecord
from sophiagraph.storage.lifecycle_types import (
    LifecycleDecision,
    LifecyclePhase,
    LifecyclePolicy,
    PromotionPredicate,
    PromotionPredicateKind,
    parse_iso_datetime,
    parse_iso_duration,
)
from sophiagraph.storage.lifecycle_types import _TIER_TRANSITION_COUNT_META_KEY


def record_phase(record: MemoryRecord) -> LifecyclePhase:
    """Derive the current lifecycle phase from explicit record fields."""

    if record.superseded_by_id:
        return LifecyclePhase.SUPERSEDED
    if record.valid_to:
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


def predicate_matches(
    predicate: PromotionPredicate,
    record: MemoryRecord,
    now: datetime,
) -> bool:
    """Return whether a structural promotion predicate matches a record."""

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
            event_time = parse_iso_datetime(record.event_time)
            window = parse_iso_duration(predicate.window_iso or "")
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
    """Evaluate one record against a lifecycle policy without side effects."""

    if not isinstance(record, MemoryRecord):
        raise InvalidArgumentError("record must be a MemoryRecord")
    if not isinstance(policy, LifecyclePolicy):
        raise InvalidArgumentError("policy must be a LifecyclePolicy")
    now = parse_iso_datetime(now_iso)
    current_phase = record_phase(record)
    if current_phase in (LifecyclePhase.ARCHIVED, LifecyclePhase.SUPERSEDED):
        return LifecycleDecision(
            current_phase=current_phase,
            next_phase=current_phase,
            transition_reason="no_transition",
        )

    updated_at = parse_iso_datetime(record.updated_at)
    age = now - updated_at

    if current_phase == LifecyclePhase.ACTIVE:
        if policy.ttl_active_iso is None:
            return LifecycleDecision(
                current_phase=current_phase,
                next_phase=current_phase,
                transition_reason="no_transition",
                next_evaluation_at_iso=None,
            )
        ttl_active = parse_iso_duration(policy.ttl_active_iso)
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

    for predicate in policy.promotion_predicates:
        if predicate_matches(predicate, record, now):
            return LifecycleDecision(
                current_phase=current_phase,
                next_phase=LifecyclePhase.ACTIVE,
                transition_reason="promotion_predicate_matched",
                matched_predicate_kind=predicate.kind,
            )
    if policy.ttl_cooling_iso is not None and policy.ttl_active_iso is not None:
        ttl_active = parse_iso_duration(policy.ttl_active_iso)
        ttl_cooling = parse_iso_duration(policy.ttl_cooling_iso)
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


def apply_decision_to_record_meta(
    current_meta: dict | None,
    decision: LifecycleDecision,
) -> dict:
    """Return a new ``meta`` dict reflecting ``decision``."""

    if decision is None or not isinstance(decision, LifecycleDecision):
        raise InvalidArgumentError("decision must be a LifecycleDecision")
    new_meta: dict = dict(current_meta or {})
    new_meta["lifecycle_phase"] = decision.next_phase.value
    if decision.transition_reason != "no_transition":
        new_meta["lifecycle_transition_reason"] = decision.transition_reason
    return new_meta


__all__ = [
    "apply_decision_to_record_meta",
    "evaluate_policy",
    "predicate_matches",
    "record_phase",
]
