# Sophiagraph Storage Retrieval Backends Spec

Date: 2026-07-02
Status: accepted and executed
Owner: Sophiagraph
Related:
[`../trackers/storage-retrieval-backends-2026-07-02-tracker.md`](../trackers/storage-retrieval-backends-2026-07-02-tracker.md),
[`../backend-compatibility-matrix.md`](../backend-compatibility-matrix.md),
[`../retrieval-boundary.md`](../retrieval-boundary.md),
[`../vector-conformance.md`](../vector-conformance.md),
[`../human-management.md`](../human-management.md),
[`../workspace-mode.md`](../workspace-mode.md)

## Purpose

Define the next storage and retrieval backend work for Sophiagraph so durable
agent memory, human-managed notes, vectors, graph traversal, and portability
remain interchangeable across local and optional backends.

The core product loop is:

```text
human notes / agent memory / imports / operator pins
  -> approved Sophiagraph records, relations, blocks, vectors, and metadata
  -> durable store
  -> retrieval, graph navigation, governance, export, and workbench views
```

This spec approved and executed the package-local storage capability,
default-store parity, portability, documentation, and example slice. It did
not approve version bumps, new optional dependencies, remote vector providers,
or hosted services.

## Current State

Sophiagraph already ships more storage machinery than PragmaGraph:

1. in-memory and SQLite durable stores,
2. portability snapshots and deltas,
3. graph-backend adapters for fake, Kuzu, and Neo4j surfaces,
4. SQLite FTS helpers for record and block search,
5. embedding lifecycle storage and external vector id tracking,
6. vector metric registry and backend-neutral conformance harness,
7. hybrid retrieval, context assembly, and retrieval explanations,
8. human note/import/source management,
9. workspace and UI workbench surfaces.

The gap is not "add a database." The gap is a clearer and fuller
interchange contract:

1. storage capabilities should be inspectable in one typed shape,
2. retrieval parity should be tested across supported stores,
3. vector backends should have concrete optional adapter lanes,
4. import/export should carry backend and vector sidecar posture clearly,
5. human-managed notes and agent memories should share the same storage and
   search posture without hiding governance metadata.

## External Research Baseline

| System | Relevant lesson | Fit for Sophiagraph |
| --- | --- | --- |
| SQLite FTS5 | Embedded full-text search over local records. | Already aligned with local-first durable memory; should remain default lexical store. |
| Kuzu | Embedded property graph database for graph traversal. | Already an optional graph backend; needs clearer capability and retrieval parity proof. |
| Neo4j | External graph database pattern for teams already running graph infra. | Optional host-owned external graph backend; not default. |
| Zvec | In-process vector database with dense/sparse vectors, FTS, hybrid search, and durable storage. | Best local-first candidate for an optional concrete vector backend. |
| DashVector | Managed vector retrieval service built on Alibaba Proxima. | Remote vector adapter reserve; useful for hosted teams, not package default. |
| LanceDB | Local/remote vector table APIs. | Optional vector backend candidate for teams wanting vector-table persistence. |
| Milvus/Zilliz | High-scale vector database and managed vector search. | Future high-scale vector adapter reserve. |

This research baseline intentionally overlaps with the PragmaGraph storage
interchange spec so each public package doc remains understandable on its own.
When the external storage baseline changes, update both package-local specs in
the same pass.

## Storage Authority Model

Sophiagraph has different authority than PragmaGraph:

1. Sophiagraph stores **approved memory knowledge**, including judgments,
   operator pins, records, trust metadata, temporal metadata, and governance.
2. The durable store is not merely a cache; it is the memory substrate.
3. Portable bundles and snapshots are still required so users can migrate,
   inspect, and back up memory.
4. Optional graph and vector backends accelerate retrieval and navigation but
   must not bypass record governance, namespace isolation, deletion policy, or
   privacy posture.

## Proposed Public Contract

Add or clarify a backend capability surface around the existing
`SophiaGraphStore` contract:

```python
class StoreCapabilityReport:
    backend: str
    contract_version: str
    supports_records: bool
    supports_relations: bool
    supports_blocks: bool
    supports_fts: bool
    supports_vectors: bool
    supports_external_vector_ids: bool
    supports_graph_queries: bool
    supports_delta_export: bool
    supports_backup: bool
    supports_governance_metadata: bool
```

The exact DTO names can change during implementation, but every supported store
should answer:

1. what it stores,
2. what it can search,
3. what it can export,
4. what it can back up,
5. what optional providers it depends on,
6. which privacy and deletion guarantees are active.

## Backend Plan

