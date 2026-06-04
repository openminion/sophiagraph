"""Provider-neutral graph backend DTOs and helpers."""

from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass, field
import json
from typing import Any, Literal, Protocol

from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.models import (
    MemoryNamespace,
    MemoryRecord,
    MemoryRelation,
    StructuralLink,
)
from sophiagraph.schema import GraphSchema, describe_schema

GraphBackendFeature = Literal[
    "schema_export",
    "batch_upsert",
    "neighbors",
    "shortest_path",
    "property_filter",
    "pattern_query",
]
GraphBackendQueryKind = Literal[
    "neighbors",
    "shortest_path",
    "schema",
    "pattern",
    "property_filter",
]

_SUPPORTED_FEATURES: frozenset[str] = frozenset(
    {
        "schema_export",
        "batch_upsert",
        "neighbors",
        "shortest_path",
        "property_filter",
        "pattern_query",
    }
)
_SUPPORTED_QUERY_KINDS: frozenset[str] = frozenset(
    {"neighbors", "shortest_path", "schema", "pattern", "property_filter"}
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


@dataclass(frozen=True, slots=True)
class GraphBackendCapabilities:
    backend_name: str
    supported_features: list[GraphBackendFeature] = field(default_factory=list)
    max_batch_size: int | None = None
    notes: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.backend_name:
            raise InvalidArgumentError("backend_name is required")
        for feature in self.supported_features:
            if feature not in _SUPPORTED_FEATURES:
                raise InvalidArgumentError(f"invalid backend feature: {feature!r}")
        if self.max_batch_size is not None and self.max_batch_size <= 0:
            raise InvalidArgumentError("max_batch_size must be positive")

    def supports(self, feature: GraphBackendFeature) -> bool:
        return feature in self.supported_features


@dataclass(frozen=True, slots=True)
class GraphExportNode:
    node_id: str
    labels: list[str]
    namespace: MemoryNamespace
    properties: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.node_id:
            raise InvalidArgumentError("node_id is required")
        if not self.labels:
            raise InvalidArgumentError("at least one node label is required")
        if not isinstance(self.namespace, MemoryNamespace):
            raise TypeError("namespace must be MemoryNamespace")


@dataclass(frozen=True, slots=True)
class GraphExportEdge:
    edge_id: str
    source_node_id: str
    target_node_id: str
    relation_type: str
    namespace: MemoryNamespace
    properties: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.edge_id:
            raise InvalidArgumentError("edge_id is required")
        if not self.source_node_id or not self.target_node_id:
            raise InvalidArgumentError("source_node_id and target_node_id are required")
        if not self.relation_type:
            raise InvalidArgumentError("relation_type is required")
        if not isinstance(self.namespace, MemoryNamespace):
            raise TypeError("namespace must be MemoryNamespace")


@dataclass(frozen=True, slots=True)
class GraphExportBatch:
    batch_id: str
    schema: GraphSchema
    nodes: list[GraphExportNode] = field(default_factory=list)
    edges: list[GraphExportEdge] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.batch_id:
            raise InvalidArgumentError("batch_id is required")


@dataclass(frozen=True, slots=True)
class GraphBackendQuery:
    query_id: str
    kind: GraphBackendQueryKind
    namespace: MemoryNamespace | None = None
    start_node_id: str | None = None
    target_node_id: str | None = None
    relation_types: list[str] | None = None
    node_labels: list[str] | None = None
    property_filters: dict[str, Any] | None = None
    limit: int | None = None
    pattern_query: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if not self.query_id:
            raise InvalidArgumentError("query_id is required")
        if self.kind not in _SUPPORTED_QUERY_KINDS:
            raise InvalidArgumentError(f"invalid query kind: {self.kind!r}")
        if self.kind in {"neighbors", "shortest_path"} and not self.start_node_id:
            raise InvalidArgumentError("graph query requires start_node_id")
        if self.kind == "shortest_path" and not self.target_node_id:
            raise InvalidArgumentError("shortest_path query requires target_node_id")
        if self.kind == "pattern" and not self.pattern_query:
            raise InvalidArgumentError("pattern queries require pattern_query payload")
        if (
            self.kind == "property_filter"
            and not self.property_filters
            and not self.node_labels
            and self.namespace is None
        ):
            raise InvalidArgumentError(
                "property_filter queries require property_filters, node_labels, or namespace"
            )
        if self.limit is not None and self.limit <= 0:
            raise InvalidArgumentError("limit must be positive")


@dataclass(frozen=True, slots=True)
class GraphBackendResultRow:
    node_ids: list[str] = field(default_factory=list)
    edge_ids: list[str] = field(default_factory=list)
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class GraphBackendResult:
    query_id: str
    backend_name: str
    rows: list[GraphBackendResultRow] = field(default_factory=list)
    unsupported_reason: str | None = None

    def __post_init__(self) -> None:
        if not self.query_id:
            raise InvalidArgumentError("query_id is required")
        if not self.backend_name:
            raise InvalidArgumentError("backend_name is required")


class GraphBackendAdapter(Protocol):
    def capabilities(self) -> GraphBackendCapabilities: ...

    def upsert_batch(self, batch: GraphExportBatch) -> None: ...

    def query(self, query: GraphBackendQuery) -> GraphBackendResult: ...


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
    "GraphBackendAdapter",
    "GraphBackendCapabilities",
    "GraphBackendFeature",
    "GraphBackendQuery",
    "GraphBackendQueryKind",
    "GraphBackendResult",
    "GraphBackendResultRow",
    "GraphExportBatch",
    "GraphExportEdge",
    "GraphExportNode",
    "build_graph_export_batch",
    "decode_json_list",
    "decode_json_object",
    "namespace_columns",
    "namespace_matches_filter",
    "property_filters_match",
    "schema_result_row",
    "shortest_path_from_edges",
]
