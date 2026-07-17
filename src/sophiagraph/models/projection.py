"""Durable derived-index projection contracts."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal, Mapping, get_args

from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.models.namespace import MemoryNamespace

ProjectionTargetKind = Literal["graph", "vector"]
ProjectionAttemptStatus = Literal["started", "applied", "skipped", "failed"]
ProjectionFailureReason = Literal[
    "target_unavailable",
    "unsupported_event",
    "canonical_object_missing",
    "target_write_failed",
    "checkpoint_write_failed",
    "lease_expired",
    "out_of_order",
    "privacy_denied",
]
ProjectionFindingKind = Literal[
    "missing", "stale", "orphan", "watermark_mismatch", "unverifiable"
]
ProjectionRepairOperation = Literal["upsert", "delete"]

_TARGET_KINDS = frozenset(get_args(ProjectionTargetKind))
_ATTEMPT_STATUSES = frozenset(get_args(ProjectionAttemptStatus))
_FAILURE_REASONS = frozenset(get_args(ProjectionFailureReason))
_FINDING_KINDS = frozenset(get_args(ProjectionFindingKind))
_REPAIR_OPERATIONS = frozenset(get_args(ProjectionRepairOperation))


def _required(value: str, name: str) -> None:
    if not value:
        raise InvalidArgumentError(f"{name} is required")


@dataclass(frozen=True, slots=True)
class ProjectionTarget:
    target_id: str
    kind: ProjectionTargetKind
    adapter_name: str
    namespace: MemoryNamespace | None = None
    enabled: bool = True
    max_attempts: int = 8
    lease_seconds: int = 30

    def __post_init__(self) -> None:
        _required(self.target_id, "target_id")
        _required(self.adapter_name, "adapter_name")
        if self.kind not in _TARGET_KINDS:
            raise InvalidArgumentError(f"invalid target kind: {self.kind!r}")
        if self.namespace is not None and not isinstance(
            self.namespace, MemoryNamespace
        ):
            raise TypeError("namespace must be MemoryNamespace or None")
        if self.max_attempts <= 0 or self.lease_seconds <= 0:
            raise InvalidArgumentError("attempt and lease limits must be positive")


@dataclass(frozen=True, slots=True)
class ProjectionCheckpoint:
    target_id: str
    cursor: int = 0
    event_id: str | None = None
    updated_at: str = ""
    target_watermark: str | None = None

    def __post_init__(self) -> None:
        _required(self.target_id, "target_id")
        if self.cursor < 0:
            raise InvalidArgumentError("cursor must be non-negative")


@dataclass(frozen=True, slots=True)
class ProjectionLease:
    target_id: str
    owner_id: str
    fencing_token: int
    acquired_at: str
    expires_at: str

    def __post_init__(self) -> None:
        _required(self.target_id, "target_id")
        _required(self.owner_id, "owner_id")
        _required(self.acquired_at, "acquired_at")
        _required(self.expires_at, "expires_at")
        if self.fencing_token <= 0:
            raise InvalidArgumentError("fencing_token must be positive")


@dataclass(frozen=True, slots=True)
class ProjectionAttempt:
    attempt_id: str
    target_id: str
    event_id: str
    cursor: int
    attempt_number: int
    status: ProjectionAttemptStatus
    started_at: str
    completed_at: str | None = None
    next_retry_at: str | None = None
    error_code: str | None = None
    error_message: str | None = None

    def __post_init__(self) -> None:
        for value, name in (
            (self.attempt_id, "attempt_id"),
            (self.target_id, "target_id"),
            (self.event_id, "event_id"),
            (self.started_at, "started_at"),
        ):
            _required(value, name)
        if self.cursor < 0 or self.attempt_number <= 0:
            raise InvalidArgumentError(
                "cursor must be non-negative and attempt_number must be positive"
            )
        if self.status not in _ATTEMPT_STATUSES:
            raise InvalidArgumentError(f"invalid attempt status: {self.status!r}")
        if self.error_message is not None and len(self.error_message) > 512:
            raise InvalidArgumentError("error_message exceeds diagnostic bound")


@dataclass(frozen=True, slots=True)
class ProjectionFailure:
    target_id: str
    event_id: str
    cursor: int
    attempt_count: int
    reason: ProjectionFailureReason
    retryable: bool
    dead_letter: bool
    updated_at: str
    next_retry_at: str | None = None
    error_message: str | None = None

    def __post_init__(self) -> None:
        _required(self.target_id, "target_id")
        _required(self.event_id, "event_id")
        _required(self.updated_at, "updated_at")
        if self.cursor < 0 or self.attempt_count <= 0:
            raise InvalidArgumentError(
                "cursor must be non-negative and attempt_count must be positive"
            )
        if self.reason not in _FAILURE_REASONS:
            raise InvalidArgumentError(f"invalid failure reason: {self.reason!r}")
        if self.error_message is not None and len(self.error_message) > 512:
            raise InvalidArgumentError("error_message exceeds diagnostic bound")


@dataclass(frozen=True, slots=True)
class ProjectionBatchResult:
    target_id: str
    source_head_cursor: int
    checkpoint_cursor: int
    requested: int
    applied: int
    skipped: int
    failed: int
    dead_lettered: int
    target_watermark: str | None = None

    def __post_init__(self) -> None:
        _required(self.target_id, "target_id")
        values = (
            self.source_head_cursor,
            self.checkpoint_cursor,
            self.requested,
            self.applied,
            self.skipped,
            self.failed,
            self.dead_lettered,
        )
        if any(value < 0 for value in values):
            raise InvalidArgumentError("projection batch counts must be non-negative")


@dataclass(frozen=True, slots=True)
class ProjectionHealth:
    target_id: str
    source_head_cursor: int
    checkpoint_cursor: int
    lag: int
    retry_count: int
    dead_letter_count: int
    lease_owner: str | None = None
    lease_expires_at: str | None = None
    last_error_reason: ProjectionFailureReason | None = None

    def __post_init__(self) -> None:
        _required(self.target_id, "target_id")
        if (
            min(
                self.source_head_cursor,
                self.checkpoint_cursor,
                self.lag,
                self.retry_count,
                self.dead_letter_count,
            )
            < 0
        ):
            raise InvalidArgumentError("projection health values must be non-negative")
        if (
            self.last_error_reason is not None
            and self.last_error_reason not in _FAILURE_REASONS
        ):
            raise InvalidArgumentError("invalid projection health error reason")


@dataclass(frozen=True, slots=True)
class ProjectionInventoryItem:
    object_id: str
    object_kind: str
    version_hash: str | None = None

    def __post_init__(self) -> None:
        _required(self.object_id, "object_id")
        _required(self.object_kind, "object_kind")


@dataclass(frozen=True, slots=True)
class ProjectionFinding:
    kind: ProjectionFindingKind
    object_id: str
    object_kind: str
    canonical_hash: str | None = None
    target_hash: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in _FINDING_KINDS:
            raise InvalidArgumentError(f"invalid finding kind: {self.kind!r}")
        _required(self.object_id, "object_id")
        _required(self.object_kind, "object_kind")


@dataclass(frozen=True, slots=True)
class ProjectionReconciliationReport:
    report_id: str
    target_id: str
    source_cursor: int
    target_watermark: str | None
    findings: tuple[ProjectionFinding, ...] = ()

    def __post_init__(self) -> None:
        _required(self.report_id, "report_id")
        _required(self.target_id, "target_id")
        if self.source_cursor < 0:
            raise InvalidArgumentError("source_cursor must be non-negative")


@dataclass(frozen=True, slots=True)
class ProjectionRepairAction:
    operation: ProjectionRepairOperation
    object_id: str
    object_kind: str
    version_hash: str | None = None

    def __post_init__(self) -> None:
        if self.operation not in _REPAIR_OPERATIONS:
            raise InvalidArgumentError(f"invalid repair operation: {self.operation!r}")
        _required(self.object_id, "object_id")
        _required(self.object_kind, "object_kind")


@dataclass(frozen=True, slots=True)
class ProjectionRepairPlan:
    plan_id: str
    report_id: str
    target_id: str
    source_cursor: int
    actions: tuple[ProjectionRepairAction, ...] = ()

    def __post_init__(self) -> None:
        _required(self.plan_id, "plan_id")
        _required(self.report_id, "report_id")
        _required(self.target_id, "target_id")
        if self.source_cursor < 0:
            raise InvalidArgumentError("source_cursor must be non-negative")


def projection_target_to_dict(target: ProjectionTarget) -> dict[str, Any]:
    payload = asdict(target)
    payload["namespace"] = (
        target.namespace.as_dict() if target.namespace is not None else None
    )
    return payload


def projection_target_from_dict(data: Mapping[str, Any]) -> ProjectionTarget:
    raw_namespace = data.get("namespace")
    return ProjectionTarget(
        target_id=str(data.get("target_id") or ""),
        kind=str(data.get("kind") or ""),  # type: ignore[arg-type]
        adapter_name=str(data.get("adapter_name") or ""),
        namespace=MemoryNamespace.from_dict(dict(raw_namespace))
        if isinstance(raw_namespace, Mapping) and raw_namespace
        else None,
        enabled=bool(data.get("enabled", True)),
        max_attempts=int(data.get("max_attempts", 8)),
        lease_seconds=int(data.get("lease_seconds", 30)),
    )


__all__ = [
    "ProjectionAttempt",
    "ProjectionAttemptStatus",
    "ProjectionBatchResult",
    "ProjectionCheckpoint",
    "ProjectionFailure",
    "ProjectionFailureReason",
    "ProjectionFinding",
    "ProjectionFindingKind",
    "ProjectionHealth",
    "ProjectionInventoryItem",
    "ProjectionLease",
    "ProjectionReconciliationReport",
    "ProjectionRepairAction",
    "ProjectionRepairOperation",
    "ProjectionRepairPlan",
    "ProjectionTarget",
    "ProjectionTargetKind",
    "projection_target_from_dict",
    "projection_target_to_dict",
]
