"""Candidate queue, review, and explicit promotion helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol
from uuid import uuid4

from sophiagraph.audit.events import (
    MemoryAuditEvent,
    MemoryAuditRecorder,
    noop_audit_recorder,
)
from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.models import (
    ArtifactRef,
    CandidateReview,
    MemoryCandidate,
    MemoryNamespace,
)
from sophiagraph.models.namespace import sorted_namespace_key
from sophiagraph.query import CandidateListOptions
from sophiagraph.storage.base import SophiaGraphStore
from sophiagraph.temporal import utc_now_iso

CandidateReviewAction = Literal["approve", "reject"]
CandidateReviewStatus = Literal["proposed", "approved", "rejected", "promoted"]


class CandidateReviewStore(Protocol):
    """Store subset used by candidate review helpers."""

    def get_candidate(self, candidate_id: str) -> MemoryCandidate | None: ...

    def list_candidates(
        self, options: CandidateListOptions
    ) -> list[MemoryCandidate]: ...

    def update_candidate(
        self,
        candidate_id: str,
        patch: dict[str, Any],
    ) -> MemoryCandidate: ...


@dataclass(frozen=True, slots=True)
class CandidateQueueOptions:
    """Structural filters for candidate review queues."""

    session_id: str | None = None
    proposed_scope: str | None = None
    status: CandidateReviewStatus | None = "proposed"
    min_confidence: float | None = None
    source_class: str | None = None
    require_evidence: bool = False
    limit: int | None = None

    def __post_init__(self) -> None:
        if self.min_confidence is not None and not 0 <= self.min_confidence <= 1:
            raise InvalidArgumentError("min_confidence must be between 0 and 1")
        if self.limit is not None and self.limit <= 0:
            raise InvalidArgumentError("limit must be positive")


@dataclass(frozen=True, slots=True)
class CandidateQueueItem:
    """One candidate row with review metadata useful to callers."""

    candidate: MemoryCandidate
    evidence_count: int
    namespace_key: str
    reviewable: bool

    def __post_init__(self) -> None:
        if not isinstance(self.candidate, MemoryCandidate):
            raise InvalidArgumentError("candidate must be a MemoryCandidate")
        if self.evidence_count < 0:
            raise InvalidArgumentError("evidence_count must be non-negative")
        if not self.namespace_key:
            raise InvalidArgumentError("namespace_key is required")


@dataclass(frozen=True, slots=True)
class CandidateReviewDecision:
    """Explicit human or host decision for one candidate."""

    candidate_id: str
    action: CandidateReviewAction
    reviewer: str
    decided_at: str = ""
    note: str | None = None

    def __post_init__(self) -> None:
        if not self.candidate_id:
            raise InvalidArgumentError("candidate_id is required")
        if self.action not in {"approve", "reject"}:
            raise InvalidArgumentError(f"invalid review action: {self.action!r}")
        if not self.reviewer:
            raise InvalidArgumentError("reviewer is required")


@dataclass(frozen=True, slots=True)
class CandidatePromotionPlan:
    """Explicit plan to promote an approved candidate into a record."""

    candidate_id: str
    target_scope: str
    reviewer: str
    evidence_refs: tuple[str, ...]
    plan_id: str = field(default_factory=lambda: f"promotion-plan-{uuid4().hex}")
    created_at: str = field(default_factory=utc_now_iso)
    provenance: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.plan_id:
            raise InvalidArgumentError("plan_id is required")
        if not self.candidate_id:
            raise InvalidArgumentError("candidate_id is required")
        if not self.target_scope:
            raise InvalidArgumentError("target_scope is required")
        if not self.reviewer:
            raise InvalidArgumentError("reviewer is required")
        if not self.evidence_refs:
            raise InvalidArgumentError("promotion requires explicit evidence_refs")
        if any(not ref for ref in self.evidence_refs):
            raise InvalidArgumentError("evidence_refs must be non-empty strings")
        if not isinstance(self.provenance, dict):
            raise InvalidArgumentError("provenance must be a dict")


@dataclass(frozen=True, slots=True)
class CandidatePromotionResult:
    """Result of applying a promotion plan."""

    plan: CandidatePromotionPlan
    record_id: str
    candidate_id: str
    audit_events: tuple[MemoryAuditEvent, ...] = ()

    def __post_init__(self) -> None:
        if not self.record_id:
            raise InvalidArgumentError("record_id is required")
        if self.candidate_id != self.plan.candidate_id:
            raise InvalidArgumentError("result candidate_id must match plan")


def list_candidate_queue(
    store: CandidateReviewStore,
    options: CandidateQueueOptions | None = None,
) -> list[CandidateQueueItem]:
    """Return a deterministic candidate review queue."""

    opts = options or CandidateQueueOptions()
    candidates = store.list_candidates(
        CandidateListOptions(
            session_id=opts.session_id,
            proposed_scope=opts.proposed_scope,
            status=opts.status,
            limit=None,
        )
    )
    if opts.min_confidence is not None:
        candidates = [
            candidate
            for candidate in candidates
            if candidate.confidence >= opts.min_confidence
        ]
    if opts.source_class is not None:
        candidates = [
            candidate
            for candidate in candidates
            if candidate.source_class == opts.source_class
        ]
    if opts.require_evidence:
        candidates = [candidate for candidate in candidates if candidate.evidence_refs]
    items = [_queue_item(candidate) for candidate in candidates]
    items.sort(
        key=lambda item: (
            item.candidate.updated_at or item.candidate.created_at or "",
            item.candidate.candidate_id,
        ),
        reverse=True,
    )
    return items[: opts.limit] if opts.limit is not None else items


def apply_candidate_review(
    store: CandidateReviewStore,
    decision: CandidateReviewDecision,
    *,
    audit_recorder: MemoryAuditRecorder = noop_audit_recorder,
) -> MemoryCandidate:
    """Apply an explicit approve/reject decision to a candidate."""

    candidate = store.get_candidate(decision.candidate_id)
    if candidate is None:
        raise InvalidArgumentError(f"unknown candidate_id: {decision.candidate_id}")
    decided_at = decision.decided_at or utc_now_iso()
    status = "approved" if decision.action == "approve" else "rejected"
    updated = store.update_candidate(
        decision.candidate_id,
        {
            "status": status,
            "review": CandidateReview(
                reviewer=decision.reviewer,
                decided_at=decided_at,
                note=decision.note,
            ),
        },
    )
    audit_recorder(
        _candidate_audit_event(
            event_type=f"memory.candidate_review.{decision.action}",
            candidate=updated,
            details={
                "reviewer": decision.reviewer,
                "decided_at": decided_at,
                "note": decision.note,
            },
        )
    )
    return updated


def build_candidate_promotion_plan(
    store: CandidateReviewStore,
    *,
    candidate_id: str,
    target_scope: str,
    reviewer: str,
    evidence_refs: tuple[str, ...] | None = None,
    provenance: dict[str, Any] | None = None,
) -> CandidatePromotionPlan:
    """Build a promotion plan from an already-approved candidate."""

    candidate = store.get_candidate(candidate_id)
    if candidate is None:
        raise InvalidArgumentError(f"unknown candidate_id: {candidate_id}")
    if candidate.status != "approved":
        raise InvalidArgumentError("candidate must be approved before promotion")
    refs = evidence_refs or _artifact_ref_ids(candidate.evidence_refs)
    return CandidatePromotionPlan(
        candidate_id=candidate_id,
        target_scope=target_scope,
        reviewer=reviewer,
        evidence_refs=tuple(refs),
        provenance=dict(provenance or {}),
    )


def apply_candidate_promotion_plan(
    store: SophiaGraphStore,
    plan: CandidatePromotionPlan,
    *,
    audit_recorder: MemoryAuditRecorder = noop_audit_recorder,
) -> CandidatePromotionResult:
    """Apply one explicit promotion plan through the canonical store method."""

    candidate = store.get_candidate(plan.candidate_id)
    if candidate is None:
        raise InvalidArgumentError(f"unknown candidate_id: {plan.candidate_id}")
    if candidate.status != "approved":
        raise InvalidArgumentError("candidate must be approved before promotion")
    if not set(plan.evidence_refs).issubset(
        set(_artifact_ref_ids(candidate.evidence_refs))
    ):
        raise InvalidArgumentError("promotion evidence_refs must come from candidate")
    record = store.promote_candidate(plan.candidate_id, plan.target_scope)
    event = _candidate_audit_event(
        event_type="memory.candidate_review.promote",
        candidate=store.get_candidate(plan.candidate_id) or candidate,
        target_id=record.id,
        details={
            "plan_id": plan.plan_id,
            "reviewer": plan.reviewer,
            "target_scope": plan.target_scope,
            "evidence_refs": list(plan.evidence_refs),
            "provenance": dict(plan.provenance),
        },
    )
    audit_recorder(event)
    return CandidatePromotionResult(
        plan=plan,
        record_id=record.id,
        candidate_id=plan.candidate_id,
        audit_events=(event,),
    )


def _artifact_ref_ids(refs: list[ArtifactRef]) -> tuple[str, ...]:
    return tuple(ref.ref for ref in refs)


def _queue_item(candidate: MemoryCandidate) -> CandidateQueueItem:
    namespace = candidate.namespace or MemoryNamespace.from_scope(
        candidate.proposed_scope
    )
    namespace_key = sorted_namespace_key(namespace)
    return CandidateQueueItem(
        candidate=candidate,
        evidence_count=len(candidate.evidence_refs),
        namespace_key=namespace_key,
        reviewable=candidate.status in {"proposed", "approved"},
    )


def _candidate_audit_event(
    *,
    event_type: str,
    candidate: MemoryCandidate,
    target_id: str | None = None,
    details: dict[str, Any],
) -> MemoryAuditEvent:
    namespace = candidate.namespace or MemoryNamespace.from_scope(
        candidate.proposed_scope
    )
    return MemoryAuditEvent(
        event_type=event_type,
        target_kind="candidate",
        target_id=target_id or candidate.candidate_id,
        scope=candidate.proposed_scope,
        record_type=candidate.type,
        session_id=candidate.session_id,
        details={
            **details,
            "candidate_id": candidate.candidate_id,
            "candidate_status": candidate.status,
            "namespace": namespace.as_dict(),
        },
    )


__all__ = [
    "CandidatePromotionPlan",
    "CandidatePromotionResult",
    "CandidateQueueItem",
    "CandidateQueueOptions",
    "CandidateReviewAction",
    "CandidateReviewDecision",
    "CandidateReviewStatus",
    "CandidateReviewStore",
    "apply_candidate_promotion_plan",
    "apply_candidate_review",
    "build_candidate_promotion_plan",
    "list_candidate_queue",
]
