"""Structural community and pattern-query helpers for graph-wide retrieval."""

from __future__ import annotations

from collections import Counter, deque
from typing import Any, Mapping
from uuid import NAMESPACE_URL, uuid5

from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.models import MemoryNamespace, MemoryRecord
from sophiagraph.models.namespace import sorted_namespace_key
from sophiagraph.query.algorithms import (
    GraphPath,
    all_simple_paths,
    degree_metrics,
)
from sophiagraph.query.graph import GraphSnapshot, GraphSnapshotOptions
from sophiagraph.query.options import ListQueryOptions, SearchQueryOptions
from sophiagraph.temporal import utc_now_iso

from .community_types import (
    PATTERN_DIRECTIONS,
    CommunityAlgorithm,
    CommunityDetectionOptions,
    CommunityQueryHit,
    CommunityOmittedDiagnostic,
    CommunityQueryOptions,
    CommunityQueryPlan,
    CommunityQueryPlanStage,
    CommunityQueryResult,
    CommunitySnapshot,
    CommunitySnapshotStatus,
    CommunitySourceSet,
    CommunityStore,
    GraphCommunity,
    GraphCommunityMembership,
    GraphLayoutHint,
    GraphPatternMatch,
    GraphPatternNodePredicate,
    GraphPatternQuery,
    GraphPatternQueryResult,
    PatternDirection,
    PatternOperator,
)

STRUCTURAL_CHANGE_TYPES = {"record", "relation", "link"}


def _stable_id(prefix: str, *parts: str) -> str:
    return f"{prefix}:{uuid5(NAMESPACE_URL, '|'.join(parts))}"


def _normalize_namespace_parts(
    namespaces: list[MemoryNamespace] | None,
) -> tuple[str, ...]:
    if not namespaces:
        return ()
    return tuple(sorted(sorted_namespace_key(namespace) for namespace in namespaces))


def _community_namespace(
    snapshot: GraphSnapshot, namespaces: list[MemoryNamespace] | None
) -> MemoryNamespace:
    if namespaces:
        return namespaces[0]
    for node in snapshot.nodes:
        if node.namespace is not None:
            return node.namespace
    return MemoryNamespace(graph_id="community")


def _node_ids(snapshot: GraphSnapshot) -> set[str]:
    return {node.record_id for node in snapshot.nodes}


def _adjacency(
    snapshot: GraphSnapshot,
    *,
    direction: PatternDirection = "both",
    relation_types: list[str] | None = None,
) -> dict[str, list[tuple[str, Any]]]:
    if direction not in PATTERN_DIRECTIONS:
        raise InvalidArgumentError(f"invalid direction: {direction!r}")
    allowed = set(relation_types or [])
    node_ids = _node_ids(snapshot)
    graph: dict[str, list[tuple[str, Any]]] = {node_id: [] for node_id in node_ids}
    for edge in snapshot.edges:
        if edge.target_record_id is None:
            continue
        if allowed and edge.relation_type not in allowed:
            continue
        if (
            edge.source_record_id not in node_ids
            or edge.target_record_id not in node_ids
        ):
            continue
        if direction in {"out", "both"}:
            graph[edge.source_record_id].append((edge.target_record_id, edge))
        if direction in {"in", "both"}:
            graph[edge.target_record_id].append((edge.source_record_id, edge))
    for neighbors in graph.values():
        neighbors.sort(key=lambda item: (item[0], item[1].edge_id))
    return graph


def _record_properties(record: MemoryRecord) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    meta_properties = record.meta.get("properties")
    if isinstance(meta_properties, dict):
        properties.update(meta_properties)
    document = record.meta.get("document")
    if isinstance(document, dict):
        properties.update(document)
    properties.setdefault("id", record.id)
    properties.setdefault("scope", record.scope)
    properties.setdefault("type", record.type)
    properties.setdefault("title", record.title)
    properties.setdefault("source", record.source)
    properties.setdefault("tier", record.tier)
    properties.setdefault("tags", list(record.tags))
    properties.setdefault("created_at", record.created_at)
    properties.setdefault("updated_at", record.updated_at)
    properties.setdefault("event_time", record.event_time)
    properties.setdefault("valid_to", record.valid_to)
    properties.setdefault("source_id", record.meta.get("source_id"))
    return properties


