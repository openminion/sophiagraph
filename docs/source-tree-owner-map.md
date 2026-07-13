# Sophiagraph Source Tree Owner Map

Status: semantic alpha

Purpose: explain the `sophiagraph` source-tree owners without treating deep
imports as blanket public promises.

## Public contract

The public package surface is documented in:

1. `README.md`
2. `API_COMPATIBILITY.md`
3. `docs/`

The preferred public entrypoint is `sophiagraph`, with stable import roots for
models, query, storage, portability, audit, trust, connectors, graph backends,
inspection, `sophiagraph.okf`, `sophiagraph.ui`, `sophiagraph.workspace`, and
`sophiagraph.workspace_sync`.

## Source-tree owner map

1. `models/` owns typed durable-memory DTOs. Within that layer,
   `models/core.py` remains the stable compatibility re-export seam over the
   canonical split model owners,
   `models/artifact.py` remains the stable multimodal artifact reference DTO
   owner with closed source-class and retention-policy enums,
   `models/artifact_projection.py` remains the stable artifact text-projection,
   segment, and citation DTO owner,
   `models/block.py` remains the stable memory-block DTO and activation-gate
   owner,
   `models/candidate.py` remains the stable candidate, review, and metadata
   normalization owner,
   `models/change.py` remains the stable structural changefeed event owner,
   `models/convergence.py` remains the stable raw-episode and fact-convergence
   link DTO owner,
   `models/document.py` remains the stable document-profile and addressable
   block DTO owner, with strict metadata hydration over aliases, provenance,
   and literal document/block kinds,
   `models/embedding.py` remains the stable caller-supplied embedding sidecar
   DTO owner, with strict dict hydration for namespace, vector, metadata, and
   required string fields,
   `models/embedding_lifecycle.py` remains the stable embedding lifecycle DTO
   owner, with deterministic namespace keys, stale-finding reasons, and strict
   `from_dict()` hydration for required string fields,
   `models/entity_fact.py` remains the stable entity, alias, fact,
   contradiction, and summary DTO owner, with shared local validation helpers
   for namespace, provenance, confidence, and mapping payload checks,
   `models/episode_procedure.py` remains the stable episode, step, outcome,
    decision, and procedure DTO owner, with shared local validation helpers for
    namespace, mapping payloads, and non-empty string list surfaces,
   `models/link.py` remains the stable structural-link and explicit resolver
    owner, with canonical kind/status allowlists and strict alias-list
    validation for explicit resolution candidates,
   `models/namespace.py` remains the stable scope and namespace primitive owner,
    with strict optional-id hydration for dict reconstruction and the canonical
    sorted namespace-key helper,
   `models/ontology.py` remains the stable ontology/category/entity-type/
    edge-type schema owner, with shared duplicate-name validation helpers for
    schema collections and property lists,
   `models/primitives.py` remains the stable primitive literal/validator owner,
    with the dead temporal-coercion placeholder removed so public temporal
    compatibility continues to flow through the real temporal owners,
   `models/privacy.py` remains the stable privacy/consent/redaction/retention
    DTO owner, with shared dict/string hydration helpers for deterministic
    `from_dict()` reconstruction,
   `models/record.py` remains the stable memory-record and retrieval-filter DTO
    owner, with shared local validation helpers for evidence refs, optional
    namespace/meta validation, and literal allowlists,
   `models/relation.py` remains the stable graph-relation DTO owner, with
    a canonical relation-type allowlist and a shared defensive meta-dict
    validator for dataclass reconstruction,
   `models/self_improvement.py` owns lifecycle behavior over the typed
   self-improving-memory contracts, while
   `models/self_improvement_types.py` owns the stable lifecycle DTOs,
   literals, and validation helpers,
   `models/storage_operations.py` remains the stable backup, lease,
    retention-snapshot, and compaction DTO owner, with shared local hydration
    helpers that reject `None`-coerced required strings during dict
    reconstruction,
   `models/tier.py` remains the stable tier-transition DTO owner, with
    canonical record-type, tier, and transition-reason allowlists plus a
    shared defensive meta-dict validator for dataclass reconstruction.
