# Sophiagraph Storage Retrieval Backends Tracker

Date: 2026-07-02
Status: done
Owner: Sophiagraph
Related:
[`../specs/storage-retrieval-backends-2026-07-02-spec.md`](../specs/storage-retrieval-backends-2026-07-02-spec.md),
[`../backend-compatibility-matrix.md`](../backend-compatibility-matrix.md),
[`../retrieval-boundary.md`](../retrieval-boundary.md),
[`../vector-conformance.md`](../vector-conformance.md),
[`../human-management.md`](../human-management.md),
[`../workspace-mode.md`](../workspace-mode.md)

## Purpose

Track the package work required to make Sophiagraph storage, retrieval, graph
backends, vector backends, and human-managed knowledge flows interchangeable
without weakening memory governance or package boundaries.

This tracker executed the package-local storage capability, default-store
parity, portability, documentation, and public example slice. It did not
approve version bumps, new optional dependencies, hosted services, or automatic
embedding-provider execution.

## Review State

Current state:

1. `12/12` active rows are complete.
2. `0/12` active rows remain `todo`.
3. no version change was made.
4. no new optional dependency was added.
5. deferred optional backend rows remain reserved behind their entry
   conditions.

## Execution Board

| ID | Priority | Class | Status | Task | Why it matters | Entry condition |
| --- | --- | --- | --- | --- | --- | --- |
| `SGSRT-00` | P0 | review gate | `done` | Accept or revise the storage/retrieval backend scope. | Prevents backend work from weakening governance, privacy, or package retrieval boundaries. | Operator accepts backend order and vector adapter posture. |
| `SGSRT-01` | P0 | contract | `done` | Add a typed store capability report across in-memory and SQLite stores. | Callers need to know which search/export/backup/vector features are available. | Scope accepted. |
| `SGSRT-02` | P0 | conformance | `done` | Add in-memory vs SQLite retrieval parity fixtures for records, blocks, relations, filters, and graph snapshots. | The two default stores should answer supported retrieval questions consistently. | Capability DTO shape accepted. |
| `SGSRT-03` | P0 | SQLite | `done` | Document and test SQLite FTS coverage, ranking posture, and block/record search parity. | SQLite is the default durable search store, so its search behavior must be explicit. | `SGSRT-02` fixtures ready. |
| `SGSRT-04` | P0 | portability | `done` | Harden import/export reporting for vectors, external vector ids, governance metadata, and deletion state. | Users need portable backups without accidentally leaking or dropping vector/governance state. | Existing portability paths inventoried. |
| `SGSRT-05` | P1 | retrieval | `done` | Surface retrieval-stage evidence across keyword, graph, temporal, trust, and vector stages. | Agents and humans need to see why a memory appeared. | Retrieval DTO impact accepted. |
| `SGSRT-06` | P1 | human management | `done` | Show backend/search capability posture in human note/import/workbench flows. | Human-managed notes should use the same search and storage truth as agent memories. | Capability report exists. |
| `SGSRT-07` | P1 | graph backend | `done` | Strengthen fake/Kuzu/Neo4j graph backend conformance and capability diagnostics. | Optional graph stores need predictable traversal behavior and typed unsupported-mode errors. | Backend compatibility matrix updated. |
| `SGSRT-08` | P1 | vector contract | `done` | Extend vector conformance for external-vector ids, deletion/orphan handling, and export posture. | Vector backends are useful only if lifecycle and portability are honest. | Current vector conformance reviewed. |
| `SGSRT-09` | P1 | docs | `done` | Update backend compatibility, retrieval boundary, vector conformance, and human-management docs. | Public docs should explain how storage choice affects retrieval and export. | Contract names settled. |
| `SGSRT-10` | P1 | examples | `done` | Add examples showing SQLite search, portability round-trip, and vector-backend conformance registration. | Users need runnable backend recipes, not only API descriptions. | `SGSRT-01` through `SGSRT-04` landed. |
| `SGSRT-CQ` | P0 | closeout | `done` | Run package validation and route deferred backend owners. | Prevents hidden backend backlog and unsupported public claims. | Active rows complete or routed. |

