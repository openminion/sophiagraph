# Durable Derived-Index Projections

Status: active

SophiaGraph keeps its memory/SQLite store and structural changefeed canonical.
Graph and vector services are derived indexes. The public
`sophiagraph.projections` surface delivers canonical events to those indexes
with durable checkpoints, leases, bounded retries, and explicit dead letters.

## Delivery contract

- Delivery is ordered and at least once per configured target.
- A target checkpoint advances only after the adapter write and optional
  target watermark succeed.
- Replaying an upsert or delete must be harmless for a conforming adapter.
- Embedding events carry identity and structural version metadata, never raw
  vectors. The vector projector loads the caller-supplied vector from the
  canonical store when it applies the event.
- The package does not claim distributed exactly-once delivery or immediate
  consistency between canonical and derived stores.

## Minimal graph projection

```python
from sophiagraph import FakeGraphBackendAdapter, SophiaGraphMemoryStore
from sophiagraph.projections import (
    GraphChangeProjector,
    ProjectionTarget,
    get_projection_health,
    run_projection_batch,
)

store = SophiaGraphMemoryStore()
store.register_projection_target(
    ProjectionTarget(
        target_id="local-graph",
        kind="graph",
        adapter_name="fake",
    )
)
backend = FakeGraphBackendAdapter()
result = run_projection_batch(
    store,
    target_id="local-graph",
    projector=GraphChangeProjector(backend),
    owner_id="explicit-host-worker",
    now="2026-07-16T12:00:00+00:00",
)
health = get_projection_health(
    store,
    target_id="local-graph",
    now="2026-07-16T12:00:00+00:00",
)
```

The host owns scheduling, credentials, adapter construction, and repair
authorization. A normal process may call `run_projection_batch(...)` on a
timer, but SophiaGraph does not start a background thread or service.

## Retry and recovery

Projection failures persist a closed reason code, bounded error text, attempt
count, retry timestamp, and dead-letter state. An operator can inspect health,
release a dead letter after recovery, and run the same batch again. If a target
write succeeds but checkpoint persistence fails, replay relies on the adapter's
declared idempotent behavior.

## Reconciliation and repair

`reconcile_projection_target(...)` compares canonical and target inventories
using IDs, structural hashes, and watermarks. It reports missing, stale,
orphaned, watermark-mismatched, or unverifiable state without reading prose or
generating semantic repairs.

`apply_projection_repair_plan(...)` is mutation-capable only when the caller:

1. explicitly authorizes the operation,
2. supplies the report binding used to create the plan, and
3. proves that the canonical source cursor has not moved.

## Upgrade and rollback

SQLite schema version 19 adds package-owned projection target, checkpoint,
lease, attempt, and failure tables. Back up the canonical store before an
upgrade. Derived indexes may be discarded and rebuilt from the changefeed.
Rollback must restore the canonical database backup created before migration;
do not treat graph/vector indexes as the recovery authority.
