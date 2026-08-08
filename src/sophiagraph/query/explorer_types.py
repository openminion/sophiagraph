"""Public structural explorer packet types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.models import MemoryNamespace, MemoryRecord, StructuralLink
from sophiagraph.models.document import KnowledgeDocumentBlock
from sophiagraph.query.algorithms import GraphCommonNeighbors, GraphPath
from sophiagraph.query.community import (
    CommunitySourceSet,
    GraphCommunity,
    GraphLayoutHint,
)
from sophiagraph.query.graph import (
    GraphSnapshot,
    GraphSnapshotOptions,
    LinkQueryOptions,
    LocalGraphOptions,
)
from sophiagraph.query.options import ListQueryOptions, SearchQueryOptions

FacetField = Literal[
    "scope",
    "type",
    "tier",
    "source",
    "tag",
    "community",
    "relation_type",
    "link_kind",
    "orphan",
]
NavigationActionKind = Literal[
    "open_root",
    "open_hit",
    "follow_backlink",
    "follow_outgoing_link",
    "inspect_path",
    "open_common_neighbor",
    "open_orphan",
    "open_community",
    "filter_community",
    "apply_repair_candidate",
]
MentionMatchKind = Literal["title", "alias", "path", "heading", "block_id"]
QueryPlanStageName = Literal[
    "records",
    "search",
    "filters",
    "graph",
    "backlinks",
    "outgoing_links",
    "paths",
    "communities",
    "facets",
    "unlinked_mentions",
]


class KnowledgeExplorerStore(Protocol):
    def list_records(self, options: ListQueryOptions) -> list[MemoryRecord]: ...

    def search_records(self, options: SearchQueryOptions) -> list[MemoryRecord]: ...

    def get_record(self, record_id: str) -> MemoryRecord | None: ...

    def list_links(self, options: LinkQueryOptions) -> list[StructuralLink]: ...

    def get_local_graph(self, options: LocalGraphOptions) -> GraphSnapshot: ...

    def get_graph_snapshot(self, options: GraphSnapshotOptions) -> GraphSnapshot: ...

    def list_document_blocks(
        self,
        *,
        record_id: str | None = None,
        document_id: str | None = None,
        block_id: str | None = None,
    ) -> list[KnowledgeDocumentBlock]: ...


@dataclass(frozen=True, slots=True)
class KnowledgeExplorerFilters:
    """Stored-field filters for explorer packets."""

    types: list[str] | None = None
    tiers: list[str] | None = None
    sources: list[str] | None = None
    tags: list[str] | None = None
    properties: dict[str, Any] = field(default_factory=dict)
    relation_types: list[str] | None = None
    link_kinds: list[str] | None = None
    include_orphans: bool = True

    def __post_init__(self) -> None:
        for name, values in (
            ("types", self.types),
            ("tiers", self.tiers),
            ("sources", self.sources),
            ("tags", self.tags),
            ("relation_types", self.relation_types),
            ("link_kinds", self.link_kinds),
        ):
            if values is not None and any(not str(value) for value in values):
                raise InvalidArgumentError(f"{name} cannot contain empty values")


@dataclass(frozen=True, slots=True)
class KnowledgeContextExcerpt:
    """Bounded structural context around an explicit link or mention."""

    record_id: str
    text: str
    source_path: str | None = None
    link_id: str | None = None
    block_id: str | None = None
    heading: str | None = None
    char_budget: int = 160

    def __post_init__(self) -> None:
        if not self.record_id:
            raise InvalidArgumentError("record_id is required")
        if self.char_budget < 0:
            raise InvalidArgumentError("char_budget must be non-negative")
        if len(self.text) > self.char_budget:
            raise InvalidArgumentError("excerpt text exceeds char_budget")


@dataclass(frozen=True, slots=True)
class KnowledgeHit:
    """One owned-knowledge hit with mechanical match evidence."""

    record_id: str
    title: str | None
    record_type: str
    score: float
    matched_fields: list[str] = field(default_factory=list)
    score_components: dict[str, float] = field(default_factory=dict)
    context: KnowledgeContextExcerpt | None = None

    def __post_init__(self) -> None:
        if not self.record_id:
            raise InvalidArgumentError("record_id is required")
        if not self.record_type:
            raise InvalidArgumentError("record_type is required")
        if self.score < 0:
            raise InvalidArgumentError("score must be non-negative")


@dataclass(frozen=True, slots=True)
class KnowledgeFacet:
    """Facet count over explicit stored fields."""

    field: FacetField
    value: str
    count: int

    def __post_init__(self) -> None:
        if not self.value:
            raise InvalidArgumentError("facet value is required")
        if self.count < 0:
            raise InvalidArgumentError("facet count must be non-negative")


@dataclass(frozen=True, slots=True)
class UnlinkedMentionCandidate:
    """Structural mention candidate that is never persisted as an edge."""

    candidate_id: str
    source_record_id: str
    target_record_id: str
    matched_text: str
    match_kind: MentionMatchKind
    context: KnowledgeContextExcerpt | None = None

    def __post_init__(self) -> None:
        if not self.candidate_id:
            raise InvalidArgumentError("candidate_id is required")
        if not self.source_record_id:
            raise InvalidArgumentError("source_record_id is required")
        if not self.target_record_id:
            raise InvalidArgumentError("target_record_id is required")
        if self.source_record_id == self.target_record_id:
            raise InvalidArgumentError("mention candidate cannot target itself")
        if not self.matched_text:
            raise InvalidArgumentError("matched_text is required")


@dataclass(frozen=True, slots=True)
class KnowledgeNavigationAction:
    """Typed action a caller may present without executing mutations."""

    action: NavigationActionKind
    record_id: str | None = None
    link_id: str | None = None
    path: GraphPath | None = None
    candidate_id: str | None = None
    label: str | None = None

    def __post_init__(self) -> None:
        if (
            self.action
            in {
                "open_root",
                "open_hit",
                "open_common_neighbor",
                "open_orphan",
            }
            and not self.record_id
        ):
            raise InvalidArgumentError(f"{self.action} requires record_id")
        if self.action in {"follow_backlink", "follow_outgoing_link"} and not (
            self.link_id and self.record_id
        ):
            raise InvalidArgumentError(f"{self.action} requires record_id and link_id")
        if self.action == "inspect_path" and self.path is None:
            raise InvalidArgumentError("inspect_path requires path")
        if self.action == "apply_repair_candidate" and not self.candidate_id:
            raise InvalidArgumentError("apply_repair_candidate requires candidate_id")


@dataclass(frozen=True, slots=True)
class KnowledgeQueryPlanStage:
    """Mechanical evidence for one explorer stage."""

    stage: QueryPlanStageName
    input_count: int
    output_count: int
    elapsed_ms: float = 0.0
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.input_count < 0 or self.output_count < 0:
            raise InvalidArgumentError("stage counts must be non-negative")
        if self.elapsed_ms < 0:
            raise InvalidArgumentError("elapsed_ms must be non-negative")


@dataclass(frozen=True, slots=True)
class KnowledgeQueryPlan:
    stages: list[KnowledgeQueryPlanStage] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class KnowledgeExplorerRequest:
    """One structural graph/search navigation request."""

    scopes: list[str]
    namespaces: list[MemoryNamespace] | None = None
    query: str | None = None
    root_record_id: str | None = None
    filters: KnowledgeExplorerFilters = field(default_factory=KnowledgeExplorerFilters)
    include_graph: bool = True
    include_backlinks: bool = True
    include_outgoing_links: bool = True
    include_unlinked_mentions: bool = False
    include_paths: bool = True
    include_facets: bool = True
    include_communities: bool = False
    include_query_plan: bool = True
    depth: int = 1
    limit: int = 20
    context_chars: int = 160
    cursor: str | None = None
    as_of: str | None = None
    valid_at: str | None = None
    effective_during: tuple[str, str] | None = None
    believed_at: str | None = None

    def __post_init__(self) -> None:
        if not self.scopes:
            raise InvalidArgumentError("explorer request requires at least one scope")
        if self.limit <= 0:
            raise InvalidArgumentError("limit must be positive")
        if self.depth < 0:
            raise InvalidArgumentError("depth must be non-negative")
        if self.context_chars < 0:
            raise InvalidArgumentError("context_chars must be non-negative")


@dataclass(frozen=True, slots=True)
class KnowledgeExplorerResult:
    """One graph/search explorer packet."""

    hits: list[KnowledgeHit]
    graph: GraphSnapshot | None = None
    backlinks: list[StructuralLink] = field(default_factory=list)
    outgoing_links: list[StructuralLink] = field(default_factory=list)
    unlinked_mentions: list[UnlinkedMentionCandidate] = field(default_factory=list)
    paths: list[GraphPath] = field(default_factory=list)
    common_neighbors: list[GraphCommonNeighbors] = field(default_factory=list)
    communities: list[GraphCommunity] = field(default_factory=list)
    source_sets: list[CommunitySourceSet] = field(default_factory=list)
    layout_hints: list[GraphLayoutHint] = field(default_factory=list)
    facets: list[KnowledgeFacet] = field(default_factory=list)
    navigation: list[KnowledgeNavigationAction] = field(default_factory=list)
    query_plan: KnowledgeQueryPlan | None = None
    warnings: list[str] = field(default_factory=list)
    next_cursor: str | None = None


@dataclass(frozen=True, slots=True)
class SavedExplorerView:
    """Repeatable explorer request with a stable view identity."""

    view_id: str
    name: str
    request: KnowledgeExplorerRequest

    def __post_init__(self) -> None:
        if not self.view_id:
            raise InvalidArgumentError("view_id is required")
        if not self.name:
            raise InvalidArgumentError("name is required")


__all__ = [
    "FacetField",
    "KnowledgeContextExcerpt",
    "KnowledgeExplorerFilters",
    "KnowledgeExplorerRequest",
    "KnowledgeExplorerResult",
    "KnowledgeExplorerStore",
    "KnowledgeFacet",
    "KnowledgeHit",
    "KnowledgeNavigationAction",
    "KnowledgeQueryPlan",
    "KnowledgeQueryPlanStage",
    "MentionMatchKind",
    "NavigationActionKind",
    "QueryPlanStageName",
    "SavedExplorerView",
    "UnlinkedMentionCandidate",
]
