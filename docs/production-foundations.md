# Production Foundations

Status: semantic alpha

SophiaGraph exposes provider-neutral production contracts while keeping default
installs local-first and deterministic.

## Compatibility

`sophiagraph.compatibility` reports the installed GraphFakos version and emits
a sorted public API manifest. GraphFakos 0.0.5 is the minimum supported
release. `make validate-patterns` checks the committed
manifest, while CI runs focused integration tests against the minimum and
latest supported GraphFakos versions.

## Vector backends

The built-in vector math and conformance harness remain dependency-free. The
optional `sophiagraph[qdrant]` extra adds a stored-vector backend with explicit
collection creation, caller-supplied embeddings, namespace filters, payload
filters, deletion, and health checks.

SophiaGraph never selects an embedding model or calls an embedding provider.

## Backend planning and ingestion

`sophiagraph.backend_planning` produces deterministic backend-versus-local
execution plans from declared capabilities. Unsupported pushdown is visible as
`local_fallback`; it is never silently treated as native backend support.

`sophiagraph.ingestion` executes ordered connector envelopes with idempotent
ingest identifiers, bounded batches, resumable checkpoints, and typed
per-item results.

## Telemetry and security

`sophiagraph.telemetry` records only allowlisted low-cardinality attributes.
Query text, record identifiers, and payload bodies are excluded. OpenTelemetry
is available through the optional `telemetry` extra.

`sophiagraph.security` provides caller-owned key and authenticated-encryption
contracts. AES-256-GCM is available through the optional `encryption` extra.
Callers remain responsible for key storage, access policy, and rotation.

## Server deployment posture

The optional server supports an enforceable production profile with bounded
request size, required authentication, request identifiers, and quotas. It is
enabled with `sophiagraph-server serve-stdio --production` and requires static
bearer auth plus a quota configuration.

## Views and collaboration

`sophiagraph.materialized_views` caches deterministic saved-view results and
uses changefeed cursors to decide when refresh is required.

`sophiagraph.collaboration` ships a conservative three-way merge adapter. It
merges independent field edits and preserves concurrent edits as typed
conflicts instead of guessing or silently applying last-write-wins.

## Scale certification

`sophiagraph.production_benchmarks` defines operator-run 10K, 100K, and 1M
item profiles with p50/p95 timing results. Workload callbacks are supplied by
the operator so SQLite, Kuzu, Neo4j, Qdrant, and host-runtime scenarios can use
the same report shape without provider dependencies in core.