## Deferred And Reserved Rows

| ID | Class | Status | Task | Entry condition |
| --- | --- | --- | --- | --- |
| `SGSRT-F01` | optional vector backend | `deferred` | Add Zvec-backed local vector adapter. | Vector lifecycle/export conformance lands and `sophiagraph[zvec]` optional dependency policy is accepted. |
| `SGSRT-F02` | optional vector backend | `deferred` | Add LanceDB-backed vector adapter. | A concrete consumer needs LanceDB local/remote vector tables. |
| `SGSRT-F03` | remote vector backend | `deferred` | Add DashVector, Milvus, or Zilliz adapter. | Hosted consumer, privacy posture, and secret/config ownership are accepted. |
| `SGSRT-F04` | graph backend expansion | `deferred` | Add richer Kuzu/Neo4j graph pattern coverage. | Existing DTO-only graph query surface proves demand beyond current traversal modes. |

## Boundary Rules

1. Sophiagraph owns approved memory knowledge, not raw static code/doc facts.
2. Stores must preserve namespace, privacy, trust, temporal, deletion, and
   governance metadata.
3. Retrieval runs only over approved stored package facts.
4. Package code does not call embedding providers directly.
5. Vector backends rank and retrieve; they do not infer new memory records.
6. Optional backends lazy-import and report typed missing-dependency errors.
7. Hosted services and background embedding refresh are not approved by this
   tracker.

## Validation Checklist

Implementation closeout must include:

1. `PYTHONDONTWRITEBYTECODE=1 make check`,
2. `PYTHONDONTWRITEBYTECODE=1 make release-check` when public imports,
   packaging, or extras change,
3. default-store retrieval parity tests,
4. import/export round-trip tests,
5. vector lifecycle and orphan external-id tests,
6. missing optional dependency tests,
7. graph backend conformance tests for accepted graph changes,
8. public docs examples with repo-relative paths only.

## Validation Evidence Log

