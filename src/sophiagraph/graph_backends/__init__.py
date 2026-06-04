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
)
from .fake import FakeGraphBackendAdapter
from .kuzu import KuzuGraphBackendAdapter

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
    "build_graph_export_batch",
]
