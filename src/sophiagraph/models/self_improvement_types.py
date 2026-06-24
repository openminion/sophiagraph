"""Typed lifecycle contracts for self-improving durable memory."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final, Literal

from sophiagraph.contracts.errors import InvalidArgumentError

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

ALLOWED_LIFECYCLE_TRANSITIONS: Final[dict[str, frozenset[str]]] = {
    "candidate": frozenset({"provisional", "suppressed", "superseded"}),
    "provisional": frozenset({"candidate", "trusted", "suppressed", "superseded"}),
    "trusted": frozenset({"provisional", "pinned", "suppressed", "superseded"}),
    "pinned": frozenset({"trusted", "superseded"}),
    "suppressed": frozenset(),
    "superseded": frozenset(),
}
EVIDENCE_DEGRADATION_OUTCOMES: Final[frozenset[str]] = frozenset(
    {"evidence_stale", "evidence_missing", "evidence_changed"}
)


def assert_non_empty(value: str, label: str) -> str:
    text = str(value or "")
    if not text:
        raise InvalidArgumentError(f"{label} is required")
    return text


def assert_member(value: str, allowed: frozenset[str], label: str) -> str:
    text = str(value or "")
    if text not in allowed:
        raise InvalidArgumentError(f"invalid {label}: {value!r}")
    return text


def assert_score(value: float, label: str) -> float:
    score = float(value)
    if not 0.0 <= score <= 1.0:
        raise InvalidArgumentError(f"{label} must be between 0 and 1 inclusive")
    return score


def pragma_refs(refs: tuple["MemoryEvidenceLink", ...]) -> tuple[str, ...]:
    return tuple(ref.ref_uri for ref in refs if ref.ref_uri.startswith("pragma://"))


@dataclass(frozen=True)
class MemoryEvidenceLink:
    """Durable citation to external evidence backing one memory."""

    ref_uri: str
    freshness_state: EvidenceFreshnessState = "fresh"
    reason_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "ref_uri", assert_non_empty(self.ref_uri, "ref_uri"))
        object.__setattr__(
            self,
            "freshness_state",
            assert_member(
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
            self, "event_id", assert_non_empty(self.event_id, "event_id")
        )
        object.__setattr__(
            self,
            "from_state",
            assert_member(self.from_state, MEMORY_LIFECYCLE_STATES, "from_state"),
        )
        object.__setattr__(
            self,
            "to_state",
            assert_member(self.to_state, MEMORY_LIFECYCLE_STATES, "to_state"),
        )
        object.__setattr__(
            self, "reason_code", assert_non_empty(self.reason_code, "reason_code")
        )
        object.__setattr__(self, "actor", assert_non_empty(self.actor, "actor"))
        object.__setattr__(
            self, "observed_at", assert_non_empty(self.observed_at, "observed_at")
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
        object.__setattr__(self, "link_id", assert_non_empty(self.link_id, "link_id"))
        object.__setattr__(
            self,
            "target_memory_id",
            assert_non_empty(self.target_memory_id, "target_memory_id"),
        )
        object.__setattr__(
            self,
            "contradicting_memory_id",
            assert_non_empty(
                self.contradicting_memory_id,
                "contradicting_memory_id",
            ),
        )
        if self.target_memory_id == self.contradicting_memory_id:
            raise InvalidArgumentError("contradiction link cannot target itself")
        object.__setattr__(
            self,
            "decision",
            assert_member(self.decision, CONTRADICTION_DECISIONS, "decision"),
        )
        object.__setattr__(
            self, "reason_code", assert_non_empty(self.reason_code, "reason_code")
        )
        object.__setattr__(
            self, "observed_at", assert_non_empty(self.observed_at, "observed_at")
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
            self, "memory_id", assert_non_empty(self.memory_id, "memory_id")
        )
        object.__setattr__(
            self,
            "namespace_ref",
            assert_non_empty(self.namespace_ref, "namespace_ref"),
        )
        object.__setattr__(
            self,
            "kind",
            assert_member(self.kind, MEMORY_LIFECYCLE_KINDS, "kind"),
        )
        object.__setattr__(
            self,
            "trust_state",
            assert_member(
                self.trust_state,
                MEMORY_LIFECYCLE_STATES,
                "trust_state",
            ),
        )
        object.__setattr__(
            self, "trust_score", assert_score(self.trust_score, "trust_score")
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
        return pragma_refs(self.evidence_refs)

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
            self, "update_id", assert_non_empty(self.update_id, "update_id")
        )
        object.__setattr__(
            self, "memory_id", assert_non_empty(self.memory_id, "memory_id")
        )
        object.__setattr__(
            self,
            "outcome",
            assert_member(self.outcome, ATTRIBUTION_OUTCOMES, "outcome"),
        )
        object.__setattr__(self, "weight", assert_score(self.weight, "weight"))
        object.__setattr__(
            self, "observed_at", assert_non_empty(self.observed_at, "observed_at")
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
            self, "packet_id", assert_non_empty(self.packet_id, "packet_id")
        )
        object.__setattr__(
            self,
            "namespace_ref",
            assert_non_empty(self.namespace_ref, "namespace_ref"),
        )
        object.__setattr__(
            self,
            "kind",
            assert_member(self.kind, MEMORY_LIFECYCLE_KINDS, "kind"),
        )
        object.__setattr__(
            self,
            "trust_state",
            assert_member(
                self.trust_state,
                MEMORY_LIFECYCLE_STATES,
                "trust_state",
            ),
        )
        object.__setattr__(
            self, "trust_score", assert_score(self.trust_score, "trust_score")
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
