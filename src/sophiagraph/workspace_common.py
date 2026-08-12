"""Shared helpers for local-workspace sync and note operations."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any

from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.models import MemoryRecord
from sophiagraph.storage.base import SophiaGraphStore
from sophiagraph.workspace import (
    load_workspace_import_profile,
    load_workspace_metadata,
    open_workspace_store,
)


def normalize_workspace_root(root: str | Path) -> Path:
    return Path(root).expanduser().resolve()


def normalize_workspace_relative_path(path: str) -> str:
    if not path:
        raise InvalidArgumentError("relative_path is required")
    normalized = PurePosixPath(path).as_posix()
    if normalized.startswith(("/", "../")) or "/../" in normalized:
        raise InvalidArgumentError("relative_path must stay under the source root")
    return normalized


def record_text(record: MemoryRecord) -> str:
    if isinstance(record.content, str):
        return record.content
    return str(record.content.get("source_text") or record.content.get("text") or "")


def open_workspace_sync_context(
    workspace_root: str | Path,
) -> tuple[SophiaGraphStore, Any, Any]:
    metadata = load_workspace_metadata(workspace_root)
    profile = load_workspace_import_profile(workspace_root)
    store = open_workspace_store(workspace_root)
    return store, metadata, profile


__all__ = [
    "normalize_workspace_relative_path",
    "normalize_workspace_root",
    "open_workspace_sync_context",
    "record_text",
]
