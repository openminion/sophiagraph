# Local UI Workbench

Status: active

The package-local UI workbench is a deterministic GraphFakos-backed preview of
typed SophiaGraph data. It is useful for inspecting records, links, graph
neighborhoods, saved views, candidates, timeline, and schema packets without
running a hosted service.

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
  --screen graph \
  --serve
```

## Boundary

The local workbench is not an authenticated hosted product. It is a package
preview and artifact-export surface. Hosted browser delivery, auth, CORS, and
multi-user operations belong in a server package or host runtime.

## Generated artifacts

- HTML preview: human-readable local browser output
- graph artifact JSON: replayable graph payload for GraphFakos
- embed HTML: embeddable static preview
- JSON report: machine-readable provider report
- Markdown report: review-friendly report summary
