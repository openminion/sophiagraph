from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta

import pytest

from sophiagraph.access import (
    AccessConstraint,
    DelegationMemoryGrant,
    MemoryAccessContext,
    MemoryAccessRequest,
    evaluate_memory_access,
    project_child_memory_grant,
)
from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.models import MemoryNamespace


def _grant(**overrides: object) -> DelegationMemoryGrant:
    values: dict[str, object] = {
        "grant_id": "grant-1",
        "issuer_authority": "openminion-policy",
        "audience": "sophiagraph",
        "delegator_agent_id": "parent",
        "subject_agent_id": "child",
        "parent_run_id": "parent-run",
        "child_run_id": "child-run",
        "trace_parent_id": "trace-1",
        "namespaces": (MemoryNamespace(project_id="project-1"),),
        "workspace_ids": ("workspace-1",),
        "operations": ("read",),
        "record_types": ("fact",),
        "issued_at": "2026-08-06T00:00:00+00:00",
        "expires_at": "2026-08-07T00:00:00+00:00",
        "max_results": 20,
        "max_context_tokens": 2000,
    }
    values.update(overrides)
    return DelegationMemoryGrant(**values)  # type: ignore[arg-type]


def _context(*constraints: AccessConstraint) -> MemoryAccessContext:
    return MemoryAccessContext(
        principal_id="principal-child",
        audience="sophiagraph",
        subject_agent_id="child",
        parent_run_id="parent-run",
        child_run_id="child-run",
        trace_parent_id="trace-1",
        constraints=constraints,
        delegated=True,
        host_max_results=15,
        host_max_context_tokens=1500,
    )


def _request(**overrides: object) -> MemoryAccessRequest:
    values: dict[str, object] = {
        "operation": "read",
        "namespaces": (MemoryNamespace(project_id="project-1"),),
        "workspace_ids": ("workspace-1",),
        "record_types": ("fact",),
        "max_results": 10,
        "max_context_tokens": 1000,
        "grant_id": "grant-1",
    }
    values.update(overrides)
    return MemoryAccessRequest(**values)  # type: ignore[arg-type]


def test_grant_round_trip_is_stable_and_frozen() -> None:
    grant = _grant()
    assert DelegationMemoryGrant.from_dict(grant.to_dict()) == grant
    with pytest.raises(FrozenInstanceError):
        grant.grant_id = "changed"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("state", "unknown"),
        ("operations", ("guess",)),
        ("current_depth", 0),
        ("max_results", 0),
        ("max_context_tokens", -1),
    ],
)
def test_grant_rejects_invalid_closed_fields_and_budgets(
    field: str, value: object
) -> None:
    with pytest.raises(InvalidArgumentError):
        _grant(**{field: value})


def test_explicit_constraint_modes_do_not_infer_from_empty_tuples() -> None:
    request = _request()
    denied = evaluate_memory_access(
        _context(AccessConstraint(mode="deny_all")), request, _grant()
    )
    allowlist_empty = evaluate_memory_access(
        _context(AccessConstraint(mode="allowlist")), request, _grant()
    )
    trusted = evaluate_memory_access(
        MemoryAccessContext(
            principal_id="local", audience="sophiagraph", delegated=False
        ),
        MemoryAccessRequest(operation="read"),
    )
    assert denied.reason == "constraint_denied"
    assert allowlist_empty.reason == "constraint_denied"
    assert trusted.allowed and trusted.reason == "trusted_local"


def test_evaluator_intersects_all_selectors_and_budgets() -> None:
    constraint = AccessConstraint(
        mode="allowlist",
        namespaces=(MemoryNamespace(project_id="project-1", user_id="user-1"),),
        workspace_ids=("workspace-1",),
        record_types=("fact",),
        operations=("read",),
        max_results=8,
        max_context_tokens=800,
    )
    decision = evaluate_memory_access(
        _context(constraint),
        _request(),
        _grant(),
        now=datetime(2026, 8, 6, 12, tzinfo=UTC),
    )
    assert decision.allowed
    assert decision.max_results == 8
    assert decision.max_context_tokens == 800
    assert decision.namespaces == (
        MemoryNamespace(project_id="project-1", user_id="user-1"),
    )


