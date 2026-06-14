"""Human note, import, and source-management helpers for SophiaGraph."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from hashlib import sha256
from html import escape
from typing import Any, Literal, Protocol
from uuid import NAMESPACE_URL, uuid5

from sophiagraph.connectors import SourceRegistryEntry
from sophiagraph.contracts.errors import InvalidArgumentError, NotFoundError
from sophiagraph.freshness import FreshnessLedgerEntry
from sophiagraph.inspection import InspectionReport, build_inspection_report
from sophiagraph.models import MemoryNamespace, MemoryRecord
from sophiagraph.query import ListQueryOptions
from sophiagraph.storage.record_lifecycle import utc_now_iso
from sophiagraph.sync import SyncConflictRecord
from sophiagraph.vault import (
    VaultDiagnostic,
    VaultFilePayload,
    VaultImportOptions,
    VaultManifest,
    build_vault_manifest,
)

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


def _stable_id(prefix: str, *parts: str) -> str:
    return f"{prefix}-{uuid5(NAMESPACE_URL, ':'.join(str(part) for part in parts))}"


def _namespace_key(namespace: MemoryNamespace) -> str:
    return "|".join(
        f"{key}={value}" for key, value in sorted(namespace.as_dict().items())
    )


def _note_meta(record: MemoryRecord) -> dict[str, Any]:
    payload = record.meta.get("human_note")
    return payload if isinstance(payload, dict) else {}


def _record_text(record: MemoryRecord) -> str:
    if isinstance(record.content, str):
        return record.content
    return str(record.content.get("text") or record.content.get("source_text") or "")


def _archive_state(record: MemoryRecord) -> bool:
    meta = _note_meta(record)
    if bool(meta.get("archived")):
        return True
    return bool(record.valid_to or record.is_deleted)


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


def note_record_id_for(scope: str, namespace: MemoryNamespace, note_key: str) -> str:
    """Return a deterministic record identifier for one note key."""
    return _stable_id("note", scope, _namespace_key(namespace), note_key)


def create_human_note(store: HumanStore, note: HumanNoteInput) -> MemoryRecord:
    """Create or replace one note-shaped record through the canonical store."""
    timestamp = note.created_at or note.updated_at or utc_now_iso()
    record = MemoryRecord(
        id=note_record_id_for(note.scope, note.namespace, note.note_key),
        scope=note.scope,
        type="artifact_digest",
        key=f"note:{note.note_key}",
        title=note.title,
        content={"text": note.body, "source_text": note.body},
        tags=list(note.tags),
        source="user_said",
        confidence=1.0,
        created_at=timestamp,
        updated_at=note.updated_at or timestamp,
        namespace=note.namespace,
        event_time=timestamp,
        meta={
            **dict(note.meta),
            "human_note": {
                "note_key": note.note_key,
                "workspace": "local_human_notes",
                "archived": False,
            },
            "document": {
                "path": f"notes/{note.note_key}.md",
                "title": note.title,
                "content_hash": sha256(note.body.encode("utf-8")).hexdigest(),
                "source_format": "markdown",
                "provenance": {"adapter": "human_note"},
            },
        },
    )
    store.put_record(record)
    return record


def update_human_note(
    store: HumanStore,
    *,
    record_id: str,
    patch: HumanNotePatch,
) -> MemoryRecord:
    """Update one existing note-shaped record in place."""
    record = store.get_record(record_id)
    if record is None:
        raise NotFoundError(f"record not found: {record_id}")
    note_meta = _note_meta(record)
    if not note_meta:
        raise InvalidArgumentError("record is not managed by the human note workspace")
    body = patch.body if patch.body is not None else _record_text(record)
    title = patch.title if patch.title is not None else (record.title or "")
    updated_at = patch.updated_at or utc_now_iso()
    meta = {
        **dict(record.meta),
        **dict(patch.meta),
        "human_note": {**note_meta, "archived": False},
        "document": {
            **dict(record.meta.get("document") or {}),
            "path": f"notes/{note_meta.get('note_key')}.md",
            "title": title,
            "content_hash": sha256(body.encode("utf-8")).hexdigest(),
            "source_format": "markdown",
            "provenance": {"adapter": "human_note"},
        },
    }
    updated = replace(
        record,
        title=title,
        content={"text": body, "source_text": body},
        tags=list(patch.tags if patch.tags is not None else record.tags),
        updated_at=updated_at,
        meta=meta,
    )
    store.put_record(updated)
    return updated


def archive_human_note(
    store: HumanStore,
    *,
    record_id: str,
    archived_at: str = "",
    reason: str = "archived by operator",
) -> MemoryRecord:
    """Archive one note while preserving its provenance-rich record history."""
    record = store.get_record(record_id)
    if record is None:
        raise NotFoundError(f"record not found: {record_id}")
    note_meta = _note_meta(record)
    if not note_meta:
        raise InvalidArgumentError("record is not managed by the human note workspace")
    when = archived_at or utc_now_iso()
    updated = replace(
        record,
        valid_to=when,
        updated_at=when,
        supersession_reason=reason,
        meta={
            **dict(record.meta),
            "human_note": {
                **note_meta,
                "archived": True,
                "archived_at": when,
                "archive_reason": reason,
            },
        },
    )
    store.put_record(updated)
    return updated


def list_human_workspace(
    store: HumanStore,
    *,
    scope: str,
    namespace: MemoryNamespace,
    include_archived: bool = False,
) -> HumanWorkspaceSnapshot:
    """List the local note workspace built over canonical MemoryRecord rows."""
    records = store.list_records(
        ListQueryOptions(
            scopes=[scope],
            namespaces=[namespace],
            include_invalidated=True,
            limit=None,
        )
    )
    entries: list[HumanNoteEntry] = []
    active_count = 0
    archived_count = 0
    for record in records:
        note_meta = _note_meta(record)
        if not note_meta:
            continue
        archived = _archive_state(record)
        if archived:
            archived_count += 1
            if not include_archived:
                continue
        else:
            active_count += 1
        entries.append(
            HumanNoteEntry(
                record_id=record.id,
                note_key=str(note_meta.get("note_key") or record.key or record.id),
                title=str(record.title or ""),
                updated_at=record.updated_at,
                namespace=record.effective_namespace,
                archived=archived,
                tags=tuple(record.tags),
                excerpt=_record_text(record)[:120],
            )
        )
    entries.sort(key=lambda item: (item.archived, item.updated_at, item.note_key))
    return HumanWorkspaceSnapshot(
        scope=scope,
        namespace=namespace,
        notes=tuple(entries),
        active_count=active_count,
        archived_count=archived_count,
    )


def plan_human_vault_import(
    store: HumanStore,
    files: list[VaultFilePayload],
    options: VaultImportOptions,
) -> VaultImportPlan:
    """Build a dry-run import plan over vault payloads without mutating the store."""
    manifest = build_vault_manifest(files, options)
    diagnostics = list(_dedupe_vault_diagnostics(files))
    records = store.list_records(
        ListQueryOptions(
            scopes=[options.scope],
            namespaces=[options.namespace],
            include_invalidated=True,
            limit=None,
        )
    )
    existing_by_path = {
        str(record.meta.get("vault", {}).get("path")): record
        for record in records
        if isinstance(record.meta.get("vault"), dict)
        if record.meta["vault"].get("vault_id") == options.vault_id
        if record.meta["vault"].get("path")
    }
    seen_paths = {item.path for item in manifest.files}
    items: list[VaultImportPlanItem] = []
    created = updated = deleted = unchanged = stale = 0
    for entry in manifest.files:
        existing = existing_by_path.get(entry.path)
        if entry.is_deleted:
            if existing is not None and not existing.is_deleted:
                items.append(
                    VaultImportPlanItem(
                        path=entry.path,
                        action="delete",
                        file_kind=entry.file_kind,
                        reason="incoming payload marks path deleted",
                        record_id=existing.id,
                        content_hash=entry.content_hash,
                    )
                )
                deleted += 1
            else:
                items.append(
                    VaultImportPlanItem(
                        path=entry.path,
                        action="unchanged",
                        file_kind=entry.file_kind,
                        reason="path already absent or deleted",
                        record_id=existing.id if existing is not None else None,
                        content_hash=entry.content_hash,
                    )
                )
                unchanged += 1
            continue
        if existing is None or existing.is_deleted:
            items.append(
                VaultImportPlanItem(
                    path=entry.path,
                    action="create",
                    file_kind=entry.file_kind,
                    reason="no active record for incoming path",
                    content_hash=entry.content_hash,
                )
            )
            created += 1
            continue
        existing_hash = str(existing.meta.get("vault", {}).get("content_hash") or "")
        if existing_hash != entry.content_hash:
            items.append(
                VaultImportPlanItem(
                    path=entry.path,
                    action="update",
                    file_kind=entry.file_kind,
                    reason="content hash changed",
                    record_id=existing.id,
                    content_hash=entry.content_hash,
                )
            )
            updated += 1
            continue
        items.append(
            VaultImportPlanItem(
                path=entry.path,
                action="unchanged",
                file_kind=entry.file_kind,
                reason="content hash unchanged",
                record_id=existing.id,
                content_hash=entry.content_hash,
            )
        )
        unchanged += 1
    if options.tombstone_missing:
        for path, record in sorted(existing_by_path.items()):
            if path in seen_paths or record.is_deleted:
                continue
            items.append(
                VaultImportPlanItem(
                    path=path,
                    action="delete",
                    file_kind=str(
                        record.meta.get("vault", {}).get("file_kind") or "asset"
                    ),
                    reason="existing path missing from incoming payload",
                    record_id=record.id,
                    content_hash=str(
                        record.meta.get("vault", {}).get("content_hash") or ""
                    ),
                )
            )
            deleted += 1
            stale += 1
    items.sort(key=lambda item: item.path)
    return VaultImportPlan(
        manifest=manifest,
        items=tuple(items),
        created_count=created,
        updated_count=updated,
        deleted_count=deleted,
        unchanged_count=unchanged,
        stale_count=stale,
        diagnostics=tuple(diagnostics),
    )


def build_source_management_console(
    store: HumanStore,
    *,
    scope: str,
    namespace: MemoryNamespace,
) -> SourceManagementConsole:
    """Build a typed source/freshness/conflict inspection packet."""
    sources = store.list_source_entries(namespaces=[namespace], limit=None)
    freshness = store.list_freshness_entries(namespaces=[namespace], limit=None)
    conflicts = store.list_sync_conflicts(namespaces=[namespace], limit=None)
    records = store.list_records(
        ListQueryOptions(
            scopes=[scope],
            namespaces=[namespace],
            include_invalidated=True,
            limit=None,
        )
    )
    freshness_by_source = {entry.source_id: entry for entry in freshness}
    open_conflicts_by_source: dict[str, int] = {}
    for conflict in conflicts:
        if conflict.status != "open":
            continue
        open_conflicts_by_source[conflict.source_id] = (
            open_conflicts_by_source.get(conflict.source_id, 0) + 1
        )
    known_sources = {entry.source_id for entry in freshness}
    broken_reference_count_by_source: dict[str, int] = {}
    for record in records:
        source_id = record.meta.get("source_id")
        if (
            not isinstance(source_id, str)
            or not source_id
            or source_id in known_sources
        ):
            continue
        broken_reference_count_by_source[source_id] = (
            broken_reference_count_by_source.get(source_id, 0) + 1
        )
    items: list[SourceStatusItem] = []
    for source in sorted(sources, key=lambda item: item.source_id):
        entry = freshness_by_source.get(source.source_id)
        items.append(
            SourceStatusItem(
                source_id=source.source_id,
                display_name=source.display_name,
                source_type=source.source_type,
                permission_scope=source.permission_scope,
                namespace=source.namespace,
                freshness_status=entry.status if entry is not None else "unknown",
                cursor=entry.cursor if entry is not None else source.cursor,
                content_hash=(
                    entry.content_hash if entry is not None else source.content_hash
                ),
                updated_at=(
                    entry.updated_at if entry is not None else source.updated_at
                ),
                open_conflict_count=open_conflicts_by_source.get(source.source_id, 0),
                broken_reference_count=broken_reference_count_by_source.get(
                    source.source_id, 0
                ),
            )
        )
    report = build_inspection_report(
        report_id=_stable_id("human-source-console", scope, _namespace_key(namespace)),
        namespace=namespace,
        generated_at=utc_now_iso(),
        records=records,
        freshness_entries=freshness,
        conflicts=conflicts,
    )
    return SourceManagementConsole(
        namespace=namespace,
        sources=tuple(items),
        inspection_report=report,
        open_conflict_count=sum(item.open_conflict_count for item in items),
    )


def build_human_workbench_packet(
    store: HumanStore,
    *,
    scope: str,
    namespace: MemoryNamespace,
    import_files: list[VaultFilePayload] | None = None,
    import_options: VaultImportOptions | None = None,
    include_archived_notes: bool = False,
) -> HumanWorkbenchPacket:
    """Build the package-local human workbench packet over canonical store data."""
    import_plan = None
    if import_files is not None and import_options is not None:
        import_plan = plan_human_vault_import(store, import_files, import_options)
    return HumanWorkbenchPacket(
        workspace=list_human_workspace(
            store,
            scope=scope,
            namespace=namespace,
            include_archived=include_archived_notes,
        ),
        import_plan=import_plan,
        source_console=build_source_management_console(
            store,
            scope=scope,
            namespace=namespace,
        ),
    )


def render_human_workbench_html(packet: HumanWorkbenchPacket) -> str:
    """Render a deterministic HTML preview for package-local human workflows."""
    notes_html = "".join(
        (
            "<li>"
            f"<strong>{escape(item.title)}</strong>"
            f" [{escape(item.note_key)}]"
            f" status={'archived' if item.archived else 'active'}"
            f" updated_at={escape(item.updated_at)}"
            "</li>"
        )
        for item in packet.workspace.notes
    )
    import_html = ""
    if packet.import_plan is not None:
        import_rows = "".join(
            (
                "<li>"
                f"{escape(item.path)} :: {escape(item.action)}"
                f" ({escape(item.reason)})"
                "</li>"
            )
            for item in packet.import_plan.items
        )
        import_html = (
            "<section><h2>Import Plan</h2>"
            f"<p>created={packet.import_plan.created_count} "
            f"updated={packet.import_plan.updated_count} "
            f"deleted={packet.import_plan.deleted_count} "
            f"unchanged={packet.import_plan.unchanged_count}</p>"
            f"<ul>{import_rows}</ul></section>"
        )
    source_html = ""
    if packet.source_console is not None:
        source_rows = "".join(
            (
                "<li>"
                f"{escape(item.display_name)} [{escape(item.source_id)}]"
                f" status={escape(item.freshness_status)}"
                f" conflicts={item.open_conflict_count}"
                "</li>"
            )
            for item in packet.source_console.sources
        )
        source_html = (
            "<section><h2>Source Console</h2>"
            f"<p>open_conflicts={packet.source_console.open_conflict_count}</p>"
            f"<ul>{source_rows}</ul></section>"
        )
    return (
        "<html><body>"
        "<h1>Human Workbench</h1>"
        f"<p>active_notes={packet.workspace.active_count} "
        f"archived_notes={packet.workspace.archived_count}</p>"
        f"<section><h2>Notes</h2><ul>{notes_html}</ul></section>"
        f"{import_html}{source_html}"
        "</body></html>"
    )


def _dedupe_vault_diagnostics(
    files: list[VaultFilePayload],
) -> list[VaultDiagnostic]:
    seen: set[str] = set()
    diagnostics: list[VaultDiagnostic] = []
    for payload in files:
        if payload.path in seen:
            diagnostics.append(
                VaultDiagnostic(
                    code="duplicate_path",
                    path=payload.path,
                    message=f"duplicate vault path skipped: {payload.path}",
                    severity="warning",
                )
            )
            continue
        seen.add(payload.path)
    return diagnostics


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
    "archive_human_note",
    "build_human_workbench_packet",
    "build_source_management_console",
    "create_human_note",
    "list_human_workspace",
    "note_record_id_for",
    "plan_human_vault_import",
    "render_human_workbench_html",
    "update_human_note",
]
