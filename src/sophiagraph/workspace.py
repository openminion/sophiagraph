"""Persistent local workspace helpers for package-owned SophiaGraph operation."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any

from sophiagraph.contracts.errors import (
    ConstraintViolationError,
    InvalidArgumentError,
    NotFoundError,
)
from sophiagraph.human import (
    HumanWorkbenchPacket,
    VaultImportPlan,
    build_human_workbench_packet,
    build_source_management_console,
    create_human_note,
    list_human_workspace,
    plan_human_vault_import,
    render_human_workbench_html,
)
from sophiagraph.models import MemoryNamespace, MemoryRecord
from sophiagraph.storage import (
    SophiaGraphSqliteStore,
    create_sqlite_store,
    default_db_path,
)
from sophiagraph.temporal import utc_now_iso_seconds
from sophiagraph.vault import (
    VaultFilePayload,
    VaultImportOptions,
    VaultImportResult,
    build_vault_manifest,
    import_vault_files,
)

WORKSPACE_SCHEMA_VERSION = "sophiagraph.workspace.v1alpha1"
WORKSPACE_METADATA_FILE = "workspace.json"
WORKSPACE_IMPORT_PROFILE_FILE = "import_profile.json"
WORKSPACE_STORE_DIR = "store"
WORKSPACE_SUPPORTED_IMPORT_SUFFIXES = (".md", ".canvas")

def _json_ready(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, MemoryNamespace):
        return value.as_dict()
    if dataclass_is_instance(value):
        return {key: _json_ready(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    return value


def dataclass_is_instance(value: Any) -> bool:
    return hasattr(value, "__dataclass_fields__")


def _load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise NotFoundError(f"workspace file not found: {path}") from exc


def _write_json(path: Path, payload: dict[str, Any]) -> None:
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
    _write_json(paths.metadata_path, _json_ready(metadata))


def save_workspace_import_profile(
    workspace_root: str | Path, profile: WorkspaceImportProfile
) -> None:
    paths = workspace_paths(workspace_root)
    _write_json(paths.import_profile_path, _json_ready(profile))


def load_workspace_metadata(workspace_root: str | Path) -> WorkspaceMetadata:
    data = _load_json(workspace_paths(workspace_root).metadata_path)
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
    data = _load_json(workspace_paths(workspace_root).import_profile_path)
    return WorkspaceImportProfile(
        vault_id=str(data["vault_id"]),
        root_label=str(data.get("root_label") or "vault"),
        tombstone_missing=bool(data.get("tombstone_missing", False)),
    )


def open_workspace_store(workspace_root: str | Path) -> SophiaGraphSqliteStore:
    paths = workspace_paths(workspace_root)
    paths.store_root.mkdir(parents=True, exist_ok=True)
    return create_sqlite_store(paths.store_root)


def initialize_workspace(
    workspace_root: str | Path,
    *,
    scope: str,
    namespace: MemoryNamespace,
    label: str = "",
    vault_id: str = "",
    root_label: str = "vault",
    tombstone_missing: bool = False,
    overwrite: bool = False,
) -> WorkspaceStatusView:
    paths = workspace_paths(workspace_root)
    metadata = build_workspace_metadata(scope=scope, namespace=namespace, label=label)
    profile = build_workspace_import_profile(
        vault_id=vault_id or (label or paths.root.name),
        root_label=root_label,
        tombstone_missing=tombstone_missing,
    )
    if paths.metadata_path.exists() or paths.import_profile_path.exists():
        existing_metadata = load_workspace_metadata(paths.root)
        existing_profile = load_workspace_import_profile(paths.root)
        if not overwrite and (
            existing_metadata != metadata or existing_profile != profile
        ):
            raise ConstraintViolationError(
                "workspace already initialized with different metadata/profile",
                details={"workspace_root": str(paths.root)},
            )
        if not overwrite:
            return load_workspace_status(paths.root)
    paths.root.mkdir(parents=True, exist_ok=True)
    paths.store_root.mkdir(parents=True, exist_ok=True)
    save_workspace_metadata(paths.root, metadata)
    save_workspace_import_profile(paths.root, profile)
    open_workspace_store(paths.root)
    return load_workspace_status(paths.root)


def load_workspace_status(
    workspace_root: str | Path,
    *,
    include_archived: bool = True,
) -> WorkspaceStatusView:
    paths = workspace_paths(workspace_root)
    metadata = load_workspace_metadata(paths.root)
    profile = load_workspace_import_profile(paths.root)
    store = open_workspace_store(paths.root)
    workspace = list_human_workspace(
        store,
        scope=metadata.scope,
        namespace=metadata.namespace,
        include_archived=include_archived,
    )
    source_console = build_source_management_console(
        store, scope=metadata.scope, namespace=metadata.namespace
    )
    return WorkspaceStatusView(
        metadata=metadata,
        import_profile=profile,
        workspace_root=str(paths.root),
        db_path=str(paths.db_path),
        record_count=store.record_count(),
        candidate_count=store.candidate_count(),
        note_count=workspace.active_count,
        archived_note_count=workspace.archived_count,
        source_count=len(source_console.sources),
        open_conflict_count=source_console.open_conflict_count,
    )


def collect_workspace_import_files(
    source_root: str | Path,
) -> list[VaultFilePayload]:
    root = Path(source_root).expanduser().resolve()
    if not root.is_dir():
        raise NotFoundError(f"source root not found: {root}")
    payloads: list[VaultFilePayload] = []
    for path in sorted(root.rglob("*")):
        if (
            not path.is_file()
            or path.suffix.lower() not in WORKSPACE_SUPPORTED_IMPORT_SUFFIXES
        ):
            continue
        relative = path.relative_to(root).as_posix()
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise InvalidArgumentError(
                f"workspace import only supports utf-8 markdown/canvas text files: {relative}"
            ) from exc
        payloads.append(
            VaultFilePayload(
                path=relative,
                content=content,
                modified_at=datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
                .replace(microsecond=0)
                .isoformat(),
            )
        )
    return payloads


def _workspace_import_options(
    metadata: WorkspaceMetadata,
    profile: WorkspaceImportProfile,
    *,
    tombstone_missing: bool | None = None,
) -> VaultImportOptions:
    return VaultImportOptions(
        vault_id=profile.vault_id,
        namespace=metadata.namespace,
        scope=metadata.scope,
        root_label=profile.root_label,
        tombstone_missing=profile.tombstone_missing
        if tombstone_missing is None
        else tombstone_missing,
    )


def plan_workspace_import(
    workspace_root: str | Path,
    source_root: str | Path,
    *,
    tombstone_missing: bool | None = None,
) -> VaultImportPlan:
    metadata = load_workspace_metadata(workspace_root)
    profile = load_workspace_import_profile(workspace_root)
    files = collect_workspace_import_files(source_root)
    options = _workspace_import_options(
        metadata,
        profile,
        tombstone_missing=tombstone_missing,
    )
    manifest = build_vault_manifest(files, options)
    store = open_workspace_store(workspace_root)
    plan = plan_human_vault_import(store, files, options)
    return VaultImportPlan(
        manifest=manifest,
        items=plan.items,
        created_count=plan.created_count,
        updated_count=plan.updated_count,
        deleted_count=plan.deleted_count,
        unchanged_count=plan.unchanged_count,
        stale_count=plan.stale_count,
        diagnostics=plan.diagnostics,
    )


def apply_workspace_import(
    workspace_root: str | Path,
    source_root: str | Path,
    *,
    tombstone_missing: bool | None = None,
) -> VaultImportResult:
    metadata = load_workspace_metadata(workspace_root)
    profile = load_workspace_import_profile(workspace_root)
    files = collect_workspace_import_files(source_root)
    options = _workspace_import_options(
        metadata,
        profile,
        tombstone_missing=tombstone_missing,
    )
    store = open_workspace_store(workspace_root)
    return import_vault_files(store, files, options)


def workspace_note_put(
    workspace_root: str | Path,
    *,
    note_key: str,
    title: str,
    body: str,
    tags: tuple[str, ...] = (),
    meta: dict[str, Any] | None = None,
) -> MemoryRecord:
    metadata = load_workspace_metadata(workspace_root)
    store = open_workspace_store(workspace_root)
    from sophiagraph.human import HumanNoteInput

    return create_human_note(
        store,
        HumanNoteInput(
            scope=metadata.scope,
            namespace=metadata.namespace,
            note_key=note_key,
            title=title,
            body=body,
            tags=tags,
            meta=meta or {},
        ),
    )


def build_workspace_workbench(
    workspace_root: str | Path,
    *,
    include_archived: bool = False,
    source_root: str | Path | None = None,
    tombstone_missing: bool | None = None,
) -> HumanWorkbenchPacket:
    metadata = load_workspace_metadata(workspace_root)
    profile = load_workspace_import_profile(workspace_root)
    store = open_workspace_store(workspace_root)
    import_files = None
    import_options = None
    if source_root is not None:
        import_files = collect_workspace_import_files(source_root)
        import_options = _workspace_import_options(
            metadata,
            profile,
            tombstone_missing=tombstone_missing,
        )
    return build_human_workbench_packet(
        store,
        scope=metadata.scope,
        namespace=metadata.namespace,
        include_archived_notes=include_archived,
        import_files=import_files,
        import_options=import_options,
    )


def render_workspace_workbench(
    workspace_root: str | Path,
    *,
    include_archived: bool = False,
    source_root: str | Path | None = None,
    tombstone_missing: bool | None = None,
) -> str:
    return render_human_workbench_html(
        build_workspace_workbench(
            workspace_root,
            include_archived=include_archived,
            source_root=source_root,
            tombstone_missing=tombstone_missing,
        )
    )


def workspace_status_to_dict(view: WorkspaceStatusView) -> dict[str, Any]:
    return _json_ready(view)


def workspace_workbench_to_dict(packet: HumanWorkbenchPacket) -> dict[str, Any]:
    return _json_ready(packet)


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
    "apply_workspace_import",
    "build_workspace_import_profile",
    "build_workspace_metadata",
    "build_workspace_workbench",
    "collect_workspace_import_files",
    "initialize_workspace",
    "load_workspace_import_profile",
    "load_workspace_metadata",
    "load_workspace_status",
    "open_workspace_store",
    "plan_workspace_import",
    "render_workspace_workbench",
    "save_workspace_import_profile",
    "save_workspace_metadata",
    "workspace_note_put",
    "workspace_paths",
    "workspace_status_to_dict",
    "workspace_workbench_to_dict",
]
