"""Typed workbench action and journal contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, cast, get_args

from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.models.namespace import MemoryNamespace

WorkbenchActionOutcome = Literal[
    "applied",
    "queued_for_review",
    "preview_only",
    "blocked",
    "conflict",
    "not_found",
    "unsupported",
    "recovery_required",
    "failed",
]
WorkbenchActionReasonCode = Literal[
    "applied",
    "idempotent_replay",
    "preview_only",
    "host_required",
    "review_not_persisted",
    "unsupported_action",
    "target_not_found",
    "scope_denied",
    "impersonation_denied",
    "stale_precondition",
    "invalid_payload",
    "missing_evidence",
    "candidate_not_approved",
    "reservation_in_progress",
    "idempotency_conflict",
    "recovery_required",
    "execution_failed",
]
ActionJournalLifecycle = Literal["reserved", "in_progress", "terminal"]
ActionAuditDurability = Literal["durable", "process_local"]

_ACTION_OUTCOMES = frozenset(get_args(WorkbenchActionOutcome))
_ACTION_REASONS = frozenset(get_args(WorkbenchActionReasonCode))
_JOURNAL_LIFECYCLES = frozenset(get_args(ActionJournalLifecycle))
_AUDIT_DURABILITIES = frozenset(get_args(ActionAuditDurability))


def _literal(value: object, allowed: frozenset[str], label: str) -> str:
    result = str(value)
    if result not in allowed:
        raise InvalidArgumentError(f"invalid {label}: {result!r}")
    return result


@dataclass(frozen=True, slots=True)
class WorkbenchActionExecutionContext:
    """Trusted server/host context for executing one workbench action."""

    action_id: str
    request_id: str
    principal_id: str
    workspace_id: str
    scope: str
    namespace: MemoryNamespace
    workspace_root: str = ""
    source_root: str = ""
    expected_updated_at: str | None = None
    expected_content_sha256: str | None = None
    plan_binding: str = ""
    confirmed: bool = False
    requested_at: str = ""
    reason: str = ""

    def __post_init__(self) -> None:
        if not self.action_id:
            raise InvalidArgumentError("action_id is required")
        if not self.request_id:
            raise InvalidArgumentError("request_id is required")
        if not self.principal_id:
            raise InvalidArgumentError("principal_id is required")
        if not self.workspace_id:
            raise InvalidArgumentError("workspace_id is required")
        if not self.scope:
            raise InvalidArgumentError("scope is required")
        if not isinstance(self.namespace, MemoryNamespace):
            raise TypeError(
                "namespace must be MemoryNamespace"
            )  # allow-bare-raise: defensive type guard in dataclass

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "request_id": self.request_id,
            "principal_id": self.principal_id,
            "workspace_id": self.workspace_id,
            "scope": self.scope,
            "namespace": self.namespace.as_dict(),
            "workspace_root": self.workspace_root,
            "source_root": self.source_root,
            "expected_updated_at": self.expected_updated_at,
            "expected_content_sha256": self.expected_content_sha256,
            "plan_binding": self.plan_binding,
            "confirmed": self.confirmed,
            "requested_at": self.requested_at,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class WorkbenchActionResult:
    """Closed result returned by direct, local UI, and HTTP action execution."""

    action_id: str
    request_id: str
    outcome: WorkbenchActionOutcome
    reason_code: WorkbenchActionReasonCode
    message: str
    action: str = ""
    target_id: str = ""
    affected_refs: tuple[str, ...] = ()
    audit_refs: tuple[str, ...] = ()
    audit_durability: ActionAuditDurability = "process_local"
    updated_at: str = ""
    retryable: bool = False
    safe_refresh: bool = True
    recovery_required: bool = False
    provider_payload: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.action_id:
            raise InvalidArgumentError("action_id is required")
        if not self.request_id:
            raise InvalidArgumentError("request_id is required")
        if self.outcome not in _ACTION_OUTCOMES:
            raise InvalidArgumentError(f"invalid action outcome: {self.outcome!r}")
        if self.reason_code not in _ACTION_REASONS:
            raise InvalidArgumentError(
                f"invalid action reason code: {self.reason_code!r}"
            )
        if self.audit_durability not in _AUDIT_DURABILITIES:
            raise InvalidArgumentError(
                f"invalid audit durability: {self.audit_durability!r}"
            )
        if not self.message:
            raise InvalidArgumentError("message is required")

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "request_id": self.request_id,
            "outcome": self.outcome,
            "reason_code": self.reason_code,
            "message": self.message,
            "action": self.action,
            "target_id": self.target_id,
            "affected_refs": list(self.affected_refs),
            "audit_refs": list(self.audit_refs),
            "audit_durability": self.audit_durability,
            "updated_at": self.updated_at,
            "retryable": self.retryable,
            "safe_refresh": self.safe_refresh,
            "recovery_required": self.recovery_required,
            "provider_payload": dict(self.provider_payload),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "WorkbenchActionResult":
        return cls(
            action_id=str(payload["action_id"]),
            request_id=str(payload["request_id"]),
            outcome=cast(
                WorkbenchActionOutcome,
                _literal(payload["outcome"], _ACTION_OUTCOMES, "action outcome"),
            ),
            reason_code=cast(
                WorkbenchActionReasonCode,
                _literal(payload["reason_code"], _ACTION_REASONS, "action reason"),
            ),
            message=str(payload["message"]),
            action=str(payload.get("action") or ""),
            target_id=str(payload.get("target_id") or ""),
            affected_refs=tuple(str(item) for item in payload.get("affected_refs", ())),
            audit_refs=tuple(str(item) for item in payload.get("audit_refs", ())),
            audit_durability=cast(
                ActionAuditDurability,
                _literal(
                    payload.get("audit_durability") or "process_local",
                    _AUDIT_DURABILITIES,
                    "audit durability",
                ),
            ),
            updated_at=str(payload.get("updated_at") or ""),
            retryable=bool(payload.get("retryable", False)),
            safe_refresh=bool(payload.get("safe_refresh", True)),
            recovery_required=bool(payload.get("recovery_required", False)),
            provider_payload=dict(payload.get("provider_payload") or {}),
        )


@dataclass(frozen=True, slots=True)
class WorkbenchActionJournalEntry:
    """Operational idempotency record for one scoped workbench action."""

    action_id: str
    request_hash: str
    action: str
    principal_id: str
    workspace_id: str
    scope: str
    namespace: MemoryNamespace
    target_id: str
    lifecycle: ActionJournalLifecycle
    fencing_token: int
    created_at: str
    updated_at: str
    started_at: str = ""
    completed_at: str = ""
    result: WorkbenchActionResult | None = None
    recovery_required: bool = False

    def __post_init__(self) -> None:
        if not self.action_id:
            raise InvalidArgumentError("action_id is required")
        if not self.request_hash:
            raise InvalidArgumentError("request_hash is required")
        if not self.action:
            raise InvalidArgumentError("action is required")
        if not self.principal_id:
            raise InvalidArgumentError("principal_id is required")
        if not self.workspace_id:
            raise InvalidArgumentError("workspace_id is required")
        if not self.scope:
            raise InvalidArgumentError("scope is required")
        if not isinstance(self.namespace, MemoryNamespace):
            raise TypeError(
                "namespace must be MemoryNamespace"
            )  # allow-bare-raise: defensive type guard in dataclass
        if not self.target_id:
            raise InvalidArgumentError("target_id is required")
        if self.lifecycle not in _JOURNAL_LIFECYCLES:
            raise InvalidArgumentError(f"invalid journal lifecycle: {self.lifecycle!r}")
        if self.fencing_token <= 0:
            raise InvalidArgumentError("fencing_token must be positive")
        if not self.created_at or not self.updated_at:
            raise InvalidArgumentError("journal timestamps are required")

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "request_hash": self.request_hash,
            "action": self.action,
            "principal_id": self.principal_id,
            "workspace_id": self.workspace_id,
            "scope": self.scope,
            "namespace": self.namespace.as_dict(),
            "target_id": self.target_id,
            "lifecycle": self.lifecycle,
            "fencing_token": self.fencing_token,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "result": self.result.to_dict() if self.result is not None else None,
            "recovery_required": self.recovery_required,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "WorkbenchActionJournalEntry":
        result_payload = payload.get("result")
        return cls(
            action_id=str(payload["action_id"]),
            request_hash=str(payload["request_hash"]),
            action=str(payload["action"]),
            principal_id=str(payload["principal_id"]),
            workspace_id=str(payload["workspace_id"]),
            scope=str(payload["scope"]),
            namespace=MemoryNamespace.from_dict(dict(payload["namespace"])),
            target_id=str(payload["target_id"]),
            lifecycle=cast(
                ActionJournalLifecycle,
                _literal(
                    payload["lifecycle"],
                    _JOURNAL_LIFECYCLES,
                    "journal lifecycle",
                ),
            ),
            fencing_token=int(payload["fencing_token"]),
            created_at=str(payload["created_at"]),
            updated_at=str(payload["updated_at"]),
            started_at=str(payload.get("started_at") or ""),
            completed_at=str(payload.get("completed_at") or ""),
            result=(
                WorkbenchActionResult.from_dict(dict(result_payload))
                if isinstance(result_payload, dict)
                else None
            ),
            recovery_required=bool(payload.get("recovery_required", False)),
        )


__all__ = [
    "ActionAuditDurability",
    "ActionJournalLifecycle",
    "WorkbenchActionExecutionContext",
    "WorkbenchActionJournalEntry",
    "WorkbenchActionOutcome",
    "WorkbenchActionReasonCode",
    "WorkbenchActionResult",
]
