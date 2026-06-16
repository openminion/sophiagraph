# sophiagraph API Compatibility Policy

Owner: `sophiagraph`
Status: `active`
Scope: stable import-root and versioning policy for external `sophiagraph` consumers

## Purpose

Define what external consumers can rely on when they build against the
standalone `sophiagraph` package.

## Stable import roots

External consumers should treat these import roots as the supported public API:

- `sophiagraph`
- `sophiagraph.models`
- `sophiagraph.query`
- `sophiagraph.storage`
- `sophiagraph.portability`
- `sophiagraph.adapters`
- `sophiagraph.canvas`
- `sophiagraph.extensions`
- `sophiagraph.views`
- `sophiagraph.schema`
- `sophiagraph.audit`
- `sophiagraph.trust`
- `sophiagraph.temporal`
- `sophiagraph.contracts`
- `sophiagraph.deletion`
- `sophiagraph.sync`
- `sophiagraph.freshness`
- `sophiagraph.connectors`
- `sophiagraph.shared_blocks`
- `sophiagraph.graph_backends`
- `sophiagraph.inspection`
- `sophiagraph.ui`
- `sophiagraph.embedding_lifecycle`
- `sophiagraph.workspace`

The top-level `sophiagraph` package is the preferred entrypoint for common usage.

## Stable top-level exports

The following top-level exports are part of the current public contract:

