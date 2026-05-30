"""Typed episode, step, outcome, decision, and procedure DTOs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Final, Literal, Mapping

from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.models.namespace import MemoryNamespace


EpisodeStatus = Literal[
    "in_progress",
    "succeeded",
    "blocked",
    "abandoned",
    "failed",
]


EPISODE_STATUSES: Final[frozenset[str]] = frozenset(
    {"in_progress", "succeeded", "blocked", "abandoned", "failed"}
)


StepKind = Literal[
    "thought",
    "tool_call",
    "tool_result",
    "user_input",
    "validation",
    "artifact",
    "decision",
    "note",
]


STEP_KINDS: Final[frozenset[str]] = frozenset(
    {
        "thought",
        "tool_call",
        "tool_result",
        "user_input",
        "validation",
        "artifact",
        "decision",
        "note",
    }
)


OutcomeStatus = Literal[
    "succeeded",
    "failed",
    "skipped",
    "deferred",
    "partial",
]


OUTCOME_STATUSES: Final[frozenset[str]] = frozenset(
    {"succeeded", "failed", "skipped", "deferred", "partial"}
)


ProcedurePromotionTier = Literal[
    "experimental",
    "promoted",
    "deprecated",
]


PROCEDURE_PROMOTION_TIERS: Final[frozenset[str]] = frozenset(
    {"experimental", "promoted", "deprecated"}
)


@dataclass(frozen=True)
class Episode:
    """One bounded unit of agent experience (a task run, a chat turn group)."""

    episode_id: str
    namespace: MemoryNamespace
    title: str
    status: EpisodeStatus
    started_at: str
    ended_at: str | None = None
    parent_episode_id: str | None = None
    task_id: str | None = None
    artifact_ids: list[str] = field(default_factory=list)
    tool_ids: list[str] = field(default_factory=list)
    summary: str = ""
    meta: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.episode_id:
            raise InvalidArgumentError("episode_id is required")
        if not isinstance(self.namespace, MemoryNamespace):
            raise InvalidArgumentError("namespace must be MemoryNamespace")
        if not self.title:
            raise InvalidArgumentError("title is required")
        if self.status not in EPISODE_STATUSES:
            raise InvalidArgumentError(f"invalid episode status: {self.status!r}")
        if not self.started_at:
            raise InvalidArgumentError("started_at is required")
        if self.ended_at is not None and self.ended_at < self.started_at:
            raise InvalidArgumentError("ended_at must be >= started_at")
        if not isinstance(self.meta, Mapping):
            raise InvalidArgumentError("meta must be a Mapping[str, Any]")
        for collection_name, items in (
            ("artifact_ids", self.artifact_ids),
            ("tool_ids", self.tool_ids),
        ):
            if not isinstance(items, list):
                raise InvalidArgumentError(f"{collection_name} must be a list")
            for item in items:
                if not isinstance(item, str) or not item:
                    raise InvalidArgumentError(
                        f"{collection_name} must contain non-empty strings"
                    )


@dataclass(frozen=True)
class EpisodeStep:
    """One ordered step inside an episode."""

    step_id: str
    episode_id: str
    namespace: MemoryNamespace
    kind: StepKind
    sequence: int
    occurred_at: str
    content: str = ""
    tool_id: str | None = None
    tool_call_id: str | None = None
    artifact_id: str | None = None
    file_path: str | None = None
    meta: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.step_id:
            raise InvalidArgumentError("step_id is required")
        if not self.episode_id:
            raise InvalidArgumentError("episode_id is required")
        if not isinstance(self.namespace, MemoryNamespace):
            raise InvalidArgumentError("namespace must be MemoryNamespace")
        if self.kind not in STEP_KINDS:
            raise InvalidArgumentError(f"invalid step kind: {self.kind!r}")
        if self.sequence < 0:
            raise InvalidArgumentError("sequence must be >= 0")
        if not self.occurred_at:
            raise InvalidArgumentError("occurred_at is required")
        if not isinstance(self.meta, Mapping):
            raise InvalidArgumentError("meta must be a Mapping[str, Any]")


@dataclass(frozen=True)
class Outcome:
    """Typed outcome attached to an episode or a step."""

    outcome_id: str
    namespace: MemoryNamespace
    status: OutcomeStatus
    occurred_at: str
    episode_id: str | None = None
    step_id: str | None = None
    actor: str = ""
    summary: str = ""
    validation_command: str | None = None
    error_class: str | None = None
    error_message: str | None = None
    meta: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.outcome_id:
            raise InvalidArgumentError("outcome_id is required")
        if not isinstance(self.namespace, MemoryNamespace):
            raise InvalidArgumentError("namespace must be MemoryNamespace")
        if self.status not in OUTCOME_STATUSES:
            raise InvalidArgumentError(f"invalid outcome status: {self.status!r}")
        if not self.occurred_at:
            raise InvalidArgumentError("occurred_at is required")
        if not self.episode_id and not self.step_id:
            raise InvalidArgumentError("outcome requires either episode_id or step_id")
        if not isinstance(self.meta, Mapping):
            raise InvalidArgumentError("meta must be a Mapping[str, Any]")


@dataclass(frozen=True)
class Decision:
    """Caller-recorded choice with alternatives + rationale (text supplied)."""

    decision_id: str
    namespace: MemoryNamespace
    title: str
    chosen: str
    occurred_at: str
    episode_id: str | None = None
    step_id: str | None = None
    alternatives: list[str] = field(default_factory=list)
    rationale: str = ""
    deciding_actor: str = ""
    meta: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.decision_id:
            raise InvalidArgumentError("decision_id is required")
        if not isinstance(self.namespace, MemoryNamespace):
            raise InvalidArgumentError("namespace must be MemoryNamespace")
        if not self.title:
            raise InvalidArgumentError("title is required")
        if not self.chosen:
            raise InvalidArgumentError("chosen is required")
        if not self.occurred_at:
            raise InvalidArgumentError("occurred_at is required")
        if not isinstance(self.alternatives, list):
            raise InvalidArgumentError("alternatives must be a list")
        for alt in self.alternatives:
            if not isinstance(alt, str) or not alt:
                raise InvalidArgumentError(
                    "alternatives must contain non-empty strings"
                )
        if not isinstance(self.meta, Mapping):
            raise InvalidArgumentError("meta must be a Mapping[str, Any]")


@dataclass(frozen=True)
class ProcedureStep:
    """One ordered step inside a procedure (caller-authored)."""

    sequence: int
    title: str
    body: str = ""
    tool_id: str | None = None

    def __post_init__(self) -> None:
        if self.sequence < 0:
            raise InvalidArgumentError("sequence must be >= 0")
        if not self.title:
            raise InvalidArgumentError("title is required")


@dataclass(frozen=True)
class Procedure:
    """Reusable typed bundle of caller-authored steps."""

    procedure_id: str
    namespace: MemoryNamespace
    title: str
    promotion_tier: ProcedurePromotionTier
    created_at: str
    steps: list[ProcedureStep] = field(default_factory=list)
    rollback_hint: str = ""
    source_episode_ids: list[str] = field(default_factory=list)
    updated_at: str = ""
    invalidated_at: str | None = None
    meta: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.procedure_id:
            raise InvalidArgumentError("procedure_id is required")
        if not isinstance(self.namespace, MemoryNamespace):
            raise InvalidArgumentError("namespace must be MemoryNamespace")
        if not self.title:
            raise InvalidArgumentError("title is required")
        if self.promotion_tier not in PROCEDURE_PROMOTION_TIERS:
            raise InvalidArgumentError(
                f"invalid promotion_tier: {self.promotion_tier!r}"
            )
        if not self.created_at:
            raise InvalidArgumentError("created_at is required")
        if not isinstance(self.steps, list):
            raise InvalidArgumentError("steps must be a list")
        for s in self.steps:
            if not isinstance(s, ProcedureStep):
                raise InvalidArgumentError("steps must be ProcedureStep instances")
        if not isinstance(self.source_episode_ids, list):
            raise InvalidArgumentError("source_episode_ids must be a list")
        for episode_id in self.source_episode_ids:
            if not isinstance(episode_id, str) or not episode_id:
                raise InvalidArgumentError(
                    "source_episode_ids must contain non-empty strings"
                )
        if not isinstance(self.meta, Mapping):
            raise InvalidArgumentError("meta must be a Mapping[str, Any]")


__all__ = [
    "Decision",
    "EPISODE_STATUSES",
    "Episode",
    "EpisodeStatus",
    "EpisodeStep",
    "OUTCOME_STATUSES",
    "Outcome",
    "OutcomeStatus",
    "PROCEDURE_PROMOTION_TIERS",
    "Procedure",
    "ProcedurePromotionTier",
    "ProcedureStep",
    "STEP_KINDS",
    "StepKind",
]
