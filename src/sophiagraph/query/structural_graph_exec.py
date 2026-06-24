"""Execution helpers for bounded structural graph queries."""

from __future__ import annotations

from dataclasses import asdict

from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.graph_backends import GraphBackendQuery
from sophiagraph.models import MemoryNamespace
from sophiagraph.query.community import (
    CommunityDetectionOptions,
    CommunityQueryOptions,
    CommunityQueryResult,
    CommunitySourceSet,
    GraphCommunity,
    GraphPatternMatch,
    GraphPatternQuery,
    GraphPatternQueryResult,
    execute_graph_pattern_query,
    pattern_query_to_backend_payload,
    query_communities,
)
from sophiagraph.query.structural_graph_types import (
    StructuralGraphPlannerStage,
    StructuralGraphQueryRequest,
    StructuralGraphQueryResult,
    StructuralGraphQueryRow,
    StructuralGraphQueryStore,
)
from sophiagraph.query.algorithms import GraphPath


def execute_structural_graph_query(
    store: StructuralGraphQueryStore,
    request: StructuralGraphQueryRequest,
) -> StructuralGraphQueryResult:
    """Execute a bounded structural graph query against package-local stores."""
    if request.mode == "pattern":
        return _execute_pattern_query(store, request)
    return _execute_global_query(store, request)


def structural_graph_query_to_backend_query(
    request: StructuralGraphQueryRequest,
) -> GraphBackendQuery:
    """Map pattern-mode structural graph queries to the shared backend DTO."""
    if request.mode != "pattern":
        raise InvalidArgumentError(
            "only pattern-mode structural graph queries map to backend DTOs today"
        )
    pattern = GraphPatternQuery(
        query_id=request.query_id,
        scopes=request.scopes,
        namespaces=request.namespaces,
        seed_record_ids=request.seed_record_ids,
        node_predicates=request.node_predicates,
        relation_types=request.relation_types,
        direction=request.direction,
        min_hops=request.min_hops,
        max_hops=request.max_hops,
        limit=request.limit,
        as_of=request.as_of,
        valid_at=request.valid_at,
    )
    return GraphBackendQuery(
        query_id=request.query_id,
        kind="pattern",
        namespace=request.namespaces[0] if request.namespaces else None,
        start_node_id=pattern.seed_record_ids[0] if pattern.seed_record_ids else None,
        relation_types=pattern.relation_types,
        node_labels=request.node_labels,
        property_filters=request.property_filters or None,
        limit=pattern.limit,
        pattern_query=pattern_query_to_backend_payload(pattern),
    )


def _execute_pattern_query(
    store: StructuralGraphQueryStore,
    request: StructuralGraphQueryRequest,
) -> StructuralGraphQueryResult:
    pattern_query = GraphPatternQuery(
        query_id=request.query_id,
        scopes=request.scopes,
        namespaces=request.namespaces,
        seed_record_ids=request.seed_record_ids,
        node_predicates=request.node_predicates,
        relation_types=request.relation_types,
        direction=request.direction,
        min_hops=request.min_hops,
        max_hops=request.max_hops,
        limit=request.limit,
        as_of=request.as_of,
        valid_at=request.valid_at,
    )
    pattern_result = execute_graph_pattern_query(store, pattern_query)
    planner = _pattern_planner(request, pattern_result)
    rows = [
        _pattern_match_to_row(request.query_id, index, match)
        for index, match in enumerate(pattern_result.matches, start=1)
    ]
    return StructuralGraphQueryResult(
        query_id=request.query_id,
        mode=request.mode,
        rows=rows,
        planner=planner,
    )


def _execute_global_query(
    store: StructuralGraphQueryStore,
    request: StructuralGraphQueryRequest,
) -> StructuralGraphQueryResult:
    community_result = query_communities(
        store,
        CommunityQueryOptions(
            detection=CommunityDetectionOptions(
                scopes=request.scopes,
                namespaces=request.namespaces,
                algorithm=request.community_algorithm,
                relation_types=request.relation_types,
                as_of=request.as_of,
                valid_at=request.valid_at,
            ),
            community_ids=request.community_ids,
            include_records=request.include_records,
            include_paths=request.include_paths,
            limit=request.limit,
        ),
    )
    planner = _global_planner(request, community_result)
    rows = [
        _community_to_row(
            request.query_id,
            index,
            community,
            community_result.source_sets,
            request.namespaces,
        )
        for index, community in enumerate(community_result.communities, start=1)
    ]
    return StructuralGraphQueryResult(
        query_id=request.query_id,
        mode=request.mode,
        rows=rows,
        planner=planner,
        omitted=list(community_result.omitted),
        communities=list(community_result.communities),
        source_sets=list(community_result.source_sets),
    )


