"""Lifecycle behavior over typed self-improving memory contracts."""

from __future__ import annotations

from dataclasses import replace

from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.models.candidate import MemoryCandidate
from sophiagraph.models.namespace import sorted_namespace_key
from sophiagraph.models.self_improvement_types import (
    ACTIVE_RETRIEVAL_STATES,
    ALLOWED_LIFECYCLE_TRANSITIONS,
    ATTRIBUTION_OUTCOMES,
    AttributionOutcome,
    CONTRADICTION_DECISIONS,
    ContradictionDecision,
    EVIDENCE_DEGRADATION_OUTCOMES,
    EVIDENCE_FRESHNESS_STATES,
    EvidenceFreshnessState,
    MEMORY_LIFECYCLE_KINDS,
    MEMORY_LIFECYCLE_STATES,
    MemoryAttributionUpdate,
    MemoryContradictionLink,
    MemoryEvidenceLink,
    MemoryLifecycleEvent,
    MemoryLifecycleKind,
    MemoryLifecycleState,
    MemoryRetrievalPacket,
    NARROW_RETRIEVAL_STATES,
    SelfImprovingMemoryLifecycle,
    TERMINAL_LIFECYCLE_STATES,
    assert_member,
)


def lifecycle_from_candidate(
    candidate: MemoryCandidate,
    *,
    memory_id: str,
    kind: MemoryLifecycleKind,
    evidence_refs: tuple[MemoryEvidenceLink, ...] = (),
    namespace_ref: str | None = None,
) -> SelfImprovingMemoryLifecycle:
    """Stage one OpenMinion-submitted candidate as durable lifecycle state."""
    return SelfImprovingMemoryLifecycle(
        memory_id=memory_id,
        candidate_id=candidate.candidate_id,
        namespace_ref=namespace_ref or _candidate_namespace_ref(candidate),
        kind=kind,
        trust_state="candidate",
        trust_score=candidate.confidence,
        evidence_refs=evidence_refs,
    )


def transition_lifecycle(
    lifecycle: SelfImprovingMemoryLifecycle,
    *,
    to_state: MemoryLifecycleState,
    reason_code: str,
    actor: str,
    observed_at: str,
    evidence_refs: tuple[MemoryEvidenceLink, ...] = (),
    superseded_by_memory_id: str | None = None,
    suppression_reason: str | None = None,
) -> SelfImprovingMemoryLifecycle:
    """Apply one explicit lifecycle transition and append an audit event."""
    target_state = assert_member(to_state, MEMORY_LIFECYCLE_STATES, "to_state")
    allowed = ALLOWED_LIFECYCLE_TRANSITIONS[lifecycle.trust_state]
    if target_state not in allowed:
        raise InvalidArgumentError(
            f"invalid lifecycle transition: {lifecycle.trust_state!r} -> {target_state!r}"
        )
    event = MemoryLifecycleEvent(
        event_id=f"{lifecycle.memory_id}:{len(lifecycle.history) + 1}",
        from_state=lifecycle.trust_state,
        to_state=target_state,
        reason_code=reason_code,
        actor=actor,
        observed_at=observed_at,
        evidence_refs=evidence_refs,
    )
    score = _score_for_transition(lifecycle.trust_score, target_state)
    return replace(
        lifecycle,
        trust_state=target_state,
        trust_score=score,
        history=(*lifecycle.history, event),
        evidence_refs=(*lifecycle.evidence_refs, *evidence_refs),
        superseded_by_memory_id=superseded_by_memory_id,
        suppression_reason=suppression_reason,
    )


def apply_attribution_update(
    lifecycle: SelfImprovingMemoryLifecycle,
    update: MemoryAttributionUpdate,
    *,
    actor: str = "system",
) -> SelfImprovingMemoryLifecycle:
    """Apply a structural later-outcome update to lifecycle trust."""
    if update.memory_id != lifecycle.memory_id:
        raise InvalidArgumentError(
            "attribution update memory_id does not match lifecycle"
        )
    if lifecycle.trust_state in TERMINAL_LIFECYCLE_STATES:
        raise InvalidArgumentError("terminal lifecycle state cannot be updated")

    next_state = lifecycle.trust_state
    next_score = lifecycle.trust_score
    suppression_reason = lifecycle.suppression_reason
    superseded_by_memory_id = lifecycle.superseded_by_memory_id

    if update.outcome == "positive":
        next_score = min(1.0, next_score + update.weight)
        if lifecycle.trust_state == "candidate" and next_score >= 0.6:
            next_state = "provisional"
        elif lifecycle.trust_state == "provisional" and next_score >= 0.8:
            next_state = "trusted"
    elif update.outcome in {"negative", "mixed", "re_review"}:
        next_score = max(0.0, next_score - update.weight)
        if lifecycle.trust_state == "trusted":
            next_state = "provisional"
        elif lifecycle.trust_state == "provisional":
            next_state = "candidate"
    elif update.outcome in EVIDENCE_DEGRADATION_OUTCOMES:
        next_score = max(0.0, next_score - update.weight)
        if lifecycle.trust_state in {"trusted", "pinned"}:
            next_state = "provisional"
        elif lifecycle.trust_state == "provisional":
            next_state = "candidate"
    elif update.outcome == "operator_pin":
        next_score = max(next_score, 1.0)
        next_state = "pinned"
    elif update.outcome == "operator_unpin":
        next_state = "trusted"
    elif update.outcome == "suppress":
        next_score = 0.0
        next_state = "suppressed"
        suppression_reason = _first_reason(update, default="attribution_suppressed")
    elif update.outcome == "supersede":
        next_state = "superseded"
        superseded_by_memory_id = update.superseded_by_memory_id

    if next_state == lifecycle.trust_state and next_score != lifecycle.trust_score:
        return replace(
            lifecycle,
            trust_score=next_score,
            evidence_refs=(*lifecycle.evidence_refs, *update.evidence_refs),
        )
    return transition_lifecycle(
        replace(lifecycle, trust_score=next_score),
        to_state=next_state,
        reason_code=_first_reason(update, default=f"attribution_{update.outcome}"),
        actor=actor,
        observed_at=update.observed_at,
        evidence_refs=update.evidence_refs,
        superseded_by_memory_id=superseded_by_memory_id,
        suppression_reason=suppression_reason,
    )


