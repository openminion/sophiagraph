"""Shared support helpers for provider-neutral graph backends."""

from __future__ import annotations

from collections import deque
from dataclasses import asdict
import json
from typing import Any

from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.models import (
    MemoryNamespace,
    MemoryRecord,
    MemoryRelation,
    StructuralLink,
)
from sophiagraph.schema import GraphSchema, describe_schema

from .types import (
    GraphBackendResultRow,
    GraphExportBatch,
    GraphExportEdge,
    GraphExportNode,
)

_NAMESPACE_FIELDS: tuple[str, ...] = (
    "tenant_id",
    "org_id",
    "user_id",
    "agent_id",
    "session_id",
    "conversation_id",
    "project_id",
    "graph_id",
)


def build_graph_export_batch(
    *,
    batch_id: str,
    records: list[MemoryRecord],
    relations: list[MemoryRelation] | None = None,
    links: list[StructuralLink] | None = None,
) -> GraphExportBatch:
    record_by_id = {record.id: record for record in records}
    nodes = [
        GraphExportNode(
            node_id=record.id,
            labels=[str(record.type)],
            namespace=record.effective_namespace,
            properties={
                "scope": record.scope,
                "key": record.key,
                "title": record.title,
                **(
                    record.meta.get("properties")
                    if isinstance(record.meta.get("properties"), dict)
                    else {}
                ),
            },
        )
        for record in records
    ]
    edges: list[GraphExportEdge] = []
    for relation in relations or []:
        source = record_by_id.get(relation.source_record_id)
        if source is None:
            continue
        edges.append(
            GraphExportEdge(
                edge_id=relation.relation_id,
                source_node_id=relation.source_record_id,
                target_node_id=relation.target_record_id,
                relation_type=str(relation.relation_type),
                namespace=source.effective_namespace,
                properties={"source": "relation"},
            )
        )
    for link in links or []:
        if link.target_record_id is None or not link.relation_type:
            continue
        edges.append(
            GraphExportEdge(
                edge_id=link.link_id,
                source_node_id=link.source_record_id,
                target_node_id=link.target_record_id,
                relation_type=link.relation_type,
                namespace=link.namespace,
                properties={"source": "link", "raw_target": link.raw_target},
            )
        )
    return GraphExportBatch(
        batch_id=batch_id,
        schema=describe_schema(records=records, relations=relations, links=links),
        nodes=nodes,
        edges=edges,
    )


def namespace_columns(namespace: MemoryNamespace) -> dict[str, str | None]:
    values = namespace.as_dict()
    return {field: values.get(field) for field in _NAMESPACE_FIELDS}


def namespace_matches_filter(
    namespace: MemoryNamespace | dict[str, str] | None,
    namespace_filter: MemoryNamespace | None,
) -> bool:
    if namespace_filter is None:
        return True
    if namespace is None:
        return False
    values = (
        namespace.as_dict() if isinstance(namespace, MemoryNamespace) else namespace
    )
    return all(
        values.get(key) == value for key, value in namespace_filter.as_dict().items()
    )


def property_filters_match(
    properties: dict[str, Any], property_filters: dict[str, Any] | None
) -> bool:
    if not property_filters:
        return True
    return all(properties.get(key) == value for key, value in property_filters.items())


def decode_json_object(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise InvalidArgumentError("serialized JSON object must decode to a dict")
    return data


def decode_json_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    data = json.loads(raw)
    if not isinstance(data, list):
        raise InvalidArgumentError("serialized JSON list must decode to a list")
    return [str(item) for item in data]


def shortest_path_from_edges(
    *,
    start_node_id: str,
    target_node_id: str,
    edges: list[GraphExportEdge],
    relation_types: list[str] | None = None,
) -> GraphBackendResultRow | None:
    allowed_relation_types = set(relation_types or [])
    adjacency: dict[str, list[GraphExportEdge]] = {}
    for edge in edges:
        if allowed_relation_types and edge.relation_type not in allowed_relation_types:
            continue
        adjacency.setdefault(edge.source_node_id, []).append(edge)
    queue: deque[tuple[str, list[str], list[str]]] = deque(
        [(start_node_id, [start_node_id], [])]
    )
    visited = {start_node_id}
    while queue:
        current, path_nodes, path_edges = queue.popleft()
        if current == target_node_id:
            return GraphBackendResultRow(
                node_ids=path_nodes,
                edge_ids=path_edges,
                properties={"query_kind": "shortest_path"},
            )
        for edge in adjacency.get(current, []):
            if edge.target_node_id in visited:
                continue
            visited.add(edge.target_node_id)
            queue.append(
                (
                    edge.target_node_id,
                    [*path_nodes, edge.target_node_id],
                    [*path_edges, edge.edge_id],
                )
            )
    return None


def schema_result_row(schema: GraphSchema) -> GraphBackendResultRow:
    return GraphBackendResultRow(properties=asdict(schema))


__all__ = [
    "build_graph_export_batch",
    "decode_json_list",
    "decode_json_object",
    "namespace_columns",
    "namespace_matches_filter",
    "property_filters_match",
    "schema_result_row",
    "shortest_path_from_edges",
]