| Date | Owner | Rows | Evidence |
| --- | --- | --- | --- |
| 2026-07-02 | codex | `SGSRT-00` | Scope accepted as a package-local default-store capability, retrieval parity, portability, docs, and public-example slice. No version bump, optional dependency, hosted service, or provider-owned embedding execution was approved. |
| 2026-07-02 | codex | `SGSRT-01`, `SGSRT-03`, `SGSRT-06` | Added `sophiagraph.storage.capabilities.StoreCapabilityReport` and `build_store_capability_report`, exported through `sophiagraph.storage` and the top-level package. Reports cover backend, durability, backup/export/import, FTS, graph/block/relation support, vector lifecycle, external vector ids, active model sets, SQLite schema version, counts, and diagnostics. |
| 2026-07-02 | codex | `SGSRT-02`, `SGSRT-04`, `SGSRT-05`, `SGSRT-08` | Added `tests/test_storage_retrieval_backends.py` covering memory/SQLite capability reports, retrieval/search parity, relation lookup, graph snapshots, portability round-trip, embedding lifecycle metadata, active model sets, and orphan external vector id reporting. |
| 2026-07-02 | codex | `SGSRT-07` | Left optional Kuzu/Neo4j expansion deferred; updated public backend docs to point callers at capability reporting while preserving DTO-only graph-backend posture. |
| 2026-07-02 | codex | `SGSRT-09` | Updated `README.md`, `docs/README.md`, `docs/storage-retrieval-backends.md`, `docs/backend-compatibility-matrix.md`, `docs/retrieval-boundary.md`, `docs/vector-conformance.md`, `docs/human-management.md`, and `docs/examples.md` with repo-relative public guidance. |
| 2026-07-02 | codex | `SGSRT-10` | Added `examples/storage_retrieval_backends.py` and wired it into `tests/test_public_examples.py`; the example emits deterministic JSON over a memory-to-SQLite portability round-trip and capability reports. |
| 2026-07-02 | codex | `SGSRT-CQ` | Focused example/storage validation passed: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:../graphfakos/src python3.11 -m pytest tests/test_public_examples.py tests/test_storage_retrieval_backends.py` -> `16 passed`. |
| 2026-07-02 | codex | `SGSRT-CQ` | Broader storage/vector validation passed: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:../graphfakos/src python3.11 -m pytest tests/test_storage_retrieval_backends.py tests/test_memory_store.py tests/test_sqlite_store.py tests/test_vector_conformance.py tests/test_embedding_lifecycle.py tests/test_embedding_lifecycle_portability.py` -> `89 passed`. |
| 2026-07-02 | codex | `SGSRT-CQ` | Targeted lint passed: `PYTHONDONTWRITEBYTECODE=1 ruff check src/sophiagraph/storage/capabilities.py src/sophiagraph/storage/__init__.py src/sophiagraph/__init__.py tests/test_storage_retrieval_backends.py tests/test_public_examples.py examples/storage_retrieval_backends.py` -> `All checks passed!`. |
| 2026-07-02 | codex | `SGSRT-CQ` | Package validation passed: `PYTHONDONTWRITEBYTECODE=1 make check` -> Ruff format/check clean and `925 passed, 1 skipped`. |
| 2026-07-02 | codex | `SGSRT-CQ` | Release validation passed: `PYTHONDONTWRITEBYTECODE=1 make release-check` -> tests passed, `sophiagraph-0.0.1` sdist/wheel built, Twine check passed, installed smoke passed, UI export passed, GraphFakos artifact replay passed. |
| 2026-07-02 | codex | `SGSRT-CQ` | Workspace closeout gates passed: `cd ../openminion && .venv/bin/python3.11 -m ruff check .` -> `All checks passed!`; `cd ../openminion && make lint` -> passed. |
| 2026-07-02 | codex | `SGSRT-CQ` | Post-authoring cleanup trimmed `src/sophiagraph/storage/capabilities.py` from 161 to 144 LOC, kept the tests/example unchanged after review, tightened SQLite FTS capability proof across record and block FTS, and reran `PYTHONDONTWRITEBYTECODE=1 make check` -> `925 passed, 1 skipped`. |

## Deferred Owner Routing

| Deferred row | Routing |
| --- | --- |
| `SGSRT-F01` | Remains deferred until `sophiagraph[zvec]` optional dependency policy and vector lifecycle/export conformance acceptance land. |
| `SGSRT-F02` | Remains deferred until a concrete LanceDB consumer needs local/remote vector-table persistence. |
| `SGSRT-F03` | Remains deferred until hosted vector consumer, privacy, secret/config, and remote-backend ownership are accepted. |
| `SGSRT-F04` | Remains deferred until DTO-only graph query demand exceeds the current traversal modes. |

## Change Log

| Date | Change |
| --- | --- |
| 2026-07-02 | Executed active storage/retrieval backend rows, added default-store capability reports and parity tests, updated public docs/examples, and left optional vector/graph backend expansions deferred behind explicit entry conditions. |

## Research Notes

1. SQLite FTS5 remains the best default local text-search posture for durable
   memory records and blocks.
2. Kuzu and Neo4j are graph-query accelerators, not replacements for memory
   governance.
3. Zvec is the strongest local-first vector backend candidate because it is
   embedded, supports dense/sparse vectors, filtering, FTS, and hybrid search.
4. DashVector, LanceDB, Milvus, and Zilliz remain optional or remote vector
   reserves until a real consumer requires them.
5. These research notes intentionally duplicate the PragmaGraph storage
   interchange tracker at package-local altitude; update both package docs when
   the external storage baseline changes.
