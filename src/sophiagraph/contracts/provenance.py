"""Memory-provenance contracts."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Sequence
from sophiagraph.contracts.errors import InvalidArgumentError


@dataclass(frozen=True)
class MemoryProvenanceEntry:
    """A single memory's contribution to a turn retrieval."""

    memory_id: str
    source: str
    written_at: str
    retrieval_score: float
    score_breakdown: Mapping[str, float] = field(default_factory=dict)
    citation_context: str = ""

    def __post_init__(self) -> None:
        if not self.memory_id:
            raise InvalidArgumentError("memory_id is required")
        if not self.source:
            raise InvalidArgumentError("source is required")
        if not self.written_at:
            raise InvalidArgumentError("written_at is required")
        if len(self.citation_context) > 200:
            raise InvalidArgumentError("citation_context must be <= 200 chars")

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["score_breakdown"] = dict(self.score_breakdown)
        return out

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "MemoryProvenanceEntry":
        return cls(
            memory_id=str(payload["memory_id"]),
            source=str(payload["source"]),
            written_at=str(payload["written_at"]),
            retrieval_score=float(payload.get("retrieval_score", 0.0)),
            score_breakdown=dict(payload.get("score_breakdown", {})),
            citation_context=str(payload.get("citation_context", "")),
        )


@dataclass(frozen=True)
class TurnProvenanceTrace:
    """Per-turn aggregate of memory-retrieval provenance."""

    session_id: str
    turn_id: str
    recorded_at: str
    entries: Sequence[MemoryProvenanceEntry] = field(default_factory=tuple)
    retrieval_cutoff: float = 0.0
    query: str = ""

    def __post_init__(self) -> None:
        if not self.session_id:
            raise InvalidArgumentError("session_id is required")
        if not self.turn_id:
            raise InvalidArgumentError("turn_id is required")
        if not self.recorded_at:
            raise InvalidArgumentError("recorded_at is required")
        for entry in self.entries:
            if not isinstance(entry, MemoryProvenanceEntry):
                raise TypeError(  # allow-bare-raise: defensive type guard on iterable contents
                    "TurnProvenanceTrace.entries must contain "
                    "MemoryProvenanceEntry instances"
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "recorded_at": self.recorded_at,
            "entries": [entry.to_dict() for entry in self.entries],
            "retrieval_cutoff": self.retrieval_cutoff,
            "query": self.query,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "TurnProvenanceTrace":
        raw_entries = payload.get("entries", [])
        entries: list[MemoryProvenanceEntry] = []
        for raw in raw_entries:
            if isinstance(raw, MemoryProvenanceEntry):
                entries.append(raw)
            else:
                entries.append(MemoryProvenanceEntry.from_dict(raw))
        return cls(
            session_id=str(payload["session_id"]),
            turn_id=str(payload["turn_id"]),
            recorded_at=str(payload["recorded_at"]),
            entries=tuple(entries),
            retrieval_cutoff=float(payload.get("retrieval_cutoff", 0.0)),
            query=str(payload.get("query", "")),
        )

    def memory_ids(self) -> list[str]:
        """Return the ordered list of memory IDs that contributed."""

        return [entry.memory_id for entry in self.entries]


__all__ = [
    "MemoryProvenanceEntry",
    "TurnProvenanceTrace",
]
