"""Typed contracts for package-local human note and source-management helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from sophiagraph.connectors import SourceRegistryEntry
from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.freshness import FreshnessLedgerEntry
from sophiagraph.inspection import InspectionReport
from sophiagraph.models import MemoryNamespace, MemoryRecord
from sophiagraph.query import ListQueryOptions
from sophiagraph.sync import SyncConflictRecord
from sophiagraph.vault import VaultDiagnostic, VaultManifest

HumanImportAction = Literal["create", "update", "delete", "unchanged"]


class HumanStore(Protocol):
    """Store subset needed by human-management helpers."""

    def put_record(self, record: MemoryRecord) -> str: ...

    def get_record(self, record_id: str) -> MemoryRecord | None: ...

    def list_records(self, options: ListQueryOptions) -> list[MemoryRecord]: ...

    def list_source_entries(
        self,
        *,
        namespaces: list[MemoryNamespace] | None = None,
        source_type: str | None = None,
        permission_scope: str | None = None,
        limit: int | None = None,
    ) -> list[SourceRegistryEntry]: ...

    def list_freshness_entries(
        self,
        *,
        namespaces: list[MemoryNamespace] | None = None,
        source_kind: str | None = None,
        source_id: str | None = None,
        status: str | None = None,
        limit: int | None = None,
    ) -> list[FreshnessLedgerEntry]: ...

    def list_sync_conflicts(
        self,
        *,
        namespaces: list[MemoryNamespace] | None = None,
        status: str | None = None,
        source_id: str | None = None,
        limit: int | None = None,
    ) -> list[SyncConflictRecord]: ...


@dataclass(frozen=True)
class HumanNoteInput:
    """Caller-supplied note payload for the local note workspace."""

    scope: str
    namespace: MemoryNamespace
    note_key: str
    title: str
    body: str
    tags: tuple[str, ...] = ()
    created_at: str = ""
    updated_at: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.scope:
            raise InvalidArgumentError("scope is required")
        if not isinstance(self.namespace, MemoryNamespace):
            raise TypeError("namespace must be MemoryNamespace")
        if not self.note_key:
            raise InvalidArgumentError("note_key is required")
        if not self.title:
            raise InvalidArgumentError("title is required")
        if not self.body:
            raise InvalidArgumentError("body is required")


@dataclass(frozen=True)
class HumanNotePatch:
    """Mutable patch over an existing note-shaped record."""

    title: str | None = None
    body: str | None = None
    tags: tuple[str, ...] | None = None
    updated_at: str = ""
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class HumanNoteEntry:
    """Summary row for one note in the local human workspace."""

    record_id: str
    note_key: str
    title: str
    updated_at: str
    namespace: MemoryNamespace
    archived: bool = False
    tags: tuple[str, ...] = ()
    excerpt: str = ""


@dataclass(frozen=True)
class HumanWorkspaceSnapshot:
    """Current human-managed note workspace view."""

    scope: str
    namespace: MemoryNamespace
    notes: tuple[HumanNoteEntry, ...] = ()
    active_count: int = 0
    archived_count: int = 0


@dataclass(frozen=True)
class VaultImportPlanItem:
    """One dry-run decision for a vault-shaped payload path."""

    path: str
    action: HumanImportAction
    file_kind: str
    reason: str
    record_id: str | None = None
    content_hash: str = ""


@dataclass(frozen=True)
class VaultImportPlan:
    """Dry-run plan over one explicit Sophia vault import."""

    manifest: VaultManifest
    items: tuple[VaultImportPlanItem, ...] = ()
    created_count: int = 0
    updated_count: int = 0
    deleted_count: int = 0
    unchanged_count: int = 0
    stale_count: int = 0
    diagnostics: tuple[VaultDiagnostic, ...] = ()


@dataclass(frozen=True)
class SourceStatusItem:
    """One merged source/freshness/conflict row."""

    source_id: str
    display_name: str
    source_type: str
    permission_scope: str
    namespace: MemoryNamespace
    freshness_status: str = "unknown"
    cursor: str | None = None
    content_hash: str | None = None
    updated_at: str = ""
    open_conflict_count: int = 0
    broken_reference_count: int = 0


@dataclass(frozen=True)
class SourceManagementConsole:
    """Inspectable source/freshness repair packet for local operators."""

    namespace: MemoryNamespace
    sources: tuple[SourceStatusItem, ...] = ()
    inspection_report: InspectionReport | None = None
    open_conflict_count: int = 0


@dataclass(frozen=True)
class HumanWorkbenchPacket:
    """Package-local operating surface for human note/import/source workflows."""

    workspace: HumanWorkspaceSnapshot
    import_plan: VaultImportPlan | None = None
    source_console: SourceManagementConsole | None = None


__all__ = [
    "HumanImportAction",
    "HumanNoteEntry",
    "HumanNoteInput",
    "HumanNotePatch",
    "HumanStore",
    "HumanWorkbenchPacket",
    "HumanWorkspaceSnapshot",
    "SourceManagementConsole",
    "SourceStatusItem",
    "VaultImportPlan",
    "VaultImportPlanItem",
]