def _match_operator(actual: Any, operator: PatternOperator, value: Any) -> bool:
    if operator == "exists":
        return actual is not None
    if operator == "eq":
        return actual == value
    if operator == "ne":
        return actual != value
    if operator == "contains":
        if isinstance(actual, list | tuple | set):
            return str(value) in {str(item) for item in actual}
        return str(value) in str(actual or "")
    if operator == "in":
        if not isinstance(value, list | tuple | set):
            raise InvalidArgumentError("pattern 'in' operator requires list-like value")
        return str(actual) in {str(item) for item in value}
    raise InvalidArgumentError(f"unsupported operator: {operator!r}")


def detect_communities(
    snapshot: GraphSnapshot,
    options: CommunityDetectionOptions,
) -> tuple[list[GraphCommunity], list[GraphCommunityMembership]]:
    """Return deterministic structural communities and memberships."""
    namespace = _community_namespace(snapshot, options.namespaces)
    adjacency = _adjacency(
        snapshot, direction="both", relation_types=options.relation_types
    )
    if options.algorithm == "connected_components":
        groups = _connected_component_groups(adjacency)
    else:
        groups = _label_propagation_groups(adjacency)
    groups = [group for group in groups if len(group) >= options.min_size]
    groups.sort(key=lambda members: (-len(members), members))
    if options.max_communities is not None:
        groups = groups[: options.max_communities]
    communities: list[GraphCommunity] = []
    memberships: list[GraphCommunityMembership] = []
    filtered_degrees = {
        record_id: len(neighbors) for record_id, neighbors in adjacency.items()
    }
    for members in groups:
        edge_ids = _community_edge_ids(
            snapshot,
            set(members),
            relation_types=options.relation_types,
        )
        seed_record_id = _community_seed_record_id(members, filtered_degrees)
        community_id = _stable_id(
            "community",
            options.algorithm,
            sorted_namespace_key(namespace),
            *members,
        )
        score = float(len(edge_ids)) / float(max(1, len(members) - 1))
        communities.append(
            GraphCommunity(
                community_id=community_id,
                namespace=namespace,
                record_ids=members,
                edge_ids=edge_ids,
                seed_record_id=seed_record_id,
                algorithm=options.algorithm,
                score=score,
                meta={"size": len(members)},
            )
        )
        for index, record_id in enumerate(
            sorted(
                members,
                key=lambda item: (
                    -filtered_degrees.get(item, 0),
                    item,
                ),
            ),
            start=1,
        ):
            evidence_ids = _membership_edge_ids(
                snapshot,
                record_id,
                set(members),
                relation_types=options.relation_types,
            )
            memberships.append(
                GraphCommunityMembership(
                    record_id=record_id,
                    community_id=community_id,
                    rank=index,
                    degree_in_community=len(evidence_ids),
                    evidence_edge_ids=evidence_ids,
                )
            )
    memberships.sort(key=lambda item: (item.community_id, item.rank, item.record_id))
    return communities, memberships


def build_community_snapshot(
    store: CommunityStore,
    options: CommunityDetectionOptions,
) -> CommunitySnapshot:
    """Compute one community snapshot and pin the latest visible cursor."""
    snapshot = store.get_graph_snapshot(
        GraphSnapshotOptions(
            scopes=options.scopes,
            namespaces=options.namespaces,
            relation_types=options.relation_types,
            include_orphans=True,
        )
    )
    communities, memberships = detect_communities(snapshot, options)
    changes = store.list_changes(namespaces=options.namespaces)
    latest_cursor = max(
        (event.cursor for event in changes if event.cursor is not None),
        default=None,
    )
    snapshot_id = _stable_id(
        "community-snapshot",
        options.algorithm,
        ",".join(sorted(options.scopes)),
        *(_normalize_namespace_parts(options.namespaces)),
        str(latest_cursor),
    )
    return CommunitySnapshot(
        snapshot_id=snapshot_id,
        algorithm=options.algorithm,
        scopes=list(options.scopes),
        namespaces=options.namespaces,
        latest_cursor=latest_cursor,
        computed_at=utc_now_iso(),
        communities=communities,
        memberships=memberships,
    )


