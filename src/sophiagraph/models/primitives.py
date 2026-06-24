"""Primitive durable-knowledge value types and validators."""

from __future__ import annotations

import re
from typing import Any, Iterable, Literal, Sequence, cast

from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.trust.types import ClaimKeyPolarity, MemorySourceClass

Scope = str
ScopeKind = Literal["session", "agent", "project", "global"]
NamespaceKind = Literal[
    "tenant",
    "org",
    "user",
    "agent",
    "session",
    "conversation",
    "project",
    "graph",
]
MemoryType = Literal[
    "pin",
    "decision",
    "task",
    "fact",
    "procedure",
    "artifact_digest",
    "plan_snapshot",
    "summary",
    "session_summary",
    "meta_insight",
    "user_preference",
    "project_convention",
    "correction",
    "tool_habit",
    "tool_outcome",
    "strategy_outcome",
    "post_completion_critique",
    "meta_rule_preference",
    "consolidated_knowledge",
    "declared_goal",
    "goal_revision",
]
MemorySource = Literal[
    "user_said",
    "tool_output",
    "agent_inferred",
    "validated",
    "imported",
]
RecordVisibility = Literal["private", "shared"]
CandidateStatus = Literal["proposed", "approved", "rejected", "promoted"]
MemoryRelationType = Literal["related_to", "depends_on", "supports", "corrects"]
RelationDirection = Literal["out", "in", "both"]
MemoryTier = Literal["working", "archival"]
MemoryTierTransitionReason = Literal[
    "age_threshold",
    "reaccess_threshold",
    "manual_override",
]
SessionSummaryThreadStatus = Literal["open", "paused", "done"]
SessionSummaryOutcome = Literal[
    "succeeded",
    "blocked",
    "no_prior_context",
    "abandoned",
    "unknown",
]

_SCOPE_PATTERN = re.compile(r"^(session|agent|project|global):[A-Za-z0-9._:-]+$")
_NAMESPACE_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]+$")


def _as_memory_type(value: str) -> MemoryType:
    return cast(MemoryType, value)


def _as_memory_source(value: str) -> MemorySource:
    return cast(MemorySource, value)


def _as_memory_tier(value: str) -> MemoryTier:
    return cast(MemoryTier, value)


def _as_candidate_status(value: str) -> CandidateStatus:
    return cast(CandidateStatus, value)


def _as_claim_key_polarity(value: str) -> ClaimKeyPolarity:
    return cast(ClaimKeyPolarity, value)


def _as_memory_source_class(value: str) -> MemorySourceClass:
    return cast(MemorySourceClass, value)


def _as_memory_relation_type(value: str) -> MemoryRelationType:
    return cast(MemoryRelationType, value)


def _as_memory_tier_transition_reason(value: str) -> MemoryTierTransitionReason:
    return cast(MemoryTierTransitionReason, value)


def _as_memory_type_list(
    values: list[str] | list[Any] | None,
) -> list[MemoryType] | None:
    if values is None:
        return None
    return cast(list[MemoryType], list(values))


def _as_memory_relation_type_list(
    values: list[str] | None,
) -> list[MemoryRelationType] | None:
    if values is None:
        return None
    return cast(list[MemoryRelationType], list(values))


coerce_memory_type = _as_memory_type
coerce_memory_source = _as_memory_source
coerce_memory_tier = _as_memory_tier
coerce_candidate_status = _as_candidate_status
coerce_memory_relation_type = _as_memory_relation_type
coerce_memory_tier_transition_reason = _as_memory_tier_transition_reason


def _assert_scope(scope: Scope) -> None:
    if not _SCOPE_PATTERN.match(scope):
        raise InvalidArgumentError(f"invalid scope: {scope!r}")


def _assert_namespace_id(value: str, label: str) -> None:
    if not value:
        raise InvalidArgumentError(f"{label} is required")
    if not _NAMESPACE_ID_PATTERN.match(value):
        raise InvalidArgumentError(f"invalid {label}: {value!r}")


def _assert_confidence(value: float) -> None:
    if not (0.0 <= value <= 1.0):
        raise InvalidArgumentError("confidence must be between 0 and 1 inclusive")


def _assert_literal(value: str, allowed: Sequence[str], label: str) -> None:
    if value not in allowed:
        raise InvalidArgumentError(f"invalid {label}: {value!r}")


def _assert_iterable(
    values: Iterable[Any], label: str, expected_type: type[str]
) -> None:
    for item in values:
        if not isinstance(item, expected_type):
            raise TypeError(
                f"{label} must contain {expected_type.__name__} values"
            )  # allow-bare-raise: defensive type guard in dataclass __post_init__


__all__ = [
    "Scope",
    "ScopeKind",
    "NamespaceKind",
    "MemoryType",
    "MemorySource",
    "RecordVisibility",
    "CandidateStatus",
    "MemoryRelationType",
    "RelationDirection",
    "MemoryTier",
    "MemoryTierTransitionReason",
    "SessionSummaryThreadStatus",
    "SessionSummaryOutcome",
    "_SCOPE_PATTERN",
    "_as_memory_type",
    "_as_memory_source",
    "_as_memory_tier",
    "_as_candidate_status",
    "_as_claim_key_polarity",
    "_as_memory_source_class",
    "_as_memory_relation_type",
    "_as_memory_tier_transition_reason",
    "_as_memory_type_list",
    "_as_memory_relation_type_list",
    "coerce_memory_type",
    "coerce_memory_source",
    "coerce_memory_tier",
    "coerce_candidate_status",
    "coerce_memory_relation_type",
    "coerce_memory_tier_transition_reason",
    "_assert_scope",
    "_assert_namespace_id",
    "_assert_confidence",
    "_assert_literal",
    "_assert_iterable",
]
