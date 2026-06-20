# Workspace Mode

Status: semantic alpha
Scope: package-local persistent local workspace contract

SophiaGraph now ships a package-owned persistent local workspace posture for
human-managed notes, explicit local file imports, and workbench rendering.

## Public root

- `sophiagraph.workspace`
- `sophiagraph.workspace_sync`

## What it provides

- deterministic workspace metadata via `WorkspaceMetadata`
- stored import defaults via `WorkspaceImportProfile`
- one bounded local workspace layout via `workspace_paths(...)`
- workspace initialization via `initialize_workspace(...)`
- workspace status inspection via `load_workspace_status(...)`
- workspace-backed note upsert via `workspace_note_put(...)`
- explicit local markdown/canvas file collection via
  `collect_workspace_import_files(...)`
- workspace-scoped import planning via `plan_workspace_import(...)`
- workspace-scoped import application via `apply_workspace_import(...)`
- workspace-backed workbench packets via `build_workspace_workbench(...)`
- deterministic HTML rendering via `render_workspace_workbench(...)`
- typed source-ledger DTOs via `WorkspaceSourceLedgerEntry`
- typed drift facts via `WorkspaceFileDelta`
- typed live-sync plans/results/status via
  `WorkspaceSyncPlan`, `WorkspaceSyncApplyResult`, and
  `WorkspaceSyncStatus`
- bounded live-sync polling via `poll_workspace_sync(...)`
- explicit file-primary note/materialize helpers via
  `workspace_file_primary_note_put(...)` and `materialize_workspace_note(...)`

## Workspace layout

Each workspace directory stores:

1. `workspace.json`
2. `import_profile.json`
3. `store/` (SQLite store root; `sophiagraph.sqlite3` remains owned by storage)

## Boundary

This surface is local-first and package-owned.

It does:

1. keep one local SQLite workspace and its defaults together,
2. read explicit local markdown/canvas files from a caller-supplied directory,
3. reuse existing human/vault/source surfaces from the package,
4. let callers reopen the same workspace without reconstructing raw defaults.
5. let callers keep a deterministic file-primary source ledger for one local
   root without introducing a daemon.

It does **not** provide:

1. hosted sync or auth
2. background watching or scheduled imports
3. automatic promotion of raw chat into durable memory
4. semantic extraction from local prose
5. browser runtime or admin console behavior
6. prose-based merge resolution or hidden DB-only writes in file-primary mode

## CLI

Workspace mode is available through `python3.11 -m sophiagraph`:

- `workspace-init`
- `workspace-status`
- `workspace-note-put`
- `workspace-import-plan`
- `workspace-import-apply`
- `workspace-workbench`
- `workspace-sync-plan`
- `workspace-sync-apply`
- `workspace-sync-status`
- `workspace-sync-poll`
- `workspace-file-note-put`
- `workspace-note-materialize`
