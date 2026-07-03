# Sophiagraph Product Gap Top 20 Roadmap Spec

Date: 2026-07-02
Status: draft discussion, not executable
Owner: Sophiagraph
Related:
[`../trackers/product-gap-top20-roadmap-2026-07-02-tracker.md`](../trackers/product-gap-top20-roadmap-2026-07-02-tracker.md),
[`../storage-retrieval-backends.md`](../storage-retrieval-backends.md),
[`../retrieval-boundary.md`](../retrieval-boundary.md),
[`../human-management.md`](../human-management.md),
[`../workspace-mode.md`](../workspace-mode.md),
[`../ui-workbench.md`](../ui-workbench.md),
[`../vector-conformance.md`](../vector-conformance.md)

## Purpose

Collect the next twenty Sophiagraph product gaps into one review-only roadmap
so future work strengthens the durable memory product without blurring it with
PragmaGraph's observed-fact graph.

This spec does not start implementation. A row becomes executable only after a
follow-up tracker accepts a bounded slice, names validation, and restates the
Sophiagraph authority model:

```text
human notes / imports / agent memories / operator pins
  -> approved memory records, relations, blocks, provenance, trust, and time
  -> durable store
  -> retrieval, graph navigation, governance, export, and workbench surfaces
```

## Research Baseline

The roadmap is grounded in current memory, knowledge-graph, retrieval, storage,
and agent-access patterns.

| Source | Public reference | Lesson for Sophiagraph |
| --- | --- | --- |
| Microsoft GraphRAG | <https://microsoft.github.io/graphrag/> | Graph-assisted retrieval is valuable, but LLM graph extraction must remain outside package storage unless explicitly approved. |
| LlamaIndex Property Graph | <https://developers.llamaindex.ai/python/framework/module_guides/indexing/lpg_index_guide/> | Users expect property-graph construction, retrieval, and storage concepts; Sophiagraph should expose memory-owned equivalents with governance. |
| SQLite FTS5 | <https://www.sqlite.org/fts5.html> | Local-first text retrieval should remain a default durable capability. |
| Kuzu | <https://kuzudb.github.io/docs/> | Embedded property graph storage is a credible optional traversal backend. |
| LanceDB | <https://docs.lancedb.com/> | Vector tables are useful for optional retrieval backends and local/remote portability. |
| Milvus | <https://milvus.io/docs> | High-scale vector retrieval belongs behind optional adapters and privacy policy. |
| Qdrant | <https://qdrant.tech/documentation/> | Payload filtering and vector metadata are important for trust, namespace, and deletion filters. |
| Chroma | <https://docs.trychroma.com/docs/overview/introduction> | Simple developer UX for vector plus metadata retrieval is an adoption benchmark. |
| DashVector | <https://www.alibabacloud.com/help/en/vrs/latest/what-is-vector-retrieval-service> | Managed vector services are useful reserves for hosted teams, not default local memory. |
| Model Context Protocol | <https://modelcontextprotocol.io/specification/2025-06-18> | Agent consumers need stable tools/resources and capability discovery for memory operations. |

## Boundary Rules

1. Sophiagraph owns approved memory knowledge, including records, relations,
   blocks, provenance, trust, temporal metadata, governance, and operator pins.
2. Human-authored notes, imports, and agent-authored memory records share the
   same governance and storage posture.
3. Retrieval can rank and explain stored memories, but package code must not
   call embedding providers or infer new memory facts without an explicit
   caller-provided record.
4. Optional graph and vector backends must preserve namespace, deletion,
   privacy, trust, temporal, and export semantics.
5. Hosted services, background sync, and remote vector providers require
   separate scope acceptance before implementation.

## Top 20 Roadmap Items

