"""Graph navigation DTOs for structural knowledge links."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.models import MemoryNamespace, RelationDirection


@dataclass(frozen=True, slots=True)
class LinkQueryOptions:
    record_id: str
    direction: RelationDirection = "out"
    relation_types: list[str] | None = None
    namespaces: list[MemoryNamespace] | None = None
    context_chars: int = 80
    limit: int | None = None

    def __post_init__(self) -> None:
        if not self.record_id:
            raise InvalidArgumentError("record_id is required")
        if self.direction not in {"out", "in", "both"}:
            raise InvalidArgumentError(f"invalid direction: {self.direction!r}")
        if self.context_chars < 0:
            raise InvalidArgumentError("context_chars must be non-negative")
        if self.limit is not None and self.limit <= 0:
            raise InvalidArgumentError("limit must be positive")


@dataclass(frozen=True, slots=True)
class LocalGraphOptions:
    record_id: str
    depth: int = 1
    direction: RelationDirection = "both"
    relation_types: list[str] | None = None
    namespaces: list[MemoryNamespace] | None = None
    max_nodes: int = 100
    max_edges: int = 250

    def __post_init__(self) -> None:
        if not self.record_id:
            raise InvalidArgumentError("record_id is required")
        if self.depth < 0:
            raise InvalidArgumentError("depth must be non-negative")
        if self.direction not in {"out", "in", "both"}:
            raise InvalidArgumentError(f"invalid direction: {self.direction!r}")
        if self.max_nodes <= 0:
            raise InvalidArgumentError("max_nodes must be positive")
        if self.max_edges <= 0:
            raise InvalidArgumentError("max_edges must be positive")


@dataclass(frozen=True, slots=True)
class GraphSnapshotOptions:
    scopes: list[str]
    namespaces: list[MemoryNamespace] | None = None
    relation_types: list[str] | None = None
    include_orphans: bool = True
    max_nodes: int = 500
    max_edges: int = 1000

    def __post_init__(self) -> None:
        if not self.scopes:
            raise InvalidArgumentError("at least one scope is required")
        if self.max_nodes <= 0:
            raise InvalidArgumentError("max_nodes must be positive")
        if self.max_edges <= 0:
            raise InvalidArgumentError("max_edges must be positive")


@dataclass(frozen=True, slots=True)
class GraphNode:
    record_id: str
    title: str | None = None
    path: str | None = None
    tags: list[str] = field(default_factory=list)
    properties: dict[str, Any] = field(default_factory=dict)
    degree_in: int = 0
    degree_out: int = 0
    orphan: bool = False
    namespace: MemoryNamespace | None = None
    provenance: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class GraphEdge:
    edge_id: str
    source_record_id: str
    target_record_id: str | None
    relation_type: str | None = None
    direction: str = "out"
    unresolved_target: str | None = None
    label: str | None = None
    provenance: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.edge_id:
            raise InvalidArgumentError("edge_id is required")
        if not self.source_record_id:
            raise InvalidArgumentError("source_record_id is required")
        if self.target_record_id is None and not self.unresolved_target:
            raise InvalidArgumentError("edge requires a target or unresolved target")


@dataclass(frozen=True, slots=True)
class GraphSnapshot:
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    root_record_id: str | None = None
    depth: int | None = None
    direction: RelationDirection = "both"
    provenance: dict[str, Any] = field(default_factory=dict)


__all__ = [
    "GraphEdge",
    "GraphNode",
    "GraphSnapshot",
    "GraphSnapshotOptions",
    "LinkQueryOptions",
    "LocalGraphOptions",
]
