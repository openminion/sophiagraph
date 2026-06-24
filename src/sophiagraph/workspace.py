"""Persistent local workspace helpers for package-owned SophiaGraph operation."""

from __future__ import annotations

from datetime import UTC, datetime
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
from sophiagraph.vault import (
    VaultFilePayload,
    VaultImportOptions,
    VaultImportResult,
    build_vault_manifest,
    import_vault_files,
)
from sophiagraph.workspace_types import (
    WORKSPACE_IMPORT_PROFILE_FILE,
    WORKSPACE_METADATA_FILE,
    WORKSPACE_SCHEMA_VERSION,
    WORKSPACE_STORE_DIR,
    WORKSPACE_SUPPORTED_IMPORT_SUFFIXES,
    WorkspaceImportProfile,
    WorkspaceMetadata,
    WorkspacePaths,
    WorkspaceStatusView,
    build_workspace_import_profile,
    build_workspace_metadata,
    json_ready,
    load_workspace_import_profile,
    load_workspace_metadata,
    open_workspace_store,
    save_workspace_import_profile,
    save_workspace_metadata,
    workspace_paths,
)


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
    return json_ready(view)


def workspace_workbench_to_dict(packet: HumanWorkbenchPacket) -> dict[str, Any]:
    return json_ready(packet)


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