| Rank | Item | Class | Target outcome | Acceptance signal |
| --- | --- | --- | --- | --- |
| 1 | Human note manager depth | package-ready | Improve create/import/edit/delete flows for human-managed notes and sources. | CLI/workbench examples prove notes become governed records with provenance. |
| 2 | Bulk import and preview pipeline | package-ready | Add dry-run, diff, duplicate detection, and namespace preview before import. | Fixture imports show accepted, skipped, duplicate, and rejected rows with explanations. |
| 3 | Retrieval evidence unification | package-ready | Normalize why a result appeared across keyword, graph, temporal, trust, and vector stages. | Results expose stage, score/order reason, source evidence, and omitted counts. |
| 4 | Trust and governance claim alignment | package-ready | Make public trust/governance claims match shipped code or deepen one named governance feature. | Docs and tests prove the chosen posture without overclaiming. |
| 5 | Temporal memory timelines | package-ready | Expose timeline views, stale/freshness filters, and temporal conflict diagnostics. | Workbench/CLI output can answer what changed, when, and why it is current. |
| 6 | Namespace and actor administration | package-ready | Strengthen tenant/user/agent/session isolation management and export proof. | Tests prove cross-namespace leakage is rejected or omitted with diagnostics. |
| 7 | Deletion, tombstone, and vector orphan lifecycle | package-ready | Make record deletion, tombstones, external vector ids, and portability status visible. | Export/import round trips preserve deletion posture and orphan diagnostics. |
| 8 | Store capability UI and CLI | package-ready | Surface backend capability reports in human workflows, CLI, and workbench packets. | Users can see FTS/vector/graph/export/backup support before querying. |
| 9 | Optional Zvec vector adapter | deferred optional backend | Add a local-first concrete vector backend after lifecycle/export conformance acceptance. | Lazy import, conformance, deletion, and export posture pass. |
| 10 | Optional LanceDB vector adapter | deferred optional backend | Support teams that want local/remote vector-table persistence. | A concrete consumer and export/privacy posture are accepted. |
| 11 | Remote vector adapter reserve | boundary reserve | Reserve DashVector, Milvus, Zilliz, or Qdrant adapters for hosted/high-scale consumers. | Secret ownership, privacy, deletion, and remote export policies are accepted first. |
| 12 | Kuzu/Neo4j graph conformance depth | deferred optional backend | Improve optional graph traversal parity without making graph backends default. | Fake/Kuzu/Neo4j fixtures prove supported traversal equivalence. |
| 13 | MCP memory service proof | package-ready or sibling package | Expose memory read/search/import/governance surfaces to non-OpenMinion MCP clients. | MCP smoke proves capability discovery and refusal of unsupported operations. |
| 14 | Workbench navigation polish | package-ready | Improve local visual memory browsing: search, filters, node detail, timeline, imports, and export. | Static artifact helps users inspect memory without hosted services. |
| 15 | Portable bundle verification | package-ready | Add bundle hash, schema, backend posture, vector policy, and migration report checks. | Backup/restore smoke proves the same memory graph and governance metadata survive. |
| 16 | Privacy and redaction profiles | package-ready | Centralize public/local/private export profiles for notes, sources, actors, and vectors. | Export profile tests prove redaction behavior and no accidental raw-vector leakage. |
| 17 | Memory candidate queue | package-ready | Add review/promote/deny flows for proposed records from human imports or agents. | Candidates remain non-authoritative until approved and emit audit evidence. |
| 18 | Retrieval eval scorecards | package-ready | Add deterministic fixtures that score retrieval stage behavior and regression changes. | Scorecards compare keyword, graph, temporal, trust, and vector stages. |
| 19 | Sophia-to-Pragma citation policy | runtime-adjacent | Define how memory records cite PragmaGraph static facts without Pragma storing Sophia judgments. | Evidence refs use typed URIs and preserve one-way authority. |
| 20 | Public recipes and sample datasets | package-ready | Provide one-command examples for notes, imports, search, vector lifecycle, export, and workbench. | Examples run without machine-local paths and are covered by smoke tests. |

## Recommended Order

1. `Rank 1` human note manager depth.
2. `Rank 3` retrieval evidence unification.
3. `Rank 8` store capability UI and CLI.
4. `Rank 15` portable bundle verification.
5. `Rank 14` workbench navigation polish.

This order finishes the human-facing memory loop before adding optional vector
or hosted backends.

## Non-Goals

1. Do not add a remote vector provider from this spec alone.
2. Do not call embedding providers from package code.
3. Do not make background sync or hosted services default.
4. Do not store PragmaGraph facts as Sophia judgments unless a memory record is
   explicitly approved.
5. Do not open twenty executable lanes at once.

## Promotion Rule

Each roadmap item must be promoted into a narrow tracker before implementation.
That tracker must name:

1. accepted scope,
2. memory governance impact,
3. import/export and deletion impact,
4. optional dependency posture,
5. focused validation,
6. package release-check impact,
7. follow-up routing for anything not executed.
