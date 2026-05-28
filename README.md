<p align="center">
  <img src="https://www.openminion.com/brand/sophiagraph-logo.png" alt="Sophiagraph logo" width="128" />
</p>

<h1 align="center">Sophiagraph</h1>

<p align="center">
  <strong>Standalone wisdom graph substrate for durable agent memory.</strong>
</p>

<p align="center">
  <a href="https://github.com/openminion/sophiagraph">GitHub</a>
  · <a href="https://pypi.org/project/sophiagraph/">PyPI</a>
  · <a href="https://www.openminion.com">Website</a>
  · <a href="https://x.com/OpenMinion">X</a>
</p>

<p align="center">
  <a href="https://pypi.org/project/sophiagraph/"><img alt="PyPI" src="https://img.shields.io/pypi/v/sophiagraph?color=3775A9"></a>
  <a href="https://pypi.org/project/sophiagraph/"><img alt="Python" src="https://img.shields.io/pypi/pyversions/sophiagraph"></a>
  <a href="LICENSE"><img alt="License" src="https://img.shields.io/badge/license-Apache--2.0-blue"></a>
  <img alt="Status" src="https://img.shields.io/badge/status-publish--ready%20alpha-5B8DEF">
</p>

`sophiagraph` is a standalone wisdom graph substrate for durable agent memory.
The name comes from Greek `Sophia` (`Σοφία`), meaning wisdom; in this package it
frames durable knowledge as a graph of records, relations, provenance, trust,
and portable snapshots.

## Trust and Brand Safety

- Official GitHub: `https://github.com/openminion`
- Official website: `https://www.openminion.com`
- Official X account: `https://x.com/OpenMinion`

`sophiagraph` has no official token, coin, NFT, airdrop, staking program,
treasury product, or investment offering. Any claim otherwise is unauthorized
and should be treated as a scam.

## License and brand-use boundary

- Source code license: `Apache-2.0`
- Brand/trademark grant: `none`

The software license grants rights to use, modify, and redistribute the code.
It does **not** grant rights to use the Sophiagraph, Sophiagraph Server, or
OpenMinion names, logos, branding, website identity, or social identity except
for truthful attribution. Forks, clones, and derivative distributions must not
present themselves as the official Sophiagraph project or imply affiliation,
endorsement, or maintenance by Sophiagraph or OpenMinion contributors unless
that is actually true.

## What the package provides

`sophiagraph` currently provides:

- canonical durable-memory models
- contract and provenance helpers
- query DTOs
- portability bundle models and codec helpers
- audit-event schemas
- trust and temporal primitives
- typed namespace DTOs for explicit tenant/user/agent/session isolation
- directed relation APIs with explicit incoming/outgoing/bidirectional lookup
- Obsidian-style structural document/link DTOs, Markdown/frontmatter adapter,
  addressable blocks, backlinks, outgoing links, local graph traversal, graph
  snapshots, deterministic graph algorithms, structural search DTOs, saved view
  evaluation, JSON Canvas DTOs, schema discovery, async facade helpers, and
  extension hooks
- a package-local SQLite durable engine
- a package-local in-memory backend for tests and ephemeral consumers
- a standalone smoke entrypoint for publish/install validation

## What the package does not provide

This package does **not** provide:

