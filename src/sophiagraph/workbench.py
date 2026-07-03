"""Collaborative second-brain workbench packets and structural action previews."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from typing import TYPE_CHECKING, Any, Literal, get_args

from sophiagraph.candidate_review import CandidateQueueItem
from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.inspection import RepairCandidate
from sophiagraph.publishing import DeliveryHandoff, PublishPlan
from sophiagraph.workspace_history import WorkspaceDiffSummary, WorkspaceRevision
from sophiagraph.workspace_roles import WorkspaceGateDecision, WorkspaceReviewRequest
from sophiagraph.workspace_sync import WorkspaceSyncPlan, WorkspaceSyncStatus

if TYPE_CHECKING:
    from sophiagraph.ui.screens import (
        CandidateReviewScreen,
        KnowledgeExplorerScreen,
        RecordDetailScreen,
        RepairCenterScreen,
    )

WorkbenchActionKind = Literal[
    "save_note",
    "propose_note_edit",
    "approve_candidate",
    "reject_candidate",
    "promote_candidate",
    "apply_repair",
    "approve_workspace_edit",
    "reject_workspace_edit",
    "build_publish_plan",
    "open_graph_selection",
    "restore_workspace",
]
WorkbenchActionStatus = Literal["allowed", "requires_review", "blocked", "preview_only"]
WorkbenchReviewItemKind = Literal[
    "candidate",
    "repair",
    "workspace_review",
    "publish_request",
    "agent_edit",
]

_ACTION_KINDS = frozenset(get_args(WorkbenchActionKind))
_ACTION_STATUSES = frozenset(get_args(WorkbenchActionStatus))
_REVIEW_ITEM_KINDS = frozenset(get_args(WorkbenchReviewItemKind))


@dataclass(frozen=True, slots=True)
class WorkbenchActionRequest:
    """One explicit workbench action request for preview or host execution."""

    action: WorkbenchActionKind
    target_id: str
    actor_id: str
    workspace_id: str
    payload_kind: str = "record"
    payload: dict[str, Any] = field(default_factory=dict)
    requires_review: bool = False

    def __post_init__(self) -> None:
        if self.action not in _ACTION_KINDS:
            raise InvalidArgumentError(f"invalid workbench action: {self.action!r}")
        if not self.target_id:
            raise InvalidArgumentError("target_id is required")
        if not self.actor_id:
            raise InvalidArgumentError("actor_id is required")
        if not self.workspace_id:
            raise InvalidArgumentError("workspace_id is required")
        if not self.payload_kind:
            raise InvalidArgumentError("payload_kind is required")


@dataclass(frozen=True, slots=True)
class WorkbenchActionPreview:
    """Deterministic preview for an action before a host applies it."""

    request: WorkbenchActionRequest
    status: WorkbenchActionStatus
    reason: str
    policy_messages: tuple[str, ...] = ()
    publish_impact: tuple[str, ...] = ()
    provenance_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.status not in _ACTION_STATUSES:
            raise InvalidArgumentError(
                f"invalid action preview status: {self.status!r}"
            )
        if not self.reason:
            raise InvalidArgumentError("reason is required")

    @property
    def allowed(self) -> bool:
        return self.status == "allowed"


@dataclass(frozen=True, slots=True)
class WorkbenchPolicyOverlay:
    """Visibility, retention, and review markers for the active workbench object."""

    visibility: str = "visible"
    retention_class: str = "standard"
    review_required: bool = False
    publish_profile_id: str = ""
    messages: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.visibility:
            raise InvalidArgumentError("visibility is required")
        if not self.retention_class:
            raise InvalidArgumentError("retention_class is required")


@dataclass(frozen=True, slots=True)
class WorkbenchPublishOverlay:
    """Publish/share preview details shown inside the workbench."""

    profile_id: str
    profile_kind: str
    included_count: int
    omitted_count: int
    delivery_target: str = ""
    payload_ref: str = ""

    def __post_init__(self) -> None:
        if not self.profile_id:
            raise InvalidArgumentError("profile_id is required")
        if self.included_count < 0 or self.omitted_count < 0:
            raise InvalidArgumentError("publish counts must be non-negative")


@dataclass(frozen=True, slots=True)
class WorkbenchReviewItem:
    """One explicit review item for candidate, repair, publish, or workspace flow."""

    item_id: str
    kind: WorkbenchReviewItemKind
    title: str
    status: str
    target_id: str
    proposer_id: str = ""
    evidence_count: int = 0
    allowed_actions: tuple[WorkbenchActionKind, ...] = ()
    preview: str = ""
    policy_gate: str = ""
    provenance_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.item_id:
            raise InvalidArgumentError("item_id is required")
        if self.kind not in _REVIEW_ITEM_KINDS:
            raise InvalidArgumentError(f"invalid review item kind: {self.kind!r}")
        if not self.title:
            raise InvalidArgumentError("title is required")
        if not self.status:
            raise InvalidArgumentError("status is required")
        if not self.target_id:
            raise InvalidArgumentError("target_id is required")
        if self.evidence_count < 0:
            raise InvalidArgumentError("evidence_count must be non-negative")
        invalid = [
            action for action in self.allowed_actions if action not in _ACTION_KINDS
        ]
        if invalid:
            raise InvalidArgumentError(f"invalid allowed action: {invalid[0]!r}")


@dataclass(frozen=True, slots=True)
class WorkbenchReviewInbox:
    """Review queue summary for the collaborative workbench."""

    items: tuple[WorkbenchReviewItem, ...] = ()

    @property
    def pending_count(self) -> int:
        return sum(1 for item in self.items if item.status in {"pending", "proposed"})

    @property
    def blocked_count(self) -> int:
        return sum(1 for item in self.items if item.status == "blocked")


@dataclass(frozen=True, slots=True)
class WorkbenchNotePanel:
    """Active note/record panel with nearby graph and policy metadata."""

    record_id: str
    title: str
    record_type: str
    updated_at: str = ""
    outgoing_count: int = 0
    backlink_count: int = 0
    related_record_ids: tuple[str, ...] = ()
    block_count: int = 0
    policy: WorkbenchPolicyOverlay = field(default_factory=WorkbenchPolicyOverlay)
    action_previews: tuple[WorkbenchActionPreview, ...] = ()

    def __post_init__(self) -> None:
        if not self.record_id:
            raise InvalidArgumentError("record_id is required")
        if not self.title:
            raise InvalidArgumentError("title is required")
        if not self.record_type:
            raise InvalidArgumentError("record_type is required")
        if self.outgoing_count < 0 or self.backlink_count < 0 or self.block_count < 0:
            raise InvalidArgumentError("note panel counts must be non-negative")


@dataclass(frozen=True, slots=True)
class WorkbenchGraphPanelState:
    """GraphFakos-backed graph panel summary for the workbench."""

    provider_id: str
    graph_role: str
    selected_node_id: str = ""
    node_count: int = 0
    edge_count: int = 0
    viewer_state: dict[str, Any] = field(default_factory=dict)
    embed_html: str = ""

    def __post_init__(self) -> None:
        if not self.provider_id:
            raise InvalidArgumentError("provider_id is required")
        if self.node_count < 0 or self.edge_count < 0:
            raise InvalidArgumentError("graph panel counts must be non-negative")


@dataclass(frozen=True, slots=True)
class CollaborativeWorkbenchState:
    """Active workspace selection and screen state."""

    workspace_id: str
    active_screen: str = "workbench"
    selected_record_id: str = ""
    actor_id: str = ""

    def __post_init__(self) -> None:
        if not self.workspace_id:
            raise InvalidArgumentError("workspace_id is required")
        if not self.active_screen:
            raise InvalidArgumentError("active_screen is required")


@dataclass(frozen=True, slots=True)
class WorkspaceWorkbenchRequest:
    """Structural request for composing a collaborative workbench packet."""

    workspace_id: str
    actor_id: str
    root_record_id: str = ""
    query: str = ""
    graph_depth: int = 1
    include_archived: bool = False

    def __post_init__(self) -> None:
        if not self.workspace_id:
            raise InvalidArgumentError("workspace_id is required")
        if not self.actor_id:
            raise InvalidArgumentError("actor_id is required")
        if self.graph_depth < 0:
            raise InvalidArgumentError("graph_depth must be non-negative")


@dataclass(frozen=True, slots=True)
class WorkspaceWorkbenchPacket:
    """One host-renderable packet for human and agent collaborative workflows."""

    request: WorkspaceWorkbenchRequest
    state: CollaborativeWorkbenchState
    explorer: KnowledgeExplorerScreen | None = None
    note_panel: WorkbenchNotePanel | None = None
    review_inbox: WorkbenchReviewInbox = field(default_factory=WorkbenchReviewInbox)
    graph_panel: WorkbenchGraphPanelState | None = None
    candidate_review: CandidateReviewScreen | None = None
    repair_center: RepairCenterScreen | None = None
    record_detail: RecordDetailScreen | None = None
    publish: WorkbenchPublishOverlay | None = None
    workspace_revisions: tuple[WorkspaceRevision, ...] = ()
    workspace_diffs: tuple[WorkspaceDiffSummary, ...] = ()
    sync_status: WorkspaceSyncStatus | None = None
    sync_plan: WorkspaceSyncPlan | None = None
    action_previews: tuple[WorkbenchActionPreview, ...] = ()


def preview_workbench_action(
    request: WorkbenchActionRequest,
    *,
    gate: WorkspaceGateDecision | None = None,
    policy: WorkbenchPolicyOverlay | None = None,
    publish_plan: PublishPlan | None = None,
    provenance_refs: tuple[str, ...] = (),
) -> WorkbenchActionPreview:
    """Preview one action without mutating the graph or workspace."""

    status: WorkbenchActionStatus = "allowed"
    reason = "allowed"
    policy_messages: tuple[str, ...] = ()
    if gate is not None and not gate.allowed:
        status = "blocked"
        reason = gate.reason
    elif request.requires_review or (policy is not None and policy.review_required):
        status = "requires_review"
        reason = "review_required"
    elif request.action in {"open_graph_selection", "build_publish_plan"}:
        status = "preview_only"
        reason = "preview_only"
    if policy is not None:
        policy_messages = policy.messages
    return WorkbenchActionPreview(
        request=request,
        status=status,
        reason=reason,
        policy_messages=policy_messages,
        publish_impact=_publish_impact(publish_plan),
        provenance_refs=provenance_refs,
    )


def candidate_queue_item_to_review_item(
    item: CandidateQueueItem,
) -> WorkbenchReviewItem:
    """Map a candidate queue item into a workbench review row."""

    candidate = item.candidate
    return WorkbenchReviewItem(
        item_id=candidate.candidate_id,
        kind="candidate",
        title=candidate.title or candidate.candidate_id,
        status=candidate.status,
        target_id=candidate.candidate_id,
        proposer_id=candidate.session_id,
        evidence_count=item.evidence_count,
        allowed_actions=("approve_candidate", "reject_candidate"),
        preview=str(candidate.content.get("text", ""))[:240],
        policy_gate="reviewable" if item.reviewable else "missing_evidence",
        provenance_refs=tuple(candidate.evidence_refs),
    )


def repair_candidate_to_review_item(candidate: RepairCandidate) -> WorkbenchReviewItem:
    """Map an explicit repair candidate into a workbench review row."""

    return WorkbenchReviewItem(
        item_id=candidate.candidate_id,
        kind="repair",
        title=f"{candidate.action}: {candidate.finding_id}",
        status=candidate.status,
        target_id=str(candidate.patch.get("target_record_id") or candidate.finding_id),
        evidence_count=1,
        allowed_actions=("apply_repair",) if candidate.status == "pending" else (),
        preview=str(candidate.patch)[:240],
        provenance_refs=(candidate.finding_id,),
    )


def workspace_review_to_review_item(
    review: WorkspaceReviewRequest,
) -> WorkbenchReviewItem:
    """Map a workspace review request into a workbench review row."""

    return WorkbenchReviewItem(
        item_id=review.review_id,
        kind="workspace_review",
        title=f"{review.action}: {review.target_id}",
        status="pending",
        target_id=review.target_id,
        proposer_id=review.proposer_id,
        evidence_count=len(review.evidence_refs),
        allowed_actions=("approve_workspace_edit", "reject_workspace_edit"),
        provenance_refs=review.evidence_refs,
    )


def publish_plan_to_review_item(plan: PublishPlan) -> WorkbenchReviewItem:
    """Map a publish/share plan into a workbench review row."""

    return WorkbenchReviewItem(
        item_id=plan.profile.profile_id,
        kind="publish_request",
        title=f"{plan.profile.kind}: {plan.profile.profile_id}",
        status="pending",
        target_id=plan.profile.profile_id,
        evidence_count=len(plan.included_record_ids),
        allowed_actions=("build_publish_plan",),
        preview=(
            f"{len(plan.included_record_ids)} included, "
            f"{len(plan.omitted_record_ids)} omitted"
        ),
    )


def build_workbench_review_inbox(
    *,
    candidates: tuple[CandidateQueueItem, ...] = (),
    repairs: tuple[RepairCandidate, ...] = (),
    workspace_reviews: tuple[WorkspaceReviewRequest, ...] = (),
    publish_plans: tuple[PublishPlan, ...] = (),
    extra_items: tuple[WorkbenchReviewItem, ...] = (),
) -> WorkbenchReviewInbox:
    """Build a deterministic review inbox from existing package-owned queues."""

    items = [
        *(candidate_queue_item_to_review_item(candidate) for candidate in candidates),
        *(repair_candidate_to_review_item(repair) for repair in repairs),
        *(workspace_review_to_review_item(review) for review in workspace_reviews),
        *(publish_plan_to_review_item(plan) for plan in publish_plans),
        *extra_items,
    ]
    items.sort(key=lambda item: (item.kind, item.item_id))
    return WorkbenchReviewInbox(tuple(items))


def publish_overlay_from_plan(
    plan: PublishPlan,
    handoff: DeliveryHandoff | None = None,
) -> WorkbenchPublishOverlay:
    """Build publish overlay metadata from the package publish/share owner."""

    return WorkbenchPublishOverlay(
        profile_id=plan.profile.profile_id,
        profile_kind=plan.profile.kind,
        included_count=len(plan.included_record_ids),
        omitted_count=len(plan.omitted_record_ids),
        delivery_target=handoff.target if handoff is not None else "",
        payload_ref=handoff.payload_ref if handoff is not None else "",
    )


def note_panel_from_record_detail(
    screen: RecordDetailScreen,
    *,
    policy: WorkbenchPolicyOverlay | None = None,
    action_previews: tuple[WorkbenchActionPreview, ...] = (),
) -> WorkbenchNotePanel:
    """Build the active note panel from the existing record-detail screen."""

    packet = screen.packet
    record = packet.record
    return WorkbenchNotePanel(
        record_id=record.id,
        title=record.title or record.key or record.id,
        record_type=record.type,
        updated_at=record.updated_at,
        outgoing_count=len(packet.outgoing_links),
        backlink_count=len(packet.backlinks),
        related_record_ids=_related_record_ids(packet),
        block_count=len(packet.document_blocks),
        policy=policy or WorkbenchPolicyOverlay(),
        action_previews=action_previews,
    )


def build_workbench_graph_panel(
    graph: object,
    *,
    viewer_state: object | None = None,
    selected_node_id: str = "",
    embed_html: str = "",
) -> WorkbenchGraphPanelState:
    """Summarize a GraphFakos graph without depending on its private internals."""

    provider_id = str(getattr(graph, "provider_id", "graphfakos"))
    graph_role = str(getattr(graph, "graph_role", "memory"))
    nodes = getattr(graph, "nodes", ())
    edges = getattr(graph, "edges", ())
    return WorkbenchGraphPanelState(
        provider_id=provider_id,
        graph_role=graph_role,
        selected_node_id=selected_node_id,
        node_count=len(nodes),
        edge_count=len(edges),
        viewer_state=_to_public_dict(viewer_state),
        embed_html=embed_html,
    )


def build_workspace_workbench_packet(
    request: WorkspaceWorkbenchRequest,
    *,
    explorer: KnowledgeExplorerScreen | None = None,
    record_detail: RecordDetailScreen | None = None,
    candidate_review: CandidateReviewScreen | None = None,
    repair_center: RepairCenterScreen | None = None,
    review_inbox: WorkbenchReviewInbox | None = None,
    graph_panel: WorkbenchGraphPanelState | None = None,
    publish: WorkbenchPublishOverlay | None = None,
    workspace_revisions: tuple[WorkspaceRevision, ...] = (),
    workspace_diffs: tuple[WorkspaceDiffSummary, ...] = (),
    sync_status: WorkspaceSyncStatus | None = None,
    sync_plan: WorkspaceSyncPlan | None = None,
    action_previews: tuple[WorkbenchActionPreview, ...] = (),
    policy: WorkbenchPolicyOverlay | None = None,
) -> WorkspaceWorkbenchPacket:
    """Compose one collaborative workbench packet from existing package surfaces."""

    selected_record_id = request.root_record_id
    note_panel = None
    if record_detail is not None:
        note_panel = note_panel_from_record_detail(
            record_detail,
            policy=policy,
            action_previews=action_previews,
        )
        selected_record_id = note_panel.record_id
    return WorkspaceWorkbenchPacket(
        request=request,
        state=CollaborativeWorkbenchState(
            workspace_id=request.workspace_id,
            selected_record_id=selected_record_id,
            actor_id=request.actor_id,
        ),
        explorer=explorer,
        note_panel=note_panel,
        review_inbox=review_inbox or WorkbenchReviewInbox(),
        graph_panel=graph_panel,
        candidate_review=candidate_review,
        repair_center=repair_center,
        record_detail=record_detail,
        publish=publish,
        workspace_revisions=workspace_revisions,
        workspace_diffs=workspace_diffs,
        sync_status=sync_status,
        sync_plan=sync_plan,
        action_previews=action_previews,
    )


def workbench_to_dict(packet: WorkspaceWorkbenchPacket) -> dict[str, Any]:
    """Return a JSON-compatible dictionary for a workbench packet."""

    return _to_public_dict(packet)


def _publish_impact(plan: PublishPlan | None) -> tuple[str, ...]:
    if plan is None:
        return ()
    return (
        f"included:{len(plan.included_record_ids)}",
        f"omitted:{len(plan.omitted_record_ids)}",
        f"profile:{plan.profile.kind}",
    )


def _related_record_ids(packet: object) -> tuple[str, ...]:
    graph = getattr(packet, "graph", None)
    record = getattr(packet, "record", None)
    record_id = getattr(record, "id", "")
    if graph is None:
        return ()
    ids = []
    for node in getattr(graph, "nodes", ()):
        node_id = str(getattr(node, "record_id", ""))
        if node_id and node_id != record_id:
            ids.append(node_id)
    return tuple(ids)


def _to_public_dict(value: object) -> dict[str, Any]:
    if value is None:
        return {}
    if hasattr(value, "to_dict"):
        result = value.to_dict()  # type: ignore[no-untyped-call]
        return dict(result) if isinstance(result, dict) else {"value": result}
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, dict):
        return dict(value)
    return {"value": str(value)}


__all__ = [
    "CollaborativeWorkbenchState",
    "WorkbenchActionKind",
    "WorkbenchActionPreview",
    "WorkbenchActionRequest",
    "WorkbenchActionStatus",
    "WorkbenchGraphPanelState",
    "WorkbenchNotePanel",
    "WorkbenchPolicyOverlay",
    "WorkbenchPublishOverlay",
    "WorkbenchReviewInbox",
    "WorkbenchReviewItem",
    "WorkbenchReviewItemKind",
    "WorkspaceWorkbenchPacket",
    "WorkspaceWorkbenchRequest",
    "build_workbench_graph_panel",
    "build_workbench_review_inbox",
    "build_workspace_workbench_packet",
    "candidate_queue_item_to_review_item",
    "note_panel_from_record_detail",
    "preview_workbench_action",
    "publish_overlay_from_plan",
    "publish_plan_to_review_item",
    "repair_candidate_to_review_item",
    "workbench_to_dict",
    "workspace_review_to_review_item",
]
