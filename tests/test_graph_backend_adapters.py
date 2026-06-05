from __future__ import annotations

from pathlib import Path
import ast
import importlib

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


class _FakeNeo4jRow:
    def __init__(self, data: dict[str, object]) -> None:
        self._data = data

    def keys(self):
        return self._data.keys()

    def __getitem__(self, key: str):
        return self._data[key]


class _FakeNeo4jResult:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = [_FakeNeo4jRow(row) for row in rows]

    def __iter__(self):
        return iter(self._rows)


class _FakeNeo4jSession:
    def __init__(self, state: dict[str, object]) -> None:
        self._state = state

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def run(self, statement: str, params: dict[str, object]):
        tag = statement.splitlines()[0].strip()
        nodes = self._state["nodes"]
        edges = self._state["edges"]
        meta = self._state["meta"]
        if tag == "// sg_op:ensure_node_constraint":
            return _FakeNeo4jResult([])
        if tag == "// sg_op:ensure_meta_constraint":
            return _FakeNeo4jResult([])
        if tag == "// sg_op:delete_edges":
            for edge_id in params.get("edge_ids", []):
                edges.pop(edge_id, None)
            return _FakeNeo4jResult([])
        if tag == "// sg_op:delete_nodes":
            for node_id in params.get("node_ids", []):
                nodes.pop(node_id, None)
            doomed = [
                edge_id
                for edge_id, edge in list(edges.items())
                if edge["source_node_id"] in params.get("node_ids", [])
                or edge["target_node_id"] in params.get("node_ids", [])
            ]
            for edge_id in doomed:
                edges.pop(edge_id, None)
            return _FakeNeo4jResult([])
        if tag == "// sg_op:upsert_node":
            nodes[params["node_id"]] = dict(params)
            return _FakeNeo4jResult([])
        if tag == "// sg_op:upsert_edge":
            edges[params["edge_id"]] = dict(params)
            return _FakeNeo4jResult([])
        if tag == "// sg_op:upsert_meta":
            meta[params["meta_key"]] = params["meta_value"]
            return _FakeNeo4jResult([])
        if tag == "// sg_op:query_schema":
            value = meta.get(params["meta_key"])
            if value is None:
                return _FakeNeo4jResult([])
            return _FakeNeo4jResult([{"meta_value": value}])
        if tag == "// sg_op:query_neighbors":
            rows = []
            start_node_id = params["start_node_id"]
            for edge in sorted(edges.values(), key=lambda item: item["edge_id"]):
                if edge["source_node_id"] != start_node_id:
                    continue
                target = nodes[edge["target_node_id"]]
                rows.append(
                    {
                        "target_node_id": target["node_id"],
                        "primary_label": target["primary_label"],
                        "labels_json": target["labels_json"],
                        "target_properties_json": target["properties_json"],
                        "target_tenant_id": target.get("tenant_id"),
                        "target_org_id": target.get("org_id"),
                        "target_user_id": target.get("user_id"),
                        "target_agent_id": target.get("agent_id"),
                        "target_session_id": target.get("session_id"),
                        "target_conversation_id": target.get("conversation_id"),
                        "target_project_id": target.get("project_id"),
                        "target_graph_id": target.get("graph_id"),
                        "edge_id": edge["edge_id"],
                        "relation_type": edge["relation_type"],
                        "edge_properties_json": edge["properties_json"],
                        "edge_tenant_id": edge.get("tenant_id"),
                        "edge_org_id": edge.get("org_id"),
                        "edge_user_id": edge.get("user_id"),
                        "edge_agent_id": edge.get("agent_id"),
                        "edge_session_id": edge.get("session_id"),
                        "edge_conversation_id": edge.get("conversation_id"),
                        "edge_project_id": edge.get("project_id"),
                        "edge_graph_id": edge.get("graph_id"),
                    }
                )
            return _FakeNeo4jResult(rows)
        if tag == "// sg_op:query_property_filter":
            rows = []
            for node in sorted(nodes.values(), key=lambda item: item["node_id"]):
                rows.append(
                    {
                        "node_id": node["node_id"],
                        "primary_label": node["primary_label"],
                        "labels_json": node["labels_json"],
                        "properties_json": node["properties_json"],
                        "tenant_id": node.get("tenant_id"),
                        "org_id": node.get("org_id"),
                        "user_id": node.get("user_id"),
                        "agent_id": node.get("agent_id"),
                        "session_id": node.get("session_id"),
                        "conversation_id": node.get("conversation_id"),
                        "project_id": node.get("project_id"),
                        "graph_id": node.get("graph_id"),
                    }
                )
            return _FakeNeo4jResult(rows)
        if tag == "// sg_op:query_all_edges":
            rows = []
            for edge in sorted(edges.values(), key=lambda item: item["edge_id"]):
                rows.append(
                    {
                        "source_node_id": edge["source_node_id"],
                        "target_node_id": edge["target_node_id"],
                        "edge_id": edge["edge_id"],
                        "relation_type": edge["relation_type"],
                        "edge_properties_json": edge["properties_json"],
                        "tenant_id": edge.get("tenant_id"),
                        "org_id": edge.get("org_id"),
                        "user_id": edge.get("user_id"),
                        "agent_id": edge.get("agent_id"),
                        "session_id": edge.get("session_id"),
                        "conversation_id": edge.get("conversation_id"),
                        "project_id": edge.get("project_id"),
                        "graph_id": edge.get("graph_id"),
                    }
                )
            return _FakeNeo4jResult(rows)
        raise AssertionError(f"unexpected query tag: {tag}")


