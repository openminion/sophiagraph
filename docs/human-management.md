# Human Management

Status: semantic alpha
Scope: package-local note, import, and source-management surface

SophiaGraph ships a package-owned human-management layer for local note
workspaces, import dry-runs, and source/freshness inspection without moving
raw-input promotion policy into the package.

## Public root

- `sophiagraph.human`

## What it provides

- deterministic note identifiers via `note_record_id_for(...)`
- note create/update/archive helpers via `create_human_note(...)`,
  `update_human_note(...)`, and `archive_human_note(...)`
- note workspace listing via `list_human_workspace(...)`
- vault-import dry-run planning via `plan_human_vault_import(...)`
- source/freshness/conflict inspection via `build_source_management_console(...)`
- a package-local operating packet via `build_human_workbench_packet(...)`
- a deterministic HTML preview via `render_human_workbench_html(...)`

## Boundary

This surface is local-first and package-owned. It keeps the current SophiaGraph
boundary explicit:

1. humans can manage note-shaped entries intentionally,
2. imports can be previewed before mutation,
3. source and freshness issues can be inspected as typed facts,
4. raw conversation is still source material, not durable graph state by
   default.

Human note and import surfaces should expose the same store capability posture
as agent-created memory. Callers can use
`build_store_capability_report(store)` to show whether a local workspace is
running against durable SQLite, in-memory preview storage, FTS-backed search,
and vector lifecycle metadata before a human applies imports or edits.

This surface does **not** provide:

1. hosted multi-user sync
2. auth or tenancy
3. OpenMinion submission-promotion policy
4. automatic semantic extraction from raw user chat
5. a browser runtime or admin console

## Typed operating packets

The management layer is intentionally packet-first:

- `HumanWorkspaceSnapshot` summarizes note workspace state
- `VaultImportPlan` summarizes dry-run import actions and diagnostics
- `SourceManagementConsole` summarizes source/freshness/conflict posture
- `HumanWorkbenchPacket` bundles those views into one local operating surface

Hosts can render or transport these packets however they want, but the package
owns one canonical local management shape instead of requiring each caller to
reassemble the workflow from lower-level store and import primitives.
