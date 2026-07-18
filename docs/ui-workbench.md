# Local UI Workbench

Status: active

The package-local UI workbench is a deterministic GraphFakos-backed view of
typed SophiaGraph data. It is useful for inspecting records, links, graph
neighborhoods, saved views, candidates, timeline, and schema packets without
running a hosted service. When served live, it can also route allowlisted
actions through the same idempotent package executor used by REST.

## Quick start

```bash
sophiagraph-ui --screen explore --serve --open
```

Write standalone artifacts instead of serving:

```bash
sophiagraph-ui \
  --screen views \
  --html-out sophiagraph-ui-preview.html \
  --artifact-out sophiagraph-artifact.json \
  --embed-out sophiagraph-embed.html \
  --report-out sophiagraph-report.json \
  --markdown-report-out sophiagraph-report.md \
  --json
```

Use a workspace:

```bash
sophiagraph-ui \
  --workspace .sophiagraph-workspace \
  --source-root . \
  --screen graph \
  --serve
```

## Live action posture

The live local server injects the trusted local principal, workspace id, scope,
namespace, workspace root, and source root. Browser payloads cannot choose
actor identity or authorization scope.

Executable actions:

- `approve_candidate`
- `reject_candidate`
- `promote_candidate`
- `save_note`

Preview-only or host-required actions:

- `apply_repair`
- `restore_workspace`
- `build_publish_plan`
- `open_graph_selection`

Review-only actions such as note-edit proposals return explicit unsupported or
review-required status unless a caller has already persisted the canonical
review request. Static HTML export remains read-only and never claims a
mutation was persisted.

## Boundary

The local workbench is not an authenticated hosted product. It is a package
preview, live-action, and artifact-export surface for one trusted local
workspace. Hosted browser delivery, auth, CORS, and multi-user operations
belong in `sophiagraph.server` or a host runtime.

## Generated artifacts

- HTML preview: human-readable local browser output
- graph artifact JSON: replayable graph payload for GraphFakos
- embed HTML: embeddable static preview
- JSON report: machine-readable provider report
- Markdown report: review-friendly report summary
