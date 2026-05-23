from __future__ import annotations

import pytest

from sophiagraph.models import MemoryNamespace, MemoryRecord, StructuralLink
from sophiagraph.query import (
    GraphSnapshotOptions,
    LinkQueryOptions,
    LocalGraphOptions,
    StructuralSearchQuery,
)
from sophiagraph.storage import SophiaGraphMemoryStore, SophiaGraphSqliteStore


def _namespace(agent_id: str = "agent") -> MemoryNamespace:
    return MemoryNamespace(tenant_id="tenant", agent_id=agent_id, graph_id="main")


def _record(record_id: str, title: str, namespace: MemoryNamespace) -> MemoryRecord:
    return MemoryRecord(
        id=record_id,
        scope=f"agent:{namespace.agent_id}",
        type="artifact_digest",
        key=f"doc:{record_id}",
        title=title,
        tags=["project/core"],
        content={"text": f"{title} body"},
        created_at="2026-05-23T00:00:00+00:00",
        updated_at="2026-05-23T00:00:00+00:00",
        namespace=namespace,
        meta={
            "document": {"path": f"{title}.md", "title": title},
            "properties": {"status": "active", "tags": ["project/core"]},
        },
    )


def _link(
    link_id: str,
    source: str,
    target: str | None,
    namespace: MemoryNamespace,
) -> StructuralLink:
    return StructuralLink(
        link_id=link_id,
        source_record_id=source,
        target_record_id=target,
        raw_target=target or "Missing",
        link_kind="wikilink",
        resolution_status="resolved" if target else "unresolved",
        relation_type="related_to",
        context_before="before " * 20,
        context_after="after " * 20,
        namespace=namespace,
        created_at="2026-05-23T00:00:00+00:00",
    )


@pytest.fixture(params=["memory", "sqlite"])
def store(request, tmp_path):
    if request.param == "memory":
        return SophiaGraphMemoryStore()
    return SophiaGraphSqliteStore(tmp_path / "sophiagraph.sqlite3")


def test_backlinks_outgoing_and_namespace_isolation(store) -> None:
    namespace = _namespace()
    other_namespace = _namespace("other")
    store.put_record(_record("rec-a", "A", namespace))
    store.put_record(_record("rec-b", "B", namespace))
    store.put_record(_record("rec-other", "B", other_namespace))
    store.put_link(_link("link-a-b", "rec-a", "rec-b", namespace))
    store.put_link(_link("link-other", "rec-other", "rec-b", other_namespace))

    outgoing = store.list_links(
        LinkQueryOptions(
            record_id="rec-a",
            direction="out",
            namespaces=[MemoryNamespace(agent_id="agent")],
            context_chars=8,
        )
    )
    backlinks = store.list_links(
        LinkQueryOptions(
            record_id="rec-b",
            direction="in",
            namespaces=[MemoryNamespace(agent_id="agent")],
        )
    )

    assert [link.link_id for link in outgoing] == ["link-a-b"]
    assert outgoing[0].context_before == " before "
    assert [link.link_id for link in backlinks] == ["link-a-b"]


def test_local_graph_handles_depth_cycles_and_snapshot(store) -> None:
    namespace = _namespace()
    for record_id, title in [("rec-a", "A"), ("rec-b", "B"), ("rec-c", "C")]:
        store.put_record(_record(record_id, title, namespace))
    store.put_link(_link("link-a-b", "rec-a", "rec-b", namespace))
    store.put_link(_link("link-b-c", "rec-b", "rec-c", namespace))
    store.put_link(_link("link-c-a", "rec-c", "rec-a", namespace))

    graph = store.get_local_graph(
        LocalGraphOptions(
            record_id="rec-a",
            depth=2,
            direction="both",
            namespaces=[MemoryNamespace(agent_id="agent")],
            max_nodes=10,
            max_edges=10,
        )
    )
    snapshot = store.get_graph_snapshot(
        GraphSnapshotOptions(
            scopes=["agent:agent"],
            namespaces=[MemoryNamespace(agent_id="agent")],
            include_orphans=False,
        )
    )

    assert {node.record_id for node in graph.nodes} == {"rec-a", "rec-b", "rec-c"}
    assert len(graph.edges) == 3
    assert len(snapshot.nodes) == 3
    assert len(snapshot.edges) == 3


def test_structural_search_matches_tags_properties_path_and_links(store) -> None:
    namespace = _namespace()
    store.put_record(_record("rec-roadmap", "Roadmap", namespace))
    store.put_record(_record("rec-target", "Target", namespace))
    store.put_link(_link("link-roadmap-target", "rec-roadmap", "rec-target", namespace))

    matches = store.structural_search_records(
        StructuralSearchQuery(
            tags=["project/core"],
            properties={"status": "active"},
            path="Roadmap.md",
            link_to="rec-target",
            namespaces=[MemoryNamespace(agent_id="agent")],
        ),
        scopes=["agent:agent"],
    )

    assert [record.id for record in matches] == ["rec-roadmap"]
