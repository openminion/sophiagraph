from __future__ import annotations

import pytest

from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.models import (
    ExplicitLinkResolver,
    KnowledgeDocumentBlock,
    LinkResolutionCandidate,
    MemoryNamespace,
    MemoryRecord,
    StructuralLink,
)
from sophiagraph.query import (
    GraphSnapshotOptions,
    LinkQueryOptions,
    LocalGraphOptions,
    StructuralSearchQuery,
    all_simple_paths,
    common_neighbors,
    connected_components,
    degree_centrality,
    degree_metrics,
    orphan_clusters,
    path_evidence,
    retrieval_path_evidence,
    shortest_path,
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


def test_explicit_link_resolver_rejects_malformed_alias_lists() -> None:
    with pytest.raises(InvalidArgumentError, match="aliases must be a list"):
        LinkResolutionCandidate(
            record_id="rec-1",
            path="Roadmap.md",
            title="Roadmap",
            aliases="Plan",  # type: ignore[arg-type]
            namespace=_namespace(),
        )

    resolver = ExplicitLinkResolver(
        [
            LinkResolutionCandidate(
                record_id="rec-1",
                path="Roadmap.md",
                title="Roadmap",
                aliases=["Plan"],
                namespace=_namespace(),
            )
        ]
    )

    assert resolver.resolve("plan", namespace=_namespace()).target_record_id == "rec-1"


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


def test_graph_algorithms_return_paths_components_and_centrality(store) -> None:
    namespace = _namespace()
    for record_id, title in [
        ("rec-a", "A"),
        ("rec-b", "B"),
        ("rec-c", "C"),
        ("rec-d", "D"),
    ]:
        store.put_record(_record(record_id, title, namespace))
    store.put_link(_link("link-a-b", "rec-a", "rec-b", namespace))
    store.put_link(_link("link-b-c", "rec-b", "rec-c", namespace))

    snapshot = store.get_graph_snapshot(
        GraphSnapshotOptions(scopes=["agent:agent"], include_orphans=True)
    )
    path = shortest_path(snapshot, "rec-a", "rec-c")
    components = connected_components(snapshot)
    centrality = degree_centrality(snapshot, normalized=False)
    evidence = path_evidence(snapshot, "rec-a", "rec-c")

    assert path is not None
    assert path.record_ids == ["rec-a", "rec-b", "rec-c"]
    assert path.edge_ids == ["link-a-b", "link-b-c"]
    assert path.hop_count == 2
    assert [component.record_ids for component in components] == [
        ["rec-a", "rec-b", "rec-c"],
        ["rec-d"],
    ]
    assert centrality["rec-b"] == 2.0
    assert [edge.edge_id for edge in evidence] == ["link-a-b", "link-b-c"]


def test_graph_algorithms_cover_bounded_paths_neighbors_orphans_and_evidence(
    store,
) -> None:
    namespace = _namespace()
    other_namespace = _namespace("other")
    for record_id, title in [
        ("rec-a", "A"),
        ("rec-b", "B"),
        ("rec-c", "C"),
        ("rec-d", "D"),
        ("rec-e", "E"),
    ]:
        store.put_record(_record(record_id, title, namespace))
    store.put_record(_record("rec-other", "Other", other_namespace))
    store.put_link(_link("link-a-b", "rec-a", "rec-b", namespace))
    store.put_link(_link("link-b-c", "rec-b", "rec-c", namespace))
    store.put_link(_link("link-a-d", "rec-a", "rec-d", namespace))
    store.put_link(_link("link-d-c", "rec-d", "rec-c", namespace))
    store.put_link(_link("link-other-c", "rec-other", "rec-c", other_namespace))

    snapshot = store.get_graph_snapshot(
        GraphSnapshotOptions(
            scopes=["agent:agent", "agent:other"],
            namespaces=[MemoryNamespace(agent_id="agent")],
            include_orphans=True,
        )
    )
    paths = all_simple_paths(snapshot, "rec-a", "rec-c", max_depth=3, max_paths=5)
    neighbors = common_neighbors(snapshot, "rec-a", "rec-c")
    metrics = {metric.record_id: metric for metric in degree_metrics(snapshot)}
    evidence = retrieval_path_evidence(
        snapshot, "rec-a", "rec-c", max_depth=3, max_paths=2
    )

    assert [path.record_ids for path in paths] == [
        ["rec-a", "rec-b", "rec-c"],
        ["rec-a", "rec-d", "rec-c"],
    ]
    assert neighbors.neighbor_record_ids == ["rec-b", "rec-d"]
    assert neighbors.edge_ids == ["link-a-b", "link-a-d", "link-b-c", "link-d-c"]
    assert metrics["rec-a"].degree_out == 2
    assert metrics["rec-c"].degree_in == 2
    assert [cluster.record_ids for cluster in orphan_clusters(snapshot)] == [["rec-e"]]
    assert evidence.record_ids == ["rec-a", "rec-b", "rec-c", "rec-d"]
    assert evidence.edge_ids == ["link-a-b", "link-b-c", "link-a-d", "link-d-c"]
    assert "rec-other" not in {node.record_id for node in snapshot.nodes}


def test_graph_algorithms_validate_limits_and_direction(store) -> None:
    namespace = _namespace()
    for record_id, title in [("rec-a", "A"), ("rec-b", "B")]:
        store.put_record(_record(record_id, title, namespace))
    store.put_link(_link("link-a-b", "rec-a", "rec-b", namespace))
    snapshot = store.get_graph_snapshot(GraphSnapshotOptions(scopes=["agent:agent"]))

    assert shortest_path(snapshot, "rec-b", "rec-a", direction="out") is None
    assert shortest_path(snapshot, "rec-b", "rec-a", direction="both") is not None
    with pytest.raises(InvalidArgumentError, match="invalid direction"):
        shortest_path(snapshot, "rec-a", "rec-b", direction="sideways")
    with pytest.raises(InvalidArgumentError, match="max_depth must be positive"):
        all_simple_paths(snapshot, "rec-a", "rec-b", max_depth=0)
    with pytest.raises(InvalidArgumentError, match="limit must be positive"):
        common_neighbors(snapshot, "rec-a", "rec-b", limit=0)


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


def test_document_blocks_round_trip_search_and_emit_changes(store) -> None:
    namespace = _namespace()
    record = _record("rec-roadmap", "Roadmap", namespace)
    store.put_record(record)
    blocks = [
        KnowledgeDocumentBlock(
            block_id="block-roadmap",
            document_id="doc-roadmap",
            record_id="rec-roadmap",
            block_type="heading",
            anchor="roadmap",
            line_start=1,
            line_end=1,
            excerpt="# Roadmap",
        ),
        KnowledgeDocumentBlock(
            block_id="todo-1",
            document_id="doc-roadmap",
            record_id="rec-roadmap",
            block_type="block",
            anchor="todo-1",
            line_start=3,
            line_end=3,
            excerpt="- [ ] ship indexed search ^todo-1",
        ),
    ]

    store.put_document_blocks("rec-roadmap", blocks)
    matches = store.structural_search_records(
        StructuralSearchQuery(
            block="todo-1",
            section="roadmap",
            task="ship indexed",
            namespaces=[MemoryNamespace(agent_id="agent")],
        ),
        scopes=["agent:agent"],
    )

    assert [
        block.block_id for block in store.list_document_blocks(record_id="rec-roadmap")
    ] == [
        "block-roadmap",
        "todo-1",
    ]
    assert [record.id for record in matches] == ["rec-roadmap"]
    assert any(event.object_type == "block" for event in store.list_changes())


def test_sqlite_document_block_search_uses_block_fts_index(tmp_path) -> None:
    store = SophiaGraphSqliteStore(tmp_path / "block-fts.sqlite3")
    namespace = _namespace()
    store.put_record(_record("rec-roadmap", "Roadmap", namespace))
    store.put_document_blocks(
        "rec-roadmap",
        [
            KnowledgeDocumentBlock(
                block_id="block-plan",
                document_id="doc-roadmap",
                record_id="rec-roadmap",
                block_type="block",
                anchor="plan",
                excerpt="- [ ] wire block fts",
            )
        ],
    )

    matches = store.structural_search_records(
        StructuralSearchQuery(
            task="wire block", namespaces=[MemoryNamespace(agent_id="agent")]
        ),
        scopes=["agent:agent"],
    )

    with store._connect() as conn:  # noqa: SLF001 - package-level regression proof
        fts_rows = conn.execute(
            "SELECT record_id FROM sophiagraph_block_fts WHERE sophiagraph_block_fts MATCH ?",
            ('"wire block"',),
        ).fetchall()

    assert [record.id for record in matches] == ["rec-roadmap"]
    assert [row["record_id"] for row in fts_rows] == ["rec-roadmap"]


def test_sqlite_structural_search_uses_fts_index_when_available(tmp_path) -> None:
    store = SophiaGraphSqliteStore(tmp_path / "fts.sqlite3")
    namespace = _namespace()
    store.put_record(_record("rec-roadmap", "Roadmap", namespace))
    store.put_record(_record("rec-notes", "Notes", namespace))

    matches = store.structural_search_records(
        StructuralSearchQuery(text_terms=["Roadmap"]),
        scopes=["agent:agent"],
    )

    with store._connect() as conn:  # noqa: SLF001 - package-level regression proof
        fts_rows = conn.execute(
            "SELECT record_id FROM sophiagraph_record_fts WHERE sophiagraph_record_fts MATCH ?",
            ('"Roadmap"',),
        ).fetchall()

    assert [record.id for record in matches] == ["rec-roadmap"]
    assert [row["record_id"] for row in fts_rows] == ["rec-roadmap"]
