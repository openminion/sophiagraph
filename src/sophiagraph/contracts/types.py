"""Durable-knowledge contract DTOs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sophiagraph.trust.types import ClaimKeyPolarity

MEMORY_CONTRACT_VERSION = "v2"


@dataclass(frozen=True)
class MemoryQuery:
    query: str
    scopes: list[str]
    types: list[str] | None = None
    limit: int | None = None
    filters: dict[str, Any] | None = None
    caller_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MemoryHit:
    record_id: str
    scope: str
    record_type: str
    text: str
    score: float = 0.0
    confidence: float = 0.0
    evidence_refs: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MemoryProcedure:
    procedure_id: str
    title: str
    steps: list[str] = field(default_factory=list)
    preflight: list[str] = field(default_factory=list)
    rollback_hint: str = ""


@dataclass(frozen=True)
class MemoryCandidateRequest:
    scope: str
    record_type: str
    title: str
    content: dict[str, Any] | str
    tags: list[str] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class MemoryCandidateDecision:
    candidate_id: str
    decision: str
    reason_code: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ClaimKeyContract:
    claim_key: str
    polarity: ClaimKeyPolarity = "asserts"


@dataclass(frozen=True)
class MemoryRuntimeSnapshot:
    agent_id: str
    session_id: str
    record_count: int = 0
    candidate_count: int = 0
    highlights: list[str] = field(default_factory=list)
    degraded: bool = False
    degraded_reason: str = ""


@dataclass(frozen=True)
class MemoryCapsule:
    capsule_text: str
    generation: int
    created_at: str
    hash: str
    scope: str
