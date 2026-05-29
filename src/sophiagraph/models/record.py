"""Memory record and retrieval DTOs."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, TypedDict, get_args

from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.models.namespace import MemoryNamespace
from sophiagraph.models.primitives import (
    MemorySource,
    MemoryTier,
    MemoryType,
    RecordVisibility,
    Scope,
    SessionSummaryOutcome,
    SessionSummaryThreadStatus,
    _assert_confidence,
    _assert_iterable,
    _assert_literal,
    _assert_scope,
)
from sophiagraph.temporal import coerce_temporal_dt


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
    integrity_hash: str | None = None

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
        if self.visibility is not None:
            _assert_literal(self.visibility, get_args(RecordVisibility), "visibility")
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
    """Compatibility result for host-runtime record-turn adapters."""

    facts_added: int
    todos_added: int
    todos_completed: int
    patch_id: str = ""
    generation: int = 0
    replayed_patches: int = 0
    lock_recovered: bool = False
    facts_auto_extracted: int = 0


__all__ = [
    "ArtifactRef",
    "MemoryRecord",
    "RetrievalFilters",
    "SessionSummaryActiveThread",
    "SessionSummaryContent",
    "MemoryPatchResult",
    "_coerce_temporal_dt",
]
