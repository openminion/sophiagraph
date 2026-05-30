"""Typed governance and audit event DTOs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Final, Literal
import uuid

from sophiagraph.audit.events import MemoryAuditEvent, _utc_now_iso
from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.models.namespace import MemoryNamespace


GovernanceEventKind = Literal[
    "write_attempt",
    "write_accepted",
    "retrieval",
    "export",
    "policy_denial",
    "lifecycle_action",
    "webhook_delivery_attempt",
    "retrieval_explanation",
    "quality_eval_signal",
]

GOVERNANCE_EVENT_KINDS: Final[frozenset[str]] = frozenset(
    {
        "write_attempt",
        "write_accepted",
        "retrieval",
        "export",
        "policy_denial",
        "lifecycle_action",
        "webhook_delivery_attempt",
        "retrieval_explanation",
        "quality_eval_signal",
    }
)

PolicySurface = Literal[
    "write",
    "export",
    "retention",
    "deletion",
]

POLICY_SURFACES: Final[frozenset[str]] = frozenset(
    {"write", "export", "retention", "deletion"}
)

PolicyDecisionAction = Literal["allow", "deny"]

POLICY_DECISION_ACTIONS: Final[frozenset[str]] = frozenset({"allow", "deny"})

PolicyDenialReasonCode = Literal[
    "POLICY_DENIED_BY_HOOK",
    "POLICY_REQUIRED_FIELDS_MISSING",
    "POLICY_NAMESPACE_FORBIDDEN",
    "POLICY_RETENTION_EXPIRED",
    "POLICY_QUOTA_EXCEEDED",
    "POLICY_TRUST_THRESHOLD_NOT_MET",
]

POLICY_DENIAL_REASON_CODES: Final[frozenset[str]] = frozenset(
    {
        "POLICY_DENIED_BY_HOOK",
        "POLICY_REQUIRED_FIELDS_MISSING",
        "POLICY_NAMESPACE_FORBIDDEN",
        "POLICY_RETENTION_EXPIRED",
        "POLICY_QUOTA_EXCEEDED",
        "POLICY_TRUST_THRESHOLD_NOT_MET",
    }
)

WebhookDeliveryStatus = Literal["pending", "succeeded", "failed", "abandoned"]

WEBHOOK_DELIVERY_STATUSES: Final[frozenset[str]] = frozenset(
    {"pending", "succeeded", "failed", "abandoned"}
)


def _require_nonempty(field_name: str, value: Any) -> None:
    if not isinstance(value, str) or not value:
        raise InvalidArgumentError(f"{field_name} must be a non-empty string")


def _require_namespace(field_name: str, value: Any) -> None:
    if not isinstance(value, MemoryNamespace):
        raise InvalidArgumentError(f"{field_name} must be a MemoryNamespace")


@dataclass(frozen=True)
class WriteAttemptEvent:
    """Recorded BEFORE a write is committed. Used to feed policy hooks."""

    namespace: MemoryNamespace
    payload_kind: str
    source_owner: str
    target_kind: str
    target_id: str | None = None
    idempotency_key: str | None = None
    trust_mode: str = "direct"
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    timestamp: str = field(default_factory=_utc_now_iso)

    def __post_init__(self) -> None:
        _require_namespace("namespace", self.namespace)
        _require_nonempty("payload_kind", self.payload_kind)
        _require_nonempty("source_owner", self.source_owner)
        _require_nonempty("target_kind", self.target_kind)

    def to_memory_audit_event(self) -> MemoryAuditEvent:
        details: dict[str, Any] = {
            "payload_kind": self.payload_kind,
            "source_owner": self.source_owner,
            "trust_mode": self.trust_mode,
            "namespace": self.namespace.as_dict(),
        }
        if self.idempotency_key is not None:
            details["idempotency_key"] = self.idempotency_key
        return MemoryAuditEvent(
            event_id=self.event_id,
            timestamp=self.timestamp,
            event_type="memory.write_attempt",
            target_kind=self.target_kind,
            target_id=self.target_id,
            details=details,
        )


@dataclass(frozen=True)
class WriteAcceptedEvent:
    """Recorded AFTER a write commits."""

    namespace: MemoryNamespace
    payload_kind: str
    source_owner: str
    target_kind: str
    target_id: str
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    timestamp: str = field(default_factory=_utc_now_iso)

    def __post_init__(self) -> None:
        _require_namespace("namespace", self.namespace)
        _require_nonempty("payload_kind", self.payload_kind)
        _require_nonempty("source_owner", self.source_owner)
        _require_nonempty("target_kind", self.target_kind)
        _require_nonempty("target_id", self.target_id)

    def to_memory_audit_event(self) -> MemoryAuditEvent:
        return MemoryAuditEvent(
            event_id=self.event_id,
            timestamp=self.timestamp,
            event_type="memory.write_accepted",
            target_kind=self.target_kind,
            target_id=self.target_id,
            details={
                "payload_kind": self.payload_kind,
                "source_owner": self.source_owner,
                "namespace": self.namespace.as_dict(),
            },
        )


@dataclass(frozen=True)
class RetrievalEvent:
    """Recorded when a caller runs a retrieval and uses results."""

    namespace: MemoryNamespace
    source_owner: str
    selected_ids: tuple[str, ...]
    omitted_count: int = 0
    retrieval_mode: str | None = None
    session_id: str | None = None
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    timestamp: str = field(default_factory=_utc_now_iso)

    def __post_init__(self) -> None:
        _require_namespace("namespace", self.namespace)
        _require_nonempty("source_owner", self.source_owner)
        if not isinstance(self.selected_ids, tuple):
            raise InvalidArgumentError("selected_ids must be a tuple of strings")
        for sid in self.selected_ids:
            if not isinstance(sid, str) or not sid:
                raise InvalidArgumentError(
                    "each selected id must be a non-empty string"
                )
        if not isinstance(self.omitted_count, int) or self.omitted_count < 0:
            raise InvalidArgumentError("omitted_count must be non-negative int")

    def to_memory_audit_event(self) -> MemoryAuditEvent:
        details: dict[str, Any] = {
            "source_owner": self.source_owner,
            "selected_ids": list(self.selected_ids),
            "omitted_count": int(self.omitted_count),
            "namespace": self.namespace.as_dict(),
        }
        if self.retrieval_mode is not None:
            details["retrieval_mode"] = self.retrieval_mode
        return MemoryAuditEvent(
            event_id=self.event_id,
            timestamp=self.timestamp,
            event_type="memory.retrieval",
            target_kind="retrieval",
            target_id=None,
            session_id=self.session_id,
            details=details,
        )


@dataclass(frozen=True)
class RetrievalExplanation:
    """Structural explanation for one selected record."""

    namespace: MemoryNamespace
    record_id: str
    structural_score: float
    embedding_score: float | None = None
    matched_filters: tuple[str, ...] = ()
    graph_path_ids: tuple[str, ...] = ()
    retrieval_mode: str | None = None

    def __post_init__(self) -> None:
        _require_namespace("namespace", self.namespace)
        _require_nonempty("record_id", self.record_id)
        if not isinstance(self.structural_score, (int, float)):
            raise InvalidArgumentError("structural_score must be numeric")
        if self.embedding_score is not None and not isinstance(
            self.embedding_score, (int, float)
        ):
            raise InvalidArgumentError("embedding_score must be numeric or None")
        if not isinstance(self.matched_filters, tuple):
            raise InvalidArgumentError("matched_filters must be a tuple")
        for f in self.matched_filters:
            if not isinstance(f, str) or not f:
                raise InvalidArgumentError(
                    "each matched_filter must be a non-empty string"
                )
        if not isinstance(self.graph_path_ids, tuple):
            raise InvalidArgumentError("graph_path_ids must be a tuple")
        for pid in self.graph_path_ids:
            if not isinstance(pid, str) or not pid:
                raise InvalidArgumentError(
                    "each graph_path_id must be a non-empty string"
                )


# Quality eval signal.

QualityEvalSignalKind = Literal[
    "explicit_user_correction",
    "validation_passed",
    "validation_failed",
    "retrieval_used",
    "retrieval_ignored",
]

QUALITY_EVAL_SIGNAL_KINDS: Final[frozenset[str]] = frozenset(
    {
        "explicit_user_correction",
        "validation_passed",
        "validation_failed",
        "retrieval_used",
        "retrieval_ignored",
    }
)


@dataclass(frozen=True)
class QualityEvalSignal:
    """Explicit caller-supplied evaluation signal for a record."""

    namespace: MemoryNamespace
    record_id: str
    signal_kind: QualityEvalSignalKind
    source_owner: str
    session_id: str | None = None
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    timestamp: str = field(default_factory=_utc_now_iso)
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_namespace("namespace", self.namespace)
        _require_nonempty("record_id", self.record_id)
        if self.signal_kind not in QUALITY_EVAL_SIGNAL_KINDS:
            raise InvalidArgumentError(
                f"unknown signal_kind: {self.signal_kind!r}; "
                f"allowed: {sorted(QUALITY_EVAL_SIGNAL_KINDS)}"
            )
        _require_nonempty("source_owner", self.source_owner)

    def to_memory_audit_event(self) -> MemoryAuditEvent:
        return MemoryAuditEvent(
            event_id=self.event_id,
            timestamp=self.timestamp,
            event_type="memory.quality_eval_signal",
            target_kind="record",
            target_id=self.record_id,
            session_id=self.session_id,
            details={
                "signal_kind": self.signal_kind,
                "source_owner": self.source_owner,
                "namespace": self.namespace.as_dict(),
                **dict(self.details or {}),
            },
        )


@dataclass(frozen=True)
class ExportEvent:
    """Recorded after a portability bundle export completes."""

    namespace: MemoryNamespace
    source_owner: str
    record_count: int
    relation_count: int = 0
    candidate_count: int = 0
    block_count: int = 0
    document_count: int = 0
    bundle_id: str | None = None
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    timestamp: str = field(default_factory=_utc_now_iso)

    def __post_init__(self) -> None:
        _require_namespace("namespace", self.namespace)
        _require_nonempty("source_owner", self.source_owner)
        for name in (
            "record_count",
            "relation_count",
            "candidate_count",
            "block_count",
            "document_count",
        ):
            value = getattr(self, name)
            if not isinstance(value, int) or value < 0:
                raise InvalidArgumentError(f"{name} must be non-negative int")

    def to_memory_audit_event(self) -> MemoryAuditEvent:
        return MemoryAuditEvent(
            event_id=self.event_id,
            timestamp=self.timestamp,
            event_type="memory.export",
            target_kind="bundle",
            target_id=self.bundle_id,
            details={
                "source_owner": self.source_owner,
                "namespace": self.namespace.as_dict(),
                "record_count": self.record_count,
                "relation_count": self.relation_count,
                "candidate_count": self.candidate_count,
                "block_count": self.block_count,
                "document_count": self.document_count,
            },
        )


# Policy denial.


@dataclass(frozen=True)
class PolicyDenialEvent:
    """Recorded when a policy hook denies a write/export/retention/deletion."""

    namespace: MemoryNamespace
    surface: PolicySurface
    reason_code: PolicyDenialReasonCode
    policy_id: str
    source_owner: str
    target_kind: str
    target_id: str | None = None
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    timestamp: str = field(default_factory=_utc_now_iso)
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_namespace("namespace", self.namespace)
        if self.surface not in POLICY_SURFACES:
            raise InvalidArgumentError(
                f"unknown surface: {self.surface!r}; allowed: {sorted(POLICY_SURFACES)}"
            )
        if self.reason_code not in POLICY_DENIAL_REASON_CODES:
            raise InvalidArgumentError(
                f"unknown reason_code: {self.reason_code!r}; "
                f"allowed: {sorted(POLICY_DENIAL_REASON_CODES)}"
            )
        _require_nonempty("policy_id", self.policy_id)
        _require_nonempty("source_owner", self.source_owner)
        _require_nonempty("target_kind", self.target_kind)

    def to_memory_audit_event(self) -> MemoryAuditEvent:
        return MemoryAuditEvent(
            event_id=self.event_id,
            timestamp=self.timestamp,
            event_type="memory.policy_denial",
            target_kind=self.target_kind,
            target_id=self.target_id,
            details={
                "surface": self.surface,
                "reason_code": self.reason_code,
                "policy_id": self.policy_id,
                "source_owner": self.source_owner,
                "namespace": self.namespace.as_dict(),
                **dict(self.details or {}),
            },
        )


# Lifecycle action event.

LifecycleAction = Literal[
    "ttl_active_elapsed",
    "ttl_cooling_elapsed",
    "promotion_applied",
    "archived",
    "deleted",
    "no_transition",
]

LIFECYCLE_ACTIONS: Final[frozenset[str]] = frozenset(
    {
        "ttl_active_elapsed",
        "ttl_cooling_elapsed",
        "promotion_applied",
        "archived",
        "deleted",
        "no_transition",
    }
)


@dataclass(frozen=True)
class LifecycleActionEvent:
    """Recorded when a lifecycle job applies a typed transition."""

    namespace: MemoryNamespace
    record_id: str
    action: LifecycleAction
    policy_id: str
    from_phase: str
    to_phase: str
    job_id: str | None = None
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    timestamp: str = field(default_factory=_utc_now_iso)

    def __post_init__(self) -> None:
        _require_namespace("namespace", self.namespace)
        _require_nonempty("record_id", self.record_id)
        if self.action not in LIFECYCLE_ACTIONS:
            raise InvalidArgumentError(
                f"unknown action: {self.action!r}; allowed: {sorted(LIFECYCLE_ACTIONS)}"
            )
        _require_nonempty("policy_id", self.policy_id)
        _require_nonempty("from_phase", self.from_phase)
        _require_nonempty("to_phase", self.to_phase)

    def to_memory_audit_event(self) -> MemoryAuditEvent:
        details: dict[str, Any] = {
            "action": self.action,
            "policy_id": self.policy_id,
            "from_phase": self.from_phase,
            "to_phase": self.to_phase,
            "namespace": self.namespace.as_dict(),
        }
        if self.job_id is not None:
            details["job_id"] = self.job_id
        return MemoryAuditEvent(
            event_id=self.event_id,
            timestamp=self.timestamp,
            event_type="memory.lifecycle_action",
            target_kind="record",
            target_id=self.record_id,
            details=details,
        )


@dataclass(frozen=True)
class WebhookDeliveryAttemptEvent:
    """Recorded for every webhook delivery attempt by the host service."""

    webhook_id: str
    delivery_id: str
    status: WebhookDeliveryStatus
    attempt: int
    target_url_host: str
    response_status_code: int | None = None
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    timestamp: str = field(default_factory=_utc_now_iso)

    def __post_init__(self) -> None:
        _require_nonempty("webhook_id", self.webhook_id)
        _require_nonempty("delivery_id", self.delivery_id)
        if self.status not in WEBHOOK_DELIVERY_STATUSES:
            raise InvalidArgumentError(
                f"unknown status: {self.status!r}; "
                f"allowed: {sorted(WEBHOOK_DELIVERY_STATUSES)}"
            )
        if not isinstance(self.attempt, int) or self.attempt < 1:
            raise InvalidArgumentError("attempt must be a positive int")
        _require_nonempty("target_url_host", self.target_url_host)
        if self.response_status_code is not None and not isinstance(
            self.response_status_code, int
        ):
            raise InvalidArgumentError("response_status_code must be an int or None")

    def to_memory_audit_event(self) -> MemoryAuditEvent:
        details: dict[str, Any] = {
            "delivery_id": self.delivery_id,
            "status": self.status,
            "attempt": self.attempt,
            "target_url_host": self.target_url_host,
        }
        if self.response_status_code is not None:
            details["response_status_code"] = self.response_status_code
        return MemoryAuditEvent(
            event_id=self.event_id,
            timestamp=self.timestamp,
            event_type="memory.webhook_delivery_attempt",
            target_kind="webhook",
            target_id=self.webhook_id,
            details=details,
        )


__all__ = [
    "ExportEvent",
    "GOVERNANCE_EVENT_KINDS",
    "GovernanceEventKind",
    "LIFECYCLE_ACTIONS",
    "LifecycleAction",
    "LifecycleActionEvent",
    "POLICY_DECISION_ACTIONS",
    "POLICY_DENIAL_REASON_CODES",
    "POLICY_SURFACES",
    "PolicyDecisionAction",
    "PolicyDenialEvent",
    "PolicyDenialReasonCode",
    "PolicySurface",
    "QUALITY_EVAL_SIGNAL_KINDS",
    "QualityEvalSignal",
    "QualityEvalSignalKind",
    "RetrievalEvent",
    "RetrievalExplanation",
    "WEBHOOK_DELIVERY_STATUSES",
    "WebhookDeliveryAttemptEvent",
    "WebhookDeliveryStatus",
    "WriteAcceptedEvent",
    "WriteAttemptEvent",
]
