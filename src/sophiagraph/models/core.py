"""Canonical durable-knowledge models and value types."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import re
from typing import Any, Iterable, Literal, Sequence, TypedDict, cast, get_args

from sophiagraph.temporal import coerce_temporal_dt
from sophiagraph.trust.types import (
    ClaimKeyPolarity,
    MemorySourceClass,
)

from sophiagraph.models.constants import MEMORY_CANDIDATE_STATUS_PROPOSED
from sophiagraph.contracts.errors import InvalidArgumentError

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


def _assert_scope(scope: Scope) -> None:
    if not _SCOPE_PATTERN.match(scope):
        raise InvalidArgumentError(f"invalid scope: {scope!r}")


def _assert_namespace_id(value: str, label: str) -> None:
    if not value:
        raise InvalidArgumentError(f"{label} is required")
    if not _NAMESPACE_ID_PATTERN.match(value):
        raise InvalidArgumentError(f"invalid {label}: {value!r}")


@dataclass(frozen=True)
class MemoryScope:
    """Canonical parser/coercer for memory scope strings."""

    kind: ScopeKind
    value: str

    def __post_init__(self) -> None:
        _assert_scope(str(self))

    def __str__(self) -> str:
        return f"{self.kind}:{self.value}"

    @property
    def is_session(self) -> bool:
        return self.kind == "session"

    @property
    def is_agent(self) -> bool:
        return self.kind == "agent"

    @property
    def is_project(self) -> bool:
        return self.kind == "project"

    @property
    def is_global(self) -> bool:
        return self.kind == "global"

    @classmethod
    def parse(cls, scope: Scope) -> "MemoryScope":
        normalized = str(scope or "").strip()
        _assert_scope(normalized)
        kind, value = normalized.split(":", 1)
        return cls(kind=kind, value=value)  # type: ignore[arg-type]

    @classmethod
    def coerce(
        cls,
        scope: Scope,
        *,
        default_kind: ScopeKind = "session",
    ) -> "MemoryScope":
        normalized = str(scope or "").strip()
        if _SCOPE_PATTERN.match(normalized):
            return cls.parse(normalized)
        if not normalized:
            raise InvalidArgumentError("scope is required")
        return cls(kind=default_kind, value=normalized)


@dataclass(frozen=True)
class MemoryNamespaceComponent:
    """One explicit namespace dimension supplied by a caller or host runtime."""

    kind: NamespaceKind
    id: str

    def __post_init__(self) -> None:
        _assert_literal(self.kind, get_args(NamespaceKind), "namespace kind")
        _assert_namespace_id(self.id, f"{self.kind}_id")

    def as_scope(self) -> Scope:
        if self.kind in {"agent", "session", "project"}:
            return f"{self.kind}:{self.id}"
        if self.kind == "graph":
            return f"global:{self.id}"
        raise InvalidArgumentError(
            f"namespace kind cannot be represented as legacy scope: {self.kind!r}"
        )


@dataclass(frozen=True)
class MemoryNamespace:
    """Typed isolation dimensions for future multi-agent memory records."""

    tenant_id: str | None = None
    org_id: str | None = None
    user_id: str | None = None
    agent_id: str | None = None
    session_id: str | None = None
    conversation_id: str | None = None
    project_id: str | None = None
    graph_id: str | None = None

    def __post_init__(self) -> None:
        values = self.as_dict()
        if not values:
            raise InvalidArgumentError("at least one namespace id is required")
        for key, value in values.items():
            _assert_namespace_id(value, key)

    @property
    def components(self) -> list[MemoryNamespaceComponent]:
        return [
            MemoryNamespaceComponent(kind=kind, id=value)
            for kind, value in (
                ("tenant", self.tenant_id),
                ("org", self.org_id),
                ("user", self.user_id),
                ("agent", self.agent_id),
                ("session", self.session_id),
                ("conversation", self.conversation_id),
                ("project", self.project_id),
                ("graph", self.graph_id),
            )
            if value is not None
        ]

    def as_dict(self) -> dict[str, str]:
        values = {
            "tenant_id": self.tenant_id,
            "org_id": self.org_id,
            "user_id": self.user_id,
            "agent_id": self.agent_id,
            "session_id": self.session_id,
            "conversation_id": self.conversation_id,
            "project_id": self.project_id,
            "graph_id": self.graph_id,
        }
        return {key: value for key, value in values.items() if value is not None}

    def matches(self, namespace_filter: "MemoryNamespace") -> bool:
        values = self.as_dict()
        return all(
            values.get(key) == value
            for key, value in namespace_filter.as_dict().items()
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MemoryNamespace":
        return cls(
            tenant_id=str(data["tenant_id"]) if data.get("tenant_id") else None,
            org_id=str(data["org_id"]) if data.get("org_id") else None,
            user_id=str(data["user_id"]) if data.get("user_id") else None,
            agent_id=str(data["agent_id"]) if data.get("agent_id") else None,
            session_id=str(data["session_id"]) if data.get("session_id") else None,
            conversation_id=str(data["conversation_id"])
            if data.get("conversation_id")
            else None,
            project_id=str(data["project_id"]) if data.get("project_id") else None,
            graph_id=str(data["graph_id"]) if data.get("graph_id") else None,
        )

    @classmethod
    def from_scope(cls, scope: Scope) -> "MemoryNamespace":
        parsed = MemoryScope.parse(scope)
        if parsed.kind == "session":
            return cls(session_id=parsed.value)
        if parsed.kind == "agent":
            return cls(agent_id=parsed.value)
        if parsed.kind == "project":
            return cls(project_id=parsed.value)
        return cls(graph_id=parsed.value)

    def to_scope(self, kind: ScopeKind) -> Scope:
        if kind == "session" and self.session_id is not None:
            return f"session:{self.session_id}"
        if kind == "agent" and self.agent_id is not None:
            return f"agent:{self.agent_id}"
        if kind == "project" and self.project_id is not None:
            return f"project:{self.project_id}"
        if kind == "global" and self.graph_id is not None:
            return f"global:{self.graph_id}"
        raise InvalidArgumentError(
            f"namespace does not contain a {kind!r} scope-compatible id"
        )


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


@dataclass(frozen=True)
class ArtifactRef:
    ref: str
    mime: str
    sha256: str
    size_bytes: int
    label: str | None = None

    def __post_init__(self) -> None:
        if self.size_bytes < 0:
            raise InvalidArgumentError("size_bytes must be non-negative")
        if not self.ref:
            raise InvalidArgumentError("ref is required")
        if not self.mime:
            raise InvalidArgumentError("mime is required")
        if not self.sha256:
            raise InvalidArgumentError("sha256 is required")


@dataclass(frozen=True)
class MemoryRecord:
    id: str
    scope: Scope
    type: MemoryType
    content: dict[str, Any] | str
    created_at: str
    updated_at: str
    key: str | None = None
    title: str | None = None
    tags: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    source: MemorySource = "agent_inferred"
    confidence: float = 0.5
    evidence_refs: list[ArtifactRef] = field(default_factory=list)
    expires_at: str | None = None
    visibility: RecordVisibility | None = None
    meta: dict[str, Any] = field(default_factory=dict)
    last_hit_at: str | None = None
    event_time: str | None = None
    valid_to: str | None = None
    supersedes_id: str | None = None
    superseded_by_id: str | None = None
    supersession_reason: str | None = None
    is_deleted: bool = False
    namespace: MemoryNamespace | None = None
    deleted_at: str | None = None
    deleted_reason: str | None = None
    tier: MemoryTier = "working"
    access_count: int = 0

    @property
    def superseded(self) -> bool:
        """Return True when this record has been superseded."""
        return self.superseded_by_id is not None

    def is_invalidated_at(self, when: datetime | str | None = None) -> bool:
        """Return True when the record has a closed temporal validity window."""
        if not self.valid_to:
            return False
        target = (
            coerce_temporal_dt(when) if when is not None else datetime.now(timezone.utc)
        )
        return coerce_temporal_dt(self.valid_to) <= target

    def is_current_at(self, when: datetime | str | None = None) -> bool:
        """Return True when the record is still current at the supplied time."""
        return not self.is_invalidated_at(when)

    def __post_init__(self) -> None:
        if not self.id:
            raise InvalidArgumentError("id is required")
        _assert_scope(self.scope)
        _assert_literal(self.type, get_args(MemoryType), "type")
        _assert_literal(self.source, get_args(MemorySource), "source")
        _assert_literal(self.tier, get_args(MemoryTier), "tier")
        _assert_confidence(self.confidence)
        if isinstance(self.content, str) and not self.content:
            raise InvalidArgumentError("content string must be non-empty")
        if int(self.access_count) < 0:
            raise InvalidArgumentError("access_count must be non-negative")
        _assert_iterable(self.tags, "tags", str)
        _assert_iterable(self.entities, "entities", str)
        for ref in self.evidence_refs:
            if not isinstance(ref, ArtifactRef):
                raise TypeError(
                    "evidence_refs must contain ArtifactRef instances"
                )  # allow-bare-raise: defensive type guard in dataclass __post_init__
        if self.namespace is not None and not isinstance(
            self.namespace, MemoryNamespace
        ):
            raise TypeError(
                "namespace must be MemoryNamespace"
            )  # allow-bare-raise: defensive type guard in dataclass __post_init__
        if not isinstance(self.meta, dict):
            raise TypeError(
                "meta must be a dict"
            )  # allow-bare-raise: defensive type guard in dataclass __post_init__

    @property
    def effective_namespace(self) -> MemoryNamespace:
        if self.namespace is not None:
            return self.namespace
        return MemoryNamespace.from_scope(self.scope)


_coerce_temporal_dt = coerce_temporal_dt


@dataclass(frozen=True)
class CandidateReview:
    reviewer: str
    decided_at: str
    note: str | None = None

    def __post_init__(self) -> None:
        if not self.reviewer:
            raise InvalidArgumentError("reviewer is required")
        if not self.decided_at:
            raise InvalidArgumentError("decided_at is required")


@dataclass(frozen=True)
class MemoryCandidate:
    candidate_id: str
    session_id: str
    proposed_scope: Scope
    type: MemoryType
    content: dict[str, Any] | str
    tags: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    source: MemorySource = "agent_inferred"
    confidence: float = 0.5
    evidence_refs: list[ArtifactRef] = field(default_factory=list)
    status: CandidateStatus = MEMORY_CANDIDATE_STATUS_PROPOSED
    key: str | None = None
    title: str | None = None
    review: CandidateReview | None = None
    meta: dict[str, Any] = field(default_factory=dict)
    claim_key: str | None = None
    polarity: ClaimKeyPolarity = "asserts"
    source_class: MemorySourceClass | None = None
    created_at: str | None = None
    updated_at: str | None = None

    def __post_init__(self) -> None:
        if not self.candidate_id:
            raise InvalidArgumentError("candidate_id is required")
        if not self.session_id:
            raise InvalidArgumentError("session_id is required")
        _assert_scope(self.proposed_scope)
        _assert_literal(self.type, get_args(MemoryType), "type")
        _assert_literal(self.source, get_args(MemorySource), "source")
        _assert_literal(self.status, get_args(CandidateStatus), "status")
        _assert_confidence(self.confidence)
        if isinstance(self.content, str) and not self.content:
            raise InvalidArgumentError("content string must be non-empty")
        _assert_iterable(self.tags, "tags", str)
        _assert_iterable(self.entities, "entities", str)
        for ref in self.evidence_refs:
            if not isinstance(ref, ArtifactRef):
                raise TypeError(
                    "evidence_refs must contain ArtifactRef instances"
                )  # allow-bare-raise: defensive type guard in dataclass __post_init__
        if self.review and not isinstance(self.review, CandidateReview):
            raise TypeError(
                "review must be CandidateReview"
            )  # allow-bare-raise: defensive type guard in dataclass __post_init__
        if not isinstance(self.meta, dict):
            raise TypeError(
                "meta must be a dict"
            )  # allow-bare-raise: defensive type guard in dataclass __post_init__
        _assert_literal(self.polarity, get_args(ClaimKeyPolarity), "polarity")
        resolved_meta = dict(self.meta)
        resolved_claim_key = self.claim_key
        if resolved_claim_key is None:
            meta_claim_key = resolved_meta.get("claim_key")
            if meta_claim_key is not None:
                resolved_claim_key = str(meta_claim_key)
        if resolved_claim_key is not None:
            resolved_claim_key = str(resolved_claim_key).strip()
            if not resolved_claim_key:
                raise InvalidArgumentError("claim_key must be non-empty when set")
            resolved_meta["claim_key"] = resolved_claim_key

        resolved_polarity = self.polarity
        meta_polarity = resolved_meta.get("polarity")
        if meta_polarity is not None and self.claim_key is None:
            resolved_polarity = _as_claim_key_polarity(str(meta_polarity))
        _assert_literal(
            resolved_polarity,
            get_args(ClaimKeyPolarity),
            "polarity",
        )
        resolved_meta["polarity"] = resolved_polarity

        resolved_source_class = self.source_class
        if resolved_source_class is None:
            meta_source_class = resolved_meta.get("source_class")
            if meta_source_class is not None:
                resolved_source_class = _as_memory_source_class(str(meta_source_class))
        if resolved_source_class is not None:
            _assert_literal(
                resolved_source_class,
                get_args(MemorySourceClass),
                "source_class",
            )
            resolved_meta["source_class"] = resolved_source_class

        object.__setattr__(self, "claim_key", resolved_claim_key)
        object.__setattr__(self, "polarity", resolved_polarity)
        object.__setattr__(self, "source_class", resolved_source_class)
        object.__setattr__(self, "meta", resolved_meta)


@dataclass(frozen=True)
class MemoryRelation:
    relation_id: str
    source_record_id: str
    target_record_id: str
    relation_type: MemoryRelationType
    created_at: str
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.relation_id:
            raise InvalidArgumentError("relation_id is required")
        if not self.source_record_id:
            raise InvalidArgumentError("source_record_id is required")
        if not self.target_record_id:
            raise InvalidArgumentError("target_record_id is required")
        if self.source_record_id == self.target_record_id:
            raise InvalidArgumentError("relation endpoints must differ")
        _assert_literal(
            self.relation_type,
            get_args(MemoryRelationType),
            "relation_type",
        )
        if not self.created_at:
            raise InvalidArgumentError("created_at is required")
        if not isinstance(self.meta, dict):
            raise TypeError(
                "meta must be a dict"
            )  # allow-bare-raise: defensive type guard in dataclass __post_init__


@dataclass(frozen=True)
class MemoryTierTransition:
    transition_id: str
    record_id: str
    scope: Scope
    record_type: MemoryType
    from_tier: MemoryTier
    to_tier: MemoryTier
    transition_reason: MemoryTierTransitionReason
    transition_at: str
    access_count: int = 0
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.transition_id:
            raise InvalidArgumentError("transition_id is required")
        if not self.record_id:
            raise InvalidArgumentError("record_id is required")
        _assert_scope(self.scope)
        _assert_literal(self.record_type, get_args(MemoryType), "record_type")
        _assert_literal(self.from_tier, get_args(MemoryTier), "from_tier")
        _assert_literal(self.to_tier, get_args(MemoryTier), "to_tier")
        _assert_literal(
            self.transition_reason,
            get_args(MemoryTierTransitionReason),
            "transition_reason",
        )
        if self.from_tier == self.to_tier:
            raise InvalidArgumentError("from_tier and to_tier must differ")
        if int(self.access_count) < 0:
            raise InvalidArgumentError("access_count must be non-negative")
        if not isinstance(self.meta, dict):
            raise TypeError(
                "meta must be a dict"
            )  # allow-bare-raise: defensive type guard in dataclass __post_init__


@dataclass(frozen=True)
class RetrievalFilters:
    scopes: list[Scope]
    types: list[MemoryType] | None = None
    min_confidence: float | None = None
    source_allowlist: list[MemorySource] | None = None
    updated_since: str | None = None
    limit: int | None = None

    def __post_init__(self) -> None:
        if not self.scopes:
            raise InvalidArgumentError("at least one scope is required")
        for scope in self.scopes:
            _assert_scope(scope)
        if self.types:
            for mem_type in self.types:
                _assert_literal(mem_type, get_args(MemoryType), "type")
        if self.min_confidence is not None:
            _assert_confidence(self.min_confidence)
        if self.source_allowlist:
            for source in self.source_allowlist:
                _assert_literal(source, get_args(MemorySource), "source")
        if self.limit is not None and self.limit <= 0:
            raise InvalidArgumentError("limit must be positive")


class SessionSummaryActiveThread(TypedDict):
    topic: str
    status: SessionSummaryThreadStatus
    next_step: str


class SessionSummaryContent(TypedDict):
    decisions: list[str]
    open_questions: list[str]
    corrections: list[str]
    topic_keywords: list[str]
    active_threads: list[SessionSummaryActiveThread]
    outcome: SessionSummaryOutcome
    turn_count: int
    summary_text: str


@dataclass(frozen=True)
class MemoryPatchResult:
    """Result returned by record_turn() on any gateway-compatible memory adapter."""

    facts_added: int
    todos_added: int
    todos_completed: int
    patch_id: str = ""
    generation: int = 0
    replayed_patches: int = 0
    lock_recovered: bool = False
    facts_auto_extracted: int = 0