def community_snapshot_status(
    store: CommunityStore,
    snapshot: CommunitySnapshot,
) -> CommunitySnapshotStatus:
    """Report whether a community snapshot is stale relative to changefeed."""
    changes = store.list_changes(
        since_cursor=snapshot.latest_cursor,
        namespaces=snapshot.namespaces,
    )
    relevant = [
        event for event in changes if event.object_type in STRUCTURAL_CHANGE_TYPES
    ]
    latest_cursor = max(
        (event.cursor for event in relevant if event.cursor is not None),
        default=snapshot.latest_cursor,
    )
    reasons = sorted({event.object_type for event in relevant})
    return CommunitySnapshotStatus(
        snapshot_id=snapshot.snapshot_id,
        stale=bool(relevant),
        latest_cursor=latest_cursor,
        stale_reasons=reasons,
    )


def query_communities(
    store: CommunityStore,
    options: CommunityQueryOptions,
) -> CommunityQueryResult:
    """Return structural global/community packets without generated summaries."""
    snapshot = build_community_snapshot(store, options.detection)
    selected = snapshot.communities
    omitted: list[CommunityOmittedDiagnostic] = []
    if options.community_ids:
        allowed = set(options.community_ids)
        pre_count = len(selected)
        selected = [
            community for community in selected if community.community_id in allowed
        ]
        if pre_count != len(selected):
            omitted.append(
                CommunityOmittedDiagnostic(
                    reason="query_filter",
                    count=pre_count - len(selected),
                    details={"filter": "community_ids"},
                )
            )
    community_by_id = {community.community_id: community for community in selected}
    memberships = [
        membership
        for membership in snapshot.memberships
        if membership.community_id in community_by_id
    ]
    if not selected:
        return CommunityQueryResult(
            communities=[],
            memberships=[],
            hits=[],
            omitted=omitted,
            query_plan=CommunityQueryPlan(
                [CommunityQueryPlanStage("communities", len(snapshot.communities), 0)]
            ),
            summary_reference_ids=options.summary_reference_ids
            if options.include_summary_refs
            else [],
        )
    community_record_ids = {
        record_id for community in selected for record_id in community.record_ids
    }
    common = {
        "scopes": options.detection.scopes,
        "namespaces": options.detection.namespaces,
        "limit": None,
        "include_invalidated": bool(
            options.detection.as_of or options.detection.valid_at
        ),
        "as_of": options.detection.as_of,
        "valid_at": options.detection.valid_at,
    }
    if options.query:
        records = store.search_records(
            SearchQueryOptions(query=options.query, **common)
        )
    else:
        records = store.list_records(ListQueryOptions(**common))
    records = [record for record in records if record.id in community_record_ids]
    plan = [
        CommunityQueryPlanStage("communities", len(snapshot.communities), len(selected))
    ]
    if options.limit and len(records) > options.limit:
        omitted.append(
            CommunityOmittedDiagnostic(
                reason="hit_limit",
                count=len(records) - options.limit,
                details={"limit": options.limit},
            )
        )
    records = records[: options.limit]
    membership_by_record = {
        membership.record_id: membership for membership in memberships
    }
    source_sets = _community_source_sets(records, membership_by_record)
    hits = [
        CommunityQueryHit(
            record=record,
            community_id=membership_by_record[record.id].community_id,
            score=_community_hit_score(record, membership_by_record[record.id]),
            source_set_ids=[
                source_set.source_set_id
                for source_set in source_sets
                if record.id in source_set.record_ids
            ],
        )
        for record in records
        if record.id in membership_by_record
    ]
    plan.append(
        CommunityQueryPlanStage("records", len(community_record_ids), len(hits))
    )
    paths: list[GraphPath] = []
    if options.include_paths:
        full_snapshot = store.get_graph_snapshot(
            GraphSnapshotOptions(
                scopes=options.detection.scopes,
                namespaces=options.detection.namespaces,
                relation_types=options.detection.relation_types,
                include_orphans=False,
            )
        )
        for community in selected:
            seed = community.seed_record_id
            if seed is None:
                continue
            for hit in hits:
                if hit.community_id != community.community_id or hit.record_id == seed:
                    continue
                path = all_simple_paths(
                    full_snapshot,
                    seed,
                    hit.record_id,
                    max_depth=2,
                    max_paths=1,
                    direction="both",
                )
                if path:
                    paths.append(path[0])
        plan.append(CommunityQueryPlanStage("paths", len(hits), len(paths)))
    return CommunityQueryResult(
        communities=selected,
        memberships=memberships,
        hits=hits if options.include_records else [],
        source_sets=source_sets,
        paths=paths,
        omitted=omitted,
        query_plan=CommunityQueryPlan(plan),
        summary_reference_ids=options.summary_reference_ids
        if options.include_summary_refs
        else [],
    )


