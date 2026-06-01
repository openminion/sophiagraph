"""Optional graph backend adapter contracts."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
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
]
GraphBackendQueryKind = Literal["neighbors", "shortest_path", "schema"]


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
            if feature not in {
                "schema_export",
                "batch_upsert",
                "neighbors",
                "shortest_path",
                "property_filter",
            }:
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
    limit: int | None = None

    def __post_init__(self) -> None:
        if not self.query_id:
            raise InvalidArgumentError("query_id is required")
        if self.kind not in {"neighbors", "shortest_path", "schema"}:
            raise InvalidArgumentError(f"invalid query kind: {self.kind!r}")
        if self.kind in {"neighbors", "shortest_path"} and not self.start_node_id:
            raise InvalidArgumentError("graph query requires start_node_id")
        if self.kind == "shortest_path" and not self.target_node_id:
            raise InvalidArgumentError("shortest_path query requires target_node_id")
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


class FakeGraphBackendAdapter:
    def __init__(self, *, support_shortest_path: bool = False) -> None:
        features: list[GraphBackendFeature] = [
            "schema_export",
            "batch_upsert",
            "neighbors",
            "property_filter",
        ]
        if support_shortest_path:
            features.append("shortest_path")
        self._capabilities = GraphBackendCapabilities(
            backend_name="fake",
            supported_features=features,
        )
        self._batch: GraphExportBatch | None = None

    def capabilities(self) -> GraphBackendCapabilities:
        return self._capabilities

    def upsert_batch(self, batch: GraphExportBatch) -> None:
        self._batch = batch

    def query(self, query: GraphBackendQuery) -> GraphBackendResult:
        if query.kind == "shortest_path" and not self._capabilities.supports(
            "shortest_path"
        ):
            return GraphBackendResult(
                query_id=query.query_id,
                backend_name=self._capabilities.backend_name,
                unsupported_reason="shortest_path unsupported by backend",
            )
        if self._batch is None:
            return GraphBackendResult(
                query_id=query.query_id,
                backend_name=self._capabilities.backend_name,
            )
        if query.kind == "schema":
            return GraphBackendResult(
                query_id=query.query_id,
                backend_name=self._capabilities.backend_name,
                rows=[
                    GraphBackendResultRow(
                        properties={
                            "node_labels": self._batch.schema.node_labels,
                            "relation_types": self._batch.schema.relation_types,
                        }
                    )
                ],
            )
        neighbors = [
            edge
            for edge in self._batch.edges
            if edge.source_node_id == query.start_node_id
            and (
                query.relation_types is None
                or edge.relation_type in query.relation_types
            )
        ]
        if query.limit is not None:
            neighbors = neighbors[: query.limit]
        return GraphBackendResult(
            query_id=query.query_id,
            backend_name=self._capabilities.backend_name,
            rows=[
                GraphBackendResultRow(
                    node_ids=[edge.target_node_id],
                    edge_ids=[edge.edge_id],
                    properties=asdict(edge),
                )
                for edge in neighbors
            ],
        )


__all__ = [
    "FakeGraphBackendAdapter",
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
]
