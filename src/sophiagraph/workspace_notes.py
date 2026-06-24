"""File-primary human-note helpers for local workspace operation."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from sophiagraph.contracts.errors import InvalidArgumentError, NotFoundError
from sophiagraph.human import archive_human_note, note_record_id_for
from sophiagraph.models import MemoryNamespace, MemoryRecord
from sophiagraph.storage.base import SophiaGraphStore
from sophiagraph.temporal import utc_now_iso_seconds
from sophiagraph.workspace_common import (
    normalize_workspace_relative_path,
    normalize_workspace_root,
    open_workspace_sync_context,
    record_text,
)

from .workspace_sync import WorkspaceSyncApplyResult, apply_workspace_sync


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
        archived_at=utc_now_iso_seconds(),
        reason="materialized into file-primary workspace sync record",
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
                self,
                "relative_path",
                normalize_workspace_relative_path(self.relative_path),
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


def workspace_file_primary_note_put(
    workspace_root: str | Path,
    source_root: str | Path,
    *,
    options: WorkspaceFilePrimaryNoteOptions,
) -> WorkspaceFilePrimaryNoteResult:
    source_root_path = normalize_workspace_root(source_root)
    source_root_path.mkdir(parents=True, exist_ok=True)
    relative_path = options.relative_path or f"notes/{options.note_key}.md"
    relative_path = normalize_workspace_relative_path(relative_path)
    if not relative_path.endswith(".md"):
        raise InvalidArgumentError("file-primary note paths must end with .md")
    markdown = _markdown_for_note(
        title=options.title,
        body=options.body,
        tags=options.tags,
    )
    target = source_root_path / Path(relative_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    written_at = utc_now_iso_seconds()
    target.write_text(markdown, encoding="utf-8")
    apply_result = apply_workspace_sync(workspace_root, source_root_path)
    record_id = apply_result.path_record_ids.get(relative_path)
    if record_id is None:
        raise NotFoundError(f"synced record missing for {relative_path}")
    store, metadata, _profile = open_workspace_sync_context(workspace_root)
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
    store, _metadata, _profile = open_workspace_sync_context(workspace_root)
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
            body=record_text(record),
            tags=tuple(record.tags),
            relative_path=relative_path or f"notes/{note_key}.md",
        ),
    )


__all__ = [
    "WorkspaceFilePrimaryNoteOptions",
    "WorkspaceFilePrimaryNoteResult",
    "materialize_workspace_note",
    "workspace_file_primary_note_put",
]
