"""Typed backend contracts for optional SophiaGraph graph adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.models import MemoryNamespace
from sophiagraph.models.projection import ProjectionInventoryItem
from sophiagraph.schema import GraphSchema

GraphBackendFeature = Literal[
    "schema_export",
    "batch_upsert",
    "neighbors",
    "shortest_path",
    "property_filter",
    "pattern_query",
    "namespace_filter",
    "temporal_filter",
    "governance_filter",
    "fulltext_search",
    "vector_search",
    "batch_delete",
    "projection_watermark",
    "inventory",
]
GraphBatchBehavior = Literal["atomic", "idempotent_partial"]
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
        "namespace_filter",
        "temporal_filter",
        "governance_filter",
        "fulltext_search",
        "vector_search",
        "batch_delete",
        "projection_watermark",
        "inventory",
    }
)
_SUPPORTED_QUERY_KINDS: frozenset[str] = frozenset(
    {"neighbors", "shortest_path", "schema", "pattern", "property_filter"}
)
_SUPPORTED_BATCH_BEHAVIORS = frozenset({"atomic", "idempotent_partial"})


@dataclass(frozen=True, slots=True)
class GraphBackendCapabilities:
    backend_name: str
    supported_features: list[GraphBackendFeature] = field(default_factory=list)
    max_batch_size: int | None = None
    notes: dict[str, str] = field(default_factory=dict)
    batch_behavior: GraphBatchBehavior = "idempotent_partial"

    def __post_init__(self) -> None:
        if not self.backend_name:
            raise InvalidArgumentError("backend_name is required")
        for feature in self.supported_features:
            if feature not in _SUPPORTED_FEATURES:
                raise InvalidArgumentError(f"invalid backend feature: {feature!r}")
        if self.max_batch_size is not None and self.max_batch_size <= 0:
            raise InvalidArgumentError("max_batch_size must be positive")
        if self.batch_behavior not in _SUPPORTED_BATCH_BEHAVIORS:
            raise InvalidArgumentError(
                f"invalid graph batch behavior: {self.batch_behavior!r}"
            )

    def supports(self, feature: GraphBackendFeature) -> bool:
        return feature in self.supported_features


@dataclass(frozen=True, slots=True)
class GraphExportNode:
    node_id: str
    labels: list[str]
    namespace: MemoryNamespace
    properties: dict[str, Any] = field(default_factory=dict)
    version_hash: str | None = None

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
    version_hash: str | None = None

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
    source_cursor_start: int | None = None
    source_cursor_end: int | None = None
    source_event_ids: tuple[str, ...] = ()
    delete_node_ids: tuple[str, ...] = ()
    delete_edge_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.batch_id:
            raise InvalidArgumentError("batch_id is required")
        if (
            self.source_cursor_start is not None
            and self.source_cursor_end is not None
            and self.source_cursor_start > self.source_cursor_end
        ):
            raise InvalidArgumentError("source cursor range is reversed")


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

    def delete(
        self, *, node_ids: tuple[str, ...], edge_ids: tuple[str, ...]
    ) -> None: ...

    def set_projection_watermark(self, cursor: int) -> None: ...

    def get_projection_watermark(self) -> int | None: ...

    def inventory(self) -> tuple[ProjectionInventoryItem, ...]: ...

    def query(self, query: GraphBackendQuery) -> GraphBackendResult: ...


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
]