- application orchestration or gateway policy
- a full Obsidian clone, editor, sync service, or visual renderer
- provider/model routing
- session orchestration
- automatic link, tag, relation, entity, or summary inference from prose
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
PYTHONPATH=src python3.11 examples/obsidian_substrate.py
```

## SQLite Write Safety

The SQLite backend configures each package-owned connection with:

- `PRAGMA journal_mode = wal`
- `PRAGMA busy_timeout = 5000`
- `PRAGMA synchronous = normal`

Writes use explicit transaction boundaries. This keeps a sibling reader, such
as a local service process or a second host process, from blocking ordinary
package writes under the common read-while-write SQLite case.

For production-like local use:

- create one store instance per process or worker, not one shared connection;
- expect SQLite's normal single-writer behavior even with WAL enabled;
- keep write transactions short and caller-owned payloads already structured;
- use `backup(...)` for online copies instead of copying live `*.sqlite3` files.

SQLite backups are available through the store:

```python
store = create_sqlite_store("/tmp/sophiagraph-demo")
store.backup("/tmp/sophiagraph-demo-backup.sqlite3")
```

New durable tables should follow the cross-table migration convention in the
docs workspace:
`docs/discussions/sophiagraph-cross-table-migration-convention-2026-05-23.md`.

## Changefeed and Delta Sync

Package stores expose append-only structural change events for durable mutation
surfaces. Current events cover records, relations, links, candidates, tier
transitions, and document blocks.

```python
changes = store.list_changes(since_cursor=0, namespaces=[namespace_filter])
delta = store.export_delta(namespaces=[namespace_filter])
target_store.import_delta(delta)
```

Change events carry caller-supplied structural payloads, namespace dimensions,
cursor order, and schema identifier strings such as `node_label` or
`relation_type`. `sophiagraph` does not infer event meaning from prose.

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

## Graph Relations

Relations are explicit, typed, directed edges between records. Consumers can
list outgoing, incoming, or bidirectional edges through the `direction` option:

```python
outgoing = store.list_relations("rec-1")
incoming = store.list_relations("rec-1", direction="in")
neighborhood = store.get_related_records(
    "rec-1",
    ["agent:demo"],
    direction="both",
)
```

The package does not infer relation types from prose. Callers must submit
relation records directly.

## Obsidian-Style Knowledge Graph Substrate

`sophiagraph` now has package-core surfaces for Obsidian-comparable structural
workflows:

- `KnowledgeDocument` wraps document-profile `MemoryRecord` nodes with path,
  title, aliases, content hash, namespace, timestamps, and provenance.
- `StructuralLink` represents explicit wikilinks, Markdown links, embeds,
  property links, external URLs, unresolved targets, headings, and block refs.
- `extract_markdown(...)` parses frontmatter, aliases, tags, and explicit link
  syntax without modifying note prose.
- `KnowledgeDocumentBlock` rows represent explicit headings and `^block-id`
  anchors; stores expose `put_document_blocks(...)` and
  `list_document_blocks(...)`.
- Store backends expose `put_link(...)`, `list_links(...)`,
  `get_backlinks(...)`, `get_outgoing_links(...)`, `get_local_graph(...)`, and
  `get_graph_snapshot(...)`.
- SQLite structural search uses FTS5 record and block indexes when available
  and keeps a deterministic Python fallback for unsupported SQLite builds.
- `sophiagraph.query` exposes deterministic graph helpers for shortest paths,
  path evidence, connected components, and degree centrality over explicit
  graph snapshots.
- Saved views evaluate deterministic filters, boolean groups, link predicates,
  grouping, sorting, projections, and summaries.
- JSON Canvas and extension hooks are package-local DTO/helper surfaces. They
  do not require a UI renderer or OpenMinion import.

Example:

```python
from sophiagraph.adapters.markdown import extract_markdown
from sophiagraph.models import LinkResolutionCandidate, MemoryNamespace
from sophiagraph.query import LinkQueryOptions, LocalGraphOptions, shortest_path

namespace = MemoryNamespace(agent_id="demo", graph_id="main")
imported = extract_markdown(
    "See [[Roadmap]].",
    path="Index.md",
    record_id="rec-index",
    namespace=namespace,
    resolver_candidates=[
        LinkResolutionCandidate(
            record_id="rec-roadmap",
            path="Roadmap.md",
            title="Roadmap",
            namespace=namespace,
        )
    ],
)
for link in imported.links:
    store.put_link(link)

backlinks = store.list_links(LinkQueryOptions(record_id="rec-roadmap", direction="in"))
local_graph = store.get_local_graph(LocalGraphOptions(record_id="rec-index", depth=1))
path = shortest_path(local_graph, "rec-index", "rec-roadmap")
```

The resolver contract is deliberately structural: explicit path first, then
case-insensitive title/alias matching inside the namespace. Unresolved and
ambiguous targets are preserved as first-class outcomes. Unlinked mentions are
not persisted as graph edges.

## Schema and Async Helpers

Use `sophiagraph.schema.describe_schema(...)` to inspect current property-graph
labels, relation types, property keys, namespace dimensions, and property-type
conflicts from explicit records/relations/links/blocks.

The optional async facade wraps a sync store without adding provider or async
database dependencies:

```python
from sophiagraph.storage import async_store

async_facade = async_store(store)
record = await async_facade.get_record("rec-1")
```

## Search and SQLite Connections

Current structural search uses deterministic matching with SQLite FTS5
candidate narrowing for record and block text when FTS5 is available. It is not
yet a vector-backed or reranked retrieval engine. The hybrid retrieval roadmap
owns the future vector/rerank design.

`SophiaGraphSqliteStore` opens a short-lived SQLite connection per method call.
That keeps alpha behavior simple and avoids hidden shared connection state. A
pooled or long-lived connection strategy should be introduced only with a
separate lifecycle/concurrency contract.

## Cross-Package Compatibility DTOs

Some contract DTOs, including runtime snapshot/capsule/query shapes and
`MemoryPatchResult`, are retained for host-runtime adapters such as OpenMinion
and future service surfaces. They are compatibility contracts; package-local
stores are not required to instantiate every DTO.

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
- `sophiagraph.adapters`
- `sophiagraph.canvas`
- `sophiagraph.extensions`
- `sophiagraph.views`
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
