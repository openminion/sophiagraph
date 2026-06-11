"""Package-owned UI route and transport contracts for the SophiaGraph explorer."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

UiTransportKind = Literal["rest"]
UiTransportStatus = Literal["designed_not_implemented"]
UiScreenId = Literal[
    "explore",
    "record_detail",
    "graph",
    "operations",
    "repair",
    "community",
    "timeline",
    "schema",
]


@dataclass(frozen=True, slots=True)
class UiTransportBoundary:
    """Typed statement of the current UI/runtime split for SophiaGraph."""

    owner_import_root: str
    runtime_package: str
    transport: UiTransportKind
    transport_status: UiTransportStatus
    server_url: str
    api_prefix: str
    imports_openminion: bool
    imports_runtime_package: bool

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class UiScreenDefinition:
    """One first-pass screen in the SophiaGraph visual explorer."""

    screen_id: UiScreenId
    route: str
    title: str
    primary_payloads: tuple[str, ...]
    mvp: bool = False
    mutating: bool = False

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def build_default_ui_boundary(
    server_url: str = "http://127.0.0.1:8765",
) -> UiTransportBoundary:
    """Return the canonical UI/runtime boundary for SGVUI v1 work."""
    return UiTransportBoundary(
        owner_import_root="sophiagraph.ui",
        runtime_package="sophiagraph-server",
        transport="rest",
        transport_status="designed_not_implemented",
        server_url=server_url,
        api_prefix="/v1/knowledge",
        imports_openminion=False,
        imports_runtime_package=False,
    )


def build_ui_screen_manifest() -> tuple[UiScreenDefinition, ...]:
    """Return the first-pass route manifest for the visual explorer."""
    return (
        UiScreenDefinition(
            screen_id="explore",
            route="/explore",
            title="Knowledge Explorer",
            primary_payloads=(
                "KnowledgeExplorerRequest",
                "KnowledgeExplorerResult",
                "SavedExplorerView",
            ),
            mvp=True,
        ),
        UiScreenDefinition(
            screen_id="record_detail",
            route="/record/:record_id",
            title="Record Detail",
            primary_payloads=("MemoryRecord", "KnowledgeRecordDetailPacket"),
            mvp=True,
        ),
        UiScreenDefinition(
            screen_id="graph",
            route="/graph",
            title="Graph View",
            primary_payloads=("GraphSnapshot", "GraphPath", "GraphCommunity"),
            mvp=True,
        ),
        UiScreenDefinition(
            screen_id="operations",
            route="/operations",
            title="Operations Console",
            primary_payloads=("OperationalRunRequest", "OperationalRunReport"),
            mvp=True,
            mutating=True,
        ),
        UiScreenDefinition(
            screen_id="repair",
            route="/repair",
            title="Repair Center",
            primary_payloads=("InspectionReport", "RepairCandidate"),
            mvp=True,
            mutating=True,
        ),
        UiScreenDefinition(
            screen_id="community",
            route="/community",
            title="Community Structure",
            primary_payloads=("CommunityQueryResult", "StructuralGraphQueryResult"),
        ),
        UiScreenDefinition(
            screen_id="timeline",
            route="/timeline",
            title="Timeline",
            primary_payloads=("ListQueryOptions", "DeletionCascadeResult"),
        ),
        UiScreenDefinition(
            screen_id="schema",
            route="/schema",
            title="Schema And Developer Panel",
            primary_payloads=(
                "GraphBackendCapabilities",
                "GraphExportBatch",
                "describe_schema",
            ),
        ),
    )