@pytest.mark.parametrize(
    ("request_overrides", "grant_overrides", "reason"),
    [
        ({"grant_id": "copied"}, {}, "grant_mismatch"),
        ({"operation": "mutate"}, {}, "operation_denied"),
        ({"record_types": ("procedure",)}, {}, "record_type_denied"),
        ({"workspace_ids": ("workspace-2",)}, {}, "workspace_denied"),
        (
            {"namespaces": (MemoryNamespace(project_id="project-2"),)},
            {},
            "selector_denied",
        ),
        ({"requested_depth": 2}, {}, "depth_exceeded"),
        ({"reshare": True}, {}, "reshare_denied"),
        ({}, {"state": "revoked"}, "grant_inactive"),
    ],
)
def test_evaluator_fails_closed_for_mismatch_and_widening(
    request_overrides: dict[str, object],
    grant_overrides: dict[str, object],
    reason: str,
) -> None:
    decision = evaluate_memory_access(
        _context(),
        _request(**request_overrides),
        _grant(**grant_overrides),
        now=datetime(2026, 8, 6, 12, tzinfo=UTC),
    )
    assert not decision.allowed
    assert decision.reason == reason


def test_expired_and_missing_grants_deny_delegated_access() -> None:
    expired = evaluate_memory_access(
        _context(),
        _request(),
        _grant(),
        now=datetime(2026, 8, 8, tzinfo=UTC),
    )
    missing = evaluate_memory_access(_context(), _request(), None)
    assert expired.reason == "grant_expired"
    assert missing.reason == "grant_required"


def test_grant_issuance_and_expiry_boundaries_are_fail_closed() -> None:
    issued_at = datetime(2026, 8, 6, 12, tzinfo=UTC)
    expires_at = issued_at + timedelta(hours=1)
    grant = _grant(
        issued_at=issued_at.isoformat(),
        expires_at=expires_at.isoformat(),
    )
    before_issued = evaluate_memory_access(
        _context(),
        _request(),
        grant,
        now=issued_at - timedelta(microseconds=1),
    )
    exactly_issued = evaluate_memory_access(
        _context(), _request(), grant, now=issued_at
    )
    exactly_expired = evaluate_memory_access(
        _context(),
        _request(),
        grant,
        now=expires_at,
    )
    revoked = evaluate_memory_access(
        _context(),
        _request(),
        _grant(
            issued_at=issued_at.isoformat(),
            expires_at=expires_at.isoformat(),
            state="revoked",
        ),
        now=issued_at,
    )
    assert before_issued.reason == "grant_not_yet_active"
    assert exactly_issued.allowed
    assert exactly_expired.reason == "grant_expired"
    assert revoked.reason == "grant_inactive"


def test_unknown_request_operation_and_invalid_request_budget_are_rejected() -> None:
    with pytest.raises(InvalidArgumentError):
        _request(operation="infer")
    with pytest.raises(InvalidArgumentError):
        _request(max_results=0)
    with pytest.raises(InvalidArgumentError):
        _request(max_context_tokens=2_147_483_648)


def test_child_projection_is_strict_and_requires_explicit_reshare() -> None:
    with pytest.raises(ValueError, match="does not permit"):
        project_child_memory_grant(
            _grant(max_depth=2),
            grant_id="grant-child",
            subject_agent_id="grandchild",
            child_run_id="grandchild-run",
            namespaces=(MemoryNamespace(project_id="project-1"),),
            operations=("read",),
            max_results=5,
            max_context_tokens=500,
        )
    projected = project_child_memory_grant(
        _grant(can_reshare=True, max_depth=2),
        grant_id="grant-child",
        subject_agent_id="grandchild",
        child_run_id="grandchild-run",
        namespaces=(MemoryNamespace(project_id="project-1", agent_id="grandchild"),),
        operations=("read",),
        max_results=5,
        max_context_tokens=500,
    )
    assert projected.parent_grant_id == "grant-1"
    assert projected.current_depth == 2
    assert not projected.can_reshare

    with pytest.raises(ValueError, match="budgets"):
        project_child_memory_grant(
            _grant(can_reshare=True, max_depth=2),
            grant_id="grant-wide",
            subject_agent_id="grandchild",
            child_run_id="grandchild-run",
            namespaces=(MemoryNamespace(project_id="project-1"),),
            operations=("read",),
            max_results=21,
            max_context_tokens=500,
        )
