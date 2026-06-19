"""Reusable audit-event schemas for durable knowledge backends."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Literal
import uuid

from sophiagraph.temporal import utc_now_iso


# Structural recorder; callers own the audit sink lifecycle.
MemoryAuditRecorder = Callable[["MemoryAuditEvent"], None]


def noop_audit_recorder(
    event: "MemoryAuditEvent",
) -> None:  # pragma: no cover - trivial
    return None


@dataclass(frozen=True)
class MemoryAuditEvent:
    event_type: str
    target_kind: str
    target_id: str | None = None
    scope: str | None = None
    record_type: str | None = None
    record_key: str | None = None
    session_id: str | None = None
    details: dict[str, Any] = field(default_factory=dict)
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    timestamp: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "timestamp": self.timestamp,
            "event_type": self.event_type,
            "target_kind": self.target_kind,
            "target_id": self.target_id,
            "scope": self.scope,
            "record_type": self.record_type,
            "record_key": self.record_key,
            "session_id": self.session_id,
            "details": dict(self.details or {}),
        }


TrustGateDecision = Literal["ALLOWED", "BLOCKED"]
TrustGateReasonCode = Literal[
    "ALLOWED",
    "MISSING_CLAIM_KEY",
    "BELOW_TRUST_THRESHOLD",
    "RATE_LIMITED",
]


@dataclass(frozen=True)
class TrustGateEvent:
    candidate_id: str
    claim_key: str | None
    trust_score: float
    sub_signals: dict[str, float]
    decision: TrustGateDecision
    reason_code: TrustGateReasonCode
    scope: str | None = None
    record_type: str | None = None
    session_id: str | None = None
    retry_after_ms: int | None = None

    def to_memory_audit_event(self) -> MemoryAuditEvent:
        details: dict[str, Any] = {
            "claim_key": self.claim_key,
            "trust_score": float(self.trust_score),
            "sub_signals": dict(self.sub_signals),
            "decision": self.decision,
            "reason_code": self.reason_code,
        }
        if self.retry_after_ms is not None:
            details["retry_after_ms"] = int(self.retry_after_ms)
        return MemoryAuditEvent(
            event_type="memory.trust_gate.evaluate",
            target_kind="candidate",
            target_id=self.candidate_id,
            scope=self.scope,
            record_type=self.record_type,
            session_id=self.session_id,
            details=details,
        )


def memory_block_audit_event(
    *,
    event_type: str,
    block_id: str,
    class_name: str | None = None,
    mode: str | None = None,
    session_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> MemoryAuditEvent:
    """Build a canonical memory-block audit event."""

    enriched: dict[str, Any] = dict(details or {})
    if class_name is not None:
        enriched.setdefault("class_name", class_name)
    if mode is not None:
        enriched.setdefault("mode", mode)
    return MemoryAuditEvent(
        event_type=event_type,
        target_kind="memory_block",
        target_id=block_id,
        session_id=session_id,
        details=enriched,
    )
