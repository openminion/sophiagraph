"""Durable-knowledge portability DTOs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from sophiagraph.contracts.provenance import TurnProvenanceTrace
from sophiagraph.models import (
    MemoryBlock,
    MemoryNamespace,
    MemoryCandidate,
    MemoryRecord,
    MemoryRelation,
    MemoryTierTransition,
    SophiaGraphChangeEvent,
)


@dataclass(frozen=True)
class MemoryBundleExportOptions:
    scopes: list[str]
    types: list[str] | None = None
    limit: int | None = None
    include_candidates: bool = False
    include_relations: bool = True
    include_tier_history: bool = False
    # Optional in-memory retrieval provenance for portability snapshots.
    include_provenance: bool = False
    # Opt in when memory blocks are part of the migration set.
    include_memory_blocks: bool = False
    namespaces: list[MemoryNamespace] | None = None


@dataclass(frozen=True)
class MemoryBundleImportOptions:
    scope_rewrites: dict[str, str] = field(default_factory=dict)
    trust_mode: Literal["direct", "candidate"] = "direct"
    conflict_mode: Literal["skip", "supersede", "error"] = "skip"
    id_mode: Literal["preserve", "regenerate"] = "preserve"
    dry_run: bool = False
    namespace_allowlist: list[MemoryNamespace] | None = None


@dataclass(frozen=True)
class MemoryBundleSnapshot:
    manifest: dict[str, Any]
    records: list[MemoryRecord]
    candidates: list[MemoryCandidate] = field(default_factory=list)
    relations: list[MemoryRelation] = field(default_factory=list)
    tier_transitions: list[MemoryTierTransition] = field(default_factory=list)
    # Empty unless export explicitly includes provenance traces.
    provenance_traces: list[TurnProvenanceTrace] = field(default_factory=list)
    # Stored DTOs carry all schema-valid modes; callers own activation.
    memory_blocks: list[MemoryBlock] = field(default_factory=list)


@dataclass(frozen=True)
class MemoryBundleImportResult:
    applied: bool
    trust_mode: str
    conflict_mode: str
    id_mode: str
    imported_records: int = 0
    staged_candidates: int = 0
    imported_candidates: int = 0
    imported_relations: int = 0
    imported_tier_transitions: int = 0
    imported_provenance_traces: int = 0
    imported_memory_blocks: int = 0
    skipped_records: int = 0
    skipped_sections: list[str] = field(default_factory=list)
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    rewrites: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class MemoryDeltaSnapshot:
    manifest: dict[str, Any]
    changes: list[SophiaGraphChangeEvent]


@dataclass(frozen=True)
class MemoryDeltaImportResult:
    applied: bool
    imported_changes: int = 0
    skipped_changes: int = 0
    skipped_event_ids: list[str] = field(default_factory=list)