- `sophiagraph.__version__`
- `sophiagraph.DEFAULT_DB_FILENAME`
- `sophiagraph.SophiaGraphSqliteStore`
- `sophiagraph.SophiaGraphMemoryStore`
- `sophiagraph.MemoryNamespace`
- `sophiagraph.MemoryNamespaceComponent`
- `sophiagraph.MemoryRecord`
- `sophiagraph.MemoryCandidate`
- `sophiagraph.MemoryRelation`
- `sophiagraph.EntitySummary`
- `sophiagraph.SUMMARY_AUTHORSHIPS`
- `sophiagraph.SUMMARY_INVALIDATION_REASONS`
- `sophiagraph.SummaryAuthorship`
- `sophiagraph.SummaryInvalidationReason`
- `sophiagraph.ActiveEmbeddingModelSet`
- `sophiagraph.VectorSpaceModelDescriptor`
- `sophiagraph.StaleEmbeddingFinding`
- `sophiagraph.ReembedCursor`
- `sophiagraph.ReembedBatch`
- `sophiagraph.ReembedPlan`
- `sophiagraph.KnowledgeDocument`
- `sophiagraph.KnowledgeDocumentBlock`
- `sophiagraph.StructuralLink`
- `sophiagraph.ExplicitLinkResolver`
- `sophiagraph.LinkResolution`
- `sophiagraph.LinkResolutionCandidate`
- `sophiagraph.AsyncSophiaGraphStore`
- `sophiagraph.ListQueryOptions`
- `sophiagraph.SearchQueryOptions`
- `sophiagraph.LinkQueryOptions`
- `sophiagraph.LocalGraphOptions`
- `sophiagraph.GraphSnapshotOptions`
- `sophiagraph.GraphSnapshot`
- `sophiagraph.GraphPath`
- `sophiagraph.GraphComponent`
- `sophiagraph.StructuralSearchQuery`
- `sophiagraph.KnowledgeExplorerRequest`
- `sophiagraph.KnowledgeExplorerResult`
- `sophiagraph.KnowledgeExplorerFilters`
- `sophiagraph.KnowledgeHit`
- `sophiagraph.KnowledgeFacet`
- `sophiagraph.KnowledgeNavigationAction`
- `sophiagraph.KnowledgeQueryPlan`
- `sophiagraph.KnowledgeQueryPlanStage`
- `sophiagraph.UnlinkedMentionCandidate`
- `sophiagraph.SavedExplorerView`
- `sophiagraph.SUMMARY_CONTEXT_OMISSION_REASONS`
- `sophiagraph.SummaryContextRequest`
- `sophiagraph.SummaryContextItem`
- `sophiagraph.SummaryContextOmission`
- `sophiagraph.SummaryContextResult`
- `sophiagraph.explore_knowledge(...)`
- `sophiagraph.evaluate_saved_explorer_view(...)`
- `sophiagraph.assemble_entity_summary_context(...)`
- `sophiagraph.shortest_path(...)`
- `sophiagraph.path_evidence(...)`
- `sophiagraph.connected_components(...)`
- `sophiagraph.degree_centrality(...)`
- `sophiagraph.create_sqlite_store(...)`
- `sophiagraph.create_memory_store()`
- `sophiagraph.default_db_path(...)`
- `sophiagraph.async_store(...)`
- `sophiagraph.WorkspaceMetadata`
- `sophiagraph.WorkspaceImportProfile`
- `sophiagraph.WorkspaceStatusView`
- `sophiagraph.initialize_workspace(...)`
- `sophiagraph.load_workspace_status(...)`
- `sophiagraph.plan_workspace_import(...)`
- `sophiagraph.apply_workspace_import(...)`
- `sophiagraph.workspace_note_put(...)`
- `sophiagraph.build_workspace_workbench(...)`
- `sophiagraph.render_workspace_workbench(...)`
- `sophiagraph.audit`
- `sophiagraph.contracts`
- `sophiagraph.portability`
- `sophiagraph.trust`
- `sophiagraph.coerce_temporal_dt`
- `sophiagraph.DeletionCascadeResult`
- `sophiagraph.ErasureAuditEntry`
- `sophiagraph.ErasureAuditExport`
- `sophiagraph.TombstoneResult`
- `sophiagraph.LocalSyncRequest`
- `sophiagraph.LocalSyncResult`
- `sophiagraph.SyncConflictRecord`
- `sophiagraph.SyncResolution`
- `sophiagraph.detect_sync_conflict(...)`
- `sophiagraph.resolve_sync_conflict(...)`
- `sophiagraph.FreshnessCursor`
- `sophiagraph.FreshnessLedgerEntry`
- `sophiagraph.ReplayDecision`
- `sophiagraph.decide_replay(...)`
- `sophiagraph.SourceRegistryEntry`
- `sophiagraph.SourceIngestEnvelope`
- `sophiagraph.SourceIngestResult`
- `sophiagraph.decide_source_ingest(...)`
- `sophiagraph.update_source_after_ingest(...)`
- `sophiagraph.SharedBlockAttachment`
- `sophiagraph.SharedBlockMirror`
- `sophiagraph.SharedBlockEditConflict`
- `sophiagraph.SharedBlockUsageEvent`
- `sophiagraph.mark_mirror_stale_if_needed(...)`
- `sophiagraph.create_shared_block_conflict(...)`
- `sophiagraph.GraphBackendCapabilities`
- `sophiagraph.GraphBackendQuery`
- `sophiagraph.GraphBackendResult`
- `sophiagraph.GraphExportBatch`
- `sophiagraph.FakeGraphBackendAdapter`
- `sophiagraph.KuzuGraphBackendAdapter`
- `sophiagraph.Neo4jGraphBackendAdapter`
- `sophiagraph.build_graph_export_batch(...)`
- `sophiagraph.detect_stale_embeddings(...)`
- `sophiagraph.build_reembed_plan(...)`
- `sophiagraph.list_orphan_external_vector_ids(...)`
- `sophiagraph.StructuralGraphQueryRequest`
- `sophiagraph.StructuralGraphQueryResult`
- `sophiagraph.StructuralGraphPlannerStage`
- `sophiagraph.execute_structural_graph_query(...)`
- `sophiagraph.structural_graph_query_to_backend_query(...)`
- `sophiagraph.structural_result_to_knowledge_plan(...)`
- `sophiagraph.SyncRunRequest`
- `sophiagraph.ConnectorReplayRequest`
- `sophiagraph.FreshnessReindexRequest`
- `sophiagraph.RepairFollowUpRequest`
- `sophiagraph.OperationalFollowUpAction`
- `sophiagraph.OperationalRunReport`
- `sophiagraph.execute_operational_run(...)`
- `sophiagraph.InspectionReport`
- `sophiagraph.InspectionFinding`
- `sophiagraph.RepairCandidate`
- `sophiagraph.build_inspection_report(...)`
- `sophiagraph.apply_repair_candidate(...)`
- `sophiagraph.adapters.McpMemoryRequest`
- `sophiagraph.adapters.McpMemoryResponse`
- `sophiagraph.adapters.SophiaGraphMcpAdapter`

