# Backend Compatibility Matrix

Status: active

SophiaGraph keeps backend adapters behind a typed `GraphBackendAdapter`
contract. Core installs remain provider-free except for the default
package-local dependencies declared in `pyproject.toml`; real graph engines are
optional extras.

| Backend | Install | Current role | Batch behavior | Delete | Watermark | Inventory | Pattern query |
| --- | --- | --- | --- | --- | --- | --- | --- |
| In-memory store | default | canonical records and tests | n/a | canonical APIs | n/a | package queries | package queries |
| SQLite store | default | canonical durable storage | n/a | canonical APIs | n/a | package queries | package queries |
| Fake graph backend | default | adapter conformance | atomic | yes | yes | yes | opt-in |
| Kuzu graph backend | `sophiagraph[kuzu]` | embedded derived index | idempotent partial | yes | yes | yes | no |
| Neo4j graph backend | `sophiagraph[neo4j]` | external derived index | idempotent partial | yes | yes | yes | no |

## Vector backends

| Backend | Install | Stored vectors | Filters | Wait posture | Watermark | Inventory |
| --- | --- | --- | --- | --- | --- | --- |
| Built-in deterministic math | default | caller-provided candidates | caller-side | n/a | n/a | n/a |
| Fake vector backend | default | yes | namespace + payload | synchronous | yes | yes |
| Qdrant | `sophiagraph[qdrant]` | yes | namespace + payload | explicit | yes | client `scroll` required |

## Adapter guarantees

- Adapters accept structured `GraphBackendQuery` DTOs.
- Adapters do not accept free-form Cypher generated from prose.
- Optional providers lazy-import inside adapter construction.
- Backend conformance should reuse the same harness for fake and real adapters.
- Projection delivery is at least once; adapter writes and deletes must be
  idempotent under replay.
- `plan_backend_execution(...)` reports native pushdown and local fallback per
  declared capability instead of hiding backend limitations.

## Choosing a backend

- Use the default memory/SQLite stores for local-first durable memory.
- Use the fake backend for package tests, examples, and adapter conformance.
- Use Kuzu when a local embedded graph engine is useful.
- Use Neo4j when the host runtime already operates an external graph database.
- Use Qdrant when the host supplies embeddings and needs external vector
  storage with namespace and payload filtering.

## Capability reporting

Use `build_store_capability_report(store)` when callers need a single typed
view of backend posture. The report covers durability, backup/export/import,
keyword and FTS availability, relation/block/vector lifecycle support, active
model-set counts, and backend diagnostics.

Detailed storage and retrieval parity guidance lives in
[`storage-retrieval-backends.md`](storage-retrieval-backends.md).
Projection checkpoints, retries, and repair guidance live in
[`durable-projections.md`](durable-projections.md).
