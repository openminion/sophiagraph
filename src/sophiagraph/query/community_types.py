"""Public structural community and pattern-query types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.models import MemoryNamespace, MemoryRecord, SophiaGraphChangeEvent
from sophiagraph.query.algorithms import GraphPath
from sophiagraph.query.graph import GraphSnapshot, GraphSnapshotOptions
from sophiagraph.query.options import ListQueryOptions, SearchQueryOptions
from sophiagraph.temporal import utc_now_iso

CommunityAlgorithm = Literal["connected_components", "label_propagation"]
CommunityLayoutKind = Literal["community_band", "degree_weight"]
PatternOperator = Literal["eq", "ne", "contains", "in", "exists"]
PatternDirection = Literal["out", "in", "both"]
PatternProjection = Literal["record_ids", "edge_ids", "community_ids", "properties"]
OmittedReason = Literal["community_limit", "hit_limit", "query_filter"]

COMMUNITY_ALGORITHMS = frozenset({"connected_components", "label_propagation"})
PATTERN_OPERATORS = frozenset({"eq", "ne", "contains", "in", "exists"})
PATTERN_DIRECTIONS = frozenset({"out", "in", "both"})
PATTERN_PROJECTIONS = frozenset(
    {"record_ids", "edge_ids", "community_ids", "properties"}
)


@dataclass(frozen=True, slots=True)
class GraphCommunity:
    community_id: str
    namespace: MemoryNamespace
    record_ids: list[str]
    edge_ids: list[str] = field(default_factory=list)
    seed_record_id: str | None = None
    algorithm: CommunityAlgorithm = "connected_components"
    score: float = 0.0
    created_at: str = field(default_factory=utc_now_iso)
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.community_id:
            raise InvalidArgumentError("community_id is required")
        if not isinstance(self.namespace, MemoryNamespace):
            raise TypeError("namespace must be MemoryNamespace")
        if not self.record_ids:
            raise InvalidArgumentError("community requires record_ids")
        if self.algorithm not in COMMUNITY_ALGORITHMS:
            raise InvalidArgumentError(f"invalid algorithm: {self.algorithm!r}")
        if self.score < 0:
            raise InvalidArgumentError("community score must be non-negative")
        if (
            self.seed_record_id is not None
            and self.seed_record_id not in self.record_ids
        ):
            raise InvalidArgumentError("seed_record_id must be inside record_ids")


@dataclass(frozen=True, slots=True)
class GraphCommunityMembership:
    record_id: str
    community_id: str
    rank: int
    degree_in_community: int
    evidence_edge_ids: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.record_id:
            raise InvalidArgumentError("record_id is required")
        if not self.community_id:
            raise InvalidArgumentError("community_id is required")
        if self.rank <= 0:
            raise InvalidArgumentError("rank must be positive")
        if self.degree_in_community < 0:
            raise InvalidArgumentError("degree_in_community must be non-negative")


@dataclass(frozen=True, slots=True)
class CommunityDetectionOptions:
    scopes: list[str]
    namespaces: list[MemoryNamespace] | None = None
    algorithm: CommunityAlgorithm = "connected_components"
    min_size: int = 1
    max_communities: int | None = None
    relation_types: list[str] | None = None
    as_of: str | None = None
    valid_at: str | None = None

    def __post_init__(self) -> None:
        if not self.scopes:
            raise InvalidArgumentError("community detection requires scopes")
        if self.algorithm not in COMMUNITY_ALGORITHMS:
            raise InvalidArgumentError(f"invalid algorithm: {self.algorithm!r}")
        if self.min_size <= 0:
            raise InvalidArgumentError("min_size must be positive")
        if self.max_communities is not None and self.max_communities <= 0:
            raise InvalidArgumentError("max_communities must be positive")


@dataclass(frozen=True, slots=True)
class CommunitySnapshot:
    snapshot_id: str
    algorithm: CommunityAlgorithm
    scopes: list[str]
    namespaces: list[MemoryNamespace] | None
    latest_cursor: int | None
    computed_at: str
    communities: list[GraphCommunity]
    memberships: list[GraphCommunityMembership]

    def __post_init__(self) -> None:
        if not self.snapshot_id:
            raise InvalidArgumentError("snapshot_id is required")
        if self.algorithm not in COMMUNITY_ALGORITHMS:
            raise InvalidArgumentError(f"invalid algorithm: {self.algorithm!r}")
        if not self.scopes:
            raise InvalidArgumentError("snapshot requires scopes")
        if not self.computed_at:
            raise InvalidArgumentError("computed_at is required")


@dataclass(frozen=True, slots=True)
class CommunitySnapshotStatus:
    snapshot_id: str
    stale: bool
    latest_cursor: int | None = None
    stale_reasons: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.snapshot_id:
            raise InvalidArgumentError("snapshot_id is required")


@dataclass(frozen=True, slots=True)
class CommunitySourceSet:
    source_set_id: str
    community_id: str
    source_key: str
    count: int
    record_ids: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.source_set_id:
            raise InvalidArgumentError("source_set_id is required")
        if not self.community_id:
            raise InvalidArgumentError("community_id is required")
        if not self.source_key:
            raise InvalidArgumentError("source_key is required")
        if self.count < 0:
            raise InvalidArgumentError("count must be non-negative")


@dataclass(frozen=True, slots=True)
class CommunityQueryHit:
    record: MemoryRecord
    community_id: str
    score: float = 0.0
    source_set_ids: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.community_id:
            raise InvalidArgumentError("community_id is required")
        if self.score < 0:
            raise InvalidArgumentError("score must be non-negative")

    @property
    def record_id(self) -> str:
        return self.record.id


@dataclass(frozen=True, slots=True)
class CommunityOmittedDiagnostic:
    reason: OmittedReason
    count: int
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.reason not in {"community_limit", "hit_limit", "query_filter"}:
            raise InvalidArgumentError(f"invalid omitted reason: {self.reason!r}")
        if self.count < 0:
            raise InvalidArgumentError("count must be non-negative")


@dataclass(frozen=True, slots=True)
class CommunityQueryPlanStage:
    stage: str
    input_count: int
    output_count: int
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.stage:
            raise InvalidArgumentError("stage is required")
        if self.input_count < 0 or self.output_count < 0:
            raise InvalidArgumentError("plan counts must be non-negative")


@dataclass(frozen=True, slots=True)
class CommunityQueryPlan:
    stages: list[CommunityQueryPlanStage] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class CommunityQueryOptions:
    detection: CommunityDetectionOptions
    community_ids: list[str] | None = None
    query: str | None = None
    include_records: bool = True
    include_paths: bool = True
    include_summary_refs: bool = False
    summary_reference_ids: list[str] = field(default_factory=list)
    limit: int = 20

    def __post_init__(self) -> None:
        if self.limit <= 0:
            raise InvalidArgumentError("limit must be positive")


@dataclass(frozen=True, slots=True)
class CommunityQueryResult:
    communities: list[GraphCommunity]
    memberships: list[GraphCommunityMembership]
    hits: list[CommunityQueryHit]
    source_sets: list[CommunitySourceSet] = field(default_factory=list)
    paths: list[GraphPath] = field(default_factory=list)
    omitted: list[CommunityOmittedDiagnostic] = field(default_factory=list)
    query_plan: CommunityQueryPlan | None = None
    summary_reference_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class GraphLayoutHint:
    record_id: str
    community_id: str | None = None
    layout_kind: CommunityLayoutKind = "community_band"
    suggested_weight: float = 1.0
    suggested_radius: float = 1.0
    edge_weight: int = 0

    def __post_init__(self) -> None:
        if not self.record_id:
            raise InvalidArgumentError("record_id is required")
        if self.layout_kind not in {"community_band", "degree_weight"}:
            raise InvalidArgumentError(f"invalid layout_kind: {self.layout_kind!r}")
        if self.suggested_weight < 0 or self.suggested_radius < 0:
            raise InvalidArgumentError("layout weights must be non-negative")
        if self.edge_weight < 0:
            raise InvalidArgumentError("edge_weight must be non-negative")


@dataclass(frozen=True, slots=True)
class GraphPatternNodePredicate:
    field: str
    operator: PatternOperator = "eq"
    value: Any = None

    def __post_init__(self) -> None:
        if not self.field:
            raise InvalidArgumentError("field is required")
        if self.operator not in PATTERN_OPERATORS:
            raise InvalidArgumentError(f"invalid operator: {self.operator!r}")


@dataclass(frozen=True, slots=True)
class GraphPatternQuery:
    query_id: str
    scopes: list[str]
    namespaces: list[MemoryNamespace] | None = None
    seed_record_ids: list[str] | None = None
    node_predicates: list[GraphPatternNodePredicate] = field(default_factory=list)
    relation_types: list[str] | None = None
    direction: PatternDirection = "both"
    min_hops: int = 1
    max_hops: int = 2
    limit: int = 50
    project: list[PatternProjection] = field(
        default_factory=lambda: [
            "record_ids",
            "edge_ids",
            "community_ids",
            "properties",
        ]
    )
    as_of: str | None = None
    valid_at: str | None = None

    def __post_init__(self) -> None:
        if not self.query_id:
            raise InvalidArgumentError("query_id is required")
        if not self.scopes:
            raise InvalidArgumentError("pattern query requires scopes")
        if self.direction not in PATTERN_DIRECTIONS:
            raise InvalidArgumentError(f"invalid direction: {self.direction!r}")
        if self.min_hops < 0 or self.max_hops <= 0 or self.max_hops < self.min_hops:
            raise InvalidArgumentError("invalid hop bounds")
        if self.limit <= 0:
            raise InvalidArgumentError("limit must be positive")
        for projection in self.project:
            if projection not in PATTERN_PROJECTIONS:
                raise InvalidArgumentError(f"invalid project field: {projection!r}")


@dataclass(frozen=True, slots=True)
class GraphPatternMatch:
    record_ids: list[str]
    edge_ids: list[str]
    community_ids: list[str] = field(default_factory=list)
    properties: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.record_ids:
            raise InvalidArgumentError("pattern match requires record_ids")


@dataclass(frozen=True, slots=True)
class GraphPatternQueryResult:
    query_id: str
    matches: list[GraphPatternMatch]
    query_plan: CommunityQueryPlan | None = None

    def __post_init__(self) -> None:
        if not self.query_id:
            raise InvalidArgumentError("query_id is required")


class CommunityStore(Protocol):
    def get_graph_snapshot(self, options: GraphSnapshotOptions) -> GraphSnapshot: ...

    def list_records(self, options: ListQueryOptions) -> list[MemoryRecord]: ...

    def search_records(self, options: SearchQueryOptions) -> list[MemoryRecord]: ...

    def list_changes(
        self,
        *,
        since_cursor: int | None = None,
        limit: int | None = None,
        namespaces: list[MemoryNamespace] | None = None,
    ) -> list[SophiaGraphChangeEvent]: ...


__all__ = [
    "COMMUNITY_ALGORITHMS",
    "CommunityAlgorithm",
    "CommunityDetectionOptions",
    "CommunityLayoutKind",
    "CommunityOmittedDiagnostic",
    "CommunityQueryHit",
    "CommunityQueryOptions",
    "CommunityQueryPlan",
    "CommunityQueryPlanStage",
    "CommunityQueryResult",
    "CommunitySnapshot",
    "CommunitySnapshotStatus",
    "CommunitySourceSet",
    "CommunityStore",
    "GraphCommunity",
    "GraphCommunityMembership",
    "GraphLayoutHint",
    "GraphPatternMatch",
    "GraphPatternNodePredicate",
    "GraphPatternQuery",
    "GraphPatternQueryResult",
    "OmittedReason",
    "PATTERN_DIRECTIONS",
    "PATTERN_OPERATORS",
    "PATTERN_PROJECTIONS",
    "PatternDirection",
    "PatternOperator",
    "PatternProjection",
]
