"""Builder helpers for the package-local SophiaGraph visual explorer screens."""

from __future__ import annotations

from typing import Any

from sophiagraph.contracts.errors import NotFoundError
from sophiagraph.inspection import RepairCandidate, build_inspection_report
from sophiagraph.models import (
    KnowledgeDocumentBlock,
    MemoryNamespace,
    MemoryRecord,
    MemoryRelation,
    StructuralLink,
)
from sophiagraph.operations import OperationalRunRequest, execute_operational_run
from sophiagraph.query import (
    CandidateListOptions,
    CommunityDetectionOptions,
    CommunityQueryOptions,
    KnowledgeExplorerRequest,
    LinkQueryOptions,
    ListQueryOptions,
    LocalGraphOptions,
    StructuralGraphQueryResult,
    common_neighbors,
    connected_components,
    explore_knowledge,
    query_communities,
    shortest_path,
)
from sophiagraph.schema import describe_schema
from sophiagraph.ui.screen_types import (
    CandidateReviewScreen,
    CommunityStructureScreen,
    GraphViewRequest,
    GraphViewScreen,
    KnowledgeExplorerScreen,
    KnowledgeRecordDetailPacket,
    OperationsConsoleScreen,
    RecordDetailScreen,
    RepairCenterScreen,
    SavedViewWorkbenchPanel,
    SavedViewWorkbenchRequest,
    SavedViewWorkbenchScreen,
    SchemaDeveloperScreen,
    TimelineScreen,
    UiStore,
)
from sophiagraph.views import evaluate_saved_view


def build_explorer_screen(
    store: UiStore,
    request: KnowledgeExplorerRequest,
) -> KnowledgeExplorerScreen:
    return KnowledgeExplorerScreen(
        request=request, result=explore_knowledge(store, request)
    )


def build_record_detail_packet(
    store: UiStore,
    *,
    record_id: str,
    graph_depth: int = 1,
) -> KnowledgeRecordDetailPacket:
    record = store.get_record(record_id)
    if record is None:
        raise NotFoundError(f"record not found: {record_id}")
    links_out = store.list_links(
        LinkQueryOptions(
            record_id=record_id,
            direction="out",
            namespaces=[record.effective_namespace],
        )
    )
    links_in = store.list_links(
        LinkQueryOptions(
            record_id=record_id,
            direction="in",
            namespaces=[record.effective_namespace],
        )
    )
    graph = store.get_local_graph(
        LocalGraphOptions(
            record_id=record_id,
            depth=graph_depth,
            namespaces=[record.effective_namespace],
        )
    )
    return KnowledgeRecordDetailPacket(
        record=record,
        relations=store.list_relations(record_id, direction="both"),
        backlinks=links_in,
        outgoing_links=links_out,
        document_blocks=store.list_document_blocks(record_id=record_id),
        graph=graph,
        related_paths=[],
    )


def build_record_detail_screen(
    store: UiStore,
    *,
    record_id: str,
    graph_depth: int = 1,
) -> RecordDetailScreen:
    return RecordDetailScreen(
        record_id=record_id,
        packet=build_record_detail_packet(
            store,
            record_id=record_id,
            graph_depth=graph_depth,
        ),
    )


def build_graph_view_screen(
    store: UiStore,
    request: GraphViewRequest,
) -> GraphViewScreen:
    snapshot = store.get_local_graph(
        LocalGraphOptions(
            record_id=request.root_record_id,
            depth=request.depth,
            relation_types=request.relation_types,
            namespaces=request.namespaces,
        )
    )
    highlighted_path = None
    if request.target_record_id:
        highlighted_path = shortest_path(
            snapshot,
            request.root_record_id,
            request.target_record_id,
        )
    shared_neighbors = None
    if request.comparison_record_id:
        shared_candidates = common_neighbors(
            snapshot,
            request.root_record_id,
            request.comparison_record_id,
        )
        shared_neighbors = shared_candidates[0] if shared_candidates else None
    communities = []
    if request.mode == "community":
        community_result = query_communities(
            store,
            CommunityQueryOptions(
                detection=CommunityDetectionOptions(
                    scopes=request.scopes,
                    namespaces=request.namespaces,
                    relation_types=request.relation_types,
                ),
                limit=20,
            ),
        )
        communities = community_result.communities
    return GraphViewScreen(
        request=request,
        snapshot=snapshot,
        highlighted_path=highlighted_path,
        shared_neighbors=shared_neighbors,
        communities=communities,
        components=connected_components(snapshot),
    )