def layout_hints_for_snapshot(
    snapshot: GraphSnapshot,
    communities: list[GraphCommunity],
) -> list[GraphLayoutHint]:
    """Return deterministic display-neutral hints from degree and membership."""
    membership_by_record = {
        record_id: community.community_id
        for community in communities
        for record_id in community.record_ids
    }
    degree_map = {
        metric.record_id: metric
        for metric in degree_metrics(snapshot, normalized=False)
    }
    return [
        GraphLayoutHint(
            record_id=node.record_id,
            community_id=membership_by_record.get(node.record_id),
            layout_kind="community_band",
            suggested_weight=float(
                degree_map.get(node.record_id).degree_total
                if degree_map.get(node.record_id)
                else 0
            ),
            suggested_radius=float(
                1
                + (
                    degree_map.get(node.record_id).degree_total
                    if degree_map.get(node.record_id)
                    else 0
                )
            ),
            edge_weight=degree_map.get(node.record_id).degree_total
            if degree_map.get(node.record_id)
            else 0,
        )
        for node in snapshot.nodes
    ]


def pattern_query_to_backend_payload(query: GraphPatternQuery) -> dict[str, Any]:
    """Serialize a structural pattern query for optional backend adapters."""
    return {
        "query_id": query.query_id,
        "scopes": list(query.scopes),
        "seed_record_ids": list(query.seed_record_ids or []),
        "node_predicates": [
            {
                "field": predicate.field,
                "operator": predicate.operator,
                "value": predicate.value,
            }
            for predicate in query.node_predicates
        ],
        "relation_types": list(query.relation_types or []),
        "direction": query.direction,
        "min_hops": query.min_hops,
        "max_hops": query.max_hops,
        "limit": query.limit,
        "project": list(query.project),
    }


