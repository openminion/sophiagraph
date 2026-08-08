"""Public structural explorer packet API."""

from __future__ import annotations

from time import perf_counter

from sophiagraph.models import StructuralLink
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

from .explorer_mechanics import (
    facets as build_facets,
    filter_details,
    filter_links,
    filter_orphans,
    filter_records,
    hit_for_record,
    load_record_page,
    navigation,
    next_cursor,
    record_page_stage,
    stage,
    unlinked_mentions,
)
from .explorer_types import (
    FacetField,
    KnowledgeContextExcerpt,
    KnowledgeExplorerFilters,
    KnowledgeExplorerRequest,
    KnowledgeExplorerResult,
    KnowledgeExplorerStore,
    KnowledgeFacet,
    KnowledgeHit,
    KnowledgeNavigationAction,
    KnowledgeQueryPlan,
    KnowledgeQueryPlanStage,
    MentionMatchKind,
    NavigationActionKind,
    QueryPlanStageName,
    SavedExplorerView,
    UnlinkedMentionCandidate,
)


def explore_knowledge(
    store: KnowledgeExplorerStore,
    request: KnowledgeExplorerRequest,
) -> KnowledgeExplorerResult:
    """Build one structural explorer packet from existing store APIs."""
    plan: list[KnowledgeQueryPlanStage] = []
    started = perf_counter()
    page_records, has_next_page, offset = load_record_page(store, request)
    plan.append(
        record_page_stage(
            request, output_count=len(page_records), offset=offset, started=started
        )
    )

    started = perf_counter()
    filtered = filter_records(page_records, request.filters)
    filtered = filter_orphans(store, filtered, request)
    plan.append(
        stage(
            "filters",
            len(page_records),
            len(filtered),
            started,
            filter_details(request.filters),
        )
    )

    hits = [
        hit_for_record(record, request.query or "", request.context_chars)
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
            stage(
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
        backlinks = filter_links(
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
        plan.append(stage("backlinks", 0, len(backlinks), started, {}))

    outgoing_links: list[StructuralLink] = []
    if request.include_outgoing_links and root_record_id is not None:
        started = perf_counter()
        outgoing_links = filter_links(
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
        plan.append(stage("outgoing_links", 0, len(outgoing_links), started, {}))

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
        plan.append(stage("paths", len(hits), len(paths), started, {}))

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
            stage(
                "communities", len(global_snapshot.nodes), len(communities), started, {}
            )
        )

    facets: list[KnowledgeFacet] = []
    if request.include_facets:
        started = perf_counter()
        facets = build_facets(
            filtered,
            graph,
            backlinks + outgoing_links,
            communities=communities,
        )
        plan.append(stage("facets", len(filtered), len(facets), started, {}))

    mentions: list[UnlinkedMentionCandidate] = []
    if request.include_unlinked_mentions:
        started = perf_counter()
        mentions = unlinked_mentions(
            store,
            filtered,
            request,
        )
        plan.append(
            stage(
                "unlinked_mentions",
                len(filtered),
                len(mentions),
                started,
                {"persisted_edges": 0},
            )
        )

    navigation_actions = navigation(
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
        navigation=navigation_actions,
        query_plan=KnowledgeQueryPlan(plan) if request.include_query_plan else None,
        warnings=warnings,
        next_cursor=next_cursor(request, offset + request.limit)
        if has_next_page
        else None,
    )


def evaluate_saved_explorer_view(
    store: KnowledgeExplorerStore,
    view: SavedExplorerView,
) -> KnowledgeExplorerResult:
    """Replay a saved explorer view without mutating the graph."""
    return explore_knowledge(store, view.request)


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
