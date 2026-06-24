# Sophiagraph UI Contracts

Status: semantic alpha
Scope: typed UI boundary contracts plus package-local visual preview

`sophiagraph.ui` is the package-owned typed boundary for deterministic
operator-facing memory and knowledge-graph screens. The package-local preview
now renders through GraphFakos, the shared graph lens package.

The ownership split is explicit:

1. `sophiagraph` owns typed durable-memory contracts and the package-local UI
   boundary surface,
2. `sophiagraph` owns the GraphFakos adapter used for package smoke, demo, and
   visual navigation of one workspace/demo graph,
3. `graphfakos` owns the reusable viewer shell, graph canvas, local server
   primitive, static HTML export, and shared viewer assertions,
4. `sophiagraph-server` or another host runtime owns the hosted browser,
   transport, auth, and operator experience.

## Current contract

- owner import root: `sophiagraph.ui`
- runtime package: `sophiagraph-server`
- transport kind: `rest`
- transport status: `designed_not_implemented`
- current API seam: `sophiagraph-server`
- reusable local server primitive: `graphfakos.server`
- local visual UI seam: `python3.11 -m sophiagraph ui-preview --serve`
- shared viewer package: `graphfakos`

## Screen manifest

The current screen manifest stays intentionally structural:

1. explore
2. record detail
3. graph
4. operations
5. repair
6. candidates
7. views
8. community
9. timeline
10. schema

## Local Visual UI

The package ships a local browser UI command for the GraphFakos-backed
second-brain viewer:

```bash
sophiagraph-ui \
  --screen explore \
  --serve \
  --open
```

Preview the saved-view workbench:

```bash
sophiagraph-ui \
  --screen views \
  --serve
```

Preview an initialized workspace instead of the built-in demo data:

```bash
sophiagraph-ui \
  --workspace <workspace-root> \
  --screen graph \
  --serve
```

Use `--html-out` only when you want a standalone HTML export. The equivalent
module form is `python3.11 -m sophiagraph ui-preview`.

## Boundary

This package does **not** currently ship a hosted browser app, Textual TUI,
daemon, or admin UI. It ships typed UI contracts, deterministic Sophiagraph to
GraphFakos adapter mapping, compatibility wrappers for the local visual server
primitive, and the local visual UI command above so the standalone package has
one canonical import root for future visual/runtime work.
