# Backend Compatibility Matrix

Status: active

SophiaGraph keeps backend adapters behind a typed `GraphBackendAdapter`
contract. Core installs remain provider-free except for the default
package-local dependencies declared in `pyproject.toml`; real graph engines are
optional extras.

| Backend | Install | Current role | Batch upsert | Schema | Neighbors | Property filter | Shortest path | Pattern query |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| In-memory store | default | record/relation storage and tests | n/a | package DTOs | package query helpers | package query helpers | package query helpers | package query helpers |
| SQLite store | default | durable local storage | n/a | package DTOs | package query helpers | package query helpers | package query helpers | package query helpers |
| Fake graph backend | default | conformance harness and examples | yes | yes | yes | yes | opt-in | opt-in |
| Kuzu graph backend | `sophiagraph[kuzu]` | embedded analytical graph backend | yes | yes | yes | yes | yes | no |
| Neo4j graph backend | `sophiagraph[neo4j]` | external graph database adapter | yes | yes | yes | yes | yes | no |

## Vector backends

| Backend | Install | Stored vectors | Namespace filters | Payload filters | Health check |
| --- | --- | --- | --- | --- | --- |
| Built-in deterministic math | default | caller-provided candidates | caller-side | caller-side | n/a |
| Qdrant | `sophiagraph[qdrant]` | yes | yes | yes | yes |

## Adapter guarantees

- Adapters accept structured `GraphBackendQuery` DTOs.
- Adapters do not accept free-form Cypher generated from prose.
- Optional providers lazy-import inside adapter construction.
- Backend conformance should reuse the same harness for fake and real adapters.
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
