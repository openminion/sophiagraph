"""Stable public facade for lifecycle policy contracts and evaluation helpers."""

from sophiagraph.storage.lifecycle_eval import (
    apply_decision_to_record_meta,
    evaluate_policy,
    predicate_matches,
    record_phase,
)
from sophiagraph.storage.lifecycle_types import (
    ConsolidationJob,
    ConsolidationRunSummary,
    LifecycleDecision,
    LifecyclePhase,
    LifecyclePolicy,
    PromotionPredicate,
    PromotionPredicateKind,
    TransitionReason,
    derive_default_policy,
    parse_iso_datetime,
    parse_iso_duration,
)


__all__ = [
    "ConsolidationJob",
    "ConsolidationRunSummary",
    "LifecycleDecision",
    "LifecyclePhase",
    "LifecyclePolicy",
    "PromotionPredicate",
    "PromotionPredicateKind",
    "TransitionReason",
    "apply_decision_to_record_meta",
    "derive_default_policy",
    "evaluate_policy",
    "parse_iso_datetime",
    "parse_iso_duration",
    "predicate_matches",
    "record_phase",
]
