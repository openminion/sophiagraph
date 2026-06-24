"""Optional Neo4j-backed graph backend adapter."""

from __future__ import annotations

from dataclasses import asdict
import json
from typing import Any

from .base import (
    GraphBackendCapabilities,
    GraphExportEdge,
    GraphBackendQuery,
    GraphBackendResult,
    GraphBackendResultRow,
    GraphExportBatch,
    decode_json_list,
    decode_json_object,
    namespace_columns,
    namespace_matches_filter,
    property_filters_match,
    schema_result_row,
    shortest_path_from_edges,
)
from .neo4j_support import as_optional_str, import_neo4j, row_namespace
from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.models import MemoryNamespace
from sophiagraph.schema import GraphSchema

_NODE_LABEL = "SGNode"
_EDGE_LABEL = "SGEdge"
_META_LABEL = "SGMeta"
_SCHEMA_META_KEY = "schema_json"
_BATCH_META_KEY = "batch_id"


class Neo4jGraphBackendAdapter:
    def __init__(
        self,
        uri: str,
        *,
        auth: tuple[str, str] | None = None,
        database: str | None = None,
    ) -> None:
        if not uri:
            raise InvalidArgumentError("uri is required")
        neo4j = import_neo4j()
        graph_database = getattr(neo4j, "GraphDatabase", None)
        if graph_database is None or not hasattr(graph_database, "driver"):
            raise ImportError(
                "neo4j.GraphDatabase.driver is required for Neo4jGraphBackendAdapter"
            )
        self._driver = (
            graph_database.driver(uri, auth=auth)
            if auth is not None
            else graph_database.driver(uri)
        )
        self._database = database
        self._capabilities = GraphBackendCapabilities(
            backend_name="neo4j",
            supported_features=[
                "schema_export",
                "batch_upsert",
                "neighbors",
                "shortest_path",
                "property_filter",
            ],
            notes={
                "install_extra": "neo4j",
                "pattern_query": "unsupported in the second-backend v1",
            },
        )
        self._ensure_schema()

    def capabilities(self) -> GraphBackendCapabilities:
        return self._capabilities

    def upsert_batch(self, batch: GraphExportBatch) -> None:
        self._ensure_schema()
        edge_ids = [edge.edge_id for edge in batch.edges]
        node_ids = [node.node_id for node in batch.nodes]
        if edge_ids:
            self._execute(
                (
                    "// sg_op:delete_edges\n"
                    f"MATCH ()-[e:{_EDGE_LABEL}]->() "
                    "WHERE e.edge_id IN $edge_ids DELETE e"
                ),
                {"edge_ids": edge_ids},
            )
        if node_ids:
            self._execute(
                (
                    "// sg_op:delete_nodes\n"
                    f"MATCH (n:{_NODE_LABEL}) "
                    "WHERE n.node_id IN $node_ids DETACH DELETE n"
                ),
                {"node_ids": node_ids},
            )
        for node in batch.nodes:
            self._execute(
                (
                    "// sg_op:upsert_node\n"
                    f"MERGE (n:{_NODE_LABEL} {{node_id: $node_id}}) "
                    "SET n.primary_label = $primary_label, "
                    "n.labels_json = $labels_json, "
                    "n.properties_json = $properties_json, "
                    "n.tenant_id = $tenant_id, "
                    "n.org_id = $org_id, "
                    "n.user_id = $user_id, "
                    "n.agent_id = $agent_id, "
                    "n.session_id = $session_id, "
                    "n.conversation_id = $conversation_id, "
                    "n.project_id = $project_id, "
                    "n.graph_id = $graph_id"
                ),
                {
                    "node_id": node.node_id,
                    "primary_label": node.labels[0],
                    "labels_json": json.dumps(node.labels, sort_keys=True),
                    "properties_json": json.dumps(node.properties, sort_keys=True),
                    **namespace_columns(node.namespace),
                },
            )
        for edge in batch.edges:
            self._execute(
                (
                    "// sg_op:upsert_edge\n"
                    f"MATCH (a:{_NODE_LABEL} {{node_id: $source_node_id}}), "
                    f"(b:{_NODE_LABEL} {{node_id: $target_node_id}}) "
                    f"CREATE (a)-[e:{_EDGE_LABEL} {{"
                    "edge_id: $edge_id, "
                    "relation_type: $relation_type, "
                    "properties_json: $properties_json, "
                    "tenant_id: $tenant_id, "
                    "org_id: $org_id, "
                    "user_id: $user_id, "
                    "agent_id: $agent_id, "
                    "session_id: $session_id, "
                    "conversation_id: $conversation_id, "
                    "project_id: $project_id, "
                    "graph_id: $graph_id"
                    "}]->(b)"
                ),
                {
                    "source_node_id": edge.source_node_id,
                    "target_node_id": edge.target_node_id,
                    "edge_id": edge.edge_id,
                    "relation_type": edge.relation_type,
                    "properties_json": json.dumps(edge.properties, sort_keys=True),
                    **namespace_columns(edge.namespace),
                },
            )
        self._upsert_meta(
            _SCHEMA_META_KEY, json.dumps(asdict(batch.schema), sort_keys=True)
        )
        self._upsert_meta(_BATCH_META_KEY, batch.batch_id)

    def query(self, query: GraphBackendQuery) -> GraphBackendResult:
        if query.kind == "pattern":
            return GraphBackendResult(
                query_id=query.query_id,
                backend_name=self._capabilities.backend_name,
                unsupported_reason="pattern_query unsupported by backend",
            )
        if query.kind == "schema":
            schema = self._load_schema()
            return GraphBackendResult(
                query_id=query.query_id,
                backend_name=self._capabilities.backend_name,
                rows=[] if schema is None else [schema_result_row(schema)],
            )
        if query.kind == "property_filter":
            return self._query_property_filter(query)
        if query.kind == "shortest_path":
            return self._query_shortest_path(query)
        return self._query_neighbors(query)

    def close(self) -> None:
        close = getattr(self._driver, "close", None)
        if callable(close):
            close()

    def _ensure_schema(self) -> None:
        self._execute(
            (
                "// sg_op:ensure_node_constraint\n"
                f"CREATE CONSTRAINT sg_node_id IF NOT EXISTS "
                f"FOR (n:{_NODE_LABEL}) REQUIRE n.node_id IS UNIQUE"
            )
        )
        self._execute(
            (
                "// sg_op:ensure_meta_constraint\n"
                f"CREATE CONSTRAINT sg_meta_key IF NOT EXISTS "
                f"FOR (m:{_META_LABEL}) REQUIRE m.meta_key IS UNIQUE"
            )
        )

    def _upsert_meta(self, key: str, value: str) -> None:
        self._execute(
            (
                "// sg_op:upsert_meta\n"
                f"MERGE (m:{_META_LABEL} {{meta_key: $meta_key}}) "
                "SET m.meta_value = $meta_value"
            ),
            {"meta_key": key, "meta_value": value},
        )

    def _load_schema(self) -> GraphSchema | None:
        rows = self._rows_as_dict(
            self._execute(
                (
                    "// sg_op:query_schema\n"
                    f"MATCH (m:{_META_LABEL} {{meta_key: $meta_key}}) "
                    "RETURN m.meta_value AS meta_value"
                ),
                {"meta_key": _SCHEMA_META_KEY},
            )
        )
        if not rows:
            return None
        payload = decode_json_object(as_optional_str(rows[0].get("meta_value")))
        return GraphSchema(**payload)

    def _query_neighbors(self, query: GraphBackendQuery) -> GraphBackendResult:
        rows = self._rows_as_dict(
            self._execute(
                (
                    "// sg_op:query_neighbors\n"
                    f"MATCH (s:{_NODE_LABEL} {{node_id: $start_node_id}})"
                    f"-[e:{_EDGE_LABEL}]->(t:{_NODE_LABEL}) "
                    "RETURN "
                    "t.node_id AS target_node_id, "
                    "t.primary_label AS primary_label, "
                    "t.labels_json AS labels_json, "
                    "t.properties_json AS target_properties_json, "
                    "t.tenant_id AS target_tenant_id, "
                    "t.org_id AS target_org_id, "
                    "t.user_id AS target_user_id, "
                    "t.agent_id AS target_agent_id, "
                    "t.session_id AS target_session_id, "
                    "t.conversation_id AS target_conversation_id, "
                    "t.project_id AS target_project_id, "
                    "t.graph_id AS target_graph_id, "
                    "e.edge_id AS edge_id, "
                    "e.relation_type AS relation_type, "
                    "e.properties_json AS edge_properties_json, "
                    "e.tenant_id AS edge_tenant_id, "
                    "e.org_id AS edge_org_id, "
                    "e.user_id AS edge_user_id, "
                    "e.agent_id AS edge_agent_id, "
                    "e.session_id AS edge_session_id, "
                    "e.conversation_id AS edge_conversation_id, "
                    "e.project_id AS edge_project_id, "
                    "e.graph_id AS edge_graph_id "
                    "ORDER BY target_node_id, edge_id"
                ),
                {"start_node_id": query.start_node_id},
            )
        )
        normalized: list[GraphBackendResultRow] = []
        for row in rows:
            relation_type = str(row["relation_type"])
            if query.relation_types and relation_type not in query.relation_types:
                continue
            target_namespace = row_namespace(row, prefix="target_")
            edge_namespace = row_namespace(row, prefix="edge_")
            if not namespace_matches_filter(target_namespace, query.namespace):
                continue
            if not namespace_matches_filter(edge_namespace, query.namespace):
                continue
            normalized.append(
                GraphBackendResultRow(
                    node_ids=[str(row["target_node_id"])],
                    edge_ids=[str(row["edge_id"])],
                    properties={
                        "labels": decode_json_list(
                            as_optional_str(row.get("labels_json"))
                        ),
                        "relation_type": relation_type,
                        "target_properties": decode_json_object(
                            as_optional_str(row.get("target_properties_json"))
                        ),
                        "edge_properties": decode_json_object(
                            as_optional_str(row.get("edge_properties_json"))
                        ),
                    },
                )
            )
        if query.limit is not None:
            normalized = normalized[: query.limit]
        return GraphBackendResult(
            query_id=query.query_id,
            backend_name=self._capabilities.backend_name,
            rows=normalized,
        )

    def _query_property_filter(self, query: GraphBackendQuery) -> GraphBackendResult:
        rows = self._rows_as_dict(
            self._execute(
                (
                    "// sg_op:query_property_filter\n"
                    f"MATCH (n:{_NODE_LABEL}) "
                    "RETURN "
                    "n.node_id AS node_id, "
                    "n.primary_label AS primary_label, "
                    "n.labels_json AS labels_json, "
                    "n.properties_json AS properties_json, "
                    "n.tenant_id AS tenant_id, "
                    "n.org_id AS org_id, "
                    "n.user_id AS user_id, "
                    "n.agent_id AS agent_id, "
                    "n.session_id AS session_id, "
                    "n.conversation_id AS conversation_id, "
                    "n.project_id AS project_id, "
                    "n.graph_id AS graph_id "
                    "ORDER BY node_id"
                )
            )
        )
        result_rows: list[GraphBackendResultRow] = []
        for row in rows:
            labels = decode_json_list(as_optional_str(row.get("labels_json")))
            if query.node_labels and not any(
                label in query.node_labels for label in labels
            ):
                continue
            namespace = row_namespace(row, prefix="")
            if not namespace_matches_filter(namespace, query.namespace):
                continue
            properties = decode_json_object(as_optional_str(row.get("properties_json")))
            if not property_filters_match(properties, query.property_filters):
                continue
            result_rows.append(
                GraphBackendResultRow(
                    node_ids=[str(row["node_id"])],
                    properties={
                        "labels": labels,
                        "namespace": namespace,
                        **properties,
                    },
                )
            )
        if query.limit is not None:
            result_rows = result_rows[: query.limit]
        return GraphBackendResult(
            query_id=query.query_id,
            backend_name=self._capabilities.backend_name,
            rows=result_rows,
        )

    def _query_shortest_path(self, query: GraphBackendQuery) -> GraphBackendResult:
        rows = self._rows_as_dict(
            self._execute(
                (
                    "// sg_op:query_all_edges\n"
                    f"MATCH (a:{_NODE_LABEL})-[e:{_EDGE_LABEL}]->(b:{_NODE_LABEL}) "
                    "RETURN "
                    "a.node_id AS source_node_id, "
                    "b.node_id AS target_node_id, "
                    "e.edge_id AS edge_id, "
                    "e.relation_type AS relation_type, "
                    "e.properties_json AS edge_properties_json, "
                    "e.tenant_id AS tenant_id, "
                    "e.org_id AS org_id, "
                    "e.user_id AS user_id, "
                    "e.agent_id AS agent_id, "
                    "e.session_id AS session_id, "
                    "e.conversation_id AS conversation_id, "
                    "e.project_id AS project_id, "
                    "e.graph_id AS graph_id "
                    "ORDER BY source_node_id, target_node_id, edge_id"
                )
            )
        )
        edges = []

        for row in rows:
            namespace = MemoryNamespace.from_dict(row_namespace(row, prefix=""))
            if not namespace_matches_filter(namespace, query.namespace):
                continue
            edges.append(
                GraphExportEdge(
                    edge_id=str(row["edge_id"]),
                    source_node_id=str(row["source_node_id"]),
                    target_node_id=str(row["target_node_id"]),
                    relation_type=str(row["relation_type"]),
                    namespace=namespace,
                    properties=decode_json_object(
                        as_optional_str(row.get("edge_properties_json"))
                    ),
                )
            )
        row = shortest_path_from_edges(
            start_node_id=str(query.start_node_id),
            target_node_id=str(query.target_node_id),
            edges=edges,
            relation_types=query.relation_types,
        )
        return GraphBackendResult(
            query_id=query.query_id,
            backend_name=self._capabilities.backend_name,
            rows=[] if row is None else [row],
        )

    def _execute(self, statement: str, params: dict[str, Any] | None = None) -> Any:
        session = (
            self._driver.session(database=self._database)
            if self._database is not None
            else self._driver.session()
        )
        with session as opened:
            return opened.run(statement, params or {})

    @staticmethod
    def _rows_as_dict(result: Any) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for row in result:
            keys = list(row.keys()) if hasattr(row, "keys") else []
            rows.append({str(key): row[key] for key in keys})
        return rows


__all__ = ["Neo4jGraphBackendAdapter"]
