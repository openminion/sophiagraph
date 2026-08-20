# Local UI Workbench

Status: active

The package-local UI workbench is a deterministic GraphFakos-backed view of
typed SophiaGraph data. It is useful for inspecting records, links, graph
neighborhoods, saved views, candidates, timeline, and schema packets without
running a hosted service. When served live, it can also route allowlisted
actions through the same idempotent package executor used by REST.

The workbench is the Sophiagraph-owned wrapper around the shared GraphFakos
viewer. Sophiagraph supplies durable-memory data, trust fields, workbench action
state, and provenance. GraphFakos supplies the reusable browser shell, graph
canvas, replayable artifact format, and provider-neutral viewer assertions.

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

Run the package-local walkthrough:

```bash
python3.11 examples/ui_workbench_export.py
```

The walkthrough builds a small durable-memory graph, writes a replayable
GraphFakos artifact, renders static HTML, approves a candidate, promotes it,
and prints a compact JSON proof summary.

## Inspector fields

Sophiagraph supplies memory-specific inspector fields through provider payloads
while GraphFakos stays provider-neutral. Record nodes expose stable id, scope,
namespace, type, tier, source, confidence, and evidence references. Candidate
nodes expose candidate id, status, claim key, polarity, source class, proposed
scope, reviewer, and evidence references.

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

## Host integration posture

OpenMinion and other hosts should treat this UI as an inspectable local
second-brain viewer, not as the durable-memory authority. A host can call the
Sophiagraph wrapper to produce a GraphFakos artifact, serve the local preview,
or embed the static preview in its own operator surface. Writes, promotions,
retention, auth, and memory policy still route through Sophiagraph or the host
runtime that owns those decisions.

Third-party graph packages should integrate at the GraphFakos provider contract
instead of copying this Sophiagraph wrapper. The wrapper is intentionally thin:
it translates Sophiagraph records, links, candidates, views, and workbench
actions into the shared viewer shape while preserving Sophiagraph-specific
semantics outside the viewer core.
