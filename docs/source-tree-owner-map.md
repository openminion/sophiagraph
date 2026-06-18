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
inspection, `sophiagraph.ui`, and `sophiagraph.workspace`.

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
6. `human.py` owns package-local note/import/source management helpers over the
   canonical store and import surfaces.
7. `workspace.py` owns the package-local persistent workspace posture and
   explicit import bridge around the human-management and store surfaces.
8. `graph_backends/` owns optional graph-adapter contracts and concrete
   backends.
9. `ui/` owns typed UI contracts only; runtime and browser implementation
   belongs outside the package.

## Repo-local but not public API

1. `tests/` contains the certification, regression, and compatibility harness.
2. `examples/` are package demos, not wider host-runtime guarantees.
3. Repository planning and execution docs stay in the workspace `docs/` tree
   instead of the package source tree.
