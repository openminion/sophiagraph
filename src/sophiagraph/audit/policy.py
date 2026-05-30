"""Typed policy hook interfaces with deterministic decisions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from sophiagraph.audit.governance import (
    POLICY_DECISION_ACTIONS,
    POLICY_DENIAL_REASON_CODES,
    POLICY_SURFACES,
    PolicyDecisionAction,
    PolicyDenialEvent,
    PolicyDenialReasonCode,
    PolicySurface,
)
from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.models.namespace import MemoryNamespace


@dataclass(frozen=True)
class PolicyRequest:
    """Inputs to a policy hook."""

    namespace: MemoryNamespace
    surface: PolicySurface
    source_owner: str
    target_kind: str
    target_id: str | None = None
    payload_kind: str | None = None
    payload_meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.namespace, MemoryNamespace):
            raise InvalidArgumentError("namespace must be a MemoryNamespace")
        if self.surface not in POLICY_SURFACES:
            raise InvalidArgumentError(
                f"unknown surface: {self.surface!r}; allowed: {sorted(POLICY_SURFACES)}"
            )
        if not isinstance(self.source_owner, str) or not self.source_owner:
            raise InvalidArgumentError("source_owner must be a non-empty string")
        if not isinstance(self.target_kind, str) or not self.target_kind:
            raise InvalidArgumentError("target_kind must be a non-empty string")
        if not isinstance(self.payload_meta, dict):
            raise InvalidArgumentError("payload_meta must be a dict")


@dataclass(frozen=True)
class PolicyDecision:
    """Typed decision returned by a policy hook."""

    action: PolicyDecisionAction
    policy_id: str
    reason_code: PolicyDenialReasonCode | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.action not in POLICY_DECISION_ACTIONS:
            raise InvalidArgumentError(
                f"unknown action: {self.action!r}; "
                f"allowed: {sorted(POLICY_DECISION_ACTIONS)}"
            )
        if not isinstance(self.policy_id, str) or not self.policy_id:
            raise InvalidArgumentError("policy_id must be a non-empty string")
        if self.action == "deny":
            if self.reason_code is None:
                raise InvalidArgumentError("deny action requires reason_code")
            if self.reason_code not in POLICY_DENIAL_REASON_CODES:
                raise InvalidArgumentError(
                    f"unknown reason_code: {self.reason_code!r}; "
                    f"allowed: {sorted(POLICY_DENIAL_REASON_CODES)}"
                )
        else:  # allow
            if self.reason_code is not None:
                raise InvalidArgumentError("allow action forbids reason_code")
        if not isinstance(self.details, dict):
            raise InvalidArgumentError("details must be a dict")

    @property
    def allowed(self) -> bool:
        return self.action == "allow"

    @property
    def denied(self) -> bool:
        return self.action == "deny"


class PolicyHook(Protocol):
    """Callable that takes a ``PolicyRequest`` and returns a ``PolicyDecision``."""

    def __call__(self, request: PolicyRequest) -> PolicyDecision: ...


PolicyHookCallable = Callable[[PolicyRequest], PolicyDecision]


def evaluate_policy_hooks(
    request: PolicyRequest,
    hooks: list[PolicyHookCallable] | tuple[PolicyHookCallable, ...],
) -> PolicyDecision:
    """Evaluate hooks left-to-right; short-circuit on the first deny."""

    if not isinstance(request, PolicyRequest):
        raise InvalidArgumentError("request must be a PolicyRequest")
    if not isinstance(hooks, (list, tuple)):
        raise InvalidArgumentError("hooks must be a list or tuple")
    for hook in hooks:
        if not callable(hook):
            raise InvalidArgumentError("each hook must be callable")
        decision = hook(request)
        if not isinstance(decision, PolicyDecision):
            raise InvalidArgumentError("hook must return a PolicyDecision instance")
        if decision.denied:
            return decision
    return PolicyDecision(action="allow", policy_id="<aggregate>")


def build_policy_denial_event(
    request: PolicyRequest,
    decision: PolicyDecision,
) -> PolicyDenialEvent:
    """Build a ``PolicyDenialEvent`` from a denying ``PolicyDecision``."""

    if not isinstance(request, PolicyRequest):
        raise InvalidArgumentError("request must be a PolicyRequest")
    if not isinstance(decision, PolicyDecision):
        raise InvalidArgumentError("decision must be a PolicyDecision")
    if not decision.denied:
        raise InvalidArgumentError(
            "build_policy_denial_event requires a denying decision"
        )
    return PolicyDenialEvent(
        namespace=request.namespace,
        surface=request.surface,
        reason_code=decision.reason_code,  # type: ignore[arg-type]
        policy_id=decision.policy_id,
        source_owner=request.source_owner,
        target_kind=request.target_kind,
        target_id=request.target_id,
        details=dict(decision.details or {}),
    )


__all__ = [
    "PolicyDecision",
    "PolicyHook",
    "PolicyHookCallable",
    "PolicyRequest",
    "build_policy_denial_event",
    "evaluate_policy_hooks",
]
