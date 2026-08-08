from __future__ import annotations

from pathlib import Path
import ast

import pytest

from sophiagraph import (
    FakeGraphBackendAdapter,
    GraphBackendQuery,
    KuzuGraphBackendAdapter,
    Neo4jGraphBackendAdapter,
    build_graph_export_batch,
)
from sophiagraph.models import (
    MemoryNamespace,
    MemoryRecord,
    MemoryRelation,
    StructuralLink,
)
from tests.fake_neo4j import install_fake_neo4j


def _ns(agent_id: str = "agent") -> MemoryNamespace:
    return MemoryNamespace(tenant_id="tenant", agent_id=agent_id, graph_id="main")


def _record(record_id: str, title: str, *, agent_id: str = "agent") -> MemoryRecord:
    return MemoryRecord(
        id=record_id,
        scope=f"agent:{agent_id}",
        type="fact",
        key=record_id,
        title=title,
        content={"text": title},
        created_at="2026-05-31T00:00:00+00:00",
        updated_at="2026-05-31T00:00:00+00:00",
        namespace=_ns(agent_id),
        meta={"properties": {"kind": "test", "title": title}},
    )


def _fixture_batch():
    records = [
        _record("rec-a", "A"),
        _record("rec-b", "B"),
        _record("rec-c", "C"),
        _record("rec-other", "Other", agent_id="other"),
    ]
    relations = [
        MemoryRelation(
            relation_id="rel-a-b",
            source_record_id="rec-a",
            target_record_id="rec-b",
            relation_type="supports",
            created_at="2026-05-31T00:00:00+00:00",
        ),
        MemoryRelation(
            relation_id="rel-b-c",
            source_record_id="rec-b",
            target_record_id="rec-c",
            relation_type="supports",
            created_at="2026-05-31T00:00:00+00:00",
        ),
        MemoryRelation(
            relation_id="rel-other-c",
            source_record_id="rec-other",
            target_record_id="rec-c",
            relation_type="supports",
            created_at="2026-05-31T00:00:00+00:00",
        ),
    ]
    links = [
        StructuralLink(
            link_id="link-a-c",
            source_record_id="rec-a",
            target_record_id="rec-c",
            raw_target="C",
            link_kind="wikilink",
            resolution_status="resolved",
            relation_type="mentions",
            namespace=_ns(),
        )
    ]
    return build_graph_export_batch(
        batch_id="batch-1", records=records, relations=relations, links=links
    )


@pytest.fixture(params=["fake", "kuzu", "neo4j"])
def backend(request, tmp_path: Path, monkeypatch):
    batch = _fixture_batch()
    if request.param == "fake":
        adapter = FakeGraphBackendAdapter(
            support_shortest_path=True,
            support_pattern_query=True,
        )
        adapter.upsert_batch(batch)
        return adapter
    if request.param == "neo4j":
        from sophiagraph.graph_backends import neo4j_support

        install_fake_neo4j(monkeypatch, neo4j_support.importlib)
        adapter = Neo4jGraphBackendAdapter("neo4j://fixture")
        adapter.upsert_batch(batch)
        return adapter
    pytest.importorskip("kuzu")
    adapter = KuzuGraphBackendAdapter(tmp_path / "graph.kuzu")
    adapter.upsert_batch(batch)
    return adapter


def test_graph_export_batch_contains_explicit_labels_relations_and_namespaces() -> None:
    batch = _fixture_batch()

    assert batch.schema.node_labels == ["fact"]
    assert batch.schema.relation_types == ["mentions", "supports"]
    assert {edge.relation_type for edge in batch.edges} == {"supports", "mentions"}
    assert all(node.namespace.agent_id for node in batch.nodes)


def test_backends_report_schema_and_capabilities(backend) -> None:
    result = backend.query(GraphBackendQuery(query_id="schema-1", kind="schema"))

    assert result.unsupported_reason is None
    assert result.rows[0].properties["node_labels"] == ["fact"]
    assert result.rows[0].properties["relation_types"] == ["mentions", "supports"]
    assert backend.capabilities().supports("batch_upsert")
    assert backend.capabilities().supports("property_filter")


def test_backends_return_normalized_neighbors(backend) -> None:
    result = backend.query(
        GraphBackendQuery(
            query_id="neighbors-1",
            kind="neighbors",
            start_node_id="rec-a",
            relation_types=["supports"],
            namespace=_ns(),
        )
    )

    assert result.unsupported_reason is None
    assert [(row.node_ids, row.edge_ids) for row in result.rows] == [
        (["rec-b"], ["rel-a-b"])
    ]


def test_backends_support_structural_property_filters(backend) -> None:
    result = backend.query(
        GraphBackendQuery(
            query_id="prop-1",
            kind="property_filter",
            namespace=_ns(),
            property_filters={"kind": "test", "title": "B"},
            node_labels=["fact"],
        )
    )

    assert result.unsupported_reason is None
    assert [row.node_ids for row in result.rows] == [["rec-b"]]


