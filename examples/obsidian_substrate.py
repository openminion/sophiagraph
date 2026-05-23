"""Obsidian-style structural link substrate example."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile

from sophiagraph.adapters.markdown import extract_markdown
from sophiagraph.models import LinkResolutionCandidate, MemoryNamespace, MemoryRecord
from sophiagraph.query import LinkQueryOptions, LocalGraphOptions
from sophiagraph.storage import create_sqlite_store


def run_example(root: str | Path) -> dict[str, object]:
    namespace = MemoryNamespace(agent_id="obsidian-demo", graph_id="main")
    store = create_sqlite_store(root)
    target = MemoryRecord(
        id="rec-roadmap",
        scope="agent:obsidian-demo",
        type="artifact_digest",
        key="doc:Roadmap",
        title="Roadmap",
        content={"text": "Target note"},
        created_at="2026-05-23T00:00:00+00:00",
        updated_at="2026-05-23T00:00:00+00:00",
        namespace=namespace,
        meta={"document": {"path": "Roadmap.md", "title": "Roadmap"}},
    )
    source = MemoryRecord(
        id="rec-index",
        scope="agent:obsidian-demo",
        type="artifact_digest",
        key="doc:Index",
        title="Index",
        content={"text": "See [[Roadmap]]."},
        created_at="2026-05-23T00:00:00+00:00",
        updated_at="2026-05-23T00:00:00+00:00",
        namespace=namespace,
        meta={"document": {"path": "Index.md", "title": "Index"}},
    )
    store.put_record(target)
    store.put_record(source)
    imported = extract_markdown(
        "See [[Roadmap]].",
        path="Index.md",
        record_id=source.id,
        namespace=namespace,
        resolver_candidates=[
            LinkResolutionCandidate(
                record_id=target.id,
                path="Roadmap.md",
                title="Roadmap",
                namespace=namespace,
            )
        ],
    )
    for link in imported.links:
        store.put_link(link)
    backlinks = store.list_links(LinkQueryOptions(record_id=target.id, direction="in"))
    graph = store.get_local_graph(LocalGraphOptions(record_id=source.id, depth=1))
    return {
        "parsed_links": len(imported.links),
        "backlinks": len(backlinks),
        "graph_nodes": len(graph.nodes),
        "graph_edges": len(graph.edges),
    }


def main() -> int:
    summary = run_example(Path(tempfile.mkdtemp(prefix="sophiagraph-obsidian-")))
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
