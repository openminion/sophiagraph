"""Shared fake Neo4j module for package-local adapter tests."""

from __future__ import annotations

import importlib
from typing import Any


class FakeNeo4jRow:
    def __init__(self, data: dict[str, object]) -> None:
        self._data = data

    def keys(self):
        return self._data.keys()

    def __getitem__(self, key: str):
        return self._data[key]


class FakeNeo4jResult:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = [FakeNeo4jRow(row) for row in rows]

    def __iter__(self):
        return iter(self._rows)


class FakeNeo4jSession:
    def __init__(self, state: dict[str, object]) -> None:
        self._state = state

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _tb) -> None:
        return None

    def run(self, statement: str, params: dict[str, object] | None = None):
        tag = statement.splitlines()[0].strip()
        params = params or {}
        nodes = self._state["nodes"]
        edges = self._state["edges"]
        meta = self._state["meta"]
        if tag == "// sg_op:ensure_node_constraint":
            return FakeNeo4jResult([])
        if tag == "// sg_op:ensure_meta_constraint":
            return FakeNeo4jResult([])
        if tag == "// sg_op:delete_edges":
            for edge_id in params.get("edge_ids", []):
                edges.pop(edge_id, None)
            return FakeNeo4jResult([])
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
            return FakeNeo4jResult([])
        if tag == "// sg_op:upsert_node":
            nodes[params["node_id"]] = dict(params)
            return FakeNeo4jResult([])
        if tag == "// sg_op:upsert_edge":
            edges[params["edge_id"]] = dict(params)
            return FakeNeo4jResult([])
        if tag == "// sg_op:upsert_meta":
            meta[params["meta_key"]] = params["meta_value"]
            return FakeNeo4jResult([])
        if tag == "// sg_op:query_schema":
            value = meta.get(params["meta_key"])
            if value is None:
                return FakeNeo4jResult([])
            return FakeNeo4jResult([{"meta_value": value}])
        if tag == "// sg_op:query_meta":
            value = meta.get(params["meta_key"])
            if value is None:
                return FakeNeo4jResult([])
            return FakeNeo4jResult([{"meta_value": value}])
        if tag == "// sg_op:projection_inventory_nodes":
            return FakeNeo4jResult(
                [
                    {
                        "object_id": node["node_id"],
                        "properties_json": node["properties_json"],
                    }
                    for node in sorted(nodes.values(), key=lambda item: item["node_id"])
                ]
            )
        if tag == "// sg_op:projection_inventory_edges":
            return FakeNeo4jResult(
                [
                    {
                        "object_id": edge["edge_id"],
                        "properties_json": edge["properties_json"],
                    }
                    for edge in sorted(edges.values(), key=lambda item: item["edge_id"])
                ]
            )
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
            return FakeNeo4jResult(rows)
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
            return FakeNeo4jResult(rows)
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
            return FakeNeo4jResult(rows)
        raise AssertionError(f"unexpected query tag: {tag}")


class FakeNeo4jDriver:
    def __init__(self) -> None:
        self.state = {"nodes": {}, "edges": {}, "meta": {}}

    def session(self, _database: object = None):
        return FakeNeo4jSession(self.state)

    def close(self) -> None:
        return None


class FakeNeo4jGraphDatabase:
    def driver(self, uri: str, _auth: object = None):
        if not uri.startswith("neo4j://"):
            raise AssertionError(f"unexpected URI: {uri}")
        return FakeNeo4jDriver()


class FakeNeo4jModule:
    GraphDatabase = FakeNeo4jGraphDatabase()


def install_fake_neo4j(monkeypatch, import_module_owner: Any) -> FakeNeo4jModule:
    """Patch a module-local importlib shim to return the shared fake Neo4j module."""

    real_import_module = importlib.import_module
    fake_module = FakeNeo4jModule()

    def _fake_import(name: str):
        if name == "neo4j":
            return fake_module
        return real_import_module(name)

    monkeypatch.setattr(import_module_owner, "import_module", _fake_import)
    return fake_module


__all__ = ["FakeNeo4jModule", "install_fake_neo4j"]
