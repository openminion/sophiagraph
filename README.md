# sophiagraph

Status: `publish-ready alpha`
Shape: standalone Python package
License: `Apache-2.0`

`sophiagraph` is a standalone wisdom graph substrate for durable agent memory.
The name comes from Greek `Sophia` (`Σοφία`), meaning wisdom; in this package it
frames durable knowledge as a graph of records, relations, provenance, trust,
and portable snapshots.

## What the package provides

`sophiagraph` currently provides:

- canonical durable-memory models
- contract and provenance helpers
- query DTOs
- portability bundle models and codec helpers
- audit-event schemas
- trust and temporal primitives
- typed namespace DTOs for explicit tenant/user/agent/session isolation
- a package-local SQLite durable engine
- a package-local in-memory backend for tests and ephemeral consumers
- a standalone smoke entrypoint for publish/install validation

## What the package does not provide

This package does **not** provide:

- application orchestration or gateway policy
- provider/model routing
- session orchestration
- implicit imports back into any host framework

Host frameworks remain the orchestrators. `sophiagraph` owns reusable durable
wisdom graph primitives and the standalone durable engine.

## Install

Editable install during local development:

```bash
python3.11 -m pip install -e .
```

Wheel build:

```bash
python3.11 -m build
```

Fresh-wheel smoke:

```bash
TMP_VENV="$(mktemp -d)/sophiagraph-venv"
python3.11 -m venv "$TMP_VENV"
"$TMP_VENV/bin/pip" install dist/sophiagraph-*.whl
"$TMP_VENV/bin/sophiagraph-smoke" --root /tmp/sophiagraph-release-smoke --seed --json
```

## Standalone Smoke

Source-root smoke:

```bash
PYTHONPATH=src python3.11 -m sophiagraph --root /tmp/sophiagraph-smoke --seed --json
```

Installed-console-script smoke:

```bash
sophiagraph-smoke --root /tmp/sophiagraph-smoke --seed --json
```

## External Consumer Quickstart

Minimal standalone flow for another framework or service:

```python
from sophiagraph.models import MemoryNamespace, MemoryRecord
from sophiagraph.portability.models import MemoryBundleExportOptions, MemoryBundleImportOptions
from sophiagraph.query import ListQueryOptions, SearchQueryOptions
from sophiagraph.storage import create_memory_store, create_sqlite_store

store = create_sqlite_store("/tmp/sophiagraph-demo")
namespace = MemoryNamespace(
    tenant_id="tenant-demo",
    user_id="user-demo",
    agent_id="demo",
    graph_id="main",
)
store.put_record(
    MemoryRecord(
        id="rec-1",
        scope="agent:demo",
        type="fact",
        key="project:apollo",
        title="Apollo launch date",
        content={"text": "Apollo launched in Q2"},
        created_at="2026-05-22T00:00:00+00:00",
        updated_at="2026-05-22T00:00:00+00:00",
        source="validated",
        confidence=0.95,
        event_time="2026-05-22T00:00:00+00:00",
        namespace=namespace,
    )
)

namespace_filter = MemoryNamespace(agent_id="demo")
records = store.list_records(
    ListQueryOptions(scopes=["agent:demo"], namespaces=[namespace_filter])
)
search_hits = store.search_records(
    SearchQueryOptions(query="Apollo", scopes=["agent:demo"], namespaces=[namespace_filter])
)
snapshot = store.export_snapshot(
    MemoryBundleExportOptions(scopes=["agent:demo"], namespaces=[namespace_filter])
)
import_store = create_memory_store()
import_store.import_snapshot(snapshot, MemoryBundleImportOptions())
```

Runnable example:

```bash
PYTHONPATH=src python3.11 examples/basic_usage.py
```

## Typed Namespaces

Records still accept the legacy `scope` string for compatibility. New
integrations can also attach typed namespace DTOs to records and use the same
typed dimensions for query/export/import boundaries:

```python
from sophiagraph.models import MemoryNamespace

namespace = MemoryNamespace(
    tenant_id="tenant-acme",
    user_id="user-j",
    agent_id="agent-codex",
    session_id="session-123",
    graph_id="main",
)

legacy_scope = namespace.to_scope("agent")

record = MemoryRecord(
    id="rec-namespace",
    scope=legacy_scope,
    type="fact",
    content={"text": "Namespace-safe records keep tenant and agent separate."},
    created_at="2026-05-23T00:00:00+00:00",
    updated_at="2026-05-23T00:00:00+00:00",
    namespace=namespace,
)

records = store.list_records(
    ListQueryOptions(scopes=[legacy_scope], namespaces=[MemoryNamespace(agent_id="agent-codex")])
)
```

Namespace values must be explicit caller-provided identifiers. `sophiagraph`
does not infer tenant, user, project, or agent identity from prose. Existing
SQLite rows without namespace columns are migrated from their explicit legacy
`scope` value only; no content or title text is inspected.

## Import Boundary Rule

`sophiagraph` must never import from host frameworks such as OpenMinion.

Dependency direction is one-way:

- allowed: host framework -> `sophiagraph`
- forbidden: `sophiagraph` -> host framework

## Public API

Stable top-level exports for external consumers:

- `sophiagraph.SophiaGraphSqliteStore`
- `sophiagraph.SophiaGraphMemoryStore`
- `sophiagraph.create_sqlite_store(...)`
- `sophiagraph.create_memory_store()`
- `sophiagraph.default_db_path(...)`
- `sophiagraph.audit`
- `sophiagraph.contracts`
- `sophiagraph.portability`
- `sophiagraph.trust`
- `sophiagraph.coerce_temporal_dt`

Supported import roots:

- `sophiagraph`
- `sophiagraph.models`
- `sophiagraph.query`
- `sophiagraph.storage`
- `sophiagraph.portability`
- `sophiagraph.audit`
- `sophiagraph.trust`
- `sophiagraph.temporal`
- `sophiagraph.contracts`

## API Compatibility

Compatibility and deprecation policy:

- `API_COMPATIBILITY.md`

## Release Docs

Package-local release runbook:

- `RELEASING.md`
- `scripts/release_check.py`
