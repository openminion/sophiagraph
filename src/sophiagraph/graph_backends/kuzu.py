"""Optional Kuzu-backed graph backend adapter."""

from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
from typing import Any

from .base import (
    GraphBackendCapabilities,
    GraphBackendQuery,
    GraphBackendResult,
    GraphBackendResultRow,
    GraphExportBatch,
    GraphExportEdge,
    GraphExportNode,
    decode_json_list,
    decode_json_object,
    namespace_columns,
    namespace_matches_filter,
    property_filters_match,
    schema_result_row,
    shortest_path_from_edges,
)
from sophiagraph.models import MemoryNamespace
from sophiagraph.models.projection import ProjectionInventoryItem
from sophiagraph.schema import GraphSchema
from .kuzu_support import (
    as_optional_str,
    import_kuzu,
    load_schema_from_json,
    memory_namespace_from_row,
    row_namespace,
)
from .patterns import evaluate_pattern_query

_NODE_TABLE = "SGNode"
_EDGE_TABLE = "SGEdge"
_META_TABLE = "SGMeta"
_SCHEMA_META_KEY = "schema_json"
_BATCH_META_KEY = "batch_id"
_WATERMARK_META_KEY = "projection_watermark"


class KuzuGraphBackendAdapter:
    def __init__(self, db_path: str | Path) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        kuzu = import_kuzu()
        self._db = kuzu.Database(str(self._db_path))
        self._conn = kuzu.Connection(self._db)
        self._capabilities = GraphBackendCapabilities(
            backend_name="kuzu",
            supported_features=[
                "schema_export",
                "batch_upsert",
                "neighbors",
                "shortest_path",
                "property_filter",
                "pattern_query",
                "batch_delete",
                "projection_watermark",
                "inventory",
            ],
            notes={
                "install_extra": "kuzu",
                "pattern_query": "deterministic typed payload evaluation",
            },
            batch_behavior="idempotent_partial",
        )
        self._ensure_schema()

    def capabilities(self) -> GraphBackendCapabilities:
        return self._capabilities

    def upsert_batch(self, batch: GraphExportBatch) -> None:
        self._ensure_schema()
        edge_ids = [*batch.delete_edge_ids, *(edge.edge_id for edge in batch.edges)]
        if edge_ids:
            self._execute(
                (
                    f"MATCH ()-[e:{_EDGE_TABLE}]->() "
                    "WHERE e.edge_id IN $edge_ids DELETE e;"
                ),
                {"edge_ids": edge_ids},
            )
        if batch.delete_node_ids:
            self._execute(
                f"MATCH (n:{_NODE_TABLE}) WHERE n.node_id IN $node_ids DETACH DELETE n;",
                {"node_ids": list(batch.delete_node_ids)},
            )
        for node in batch.nodes:
            self._insert_node(node)
        for edge in batch.edges:
            self._insert_edge(edge)
        self._upsert_meta(
            _SCHEMA_META_KEY, json.dumps(asdict(batch.schema), sort_keys=True)
        )
        self._upsert_meta(_BATCH_META_KEY, batch.batch_id)

    def delete(self, *, node_ids: tuple[str, ...], edge_ids: tuple[str, ...]) -> None:
        if edge_ids:
            self._execute(
                f"MATCH ()-[e:{_EDGE_TABLE}]->() WHERE e.edge_id IN $edge_ids DELETE e;",
                {"edge_ids": list(edge_ids)},
            )
        if node_ids:
            self._execute(
                f"MATCH (n:{_NODE_TABLE}) WHERE n.node_id IN $node_ids DETACH DELETE n;",
                {"node_ids": list(node_ids)},
            )

    def set_projection_watermark(self, cursor: int) -> None:
        self._upsert_meta(_WATERMARK_META_KEY, str(int(cursor)))

    def get_projection_watermark(self) -> int | None:
        value = self._load_meta(_WATERMARK_META_KEY)
        return int(value) if value is not None else None

    def inventory(self) -> tuple[ProjectionInventoryItem, ...]:
        node_rows = self._rows_as_dict(
            self._execute(
                f"MATCH (n:{_NODE_TABLE}) RETURN n.node_id AS object_id, n.properties_json AS properties_json;"
            )
        )
        edge_rows = self._rows_as_dict(
            self._execute(
                f"MATCH ()-[e:{_EDGE_TABLE}]->() RETURN e.edge_id AS object_id, e.properties_json AS properties_json;"
            )
        )
        items = [
            ProjectionInventoryItem(
                object_id=str(row["object_id"]),
                object_kind=kind,
                version_hash=decode_json_object(
                    as_optional_str(row["properties_json"])
                ).get("_projection_version"),
            )
            for kind, rows in (("node", node_rows), ("edge", edge_rows))
            for row in rows
        ]
        return tuple(sorted(items, key=lambda item: (item.object_kind, item.object_id)))

    def query(self, query: GraphBackendQuery) -> GraphBackendResult:
        if query.kind == "pattern":
            return evaluate_pattern_query(
                query,
                backend_name=self._capabilities.backend_name,
                nodes=self._all_nodes(namespace_filter=query.namespace),
                edges=self._all_edges(namespace_filter=query.namespace),
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

    def _ensure_schema(self) -> None:
        self._execute(
            (
                f"CREATE NODE TABLE IF NOT EXISTS {_NODE_TABLE}("
                "node_id STRING, "
                "primary_label STRING, "
                "labels_json STRING, "
                "properties_json STRING, "
                "tenant_id STRING, "
                "org_id STRING, "
                "user_id STRING, "
                "agent_id STRING, "
                "session_id STRING, "
                "conversation_id STRING, "
                "project_id STRING, "
                "graph_id STRING, "
                "PRIMARY KEY(node_id));"
            )
        )
        self._execute(
            (
                f"CREATE REL TABLE IF NOT EXISTS {_EDGE_TABLE}("
                f"FROM {_NODE_TABLE} TO {_NODE_TABLE}, "
                "edge_id STRING, "
                "relation_type STRING, "
                "properties_json STRING, "
                "tenant_id STRING, "
                "org_id STRING, "
                "user_id STRING, "
                "agent_id STRING, "
                "session_id STRING, "
                "conversation_id STRING, "
                "project_id STRING, "
                "graph_id STRING);"
            )
        )
        self._execute(
            (
                f"CREATE NODE TABLE IF NOT EXISTS {_META_TABLE}("
                "meta_key STRING, meta_value STRING, PRIMARY KEY(meta_key));"
            )
        )

    def _insert_node(self, node: GraphExportNode) -> None:
        params = {
            "node_id": node.node_id,
            "primary_label": node.labels[0],
            "labels_json": json.dumps(node.labels, sort_keys=True),
            "properties_json": json.dumps(
                {
                    **node.properties,
                    "_projection_version": node.version_hash,
                },
                sort_keys=True,
            ),
            **namespace_columns(node.namespace),
        }
        self._execute(
            (
                f"MERGE (n:{_NODE_TABLE} {{node_id: $node_id}}) "
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
                "n.graph_id = $graph_id;"
            ),
            params,
        )

    def _insert_edge(self, edge: GraphExportEdge) -> None:
        params = {
            "source_node_id": edge.source_node_id,
            "target_node_id": edge.target_node_id,
            "edge_id": edge.edge_id,
            "relation_type": edge.relation_type,
            "properties_json": json.dumps(
                {
                    **edge.properties,
                    "_projection_version": edge.version_hash,
                },
                sort_keys=True,
            ),
            **namespace_columns(edge.namespace),
        }
        self._execute(
            (
                f"MATCH (a:{_NODE_TABLE} {{node_id: $source_node_id}}), "
                f"(b:{_NODE_TABLE} {{node_id: $target_node_id}}) "
                f"CREATE (a)-[:{_EDGE_TABLE} {{"
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
                "graph_id: $graph_id}]->(b);"
            ),
            params,
        )

    def _upsert_meta(self, key: str, value: str) -> None:
        self._execute(
            f"MATCH (m:{_META_TABLE} {{meta_key: $meta_key}}) DELETE m;",
            {"meta_key": key},
        )
        self._execute(
            f"CREATE (:{_META_TABLE} {{meta_key: $meta_key, meta_value: $meta_value}});",
            {"meta_key": key, "meta_value": value},
        )

    def _load_meta(self, key: str) -> str | None:
        rows = self._rows_as_dict(
            self._execute(
                f"MATCH (m:{_META_TABLE} {{meta_key: $meta_key}}) RETURN m.meta_value AS meta_value;",
                {"meta_key": key},
            )
        )
        return as_optional_str(rows[0]["meta_value"]) if rows else None

    def _query_neighbors(self, query: GraphBackendQuery) -> GraphBackendResult:
        rows = self._rows_as_dict(
            self._execute(
                (
                    f"MATCH (s:{_NODE_TABLE} {{node_id: $start_node_id}})"
                    f"-[e:{_EDGE_TABLE}]->(t:{_NODE_TABLE}) "
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
                    "e.graph_id AS edge_graph_id;"
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
                        "relation_type": relation_type,
                        "labels": decode_json_list(as_optional_str(row["labels_json"])),
                        "target_namespace": target_namespace,
                        "edge_namespace": edge_namespace,
                        "target_properties": decode_json_object(
                            as_optional_str(row["target_properties_json"])
                        ),
                        "edge_properties": decode_json_object(
                            as_optional_str(row["edge_properties_json"])
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
        where_clauses: list[str] = []
        params: dict[str, Any] = {}
        if query.node_labels:
            where_clauses.append("n.primary_label IN $node_labels")
            params["node_labels"] = list(query.node_labels)
        if query.namespace is not None:
            for field, value in query.namespace.as_dict().items():
                where_clauses.append(f"n.{field} = ${field}")
                params[field] = value
        statement = f"MATCH (n:{_NODE_TABLE}) "
        if where_clauses:
            statement += f"WHERE {' AND '.join(where_clauses)} "
        statement += (
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
            "n.graph_id AS graph_id;"
        )
        rows = self._rows_as_dict(self._execute(statement, params))
        normalized: list[GraphBackendResultRow] = []
        for row in rows:
            properties = decode_json_object(as_optional_str(row["properties_json"]))
            if not property_filters_match(properties, query.property_filters):
                continue
            normalized.append(
                GraphBackendResultRow(
                    node_ids=[str(row["node_id"])],
                    properties={
                        "labels": decode_json_list(as_optional_str(row["labels_json"])),
                        "namespace": row_namespace(row, prefix=""),
                        **properties,
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

    def _query_shortest_path(self, query: GraphBackendQuery) -> GraphBackendResult:
        edges = self._all_edges(namespace_filter=query.namespace)
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

    def _load_schema(self) -> GraphSchema | None:
        rows = self._rows_as_dict(
            self._execute(
                f"MATCH (m:{_META_TABLE} {{meta_key: $meta_key}}) RETURN m.meta_value AS meta_value;",
                {"meta_key": _SCHEMA_META_KEY},
            )
        )
        if not rows:
            return None
        return load_schema_from_json(as_optional_str(rows[0]["meta_value"]))

    def _all_edges(
        self, *, namespace_filter: MemoryNamespace | None = None
    ) -> list[GraphExportEdge]:
        rows = self._rows_as_dict(
            self._execute(
                (
                    f"MATCH (a:{_NODE_TABLE})-[e:{_EDGE_TABLE}]->(b:{_NODE_TABLE}) "
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
                    "e.graph_id AS graph_id;"
                )
            )
        )
        edges: list[GraphExportEdge] = []
        for row in rows:
            namespace = memory_namespace_from_row(row, prefix="")
            if namespace_filter is not None and not namespace.matches(namespace_filter):
                continue
            edges.append(
                GraphExportEdge(
                    edge_id=str(row["edge_id"]),
                    source_node_id=str(row["source_node_id"]),
                    target_node_id=str(row["target_node_id"]),
                    relation_type=str(row["relation_type"]),
                    namespace=namespace,
                    properties=decode_json_object(
                        as_optional_str(row["edge_properties_json"])
                    ),
                )
            )
        return edges

    def _all_nodes(
        self, *, namespace_filter: MemoryNamespace | None = None
    ) -> list[GraphExportNode]:
        rows = self._rows_as_dict(
            self._execute(
                (
                    f"MATCH (n:{_NODE_TABLE}) RETURN "
                    "n.node_id AS node_id, n.labels_json AS labels_json, "
                    "n.properties_json AS properties_json, "
                    "n.tenant_id AS tenant_id, n.org_id AS org_id, "
                    "n.user_id AS user_id, n.agent_id AS agent_id, "
                    "n.session_id AS session_id, "
                    "n.conversation_id AS conversation_id, "
                    "n.project_id AS project_id, n.graph_id AS graph_id;"
                )
            )
        )
        nodes: list[GraphExportNode] = []
        for row in rows:
            namespace = memory_namespace_from_row(row, prefix="")
            if namespace_filter is not None and not namespace.matches(namespace_filter):
                continue
            nodes.append(
                GraphExportNode(
                    node_id=str(row["node_id"]),
                    labels=decode_json_list(as_optional_str(row["labels_json"])),
                    namespace=namespace,
                    properties=decode_json_object(
                        as_optional_str(row["properties_json"])
                    ),
                )
            )
        return nodes

    def _execute(self, statement: str, params: dict[str, Any] | None = None):
        if params is None:
            return self._conn.execute(statement)
        return self._conn.execute(statement, params)

    @staticmethod
    def _rows_as_dict(result: Any) -> list[dict[str, Any]]:
        columns = [str(column) for column in result.get_column_names()]
        rows: list[dict[str, Any]] = []
        while result.has_next():
            values = result.get_next()
            rows.append(dict(zip(columns, values, strict=True)))
        return rows


__all__ = ["KuzuGraphBackendAdapter"]