def attach_contradiction(
    lifecycle: SelfImprovingMemoryLifecycle,
    link: MemoryContradictionLink,
    *,
    actor: str = "system",
) -> SelfImprovingMemoryLifecycle:
    """Attach an explicit contradiction or supersession link without guessing content."""
    if link.target_memory_id != lifecycle.memory_id:
        raise InvalidArgumentError("contradiction target does not match lifecycle")
    linked = replace(
        lifecycle,
        contradiction_links=(*lifecycle.contradiction_links, link),
        evidence_refs=(*lifecycle.evidence_refs, *link.evidence_refs),
    )
    if link.decision == "suppress_target":
        return transition_lifecycle(
            linked,
            to_state="suppressed",
            reason_code=link.reason_code,
            actor=actor,
            observed_at=link.observed_at,
            evidence_refs=link.evidence_refs,
            suppression_reason=link.reason_code,
        )
    if link.decision == "supersede_target":
        return transition_lifecycle(
            linked,
            to_state="superseded",
            reason_code=link.reason_code,
            actor=actor,
            observed_at=link.observed_at,
            evidence_refs=link.evidence_refs,
            superseded_by_memory_id=link.contradicting_memory_id,
        )
    if link.decision == "mark_for_review" and linked.trust_state == "trusted":
        return transition_lifecycle(
            linked,
            to_state="provisional",
            reason_code=link.reason_code,
            actor=actor,
            observed_at=link.observed_at,
            evidence_refs=link.evidence_refs,
        )
    return linked


def build_memory_retrieval_packet(
    lifecycle: SelfImprovingMemoryLifecycle,
    *,
    packet_id: str,
    include_narrow: bool = False,
) -> MemoryRetrievalPacket:
    """Build a compact OpenMinion-facing packet from lifecycle state."""
    omitted_reason: str | None = None
    reason_codes: tuple[str, ...]
    if lifecycle.trust_state in ACTIVE_RETRIEVAL_STATES:
        reason_codes = ("trusted_retrieval",)
    elif include_narrow and lifecycle.trust_state in NARROW_RETRIEVAL_STATES:
        reason_codes = ("narrow_retrieval",)
    else:
        reason_codes = ()
        omitted_reason = f"trust_state_{lifecycle.trust_state}"
    return MemoryRetrievalPacket(
        packet_id=packet_id,
        namespace_ref=lifecycle.namespace_ref,
        kind=lifecycle.kind,
        trust_state=lifecycle.trust_state,
        trust_score=lifecycle.trust_score,
        retrieval_reason_codes=reason_codes,
        memory_refs=() if omitted_reason else lifecycle.memory_refs,
        pragma_refs=() if omitted_reason else lifecycle.pragma_refs,
        summary_block_ids=() if omitted_reason else lifecycle.summary_block_ids,
        omitted_reason=omitted_reason,
    )


def _first_reason(update: MemoryAttributionUpdate, *, default: str) -> str:
    return update.reason_codes[0] if update.reason_codes else default


def _candidate_namespace_ref(candidate: MemoryCandidate) -> str:
    if candidate.namespace is None:
        return candidate.proposed_scope
    return sorted_namespace_key(candidate.namespace)


def _score_for_transition(score: float, state: str) -> float:
    floors = {
        "candidate": min(score, 0.59),
        "provisional": max(score, 0.6),
        "trusted": max(score, 0.8),
        "pinned": 1.0,
        "suppressed": 0.0,
        "superseded": score,
    }
    return floors[state]


__all__ = [
    "ACTIVE_RETRIEVAL_STATES",
    "ATTRIBUTION_OUTCOMES",
    "AttributionOutcome",
    "CONTRADICTION_DECISIONS",
    "ContradictionDecision",
    "EVIDENCE_FRESHNESS_STATES",
    "EvidenceFreshnessState",
    "MEMORY_LIFECYCLE_KINDS",
    "MEMORY_LIFECYCLE_STATES",
    "MemoryAttributionUpdate",
    "MemoryContradictionLink",
    "MemoryEvidenceLink",
    "MemoryLifecycleEvent",
    "MemoryLifecycleKind",
    "MemoryLifecycleState",
    "MemoryRetrievalPacket",
    "NARROW_RETRIEVAL_STATES",
    "SelfImprovingMemoryLifecycle",
    "TERMINAL_LIFECYCLE_STATES",
    "apply_attribution_update",
    "attach_contradiction",
    "build_memory_retrieval_packet",
    "lifecycle_from_candidate",
    "transition_lifecycle",
]
