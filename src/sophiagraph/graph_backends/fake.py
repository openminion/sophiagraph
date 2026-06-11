"""Provider-free fake graph backend for conformance tests."""

from __future__ import annotations

from dataclasses import asdict

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
        ]
        if support_shortest_path:
            features.append("shortest_path")
        if support_pattern_query:
            features.append("pattern_query")
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
        payload = query.pattern_query or {}
        seeds = [str(item) for item in payload.get("seed_record_ids", [])]
        relation_types = {
            str(item) for item in payload.get("relation_types", []) if str(item)
        }
        max_hops = int(payload.get("max_hops", 1))
        edges = list(self._batch.edges)
        rows: list[GraphBackendResultRow] = []
        for seed in seeds:
            current = seed
            current_edge_ids: list[str] = []
            current_node_ids = [seed]
            hops = 0
            while hops < max_hops:
                next_edge = next(
                    (
                        edge
                        for edge in edges
                        if edge.source_node_id == current
                        and (not relation_types or edge.relation_type in relation_types)
                    ),
                    None,
                )
                if next_edge is None:
                    break
                current_edge_ids.append(next_edge.edge_id)
                current_node_ids.append(next_edge.target_node_id)
                current = next_edge.target_node_id
                hops += 1
            if len(current_node_ids) > 1:
                rows.append(
                    GraphBackendResultRow(
                        node_ids=current_node_ids,
                        edge_ids=current_edge_ids,
                        properties={"query_kind": "pattern"},
                    )
                )
        return GraphBackendResult(
            query_id=query.query_id,
            backend_name=self._capabilities.backend_name,
            rows=rows,
        )


__all__ = ["FakeGraphBackendAdapter"]
