"""Optional graph backend adapter contracts and implementations."""

from .base import (
    GraphBackendAdapter,
    GraphBackendCapabilities,
    GraphBackendFeature,
    GraphBackendQuery,
    GraphBackendQueryKind,
    GraphBackendResult,
    GraphBackendResultRow,
    GraphExportBatch,
    GraphExportEdge,
    GraphExportNode,
    build_graph_export_batch,
    decode_json_list,
    decode_json_object,
    namespace_columns,
    namespace_matches_filter,
    property_filters_match,
    schema_result_row,
    shortest_path_from_edges,
)
from .fake import FakeGraphBackendAdapter
from .kuzu import KuzuGraphBackendAdapter
from .neo4j import Neo4jGraphBackendAdapter

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
    "KuzuGraphBackendAdapter",
    "Neo4jGraphBackendAdapter",
    "build_graph_export_batch",
    "decode_json_list",
    "decode_json_object",
    "namespace_columns",
    "namespace_matches_filter",
    "property_filters_match",
    "schema_result_row",
    "shortest_path_from_edges",
]
