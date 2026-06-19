"""Live local workspace sync helpers for file-primary SophiaGraph operation."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path, PurePosixPath
from time import sleep
from typing import Any, Literal

from sophiagraph.connectors import SourceRegistryEntry
from sophiagraph.contracts.errors import InvalidArgumentError, NotFoundError
from sophiagraph.freshness import (
    FreshnessLedgerEntry,
    FreshnessStatus,
)
from sophiagraph.human import archive_human_note, note_record_id_for
from sophiagraph.models import MemoryNamespace, MemoryRecord
from sophiagraph.storage.base import SophiaGraphStore
from sophiagraph.sync import (
    LocalSyncRequest,
    SyncConflictRecord,
    detect_sync_conflict,
    sync_conflict_from_dict,
    sync_conflict_to_dict,
)
from sophiagraph.vault import VaultFilePayload, VaultImportOptions, import_vault_files
from sophiagraph.workspace import (
    collect_workspace_import_files,
    load_workspace_import_profile,
    load_workspace_metadata,
    open_workspace_store,
)

WorkspaceFileDeltaKind = Literal[
    "created",
    "modified",
    "deleted",
    "renamed",
    "conflict",
]

_WORKSPACE_SYNC_META_KEY = "workspace_sync"


def _utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _normalize_root(root: str | Path) -> Path:
    return Path(root).expanduser().resolve()


def _normalized_root_label(root: Path) -> str:
    return root.as_posix()


def _validate_relative_path(path: str) -> str:
    if not path:
        raise InvalidArgumentError("relative_path is required")
    normalized = PurePosixPath(path).as_posix()
    if (
        normalized.startswith("/")
        or normalized.startswith("../")
        or "/../" in normalized
    ):
        raise InvalidArgumentError("relative_path must stay under the source root")
    return normalized


def _workspace_file_source_id(relative_path: str) -> str:
    return f"workspace-file:{_validate_relative_path(relative_path)}"


def _workspace_root_source_id(source_root: str | Path) -> str:
    normalized = _normalized_root_label(_normalize_root(source_root))
    digest = sha256(normalized.encode("utf-8")).hexdigest()[:16]
    return f"workspace-root:{digest}"


def _combined_hash(payloads: list[VaultFilePayload]) -> str:
    digest = sha256()
    for payload in sorted(payloads, key=lambda item: item.path):
        digest.update(payload.path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(payload.content_hash.encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def _record_text(record: MemoryRecord) -> str:
    if isinstance(record.content, str):
        return record.content
    return str(record.content.get("source_text") or record.content.get("text") or "")


def _record_vault_hash(record: MemoryRecord | None) -> str | None:
    if record is None:
        return None
    vault_meta = record.meta.get("vault")
    if isinstance(vault_meta, dict):
        content_hash = vault_meta.get("content_hash")
        if isinstance(content_hash, str) and content_hash:
            return content_hash
    document_meta = record.meta.get("document")
    if isinstance(document_meta, dict):
        content_hash = document_meta.get("content_hash")
        if isinstance(content_hash, str) and content_hash:
            return content_hash
    return None


def _active_workspace_sync_entry(
    entry: FreshnessLedgerEntry,
    *,
    source_root: Path,
) -> bool:
    meta = dict(entry.meta)
    return (
        entry.source_kind == "file"
        and meta.get(_WORKSPACE_SYNC_META_KEY) is True
        and meta.get("deleted") is not True
        and meta.get("source_root") == _normalized_root_label(source_root)
        and meta.get("relative_path") == _relative_path_from_source_id(entry.source_id)
    )


def _relative_path_from_source_id(source_id: str) -> str:
    if not source_id.startswith("workspace-file:"):
        raise InvalidArgumentError(
            "workspace file source ids must start with workspace-file:"
        )
    return _validate_relative_path(source_id.split("workspace-file:", 1)[1])


def _entry_sort_key(entry: FreshnessLedgerEntry) -> tuple[str, str]:
    return (entry.updated_at, entry.ledger_id)


def _record_for_entry(
    store: SophiaGraphStore,
    entry: FreshnessLedgerEntry,
) -> MemoryRecord | None:
    for record_id in entry.record_ids:
        record = store.get_record(record_id)
        if record is not None:
            return record
    return None


def _workspace_sync_options(
    workspace_root: str | Path,
) -> tuple[SophiaGraphStore, Any, Any]:
    metadata = load_workspace_metadata(workspace_root)
    profile = load_workspace_import_profile(workspace_root)
    store = open_workspace_store(workspace_root)
    return store, metadata, profile


def _vault_import_options(metadata: Any, profile: Any) -> VaultImportOptions:
    return VaultImportOptions(
        vault_id=profile.vault_id,
        namespace=metadata.namespace,
        scope=metadata.scope,
        root_label=profile.root_label,
        tombstone_missing=False,
    )


def _root_source_entry(
    *,
    namespace: MemoryNamespace,
    source_root: Path,
    cursor: str | None,
    content_hash: str | None,
    updated_at: str,
    created_at: str,
) -> SourceRegistryEntry:
    return SourceRegistryEntry(
        source_id=_workspace_root_source_id(source_root),
        source_type="file",
        namespace=namespace,
        display_name=source_root.name or "workspace-root",
        permission_scope="read_write",
        cursor=cursor,
        content_hash=content_hash,
        provenance={
            _WORKSPACE_SYNC_META_KEY: True,
            "source_root": _normalized_root_label(source_root),
        },
        created_at=created_at,
        updated_at=updated_at,
    )


def _workspace_sync_entries(
    store: SophiaGraphStore,
    *,
    namespace: MemoryNamespace,
    source_root: Path,
) -> dict[str, FreshnessLedgerEntry]:
    entries = store.list_freshness_entries(
        namespaces=[namespace],
        source_kind="file",
        limit=None,
    )
    by_path: dict[str, FreshnessLedgerEntry] = {}
    for entry in entries:
        if not _active_workspace_sync_entry(entry, source_root=source_root):
            continue
        path = _relative_path_from_source_id(entry.source_id)
        previous = by_path.get(path)
        if previous is None or _entry_sort_key(entry) > _entry_sort_key(previous):
            by_path[path] = entry
    return by_path


def _sync_request_for_entry(
    *,
    namespace: MemoryNamespace,
    entry: FreshnessLedgerEntry,
    path: str,
    current_file_hash: str | None,
    current_record_hash: str | None,
) -> LocalSyncRequest:
    return LocalSyncRequest(
        mode="file_primary",
        namespace=namespace,
        source_id=entry.source_id,
        path=path,
        record_id=entry.record_ids[0] if entry.record_ids else None,
        previous_file_hash=entry.content_hash,
        previous_record_hash=entry.content_hash,
        current_file_hash=current_file_hash,
        current_record_hash=current_record_hash,
    )


def _markdown_for_note(
    *,
    title: str,
    body: str,
    tags: tuple[str, ...],
) -> str:
    lines = ["---", f"title: {title}"]
    if tags:
        lines.append("tags:")
        for tag in tags:
            lines.append(f"  - {tag}")
    lines.extend(["---", f"# {title}", "", body.rstrip(), ""])
    return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class WorkspaceSourceLedgerEntry:
    namespace: MemoryNamespace
    relative_path: str
    source_id: str
    status: FreshnessStatus
    content_hash: str | None = None
    observed_mtime: str | None = None
    updated_at: str = ""
    record_ids: tuple[str, ...] = ()
    file_kind: str = "markdown"
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "relative_path", _validate_relative_path(self.relative_path)
        )
        if not isinstance(self.namespace, MemoryNamespace):
            raise TypeError("namespace must be MemoryNamespace")
        if not self.source_id:
            raise InvalidArgumentError("source_id is required")
        if self.status not in {"fresh", "stale", "pending", "failed", "unknown"}:
            raise InvalidArgumentError(f"invalid status: {self.status!r}")

    def to_freshness_entry(self, *, source_root: str | Path) -> FreshnessLedgerEntry:
        root = _normalize_root(source_root)
        return FreshnessLedgerEntry.create(
            namespace=self.namespace,
            source_kind="file",
            source_id=self.source_id,
            status=self.status,
            cursor=self.observed_mtime,
            content_hash=self.content_hash,
            updated_at=self.updated_at,
            record_ids=list(self.record_ids),
            meta={
                **dict(self.meta),
                _WORKSPACE_SYNC_META_KEY: True,
                "relative_path": self.relative_path,
                "file_kind": self.file_kind,
                "source_root": _normalized_root_label(root),
            },
        )

    @classmethod
    def from_freshness_entry(
        cls, entry: FreshnessLedgerEntry
    ) -> "WorkspaceSourceLedgerEntry":
        meta = dict(entry.meta)
        relative_path = str(
            meta.get("relative_path") or _relative_path_from_source_id(entry.source_id)
        )
        file_kind = str(
            meta.get("file_kind")
            or Path(relative_path).suffix.lstrip(".")
            or "markdown"
        )
        extra_meta = {
            key: value
            for key, value in meta.items()
            if key
            not in {
                _WORKSPACE_SYNC_META_KEY,
                "relative_path",
                "file_kind",
                "source_root",
            }
        }
        return cls(
            namespace=entry.namespace,
            relative_path=relative_path,
            source_id=entry.source_id,
            status=entry.status,
            content_hash=entry.content_hash,
            observed_mtime=entry.cursor,
            updated_at=entry.updated_at,
            record_ids=tuple(entry.record_ids),
            file_kind=file_kind,
            meta=extra_meta,
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["namespace"] = self.namespace.as_dict()
        payload["record_ids"] = list(self.record_ids)
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorkspaceSourceLedgerEntry":
        payload = dict(data)
        payload["namespace"] = MemoryNamespace.from_dict(payload["namespace"])
        payload["record_ids"] = tuple(payload.get("record_ids", ()))
        return cls(**payload)


@dataclass(frozen=True, slots=True)
class WorkspaceFileDelta:
    kind: WorkspaceFileDeltaKind
    relative_path: str
    source_id: str
    content_hash: str | None = None
    modified_at: str | None = None
    previous_relative_path: str | None = None
    previous_content_hash: str | None = None
    file_kind: str = "markdown"
    record_ids: tuple[str, ...] = ()
    conflict: SyncConflictRecord | None = None
    reason: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "relative_path", _validate_relative_path(self.relative_path)
        )
        if self.previous_relative_path is not None:
            object.__setattr__(
                self,
                "previous_relative_path",
                _validate_relative_path(self.previous_relative_path),
            )
        if self.kind not in {"created", "modified", "deleted", "renamed", "conflict"}:
            raise InvalidArgumentError(f"invalid delta kind: {self.kind!r}")
        if not self.source_id:
            raise InvalidArgumentError("source_id is required")
        if self.kind == "renamed" and not self.previous_relative_path:
            raise InvalidArgumentError("renamed deltas require previous_relative_path")
        if self.kind == "conflict" and self.conflict is None:
            raise InvalidArgumentError("conflict deltas require a SyncConflictRecord")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["record_ids"] = list(self.record_ids)
        if self.conflict is not None:
            payload["conflict"] = sync_conflict_to_dict(self.conflict)
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorkspaceFileDelta":
        payload = dict(data)
        payload["record_ids"] = tuple(payload.get("record_ids", ()))
        if isinstance(payload.get("conflict"), dict):
            payload["conflict"] = sync_conflict_from_dict(payload["conflict"])
        return cls(**payload)


@dataclass(frozen=True, slots=True)
class WorkspaceSyncPlan:
    workspace_root: str
    source_root: str
    namespace: MemoryNamespace
    observed_at: str
    deltas: tuple[WorkspaceFileDelta, ...] = ()
    tracked_count: int = 0
    unchanged_count: int = 0

    def __post_init__(self) -> None:
        if not self.workspace_root:
            raise InvalidArgumentError("workspace_root is required")
        if not self.source_root:
            raise InvalidArgumentError("source_root is required")
        if not isinstance(self.namespace, MemoryNamespace):
            raise TypeError("namespace must be MemoryNamespace")
        if not self.observed_at:
            raise InvalidArgumentError("observed_at is required")

    @property
    def created_count(self) -> int:
        return sum(1 for delta in self.deltas if delta.kind == "created")

    @property
    def modified_count(self) -> int:
        return sum(1 for delta in self.deltas if delta.kind == "modified")

    @property
    def deleted_count(self) -> int:
        return sum(1 for delta in self.deltas if delta.kind == "deleted")

    @property
    def renamed_count(self) -> int:
        return sum(1 for delta in self.deltas if delta.kind == "renamed")

    @property
    def conflict_count(self) -> int:
        return sum(1 for delta in self.deltas if delta.kind == "conflict")

    def to_dict(self) -> dict[str, Any]:
        return {
            "workspace_root": self.workspace_root,
            "source_root": self.source_root,
            "namespace": self.namespace.as_dict(),
            "observed_at": self.observed_at,
            "deltas": [delta.to_dict() for delta in self.deltas],
            "tracked_count": self.tracked_count,
            "unchanged_count": self.unchanged_count,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorkspaceSyncPlan":
        return cls(
            workspace_root=str(data["workspace_root"]),
            source_root=str(data["source_root"]),
            namespace=MemoryNamespace.from_dict(data["namespace"]),
            observed_at=str(data["observed_at"]),
            deltas=tuple(
                WorkspaceFileDelta.from_dict(item) for item in data.get("deltas", [])
            ),
            tracked_count=int(data.get("tracked_count", 0)),
            unchanged_count=int(data.get("unchanged_count", 0)),
        )


@dataclass(frozen=True, slots=True)
class WorkspaceSyncApplyResult:
    workspace_root: str
    source_root: str
    namespace: MemoryNamespace
    applied_at: str
    plan: WorkspaceSyncPlan
    imported_paths: tuple[str, ...] = ()
    stale_paths: tuple[str, ...] = ()
    conflict_ids: tuple[str, ...] = ()
    ledger_ids: tuple[str, ...] = ()
    path_record_ids: dict[str, str] = field(default_factory=dict)
    source_entry_id: str | None = None

    def __post_init__(self) -> None:
        if not self.applied_at:
            raise InvalidArgumentError("applied_at is required")

    def to_dict(self) -> dict[str, Any]:
        return {
            "workspace_root": self.workspace_root,
            "source_root": self.source_root,
            "namespace": self.namespace.as_dict(),
            "applied_at": self.applied_at,
            "plan": self.plan.to_dict(),
            "imported_paths": list(self.imported_paths),
            "stale_paths": list(self.stale_paths),
            "conflict_ids": list(self.conflict_ids),
            "ledger_ids": list(self.ledger_ids),
            "path_record_ids": dict(self.path_record_ids),
            "source_entry_id": self.source_entry_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorkspaceSyncApplyResult":
        return cls(
            workspace_root=str(data["workspace_root"]),
            source_root=str(data["source_root"]),
            namespace=MemoryNamespace.from_dict(data["namespace"]),
            applied_at=str(data["applied_at"]),
            plan=WorkspaceSyncPlan.from_dict(data["plan"]),
            imported_paths=tuple(data.get("imported_paths", ())),
            stale_paths=tuple(data.get("stale_paths", ())),
            conflict_ids=tuple(data.get("conflict_ids", ())),
            ledger_ids=tuple(data.get("ledger_ids", ())),
            path_record_ids=dict(data.get("path_record_ids", {})),
            source_entry_id=data.get("source_entry_id"),
        )


@dataclass(frozen=True, slots=True)
class WorkspaceSyncStatus:
    workspace_root: str
    source_root: str
    namespace: MemoryNamespace
    tracked_count: int
    active_file_count: int
    fresh_count: int
    stale_count: int
    failed_count: int
    open_conflict_count: int
    pending_delta_count: int
    last_scan_at: str | None = None
    latest_change_cursor: int | None = None
    source_entry_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "workspace_root": self.workspace_root,
            "source_root": self.source_root,
            "namespace": self.namespace.as_dict(),
            "tracked_count": self.tracked_count,
            "active_file_count": self.active_file_count,
            "fresh_count": self.fresh_count,
            "stale_count": self.stale_count,
            "failed_count": self.failed_count,
            "open_conflict_count": self.open_conflict_count,
            "pending_delta_count": self.pending_delta_count,
            "last_scan_at": self.last_scan_at,
            "latest_change_cursor": self.latest_change_cursor,
            "source_entry_id": self.source_entry_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorkspaceSyncStatus":
        return cls(
            workspace_root=str(data["workspace_root"]),
            source_root=str(data["source_root"]),
            namespace=MemoryNamespace.from_dict(data["namespace"]),
            tracked_count=int(data["tracked_count"]),
            active_file_count=int(data["active_file_count"]),
            fresh_count=int(data["fresh_count"]),
            stale_count=int(data["stale_count"]),
            failed_count=int(data["failed_count"]),
            open_conflict_count=int(data["open_conflict_count"]),
            pending_delta_count=int(data["pending_delta_count"]),
            last_scan_at=data.get("last_scan_at"),
            latest_change_cursor=data.get("latest_change_cursor"),
            source_entry_id=data.get("source_entry_id"),
        )


@dataclass(frozen=True, slots=True)
class WorkspaceFilePrimaryNoteOptions:
    note_key: str
    title: str
    body: str
    tags: tuple[str, ...] = ()
    relative_path: str | None = None

    def __post_init__(self) -> None:
        if not self.note_key:
            raise InvalidArgumentError("note_key is required")
        if not self.title:
            raise InvalidArgumentError("title is required")
        if not self.body:
            raise InvalidArgumentError("body is required")
        if self.relative_path is not None:
            object.__setattr__(
                self, "relative_path", _validate_relative_path(self.relative_path)
            )


@dataclass(frozen=True, slots=True)
class WorkspaceFilePrimaryNoteResult:
    relative_path: str
    record_id: str
    written_at: str
    apply_result: WorkspaceSyncApplyResult

    def to_dict(self) -> dict[str, Any]:
        return {
            "relative_path": self.relative_path,
            "record_id": self.record_id,
            "written_at": self.written_at,
            "apply_result": self.apply_result.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorkspaceFilePrimaryNoteResult":
        return cls(
            relative_path=str(data["relative_path"]),
            record_id=str(data["record_id"]),
            written_at=str(data["written_at"]),
            apply_result=WorkspaceSyncApplyResult.from_dict(data["apply_result"]),
        )


@dataclass(frozen=True, slots=True)
class WorkspacePollCycle:
    cycle_index: int
    status: WorkspaceSyncStatus
    plan: WorkspaceSyncPlan
    apply_result: WorkspaceSyncApplyResult | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "cycle_index": self.cycle_index,
            "status": self.status.to_dict(),
            "plan": self.plan.to_dict(),
            "apply_result": None
            if self.apply_result is None
            else self.apply_result.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorkspacePollCycle":
        apply_result_data = data.get("apply_result")
        return cls(
            cycle_index=int(data["cycle_index"]),
            status=WorkspaceSyncStatus.from_dict(data["status"]),
            plan=WorkspaceSyncPlan.from_dict(data["plan"]),
            apply_result=None
            if apply_result_data is None
            else WorkspaceSyncApplyResult.from_dict(apply_result_data),
        )


def _build_file_payload_map(source_root: Path) -> dict[str, VaultFilePayload]:
    return {
        payload.path: payload for payload in collect_workspace_import_files(source_root)
    }


def scan_workspace_sync(
    workspace_root: str | Path,
    source_root: str | Path,
) -> WorkspaceSyncPlan:
    source_root_path = _normalize_root(source_root)
    store, metadata, _profile = _workspace_sync_options(workspace_root)
    observed_at = _utc_now_iso()
    payloads = _build_file_payload_map(source_root_path)
    ledger_by_path = _workspace_sync_entries(
        store,
        namespace=metadata.namespace,
        source_root=source_root_path,
    )

    deltas: list[WorkspaceFileDelta] = []
    unchanged = 0
    created_candidates: list[WorkspaceFileDelta] = []
    deleted_candidates: list[WorkspaceFileDelta] = []

    for path, payload in sorted(payloads.items()):
        entry = ledger_by_path.get(path)
        if entry is None:
            created_candidates.append(
                WorkspaceFileDelta(
                    kind="created",
                    relative_path=path,
                    source_id=_workspace_file_source_id(path),
                    content_hash=payload.content_hash,
                    modified_at=payload.modified_at,
                    file_kind=str(payload.file_kind),
                    reason="path not present in source ledger",
                )
            )
            continue
        record = _record_for_entry(store, entry)
        record_hash = _record_vault_hash(record)
        if record is None and entry.record_ids:
            deltas.append(
                WorkspaceFileDelta(
                    kind="modified",
                    relative_path=path,
                    source_id=entry.source_id,
                    content_hash=payload.content_hash,
                    modified_at=payload.modified_at,
                    previous_content_hash=entry.content_hash,
                    file_kind=str(payload.file_kind),
                    record_ids=tuple(entry.record_ids),
                    reason="file remains authoritative; index record is missing and must be rebuilt",
                )
            )
            continue
        if payload.content_hash == entry.content_hash and (
            record_hash is None or record_hash == entry.content_hash
        ):
            unchanged += 1
            continue
        if payload.content_hash == entry.content_hash and record_hash not in {
            None,
            entry.content_hash,
        }:
            conflict = detect_sync_conflict(
                _sync_request_for_entry(
                    namespace=metadata.namespace,
                    entry=entry,
                    path=path,
                    current_file_hash=payload.content_hash,
                    current_record_hash=record_hash,
                ),
                observed_at=observed_at,
            ).conflict
            assert conflict is not None
            deltas.append(
                WorkspaceFileDelta(
                    kind="conflict",
                    relative_path=path,
                    source_id=entry.source_id,
                    content_hash=payload.content_hash,
                    modified_at=payload.modified_at,
                    previous_content_hash=entry.content_hash,
                    file_kind=str(payload.file_kind),
                    record_ids=tuple(entry.record_ids),
                    conflict=conflict,
                    reason="database index changed independently since the last file ledger state",
                )
            )
            continue
        if record_hash not in {None, entry.content_hash}:
            conflict = detect_sync_conflict(
                _sync_request_for_entry(
                    namespace=metadata.namespace,
                    entry=entry,
                    path=path,
                    current_file_hash=payload.content_hash,
                    current_record_hash=record_hash,
                ),
                observed_at=observed_at,
            ).conflict
            assert conflict is not None
            deltas.append(
                WorkspaceFileDelta(
                    kind="conflict",
                    relative_path=path,
                    source_id=entry.source_id,
                    content_hash=payload.content_hash,
                    modified_at=payload.modified_at,
                    previous_content_hash=entry.content_hash,
                    file_kind=str(payload.file_kind),
                    record_ids=tuple(entry.record_ids),
                    conflict=conflict,
                    reason="file and index both changed since the previous synced hash",
                )
            )
            continue
        deltas.append(
            WorkspaceFileDelta(
                kind="modified",
                relative_path=path,
                source_id=entry.source_id,
                content_hash=payload.content_hash,
                modified_at=payload.modified_at,
                previous_content_hash=entry.content_hash,
                file_kind=str(payload.file_kind),
                record_ids=tuple(entry.record_ids),
                reason="file content hash changed",
            )
        )

    for path, entry in sorted(ledger_by_path.items()):
        if path in payloads:
            continue
        record = _record_for_entry(store, entry)
        record_hash = _record_vault_hash(record)
        if record_hash not in {None, entry.content_hash}:
            conflict = detect_sync_conflict(
                _sync_request_for_entry(
                    namespace=metadata.namespace,
                    entry=entry,
                    path=path,
                    current_file_hash=None,
                    current_record_hash=record_hash,
                ),
                observed_at=observed_at,
            ).conflict
            assert conflict is not None
            deltas.append(
                WorkspaceFileDelta(
                    kind="conflict",
                    relative_path=path,
                    source_id=entry.source_id,
                    previous_content_hash=entry.content_hash,
                    file_kind=entry.meta.get("file_kind", "markdown"),
                    record_ids=tuple(entry.record_ids),
                    conflict=conflict,
                    reason="file disappeared while the index changed independently",
                )
            )
            continue
        deleted_candidates.append(
            WorkspaceFileDelta(
                kind="deleted",
                relative_path=path,
                source_id=entry.source_id,
                previous_content_hash=entry.content_hash,
                file_kind=entry.meta.get("file_kind", "markdown"),
                record_ids=tuple(entry.record_ids),
                reason="tracked file is no longer present under the source root",
            )
        )

    created_by_hash: dict[str, list[WorkspaceFileDelta]] = {}
    deleted_by_hash: dict[str, list[WorkspaceFileDelta]] = {}
    for delta in created_candidates:
        created_by_hash.setdefault(delta.content_hash or "", []).append(delta)
    for delta in deleted_candidates:
        deleted_by_hash.setdefault(delta.previous_content_hash or "", []).append(delta)

    consumed_created: set[str] = set()
    consumed_deleted: set[str] = set()
    for content_hash, created_rows in sorted(created_by_hash.items()):
        deleted_rows = deleted_by_hash.get(content_hash, [])
        if not deleted_rows or not content_hash:
            continue
        for deleted_row, created_row in zip(
            sorted(deleted_rows, key=lambda item: item.relative_path),
            sorted(created_rows, key=lambda item: item.relative_path),
        ):
            consumed_deleted.add(deleted_row.relative_path)
            consumed_created.add(created_row.relative_path)
            deltas.append(
                WorkspaceFileDelta(
                    kind="renamed",
                    relative_path=created_row.relative_path,
                    previous_relative_path=deleted_row.relative_path,
                    source_id=created_row.source_id,
                    content_hash=created_row.content_hash,
                    modified_at=created_row.modified_at,
                    previous_content_hash=deleted_row.previous_content_hash,
                    file_kind=created_row.file_kind,
                    record_ids=deleted_row.record_ids,
                    reason="hash-first rename pairing over deleted and created paths",
                )
            )

    deltas.extend(
        delta
        for delta in created_candidates
        if delta.relative_path not in consumed_created
    )
    deltas.extend(
        delta
        for delta in deleted_candidates
        if delta.relative_path not in consumed_deleted
    )
    deltas.sort(
        key=lambda delta: (
            delta.relative_path,
            delta.previous_relative_path or "",
            delta.kind,
        )
    )
    return WorkspaceSyncPlan(
        workspace_root=str(_normalize_root(workspace_root)),
        source_root=str(source_root_path),
        namespace=metadata.namespace,
        observed_at=observed_at,
        deltas=tuple(deltas),
        tracked_count=len(ledger_by_path),
        unchanged_count=unchanged,
    )


def _put_workspace_sync_entry(
    store: SophiaGraphStore,
    *,
    namespace: MemoryNamespace,
    source_root: Path,
    relative_path: str,
    file_kind: str,
    content_hash: str | None,
    observed_mtime: str | None,
    updated_at: str,
    record_ids: tuple[str, ...],
    status: FreshnessStatus,
    meta: dict[str, Any] | None = None,
) -> str:
    entry = WorkspaceSourceLedgerEntry(
        namespace=namespace,
        relative_path=relative_path,
        source_id=_workspace_file_source_id(relative_path),
        status=status,
        content_hash=content_hash,
        observed_mtime=observed_mtime,
        updated_at=updated_at,
        record_ids=record_ids,
        file_kind=file_kind,
        meta=dict(meta or {}),
    ).to_freshness_entry(source_root=source_root)
    return store.put_freshness_entry(entry)


def apply_workspace_sync(
    workspace_root: str | Path,
    source_root: str | Path,
    *,
    plan: WorkspaceSyncPlan | None = None,
) -> WorkspaceSyncApplyResult:
    source_root_path = _normalize_root(source_root)
    store, metadata, profile = _workspace_sync_options(workspace_root)
    active_plan = plan or scan_workspace_sync(workspace_root, source_root_path)
    payloads = _build_file_payload_map(source_root_path)
    applied_at = _utc_now_iso()

    import_payloads: list[VaultFilePayload] = []
    stale_paths: list[str] = []
    conflict_ids: list[str] = []
    ledger_ids: list[str] = []
    renamed_old_by_new: dict[str, WorkspaceFileDelta] = {}
    delta_by_path = {delta.relative_path: delta for delta in active_plan.deltas}

    for delta in active_plan.deltas:
        if delta.kind == "conflict":
            assert delta.conflict is not None
            store.put_sync_conflict(delta.conflict)
            conflict_ids.append(delta.conflict.conflict_id)
            continue
        if delta.kind == "deleted":
            import_payloads.append(
                VaultFilePayload(
                    path=delta.relative_path,
                    deleted=True,
                    file_kind=delta.file_kind,
                )
            )
            stale_paths.append(delta.relative_path)
            continue
        if delta.kind == "renamed":
            renamed_old_by_new[delta.relative_path] = delta
            import_payloads.append(
                VaultFilePayload(
                    path=delta.previous_relative_path or delta.relative_path,
                    deleted=True,
                    file_kind=delta.file_kind,
                )
            )
            stale_paths.append(delta.previous_relative_path or delta.relative_path)
        payload = payloads.get(delta.relative_path)
        if payload is None:
            raise NotFoundError(
                f"source file not found during apply: {delta.relative_path}"
            )
        import_payloads.append(payload)

    path_record_ids: dict[str, str] = {}
    imported_paths: list[str] = []
    if import_payloads:
        result = import_vault_files(
            store,
            import_payloads,
            _vault_import_options(metadata, profile),
        )
        for file in result.manifest.files:
            delta = delta_by_path.get(file.path)
            if delta is not None and not file.is_deleted and file.record_id is not None:
                path_record_ids[file.path] = file.record_id
                imported_paths.append(file.path)
                ledger_ids.append(
                    _put_workspace_sync_entry(
                        store,
                        namespace=metadata.namespace,
                        source_root=source_root_path,
                        relative_path=file.path,
                        file_kind=file.file_kind,
                        content_hash=file.content_hash,
                        observed_mtime=file.modified_at,
                        updated_at=applied_at,
                        record_ids=(file.record_id,),
                        status="fresh",
                    )
                )
                rename_delta = renamed_old_by_new.get(file.path)
                if (
                    rename_delta is not None
                    and rename_delta.previous_relative_path is not None
                ):
                    ledger_ids.append(
                        _put_workspace_sync_entry(
                            store,
                            namespace=metadata.namespace,
                            source_root=source_root_path,
                            relative_path=rename_delta.previous_relative_path,
                            file_kind=rename_delta.file_kind,
                            content_hash=rename_delta.previous_content_hash,
                            observed_mtime=None,
                            updated_at=applied_at,
                            record_ids=rename_delta.record_ids,
                            status="stale",
                            meta={"superseded_by": file.path, "deleted": True},
                        )
                    )
            elif file.is_deleted:
                delta = delta_by_path.get(file.path)
                if delta is not None:
                    ledger_ids.append(
                        _put_workspace_sync_entry(
                            store,
                            namespace=metadata.namespace,
                            source_root=source_root_path,
                            relative_path=file.path,
                            file_kind=file.file_kind,
                            content_hash=file.content_hash,
                            observed_mtime=file.modified_at,
                            updated_at=applied_at,
                            record_ids=delta.record_ids,
                            status="stale",
                            meta={"deleted": True},
                        )
                    )
    current_payloads = collect_workspace_import_files(source_root_path)
    existing_source_entry = store.get_source_entry(
        _workspace_root_source_id(source_root_path)
    )
    source_entry = _root_source_entry(
        namespace=metadata.namespace,
        source_root=source_root_path,
        cursor=applied_at,
        content_hash=_combined_hash(current_payloads),
        updated_at=applied_at,
        created_at=(
            existing_source_entry.created_at
            if existing_source_entry is not None
            else applied_at
        ),
    )
    source_entry_id = store.put_source_entry(source_entry)
    return WorkspaceSyncApplyResult(
        workspace_root=str(_normalize_root(workspace_root)),
        source_root=str(source_root_path),
        namespace=metadata.namespace,
        applied_at=applied_at,
        plan=active_plan,
        imported_paths=tuple(sorted(imported_paths)),
        stale_paths=tuple(sorted(stale_paths)),
        conflict_ids=tuple(sorted(conflict_ids)),
        ledger_ids=tuple(sorted(ledger_ids)),
        path_record_ids=path_record_ids,
        source_entry_id=source_entry_id,
    )


def workspace_sync_status(
    workspace_root: str | Path,
    source_root: str | Path,
    *,
    plan: WorkspaceSyncPlan | None = None,
) -> WorkspaceSyncStatus:
    source_root_path = _normalize_root(source_root)
    store, metadata, _profile = _workspace_sync_options(workspace_root)
    entries = list(
        _workspace_sync_entries(
            store, namespace=metadata.namespace, source_root=source_root_path
        ).values()
    )
    fresh_count = sum(1 for entry in entries if entry.status == "fresh")
    stale_count = sum(1 for entry in entries if entry.status == "stale")
    failed_count = sum(1 for entry in entries if entry.status == "failed")
    last_scan_at = max(
        (entry.updated_at for entry in entries if entry.updated_at), default=None
    )
    latest_cursor = max(
        (
            event.cursor or 0
            for event in store.list_changes(namespaces=[metadata.namespace], limit=None)
        ),
        default=None,
    )
    root_source_id = _workspace_root_source_id(source_root_path)
    source_entry = store.get_source_entry(root_source_id)
    active_plan = plan or scan_workspace_sync(workspace_root, source_root_path)
    open_conflict_count = len(
        [
            conflict
            for conflict in store.list_sync_conflicts(
                namespaces=[metadata.namespace],
                status="open",
                limit=None,
            )
            if conflict.source_id.startswith("workspace-file:")
        ]
    )
    return WorkspaceSyncStatus(
        workspace_root=str(_normalize_root(workspace_root)),
        source_root=str(source_root_path),
        namespace=metadata.namespace,
        tracked_count=len(entries),
        active_file_count=fresh_count,
        fresh_count=fresh_count,
        stale_count=stale_count,
        failed_count=failed_count,
        open_conflict_count=open_conflict_count,
        pending_delta_count=len(active_plan.deltas),
        last_scan_at=last_scan_at
        or (source_entry.updated_at if source_entry else None),
        latest_change_cursor=latest_cursor,
        source_entry_id=source_entry.source_id if source_entry is not None else None,
    )


def poll_workspace_sync(
    workspace_root: str | Path,
    source_root: str | Path,
    *,
    cycles: int = 1,
    interval_seconds: float = 0.0,
    apply_changes: bool = False,
) -> tuple[WorkspacePollCycle, ...]:
    if cycles <= 0:
        raise InvalidArgumentError("cycles must be positive")
    if interval_seconds < 0:
        raise InvalidArgumentError("interval_seconds must be non-negative")
    cycles_out: list[WorkspacePollCycle] = []
    for cycle_index in range(cycles):
        plan = scan_workspace_sync(workspace_root, source_root)
        apply_result = (
            apply_workspace_sync(workspace_root, source_root, plan=plan)
            if apply_changes and plan.deltas
            else None
        )
        status = workspace_sync_status(workspace_root, source_root, plan=plan)
        cycles_out.append(
            WorkspacePollCycle(
                cycle_index=cycle_index,
                status=status,
                plan=plan,
                apply_result=apply_result,
            )
        )
        if cycle_index + 1 < cycles:
            sleep(interval_seconds)
    return tuple(cycles_out)


def _update_record_human_note_meta(
    store: SophiaGraphStore,
    *,
    record_id: str,
    note_key: str,
) -> MemoryRecord:
    record = store.get_record(record_id)
    if record is None:
        raise NotFoundError(f"record not found after sync: {record_id}")
    updated = replace(
        record,
        meta={
            **dict(record.meta),
            "human_note": {
                **dict(record.meta.get("human_note") or {}),
                "note_key": note_key,
                "workspace": "local_human_notes",
                "archived": False,
            },
        },
    )
    store.put_record(updated)
    return updated


def _archive_legacy_note_if_needed(
    store: SophiaGraphStore,
    *,
    scope: str,
    namespace: MemoryNamespace,
    note_key: str,
    replacement_record_id: str,
) -> None:
    legacy_id = note_record_id_for(scope, namespace, note_key)
    if legacy_id == replacement_record_id:
        return
    legacy_record = store.get_record(legacy_id)
    if legacy_record is None:
        return
    note_meta = legacy_record.meta.get("human_note")
    if not isinstance(note_meta, dict):
        return
    archive_human_note(
        store,
        record_id=legacy_id,
        archived_at=_utc_now_iso(),
        reason="materialized into file-primary workspace sync record",
    )


def workspace_file_primary_note_put(
    workspace_root: str | Path,
    source_root: str | Path,
    *,
    options: WorkspaceFilePrimaryNoteOptions,
) -> WorkspaceFilePrimaryNoteResult:
    source_root_path = _normalize_root(source_root)
    source_root_path.mkdir(parents=True, exist_ok=True)
    relative_path = options.relative_path or f"notes/{options.note_key}.md"
    relative_path = _validate_relative_path(relative_path)
    if not relative_path.endswith(".md"):
        raise InvalidArgumentError("file-primary note paths must end with .md")
    markdown = _markdown_for_note(
        title=options.title,
        body=options.body,
        tags=options.tags,
    )
    target = source_root_path / Path(relative_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    written_at = _utc_now_iso()
    target.write_text(markdown, encoding="utf-8")
    apply_result = apply_workspace_sync(workspace_root, source_root_path)
    record_id = apply_result.path_record_ids.get(relative_path)
    if record_id is None:
        raise NotFoundError(f"synced record missing for {relative_path}")
    store, metadata, _profile = _workspace_sync_options(workspace_root)
    updated = _update_record_human_note_meta(
        store,
        record_id=record_id,
        note_key=options.note_key,
    )
    _archive_legacy_note_if_needed(
        store,
        scope=metadata.scope,
        namespace=metadata.namespace,
        note_key=options.note_key,
        replacement_record_id=updated.id,
    )
    return WorkspaceFilePrimaryNoteResult(
        relative_path=relative_path,
        record_id=updated.id,
        written_at=written_at,
        apply_result=apply_result,
    )


def materialize_workspace_note(
    workspace_root: str | Path,
    source_root: str | Path,
    *,
    record_id: str,
    relative_path: str | None = None,
) -> WorkspaceFilePrimaryNoteResult:
    store, _metadata, _profile = _workspace_sync_options(workspace_root)
    record = store.get_record(record_id)
    if record is None:
        raise NotFoundError(f"record not found: {record_id}")
    note_meta = record.meta.get("human_note")
    if not isinstance(note_meta, dict):
        raise InvalidArgumentError("record is not a human-managed note")
    note_key = str(note_meta.get("note_key") or record.key or record.id)
    return workspace_file_primary_note_put(
        workspace_root,
        source_root,
        options=WorkspaceFilePrimaryNoteOptions(
            note_key=note_key,
            title=str(record.title or note_key),
            body=_record_text(record),
            tags=tuple(record.tags),
            relative_path=relative_path or f"notes/{note_key}.md",
        ),
    )


__all__ = [
    "WorkspaceFileDelta",
    "WorkspaceFileDeltaKind",
    "WorkspaceFilePrimaryNoteOptions",
    "WorkspaceFilePrimaryNoteResult",
    "WorkspacePollCycle",
    "WorkspaceSourceLedgerEntry",
    "WorkspaceSyncApplyResult",
    "WorkspaceSyncPlan",
    "WorkspaceSyncStatus",
    "apply_workspace_sync",
    "materialize_workspace_note",
    "poll_workspace_sync",
    "scan_workspace_sync",
    "workspace_file_primary_note_put",
    "workspace_sync_status",
]
