"""Stable public facade for provider-neutral graph backend contracts and helpers."""

from __future__ import annotations

from .support import (
    build_graph_export_batch,
    decode_json_list,
    decode_json_object,
    namespace_columns,
    namespace_matches_filter,
    property_filters_match,
    schema_result_row,
    shortest_path_from_edges,
)
from .types import (
    GraphBackendAdapter,
    GraphBatchBehavior,
    GraphBackendCapabilities,
    GraphBackendFeature,
    GraphBackendQuery,
    GraphBackendQueryKind,
    GraphBackendResult,
    GraphBackendResultRow,
    GraphExportBatch,
    GraphExportEdge,
    GraphExportNode,
)


__all__ = [
    "GraphBackendAdapter",
    "GraphBatchBehavior",
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
