"""Provable deletion and erasure-audit DTOs."""

from __future__ import annotations

from dataclasses import dataclass, field

from sophiagraph.models import MemoryNamespace


@dataclass(frozen=True, slots=True)
class TombstoneResult:
    record_id: str
    deleted_at: str
    reason: str
    namespace: MemoryNamespace


@dataclass(frozen=True, slots=True)
class DeletionCascadeResult:
    root_record_id: str
    tombstoned_record_ids: list[str]
    removed_relation_ids: list[str] = field(default_factory=list)
    removed_link_ids: list[str] = field(default_factory=list)
    removed_block_ids: list[str] = field(default_factory=list)
    removed_embedding_keys: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ErasureAuditEntry:
    record_id: str
    namespace: MemoryNamespace
    deleted_at: str
    reason: str
    cascaded: bool


@dataclass(frozen=True, slots=True)
class ErasureAuditExport:
    entries: list[ErasureAuditEntry]


__all__ = [
    "DeletionCascadeResult",
    "ErasureAuditEntry",
    "ErasureAuditExport",
    "TombstoneResult",
]