def _pattern_planner(
    request: StructuralGraphQueryRequest,
    result: GraphPatternQueryResult,
) -> list[StructuralGraphPlannerStage]:
    stages = [
        StructuralGraphPlannerStage(
            stage="mode",
            input_count=1,
            output_count=1,
            details={"mode": request.mode},
        )
    ]
    if request.seed_record_ids:
        stages.append(
            StructuralGraphPlannerStage(
                stage="seed_filter",
                input_count=len(request.seed_record_ids),
                output_count=len(request.seed_record_ids),
                details={"seed_record_ids": list(request.seed_record_ids)},
            )
        )
    pattern_details = {}
    if result.query_plan is not None:
        pattern_details["stages"] = [
            asdict(stage) for stage in result.query_plan.stages
        ]
    stages.append(
        StructuralGraphPlannerStage(
            stage="pattern_execute",
            input_count=len(request.seed_record_ids or []),
            output_count=len(result.matches),
            details=pattern_details,
        )
    )
    return stages


def _global_planner(
    request: StructuralGraphQueryRequest,
    result: CommunityQueryResult,
) -> list[StructuralGraphPlannerStage]:
    stages = [
        StructuralGraphPlannerStage(
            stage="mode",
            input_count=1,
            output_count=1,
            details={"mode": request.mode},
        ),
        StructuralGraphPlannerStage(
            stage="community_detect",
            input_count=len(request.scopes),
            output_count=len(result.communities),
            details={"algorithm": request.community_algorithm},
        ),
    ]
    if result.query_plan is not None:
        details = {"stages": [asdict(stage) for stage in result.query_plan.stages]}
        stages.append(
            StructuralGraphPlannerStage(
                stage="community_query",
                input_count=len(result.communities),
                output_count=len(result.hits),
                details=details,
            )
        )
    if result.omitted:
        stages.append(
            StructuralGraphPlannerStage(
                stage="result_limit",
                input_count=len(result.communities),
                output_count=len(result.communities),
                details={
                    "omitted": [asdict(item) for item in result.omitted],
                    "limit": request.limit,
                },
            )
        )
    return stages


def _pattern_match_to_row(
    query_id: str,
    index: int,
    match: GraphPatternMatch,
) -> StructuralGraphQueryRow:
    path = GraphPath(record_ids=match.record_ids, edge_ids=match.edge_ids)
    return StructuralGraphQueryRow(
        row_id=f"{query_id}:row:{index}",
        node_ids=list(match.record_ids),
        edge_ids=list(match.edge_ids),
        community_ids=list(match.community_ids),
        properties=dict(match.properties),
        path=path,
    )


def _community_to_row(
    query_id: str,
    index: int,
    community: GraphCommunity,
    source_sets: list[CommunitySourceSet],
    namespaces: list[MemoryNamespace] | None,
) -> StructuralGraphQueryRow:
    community_source_sets = [
        source_set
        for source_set in source_sets
        if source_set.community_id == community.community_id
    ]
    return StructuralGraphQueryRow(
        row_id=f"{query_id}:row:{index}",
        node_ids=list(community.record_ids),
        edge_ids=list(community.edge_ids),
        community_ids=[community.community_id],
        source_set_ids=[
            source_set.source_set_id for source_set in community_source_sets
        ],
        namespace_keys=_namespace_keys(namespaces or [community.namespace]),
        properties={
            "algorithm": community.algorithm,
            "score": community.score,
            "record_count": len(community.record_ids),
            "source_set_count": len(community_source_sets),
        },
    )


def _namespace_keys(namespaces: list[MemoryNamespace]) -> list[str]:
    keys = []
    for namespace in namespaces:
        key = "|".join(
            f"{field}={value}" for field, value in sorted(namespace.as_dict().items())
        )
        if key and key not in keys:
            keys.append(key)
    return keys


__all__ = [
    "execute_structural_graph_query",
    "structural_graph_query_to_backend_query",
]