2. `storage/` owns in-memory, SQLite, lifecycle, portability, changefeed, and
   durable storage-operation behavior. `storage/entity_episode_store.py`
   remains the shared predicate and raw-episode filter owner for entity/fact/
   episode/procedure row selection, with strict option validation on the
   cross-backend raw-episode list surface. `storage/base.py` is the stable public
   store façade, `storage/protocol_core.py` owns the core record/link/block/
   sync protocol slices, `storage/protocol_extended.py` owns the semantic,
   temporal, artifact, deletion, and history protocol slices, `storage/__init__.py`
   remains the stable storage import seam, `storage/factory.py` remains the
   canonical package store-construction owner, `storage/async_facade.py`
   remains the minimal asyncio wrapper owner, `storage/record_lifecycle.py`
   remains the shared record query-match plus invalidate/supersede helper
   owner used by both backends, `storage/memory.py` remains the stable
   in-memory store façade, `storage/memory_changefeed.py` remains the tiny
   in-memory change-event append and dedupe owner, `storage/memory_sync_store.py`
   owns the in-memory sync/freshness/source/shared-block methods extracted
   from that façade, `storage/memory_block_helpers.py` remains the tiny shared
   edit-gate owner reused by the in-memory and SQLite block surfaces, and
   `storage/lifecycle_policy.py` is the stable lifecycle-policy façade,
   `storage/lifecycle_types.py` owns the closed lifecycle enums, policy/job
   DTOs, and ISO parsing helpers, `storage/lifecycle_eval.py` owns pure
   lifecycle evaluation and record-meta application helpers, and
   `storage/graph_helpers.py` is the stable graph-helper façade over
   `storage/graph_serialization.py` and `storage/graph_support.py`,
   `storage/portability_helpers.py` remains the shared snapshot-import and
   delta-export helper owner reused by both storage backends,
   `storage/memory_portability.py` remains the cohesive in-memory snapshot,
   changefeed-listing, and delta-import owner on top of the canonical
   portability codecs, `storage/sqlite/portability.py` remains the cohesive
   SQLite snapshot-export changefeed-listing and delta-replay owner on top of
   the canonical portability codecs, `storage/migration_tooling.py` remains
   the cohesive lifecycle-migration detect, backup-receipt, and verification owner,
   `storage/sqlite/schema.py` owns SQLite schema creation plus namespace-column
   migration, `storage/sqlite/rows.py` owns SQLite row-json and namespace
   helpers, `storage/sqlite/fts.py` owns SQLite record/block FTS helpers,
   `storage/sqlite/typed_graph.py` owns typed entity fact contradiction
   summary episode procedure and convergence persistence for the SQLite store,
   `storage/sqlite/aux.py` remains the narrow SQLite-only auxiliary-object
   persistence owner for sync conflicts freshness entries source-ingest
   records and shared-block mirrors, `storage/sqlite/changefeed.py` remains
   the tight SQLite-only row-codec and event-write owner for the durable
   changefeed table, and
   `storage/ontology_validator.py` remains the typed ontology property-check
   and store-backed ontology-resolution owner.
