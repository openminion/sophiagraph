"""Typed workspace metadata, profile, and persistence helpers."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any

from sophiagraph.contracts.errors import InvalidArgumentError, NotFoundError
from sophiagraph.models import MemoryNamespace
from sophiagraph.storage import (
    SophiaGraphSqliteStore,
    create_sqlite_store,
    default_db_path,
)
from sophiagraph.temporal import utc_now_iso_seconds

WORKSPACE_SCHEMA_VERSION = "sophiagraph.workspace.v1alpha1"
WORKSPACE_METADATA_FILE = "workspace.json"
WORKSPACE_IMPORT_PROFILE_FILE = "import_profile.json"
WORKSPACE_STORE_DIR = "store"
WORKSPACE_SUPPORTED_IMPORT_SUFFIXES = (".md", ".canvas")


def dataclass_is_instance(value: Any) -> bool:
    return hasattr(value, "__dataclass_fields__")


def json_ready(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, MemoryNamespace):
        return value.as_dict()
    if dataclass_is_instance(value):
        return {key: json_ready(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_ready(item) for item in value]
    return value


def load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise NotFoundError(f"workspace file not found: {path}") from exc


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


@dataclass(frozen=True, slots=True)
class WorkspacePaths:
    root: Path
    metadata_path: Path
    import_profile_path: Path
    store_root: Path
    db_path: Path


@dataclass(frozen=True, slots=True)
class WorkspaceMetadata:
    scope: str
    namespace: MemoryNamespace
    label: str = ""
    schema_version: str = WORKSPACE_SCHEMA_VERSION
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self) -> None:
        if not self.scope:
            raise InvalidArgumentError("scope is required")
        if not isinstance(self.namespace, MemoryNamespace):
            raise TypeError("namespace must be MemoryNamespace")
        if not self.schema_version:
            raise InvalidArgumentError("schema_version is required")
        if not self.created_at:
            object.__setattr__(self, "created_at", utc_now_iso_seconds())
        if not self.updated_at:
            object.__setattr__(self, "updated_at", self.created_at)


@dataclass(frozen=True, slots=True)
class WorkspaceImportProfile:
    vault_id: str
    root_label: str = "vault"
    tombstone_missing: bool = False

    def __post_init__(self) -> None:
        if not self.vault_id:
            raise InvalidArgumentError("vault_id is required")
        if not self.root_label:
            raise InvalidArgumentError("root_label is required")


@dataclass(frozen=True, slots=True)
class WorkspaceStatusView:
    metadata: WorkspaceMetadata
    import_profile: WorkspaceImportProfile
    workspace_root: str
    db_path: str
    record_count: int
    candidate_count: int
    note_count: int
    archived_note_count: int
    source_count: int
    open_conflict_count: int


def workspace_paths(workspace_root: str | Path) -> WorkspacePaths:
    root = Path(workspace_root).expanduser().resolve()
    store_root = root / WORKSPACE_STORE_DIR
    return WorkspacePaths(
        root=root,
        metadata_path=root / WORKSPACE_METADATA_FILE,
        import_profile_path=root / WORKSPACE_IMPORT_PROFILE_FILE,
        store_root=store_root,
        db_path=default_db_path(store_root),
    )


def build_workspace_metadata(
    *,
    scope: str,
    namespace: MemoryNamespace,
    label: str = "",
    created_at: str = "",
    updated_at: str = "",
) -> WorkspaceMetadata:
    return WorkspaceMetadata(
        scope=scope,
        namespace=namespace,
        label=label,
        created_at=created_at,
        updated_at=updated_at,
    )


def build_workspace_import_profile(
    *,
    vault_id: str,
    root_label: str = "vault",
    tombstone_missing: bool = False,
) -> WorkspaceImportProfile:
    return WorkspaceImportProfile(
        vault_id=vault_id,
        root_label=root_label,
        tombstone_missing=tombstone_missing,
    )


def save_workspace_metadata(
    workspace_root: str | Path, metadata: WorkspaceMetadata
) -> None:
    paths = workspace_paths(workspace_root)
    write_json(paths.metadata_path, json_ready(metadata))


def save_workspace_import_profile(
    workspace_root: str | Path, profile: WorkspaceImportProfile
) -> None:
    paths = workspace_paths(workspace_root)
    write_json(paths.import_profile_path, json_ready(profile))


def load_workspace_metadata(workspace_root: str | Path) -> WorkspaceMetadata:
    data = load_json(workspace_paths(workspace_root).metadata_path)
    return WorkspaceMetadata(
        scope=str(data["scope"]),
        namespace=MemoryNamespace.from_dict(dict(data["namespace"])),
        label=str(data.get("label") or ""),
        schema_version=str(data.get("schema_version") or WORKSPACE_SCHEMA_VERSION),
        created_at=str(data.get("created_at") or ""),
        updated_at=str(data.get("updated_at") or ""),
    )


def load_workspace_import_profile(
    workspace_root: str | Path,
) -> WorkspaceImportProfile:
    data = load_json(workspace_paths(workspace_root).import_profile_path)
    return WorkspaceImportProfile(
        vault_id=str(data["vault_id"]),
        root_label=str(data.get("root_label") or "vault"),
        tombstone_missing=bool(data.get("tombstone_missing", False)),
    )


def open_workspace_store(workspace_root: str | Path) -> SophiaGraphSqliteStore:
    paths = workspace_paths(workspace_root)
    paths.store_root.mkdir(parents=True, exist_ok=True)
    return create_sqlite_store(paths.store_root)


__all__ = [
    "WORKSPACE_IMPORT_PROFILE_FILE",
    "WORKSPACE_METADATA_FILE",
    "WORKSPACE_SCHEMA_VERSION",
    "WORKSPACE_STORE_DIR",
    "WORKSPACE_SUPPORTED_IMPORT_SUFFIXES",
    "WorkspaceImportProfile",
    "WorkspaceMetadata",
    "WorkspacePaths",
    "WorkspaceStatusView",
    "build_workspace_import_profile",
    "build_workspace_metadata",
    "dataclass_is_instance",
    "json_ready",
    "load_json",
    "load_workspace_import_profile",
    "load_workspace_metadata",
    "open_workspace_store",
    "save_workspace_import_profile",
    "save_workspace_metadata",
    "workspace_paths",
    "write_json",
]