### In-Memory Store

Role: tests, examples, temporary workbench previews, and import dry-runs.

Required next work:

1. expose the same capability report as durable stores,
2. participate in retrieval parity fixtures,
3. keep portability snapshot import/export behavior aligned with SQLite.

### SQLite Store

Role: default durable local memory store.

Required next work:

1. document FTS table coverage and ranking posture,
2. add retrieval parity tests across record, block, relation, vector metadata,
   and governance filters,
3. add capability reporting,
4. make backup/export status visible to workbench and CLI surfaces.

### Kuzu Graph Backend

Role: optional embedded graph traversal over exported or mirrored memory graph
facts.

Required next work:

1. declare graph-query capabilities,
2. prove batch-upsert and query parity against fake backend fixtures,
3. keep it optional through `sophiagraph[kuzu]`,
4. preserve no-freeform-query guarantees.

### Neo4j Graph Backend

Role: optional external graph backend for hosts that already operate Neo4j.

Required next work:

1. keep adapter DTO-only,
2. expose capability and connection diagnostics,
3. keep remote dependency and secrets out of default package checks.

### Vector Backends

Sophiagraph already owns vector metrics and conformance. The next gap is a
concrete optional vector backend path.

Recommended order:

1. keep built-in deterministic vector backend as conformance oracle,
2. add local Zvec adapter as first concrete optional vector backend,
3. reserve LanceDB for local/remote vector-table consumers,
4. reserve DashVector, Milvus, and Zilliz for hosted/high-scale consumers.

Vector backend rules:

1. package never calls embedding providers directly,
2. callers provide vectors or provider callbacks,
3. backend adapters store and search vectors but do not infer new memory facts,
4. all vector hits must resolve to approved memory records or blocks,
5. deletion and orphan external vector id handling must be tested,
6. export must explicitly state whether raw vectors are included, omitted, or
   referenced externally.

## Search And Retrieval Goals

The storage layer should support:

1. keyword search over records,
2. FTS over blocks and notes,
3. graph neighborhood retrieval,
4. relation traversal,
5. temporal filtering,
6. trust/governance filtering,
7. namespace and actor isolation,
8. vector-stage retrieval over caller-supplied embeddings,
9. hybrid retrieval explanations,
10. portable context assembly over approved stored facts.

Every retrieval result should expose:

1. record or block id,
2. matched stage,
3. score or ordering reason,
4. source evidence,
5. trust/governance markers,
6. vector-space metadata when vectors were used,
7. omitted or filtered counts.

## Import And Export Requirements

Import/export must preserve:

1. records,
2. relations,
3. blocks and document links,
4. namespaces,
5. audit/change events where supported,
6. lifecycle and governance metadata,
7. privacy posture,
8. embedding metadata,
9. external vector ids and orphan tracking,
10. deletion/tombstone state where supported.

Raw vectors should be exportable only through explicit options. Default exports
should prefer metadata and external ids unless the user asks for portable raw
vectors.

## Human Management Requirements

Human note/import management must use the same storage posture as agent memory:

1. import dry-runs should report backend capability limits,
2. workbench previews should show whether search is lexical, vector, graph, or
   hybrid,
3. source freshness should cite the backend and last import/sync state,
4. note edits should preserve governance and review status,
5. stored human notes and agent-created records should remain queryable through
   one retrieval surface.

## Non-Goals

This spec does not approve:

1. replacing the default SQLite store,
2. hosted Sophiagraph services,
3. package-owned embedding provider calls,
4. automatic background embedding refresh,
5. freeform graph queries generated from prose,
6. making Zvec, LanceDB, DashVector, Milvus, Zilliz, Kuzu, or Neo4j default
   dependencies,
7. bypassing namespace/privacy/governance filters for retrieval speed.

## Validation Expectations

Implementation trackers must require:

1. store capability report tests,
2. in-memory vs SQLite retrieval parity tests,
3. graph backend conformance tests for accepted graph adapters,
4. vector backend conformance tests for accepted vector adapters,
5. deletion/orphan-vector tests,
6. import/export round-trip tests,
7. human-management search tests,
8. package `make check`,
9. package `make release-check` when public imports or packaging change.

## Open Questions

1. Should Zvec be the first concrete optional vector backend?
2. Should vector backend adapters live in core extras or separate packages?
3. Should raw vectors be included in portable bundles by default, never, or only
   by explicit option?
4. Should retrieval capability reports be exposed through CLI, UI workbench, or
   both?
5. Should graph backend parity be measured against fake backend only or also
   against SQLite graph snapshots?
