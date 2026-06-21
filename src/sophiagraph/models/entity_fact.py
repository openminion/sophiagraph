"""Typed entity, fact, alias, contradiction, and summary DTOs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Final, Literal, Mapping

from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.models.namespace import MemoryNamespace
from sophiagraph.models.privacy import PrivacyPolicyState


EntityFactSourceKind = Literal[
    "tool_observation",
    "user_input",
    "model_authored",
    "imported_bundle",
    "validation_result",
]


ENTITY_FACT_SOURCE_KINDS: Final[frozenset[str]] = frozenset(
    {
        "tool_observation",
        "user_input",
        "model_authored",
        "imported_bundle",
        "validation_result",
    }
)


ContradictionDecision = Literal[
    "supersedes",
    "both_valid",
    "invalidates_target",
]


CONTRADICTION_DECISIONS: Final[frozenset[str]] = frozenset(
    {"supersedes", "both_valid", "invalidates_target"}
)


SummaryAuthorship = Literal["model_authored", "operator_authored", "system_derived"]


SUMMARY_AUTHORSHIPS: Final[frozenset[str]] = frozenset(
    {"model_authored", "operator_authored", "system_derived"}
)


SummaryInvalidationReason = Literal[
    "source_record_changed",
    "entity_changed",
    "privacy_policy_changed",
    "operator_replaced",
    "stale_time_window",
]


SUMMARY_INVALIDATION_REASONS: Final[frozenset[str]] = frozenset(
    {
        "source_record_changed",
        "entity_changed",
        "privacy_policy_changed",
        "operator_replaced",
        "stale_time_window",
    }
)


@dataclass(frozen=True)
class EntityFactProvenance:
    """Caller-supplied provenance for entity/fact DTOs."""

    source_kind: EntityFactSourceKind
    source_id: str
    actor: str
    extra: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.source_kind not in ENTITY_FACT_SOURCE_KINDS:
            raise InvalidArgumentError(
                f"invalid entity/fact source_kind: {self.source_kind!r}"
            )
        if not self.source_id:
            raise InvalidArgumentError("provenance.source_id is required")
        if not self.actor:
            raise InvalidArgumentError("provenance.actor is required")
        if not isinstance(self.extra, Mapping):
            raise InvalidArgumentError("provenance.extra must be a Mapping[str, Any]")


@dataclass(frozen=True)
class Entity:
    """Canonical entity identity row."""

    entity_id: str
    canonical_name: str
    namespace: MemoryNamespace
    provenance: EntityFactProvenance
    entity_type: str = "unspecified"
    created_at: str = ""
    updated_at: str = ""
    confidence: float = 0.5
    invalidated_at: str | None = None
    meta: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.entity_id:
            raise InvalidArgumentError("entity_id is required")
        if not self.canonical_name:
            raise InvalidArgumentError("canonical_name is required")
        if not isinstance(self.namespace, MemoryNamespace):
            raise InvalidArgumentError("namespace must be MemoryNamespace")
        if not isinstance(self.provenance, EntityFactProvenance):
            raise InvalidArgumentError("provenance must be EntityFactProvenance")
        if not isinstance(self.meta, Mapping):
            raise InvalidArgumentError("meta must be a Mapping[str, Any]")
        if not (0.0 <= self.confidence <= 1.0):
            raise InvalidArgumentError("confidence must be in [0.0, 1.0]")


@dataclass(frozen=True)
class EntityAlias:
    """Alias name pointing at a canonical entity."""

    alias_id: str
    alias_name: str
    entity_id: str
    original_entity_id: str
    namespace: MemoryNamespace
    provenance: EntityFactProvenance
    created_at: str = ""
    is_primary: bool = False
    meta: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.alias_id:
            raise InvalidArgumentError("alias_id is required")
        if not self.alias_name:
            raise InvalidArgumentError("alias_name is required")
        if not self.entity_id:
            raise InvalidArgumentError("entity_id is required")
        if not self.original_entity_id:
            raise InvalidArgumentError("original_entity_id is required")
        if not isinstance(self.namespace, MemoryNamespace):
            raise InvalidArgumentError("namespace must be MemoryNamespace")
        if not isinstance(self.provenance, EntityFactProvenance):
            raise InvalidArgumentError("provenance must be EntityFactProvenance")
        if not isinstance(self.meta, Mapping):
            raise InvalidArgumentError("meta must be a Mapping[str, Any]")


@dataclass(frozen=True)
class Fact:
    """Typed temporal claim about one or two entities."""

    fact_id: str
    namespace: MemoryNamespace
    subject_entity_id: str
    predicate: str
    object_entity_id: str | None = None
    object_literal: str | None = None
    provenance: EntityFactProvenance | None = None
    confidence: float = 0.5
    valid_from: str | None = None
    valid_to: str | None = None
    observed_at: str = ""
    created_at: str = ""
    updated_at: str = ""
    invalidated_at: str | None = None
    superseded_by_fact_id: str | None = None
    # Caller-supplied raw episode IDs that justify this fact.
    source_episode_ids: list[str] = field(default_factory=list)
    meta: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.fact_id:
            raise InvalidArgumentError("fact_id is required")
        if not isinstance(self.namespace, MemoryNamespace):
            raise InvalidArgumentError("namespace must be MemoryNamespace")
        if not self.subject_entity_id:
            raise InvalidArgumentError("subject_entity_id is required")
        if not self.predicate:
            raise InvalidArgumentError("predicate is required")
        if self.object_entity_id is None and self.object_literal is None:
            raise InvalidArgumentError(
                "fact requires either object_entity_id or object_literal"
            )
        if self.provenance is not None and not isinstance(
            self.provenance, EntityFactProvenance
        ):
            raise InvalidArgumentError("provenance must be EntityFactProvenance")
        if not (0.0 <= self.confidence <= 1.0):
            raise InvalidArgumentError("confidence must be in [0.0, 1.0]")
        if (
            self.valid_from is not None
            and self.valid_to is not None
            and self.valid_to < self.valid_from
        ):
            raise InvalidArgumentError("valid_to must be >= valid_from")
        if not isinstance(self.source_episode_ids, list):
            raise InvalidArgumentError("source_episode_ids must be a list")
        for episode_id in self.source_episode_ids:
            if not isinstance(episode_id, str) or not episode_id:
                raise InvalidArgumentError(
                    "source_episode_ids must contain non-empty strings"
                )
        if not isinstance(self.meta, Mapping):
            raise InvalidArgumentError("meta must be a Mapping[str, Any]")

    @property
    def is_invalidated(self) -> bool:
        return self.invalidated_at is not None or self.superseded_by_fact_id is not None


@dataclass(frozen=True)
class Contradiction:
    """Explicit decision about two facts that disagree."""

    contradiction_id: str
    namespace: MemoryNamespace
    target_fact_id: str
    contradicting_fact_id: str
    decision: ContradictionDecision
    deciding_actor: str
    decided_at: str
    reason: str = ""
    meta: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.contradiction_id:
            raise InvalidArgumentError("contradiction_id is required")
        if not isinstance(self.namespace, MemoryNamespace):
            raise InvalidArgumentError("namespace must be MemoryNamespace")
        if not self.target_fact_id:
            raise InvalidArgumentError("target_fact_id is required")
        if not self.contradicting_fact_id:
            raise InvalidArgumentError("contradicting_fact_id is required")
        if self.target_fact_id == self.contradicting_fact_id:
            raise InvalidArgumentError(
                "target_fact_id and contradicting_fact_id must differ"
            )
        if self.decision not in CONTRADICTION_DECISIONS:
            raise InvalidArgumentError(
                f"invalid contradiction decision: {self.decision!r}"
            )
        if not self.deciding_actor:
            raise InvalidArgumentError("deciding_actor is required")
        if not self.decided_at:
            raise InvalidArgumentError("decided_at is required")
        if not isinstance(self.meta, Mapping):
            raise InvalidArgumentError("meta must be a Mapping[str, Any]")


@dataclass(frozen=True)
class EntitySummary:
    """Caller-supplied textual summary attached to an entity."""

    summary_id: str
    entity_id: str
    namespace: MemoryNamespace
    summary_text: str
    provenance: EntityFactProvenance
    authorship: SummaryAuthorship = "model_authored"
    created_at: str = ""
    updated_at: str = ""
    invalidated_at: str | None = None
    invalidation_reason: SummaryInvalidationReason | None = None
    superseded_by_summary_id: str | None = None
    source_record_ids: tuple[str, ...] = ()
    privacy_policy: PrivacyPolicyState | None = None
    meta: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.summary_id:
            raise InvalidArgumentError("summary_id is required")
        if not self.entity_id:
            raise InvalidArgumentError("entity_id is required")
        if not isinstance(self.namespace, MemoryNamespace):
            raise InvalidArgumentError("namespace must be MemoryNamespace")
        if not self.summary_text:
            raise InvalidArgumentError(
                "summary_text is required (the package never generates it)"
            )
        if not isinstance(self.provenance, EntityFactProvenance):
            raise InvalidArgumentError("provenance must be EntityFactProvenance")
        if self.authorship not in SUMMARY_AUTHORSHIPS:
            raise InvalidArgumentError(
                f"invalid summary authorship: {self.authorship!r}"
            )
        if self.invalidation_reason is not None and (
            self.invalidation_reason not in SUMMARY_INVALIDATION_REASONS
        ):
            raise InvalidArgumentError(
                f"invalid summary invalidation_reason: {self.invalidation_reason!r}"
            )
        if (
            self.superseded_by_summary_id is not None
            and not self.superseded_by_summary_id
        ):
            raise InvalidArgumentError(
                "superseded_by_summary_id must be a non-empty string or None"
            )
        if not isinstance(self.source_record_ids, tuple):
            raise InvalidArgumentError("source_record_ids must be a tuple[str, ...]")
        for record_id in self.source_record_ids:
            if not isinstance(record_id, str) or not record_id:
                raise InvalidArgumentError(
                    "source_record_ids must contain non-empty strings"
                )
        if self.privacy_policy is not None and not isinstance(
            self.privacy_policy, PrivacyPolicyState
        ):
            raise InvalidArgumentError(
                "privacy_policy must be PrivacyPolicyState or None"
            )
        if not isinstance(self.meta, Mapping):
            raise InvalidArgumentError("meta must be a Mapping[str, Any]")

    @property
    def is_invalidated(self) -> bool:
        return (
            self.invalidated_at is not None
            or self.superseded_by_summary_id is not None
            or self.invalidation_reason is not None
        )


__all__ = [
    "CONTRADICTION_DECISIONS",
    "ContradictionDecision",
    "Contradiction",
    "ENTITY_FACT_SOURCE_KINDS",
    "Entity",
    "EntityAlias",
    "EntityFactProvenance",
    "EntityFactSourceKind",
    "EntitySummary",
    "Fact",
    "SUMMARY_AUTHORSHIPS",
    "SUMMARY_INVALIDATION_REASONS",
    "SummaryAuthorship",
    "SummaryInvalidationReason",
]
