"""Deterministic graph algorithms over structural graph snapshots."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.query.graph import GraphEdge, GraphSnapshot


@dataclass(frozen=True, slots=True)
class GraphPath:
    """Shortest-path result with explicit edge evidence."""

    record_ids: list[str]
    edge_ids: list[str]
    relation_types: list[str | None] = field(default_factory=list)

    @property
    def hop_count(self) -> int:
        return len(self.edge_ids)


@dataclass(frozen=True, slots=True)
class GraphComponent:
    """Connected component in a graph snapshot."""

    component_id: str
    record_ids: list[str]


def _edge_neighbors(edge: GraphEdge) -> tuple[str, str] | None:
    if edge.target_record_id is None:
        return None
    return edge.source_record_id, edge.target_record_id


def _adjacency(snapshot: GraphSnapshot) -> dict[str, list[tuple[str, GraphEdge]]]:
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
        graph[source].append((target, edge))
        graph[target].append((source, edge))
    for neighbors in graph.values():
        neighbors.sort(key=lambda item: (item[0], item[1].edge_id))
    return graph


def shortest_path(
    snapshot: GraphSnapshot,
    source_record_id: str,
    target_record_id: str,
) -> GraphPath | None:
    """Return the deterministic unweighted shortest path between two records."""
    if not source_record_id:
        raise InvalidArgumentError("source_record_id is required")
    if not target_record_id:
        raise InvalidArgumentError("target_record_id is required")
    if source_record_id == target_record_id:
        return GraphPath(record_ids=[source_record_id], edge_ids=[], relation_types=[])
    graph = _adjacency(snapshot)
    if source_record_id not in graph or target_record_id not in graph:
        return None
    queue: deque[str] = deque([source_record_id])
    previous: dict[str, tuple[str, GraphEdge] | None] = {source_record_id: None}
    while queue:
        current = queue.popleft()
        for neighbor, edge in graph[current]:
            if neighbor in previous:
                continue
            previous[neighbor] = (current, edge)
            if neighbor == target_record_id:
                queue.clear()
                break
            queue.append(neighbor)
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
) -> list[GraphEdge]:
    """Return edge DTOs that support the shortest path between two records."""
    path = shortest_path(snapshot, source_record_id, target_record_id)
    if path is None:
        return []
    edge_by_id = {edge.edge_id: edge for edge in snapshot.edges}
    return [edge_by_id[edge_id] for edge_id in path.edge_ids if edge_id in edge_by_id]


def connected_components(snapshot: GraphSnapshot) -> list[GraphComponent]:
    """Return undirected connected components for the visible snapshot nodes."""
    graph = _adjacency(snapshot)
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


def degree_centrality(
    snapshot: GraphSnapshot,
    *,
    normalized: bool = True,
) -> dict[str, float]:
    """Return degree centrality using explicit snapshot edges only."""
    node_ids = {node.record_id for node in snapshot.nodes}
    degree = {node_id: 0.0 for node_id in node_ids}
    for edge in snapshot.edges:
        pair = _edge_neighbors(edge)
        if pair is None:
            continue
        source, target = pair
        if source in node_ids:
            degree[source] += 1.0
        if target in node_ids:
            degree[target] += 1.0
    if normalized and len(node_ids) > 1:
        divisor = float(len(node_ids) - 1)
        return {record_id: value / divisor for record_id, value in degree.items()}
    return degree


__all__ = [
    "GraphComponent",
    "GraphPath",
    "connected_components",
    "degree_centrality",
    "path_evidence",
    "shortest_path",
]
