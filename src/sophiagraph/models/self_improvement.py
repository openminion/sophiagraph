"""Typed lifecycle contracts for self-improving durable memory."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Final, Literal

from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.models.candidate import MemoryCandidate
from sophiagraph.models.namespace import sorted_namespace_key

MemoryLifecycleState = Literal[
    "candidate",
    "provisional",
    "trusted",
    "pinned",
    "suppressed",
    "superseded",
]
MemoryLifecycleKind = Literal[
    "lesson",
    "procedure",
    "preference",
    "goal_revision",
    "failure_pattern",
    "strategy_outcome",
]
EvidenceFreshnessState = Literal["fresh", "stale", "missing", "changed"]
AttributionOutcome = Literal[
    "positive",
    "negative",
    "mixed",
    "evidence_stale",
    "evidence_missing",
    "evidence_changed",
    "operator_pin",
    "operator_unpin",
    "suppress",
    "supersede",
    "re_review",
]
ContradictionDecision = Literal[
    "mark_for_review",
    "suppress_target",
    "supersede_target",
    "keep_both",
]

MEMORY_LIFECYCLE_STATES: Final[frozenset[str]] = frozenset(
    {
        "candidate",
        "provisional",
        "trusted",
        "pinned",
        "suppressed",
        "superseded",
    }
)
MEMORY_LIFECYCLE_KINDS: Final[frozenset[str]] = frozenset(
    {
        "lesson",
        "procedure",
        "preference",
        "goal_revision",
        "failure_pattern",
        "strategy_outcome",
    }
)
EVIDENCE_FRESHNESS_STATES: Final[frozenset[str]] = frozenset(
    {"fresh", "stale", "missing", "changed"}
)
ATTRIBUTION_OUTCOMES: Final[frozenset[str]] = frozenset(
    {
        "positive",
        "negative",
        "mixed",
        "evidence_stale",
        "evidence_missing",
        "evidence_changed",
        "operator_pin",
        "operator_unpin",
        "suppress",
        "supersede",
        "re_review",
    }
)
CONTRADICTION_DECISIONS: Final[frozenset[str]] = frozenset(
    {
        "mark_for_review",
        "suppress_target",
        "supersede_target",
        "keep_both",
    }
)

TERMINAL_LIFECYCLE_STATES: Final[frozenset[str]] = frozenset(
    {"suppressed", "superseded"}
)
ACTIVE_RETRIEVAL_STATES: Final[frozenset[str]] = frozenset({"trusted", "pinned"})
NARROW_RETRIEVAL_STATES: Final[frozenset[str]] = frozenset({"provisional"})

_ALLOWED_TRANSITIONS: Final[dict[str, frozenset[str]]] = {
    "candidate": frozenset({"provisional", "suppressed", "superseded"}),
    "provisional": frozenset({"candidate", "trusted", "suppressed", "superseded"}),
    "trusted": frozenset({"provisional", "pinned", "suppressed", "superseded"}),
    "pinned": frozenset({"trusted", "superseded"}),
    "suppressed": frozenset(),
    "superseded": frozenset(),
}
_EVIDENCE_DEGRADATION_OUTCOMES: Final[frozenset[str]] = frozenset(
    {"evidence_stale", "evidence_missing", "evidence_changed"}
)


def _assert_non_empty(value: str, label: str) -> str:
    text = str(value or "")
    if not text:
        raise InvalidArgumentError(f"{label} is required")
    return text


def _assert_member(value: str, allowed: frozenset[str], label: str) -> str:
    text = str(value or "")
    if text not in allowed:
        raise InvalidArgumentError(f"invalid {label}: {value!r}")
    return text


def _assert_score(value: float, label: str) -> float:
    score = float(value)
    if not 0.0 <= score <= 1.0:
        raise InvalidArgumentError(f"{label} must be between 0 and 1 inclusive")
    return score


def _pragma_refs(refs: tuple["MemoryEvidenceLink", ...]) -> tuple[str, ...]:
    return tuple(ref.ref_uri for ref in refs if ref.ref_uri.startswith("pragma://"))


@dataclass(frozen=True)
class MemoryEvidenceLink:
    """Durable citation to external evidence backing one memory."""

    ref_uri: str
    freshness_state: EvidenceFreshnessState = "fresh"
    reason_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "ref_uri", _assert_non_empty(self.ref_uri, "ref_uri"))
        object.__setattr__(
            self,
            "freshness_state",
            _assert_member(
                self.freshness_state,
                EVIDENCE_FRESHNESS_STATES,
                "freshness_state",
            ),
        )
        object.__setattr__(
            self,
            "reason_codes",
            tuple(str(code) for code in self.reason_codes if str(code)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "ref_uri": self.ref_uri,
            "freshness_state": self.freshness_state,
            "reason_codes": list(self.reason_codes),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "MemoryEvidenceLink":
        return cls(
            ref_uri=str(payload.get("ref_uri", "") or ""),
            freshness_state=str(payload.get("freshness_state", "fresh") or "fresh"),
            reason_codes=tuple(payload.get("reason_codes") or ()),
        )


@dataclass(frozen=True)
class MemoryLifecycleEvent:
    """Audit event for one explicit lifecycle state change."""

    event_id: str
    from_state: MemoryLifecycleState
    to_state: MemoryLifecycleState
    reason_code: str
    actor: str
    observed_at: str
    evidence_refs: tuple[MemoryEvidenceLink, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "event_id", _assert_non_empty(self.event_id, "event_id")
        )
        object.__setattr__(
            self,
            "from_state",
            _assert_member(self.from_state, MEMORY_LIFECYCLE_STATES, "from_state"),
        )
        object.__setattr__(
            self,
            "to_state",
            _assert_member(self.to_state, MEMORY_LIFECYCLE_STATES, "to_state"),
        )
        object.__setattr__(
            self, "reason_code", _assert_non_empty(self.reason_code, "reason_code")
        )
        object.__setattr__(self, "actor", _assert_non_empty(self.actor, "actor"))
        object.__setattr__(
            self, "observed_at", _assert_non_empty(self.observed_at, "observed_at")
        )
        object.__setattr__(self, "evidence_refs", tuple(self.evidence_refs))

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "from_state": self.from_state,
            "to_state": self.to_state,
            "reason_code": self.reason_code,
            "actor": self.actor,
            "observed_at": self.observed_at,
            "evidence_refs": [ref.to_dict() for ref in self.evidence_refs],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "MemoryLifecycleEvent":
        return cls(
            event_id=str(payload.get("event_id", "") or ""),
            from_state=str(payload.get("from_state", "") or ""),
            to_state=str(payload.get("to_state", "") or ""),
            reason_code=str(payload.get("reason_code", "") or ""),
            actor=str(payload.get("actor", "") or ""),
            observed_at=str(payload.get("observed_at", "") or ""),
            evidence_refs=tuple(
                MemoryEvidenceLink.from_dict(item)
                for item in payload.get("evidence_refs", ())
            ),
        )


@dataclass(frozen=True)
class MemoryContradictionLink:
    """Typed link between two durable memories that need review."""

    link_id: str
    target_memory_id: str
    contradicting_memory_id: str
    decision: ContradictionDecision
    reason_code: str
    observed_at: str
    evidence_refs: tuple[MemoryEvidenceLink, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "link_id", _assert_non_empty(self.link_id, "link_id"))
        object.__setattr__(
            self,
            "target_memory_id",
            _assert_non_empty(self.target_memory_id, "target_memory_id"),
        )
        object.__setattr__(
            self,
            "contradicting_memory_id",
            _assert_non_empty(
                self.contradicting_memory_id,
                "contradicting_memory_id",
            ),
        )
        if self.target_memory_id == self.contradicting_memory_id:
            raise InvalidArgumentError("contradiction link cannot target itself")
        object.__setattr__(
            self,
            "decision",
            _assert_member(self.decision, CONTRADICTION_DECISIONS, "decision"),
        )
        object.__setattr__(
            self, "reason_code", _assert_non_empty(self.reason_code, "reason_code")
        )
        object.__setattr__(
            self, "observed_at", _assert_non_empty(self.observed_at, "observed_at")
        )
        object.__setattr__(self, "evidence_refs", tuple(self.evidence_refs))

    def to_dict(self) -> dict[str, Any]:
        return {
            "link_id": self.link_id,
            "target_memory_id": self.target_memory_id,
            "contradicting_memory_id": self.contradicting_memory_id,
            "decision": self.decision,
            "reason_code": self.reason_code,
            "observed_at": self.observed_at,
            "evidence_refs": [ref.to_dict() for ref in self.evidence_refs],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "MemoryContradictionLink":
        return cls(
            link_id=str(payload.get("link_id", "") or ""),
            target_memory_id=str(payload.get("target_memory_id", "") or ""),
            contradicting_memory_id=str(
                payload.get("contradicting_memory_id", "") or ""
            ),
            decision=str(payload.get("decision", "") or ""),
            reason_code=str(payload.get("reason_code", "") or ""),
            observed_at=str(payload.get("observed_at", "") or ""),
            evidence_refs=tuple(
                MemoryEvidenceLink.from_dict(item)
                for item in payload.get("evidence_refs", ())
            ),
        )


@dataclass(frozen=True)
class SelfImprovingMemoryLifecycle:
    """Durable lifecycle state for one self-improving memory candidate."""

    memory_id: str
    namespace_ref: str
    kind: MemoryLifecycleKind
    trust_state: MemoryLifecycleState = "candidate"
    trust_score: float = 0.0
    candidate_id: str = ""
    memory_refs: tuple[str, ...] = ()
    evidence_refs: tuple[MemoryEvidenceLink, ...] = ()
    summary_block_ids: tuple[str, ...] = ()
    history: tuple[MemoryLifecycleEvent, ...] = ()
    contradiction_links: tuple[MemoryContradictionLink, ...] = ()
    superseded_by_memory_id: str | None = None
    suppression_reason: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "memory_id", _assert_non_empty(self.memory_id, "memory_id")
        )
        object.__setattr__(
            self,
            "namespace_ref",
            _assert_non_empty(self.namespace_ref, "namespace_ref"),
        )
        object.__setattr__(
            self,
            "kind",
            _assert_member(self.kind, MEMORY_LIFECYCLE_KINDS, "kind"),
        )
        object.__setattr__(
            self,
            "trust_state",
            _assert_member(
                self.trust_state,
                MEMORY_LIFECYCLE_STATES,
                "trust_state",
            ),
        )
        object.__setattr__(
            self, "trust_score", _assert_score(self.trust_score, "trust_score")
        )
        object.__setattr__(self, "candidate_id", str(self.candidate_id or ""))
        object.__setattr__(
            self,
            "memory_refs",
            tuple(str(ref) for ref in self.memory_refs if str(ref)),
        )
        object.__setattr__(self, "evidence_refs", tuple(self.evidence_refs))
        object.__setattr__(
            self,
            "summary_block_ids",
            tuple(str(ref) for ref in self.summary_block_ids if str(ref)),
        )
        object.__setattr__(self, "history", tuple(self.history))
        object.__setattr__(self, "contradiction_links", tuple(self.contradiction_links))
        if self.trust_state == "superseded" and not self.superseded_by_memory_id:
            raise InvalidArgumentError(
                "superseded state requires superseded_by_memory_id"
            )
        if self.trust_state == "suppressed" and not self.suppression_reason:
            raise InvalidArgumentError("suppressed state requires suppression_reason")

    @property
    def pragma_refs(self) -> tuple[str, ...]:
        return _pragma_refs(self.evidence_refs)

    def to_dict(self) -> dict[str, Any]:
        return {
            "memory_id": self.memory_id,
            "namespace_ref": self.namespace_ref,
            "kind": self.kind,
            "trust_state": self.trust_state,
            "trust_score": self.trust_score,
            "candidate_id": self.candidate_id,
            "memory_refs": list(self.memory_refs),
            "evidence_refs": [ref.to_dict() for ref in self.evidence_refs],
            "summary_block_ids": list(self.summary_block_ids),
            "history": [event.to_dict() for event in self.history],
            "contradiction_links": [
                link.to_dict() for link in self.contradiction_links
            ],
            "superseded_by_memory_id": self.superseded_by_memory_id,
            "suppression_reason": self.suppression_reason,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SelfImprovingMemoryLifecycle":
        return cls(
            memory_id=str(payload.get("memory_id", "") or ""),
            namespace_ref=str(payload.get("namespace_ref", "") or ""),
            kind=str(payload.get("kind", "") or ""),
            trust_state=str(payload.get("trust_state", "candidate") or "candidate"),
            trust_score=float(payload.get("trust_score", 0.0) or 0.0),
            candidate_id=str(payload.get("candidate_id", "") or ""),
            memory_refs=tuple(payload.get("memory_refs") or ()),
            evidence_refs=tuple(
                MemoryEvidenceLink.from_dict(item)
                for item in payload.get("evidence_refs", ())
            ),
            summary_block_ids=tuple(payload.get("summary_block_ids") or ()),
            history=tuple(
                MemoryLifecycleEvent.from_dict(item)
                for item in payload.get("history", ())
            ),
            contradiction_links=tuple(
                MemoryContradictionLink.from_dict(item)
                for item in payload.get("contradiction_links", ())
            ),
            superseded_by_memory_id=payload.get("superseded_by_memory_id"),
            suppression_reason=payload.get("suppression_reason"),
        )


@dataclass(frozen=True)
class MemoryAttributionUpdate:
    """Later outcome attribution used to update lifecycle trust."""

    update_id: str
    memory_id: str
    outcome: AttributionOutcome
    weight: float
    observed_at: str
    reason_codes: tuple[str, ...] = ()
    evidence_refs: tuple[MemoryEvidenceLink, ...] = ()
    superseded_by_memory_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "update_id", _assert_non_empty(self.update_id, "update_id")
        )
        object.__setattr__(
            self, "memory_id", _assert_non_empty(self.memory_id, "memory_id")
        )
        object.__setattr__(
            self,
            "outcome",
            _assert_member(self.outcome, ATTRIBUTION_OUTCOMES, "outcome"),
        )
        object.__setattr__(self, "weight", _assert_score(self.weight, "weight"))
        object.__setattr__(
            self, "observed_at", _assert_non_empty(self.observed_at, "observed_at")
        )
        object.__setattr__(
            self,
            "reason_codes",
            tuple(str(code) for code in self.reason_codes if str(code)),
        )
        object.__setattr__(self, "evidence_refs", tuple(self.evidence_refs))
        if self.outcome == "supersede" and not self.superseded_by_memory_id:
            raise InvalidArgumentError(
                "supersede outcome requires superseded_by_memory_id"
            )


@dataclass(frozen=True)
class MemoryRetrievalPacket:
    """Compact OpenMinion-facing packet for one durable memory."""

    packet_id: str
    namespace_ref: str
    kind: MemoryLifecycleKind
    trust_state: MemoryLifecycleState
    trust_score: float
    retrieval_reason_codes: tuple[str, ...] = ()
    memory_refs: tuple[str, ...] = ()
    pragma_refs: tuple[str, ...] = ()
    summary_block_ids: tuple[str, ...] = ()
    omitted_reason: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "packet_id", _assert_non_empty(self.packet_id, "packet_id")
        )
        object.__setattr__(
            self,
            "namespace_ref",
            _assert_non_empty(self.namespace_ref, "namespace_ref"),
        )
        object.__setattr__(
            self,
            "kind",
            _assert_member(self.kind, MEMORY_LIFECYCLE_KINDS, "kind"),
        )
        object.__setattr__(
            self,
            "trust_state",
            _assert_member(
                self.trust_state,
                MEMORY_LIFECYCLE_STATES,
                "trust_state",
            ),
        )
        object.__setattr__(
            self, "trust_score", _assert_score(self.trust_score, "trust_score")
        )
        object.__setattr__(
            self,
            "retrieval_reason_codes",
            tuple(str(code) for code in self.retrieval_reason_codes if str(code)),
        )
        object.__setattr__(
            self,
            "memory_refs",
            tuple(str(ref) for ref in self.memory_refs if str(ref)),
        )
        object.__setattr__(
            self,
            "pragma_refs",
            tuple(str(ref) for ref in self.pragma_refs if str(ref)),
        )
        object.__setattr__(
            self,
            "summary_block_ids",
            tuple(str(ref) for ref in self.summary_block_ids if str(ref)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "packet_id": self.packet_id,
            "namespace_ref": self.namespace_ref,
            "kind": self.kind,
            "trust_state": self.trust_state,
            "trust_score": self.trust_score,
            "retrieval_reason_codes": list(self.retrieval_reason_codes),
            "memory_refs": list(self.memory_refs),
            "pragma_refs": list(self.pragma_refs),
            "summary_block_ids": list(self.summary_block_ids),
            "omitted_reason": self.omitted_reason,
        }


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
    target_state = _assert_member(to_state, MEMORY_LIFECYCLE_STATES, "to_state")
    allowed = _ALLOWED_TRANSITIONS[lifecycle.trust_state]
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
    elif update.outcome in _EVIDENCE_DEGRADATION_OUTCOMES:
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
    """Attach an explicit contradiction/supersession link without guessing content."""
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
