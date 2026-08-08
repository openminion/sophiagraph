"""Provider-free fake graph backend for conformance tests."""

from __future__ import annotations

from dataclasses import asdict

from sophiagraph.models.projection import ProjectionInventoryItem
from sophiagraph.schema import GraphSchema

from .base import (
    GraphBackendCapabilities,
    GraphBackendFeature,
    GraphBackendQuery,
    GraphBackendResult,
    GraphBackendResultRow,
    GraphExportBatch,
    GraphExportEdge,
    namespace_matches_filter,
    property_filters_match,
    schema_result_row,
    shortest_path_from_edges,
)
from .patterns import evaluate_pattern_query


class FakeGraphBackendAdapter:
    def __init__(
        self,
        *,
        support_shortest_path: bool = False,
        support_pattern_query: bool = False,
    ) -> None:
        features: list[GraphBackendFeature] = [
            "schema_export",
            "batch_upsert",
            "neighbors",
            "property_filter",
            "batch_delete",
            "projection_watermark",
            "inventory",
        ]
        if support_shortest_path:
            features.append("shortest_path")
        if support_pattern_query:
            features.append("pattern_query")
        self._capabilities = GraphBackendCapabilities(
            backend_name="fake",
            supported_features=features,
            batch_behavior="atomic",
        )
        self._schema = GraphSchema(node_labels=[], relation_types=[])
        self._nodes = {}
        self._edges = {}
        self._batch: GraphExportBatch | None = None
        self._watermark: int | None = None

    def capabilities(self) -> GraphBackendCapabilities:
        return self._capabilities

    def upsert_batch(self, batch: GraphExportBatch) -> None:
        self.delete(
            node_ids=batch.delete_node_ids,
            edge_ids=batch.delete_edge_ids,
        )
        self._schema = batch.schema
        self._nodes.update({node.node_id: node for node in batch.nodes})
        self._edges.update({edge.edge_id: edge for edge in batch.edges})
        self._refresh_batch(batch.batch_id)

    def delete(self, *, node_ids: tuple[str, ...], edge_ids: tuple[str, ...]) -> None:
        for edge_id in edge_ids:
            self._edges.pop(edge_id, None)
        for node_id in node_ids:
            self._nodes.pop(node_id, None)
        self._edges = {
            edge_id: edge
            for edge_id, edge in self._edges.items()
            if edge.source_node_id not in node_ids
            and edge.target_node_id not in node_ids
        }
        self._refresh_batch("delete")

    def set_projection_watermark(self, cursor: int) -> None:
        self._watermark = int(cursor)

    def get_projection_watermark(self) -> int | None:
        return self._watermark

    def inventory(self) -> tuple[ProjectionInventoryItem, ...]:
        items = [
            ProjectionInventoryItem(
                object_id=node.node_id,
                object_kind="node",
                version_hash=node.version_hash,
            )
            for node in self._nodes.values()
        ]
        items.extend(
            ProjectionInventoryItem(
                object_id=edge.edge_id,
                object_kind="edge",
                version_hash=edge.version_hash,
            )
            for edge in self._edges.values()
        )
        return tuple(sorted(items, key=lambda item: (item.object_kind, item.object_id)))

    def _refresh_batch(self, batch_id: str) -> None:
        self._batch = GraphExportBatch(
            batch_id=batch_id,
            schema=self._schema,
            nodes=list(self._nodes.values()),
            edges=list(self._edges.values()),
        )

    def query(self, query: GraphBackendQuery) -> GraphBackendResult:
        if query.kind == "shortest_path" and not self._capabilities.supports(
            "shortest_path"
        ):
            return GraphBackendResult(
                query_id=query.query_id,
                backend_name=self._capabilities.backend_name,
                unsupported_reason="shortest_path unsupported by backend",
            )
        if query.kind == "pattern" and not self._capabilities.supports("pattern_query"):
            return GraphBackendResult(
                query_id=query.query_id,
                backend_name=self._capabilities.backend_name,
                unsupported_reason="pattern_query unsupported by backend",
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
                rows=[schema_result_row(self._batch.schema)],
            )
        if query.kind == "pattern":
            return self._query_pattern(query)
        if query.kind == "property_filter":
            return self._query_property_filter(query)
        if query.kind == "shortest_path":
            all_edges = list(self._batch.edges)
            if query.namespace is not None:
                all_edges = [
                    edge
                    for edge in all_edges
                    if namespace_matches_filter(edge.namespace, query.namespace)
                ]
            row = shortest_path_from_edges(
                start_node_id=str(query.start_node_id),
                target_node_id=str(query.target_node_id),
                edges=all_edges,
                relation_types=query.relation_types,
            )
            return GraphBackendResult(
                query_id=query.query_id,
                backend_name=self._capabilities.backend_name,
                rows=[] if row is None else [row],
            )
        neighbors = self._filtered_edges(query)
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

    def _filtered_edges(self, query: GraphBackendQuery) -> list[GraphExportEdge]:
        if self._batch is None:
            return []
        node_by_id = {node.node_id: node for node in self._batch.nodes}
        edges = [
            edge
            for edge in self._batch.edges
            if edge.source_node_id == query.start_node_id
            and (
                query.relation_types is None
                or edge.relation_type in query.relation_types
            )
        ]
        if query.namespace is not None:
            edges = [
                edge
                for edge in edges
                if namespace_matches_filter(edge.namespace, query.namespace)
                and namespace_matches_filter(
                    node_by_id.get(edge.target_node_id).namespace
                    if edge.target_node_id in node_by_id
                    else None,
                    query.namespace,
                )
            ]
        return edges

    def _query_property_filter(self, query: GraphBackendQuery) -> GraphBackendResult:
        if self._batch is None:
            return GraphBackendResult(
                query_id=query.query_id,
                backend_name=self._capabilities.backend_name,
            )
        rows: list[GraphBackendResultRow] = []
        for node in self._batch.nodes:
            if query.node_labels and not any(
                label in query.node_labels for label in node.labels
            ):
                continue
            if not namespace_matches_filter(node.namespace, query.namespace):
                continue
            if not property_filters_match(node.properties, query.property_filters):
                continue
            rows.append(
                GraphBackendResultRow(
                    node_ids=[node.node_id],
                    properties={
                        "labels": list(node.labels),
                        "namespace": node.namespace.as_dict(),
                        **node.properties,
                    },
                )
            )
        if query.limit is not None:
            rows = rows[: query.limit]
        return GraphBackendResult(
            query_id=query.query_id,
            backend_name=self._capabilities.backend_name,
            rows=rows,
        )

    def _query_pattern(self, query: GraphBackendQuery) -> GraphBackendResult:
        if self._batch is None:
            return GraphBackendResult(
                query_id=query.query_id,
                backend_name=self._capabilities.backend_name,
            )
        return evaluate_pattern_query(
            query,
            backend_name=self._capabilities.backend_name,
            nodes=list(self._batch.nodes),
            edges=list(self._batch.edges),
        )


__all__ = ["FakeGraphBackendAdapter"]
