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

`sophiagraph` is the standalone durable-memory package in the OpenMinion
family. Use it when you want typed records, relations, provenance, trust, and
portable memory snapshots outside a host runtime.

The name comes from Greek `Sophia` (`Σοφία`), meaning wisdom; in this package it
frames durable knowledge as a graph of records, relations, provenance, trust,
and portable snapshots.

## Trust and Brand Safety

- Official GitHub: `https://github.com/openminion/sophiagraph`
- Official website: `https://www.openminion.com`
- Official X account: `https://x.com/OpenMinion`

`sophiagraph` has no official token, coin, NFT, airdrop, staking program,
treasury product, or investment offering. Any claim otherwise is unauthorized
and should be treated as a scam.

## At a glance

- Current public package line: `0.0.1` alpha
- Best fit when: you want durable memory records, relations, provenance, trust,
  and exportable graph state outside a host runtime
- Backends today: a package-local SQLite engine, an in-memory backend for
  tests and ephemeral consumers, plus optional Kuzu and Neo4j graph adapters
- Public shape: typed memory models, storage contracts, governance helpers,
  portability bundles, workspace helpers, and package-local UI preview
  boundaries
- Not the claim: `sophiagraph` does not own orchestration, provider routing,
  hosted webhook delivery, or hosted admin/runtime UI behavior

## What Sophiagraph provides

`sophiagraph` currently provides:

- Core memory contracts: canonical durable-memory models, provenance helpers,
  query DTOs, namespace isolation, relation APIs, and portability bundle
  models/codecs
- Storage and portability: a package-local SQLite durable engine, an in-memory
  backend, standalone smoke validation, and graph/record export surfaces
- Governance and lifecycle: trust/policy primitives, audit events, temporal
  freshness helpers, vector metric/embedding lifecycle support, lifecycle
  policy evaluation, artifact records, and JSON Canvas contracts
- Interop and repair: connector ingestion envelopes, sync conflict DTOs,
  structural inspection reports, repair candidates, shared memory-block
  primitives, and optional Kuzu/Neo4j graph-backend adapters
- Local operations: note-management helpers, workspace/workbench helpers,
  deterministic live workspace sync, UI boundary contracts in
  `sophiagraph.ui`, and the `sophiagraph.okf` bundle profile for import/export
  workflows
- Human workflow helpers: candidate review/promotion queues, workspace
  history/recovery previews, and typed object templates for explicit
  creation flows

### Package vs service ownership for governance, lifecycle, and webhooks

`sophiagraph` (this package) is the **typed shape and deterministic
evaluator** for governance and lifecycle. It exposes:

- typed event DTOs and audit recorder callbacks (`sophiagraph.audit.*`),
- deterministic policy hook evaluation (`evaluate_policy_hooks` with
  short-circuit-on-first-deny semantics),
- pure lifecycle policy evaluation (`evaluate_policy` and
  `apply_decision_to_record_meta`),
- typed `WebhookDeliveryAttemptEvent` so service/admin consumers can
  align on the event shape.

`sophiagraph` does **NOT** open HTTP connections, run cron schedulers,
or deliver webhooks. Those are the responsibility of
`sophiagraph-server` (the runtime service) and the host runtime. The
package supplies the typed contract; the service supplies the
operational behavior.

## What Sophiagraph does not provide

This package does **not** provide:

- application orchestration or gateway policy
- a full Obsidian clone, editor, sync service, or visual renderer
- provider/model routing
- session orchestration
- automatic link, tag, relation, entity, or summary inference from prose
- automatic file sync conflict resolution, connector payload interpretation,
  shared-block reconciliation, Text2Cypher generation, or semantic repair
  suggestions from prose
- implicit imports back into any host framework
- HTTP webhook delivery, scheduled job execution, or hosted admin UI
  (those belong to `sophiagraph-server` or the host runtime)
- semantic policy decisions inferred from freeform model output (policy
  hooks must return typed `PolicyDecision` instances with closed-enum
  reason codes)
- direct embedding-provider calls, automatic re-embedding, or model-selection
  recommendations (hosts own provider execution and scheduling)

The current visual explorer command lives in `sophiagraph.ui` and renders
through GraphFakos, the shared graph lens package. Sophiagraph owns the
second-brain adapter and durable-memory semantics; GraphFakos owns the reusable
viewer shell, graph canvas, local server primitive, and static export surface.
Browser-facing runtime transport is still expected to route through
`sophiagraph-server` over the REST design pinned by SSSF-02 rather than private
in-process imports.

You can run the package-local visual UI today:

```bash
sophiagraph-ui \
  --screen explore \
  --serve \
  --open
```

Use a persistent workspace as the preview source:

```bash
sophiagraph-ui \
  --workspace <workspace-root> \
  --screen views \
  --serve
```

Use `--html-out` only when you want to export a standalone HTML snapshot. The
equivalent module form is `python3.11 -m sophiagraph ui-preview`.