def execute_graph_pattern_query(
    store: CommunityStore,
    query: GraphPatternQuery,
) -> GraphPatternQueryResult:
    """Execute one provider-free graph-pattern query against explicit edges."""
    snapshot = store.get_graph_snapshot(
        GraphSnapshotOptions(
            scopes=query.scopes,
            namespaces=query.namespaces,
            relation_types=query.relation_types,
            include_orphans=True,
        )
    )
    records = store.list_records(
        ListQueryOptions(
            scopes=query.scopes,
            namespaces=query.namespaces,
            limit=None,
            include_invalidated=bool(query.as_of or query.valid_at),
            as_of=query.as_of,
            valid_at=query.valid_at,
        )
    )
    record_by_id = {record.id: record for record in records}
    communities, memberships = detect_communities(
        snapshot,
        CommunityDetectionOptions(
            scopes=query.scopes,
            namespaces=query.namespaces,
            relation_types=query.relation_types,
        ),
    )
    community_ids_by_record = {
        membership.record_id: membership.community_id for membership in memberships
    }
    node_ids = sorted(_node_ids(snapshot))
    seed_ids = sorted(query.seed_record_ids or node_ids)
    candidate_ids = [
        record_id
        for record_id in node_ids
        if record_id in record_by_id
        and _record_matches_predicates(record_by_id[record_id], query.node_predicates)
    ]
    matches: list[GraphPatternMatch] = []
    seen: set[tuple[tuple[str, ...], tuple[str, ...]]] = set()
    for seed_id in seed_ids:
        for candidate_id in candidate_ids:
            if seed_id == candidate_id:
                continue
            paths = all_simple_paths(
                snapshot,
                seed_id,
                candidate_id,
                max_depth=query.max_hops,
                max_paths=1,
                direction=query.direction,
            )
            if not paths:
                continue
            path = paths[0]
            if path.hop_count < query.min_hops:
                continue
            key = (tuple(path.record_ids), tuple(path.edge_ids))
            if key in seen:
                continue
            seen.add(key)
            properties: dict[str, Any] = {}
            if "properties" in query.project:
                target_record = record_by_id.get(candidate_id)
                if target_record is not None:
                    properties = _record_properties(target_record)
            matches.append(
                GraphPatternMatch(
                    record_ids=path.record_ids if "record_ids" in query.project else [],
                    edge_ids=path.edge_ids if "edge_ids" in query.project else [],
                    community_ids=sorted(
                        {
                            community_ids_by_record[record_id]
                            for record_id in path.record_ids
                            if record_id in community_ids_by_record
                        }
                    )
                    if "community_ids" in query.project
                    else [],
                    properties=properties,
                )
            )
            if len(matches) >= query.limit:
                break
        if len(matches) >= query.limit:
            break
    matches.sort(key=lambda item: (item.record_ids, item.edge_ids))
    return GraphPatternQueryResult(
        query_id=query.query_id,
        matches=matches,
        query_plan=CommunityQueryPlan(
            [
                CommunityQueryPlanStage("seeds", len(seed_ids), len(seed_ids)),
                CommunityQueryPlanStage(
                    "candidates", len(node_ids), len(candidate_ids)
                ),
                CommunityQueryPlanStage("matches", len(candidate_ids), len(matches)),
            ]
        ),
    )


def _connected_component_groups(
    adjacency: Mapping[str, list[tuple[str, Any]]],
) -> list[list[str]]:
    seen: set[str] = set()
    groups: list[list[str]] = []
    for node_id in sorted(adjacency):
        if node_id in seen:
            continue
        queue: deque[str] = deque([node_id])
        seen.add(node_id)
        members: list[str] = []
        while queue:
            current = queue.popleft()
            members.append(current)
            for neighbor, _edge in adjacency[current]:
                if neighbor not in seen:
                    seen.add(neighbor)
                    queue.append(neighbor)
        groups.append(sorted(members))
    return groups


def _label_propagation_groups(
    adjacency: Mapping[str, list[tuple[str, Any]]],
) -> list[list[str]]:
    labels = {node_id: node_id for node_id in adjacency}
    changed = True
    iterations = 0
    while changed and iterations < 25:
        changed = False
        iterations += 1
        for node_id in sorted(adjacency):
            neighbor_labels = [
                labels[neighbor] for neighbor, _edge in adjacency[node_id]
            ]
            if not neighbor_labels:
                continue
            counts = Counter(neighbor_labels)
            max_count = max(counts.values())
            winning = sorted(
                label for label, count in counts.items() if count == max_count
            )[0]
            if labels[node_id] != winning:
                labels[node_id] = winning
                changed = True
    grouped: dict[str, list[str]] = {}
    for node_id, label in labels.items():
        grouped.setdefault(label, []).append(node_id)
    return [
        sorted(group)
        for _, group in sorted(
            grouped.items(), key=lambda item: (len(item[1]) * -1, item[0])
        )
    ]


