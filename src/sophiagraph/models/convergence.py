"""Temporal context graph DTOs linking raw episodes to explicit facts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Final, Literal, Mapping

from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.models.entity_fact import EntityFactProvenance
from sophiagraph.models.namespace import MemoryNamespace


RawEpisodeKind = Literal[
    "message",
    "tool_output",
    "user_input",
    "system_event",
    "validation_result",
    "import_event",
]


RAW_EPISODE_KINDS: Final[frozenset[str]] = frozenset(
    {
        "message",
        "tool_output",
        "user_input",
        "system_event",
        "validation_result",
        "import_event",
    }
)


FactActiveState = Literal["active", "historical", "all"]

FACT_ACTIVE_STATES: Final[frozenset[str]] = frozenset({"active", "historical", "all"})


@dataclass(frozen=True)
class RawEpisode:
    """Caller-submitted raw event used as evidence for facts."""

    episode_id: str
    kind: RawEpisodeKind
    source: str
    source_id: str
    namespace: MemoryNamespace
    occurred_at: str
    ingested_at: str
    payload: Mapping[str, Any]
    provenance: EntityFactProvenance
    actor: str = ""
    invalidated_at: str | None = None
    meta: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.episode_id:
            raise InvalidArgumentError("episode_id is required")
        if self.kind not in RAW_EPISODE_KINDS:
            raise InvalidArgumentError(f"invalid raw episode kind: {self.kind!r}")
        if not self.source:
            raise InvalidArgumentError("source is required")
        if not self.source_id:
            raise InvalidArgumentError("source_id is required")
        if not isinstance(self.namespace, MemoryNamespace):
            raise InvalidArgumentError("namespace must be MemoryNamespace")
        if not self.occurred_at:
            raise InvalidArgumentError("occurred_at is required")
        if not self.ingested_at:
            raise InvalidArgumentError("ingested_at is required")
        if not isinstance(self.payload, Mapping):
            raise InvalidArgumentError("payload must be a Mapping[str, Any]")
        if not isinstance(self.provenance, EntityFactProvenance):
            raise InvalidArgumentError("provenance must be EntityFactProvenance")
        if not isinstance(self.meta, Mapping):
            raise InvalidArgumentError("meta must be a Mapping[str, Any]")


@dataclass(frozen=True)
class FactConvergenceLink:
    """Evidence row tying one fact to one raw episode."""

    link_id: str
    fact_id: str
    episode_id: str
    namespace: MemoryNamespace
    role: str = "primary"
    confidence: float = 1.0
    created_at: str = ""
    meta: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.link_id:
            raise InvalidArgumentError("link_id is required")
        if not self.fact_id:
            raise InvalidArgumentError("fact_id is required")
        if not self.episode_id:
            raise InvalidArgumentError("episode_id is required")
        if not isinstance(self.namespace, MemoryNamespace):
            raise InvalidArgumentError("namespace must be MemoryNamespace")
        if not self.role:
            raise InvalidArgumentError("role is required")
        if not (0.0 <= self.confidence <= 1.0):
            raise InvalidArgumentError("confidence must be in [0.0, 1.0]")
        if not isinstance(self.meta, Mapping):
            raise InvalidArgumentError("meta must be a Mapping[str, Any]")


__all__ = [
    "FACT_ACTIVE_STATES",
    "FactActiveState",
    "FactConvergenceLink",
    "RAW_EPISODE_KINDS",
    "RawEpisode",
    "RawEpisodeKind",
]
