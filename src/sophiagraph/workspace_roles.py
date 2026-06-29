"""Typed local-first workspace roles, permissions, and review gates."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import uuid4

from sophiagraph.audit.events import MemoryAuditEvent
from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.models import MemoryNamespace
from sophiagraph.temporal import utc_now_iso

WorkspaceRoleName = Literal["owner", "maintainer", "reviewer", "viewer"]
WorkspacePermission = Literal["read", "propose", "review", "apply", "admin"]
ReviewDecision = Literal["approved", "rejected"]

_WORKSPACE_PERMISSIONS: frozenset[WorkspacePermission] = frozenset(
    ("read", "propose", "review", "apply", "admin")
)
_REVIEW_DECISIONS: frozenset[ReviewDecision] = frozenset({"approved", "rejected"})

ROLE_PERMISSIONS: dict[WorkspaceRoleName, frozenset[WorkspacePermission]] = {
    "owner": _WORKSPACE_PERMISSIONS,
    "maintainer": frozenset({"read", "propose", "review", "apply"}),
    "reviewer": frozenset({"read", "propose", "review"}),
    "viewer": frozenset({"read"}),
}


@dataclass(frozen=True, slots=True)
class WorkspaceRoleBinding:
    """One actor role in a local-first workspace."""

    workspace_id: str
    actor_id: str
    role: WorkspaceRoleName
    namespace: MemoryNamespace | None = None

    def __post_init__(self) -> None:
        if not self.workspace_id:
            raise InvalidArgumentError("workspace_id is required")
        if not self.actor_id:
            raise InvalidArgumentError("actor_id is required")
        if self.role not in ROLE_PERMISSIONS:
            raise InvalidArgumentError(f"invalid role: {self.role!r}")

    @property
    def permissions(self) -> frozenset[WorkspacePermission]:
        return ROLE_PERMISSIONS[self.role]


@dataclass(frozen=True, slots=True)
class WorkspaceActionRequest:
    """One requested workspace action to gate structurally."""

    workspace_id: str
    actor_id: str
    action: WorkspacePermission
    target_id: str
    payload_kind: str = "record"
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.workspace_id:
            raise InvalidArgumentError("workspace_id is required")
        if not self.actor_id:
            raise InvalidArgumentError("actor_id is required")
        if self.action not in _WORKSPACE_PERMISSIONS:
            raise InvalidArgumentError(f"invalid action: {self.action!r}")
        if not self.target_id:
            raise InvalidArgumentError("target_id is required")


@dataclass(frozen=True, slots=True)
class WorkspaceGateDecision:
    """Allow/deny result for a role-gated workspace action."""

    allowed: bool
    actor_id: str
    action: WorkspacePermission
    reason: str
    role: WorkspaceRoleName | None = None


@dataclass(frozen=True, slots=True)
class WorkspaceReviewRequest:
    """Explicit review request for shared workspace changes."""

    review_id: str
    workspace_id: str
    proposer_id: str
    target_id: str
    action: WorkspacePermission = "apply"
    created_at: str = field(default_factory=utc_now_iso)
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.review_id:
            raise InvalidArgumentError("review_id is required")
        if not self.workspace_id:
            raise InvalidArgumentError("workspace_id is required")
        if not self.proposer_id:
            raise InvalidArgumentError("proposer_id is required")
        if not self.target_id:
            raise InvalidArgumentError("target_id is required")


@dataclass(frozen=True, slots=True)
class WorkspaceReviewDecision:
    """Explicit approve/reject decision for a review request."""

    review_id: str
    reviewer_id: str
    decision: ReviewDecision
    decided_at: str = field(default_factory=utc_now_iso)
    note: str = ""

    def __post_init__(self) -> None:
        if not self.review_id:
            raise InvalidArgumentError("review_id is required")
        if not self.reviewer_id:
            raise InvalidArgumentError("reviewer_id is required")
        if self.decision not in _REVIEW_DECISIONS:
            raise InvalidArgumentError(f"invalid review decision: {self.decision!r}")


def evaluate_workspace_action(
    bindings: tuple[WorkspaceRoleBinding, ...],
    request: WorkspaceActionRequest,
) -> WorkspaceGateDecision:
    """Evaluate one structural role gate without hosted auth semantics."""

    for binding in bindings:
        if (
            binding.workspace_id == request.workspace_id
            and binding.actor_id == request.actor_id
        ):
            allowed = request.action in binding.permissions
            return WorkspaceGateDecision(
                allowed=allowed,
                actor_id=request.actor_id,
                action=request.action,
                role=binding.role,
                reason="allowed" if allowed else "permission_denied",
            )
    return WorkspaceGateDecision(
        allowed=False,
        actor_id=request.actor_id,
        action=request.action,
        role=None,
        reason="role_not_found",
    )


def create_workspace_review_request(
    *,
    workspace_id: str,
    proposer_id: str,
    target_id: str,
    action: WorkspacePermission = "apply",
    evidence_refs: tuple[str, ...] = (),
) -> WorkspaceReviewRequest:
    """Create an explicit review request."""

    return WorkspaceReviewRequest(
        review_id=f"workspace-review-{uuid4().hex}",
        workspace_id=workspace_id,
        proposer_id=proposer_id,
        target_id=target_id,
        action=action,
        evidence_refs=evidence_refs,
    )


def apply_workspace_review_decision(
    review: WorkspaceReviewRequest,
    decision: WorkspaceReviewDecision,
) -> MemoryAuditEvent:
    """Build a typed audit event for an explicit review outcome."""

    if review.review_id != decision.review_id:
        raise InvalidArgumentError("decision review_id must match review")
    return MemoryAuditEvent(
        event_type="workspace.review_decision",
        target_kind="workspace_review",
        target_id=review.target_id,
        scope=review.workspace_id,
        details={
            "review_id": review.review_id,
            "decision": decision.decision,
            "action": review.action,
            "proposer_id": review.proposer_id,
            "reviewer_id": decision.reviewer_id,
            "note": decision.note,
        },
    )


__all__ = [
    "ROLE_PERMISSIONS",
    "WorkspaceActionRequest",
    "WorkspaceGateDecision",
    "WorkspacePermission",
    "WorkspaceReviewDecision",
    "WorkspaceReviewRequest",
    "WorkspaceRoleBinding",
    "WorkspaceRoleName",
    "apply_workspace_review_decision",
    "create_workspace_review_request",
    "evaluate_workspace_action",
]
