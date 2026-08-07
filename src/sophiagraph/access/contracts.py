"""Typed delegated-memory access contracts."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.models import MemoryNamespace

AccessConstraintMode = Literal["unconstrained_trusted", "deny_all", "allowlist"]
DelegationGrantState = Literal["active", "revoked", "expired", "cancelled"]
MemoryAccessOperation = Literal[
    "read", "propose", "promote", "mutate", "export", "admin"
]
MemoryAccessReason = Literal[
    "allowed",
    "trusted_local",
    "constraint_denied",
    "grant_required",
    "grant_unresolved",
    "grant_inactive",
    "grant_not_yet_active",
    "grant_expired",
    "grant_mismatch",
    "operation_denied",
    "record_type_denied",
    "selector_denied",
    "workspace_denied",
    "depth_exceeded",
    "reshare_denied",
    "invalid_budget",
    "policy_denied",
]

_OPERATIONS = frozenset({"read", "propose", "promote", "mutate", "export", "admin"})
_STATES = frozenset({"active", "revoked", "expired", "cancelled"})
_MODES = frozenset({"unconstrained_trusted", "deny_all", "allowlist"})
_MAX_BOUND = 2_147_483_647


def _require_positive(value: int | None, name: str) -> None:
    if value is not None and (
        not isinstance(value, int) or value <= 0 or value > _MAX_BOUND
    ):
        raise InvalidArgumentError(f"{name} must be a positive 32-bit integer")


def _parse_time(value: str, name: str) -> datetime:
    if not value:
        raise InvalidArgumentError(f"{name} is required")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise InvalidArgumentError(f"{name} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise InvalidArgumentError(f"{name} must include a timezone")
    return parsed.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class AccessConstraint:
    """One explicit allow, deny, or trusted-unconstrained access boundary."""

    mode: AccessConstraintMode
    namespaces: tuple[MemoryNamespace, ...] = ()
    workspace_ids: tuple[str, ...] = ()
    record_types: tuple[str, ...] = ()
    operations: tuple[MemoryAccessOperation, ...] = ()
    max_results: int | None = None
    max_context_tokens: int | None = None

    def __post_init__(self) -> None:
        if self.mode not in _MODES:
            raise InvalidArgumentError(f"invalid access constraint mode: {self.mode!r}")
        if any(operation not in _OPERATIONS for operation in self.operations):
            raise InvalidArgumentError("constraint contains an invalid operation")
        if any(not value for value in (*self.workspace_ids, *self.record_types)):
            raise InvalidArgumentError(
                "constraint allowlists cannot contain empty values"
            )
        _require_positive(self.max_results, "max_results")
        _require_positive(self.max_context_tokens, "max_context_tokens")


@dataclass(frozen=True, slots=True)
class DelegationMemoryGrant:
    """Host-issued projection authorizing bounded delegated memory access."""

    grant_id: str
    issuer_authority: str
    audience: str
    delegator_agent_id: str
    subject_agent_id: str
    parent_run_id: str
    child_run_id: str
    trace_parent_id: str
    namespaces: tuple[MemoryNamespace, ...]
    workspace_ids: tuple[str, ...]
    operations: tuple[MemoryAccessOperation, ...]
    issued_at: str
    expires_at: str
    max_results: int
    max_context_tokens: int
    schema_version: str = "1"
    state: DelegationGrantState = "active"
    parent_grant_id: str | None = None
    record_types: tuple[str, ...] = ()
    current_depth: int = 1
    max_depth: int = 1
    can_reshare: bool = False

    def __post_init__(self) -> None:
        required = {
            "grant_id": self.grant_id,
            "issuer_authority": self.issuer_authority,
            "audience": self.audience,
            "delegator_agent_id": self.delegator_agent_id,
            "subject_agent_id": self.subject_agent_id,
            "parent_run_id": self.parent_run_id,
            "child_run_id": self.child_run_id,
            "trace_parent_id": self.trace_parent_id,
            "schema_version": self.schema_version,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise InvalidArgumentError(
                f"required grant fields are empty: {', '.join(missing)}"
            )
        if self.state not in _STATES:
            raise InvalidArgumentError(f"invalid grant state: {self.state!r}")
        if not self.namespaces:
            raise InvalidArgumentError("delegated grants require namespace selectors")
        if not self.operations or any(
            item not in _OPERATIONS for item in self.operations
        ):
            raise InvalidArgumentError(
                "grant operations must be a non-empty closed-set allowlist"
            )
        if (
            self.current_depth < 1
            or self.max_depth < 1
            or self.current_depth > self.max_depth
        ):
            raise InvalidArgumentError(
                "grant depth must be positive and within max_depth"
            )
        _require_positive(self.max_results, "max_results")
        _require_positive(self.max_context_tokens, "max_context_tokens")
        if _parse_time(self.expires_at, "expires_at") <= _parse_time(
            self.issued_at, "issued_at"
        ):
            raise InvalidArgumentError("expires_at must be after issued_at")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "DelegationMemoryGrant":
        data = dict(value)
        data["namespaces"] = tuple(
            item
            if isinstance(item, MemoryNamespace)
            else MemoryNamespace.from_dict(item)
            for item in data.get("namespaces", ())
        )
        for key in ("workspace_ids", "operations", "record_types"):
            data[key] = tuple(data.get(key, ()))
        return cls(**data)


@dataclass(frozen=True, slots=True)
class MemoryAccessContext:
    """Trusted runtime identity and narrowing constraints for one operation."""

    principal_id: str
    audience: str
    subject_agent_id: str | None = None
    parent_run_id: str | None = None
    child_run_id: str | None = None
    trace_parent_id: str | None = None
    constraints: tuple[AccessConstraint, ...] = ()
    delegated: bool = False
    host_max_results: int = 1000
    host_max_context_tokens: int = 32768
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.principal_id or not self.audience:
            raise InvalidArgumentError("principal_id and audience are required")
        _require_positive(self.host_max_results, "host_max_results")
        _require_positive(self.host_max_context_tokens, "host_max_context_tokens")


@dataclass(frozen=True, slots=True)
class MemoryAccessRequest:
    """Requested delegated-memory operation before structural narrowing."""

    operation: MemoryAccessOperation
    namespaces: tuple[MemoryNamespace, ...] = ()
    workspace_ids: tuple[str, ...] = ()
    record_types: tuple[str, ...] = ()
    max_results: int = 50
    max_context_tokens: int = 4096
    grant_id: str | None = None
    requested_depth: int = 1
    reshare: bool = False

    def __post_init__(self) -> None:
        if self.operation not in _OPERATIONS:
            raise InvalidArgumentError(
                f"invalid memory access operation: {self.operation!r}"
            )
        _require_positive(self.max_results, "max_results")
        _require_positive(self.max_context_tokens, "max_context_tokens")
        if self.requested_depth < 1:
            raise InvalidArgumentError("requested_depth must be positive")


@dataclass(frozen=True, slots=True)
class MemoryAccessDecision:
    """Deterministic effective access decision returned before data access."""

    allowed: bool
    operation: MemoryAccessOperation
    reason: MemoryAccessReason
    namespaces: tuple[MemoryNamespace, ...] = ()
    workspace_ids: tuple[str, ...] = ()
    record_types: tuple[str, ...] = ()
    max_results: int = 0
    max_context_tokens: int = 0
    grant_id: str | None = None
    evidence_refs: tuple[str, ...] = ()


class DelegationMemoryGrantResolver(Protocol):
    """Package-neutral host resolver for authoritative grant state."""

    def resolve_grant(
        self,
        grant_id: str,
        *,
        context: MemoryAccessContext,
        operation: MemoryAccessOperation,
    ) -> DelegationMemoryGrant | None: ...


__all__ = [
    "AccessConstraint",
    "AccessConstraintMode",
    "DelegationGrantState",
    "DelegationMemoryGrant",
    "DelegationMemoryGrantResolver",
    "MemoryAccessContext",
    "MemoryAccessDecision",
    "MemoryAccessOperation",
    "MemoryAccessReason",
    "MemoryAccessRequest",
]
