"""Typed screen packets for the package-local SophiaGraph visual explorer."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Protocol

from sophiagraph.contracts.errors import InvalidArgumentError, NotFoundError
from sophiagraph.inspection import (
    InspectionReport,
    RepairCandidate,
    build_inspection_report,
)
from sophiagraph.models import (
    KnowledgeDocumentBlock,
    MemoryNamespace,
    MemoryRecord,
    MemoryRelation,
    StructuralLink,
)
from sophiagraph.operations import (
    OperationalRunReport,
    OperationalRunRequest,
    execute_operational_run,
)
from sophiagraph.query import (
    CommunityDetectionOptions,
    CommunityQueryOptions,
    CommunityQueryResult,
    GraphCommonNeighbors,
    GraphCommunity,
    GraphComponent,
    GraphPath,
    GraphSnapshot,
    GraphSnapshotOptions,
    KnowledgeExplorerRequest,
    KnowledgeExplorerResult,
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
from sophiagraph.schema import GraphSchema, describe_schema

ScreenId = Literal[
    "explore",
    "record_detail",
    "graph",
    "operations",
    "repair",
    "community",
    "timeline",
    "schema",
]
GraphViewMode = Literal["neighborhood", "path", "orphan", "community"]


class _UiStore(Protocol):
    def get_record(self, record_id: str) -> MemoryRecord | None: ...

    def list_records(self, options: ListQueryOptions) -> list[MemoryRecord]: ...

    def list_relations(
        self,
        record_id: str,
        *,
        direction: str = "out",
        relation_types: list[Any] | None = None,
        limit: int | None = None,
    ) -> list[MemoryRelation]: ...

    def list_links(self, options: LinkQueryOptions) -> list[StructuralLink]: ...

    def list_document_blocks(
        self,
        *,
        record_id: str | None = None,
        document_id: str | None = None,
        block_id: str | None = None,
    ) -> list[KnowledgeDocumentBlock]: ...

    def get_local_graph(self, options: LocalGraphOptions) -> GraphSnapshot: ...

    def get_graph_snapshot(self, options: GraphSnapshotOptions) -> GraphSnapshot: ...


@dataclass(frozen=True, slots=True)
class KnowledgeExplorerScreen:
    request: KnowledgeExplorerRequest
    result: KnowledgeExplorerResult
    screen_id: ScreenId = "explore"


@dataclass(frozen=True, slots=True)
class KnowledgeRecordDetailPacket:
    record: MemoryRecord
    relations: list[MemoryRelation] = field(default_factory=list)
    backlinks: list[StructuralLink] = field(default_factory=list)
    outgoing_links: list[StructuralLink] = field(default_factory=list)
    document_blocks: list[KnowledgeDocumentBlock] = field(default_factory=list)
    graph: GraphSnapshot | None = None
    related_paths: list[GraphPath] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class RecordDetailScreen:
    record_id: str
    packet: KnowledgeRecordDetailPacket
    screen_id: ScreenId = "record_detail"


@dataclass(frozen=True, slots=True)
class GraphViewRequest:
    root_record_id: str
    scopes: list[str]
    namespaces: list[MemoryNamespace] | None = None
    mode: GraphViewMode = "neighborhood"
    depth: int = 1
    relation_types: list[str] | None = None
    target_record_id: str | None = None
    comparison_record_id: str | None = None

    def __post_init__(self) -> None:
        if not self.root_record_id:
            raise InvalidArgumentError("root_record_id is required")
        if not self.scopes:
            raise InvalidArgumentError("scopes are required")
        if self.mode not in {"neighborhood", "path", "orphan", "community"}:
            raise InvalidArgumentError(f"invalid mode: {self.mode!r}")
        if self.depth < 0:
            raise InvalidArgumentError("depth must be non-negative")


@dataclass(frozen=True, slots=True)
class GraphViewScreen:
    request: GraphViewRequest
    snapshot: GraphSnapshot
    highlighted_path: GraphPath | None = None
    shared_neighbors: GraphCommonNeighbors | None = None
    communities: list[GraphCommunity] = field(default_factory=list)
    components: list[GraphComponent] = field(default_factory=list)
    screen_id: ScreenId = "graph"


@dataclass(frozen=True, slots=True)
class OperationsConsoleScreen:
    request: OperationalRunRequest
    report: OperationalRunReport
    screen_id: ScreenId = "operations"


@dataclass(frozen=True, slots=True)
class RepairCenterScreen:
    report: InspectionReport
    repair_candidates: list[RepairCandidate] = field(default_factory=list)
    screen_id: ScreenId = "repair"


@dataclass(frozen=True, slots=True)
class CommunityStructureScreen:
    request: CommunityQueryOptions
    result: CommunityQueryResult
    screen_id: ScreenId = "community"


@dataclass(frozen=True, slots=True)
class TimelineScreen:
    options: ListQueryOptions
    records: list[MemoryRecord]
    screen_id: ScreenId = "timeline"


@dataclass(frozen=True, slots=True)
class SchemaDeveloperScreen:
    schema: GraphSchema
    backend_capabilities: dict[str, Any] | None = None
    export_batch_preview: dict[str, Any] | None = None
    last_request_payload: dict[str, Any] | None = None
    last_response_payload: dict[str, Any] | None = None
    structural_result: StructuralGraphQueryResult | None = None
    screen_id: ScreenId = "schema"


def build_explorer_screen(
    store: _UiStore,
    request: KnowledgeExplorerRequest,
) -> KnowledgeExplorerScreen:
    return KnowledgeExplorerScreen(
        request=request, result=explore_knowledge(store, request)
    )


def build_record_detail_packet(
    store: _UiStore,
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
    store: _UiStore,
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
    store: _UiStore,
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
    communities: list[GraphCommunity] = []
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


def build_community_structure_screen(
    store: _UiStore,
    request: CommunityQueryOptions,
) -> CommunityStructureScreen:
    return CommunityStructureScreen(
        request=request, result=query_communities(store, request)
    )


def build_timeline_screen(
    store: _UiStore,
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


def screen_to_dict(screen: Any) -> dict[str, Any]:
    """Return a plain dict snapshot for a typed screen packet."""

    return asdict(screen)


__all__ = [
    "CommunityStructureScreen",
    "GraphViewMode",
    "GraphViewRequest",
    "GraphViewScreen",
    "KnowledgeExplorerScreen",
    "KnowledgeRecordDetailPacket",
    "OperationsConsoleScreen",
    "RecordDetailScreen",
    "RepairCenterScreen",
    "SchemaDeveloperScreen",
    "ScreenId",
    "TimelineScreen",
    "build_community_structure_screen",
    "build_explorer_screen",
    "build_graph_view_screen",
    "build_operations_console_screen",
    "build_record_detail_packet",
    "build_record_detail_screen",
    "build_repair_center_screen",
    "build_schema_developer_screen",
    "build_timeline_screen",
    "screen_to_dict",
]
