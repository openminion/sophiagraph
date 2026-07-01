# Examples

Status: active

The `examples/` directory contains runnable, package-local examples that use
public SophiaGraph imports only. Each example prints deterministic JSON or
writes artifacts under a temporary directory.

Run one example directly:

```bash
PYTHONPATH=src python3.11 examples/basic_usage.py
```

Run the example smoke tests:

```bash
PYTHONPATH=src python3.11 -m pytest -q tests/test_public_examples.py
```

## Included examples

- `basic_usage.py` inserts a typed record, lists/searches by namespace, and
  round-trips a bundle into an in-memory store.
- `workspace_sync_demo.py` initializes a local workspace, syncs Markdown notes,
  and reports the tracked file status.
- `okf_obsidian_roundtrip.py` imports the bundled OKF fixture and exports both
  portable Markdown and Obsidian-compatible wikilinks.
- `graph_backend_export.py` exports explicit records/relations into the fake
  graph backend and runs a structural shortest-path query.
- `privacy_redaction.py` applies a typed privacy policy, redacts export output,
  and shows which record was omitted or redacted.
- `benchmark_conformance.py` emits the built-in benchmark scorecard summary.
- `ui_workbench_export.py` writes deterministic local HTML, artifact, embed,
  JSON report, and Markdown report files.

## Example contract

Examples should stay small and deterministic:

1. Use public imports from `sophiagraph`.
2. Avoid local machine paths in output.
3. Avoid network calls and provider credentials.
4. Prefer temporary directories for generated files.
5. Print a compact JSON summary suitable for smoke tests.
