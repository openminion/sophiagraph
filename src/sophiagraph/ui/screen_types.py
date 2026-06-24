"""Typed screen packets for the package-local SophiaGraph visual explorer."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Protocol

from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.inspection import InspectionReport, RepairCandidate
from sophiagraph.models import (
    KnowledgeDocumentBlock,
    MemoryCandidate,
    MemoryNamespace,
    MemoryRecord,
    MemoryRelation,
    StructuralLink,
)
from sophiagraph.operations import OperationalRunReport, OperationalRunRequest
from sophiagraph.query import (
    CandidateListOptions,
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
)
from sophiagraph.schema import GraphSchema
from sophiagraph.views import SavedViewDefinition, SavedViewResult

ScreenId = Literal[
    "explore",
    "record_detail",
    "graph",
    "operations",
    "repair",
    "candidate_review",
    "saved_views",
    "community",
    "timeline",
    "schema",
]
GraphViewMode = Literal["neighborhood", "path", "orphan", "community"]


class UiStore(Protocol):
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

    def list_candidates(
        self, options: CandidateListOptions
    ) -> list[MemoryCandidate]: ...


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
class CandidateReviewScreen:
    options: CandidateListOptions
    candidates: list[MemoryCandidate] = field(default_factory=list)
    screen_id: ScreenId = "candidate_review"


@dataclass(frozen=True, slots=True)
class SavedViewWorkbenchRequest:
    scopes: list[str]
    definitions: list[SavedViewDefinition]
    namespaces: list[MemoryNamespace] | None = None
    include_invalidated: bool = False
    live: bool = True

    def __post_init__(self) -> None:
        if not self.scopes:
            raise InvalidArgumentError("scopes are required")
        if not self.definitions:
            raise InvalidArgumentError("saved view definitions are required")


@dataclass(frozen=True, slots=True)
class SavedViewWorkbenchPanel:
    definition: SavedViewDefinition
    result: SavedViewResult
    status: Literal["ready", "empty"] = "ready"


@dataclass(frozen=True, slots=True)
class SavedViewWorkbenchScreen:
    request: SavedViewWorkbenchRequest
    panels: list[SavedViewWorkbenchPanel] = field(default_factory=list)
    screen_id: ScreenId = "saved_views"


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


def screen_to_dict(screen: Any) -> dict[str, Any]:
    """Return a plain dict snapshot for a typed screen packet."""

    return asdict(screen)


__all__ = [
    "CandidateReviewScreen",
    "CommunityStructureScreen",
    "GraphViewMode",
    "GraphViewRequest",
    "GraphViewScreen",
    "KnowledgeExplorerScreen",
    "KnowledgeRecordDetailPacket",
    "OperationsConsoleScreen",
    "RecordDetailScreen",
    "RepairCenterScreen",
    "SavedViewWorkbenchPanel",
    "SavedViewWorkbenchRequest",
    "SavedViewWorkbenchScreen",
    "SchemaDeveloperScreen",
    "ScreenId",
    "TimelineScreen",
    "UiStore",
    "screen_to_dict",
]