def _community_edge_ids(
    snapshot: GraphSnapshot,
    member_ids: set[str],
    *,
    relation_types: list[str] | None,
) -> list[str]:
    allowed = set(relation_types or [])
    edge_ids = [
        edge.edge_id
        for edge in snapshot.edges
        if edge.target_record_id is not None
        and (not allowed or edge.relation_type in allowed)
        and edge.source_record_id in member_ids
        and edge.target_record_id in member_ids
    ]
    return sorted(set(edge_ids))


def _community_seed_record_id(
    members: list[str],
    degree_map: Mapping[str, int],
) -> str:
    return sorted(
        members,
        key=lambda item: (
            -degree_map.get(item, 0),
            item,
        ),
    )[0]


def _membership_edge_ids(
    snapshot: GraphSnapshot,
    record_id: str,
    member_ids: set[str],
    *,
    relation_types: list[str] | None,
) -> list[str]:
    allowed = set(relation_types or [])
    return sorted(
        {
            edge.edge_id
            for edge in snapshot.edges
            if edge.target_record_id is not None
            and (not allowed or edge.relation_type in allowed)
            and (
                (
                    edge.source_record_id == record_id
                    and edge.target_record_id in member_ids
                )
                or (
                    edge.target_record_id == record_id
                    and edge.source_record_id in member_ids
                )
            )
        }
    )


def _community_source_sets(
    records: list[MemoryRecord],
    membership_by_record: Mapping[str, GraphCommunityMembership],
) -> list[CommunitySourceSet]:
    buckets: dict[tuple[str, str], list[str]] = {}
    for record in records:
        membership = membership_by_record.get(record.id)
        if membership is None:
            continue
        keys = [f"source:{record.source}"]
        source_id = record.meta.get("source_id")
        if isinstance(source_id, str) and source_id:
            keys.append(f"source_id:{source_id}")
        for source_key in keys:
            buckets.setdefault((membership.community_id, source_key), []).append(
                record.id
            )
    source_sets = [
        CommunitySourceSet(
            source_set_id=_stable_id("source-set", community_id, source_key),
            community_id=community_id,
            source_key=source_key,
            count=len(record_ids),
            record_ids=sorted(record_ids),
        )
        for (community_id, source_key), record_ids in sorted(buckets.items())
    ]
    return source_sets


def _community_hit_score(
    record: MemoryRecord,
    membership: GraphCommunityMembership,
) -> float:
    score = float(membership.degree_in_community)
    if record.meta.get("source_id"):
        score += 0.1
    return score


def _record_matches_predicates(
    record: MemoryRecord,
    predicates: list[GraphPatternNodePredicate],
) -> bool:
    properties = _record_properties(record)
    for predicate in predicates:
        actual = properties.get(predicate.field)
        if not _match_operator(actual, predicate.operator, predicate.value):
            return False
    return True


__all__ = [
    "CommunityAlgorithm",
    "CommunityDetectionOptions",
    "CommunityOmittedDiagnostic",
    "CommunityQueryHit",
    "CommunityQueryOptions",
    "CommunityQueryPlan",
    "CommunityQueryPlanStage",
    "CommunityQueryResult",
    "CommunitySnapshot",
    "CommunitySnapshotStatus",
    "CommunitySourceSet",
    "GraphCommunity",
    "GraphCommunityMembership",
    "GraphLayoutHint",
    "GraphPatternMatch",
    "GraphPatternNodePredicate",
    "GraphPatternQuery",
    "GraphPatternQueryResult",
    "build_community_snapshot",
    "community_snapshot_status",
    "detect_communities",
    "execute_graph_pattern_query",
    "layout_hints_for_snapshot",
    "pattern_query_to_backend_payload",
    "query_communities",
]