def build_operations_console_screen(
    request: OperationalRunRequest,
) -> OperationsConsoleScreen:
    return OperationsConsoleScreen(
        request=request, report=execute_operational_run(request)
    )


def build_repair_center_screen(
    *,
    report_id: str,
    namespace: MemoryNamespace,
    generated_at: str,
    records: list[MemoryRecord],
    links: list[StructuralLink] | None = None,
    facts: list[Any] | None = None,
    freshness_entries: list[Any] | None = None,
    conflicts: list[Any] | None = None,
    repair_candidates: list[RepairCandidate] | None = None,
) -> RepairCenterScreen:
    return RepairCenterScreen(
        report=build_inspection_report(
            report_id=report_id,
            namespace=namespace,
            generated_at=generated_at,
            records=records,
            links=links,
            facts=facts,
            freshness_entries=freshness_entries,
            conflicts=conflicts,
        ),
        repair_candidates=list(repair_candidates or []),
    )


def build_candidate_review_screen(
    store: UiStore,
    options: CandidateListOptions,
) -> CandidateReviewScreen:
    return CandidateReviewScreen(
        options=options,
        candidates=store.list_candidates(options),
    )


def build_saved_view_workbench_screen(
    store: UiStore,
    request: SavedViewWorkbenchRequest,
) -> SavedViewWorkbenchScreen:
    records = store.list_records(
        ListQueryOptions(
            scopes=request.scopes,
            namespaces=request.namespaces,
            include_invalidated=request.include_invalidated,
        )
    )
    panels: list[SavedViewWorkbenchPanel] = []
    for definition in request.definitions:
        result = evaluate_saved_view(records, definition)
        panels.append(
            SavedViewWorkbenchPanel(
                definition=definition,
                result=result,
                status="ready" if result.rows else "empty",
            )
        )
    return SavedViewWorkbenchScreen(request=request, panels=panels)


def build_community_structure_screen(
    store: UiStore,
    request: CommunityQueryOptions,
) -> CommunityStructureScreen:
    return CommunityStructureScreen(
        request=request, result=query_communities(store, request)
    )


def build_timeline_screen(
    store: UiStore,
    options: ListQueryOptions,
) -> TimelineScreen:
    return TimelineScreen(options=options, records=store.list_records(options))


def build_schema_developer_screen(
    *,
    records: list[MemoryRecord],
    relations: list[MemoryRelation] | None = None,
    links: list[StructuralLink] | None = None,
    blocks: list[KnowledgeDocumentBlock] | None = None,
    backend_capabilities: dict[str, Any] | None = None,
    export_batch_preview: dict[str, Any] | None = None,
    last_request_payload: dict[str, Any] | None = None,
    last_response_payload: dict[str, Any] | None = None,
    structural_result: StructuralGraphQueryResult | None = None,
) -> SchemaDeveloperScreen:
    return SchemaDeveloperScreen(
        schema=describe_schema(
            records=records,
            relations=relations,
            links=links,
            blocks=blocks,
        ),
        backend_capabilities=backend_capabilities,
        export_batch_preview=export_batch_preview,
        last_request_payload=last_request_payload,
        last_response_payload=last_response_payload,
        structural_result=structural_result,
    )


__all__ = [
    "build_candidate_review_screen",
    "build_community_structure_screen",
    "build_explorer_screen",
    "build_graph_view_screen",
    "build_operations_console_screen",
    "build_record_detail_packet",
    "build_record_detail_screen",
    "build_repair_center_screen",
    "build_saved_view_workbench_screen",
    "build_schema_developer_screen",
    "build_timeline_screen",
]
