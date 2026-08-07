"""Pure structural authorization for delegated memory access."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

from sophiagraph.access.contracts import (
    AccessConstraint,
    DelegationMemoryGrant,
    MemoryAccessContext,
    MemoryAccessDecision,
    MemoryAccessReason,
    MemoryAccessRequest,
)
from sophiagraph.models import MemoryNamespace


def _compatible_namespace(
    left: MemoryNamespace, right: MemoryNamespace
) -> MemoryNamespace | None:
    values = left.as_dict()
    for key, value in right.as_dict().items():
        if key in values and values[key] != value:
            return None
        values[key] = value
    return MemoryNamespace.from_dict(values)


def intersect_memory_namespaces(
    left: tuple[MemoryNamespace, ...], right: tuple[MemoryNamespace, ...]
) -> tuple[MemoryNamespace, ...]:
    """Return compatible selector intersections without widening either side."""

    if not left:
        return right
    if not right:
        return left
    resolved = {
        tuple(sorted(candidate.as_dict().items())): candidate
        for first in left
        for second in right
        if (candidate := _compatible_namespace(first, second)) is not None
    }
    return tuple(resolved[key] for key in sorted(resolved))


def _intersect_values(left: tuple[str, ...], right: tuple[str, ...]) -> tuple[str, ...]:
    if not left:
        return right
    if not right:
        return left
    return tuple(sorted(set(left).intersection(right)))


def _denied(
    request: MemoryAccessRequest,
    reason: MemoryAccessReason,
    *,
    grant_id: str | None = None,
    evidence_refs: tuple[str, ...] = (),
) -> MemoryAccessDecision:
    return MemoryAccessDecision(
        allowed=False,
        operation=request.operation,
        reason=reason,
        grant_id=grant_id,
        evidence_refs=evidence_refs,
    )


def _grant_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _constraint_intersection(
    constraints: tuple[AccessConstraint, ...],
) -> (
    tuple[
        tuple[MemoryNamespace, ...],
        tuple[str, ...],
        tuple[str, ...],
        tuple[str, ...],
        list[int],
        list[int],
    ]
    | None
):
    namespaces: tuple[MemoryNamespace, ...] = ()
    workspaces: tuple[str, ...] = ()
    record_types: tuple[str, ...] = ()
    operations: tuple[str, ...] = ()
    result_limits: list[int] = []
    context_limits: list[int] = []
    for constraint in constraints:
        if constraint.mode == "deny_all":
            return None
        if constraint.mode == "unconstrained_trusted":
            continue
        if not constraint.namespaces:
            return None
        namespaces = intersect_memory_namespaces(namespaces, constraint.namespaces)
        workspaces = _intersect_values(workspaces, constraint.workspace_ids)
        record_types = _intersect_values(record_types, constraint.record_types)
        operations = _intersect_values(operations, constraint.operations)
        if not namespaces or (constraint.workspace_ids and not workspaces):
            return None
        if constraint.record_types and not record_types:
            return None
        if constraint.operations and not operations:
            return None
        if constraint.max_results is not None:
            result_limits.append(constraint.max_results)
        if constraint.max_context_tokens is not None:
            context_limits.append(constraint.max_context_tokens)
    return (
        namespaces,
        workspaces,
        record_types,
        operations,
        result_limits,
        context_limits,
    )


def _validate_delegated_grant(
    context: MemoryAccessContext,
    request: MemoryAccessRequest,
    grant: DelegationMemoryGrant,
    *,
    now: datetime | None,
    evidence: tuple[str, ...],
) -> tuple[MemoryAccessDecision | None, tuple[str, ...]]:
    evidence = (*evidence, f"grant:{grant.grant_id}")
    if grant.state != "active":
        return (
            _denied(
                request,
                "grant_inactive",
                grant_id=grant.grant_id,
                evidence_refs=evidence,
            ),
            evidence,
        )
    current = (now or datetime.now(UTC)).astimezone(UTC)
    issued = _grant_time(grant.issued_at)
    expires = _grant_time(grant.expires_at)
    if current < issued:
        reason: MemoryAccessReason = "grant_not_yet_active"
    elif current >= expires:
        reason = "grant_expired"
    elif request.grant_id != grant.grant_id:
        reason = "grant_mismatch"
    else:
        bindings = (
            (context.audience, grant.audience),
            (context.subject_agent_id, grant.subject_agent_id),
            (context.parent_run_id, grant.parent_run_id),
            (context.child_run_id, grant.child_run_id),
            (context.trace_parent_id, grant.trace_parent_id),
        )
        reason = (
            "grant_mismatch"
            if any(
                actual is None or actual != expected for actual, expected in bindings
            )
            else "allowed"
        )
    if reason != "allowed":
        return (
            _denied(
                request,
                reason,
                grant_id=grant.grant_id,
                evidence_refs=evidence,
            ),
            evidence,
        )
    if request.operation not in grant.operations:
        reason = "operation_denied"
    elif request.requested_depth > grant.max_depth:
        reason = "depth_exceeded"
    elif request.reshare and not grant.can_reshare:
        reason = "reshare_denied"
    else:
        return None, evidence
    return (
        _denied(
            request,
            reason,
            grant_id=grant.grant_id,
            evidence_refs=evidence,
        ),
        evidence,
    )


def _intersect_request_selectors(
    request: MemoryAccessRequest,
    *,
    namespaces: tuple[MemoryNamespace, ...],
    workspaces: tuple[str, ...],
    record_types: tuple[str, ...],
    delegated: bool,
    evidence: tuple[str, ...],
) -> tuple[
    MemoryAccessDecision | None,
    tuple[MemoryNamespace, ...],
    tuple[str, ...],
    tuple[str, ...],
]:
    if request.namespaces:
        namespaces = intersect_memory_namespaces(namespaces, request.namespaces)
    if delegated and not namespaces:
        return (
            _denied(
                request,
                "selector_denied",
                grant_id=request.grant_id,
                evidence_refs=evidence,
            ),
            namespaces,
            workspaces,
            record_types,
        )
    if request.workspace_ids:
        workspaces = _intersect_values(workspaces, request.workspace_ids)
        if delegated and not workspaces:
            return (
                _denied(
                    request,
                    "workspace_denied",
                    grant_id=request.grant_id,
                    evidence_refs=evidence,
                ),
                namespaces,
                workspaces,
                record_types,
            )
    if request.record_types:
        record_types = _intersect_values(record_types, request.record_types)
        if delegated and not record_types:
            return (
                _denied(
                    request,
                    "record_type_denied",
                    grant_id=request.grant_id,
                    evidence_refs=evidence,
                ),
                namespaces,
                workspaces,
                record_types,
            )
    return None, namespaces, workspaces, record_types


def evaluate_memory_access(
    context: MemoryAccessContext,
    request: MemoryAccessRequest,
    grant: DelegationMemoryGrant | None = None,
    *,
    now: datetime | None = None,
) -> MemoryAccessDecision:
    """Intersect trusted constraints and one authoritative grant projection."""

    evidence = context.evidence_refs
    intersection = _constraint_intersection(context.constraints)
    if intersection is None:
        return _denied(request, "constraint_denied", evidence_refs=evidence)
    namespaces, workspaces, record_types, operations, result_limits, context_limits = (
        intersection
    )

    if context.delegated:
        if grant is None:
            return _denied(request, "grant_required", evidence_refs=evidence)
        denial, evidence = _validate_delegated_grant(
            context,
            request,
            grant,
            now=now,
            evidence=evidence,
        )
        if denial is not None:
            return denial
        namespaces = intersect_memory_namespaces(namespaces, grant.namespaces)
        workspaces = _intersect_values(workspaces, grant.workspace_ids)
        record_types = _intersect_values(record_types, grant.record_types)
        operations = _intersect_values(operations, grant.operations)
        result_limits.append(grant.max_results)
        context_limits.append(grant.max_context_tokens)

    denial, namespaces, workspaces, record_types = _intersect_request_selectors(
        request,
        namespaces=namespaces,
        workspaces=workspaces,
        record_types=record_types,
        delegated=context.delegated,
        evidence=evidence,
    )
    if denial is not None:
        return denial
    if operations and request.operation not in operations:
        return _denied(
            request,
            "operation_denied",
            grant_id=request.grant_id,
            evidence_refs=evidence,
        )

    max_results = min(request.max_results, context.host_max_results, *result_limits)
    max_context_tokens = min(
        request.max_context_tokens,
        context.host_max_context_tokens,
        *context_limits,
    )
    return MemoryAccessDecision(
        allowed=True,
        operation=request.operation,
        reason="allowed" if context.delegated else "trusted_local",
        namespaces=namespaces or request.namespaces,
        workspace_ids=workspaces or request.workspace_ids,
        record_types=record_types or request.record_types,
        max_results=max_results,
        max_context_tokens=max_context_tokens,
        grant_id=request.grant_id,
        evidence_refs=evidence,
    )


def project_child_memory_grant(
    parent: DelegationMemoryGrant,
    *,
    grant_id: str,
    subject_agent_id: str,
    child_run_id: str,
    namespaces: tuple[MemoryNamespace, ...],
    operations: tuple[str, ...],
    max_results: int,
    max_context_tokens: int,
) -> DelegationMemoryGrant:
    """Create a strict child projection only when the parent permits re-sharing."""

    if not parent.can_reshare:
        raise ValueError("parent grant does not permit re-sharing")
    if parent.current_depth >= parent.max_depth:
        raise ValueError("parent grant has no remaining delegation depth")
    narrowed_namespaces = intersect_memory_namespaces(parent.namespaces, namespaces)
    narrowed_operations = _intersect_values(parent.operations, operations)
    if not namespaces or set(narrowed_namespaces) != set(namespaces):
        raise ValueError("child namespaces must be a strict parent subset")
    if not operations or set(narrowed_operations) != set(operations):
        raise ValueError("child operations must be a parent subset")
    if (
        max_results > parent.max_results
        or max_context_tokens > parent.max_context_tokens
    ):
        raise ValueError("child budgets cannot widen parent budgets")
    return replace(
        parent,
        grant_id=grant_id,
        delegator_agent_id=parent.subject_agent_id,
        subject_agent_id=subject_agent_id,
        parent_run_id=parent.child_run_id,
        child_run_id=child_run_id,
        namespaces=namespaces,
        operations=operations,  # type: ignore[arg-type]
        max_results=max_results,
        max_context_tokens=max_context_tokens,
        parent_grant_id=parent.grant_id,
        current_depth=parent.current_depth + 1,
        can_reshare=False,
    )


__all__ = ["evaluate_memory_access", "project_child_memory_grant"]