Host frameworks remain the orchestrators. `sophiagraph` owns reusable durable
wisdom graph primitives and the standalone durable engine.

## Workspace Quickstart

Create one persistent local workspace with stored scope/namespace/import
defaults:

```bash
python3.11 -m sophiagraph workspace-init <workspace-root> \
  --scope agent:local \
  --agent-id local \
  --graph-id main \
  --label local-wisdom \
  --json
```

Inspect the workspace:

```bash
python3.11 -m sophiagraph workspace-status <workspace-root> --json
```

Preview a local markdown/canvas import:

```bash
python3.11 -m sophiagraph workspace-import-plan \
  <workspace-root> <notes-root> --json
```

Scan the same root as a file-primary live-sync source:

```bash
python3.11 -m sophiagraph workspace-sync-plan \
  <workspace-root> <notes-root> --json
```

Apply the typed live-sync plan and refresh the graph index:

```bash
python3.11 -m sophiagraph workspace-sync-apply \
  <workspace-root> <notes-root> --json
```

Write a canonical markdown note to disk first, then refresh the index:

```bash
python3.11 -m sophiagraph workspace-file-note-put \
  <workspace-root> <notes-root> welcome \
  --title "Welcome" \
  --body "Hello from a file-primary workspace." \
  --json
```

## OKF Interoperability Quickstart

Import a Google OKF-style bundle through the public package surface:

```python
from sophiagraph import MemoryNamespace, import_okf_bundle

bundle = import_okf_bundle(
    "<bundle-root>",
    namespace=MemoryNamespace(agent_id="local", graph_id="main"),
)

assert bundle.manifest.spec_commit
assert bundle.manifest.concept_count >= 0
```

Export the same bundle back to portable Markdown by default, or request
Obsidian-flavored output explicitly:

```python
from sophiagraph import export_okf_bundle, write_okf_bundle

portable_files = export_okf_bundle(bundle)
obsidian_files = export_okf_bundle(bundle, obsidian_compatible=True)
write_okf_bundle(bundle, "<portable-output-root>")
```

## Install

Editable install during local development:

```bash
python3.11 -m pip install -e .
```

Optional Kuzu backend support:

```bash
python3.11 -m pip install -e '.[kuzu]'
```

Optional Neo4j backend support:

```bash
python3.11 -m pip install -e '.[neo4j]'
```

Embedding lifecycle helpers are package-local and require no extra dependency.
Hosts provide the provider callback and vector-store operations; SophiaGraph
only emits typed findings, plans, registries, and orphan IDs.

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

## Docs and release

- `docs/README.md` summarizes the package-local docs contract.
- `docs/certification-readiness-matrix.md` records standalone and
  OpenMinion proof coverage for the public package surface.
- `docs/standalone-claim-alignment.md` maps public standalone claims
  to the concrete package surfaces and proof that ship today.
- `docs/retrieval-boundary.md` records the canonical package vs host
  retrieval ownership split.
- `docs/vector-conformance.md` records the vector registry and
  backend-conformance harness.
- `docs/human-management.md` records the package-owned human
  note/import/source management surface.
- `docs/workspace-mode.md` records the package-owned persistent local
  workspace and explicit local import-bridge surface.
- `docs/ui-contracts.md` records the package-owned UI boundary
  contract.
- `docs/source-tree-owner-map.md` explains the source-tree module
  layout and public-vs-repo-local boundary.
- `API_COMPATIBILITY.md` records the supported public import roots and
  top-level export policy.
- `RELEASING.md` records the package-local release and PyPI publish flow.
- `scripts/release_check.py` is the canonical release smoke entrypoint.

## Optional Graph Backend

Use SQLite or the in-memory store as the canonical SophiaGraph record store.
Reach for the optional Kuzu or Neo4j backends when you want the
provider-neutral export batch plus a graph adapter that can answer normalized
`neighbors`, `shortest_path`, `property_filter`, and `schema` queries.

```python
from sophiagraph import (
    GraphBackendQuery,
    KuzuGraphBackendAdapter,
    Neo4jGraphBackendAdapter,
    MemoryNamespace,
    MemoryRecord,
    build_graph_export_batch,
)

namespace = MemoryNamespace(agent_id="demo", graph_id="main")
records = [
    MemoryRecord(
        id="rec-a",
        scope="agent:demo",
        type="fact",
        key="a",
        title="A",
        content={"text": "A"},
        created_at="2026-06-03T00:00:00+00:00",
        updated_at="2026-06-03T00:00:00+00:00",
        namespace=namespace,
        meta={"properties": {"kind": "test"}},
    ),
]
batch = build_graph_export_batch(batch_id="demo", records=records)
backend = KuzuGraphBackendAdapter("/tmp/sophiagraph-demo.kuzu")
backend.upsert_batch(batch)
result = backend.query(
    GraphBackendQuery(
        query_id="q-schema",
        kind="schema",
    )
)
```