## Versioning posture

`sophiagraph` is currently `0.x` software.

That means:

1. additive API changes are preferred,
2. breaking changes are still possible,
3. breaking changes must be called out in release notes and package docs,
4. stable import roots should not be moved casually even during `0.x`.

## Deprecation policy

When a public symbol or import path needs to change:

1. prefer an additive replacement first,
2. document the new path in `README.md`,
3. keep the old path available for at least one `0.x` release when practical,
4. remove only after the deprecation is documented in release notes.

If a safety or correctness issue requires immediate removal, the release notes
must say so explicitly.

## Compatibility tests

Public-contract confidence should be enforced by tests that cover:

1. import-root availability,
2. public top-level export availability,
3. store-behavior regressions for package-owned backends,
4. portability round-trip expectations,
5. namespace-safe query/export/import boundaries,
6. explicit link/backlink/local-graph behavior across memory and SQLite stores,
7. Markdown/frontmatter structural import behavior with no prose rewrites,
8. release/install smoke for built artifacts.
9. changefeed/delta replay behavior for current durable mutation surfaces,
10. deterministic saved-view evaluation,
11. document-block storage/search behavior,
12. schema discovery and async facade import/use.
13. bitemporal `as_of` / `valid_at` / `believed_at` record queries,
14. provable deletion tombstone and erasure-audit export behavior,
15. provider-free MCP adapter CRUD/search smoke behavior.
16. local-first sync conflict DTOs and explicit resolution helpers,
17. freshness ledger and connector idempotency contracts,
18. shared-block attachment/mirror/audit primitives,
19. structural graph query planner evidence and backend-envelope mapping,
20. operational sync/replay/reindex/repair run envelopes over public imports.
19. optional graph-backend adapter contracts,
20. structural inspection reports and explicit repair candidates.
21. graph/search explorer packets with backlinks, facets, paths, navigation
    actions, and mechanical query-plan evidence.
22. optional concrete graph backend adapters for Kuzu and Neo4j.
23. namespace-scoped active embedding registries, stale-embedding detection,
    resumable re-embed plans, and orphan vector-id lifecycle helpers.
24. persistent local workspace metadata/profile/status flows plus explicit
    local markdown/canvas import planning and application.

## Internal compatibility shims

Underscore-prefixed model cast helpers and codec hydrator aliases may remain
available during `0.x` for OpenMinion compatibility, but they are not part of
`__all__` and should not be used by new external consumers. New code should use
public model imports and public codec helpers such as `record_from_dict`.

The package currently uses small internal mixins for storage portability
behavior and composition-style helper modules for shared query/build logic.
This is an internal layout choice for `0.x`: public consumers should depend on
the store classes and stable import roots, not private storage helper modules.

Embedding lifecycle follows the same ownership boundary: `sophiagraph` exports
typed registries, stale-detection helpers, resumable plans, and orphan-vector
enumeration, but it does not import provider SDKs or invoke embedding APIs on
its own. Hosts own actual embedding execution.

## Non-goals

This policy does not promise:

1. host-framework orchestration semantics,
2. an Obsidian editor, renderer, sync service, or plugin runtime,
3. semantic inference of tags, links, relation types, or summaries from prose,
4. compatibility for private helper modules,
5. long-term support for undocumented import paths,
6. compatibility with every possible third-party graph backend.
