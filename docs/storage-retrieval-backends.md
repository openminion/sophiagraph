# Storage Retrieval Backends

Status: semantic alpha

Sophiagraph stores approved memory knowledge. Its stores are not rebuildable
caches over source files; they are the durable substrate for records, relations,
namespaces, trust, temporal state, deletion state, embedding lifecycle metadata,
and portable memory bundles.

## Default Stores

| Store | Role | Durable? |
| --- | --- | --- |
| `SophiaGraphMemoryStore` | In-memory store for tests, examples, and ephemeral local consumers. | no |
| `SophiaGraphSqliteStore` | Package-local durable SQLite store with FTS-backed record/block search when FTS5 is available. | yes |

Both stores expose the same public store protocol for records, candidates,
relations, document blocks, memory blocks, graph snapshots, embeddings,
active model sets, orphan external vector IDs, export/import, and deltas.

## Capability Report

Use `build_store_capability_report` to inspect backend posture without guessing
from the concrete class:

```python
from sophiagraph import SophiaGraphSqliteStore, build_store_capability_report

store = SophiaGraphSqliteStore(".sophiagraph/sophiagraph.sqlite3")
report = build_store_capability_report(store)

print(report.to_dict())
```

The report includes:

1. backend name,
2. durable/backup/export/import posture,
3. keyword and FTS search posture,
4. graph, relation, block, and memory-block support,
5. namespace, deletion, vector lifecycle, and active-model-set support,
6. record/candidate/embedding/model-set counts,
7. SQLite schema version and diagnostics when applicable.

## Retrieval Parity

The default stores are expected to agree on supported queries:

```python
from sophiagraph import (
    ListQueryOptions,
    SearchQueryOptions,
    SophiaGraphMemoryStore,
)

store = SophiaGraphMemoryStore()

records = store.list_records(ListQueryOptions(scopes=["agent:local"]))
hits = store.search_records(
    SearchQueryOptions(query="operator preference", scopes=["agent:local"])
)
```

SQLite may use FTS5 internally, but the public contract remains deterministic:
unsupported or unavailable FTS must not silently alter governance, namespace, or
portability semantics.

## Portability And Vector Lifecycle

Portable memory bundles preserve memory governance and embedding lifecycle
metadata when explicitly requested:

```python
from sophiagraph import MemoryBundleExportOptions, MemoryBundleImportOptions

snapshot = store.export_snapshot(
    MemoryBundleExportOptions(
        scopes=["agent:local"],
        include_relations=True,
        include_memory_blocks=True,
        include_embedding_lifecycle=True,
    )
)

result = store.import_snapshot(snapshot, MemoryBundleImportOptions())
```

Vector backends rank and retrieve approved stored facts. They do not infer new
memory records, choose embedding providers, or run embedding jobs. Hosts own
provider execution and scheduling; Sophiagraph stores lifecycle metadata,
active model sets, stale findings, and orphan external vector IDs.

## Boundary

Optional Kuzu, Neo4j, Zvec, LanceDB, DashVector, Milvus, and Zilliz integrations
remain optional or deferred unless a concrete consumer accepts their dependency,
privacy, and export posture. Missing optional backends should report typed
capability diagnostics rather than changing retrieval behavior silently.
