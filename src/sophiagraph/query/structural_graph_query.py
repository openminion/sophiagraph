"""Higher-level structural graph query envelopes and deterministic planners."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Protocol

from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.graph_backends import GraphBackendQuery
from sophiagraph.models import MemoryNamespace
from sophiagraph.query.algorithms import GraphPath
from sophiagraph.query.community import (
    CommunityAlgorithm,
    CommunityDetectionOptions,
    CommunityOmittedDiagnostic,
    CommunityQueryOptions,
    CommunitySourceSet,
    CommunityStore,
    CommunityQueryResult,
    GraphCommunity,
    GraphPatternMatch,
    GraphPatternNodePredicate,
    GraphPatternQuery,
    GraphPatternQueryResult,
    PatternDirection,
    execute_graph_pattern_query,
    pattern_query_to_backend_payload,
    query_communities,
)
from sophiagraph.query.explorer import (
    KnowledgeQueryPlan,
    KnowledgeQueryPlanStage,
)

StructuralGraphQueryMode = Literal["pattern", "global"]
StructuralGraphPlannerStageName = Literal[
    "mode",
    "seed_filter",
    "pattern_execute",
    "community_detect",
    "community_query",
    "result_limit",
]

_QUERY_MODES: frozenset[str] = frozenset({"pattern", "global"})
_PLANNER_STAGES: frozenset[str] = frozenset(
    {
        "mode",
        "seed_filter",
        "pattern_execute",
        "community_detect",
        "community_query",
        "result_limit",
    }
)


class StructuralGraphQueryStore(CommunityStore, Protocol):
    """Store protocol reused by structural graph query execution."""


@dataclass(frozen=True, slots=True)
class StructuralGraphQueryRequest:
    """Bounded structural graph query request for pattern or global execution."""

    query_id: str
    mode: StructuralGraphQueryMode
    scopes: list[str]
    namespaces: list[MemoryNamespace] | None = None
    seed_record_ids: list[str] | None = None
    node_predicates: list[GraphPatternNodePredicate] = field(default_factory=list)
    relation_types: list[str] | None = None
    direction: PatternDirection = "both"
    min_hops: int = 1
    max_hops: int = 2
    limit: int = 20
    community_algorithm: CommunityAlgorithm = "connected_components"
    community_ids: list[str] | None = None
    include_records: bool = True
    include_paths: bool = True
    node_labels: list[str] | None = None
    property_filters: dict[str, Any] = field(default_factory=dict)
    as_of: str | None = None
    valid_at: str | None = None

    def __post_init__(self) -> None:
        if not self.query_id:
            raise InvalidArgumentError("query_id is required")
        if self.mode not in _QUERY_MODES:
            raise InvalidArgumentError(f"invalid structural query mode: {self.mode!r}")
        if not self.scopes:
            raise InvalidArgumentError("structural graph query requires scopes")
        if self.direction not in {"out", "in", "both"}:
            raise InvalidArgumentError(f"invalid direction: {self.direction!r}")
        if self.min_hops < 0 or self.max_hops <= 0 or self.max_hops < self.min_hops:
            raise InvalidArgumentError("invalid hop bounds")
        if self.limit <= 0:
            raise InvalidArgumentError("limit must be positive")
        if self.community_algorithm not in {
            "connected_components",
            "label_propagation",
        }:
            raise InvalidArgumentError(
                f"invalid community_algorithm: {self.community_algorithm!r}"
            )
        if self.node_labels is not None and any(
            not label for label in self.node_labels
        ):
            raise InvalidArgumentError("node_labels cannot contain empty values")


@dataclass(frozen=True, slots=True)
class StructuralGraphPlannerStage:
    """Deterministic evidence for one structural graph query stage."""

    stage: StructuralGraphPlannerStageName
    input_count: int
    output_count: int
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.stage not in _PLANNER_STAGES:
            raise InvalidArgumentError(f"invalid planner stage: {self.stage!r}")
        if self.input_count < 0 or self.output_count < 0:
            raise InvalidArgumentError("planner stage counts must be non-negative")


@dataclass(frozen=True, slots=True)
class StructuralGraphQueryRow:
    """Normalized structural graph query row with only explicit identifiers."""

    row_id: str
    node_ids: list[str] = field(default_factory=list)
    edge_ids: list[str] = field(default_factory=list)
    community_ids: list[str] = field(default_factory=list)
    source_set_ids: list[str] = field(default_factory=list)
    namespace_keys: list[str] = field(default_factory=list)
    properties: dict[str, Any] = field(default_factory=dict)
    path: GraphPath | None = None

    def __post_init__(self) -> None:
        if not self.row_id:
            raise InvalidArgumentError("row_id is required")
        if not (self.node_ids or self.edge_ids or self.community_ids):
            raise InvalidArgumentError(
                "structural graph query rows require nodes, edges, or communities"
            )


@dataclass(frozen=True, slots=True)
class StructuralGraphQueryResult:
    """Normalized structural graph query result with planner evidence."""

    query_id: str
    mode: StructuralGraphQueryMode
    rows: list[StructuralGraphQueryRow] = field(default_factory=list)
    planner: list[StructuralGraphPlannerStage] = field(default_factory=list)
    omitted: list[CommunityOmittedDiagnostic] = field(default_factory=list)
    communities: list[GraphCommunity] = field(default_factory=list)
    source_sets: list[CommunitySourceSet] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.query_id:
            raise InvalidArgumentError("query_id is required")
        if self.mode not in _QUERY_MODES:
            raise InvalidArgumentError(f"invalid structural query mode: {self.mode!r}")


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


def structural_result_to_knowledge_plan(
    result: StructuralGraphQueryResult,
) -> KnowledgeQueryPlan:
    """Convert structural planner stages into the explorer knowledge-plan DTO."""
    return KnowledgeQueryPlan(
        stages=[
            KnowledgeQueryPlanStage(
                stage=_planner_stage_to_query_plan_stage(stage.stage),
                input_count=stage.input_count,
                output_count=stage.output_count,
                details=dict(stage.details),
            )
            for stage in result.planner
        ]
    )


def structural_graph_query_request_to_dict(
    request: StructuralGraphQueryRequest,
) -> dict[str, Any]:
    """Serialize a structural graph query request with explicit namespaces."""
    payload = asdict(request)
    payload["namespaces"] = [
        namespace.as_dict() for namespace in request.namespaces or []
    ]
    payload["node_predicates"] = [
        asdict(predicate) for predicate in request.node_predicates
    ]
    return payload


def structural_graph_query_request_from_dict(
    data: dict[str, Any],
) -> StructuralGraphQueryRequest:
    """Hydrate a structural graph query request from plain dict data."""
    payload = dict(data)
    payload["namespaces"] = [
        MemoryNamespace.from_dict(namespace)
        if isinstance(namespace, dict)
        else namespace
        for namespace in payload.get("namespaces") or []
    ] or None
    payload["node_predicates"] = [
        GraphPatternNodePredicate(**predicate)
        if isinstance(predicate, dict)
        else predicate
        for predicate in payload.get("node_predicates", [])
    ]
    return StructuralGraphQueryRequest(**payload)


def structural_graph_query_result_to_dict(
    result: StructuralGraphQueryResult,
) -> dict[str, Any]:
    """Serialize a structural graph query result to plain dict data."""
    return {
        "query_id": result.query_id,
        "mode": result.mode,
        "rows": [
            {
                "row_id": row.row_id,
                "node_ids": list(row.node_ids),
                "edge_ids": list(row.edge_ids),
                "community_ids": list(row.community_ids),
                "source_set_ids": list(row.source_set_ids),
                "namespace_keys": list(row.namespace_keys),
                "properties": dict(row.properties),
                "path": asdict(row.path) if row.path is not None else None,
            }
            for row in result.rows
        ],
        "planner": [asdict(stage) for stage in result.planner],
        "omitted": [asdict(item) for item in result.omitted],
        "communities": [
            {
                **asdict(community),
                "namespace": community.namespace.as_dict(),
            }
            for community in result.communities
        ],
        "source_sets": [asdict(source_set) for source_set in result.source_sets],
    }


def structural_graph_query_result_from_dict(
    data: dict[str, Any],
) -> StructuralGraphQueryResult:
    """Hydrate a structural graph query result from plain dict data."""
    payload = dict(data)
    rows = []
    for row in payload.get("rows", []):
        path_payload = row.get("path")
        rows.append(
            StructuralGraphQueryRow(
                row_id=row["row_id"],
                node_ids=list(row.get("node_ids", [])),
                edge_ids=list(row.get("edge_ids", [])),
                community_ids=list(row.get("community_ids", [])),
                source_set_ids=list(row.get("source_set_ids", [])),
                namespace_keys=list(row.get("namespace_keys", [])),
                properties=dict(row.get("properties", {})),
                path=GraphPath(**path_payload)
                if isinstance(path_payload, dict)
                else None,
            )
        )
    planner = [
        StructuralGraphPlannerStage(**stage) for stage in payload.get("planner", [])
    ]
    omitted = [
        CommunityOmittedDiagnostic(**item) for item in payload.get("omitted", [])
    ]
    communities = []
    for community in payload.get("communities", []):
        community_payload = dict(community)
        if isinstance(community_payload.get("namespace"), dict):
            community_payload["namespace"] = MemoryNamespace.from_dict(
                community_payload["namespace"]
            )
        communities.append(GraphCommunity(**community_payload))
    source_sets = [
        CommunitySourceSet(**source_set)
        for source_set in payload.get("source_sets", [])
    ]
    return StructuralGraphQueryResult(
        query_id=payload["query_id"],
        mode=payload["mode"],
        rows=rows,
        planner=planner,
        omitted=omitted,
        communities=communities,
        source_sets=source_sets,
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
        output_count = len(result.hits)
        stages.append(
            StructuralGraphPlannerStage(
                stage="community_query",
                input_count=len(result.communities),
                output_count=output_count,
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


def _planner_stage_to_query_plan_stage(
    stage: StructuralGraphPlannerStageName,
) -> str:
    mapping = {
        "mode": "filters",
        "seed_filter": "filters",
        "pattern_execute": "graph",
        "community_detect": "communities",
        "community_query": "graph",
        "result_limit": "filters",
    }
    return mapping[stage]


__all__ = [
    "StructuralGraphPlannerStage",
    "StructuralGraphPlannerStageName",
    "StructuralGraphQueryMode",
    "StructuralGraphQueryRequest",
    "StructuralGraphQueryResult",
    "StructuralGraphQueryRow",
    "execute_structural_graph_query",
    "structural_graph_query_request_from_dict",
    "structural_graph_query_request_to_dict",
    "structural_graph_query_result_from_dict",
    "structural_graph_query_result_to_dict",
    "structural_graph_query_to_backend_query",
    "structural_result_to_knowledge_plan",
]