3. `query/` owns retrieval, graph, explorer, structural, temporal, and block
   query helpers. Within that layer, `query/retrieval.py` owns hybrid retrieval
   pipeline behavior while `query/retrieval_types.py` owns the stable stage
   DTOs, result packets, and adapter protocols. `query/structural_graph_query.py`
   is the stable bounded structural-query façade, `query/structural_graph_types.py`
   owns the typed structural-query request/result/codec contracts, and
   `query/structural_graph_exec.py` owns execution and planner mechanics.
   `query/algorithms.py` is the stable graph-algorithm façade,
   `query/algorithm_types.py` owns path/component/degree result DTOs, and
   `query/algorithm_exec.py` owns deterministic traversal and graph-metric
   execution helpers. `query/options.py` remains the stable owner for generic
   list/search/candidate/embedding query DTOs, `query/graph.py` remains the
   stable owner for link, local-graph, and graph-snapshot DTOs,
   `query/artifacts.py` remains the stable artifact-backed text query owner,
   including projection freshness, privacy-aware omission handling, citation
   preservation, and export filtering over typed artifact records,
   `query/blocks.py` remains the stable budget-aware memory-block context and
   structural disagreement owner, with canonical disagreement-kind validation
   and typed detail guards on the public signal surface,
   `query/entity_summary_context.py` remains the stable typed entity-summary
   context owner, with strict request/item/omission validation over ids,
   namespace filters, and mapping-shaped metadata payloads,
   `query/structural.py` remains the stable owner for deterministic
   Obsidian-style structural-search DTOs and parsing, `query/temporal.py`
   remains the stable owner for bitemporal record-filter helpers, and
   `query/replay.py` remains the stable owner for bounded episode-replay DTOs
   plus deterministic replay assembly. `query/__init__.py` remains the stable
   public import seam that re-exports the canonical query surface.
4. `contracts/`, `audit/`, `trust/`, and `temporal/` own typed policy and
   governance boundaries. `contracts/errors.py` remains the canonical package
   error-envelope owner, `contracts/provenance.py` remains the provenance-trace
   contract owner, and `contracts/types.py` remains the package/host adapter
   DTO and contract-version owner. `audit/events.py` remains the structural
   audit-event schema owner while `audit/__init__.py` remains the stable audit
   import seam. `privacy.py` is the stable privacy public façade,
   `privacy_types.py` owns omission/result DTOs plus package-local privacy
   constants, and `privacy_ops.py` owns deterministic policy decoding,
   redaction, retrieval/export filtering, and retention application helpers.
   `trust/__init__.py` remains the stable trust import seam, `trust/types.py`
   remains the typed trust-score and claim-polarity owner, and
   `temporal/__init__.py` remains the reusable UTC/time coercion owner.
5. `shared_blocks.py` remains the stable shared-block collaboration owner,
   including attachments, mirrors, edit conflicts, usage events, and typed
   payload validation for collaboration metadata and status surfaces.
6. `adapters/`, `connectors.py`, `sync.py`, and `freshness.py` own package-side
   connector and replay helpers. `adapters/markdown.py` remains the structural
   Markdown/frontmatter import-export owner, `adapters/mcp.py` remains the thin
   provider-free MCP bridge owner, `freshness.py` remains the ledger/cursor/
   replay-decision owner, `connectors.py` remains the provider-neutral source
   registry and ingest-contract owner, `sync.py` remains the typed local-sync
   request/result/conflict and deterministic conflict-resolution owner, and
   `embedding_lifecycle.py` remains the
   pure stale-detection and re-embed-planning owner over the public store
   protocol.
7. `human.py` owns the package-local human-management public façade,
   `human_types.py` owns the typed note/import/source contracts, and
   `human_render.py` owns deterministic HTML rendering for the workbench packet.
8. `operations.py` owns the operational public façade, while
   `operations_types.py` owns typed run/request/report contracts and
   `operations_codec.py` owns dict hydration/serialization helpers.
9. `schema.py` remains the deterministic property-graph schema discovery owner,
   `vectors.py` remains the deterministic vector similarity and backend
   conformance-harness owner with a closed metric enum and explicit protocol seam,
   `integrity.py` remains the row-level integrity hash owner, `extensions.py`
   remains the lightweight extension-registry owner, and `deletion.py` remains
   the package-local tombstone and erasure-audit DTO owner. `canvas.py`
   remains the deterministic JSON Canvas DTO, codec, and explicit
   relation-mapping owner. `inspection.py` remains the structural inspection,
   report hydration, and explicit repair-candidate owner.
