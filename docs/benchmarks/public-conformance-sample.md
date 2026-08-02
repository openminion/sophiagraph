# SophiaGraph Public Benchmark And Conformance

- Suite: `sophiagraph-public-conformance`
- Package version: `0.0.6`
- Benchmark version: `2026-06-29`
- Fixture revision: `2026-06-29`
- Overall: `passed`

## Status Counts

- `failed`: 0
- `passed`: 8
- `skipped`: 0
- `unsupported_by_design`: 1

## Results

| Group | Case | Status | Public surface | Detail |
| --- | --- | --- | --- | --- |
| backend_parity | fake-backend-capabilities | passed | `sophiagraph.graph_backends.FakeGraphBackendAdapter` |  |
| graph_navigation | graph-shortest-path | passed | `sophiagraph.query.shortest_path` |  |
| interoperability | okf-baseline-pinned | passed | `sophiagraph.okf.OKF_SPEC_BASELINE_COMMIT` |  |
| interoperability | text2cypher-refused | unsupported_by_design | `sophiagraph.query.structural_graph_query` | Core accepts typed structural query DTOs only. |
| memory_lifecycle | memory-block-creation | passed | `sophiagraph.models.MemoryBlock` |  |
| openminion_direct | openminion-direct-handoff | passed | `sophiagraph.benchmarks.BenchmarkScorecard.openminion_eval_payload` |  |
| privacy_export | privacy-export-gates | passed | `sophiagraph.privacy.filter_snapshot_for_export` |  |
| view_publish_profiles | publish-profile-surface | passed | `sophiagraph.publishing.build_publish_plan` |  |
| workspace_roundtrip | workspace-ledger-entry | passed | `sophiagraph.workspace_sync.WorkspaceSourceLedgerEntry` |  |
