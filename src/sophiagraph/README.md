# Sophiagraph Package Layout

`sophiagraph` is the standalone wisdom-graph package for durable agent memory.

## Public contract

The public package surface is documented in:

1. `README.md`
2. `API_COMPATIBILITY.md`
3. `docs/reference/`

The preferred public entrypoint is `sophiagraph`, with stable import roots for
models, query, storage, portability, audit, trust, connectors, graph backends,
inspection, and `sophiagraph.ui`.

## Source-tree owner map

1. `models/` owns typed durable-memory DTOs.
2. `storage/` owns in-memory, SQLite, lifecycle, portability, and changefeed
   behavior.
3. `query/` owns retrieval, graph, explorer, structural, temporal, and block
   query helpers.
4. `contracts/`, `audit/`, `trust/`, and `temporal/` own typed policy and
   governance boundaries.
5. `adapters/`, `connectors.py`, `sync.py`, and `freshness.py` own package-side
   connector and replay helpers.
6. `graph_backends/` owns optional graph-adapter contracts and concrete local
   backends.
7. `ui/` owns typed UI contracts only; runtime/browser implementation belongs
   outside the package.

## Repo-local but not public API

1. `tests/` contains the certification, regression, and compatibility harness.
2. `examples/` are package demos, not wider host-runtime guarantees.
3. Root-repo planning and execution docs stay under the workspace `docs/`
   tree instead of inside the package source tree.