10. `storage/operations.py` owns the storage-operation public façade, while
   `storage/backups.py` owns backup, restore, and retention-snapshot flows,
   `storage/leases.py` owns write-lease acquisition and heartbeat behavior,
   `storage/compaction.py` owns compaction and coordinated backup helpers,
   `storage/graph_queries.py` remains the cohesive store-neutral local-graph
   and graph-snapshot builder owner, and `storage/operation_support.py` owns
   the small shared private helpers those owners reuse.
11. `portability/codec.py` is the stable public portability façade,
   `portability/row_codec.py` owns JSON helpers plus row hydration for typed
   records, candidates, relations, tier transitions, memory blocks, and change
   events, `portability/bundle_codec.py` owns manifest, checksum, tarball, and
   bundle snapshot read/write behavior, `portability/__init__.py` remains the
   stable portability import seam, and `portability/models.py` remains the
   typed bundle/delta snapshot contract owner.
12. `workspace.py` is the stable workspace façade for package-local persistent
   workspace posture, status, import, and workbench flows.
13. `workspace_types.py` owns typed workspace metadata/profile/status
   contracts plus the workspace JSON/store-path helpers they depend on.
14. `workspace_sync.py` owns file-primary live-sync helpers, source-ledger
   DTOs, and bounded polling on top of the canonical workspace, vault,
   freshness, and sync owners.
15. `workspace_notes.py` owns file-primary note/materialize flows that sit on
   top of the canonical workspace and workspace-sync owners.
16. `graph_backends/` owns optional graph-adapter contracts and concrete
   backends. `base.py` is the stable public facade, `types.py` owns the typed
   backend DTO/protocol contracts, and `support.py` owns shared export,
   namespace, JSON, and shortest-path helpers. `fake.py` remains the
   provider-free conformance backend owner, while backend-local private helpers
   stay beside their concrete adapter when that keeps the optional-provider
   seam narrow, such as `kuzu_support.py` and `neo4j_support.py` for the
   provider-specific adapters.
17. `vault.py` owns the stable vault public façade, while `vault_types.py`
   owns the typed import/export/repair contracts, `vault_support.py` owns
   shared path/id/meta helpers, `vault_io.py` owns import/export and manifest
   flows, and `vault_repairs.py` owns rename/repair planning and application.
18. `okf.py` owns the stable OKF public façade, while `okf_io.py`,
   `okf_navigation.py`, and `okf_support.py` own import/export and navigation
   mechanics over the package-local document substrate.
19. `ui/` owns typed UI contracts, the Sophiagraph-to-GraphFakos adapter, and
   package CLI preview wiring. `ui/__init__.py` remains the stable UI import
   seam, `ui/contracts.py` owns typed route and transport-boundary contracts,
   `ui/local_server.py` remains the stable local-viewer compatibility seam,
   `preview.py` is the stable preview façade,
   `preview_types.py` owns typed request/result contracts, and
   `preview_support.py` owns preview request parsing plus package-local demo
   store / GraphFakos bridge helpers. `screens.py` is the stable screen façade,
   `screen_types.py` owns typed screen packets and local UI store protocol
   contracts, `screen_builders.py` owns deterministic screen assembly, and
   `state.py` owns the tiny cross-screen UI state DTO.
   Shared viewer shell, local server behavior, static export, and reusable
   viewer assertions belong to GraphFakos.
20. `views.py` is the stable saved-view public façade, `view_types.py` owns the
   typed saved-view DTO and literal contracts, and `view_eval.py` owns the
   deterministic filter, summary, and formula-evaluation helpers.

## Repo-local but not public API

1. `tests/` contains the certification, regression, and compatibility harness.
2. `examples/` are package demos, not wider host-runtime guarantees.
3. Repository planning and execution docs stay in the workspace `docs/` tree
   instead of the package source tree.
4. `scripts/validate_quality_patterns.py` and `scripts/baselines/` own the
   package-local structural quality ratchets used by `make validate-patterns`
   and `make check`.
