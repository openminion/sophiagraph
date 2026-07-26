<p align="center">
  <img src="https://www.openminion.com/brand/openminion-logo.png" alt="SophiaGraph logo" width="128" />
</p>

<h1 align="center">SophiaGraph</h1>

<p align="center">
  <strong>Durable memory, provenance, and knowledge-workspace primitives for local AI systems.</strong>
</p>

<p align="center">
  <a href="https://github.com/openminion/sophiagraph">GitHub</a>
  · <a href="https://pypi.org/project/sophiagraph/">PyPI</a>
  · <a href="https://www.openminion.com">Website</a>
  · <a href="docs/README.md">Docs</a>
  · <a href="https://x.com/OpenMinion">X</a>
</p>

<p align="center">
  <a href="https://pypi.org/project/sophiagraph/"><img alt="PyPI" src="https://img.shields.io/badge/pypi-v0.0.5-3775A9"></a>
  <a href="https://pypi.org/project/sophiagraph/"><img alt="Python" src="https://img.shields.io/pypi/pyversions/sophiagraph?cacheSeconds=300"></a>
  <a href="LICENSE"><img alt="License" src="https://img.shields.io/badge/license-Apache--2.0-blue"></a>
  <img alt="Status" src="https://img.shields.io/badge/status-alpha-6B7280">
</p>

SophiaGraph `v0.0.5` is a standalone alpha package for durable, typed memory.
It stores memory records, relations, provenance, lifecycle state, and portable
workspace data without importing the OpenMinion runtime.

## Read This First

