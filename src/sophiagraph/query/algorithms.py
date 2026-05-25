"""Deterministic graph algorithms over structural graph snapshots."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.query.graph import GraphEdge, GraphSnapshot

_DIRECTIONS = {"out", "in", "both"}


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


def _validate_direction(direction: str) -> None:
    if direction not in _DIRECTIONS:
        raise InvalidArgumentError(f"invalid direction: {direction!r}")


def _validate_positive(value: int | None, name: str) -> None:
    if value is not None and value <= 0:
        raise InvalidArgumentError(f"{name} must be positive")


def _validate_non_negative(value: int | None, name: str) -> None:
    if value is not None and value < 0:
        raise InvalidArgumentError(f"{name} must be non-negative")


def _edge_neighbors(edge: GraphEdge) -> tuple[str, str] | None:
    if edge.target_record_id is None:
        return None
    return edge.source_record_id, edge.target_record_id


def _adjacency(
    snapshot: GraphSnapshot, *, direction: str = "both"
) -> dict[str, list[tuple[str, GraphEdge]]]:
    _validate_direction(direction)
    node_ids = {node.record_id for node in snapshot.nodes}
    graph: dict[str, list[tuple[str, GraphEdge]]] = {
        node_id: [] for node_id in node_ids
    }
    for edge in snapshot.edges:
        pair = _edge_neighbors(edge)
        if pair is None:
            continue
        source, target = pair
        if source not in node_ids or target not in node_ids:
            continue
        if direction in {"out", "both"}:
            graph[source].append((target, edge))
        if direction in {"in", "both"}:
            graph[target].append((source, edge))
    for neighbors in graph.values():
        neighbors.sort(key=lambda item: (item[0], item[1].edge_id))
    return graph


def shortest_path(
    snapshot: GraphSnapshot,
    source_record_id: str,
    target_record_id: str,
    *,
    direction: str = "both",
    max_depth: int | None = None,
) -> GraphPath | None:
    """Return the deterministic unweighted shortest path between two records."""
    if not source_record_id:
        raise InvalidArgumentError("source_record_id is required")
    if not target_record_id:
        raise InvalidArgumentError("target_record_id is required")
    _validate_direction(direction)
    _validate_non_negative(max_depth, "max_depth")
    if source_record_id == target_record_id:
        return GraphPath(record_ids=[source_record_id], edge_ids=[], relation_types=[])
    graph = _adjacency(snapshot, direction=direction)
    if source_record_id not in graph or target_record_id not in graph:
        return None
    queue: deque[tuple[str, int]] = deque([(source_record_id, 0)])
    previous: dict[str, tuple[str, GraphEdge] | None] = {source_record_id: None}
    while queue:
        current, depth = queue.popleft()
        if max_depth is not None and depth >= max_depth:
            continue
        for neighbor, edge in graph[current]:
            if neighbor in previous:
                continue
            previous[neighbor] = (current, edge)
            if neighbor == target_record_id:
                queue.clear()
                break
            queue.append((neighbor, depth + 1))
    if target_record_id not in previous:
        return None
    record_ids = [target_record_id]
    edge_ids: list[str] = []
    relation_types: list[str | None] = []
    current = target_record_id
    while previous[current] is not None:
        parent, edge = previous[current]
        record_ids.append(parent)
        edge_ids.append(edge.edge_id)
        relation_types.append(edge.relation_type)
        current = parent
    record_ids.reverse()
    edge_ids.reverse()
    relation_types.reverse()
    return GraphPath(
        record_ids=record_ids,
        edge_ids=edge_ids,
        relation_types=relation_types,
    )


def path_evidence(
    snapshot: GraphSnapshot,
    source_record_id: str,
    target_record_id: str,
    *,
    direction: str = "both",
    max_depth: int | None = None,
) -> list[GraphEdge]:
    """Return edge DTOs that support the shortest path between two records."""
    path = shortest_path(
        snapshot,
        source_record_id,
        target_record_id,
        direction=direction,
        max_depth=max_depth,
    )
    if path is None:
        return []
    edge_by_id = {edge.edge_id: edge for edge in snapshot.edges}
    return [edge_by_id[edge_id] for edge_id in path.edge_ids if edge_id in edge_by_id]


def all_simple_paths(
    snapshot: GraphSnapshot,
    source_record_id: str,
    target_record_id: str,
    *,
    max_depth: int = 4,
    max_paths: int = 25,
    direction: str = "both",
) -> list[GraphPath]:
    """Return deterministic bounded simple paths between two records."""
    if not source_record_id:
        raise InvalidArgumentError("source_record_id is required")
    if not target_record_id:
        raise InvalidArgumentError("target_record_id is required")
    _validate_direction(direction)
    _validate_positive(max_depth, "max_depth")
    _validate_positive(max_paths, "max_paths")
    graph = _adjacency(snapshot, direction=direction)
    if source_record_id not in graph or target_record_id not in graph:
        return []
    paths: list[GraphPath] = []
    stack: list[tuple[str, list[str], list[GraphEdge]]] = [
        (source_record_id, [source_record_id], [])
    ]
    while stack and len(paths) < max_paths:
        current, record_ids, edges = stack.pop()
        if len(edges) >= max_depth:
            continue
        for neighbor, edge in reversed(graph[current]):
            if neighbor in record_ids:
                continue
            next_records = [*record_ids, neighbor]
            next_edges = [*edges, edge]
            if neighbor == target_record_id:
                paths.append(
                    GraphPath(
                        record_ids=next_records,
                        edge_ids=[item.edge_id for item in next_edges],
                        relation_types=[item.relation_type for item in next_edges],
                    )
                )
                if len(paths) >= max_paths:
                    break
                continue
            stack.append((neighbor, next_records, next_edges))
    paths.sort(key=lambda path: (path.hop_count, path.record_ids, path.edge_ids))
    return paths


def connected_components(
    snapshot: GraphSnapshot, *, direction: str = "both"
) -> list[GraphComponent]:
    """Return undirected connected components for the visible snapshot nodes."""
    graph = _adjacency(snapshot, direction=direction)
    seen: set[str] = set()
    components: list[GraphComponent] = []
    for node_id in sorted(graph):
        if node_id in seen:
            continue
        queue: deque[str] = deque([node_id])
        seen.add(node_id)
        members: list[str] = []
        while queue:
            current = queue.popleft()
            members.append(current)
            for neighbor, _edge in graph[current]:
                if neighbor not in seen:
                    seen.add(neighbor)
                    queue.append(neighbor)
        members.sort()
        components.append(
            GraphComponent(
                component_id=f"component:{len(components) + 1}",
                record_ids=members,
            )
        )
    return components


def common_neighbors(
    snapshot: GraphSnapshot,
    record_id: str,
    other_record_id: str,
    *,
    direction: str = "both",
    limit: int | None = None,
) -> GraphCommonNeighbors:
    """Return shared explicit neighbors for two records."""
    if not record_id:
        raise InvalidArgumentError("record_id is required")
    if not other_record_id:
        raise InvalidArgumentError("other_record_id is required")
    _validate_direction(direction)
    _validate_positive(limit, "limit")
    graph = _adjacency(snapshot, direction=direction)
    first = {neighbor for neighbor, _edge in graph.get(record_id, [])}
    second = {neighbor for neighbor, _edge in graph.get(other_record_id, [])}
    neighbors = sorted(first & second)
    if limit is not None:
        neighbors = neighbors[:limit]
    edge_ids = sorted(
        edge.edge_id
        for source in (record_id, other_record_id)
        for neighbor, edge in graph.get(source, [])
        if neighbor in neighbors
    )
    return GraphCommonNeighbors(
        record_id=record_id,
        other_record_id=other_record_id,
        neighbor_record_ids=neighbors,
        edge_ids=edge_ids,
    )


def degree_metrics(
    snapshot: GraphSnapshot,
    *,
    normalized: bool = True,
) -> list[GraphDegreeMetric]:
    """Return deterministic in/out/total degree metrics for every node."""
    node_ids = {node.record_id for node in snapshot.nodes}
    degree_in = {node_id: 0 for node_id in node_ids}
    degree_out = {node_id: 0 for node_id in node_ids}
    for edge in snapshot.edges:
        pair = _edge_neighbors(edge)
        if pair is None:
            continue
        source, target = pair
        if source in node_ids:
            degree_out[source] += 1
        if target in node_ids:
            degree_in[target] += 1
    divisor = float(len(node_ids) - 1) if normalized and len(node_ids) > 1 else 1.0
    return [
        GraphDegreeMetric(
            record_id=node_id,
            degree_in=degree_in[node_id],
            degree_out=degree_out[node_id],
            degree_total=degree_in[node_id] + degree_out[node_id],
            centrality=(degree_in[node_id] + degree_out[node_id]) / divisor,
        )
        for node_id in sorted(node_ids)
    ]


def degree_centrality(
    snapshot: GraphSnapshot,
    *,
    normalized: bool = True,
) -> dict[str, float]:
    """Return degree centrality using explicit snapshot edges only."""
    return {
        metric.record_id: metric.centrality
        for metric in degree_metrics(snapshot, normalized=normalized)
    }


def orphan_clusters(snapshot: GraphSnapshot) -> list[GraphOrphanCluster]:
    """Return nodes with no incident explicit edges as a deterministic cluster."""
    orphan_ids = [
        metric.record_id
        for metric in degree_metrics(snapshot, normalized=False)
        if metric.degree_total == 0
    ]
    if not orphan_ids:
        return []
    return [GraphOrphanCluster(cluster_id="orphans:1", record_ids=orphan_ids)]


def retrieval_path_evidence(
    snapshot: GraphSnapshot,
    source_record_id: str,
    target_record_id: str,
    *,
    max_depth: int = 4,
    max_paths: int = 3,
    direction: str = "both",
) -> RetrievalPathEvidence:
    """Return GraphRAG-safe path evidence from stored edges only."""
    return RetrievalPathEvidence(
        source_record_id=source_record_id,
        target_record_id=target_record_id,
        paths=all_simple_paths(
            snapshot,
            source_record_id,
            target_record_id,
            max_depth=max_depth,
            max_paths=max_paths,
            direction=direction,
        ),
    )


__all__ = [
    "GraphCommonNeighbors",
    "GraphComponent",
    "GraphDegreeMetric",
    "GraphOrphanCluster",
    "GraphPath",
    "RetrievalPathEvidence",
    "all_simple_paths",
    "common_neighbors",
    "connected_components",
    "degree_metrics",
    "degree_centrality",
    "orphan_clusters",
    "path_evidence",
    "retrieval_path_evidence",
    "shortest_path",
]
