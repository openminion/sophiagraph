"""Graph/search explorer packets for owned-knowledge navigation."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any, Literal, Protocol
from uuid import NAMESPACE_URL, uuid5

from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.models import MemoryNamespace, MemoryRecord, StructuralLink
from sophiagraph.models.document import KnowledgeDocumentBlock
from sophiagraph.query.algorithms import (
    GraphCommonNeighbors,
    GraphPath,
    common_neighbors,
    shortest_path,
)
from sophiagraph.query.community import (
    CommunityDetectionOptions,
    CommunitySourceSet,
    GraphCommunity,
    GraphLayoutHint,
    detect_communities,
    layout_hints_for_snapshot,
    query_communities,
    CommunityQueryOptions,
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
        if self.cursor is not None:
            raise InvalidArgumentError("cursor pagination is not implemented yet")


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


def explore_knowledge(
    store: KnowledgeExplorerStore,
    request: KnowledgeExplorerRequest,
) -> KnowledgeExplorerResult:
    """Build one structural explorer packet from existing store APIs."""
    plan: list[KnowledgeQueryPlanStage] = []
    started = perf_counter()
    records = _load_records(store, request)
    plan.append(
        _stage(
            "search" if request.query else "records",
            0,
            len(records),
            started,
            {"query": request.query or "", "limit": request.limit},
        )
    )

    started = perf_counter()
    filtered = _filter_records(records, request.filters)
    filtered = _filter_orphans(store, filtered, request)
    plan.append(
        _stage(
            "filters",
            len(records),
            min(len(filtered), request.limit),
            started,
            _filter_details(request.filters),
        )
    )
    filtered = filtered[: request.limit]

    hits = [
        _hit_for_record(record, request.query or "", request.context_chars)
        for record in filtered
    ]
    root_record_id = request.root_record_id or (hits[0].record_id if hits else None)

    graph: GraphSnapshot | None = None
    if request.include_graph and root_record_id is not None:
        started = perf_counter()
        try:
            graph = store.get_local_graph(
                LocalGraphOptions(
                    record_id=root_record_id,
                    depth=request.depth,
                    relation_types=request.filters.relation_types,
                    namespaces=request.namespaces,
                )
            )
        except Exception as exc:  # allow-bare-raise: boundary records warning
            graph = None
            graph_warning = f"graph unavailable: {type(exc).__name__}"
        else:
            graph_warning = ""
        plan.append(
            _stage(
                "graph",
                len(filtered),
                len(graph.nodes) if graph else 0,
                started,
                {"root_record_id": root_record_id, "depth": request.depth},
            )
        )
    else:
        graph_warning = ""

    backlinks: list[StructuralLink] = []
    if request.include_backlinks and root_record_id is not None:
        started = perf_counter()
        backlinks = _filter_links(
            store.list_links(
                LinkQueryOptions(
                    record_id=root_record_id,
                    direction="in",
                    relation_types=request.filters.relation_types,
                    namespaces=request.namespaces,
                    context_chars=request.context_chars,
                    limit=request.limit,
                )
            ),
            request.filters,
        )
        plan.append(_stage("backlinks", 0, len(backlinks), started, {}))

    outgoing_links: list[StructuralLink] = []
    if request.include_outgoing_links and root_record_id is not None:
        started = perf_counter()
        outgoing_links = _filter_links(
            store.list_links(
                LinkQueryOptions(
                    record_id=root_record_id,
                    direction="out",
                    relation_types=request.filters.relation_types,
                    namespaces=request.namespaces,
                    context_chars=request.context_chars,
                    limit=request.limit,
                )
            ),
            request.filters,
        )
        plan.append(_stage("outgoing_links", 0, len(outgoing_links), started, {}))

    paths: list[GraphPath] = []
    common: list[GraphCommonNeighbors] = []
    if request.include_paths and graph is not None and root_record_id is not None:
        started = perf_counter()
        for hit in hits:
            if hit.record_id == root_record_id:
                continue
            path = shortest_path(
                graph,
                root_record_id,
                hit.record_id,
                max_depth=max(1, request.depth),
            )
            if path is not None:
                paths.append(path)
            neighbors = common_neighbors(graph, root_record_id, hit.record_id)
            if neighbors.neighbor_record_ids:
                common.append(neighbors)
        plan.append(_stage("paths", len(hits), len(paths), started, {}))

    communities: list[GraphCommunity] = []
    source_sets: list[CommunitySourceSet] = []
    layout_hints: list[GraphLayoutHint] = []
    if request.include_communities:
        started = perf_counter()
        global_snapshot = store.get_graph_snapshot(
            GraphSnapshotOptions(
                scopes=request.scopes,
                namespaces=request.namespaces,
                relation_types=request.filters.relation_types,
                include_orphans=request.filters.include_orphans,
            )
        )
        communities, _memberships = detect_communities(
            global_snapshot,
            CommunityDetectionOptions(
                scopes=request.scopes,
                namespaces=request.namespaces,
                relation_types=request.filters.relation_types,
            ),
        )
        source_sets = query_communities(
            store,
            CommunityQueryOptions(
                detection=CommunityDetectionOptions(
                    scopes=request.scopes,
                    namespaces=request.namespaces,
                    relation_types=request.filters.relation_types,
                ),
                query=request.query,
                include_records=False,
                include_paths=False,
                limit=request.limit,
            ),
        ).source_sets
        layout_hints = layout_hints_for_snapshot(global_snapshot, communities)
        plan.append(
            _stage(
                "communities", len(global_snapshot.nodes), len(communities), started, {}
            )
        )

    facets: list[KnowledgeFacet] = []
    if request.include_facets:
        started = perf_counter()
        facets = _facets(
            filtered,
            graph,
            backlinks + outgoing_links,
            communities=communities,
        )
        plan.append(_stage("facets", len(filtered), len(facets), started, {}))

    mentions: list[UnlinkedMentionCandidate] = []
    if request.include_unlinked_mentions:
        started = perf_counter()
        mentions = _unlinked_mentions(
            store,
            records,
            request,
        )
        plan.append(
            _stage(
                "unlinked_mentions",
                len(records),
                len(mentions),
                started,
                {"persisted_edges": 0},
            )
        )

    navigation = _navigation(
        root_record_id=root_record_id,
        hits=hits,
        backlinks=backlinks,
        outgoing_links=outgoing_links,
        paths=paths,
        common=common,
        graph=graph,
        communities=communities,
        mentions=mentions,
    )
    warnings = [graph_warning] if graph_warning else []
    return KnowledgeExplorerResult(
        hits=hits,
        graph=graph,
        backlinks=backlinks,
        outgoing_links=outgoing_links,
        unlinked_mentions=mentions,
        paths=paths,
        common_neighbors=common,
        communities=communities,
        source_sets=source_sets,
        layout_hints=layout_hints,
        facets=facets,
        navigation=navigation,
        query_plan=KnowledgeQueryPlan(plan) if request.include_query_plan else None,
        warnings=warnings,
    )


def evaluate_saved_explorer_view(
    store: KnowledgeExplorerStore,
    view: SavedExplorerView,
) -> KnowledgeExplorerResult:
    """Replay a saved explorer view without mutating the graph."""
    return explore_knowledge(store, view.request)


def _load_records(
    store: KnowledgeExplorerStore,
    request: KnowledgeExplorerRequest,
) -> list[MemoryRecord]:
    common = {
        "scopes": request.scopes,
        "types": request.filters.types,
        "tiers": request.filters.tiers,
        "include_invalidated": bool(
            request.as_of
            or request.valid_at
            or request.effective_during
            or request.believed_at
        ),
        "limit": None,
        "namespaces": request.namespaces,
        "as_of": request.as_of,
        "valid_at": request.valid_at,
        "effective_during": request.effective_during,
        "believed_at": request.believed_at,
    }
    if request.query and request.query.strip():
        return store.search_records(SearchQueryOptions(query=request.query, **common))
    return store.list_records(ListQueryOptions(**common))


def _filter_records(
    records: list[MemoryRecord],
    filters: KnowledgeExplorerFilters,
) -> list[MemoryRecord]:
    filtered = list(records)
    if filters.sources:
        allowed = set(filters.sources)
        filtered = [record for record in filtered if record.source in allowed]
    if filters.tags:
        allowed_tags = {tag.lower().lstrip("#") for tag in filters.tags}
        filtered = [
            record
            for record in filtered
            if allowed_tags.intersection(
                {tag.lower().lstrip("#") for tag in record.tags}
            )
        ]
    if filters.properties:
        filtered = [
            record
            for record in filtered
            if _record_has_properties(record, filters.properties)
        ]
    return filtered


def _filter_orphans(
    store: KnowledgeExplorerStore,
    records: list[MemoryRecord],
    request: KnowledgeExplorerRequest,
) -> list[MemoryRecord]:
    if request.filters.include_orphans:
        return records
    snapshot = store.get_graph_snapshot(
        GraphSnapshotOptions(
            scopes=request.scopes,
            namespaces=request.namespaces,
            include_orphans=True,
            max_nodes=max(len(records), 1),
        )
    )
    connected = {node.record_id for node in snapshot.nodes if not node.orphan}
    return [record for record in records if record.id in connected]


def _record_has_properties(record: MemoryRecord, expected: dict[str, Any]) -> bool:
    properties = _record_properties(record)
    for key, value in expected.items():
        if properties.get(key) != value:
            return False
    return True


def _filter_links(
    links: list[StructuralLink],
    filters: KnowledgeExplorerFilters,
) -> list[StructuralLink]:
    result = links
    if filters.link_kinds:
        allowed = set(filters.link_kinds)
        result = [link for link in result if link.link_kind in allowed]
    return result


def _hit_for_record(
    record: MemoryRecord,
    query: str,
    context_chars: int,
) -> KnowledgeHit:
    matched = _matched_fields(record, query)
    score = 1.0 + (0.25 * len(matched))
    return KnowledgeHit(
        record_id=record.id,
        title=record.title,
        record_type=record.type,
        score=score,
        matched_fields=matched,
        score_components={"keyword": score},
        context=_record_excerpt(record, context_chars),
    )


def _matched_fields(record: MemoryRecord, query: str) -> list[str]:
    if not query:
        return []
    needle = query.lower()
    fields: list[str] = []
    if record.title and needle in record.title.lower():
        fields.append("title")
    if record.key and needle in record.key.lower():
        fields.append("key")
    if any(needle in tag.lower() for tag in record.tags):
        fields.append("tags")
    if needle in _content_text(record).lower():
        fields.append("content")
    if needle in str(record.meta).lower():
        fields.append("meta")
    return fields


def _record_excerpt(
    record: MemoryRecord, context_chars: int
) -> KnowledgeContextExcerpt:
    text = _content_text(record).strip().replace("\n", " ")
    bounded = text[:context_chars] if context_chars else ""
    return KnowledgeContextExcerpt(
        record_id=record.id,
        text=bounded,
        source_path=_document_path(record),
        char_budget=context_chars,
    )


def _content_text(record: MemoryRecord) -> str:
    if isinstance(record.content, str):
        return record.content
    text = record.content.get("text")
    if isinstance(text, str):
        return text
    return str(record.content)


def _record_properties(record: MemoryRecord) -> dict[str, Any]:
    properties: dict[str, Any] = {
        "scope": record.scope,
        "type": record.type,
        "tier": record.tier,
        "source": record.source,
        "key": record.key,
        "title": record.title,
    }
    document = record.meta.get("document")
    if isinstance(document, dict):
        properties.update(document)
    extra = record.meta.get("properties")
    if isinstance(extra, dict):
        properties.update(extra)
    return properties


def _document_path(record: MemoryRecord) -> str | None:
    document = record.meta.get("document")
    if isinstance(document, dict) and isinstance(document.get("path"), str):
        return document["path"]
    return None


def _facets(
    records: list[MemoryRecord],
    graph: GraphSnapshot | None,
    links: list[StructuralLink],
    *,
    communities: list[GraphCommunity],
) -> list[KnowledgeFacet]:
    counters: dict[FacetField, Counter[str]] = {
        "scope": Counter(),
        "type": Counter(),
        "tier": Counter(),
        "source": Counter(),
        "tag": Counter(),
        "community": Counter(),
        "orphan": Counter(),
        "relation_type": Counter(),
        "link_kind": Counter(),
    }
    for record in records:
        counters["scope"][record.scope] += 1
        counters["type"][record.type] += 1
        counters["tier"][record.tier] += 1
        counters["source"][record.source] += 1
        for tag in record.tags:
            counters["tag"][tag] += 1
    if graph is not None:
        for node in graph.nodes:
            counters["orphan"][str(bool(node.orphan)).lower()] += 1
    for community in communities:
        counters["community"][community.community_id] += len(community.record_ids)
    for link in links:
        counters["link_kind"][link.link_kind] += 1
        if link.relation_type:
            counters["relation_type"][link.relation_type] += 1
    facets: list[KnowledgeFacet] = []
    for field_name, counter in counters.items():
        for value, count in sorted(counter.items()):
            facets.append(KnowledgeFacet(field=field_name, value=value, count=count))
    return facets


def _unlinked_mentions(
    store: KnowledgeExplorerStore,
    records: list[MemoryRecord],
    request: KnowledgeExplorerRequest,
) -> list[UnlinkedMentionCandidate]:
    mentions: list[UnlinkedMentionCandidate] = []
    candidates = _mention_targets(store, records)
    for source in records:
        text = _content_text(source)
        if not text:
            continue
        linked_targets = {
            link.target_record_id
            for link in store.list_links(
                LinkQueryOptions(
                    record_id=source.id,
                    direction="out",
                    namespaces=request.namespaces,
                    context_chars=request.context_chars,
                )
            )
            if link.target_record_id
        }
        lowered = text.lower()
        for target_id, match_text, kind in candidates:
            if target_id == source.id or target_id in linked_targets:
                continue
            if len(match_text.strip()) < 3:
                continue
            index = lowered.find(match_text.lower())
            if index < 0:
                continue
            context = _bounded_text(text, index, len(match_text), request.context_chars)
            candidate_id = _stable_id("mention", source.id, target_id, kind, match_text)
            mentions.append(
                UnlinkedMentionCandidate(
                    candidate_id=candidate_id,
                    source_record_id=source.id,
                    target_record_id=target_id,
                    matched_text=match_text,
                    match_kind=kind,
                    context=KnowledgeContextExcerpt(
                        record_id=source.id,
                        text=context,
                        source_path=_document_path(source),
                        char_budget=request.context_chars,
                    ),
                )
            )
            if len(mentions) >= request.limit:
                return mentions
    return mentions


def _mention_targets(
    store: KnowledgeExplorerStore,
    records: list[MemoryRecord],
) -> list[tuple[str, str, MentionMatchKind]]:
    targets: list[tuple[str, str, MentionMatchKind]] = []
    for record in records:
        if record.title:
            targets.append((record.id, record.title, "title"))
        aliases = record.meta.get("aliases")
        if isinstance(aliases, list):
            targets.extend((record.id, str(alias), "alias") for alias in aliases)
        path = _document_path(record)
        if path:
            targets.append((record.id, path, "path"))
        try:
            blocks = store.list_document_blocks(record_id=record.id)
        except Exception:  # allow-bare-raise: optional store method guard
            blocks = []
        for block in blocks:
            if block.block_type == "heading":
                targets.append((record.id, block.anchor, "heading"))
            targets.append((record.id, block.block_id, "block_id"))
    return targets


def _bounded_text(text: str, index: int, length: int, budget: int) -> str:
    if budget <= 0:
        return ""
    half = max(0, (budget - length) // 2)
    start = max(0, index - half)
    end = min(len(text), index + length + half)
    return text[start:end].replace("\n", " ")


def _navigation(
    *,
    root_record_id: str | None,
    hits: list[KnowledgeHit],
    backlinks: list[StructuralLink],
    outgoing_links: list[StructuralLink],
    paths: list[GraphPath],
    common: list[GraphCommonNeighbors],
    graph: GraphSnapshot | None,
    communities: list[GraphCommunity],
    mentions: list[UnlinkedMentionCandidate],
) -> list[KnowledgeNavigationAction]:
    actions: list[KnowledgeNavigationAction] = []
    if root_record_id:
        actions.append(
            KnowledgeNavigationAction(
                action="open_root",
                record_id=root_record_id,
                label="Open root",
            )
        )
    for hit in hits:
        actions.append(
            KnowledgeNavigationAction(
                action="open_hit",
                record_id=hit.record_id,
                label=hit.title or hit.record_id,
            )
        )
    for link in backlinks:
        actions.append(
            KnowledgeNavigationAction(
                action="follow_backlink",
                record_id=link.source_record_id,
                link_id=link.link_id,
                label=link.display_text or link.raw_target,
            )
        )
    for link in outgoing_links:
        if link.target_record_id:
            actions.append(
                KnowledgeNavigationAction(
                    action="follow_outgoing_link",
                    record_id=link.target_record_id,
                    link_id=link.link_id,
                    label=link.display_text or link.raw_target,
                )
            )
    for path in paths:
        actions.append(
            KnowledgeNavigationAction(
                action="inspect_path",
                path=path,
                label=f"{path.hop_count} hop path",
            )
        )
    for neighbors in common:
        for record_id in neighbors.neighbor_record_ids:
            actions.append(
                KnowledgeNavigationAction(
                    action="open_common_neighbor",
                    record_id=record_id,
                    label="Open common neighbor",
                )
            )
    if graph is not None:
        for node in graph.nodes:
            if node.orphan:
                actions.append(
                    KnowledgeNavigationAction(
                        action="open_orphan",
                        record_id=node.record_id,
                        label=node.title or node.record_id,
                    )
                )
    for community in communities:
        actions.append(
            KnowledgeNavigationAction(
                action="open_community",
                record_id=community.seed_record_id or community.record_ids[0],
                label=f"Open community ({len(community.record_ids)})",
            )
        )
        actions.append(
            KnowledgeNavigationAction(
                action="filter_community",
                record_id=community.seed_record_id or community.record_ids[0],
                label=f"Filter community ({len(community.record_ids)})",
            )
        )
    for mention in mentions:
        actions.append(
            KnowledgeNavigationAction(
                action="apply_repair_candidate",
                candidate_id=mention.candidate_id,
                label=f"Review mention: {mention.matched_text}",
            )
        )
    return actions


def _stage(
    stage: QueryPlanStageName,
    input_count: int,
    output_count: int,
    started: float,
    details: dict[str, Any],
) -> KnowledgeQueryPlanStage:
    return KnowledgeQueryPlanStage(
        stage=stage,
        input_count=input_count,
        output_count=output_count,
        elapsed_ms=round((perf_counter() - started) * 1000, 3),
        details=details,
    )


def _filter_details(filters: KnowledgeExplorerFilters) -> dict[str, Any]:
    return {
        "types": list(filters.types or []),
        "tiers": list(filters.tiers or []),
        "sources": list(filters.sources or []),
        "tags": list(filters.tags or []),
        "properties": dict(filters.properties),
        "relation_types": list(filters.relation_types or []),
        "link_kinds": list(filters.link_kinds or []),
        "include_orphans": filters.include_orphans,
    }


def _stable_id(prefix: str, *parts: str) -> str:
    return f"{prefix}-{uuid5(NAMESPACE_URL, ':'.join(str(part) for part in parts))}"


__all__ = [
    "FacetField",
    "KnowledgeContextExcerpt",
    "KnowledgeExplorerFilters",
    "KnowledgeExplorerRequest",
    "KnowledgeExplorerResult",
    "KnowledgeExplorerStore",
    "KnowledgeFacet",
    "KnowledgeHit",
    "GraphCommunity",
    "GraphLayoutHint",
    "KnowledgeNavigationAction",
    "KnowledgeQueryPlan",
    "KnowledgeQueryPlanStage",
    "MentionMatchKind",
    "NavigationActionKind",
    "QueryPlanStageName",
    "SavedExplorerView",
    "UnlinkedMentionCandidate",
    "evaluate_saved_explorer_view",
    "explore_knowledge",
]
