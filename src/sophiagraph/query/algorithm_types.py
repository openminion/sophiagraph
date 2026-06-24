"""Typed graph algorithm result contracts."""

from __future__ import annotations

from dataclasses import dataclass, field

from sophiagraph.contracts.errors import InvalidArgumentError


@dataclass(frozen=True, slots=True)
class GraphPath:
    """Shortest-path result with explicit edge evidence."""

    record_ids: list[str]
    edge_ids: list[str]
    relation_types: list[str | None] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.record_ids:
            raise InvalidArgumentError("GraphPath requires at least one record_id")
        if len(self.edge_ids) != len(self.record_ids) - 1:
            raise InvalidArgumentError("edge_ids must connect consecutive records")
        if self.relation_types and len(self.relation_types) != len(self.edge_ids):
            raise InvalidArgumentError("relation_types must match edge_ids")

    @property
    def hop_count(self) -> int:
        return len(self.edge_ids)


@dataclass(frozen=True, slots=True)
class GraphComponent:
    """Connected component in a graph snapshot."""

    component_id: str
    record_ids: list[str]

    def __post_init__(self) -> None:
        if not self.component_id:
            raise InvalidArgumentError("component_id is required")
        if not self.record_ids:
            raise InvalidArgumentError("component requires at least one record_id")


@dataclass(frozen=True, slots=True)
class GraphCommonNeighbors:
    """Shared neighbors between two records with edge evidence."""

    record_id: str
    other_record_id: str
    neighbor_record_ids: list[str]
    edge_ids: list[str]

    def __post_init__(self) -> None:
        if not self.record_id:
            raise InvalidArgumentError("record_id is required")
        if not self.other_record_id:
            raise InvalidArgumentError("other_record_id is required")


@dataclass(frozen=True, slots=True)
class GraphDegreeMetric:
    """Degree metrics for one graph record."""

    record_id: str
    degree_in: int
    degree_out: int
    degree_total: int
    centrality: float

    def __post_init__(self) -> None:
        if not self.record_id:
            raise InvalidArgumentError("record_id is required")
        if self.degree_in < 0 or self.degree_out < 0 or self.degree_total < 0:
            raise InvalidArgumentError("degree values must be non-negative")


@dataclass(frozen=True, slots=True)
class GraphOrphanCluster:
    """Records with no explicit incident graph edges."""

    cluster_id: str
    record_ids: list[str]

    def __post_init__(self) -> None:
        if not self.cluster_id:
            raise InvalidArgumentError("cluster_id is required")
        if not self.record_ids:
            raise InvalidArgumentError("orphan cluster requires record_ids")


@dataclass(frozen=True, slots=True)
class RetrievalPathEvidence:
    """GraphRAG-safe path evidence: only record IDs, edge IDs, and relations."""

    source_record_id: str
    target_record_id: str
    paths: list[GraphPath] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.source_record_id:
            raise InvalidArgumentError("source_record_id is required")
        if not self.target_record_id:
            raise InvalidArgumentError("target_record_id is required")

    @property
    def record_ids(self) -> list[str]:
        ordered: list[str] = []
        for path in self.paths:
            for record_id in path.record_ids:
                if record_id not in ordered:
                    ordered.append(record_id)
        return ordered

    @property
    def edge_ids(self) -> list[str]:
        ordered: list[str] = []
        for path in self.paths:
            for edge_id in path.edge_ids:
                if edge_id not in ordered:
                    ordered.append(edge_id)
        return ordered


__all__ = [
    "GraphCommonNeighbors",
    "GraphComponent",
    "GraphDegreeMetric",
    "GraphOrphanCluster",
    "GraphPath",
    "RetrievalPathEvidence",
]