For Neo4j-backed usage, swap the adapter construction:

```python
backend = Neo4jGraphBackendAdapter(
    "neo4j://db.example.test:7687",
    auth=("neo4j", "password"),
)
```

The concrete backend adapters are still structural-only:

- callers pass typed backend DTOs, never freeform Cypher,
- labels, relation types, namespaces, and properties stay caller-supplied,
- unsupported features return typed `unsupported_reason` values.

## Structural Graph Query

Use the higher-level structural query envelope when you want one typed entry
point over bounded pattern traversal and namespace-wide community packets,
while keeping planner evidence deterministic and structural-only:

```python
from sophiagraph import (
    GraphPatternNodePredicate,
    MemoryNamespace,
    StructuralGraphQueryRequest,
    execute_structural_graph_query,
    structural_result_to_knowledge_plan,
)

namespace = MemoryNamespace(agent_id="demo", graph_id="main")
result = execute_structural_graph_query(
    store,
    StructuralGraphQueryRequest(
        query_id="q-pattern",
        mode="pattern",
        scopes=["agent:demo"],
        namespaces=[namespace],
        seed_record_ids=["rec-a"],
        node_predicates=[GraphPatternNodePredicate("kind", "eq", "test")],
        relation_types=["supports"],
        max_hops=2,
    ),
)
plan = structural_result_to_knowledge_plan(result)
```

This layer stays structural:

- no natural-language query parsing,
- no generated community labels or summaries,
- no provider-specific public query types.

## Operational Envelopes

Use the operational run envelope when you want one public, package-local
surface over sync conflicts, connector replay, freshness-driven reindex, and
inspection follow-up:

```python
from sophiagraph import (
    ConnectorReplayRequest,
    FreshnessLedgerEntry,
    SourceIngestEnvelope,
    SourceRegistryEntry,
    execute_operational_run,
)

source = SourceRegistryEntry(
    source_id="connector:fake",
    source_type="test_fake",
    namespace=namespace,
    display_name="Fake source",
    permission_scope="read_only",
)
freshness = FreshnessLedgerEntry.create(
    namespace=namespace,
    source_kind="connector",
    source_id=source.source_id,
    status="fresh",
    cursor="cursor-1",
    content_hash="hash-1",
)
envelope = SourceIngestEnvelope.create(
    source_id=source.source_id,
    namespace=source.namespace,
    payload_kind="document",
    payload={"id": "doc-1"},
    cursor="cursor-2",
    content_hash="hash-2",
)
report = execute_operational_run(
    ConnectorReplayRequest(
        run_id="replay-1",
        source=source,
        envelope=envelope,
        existing_freshness=freshness,
    )
)
```

Reports stay explicit:

- replay decisions remain typed,
- follow-up actions are structural and source-scoped,
- scheduler ownership stays outside `sophiagraph` core.

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

MCP-style host bridge without importing OpenMinion:

```python
from dataclasses import asdict

from sophiagraph.adapters import McpMemoryRequest, SophiaGraphMcpAdapter

adapter = SophiaGraphMcpAdapter(store)
adapter.handle(McpMemoryRequest(operation="create", payload={"record": asdict(record)}))
adapter.handle(
    McpMemoryRequest(
        operation="search",
        payload={"query": "Apollo", "scopes": ["agent:demo"], "limit": 5},
    )
)
```

Claude Code, Cursor, Windsurf, and other MCP hosts should wire this adapter
through their own MCP runtime package. `sophiagraph` supplies the structural
CRUD/search bridge; host-specific manifests, auth, process lifecycle, and
transport are owned by the host or an optional sibling adapter package.

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

New durable tables should keep migrations deterministic, idempotent, and
compatible with existing package stores.

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

Sophiagraph already owns a typed retrieval substrate over approved graph state.
Today that includes deterministic keyword search, optional vector-stage fusion,
graph expansion, recency weighting, trust weighting, explicit rerank inputs,
and explanation payloads for why a hit surfaced.

Hosts still own provider execution and orchestration. The package accepts
caller-supplied vector or rerank adapters and typed score inputs; it does not
call embedding providers directly, schedule automatic re-embedding, or decide
when retrieval should run in a user turn.

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

## OpenMinion submission integration

OpenMinion feeds typed, provenance-rich activity into Sophiagraph through a
direct-SDK submission path. The `SubmissionEnvelope` shape is pinned by
`SUBMISSION_ENVELOPE_SCHEMA_VERSION = "openminion_sophiagraph_submission.v1"`
so future MCP or REST transports can route the same payload without renaming
fields.

The direct-SDK path is the default OpenMinion integration; `sophiagraph-server`
service transports are opt-in for external clients or non-Python hosts.

## API Compatibility

Compatibility and deprecation policy:

- `API_COMPATIBILITY.md`

## Release Docs

Package-local release runbook:

- `RELEASING.md`
- `scripts/release_check.py`

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