1. Read [At a Glance](#at-a-glance) to confirm the package boundary.
2. Follow [Install](#install) and [Quick Start](#quick-start) for a durable
   SQLite-backed memory round trip.
3. Read [How It Fits](#how-it-fits) before combining SophiaGraph with
   OpenMinion, PragmaGraph, or GraphFakos.
4. Use the [package docs](docs/README.md) for workspace, storage, service,
   retrieval, and production-oriented guidance.
5. Read [Development](#development) before changing the package.

## Trust and Brand Safety

- Official GitHub: <https://github.com/openminion/sophiagraph>
- Official website: <https://www.openminion.com>
- Official X account: <https://x.com/OpenMinion>

SophiaGraph has no official token, coin, NFT, airdrop, staking program,
treasury product, or investment offering. Any claim otherwise is unauthorized
and should be treated as a scam.

## At a Glance

| | |
| --- | --- |
| Package | `sophiagraph` |
| Current line | `v0.0.5` alpha |
| Python | 3.11+ |
| Best fit | Durable agent memory, provenance, lifecycle, and local knowledge workspaces |
| Default durable backend | SQLite |
| Additional backends | In-memory, optional Kuzu and Neo4j graph adapters, optional Qdrant vector adapter |
| Not the claim | Agent orchestration, provider routing, or automatic semantic inference |

## Common Commands

```bash
python3.11 -m pip install sophiagraph
sophiagraph-smoke
sophiagraph-ui --screen explore --serve --open
```

Create and inspect a persistent workspace:

```bash
python3.11 -m sophiagraph workspace-init .sophia-workspace \
  --scope agent:local --agent-id local --graph-id main --json
python3.11 -m sophiagraph workspace-status .sophia-workspace --json
```

## Install

Install the base package:

```bash
python3.11 -m pip install sophiagraph
```

Install an optional backend only when you need it:

```bash
python3.11 -m pip install "sophiagraph[kuzu]"
python3.11 -m pip install "sophiagraph[neo4j]"
```

For a source checkout:

```bash
python3.11 -m pip install -e ".[dev]"
```

## Quick Start

### External Consumer Quickstart

Store and retrieve one typed memory record:

```python
from pathlib import Path
from uuid import uuid4

from sophiagraph.models import MemoryNamespace, MemoryRecord
from sophiagraph.query import SearchQueryOptions
from sophiagraph.storage import create_sqlite_store

store = create_sqlite_store(Path(".sophiagraph"))
namespace = MemoryNamespace(agent_id="demo", graph_id="main")
record = MemoryRecord(
    id=str(uuid4()),
    scope="agent:demo",
    type="fact",
    key="project:apollo",
    title="Apollo launch window",
    content={"text": "Apollo launches in Q2."},
    created_at="2026-01-01T00:00:00+00:00",
    updated_at="2026-01-01T00:00:00+00:00",
    source="validated",
    confidence=0.95,
    namespace=namespace,
)

store.put_record(record)
matches = store.search_records(
    SearchQueryOptions(
        query="Apollo",
        scopes=["agent:demo"],
        namespaces=[namespace],
    )
)
print(matches)
```

Run the complete example:

```bash
python3.11 examples/basic_usage.py
```

Use `create_memory_store()` instead when a test or short-lived consumer needs
an ephemeral in-memory store rather than a durable SQLite path.

## What SophiaGraph Provides

- typed memory records, namespaces, relations, provenance, and citations
- SQLite and in-memory stores with explicit capability reporting
- portable snapshots and import/export contracts
- lifecycle, trust, governance, deletion, audit, and freshness helpers
- structural queries, graph paths, connected components, and knowledge views
- workspace initialization, sync planning, history, templates, and publishing
- optional graph and vector backend adapters
- bounded local UI and server surfaces for package-owned workflows

## What SophiaGraph Does Not Provide

- application or agent orchestration
- model-provider selection or routing
- session and turn execution
- automatic fact, relation, tag, or summary inference from prose
- automatic embedding-provider calls or model selection
- hosted collaboration, hosted administration, or managed sync
- ownership of a host application’s authorization or policy decisions

The core package operates on explicit typed inputs. Hosts remain responsible for
LLM calls, semantic interpretation, scheduling, credentials, and user-facing
policy.

## How It Fits

| Package | Responsibility |
| --- | --- |
| OpenMinion | Agent runtime, turns, tools, sessions, and orchestration |
| SophiaGraph | Durable memory, provenance, lifecycle, and workspace knowledge |
| PragmaGraph | Deterministic observed facts from code, docs, artifacts, and Git history |
| GraphFakos | Provider-neutral graph viewing and interaction contracts |

SophiaGraph can run by itself. OpenMinion may use it as a memory backend, and
GraphFakos may visualize a provider projection, but neither integration changes
who owns memory truth.

## Storage and Workspace Paths

Use the in-memory store for tests and ephemeral consumers. Use SQLite for the
default durable local path. Optional Kuzu, Neo4j, and Qdrant adapters expose
capability-specific behavior and should be selected explicitly.

The workspace surface adds persistent scope, namespace, import, sync, review,
and publishing workflows on top of those package contracts:

```bash
python3.11 -m sophiagraph workspace-import-plan \
  .sophia-workspace ./notes --json
python3.11 -m sophiagraph workspace-sync-apply \
  .sophia-workspace ./notes --json
```

Read [`docs/workspace-mode.md`](docs/workspace-mode.md),
[`docs/storage-retrieval-backends.md`](docs/storage-retrieval-backends.md), and
[`docs/retrieval-boundary.md`](docs/retrieval-boundary.md) before building a
larger integration.

## Development

```bash
make dev-install
make hooks-install
make check
```

Use `make release-check` before publishing or changing the documented public
surface.

## Docs and Release

- [`docs/README.md`](docs/README.md): package documentation map
- [`docs/getting-started.md`](docs/getting-started.md): contributor bootstrap
- [`docs/api-stability.md`](docs/api-stability.md): public stability guidance
- [`docs/production-foundations.md`](docs/production-foundations.md):
  production-oriented package boundaries
- [`docs/backend-compatibility-matrix.md`](docs/backend-compatibility-matrix.md):
  backend support and proof
- [`docs/source-tree-owner-map.md`](docs/source-tree-owner-map.md): code owners
  and package layout
- [`docs/standalone-claim-alignment.md`](docs/standalone-claim-alignment.md):
  public claims mapped to shipped package surfaces and proof
- [`API_COMPATIBILITY.md`](API_COMPATIBILITY.md): supported import roots
- [`RELEASING.md`](RELEASING.md): release and publish flow

## License and Brand-use Boundary

- Source code license: Apache-2.0
- Brand/trademark grant: none

The license grants rights to use, modify, and redistribute the code. It does
not grant rights to present a fork, clone, token, website, or social account as
the official SophiaGraph or OpenMinion project or imply affiliation or
endorsement.