class _FakeNeo4jDriver:
    def __init__(self) -> None:
        self.state = {"nodes": {}, "edges": {}, "meta": {}}

    def session(self, database=None):  # noqa: ARG002
        return _FakeNeo4jSession(self.state)

    def close(self) -> None:
        return None


class _FakeNeo4jGraphDatabase:
    def driver(self, uri: str, auth=None):  # noqa: ARG002
        if not uri.startswith("neo4j://"):
            raise AssertionError(f"unexpected URI: {uri}")
        return _FakeNeo4jDriver()


class _FakeNeo4jModule:
    GraphDatabase = _FakeNeo4jGraphDatabase()


@pytest.fixture(params=["fake", "kuzu", "neo4j"])
def backend(request, tmp_path: Path, monkeypatch):
    batch = _fixture_batch()
    if request.param == "fake":
        adapter = FakeGraphBackendAdapter(support_shortest_path=True)
        adapter.upsert_batch(batch)
        return adapter
    if request.param == "neo4j":
        from sophiagraph.graph_backends import neo4j as neo4j_module

        real_import_module = importlib.import_module

        def _fake_import(name: str):
            if name == "neo4j":
                return _FakeNeo4jModule()
            return real_import_module(name)

        monkeypatch.setattr(neo4j_module.importlib, "import_module", _fake_import)
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
    assert result.rows[0].node_ids == ["rec-a", "rec-b", "rec-c"]
    assert result.rows[0].edge_ids == ["rel-a-b", "rel-b-c"]


def test_kuzu_adapter_requires_optional_dependency_message(
    monkeypatch, tmp_path: Path
) -> None:
    from sophiagraph.graph_backends import kuzu as kuzu_module

    def _raise(name: str):
        raise ImportError(name)

    monkeypatch.setattr(kuzu_module.importlib, "import_module", _raise)
    with pytest.raises(ImportError, match=r"sophiagraph\[kuzu\]"):
        KuzuGraphBackendAdapter(tmp_path / "missing.kuzu")


def test_neo4j_adapter_requires_optional_dependency_message(monkeypatch) -> None:
    from sophiagraph.graph_backends import neo4j as neo4j_module

    def _raise(name: str):
        raise ImportError(name)

    monkeypatch.setattr(neo4j_module.importlib, "import_module", _raise)
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
