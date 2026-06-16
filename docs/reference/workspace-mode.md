# Workspace Mode

SophiaGraph now ships a package-owned persistent local workspace posture for
human-managed notes, explicit local file imports, and workbench rendering.

## Public root

- `sophiagraph.workspace`

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

It does **not** provide:

1. hosted sync or auth
2. background watching or scheduled imports
3. automatic promotion of raw chat into durable memory
4. semantic extraction from local prose
5. browser runtime or admin console behavior

## CLI

Workspace mode is available through `python3.11 -m sophiagraph`:

- `workspace-init`
- `workspace-status`
- `workspace-note-put`
- `workspace-import-plan`
- `workspace-import-apply`
- `workspace-workbench`
