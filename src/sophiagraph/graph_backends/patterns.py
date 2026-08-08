"""Deterministic structural pattern evaluation for graph backend adapters."""

from __future__ import annotations

from collections import deque
from typing import Any

from sophiagraph.contracts.errors import InvalidArgumentError

from .support import namespace_matches_filter
from .types import (
    GraphBackendQuery,
    GraphBackendResult,
    GraphBackendResultRow,
    GraphExportEdge,
    GraphExportNode,
)

_DIRECTIONS = frozenset({"out", "in", "both"})
_OPERATORS = frozenset({"eq", "ne", "contains", "in", "exists"})


def evaluate_pattern_query(
    query: GraphBackendQuery,
    *,
    backend_name: str,
    nodes: list[GraphExportNode],
    edges: list[GraphExportEdge],
) -> GraphBackendResult:
    """Evaluate one typed pattern payload without accepting backend query text."""

    payload = query.pattern_query or {}
    direction = str(payload.get("direction", "both"))
    if direction not in _DIRECTIONS:
        raise InvalidArgumentError(f"invalid pattern direction: {direction!r}")
    min_hops = _non_negative_int(payload, "min_hops", default=1)
    max_hops = _positive_int(payload, "max_hops", default=2)
    if min_hops > max_hops:
        raise InvalidArgumentError("pattern min_hops cannot exceed max_hops")
    predicates = _predicates(payload.get("node_predicates", []))
    relation_types = {
        str(item) for item in payload.get("relation_types", []) if str(item)
    }
    node_by_id = {
        node.node_id: node
        for node in nodes
        if namespace_matches_filter(node.namespace, query.namespace)
    }
    filtered_edges = [
        edge
        for edge in edges
        if edge.source_node_id in node_by_id
        and edge.target_node_id in node_by_id
        and namespace_matches_filter(edge.namespace, query.namespace)
        and (not relation_types or edge.relation_type in relation_types)
    ]
    candidate_ids = sorted(
        node_id
        for node_id, node in node_by_id.items()
        if _matches_predicates(node, predicates)
    )
    requested_seeds = payload.get("seed_record_ids", [])
    seeds = (
        sorted(str(item) for item in requested_seeds if str(item) in node_by_id)
        if requested_seeds
        else sorted(node_by_id)
    )
    limit = min(
        query.limit or _positive_int(payload, "limit", default=50),
        _positive_int(payload, "limit", default=50),
    )
    project = {str(item) for item in payload.get("project", [])}
    rows: list[GraphBackendResultRow] = []
    seen: set[tuple[tuple[str, ...], tuple[str, ...]]] = set()
    for seed in seeds:
        for target in candidate_ids:
            if seed == target:
                continue
            path = _shortest_path(
                seed,
                target,
                edges=filtered_edges,
                direction=direction,
                max_hops=max_hops,
            )
            if path is None or len(path[1]) < min_hops:
                continue
            key = (tuple(path[0]), tuple(path[1]))
            if key in seen:
                continue
            seen.add(key)
            target_node = node_by_id[target]
            rows.append(
                GraphBackendResultRow(
                    node_ids=path[0] if not project or "record_ids" in project else [],
                    edge_ids=path[1] if not project or "edge_ids" in project else [],
                    properties=(
                        {"labels": list(target_node.labels), **target_node.properties}
                        if not project or "properties" in project
                        else {}
                    ),
                )
            )
            if len(rows) >= limit:
                return _result(query, backend_name, rows)
    return _result(query, backend_name, rows)


def _shortest_path(
    start: str,
    target: str,
    *,
    edges: list[GraphExportEdge],
    direction: str,
    max_hops: int,
) -> tuple[list[str], list[str]] | None:
    adjacency: dict[str, list[tuple[str, str]]] = {}
    for edge in edges:
        if direction in {"out", "both"}:
            adjacency.setdefault(edge.source_node_id, []).append(
                (edge.target_node_id, edge.edge_id)
            )
        if direction in {"in", "both"}:
            adjacency.setdefault(edge.target_node_id, []).append(
                (edge.source_node_id, edge.edge_id)
            )
    for neighbors in adjacency.values():
        neighbors.sort()
    queue = deque([(start, [start], [])])
    while queue:
        current, node_ids, edge_ids = queue.popleft()
        if len(edge_ids) >= max_hops:
            continue
        for neighbor, edge_id in adjacency.get(current, []):
            if neighbor in node_ids:
                continue
            next_nodes = [*node_ids, neighbor]
            next_edges = [*edge_ids, edge_id]
            if neighbor == target:
                return next_nodes, next_edges
            queue.append((neighbor, next_nodes, next_edges))
    return None


def _predicates(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise InvalidArgumentError("node_predicates must be a list")
    predicates: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict) or not str(item.get("field", "")):
            raise InvalidArgumentError("pattern predicates require a field")
        operator = str(item.get("operator", "eq"))
        if operator not in _OPERATORS:
            raise InvalidArgumentError(f"invalid pattern operator: {operator!r}")
        predicates.append(dict(item))
    return predicates


def _matches_predicates(
    node: GraphExportNode,
    predicates: list[dict[str, Any]],
) -> bool:
    values = {"id": node.node_id, "labels": list(node.labels), **node.properties}
    return all(
        _match(
            values.get(str(item["field"])),
            str(item.get("operator", "eq")),
            item.get("value"),
        )
        for item in predicates
    )


def _match(actual: Any, operator: str, expected: Any) -> bool:
    if operator == "exists":
        return actual is not None
    if operator == "eq":
        return actual == expected
    if operator == "ne":
        return actual != expected
    if operator == "contains":
        if isinstance(actual, (list, tuple, set)):
            return str(expected) in {str(item) for item in actual}
        return str(expected) in str(actual or "")
    if not isinstance(expected, (list, tuple, set)):
        raise InvalidArgumentError("pattern 'in' operator requires list-like value")
    return str(actual) in {str(item) for item in expected}


def _positive_int(payload: dict[str, Any], key: str, *, default: int) -> int:
    value = payload.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise InvalidArgumentError(f"pattern {key} must be a positive integer")
    return value


def _non_negative_int(payload: dict[str, Any], key: str, *, default: int) -> int:
    value = payload.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise InvalidArgumentError(f"pattern {key} must be a non-negative integer")
    return value


def _result(
    query: GraphBackendQuery,
    backend_name: str,
    rows: list[GraphBackendResultRow],
) -> GraphBackendResult:
    return GraphBackendResult(
        query_id=query.query_id,
        backend_name=backend_name,
        rows=rows,
    )


__all__ = ["evaluate_pattern_query"]