def test_backends_compute_shortest_path(backend) -> None:
    result = backend.query(
        GraphBackendQuery(
            query_id="path-1",
            kind="shortest_path",
            start_node_id="rec-a",
            target_node_id="rec-c",
            relation_types=["supports"],
        )
    )

    assert result.unsupported_reason is None
    assert result.rows[0].node_ids == ["rec-a", "rec-b", "rec-c"]
    assert result.rows[0].edge_ids == ["rel-a-b", "rel-b-c"]


def test_backends_execute_typed_pattern_queries(backend) -> None:
    result = backend.query(
        GraphBackendQuery(
            query_id="pattern-1",
            kind="pattern",
            namespace=_ns(),
            pattern_query={
                "seed_record_ids": ["rec-a"],
                "node_predicates": [{"field": "title", "operator": "eq", "value": "C"}],
                "relation_types": ["supports"],
                "direction": "out",
                "min_hops": 2,
                "max_hops": 2,
                "limit": 1,
            },
        )
    )

    assert backend.capabilities().supports("pattern_query")
    assert result.unsupported_reason is None
    assert result.rows[0].node_ids == ["rec-a", "rec-b", "rec-c"]
    assert result.rows[0].edge_ids == ["rel-a-b", "rel-b-c"]
    assert result.rows[0].properties["title"] == "C"


def test_backends_replay_delete_watermark_and_inventory(backend) -> None:
    backend.upsert_batch(_fixture_batch())
    backend.set_projection_watermark(12)
    assert backend.get_projection_watermark() == 12
    assert {item.object_id for item in backend.inventory()} >= {
        "rec-a",
        "rel-a-b",
    }
    backend.delete(node_ids=(), edge_ids=("rel-a-b",))
    backend.delete(node_ids=(), edge_ids=("rel-a-b",))
    assert "rel-a-b" not in {item.object_id for item in backend.inventory()}


def test_backend_node_upsert_preserves_existing_edges(backend) -> None:
    backend.upsert_batch(
        build_graph_export_batch(
            batch_id="node-update",
            records=[_record("rec-a", "A updated")],
        )
    )

    result = backend.query(
        GraphBackendQuery(
            query_id="neighbors-after-update",
            kind="neighbors",
            start_node_id="rec-a",
            relation_types=["supports"],
            namespace=_ns(),
        )
    )

    assert [(row.node_ids, row.edge_ids) for row in result.rows] == [
        (["rec-b"], ["rel-a-b"])
    ]


def test_fake_backend_negotiates_pattern_query_support() -> None:
    batch = _fixture_batch()
    unsupported = FakeGraphBackendAdapter()
    supported = FakeGraphBackendAdapter(support_pattern_query=True)
    unsupported.upsert_batch(batch)
    supported.upsert_batch(batch)
    query = GraphBackendQuery(
        query_id="q-pattern",
        kind="pattern",
        pattern_query={
            "seed_record_ids": ["rec-a"],
            "relation_types": ["supports"],
            "max_hops": 2,
        },
    )

    assert unsupported.query(query).unsupported_reason == (
        "pattern_query unsupported by backend"
    )
    assert supported.capabilities().supports("pattern_query")
    result = supported.query(query)
    assert result.unsupported_reason is None
    assert [row.node_ids for row in result.rows] == [
        ["rec-a", "rec-b"],
        ["rec-a", "rec-b", "rec-c"],
    ]
    assert [row.edge_ids for row in result.rows] == [
        ["rel-a-b"],
        ["rel-a-b", "rel-b-c"],
    ]


def test_kuzu_adapter_requires_optional_dependency_message(
    monkeypatch, tmp_path: Path
) -> None:
    from sophiagraph.graph_backends import kuzu_support

    def _raise(name: str):
        raise ImportError(name)

    monkeypatch.setattr(kuzu_support.importlib, "import_module", _raise)
    with pytest.raises(ImportError, match=r"sophiagraph\[kuzu\]"):
        KuzuGraphBackendAdapter(tmp_path / "missing.kuzu")


def test_neo4j_adapter_requires_optional_dependency_message(monkeypatch) -> None:
    from sophiagraph.graph_backends import neo4j_support

    def _raise(name: str):
        raise ImportError(name)

    monkeypatch.setattr(neo4j_support.importlib, "import_module", _raise)
    with pytest.raises(ImportError, match=r"sophiagraph\[neo4j\]"):
        Neo4jGraphBackendAdapter("neo4j://missing")


def test_no_text_to_cypher_surface_landed() -> None:
    forbidden = {
        "text_to_cypher",
        "generate_cypher",
        "cypher_from_prompt",
        "nl_to_cypher",
    }
    root = (
        Path(__file__).resolve().parents[1] / "src" / "sophiagraph" / "graph_backends"
    )
    for path in root.glob("*.py"):
        source = path.read_text(encoding="utf-8")
        hits = {symbol for symbol in forbidden if symbol in source}
        assert not hits, f"{path.name} contains forbidden symbols: {sorted(hits)}"


def test_public_import_surface_contains_real_backend() -> None:
    source = Path(__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    assert "sophiagraph" in imported
