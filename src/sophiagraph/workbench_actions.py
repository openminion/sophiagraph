"""Executable workbench action owner for Sophiagraph."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Protocol

from sophiagraph.audit.events import MemoryAuditEvent
from sophiagraph.candidate_review import (
    CandidateReviewDecision,
    apply_candidate_promotion_plan,
    apply_candidate_review,
    build_candidate_promotion_plan,
)
from sophiagraph.contracts.errors import InvalidArgumentError, NotFoundError
from sophiagraph.models import (
    MemoryCandidate,
    MemoryNamespace,
    ActionAuditDurability,
    WorkbenchActionExecutionContext,
    WorkbenchActionJournalEntry,
    WorkbenchActionOutcome,
    WorkbenchActionReasonCode,
    WorkbenchActionResult,
)
from sophiagraph.storage.base import SophiaGraphStore
from sophiagraph.temporal import utc_now_iso
from sophiagraph.telemetry import (
    NullTelemetrySink,
    TelemetryEvent,
    TelemetrySink,
    safe_telemetry_attributes,
)
from sophiagraph.workbench import WorkbenchActionRequest
from sophiagraph.workspace_common import normalize_workspace_relative_path
from sophiagraph.workspace_notes import (
    WorkspaceFilePrimaryNoteOptions,
    workspace_file_primary_note_put,
)

EXECUTABLE_WORKBENCH_ACTIONS = frozenset(
    {
        "approve_candidate",
        "reject_candidate",
        "promote_candidate",
        "save_note",
    }
)
PREVIEW_ONLY_WORKBENCH_ACTIONS = frozenset(
    {"apply_repair", "build_publish_plan", "open_graph_selection"}
)
HOST_REQUIRED_WORKBENCH_ACTIONS = frozenset({"restore_workspace"})
REVIEW_ONLY_WORKBENCH_ACTIONS = frozenset(
    {"propose_note_edit", "approve_workspace_edit", "reject_workspace_edit"}
)
PAYLOAD_IDENTITY_KEYS = frozenset(
    {
        "actor_id",
        "principal_id",
        "auth_token",
        "tenant_id",
        "namespace",
        "scope",
        "workspace_id",
    }
)


class WorkbenchActionStore(SophiaGraphStore, Protocol):
    """Store subset needed by the executable workbench action owner."""


class WorkbenchActionCrash(RuntimeError):
    """Test-only fault injection after a side effect but before finalization."""


def execute_workbench_action(
    store: WorkbenchActionStore,
    request: WorkbenchActionRequest,
    context: WorkbenchActionExecutionContext,
    *,
    telemetry_sink: TelemetrySink | None = None,
    fault_after_side_effect: bool = False,
) -> WorkbenchActionResult:
    """Reserve, execute, audit, and finalize one trusted workbench action."""

    sink = telemetry_sink or NullTelemetrySink()
    preflight = _preflight_request(request, context)
    if preflight is not None:
        _record_action_telemetry(sink, request.action, preflight)
        return preflight
    now = context.requested_at or utc_now_iso()
    request_hash = workbench_action_request_hash(request, context)
    new_entry = WorkbenchActionJournalEntry(
        action_id=context.action_id,
        request_hash=request_hash,
        action=request.action,
        principal_id=context.principal_id,
        workspace_id=context.workspace_id,
        scope=context.scope,
        namespace=context.namespace,
        target_id=request.target_id,
        lifecycle="reserved",
        fencing_token=1,
        created_at=now,
        updated_at=now,
    )
    entry = store.reserve_workbench_action(new_entry)
    if entry != new_entry:
        replay = _result_for_existing_entry(entry, request_hash, context)
        if replay is not None:
            _record_action_telemetry(sink, request.action, replay)
            return replay
    started = utc_now_iso()
    entry = store.mark_workbench_action_in_progress(
        entry.action_id,
        fencing_token=entry.fencing_token,
        started_at=started,
    )
    side_effect_done = False
    try:
        result = _execute_reserved_action(store, request, context)
        side_effect_done = result.outcome == "applied"
        if side_effect_done and fault_after_side_effect:
            raise WorkbenchActionCrash("simulated action crash after side effect")
    except WorkbenchActionCrash:
        raise
    except (InvalidArgumentError, NotFoundError) as exc:
        result = _typed_error_result(request, context, exc)
    except Exception as exc:  # pragma: no cover - defensive package boundary
        result = _result(
            request,
            context,
            outcome="failed",
            reason_code="execution_failed",
            message=f"action failed: {type(exc).__name__}",
            retryable=False,
        )
    completed = utc_now_iso()
    result = _with_action_audit_ref(store, result)
    store.finalize_workbench_action(
        entry.action_id,
        fencing_token=entry.fencing_token,
        result=result,
        completed_at=completed,
    )
    _record_action_telemetry(sink, request.action, result)
    return result


def preview_workbench_execution(
    request: WorkbenchActionRequest,
    context: WorkbenchActionExecutionContext,
) -> WorkbenchActionResult:
    """Return the execution posture without reserving or mutating."""

    preflight = _preflight_request(request, context)
    if preflight is not None:
        return preflight
    if request.action in EXECUTABLE_WORKBENCH_ACTIONS:
        return _result(
            request,
            context,
            outcome="preview_only",
            reason_code="preview_only",
            message="action can be executed by the trusted workbench executor",
            provider_payload={"executable": True},
        )
    return _posture_result(request, context)


def workbench_action_status(
    store: WorkbenchActionStore,
    *,
    action_id: str,
    scope: str,
    namespace: MemoryNamespace,
) -> WorkbenchActionJournalEntry | None:
    """Return a scoped journal entry, denying cross-namespace lookups."""

    return store.get_workbench_action(action_id, scope=scope, namespace=namespace)


def prune_workbench_action_journal(
    store: WorkbenchActionStore,
    *,
    completed_before: str,
) -> int:
    """Prune terminal non-recovery action journal entries."""

    return store.prune_workbench_actions(completed_before=completed_before)


def workbench_action_request_hash(
    request: WorkbenchActionRequest,
    context: WorkbenchActionExecutionContext,
) -> str:
    payload = {
        "request": asdict(request),
        "principal_id": context.principal_id,
        "workspace_id": context.workspace_id,
        "scope": context.scope,
        "namespace": context.namespace.as_dict(),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return sha256(encoded.encode("utf-8")).hexdigest()


def _execute_reserved_action(
    store: WorkbenchActionStore,
    request: WorkbenchActionRequest,
    context: WorkbenchActionExecutionContext,
) -> WorkbenchActionResult:
    if request.action in PREVIEW_ONLY_WORKBENCH_ACTIONS:
        return _posture_result(request, context)
    if request.action in HOST_REQUIRED_WORKBENCH_ACTIONS:
        return _posture_result(request, context)
    if request.action in REVIEW_ONLY_WORKBENCH_ACTIONS:
        return _posture_result(request, context)
    if request.action in {"approve_candidate", "reject_candidate"}:
        return _execute_candidate_review(store, request, context)
    if request.action == "promote_candidate":
        return _execute_candidate_promotion(store, request, context)
    if request.action == "save_note":
        return _execute_save_note(request, context)
    return _result(
        request,
        context,
        outcome="unsupported",
        reason_code="unsupported_action",
        message=f"unsupported workbench action: {request.action}",
        retryable=False,
    )


def _execute_candidate_review(
    store: WorkbenchActionStore,
    request: WorkbenchActionRequest,
    context: WorkbenchActionExecutionContext,
) -> WorkbenchActionResult:
    candidate_id = _candidate_id(request.target_id)
    candidate = _scoped_candidate(store, candidate_id, context)
    stale = _stale_candidate_result(request, context, candidate)
    if stale is not None:
        return stale
    events: list[MemoryAuditEvent] = []
    updated = apply_candidate_review(
        store,
        CandidateReviewDecision(
            candidate_id=candidate_id,
            action="approve" if request.action == "approve_candidate" else "reject",
            reviewer=context.principal_id,
            note=_payload_string(request.payload, "note"),
        ),
        audit_recorder=events.append,
    )
    return _result(
        request,
        context,
        outcome="applied",
        reason_code="applied",
        message=f"candidate {updated.status}",
        target_id=candidate_id,
        affected_refs=(f"candidate:{candidate_id}",),
        audit_refs=tuple(f"audit:{event.event_id}" for event in events),
        updated_at=updated.updated_at or "",
        provider_payload={"candidate_status": updated.status},
    )


def _execute_candidate_promotion(
    store: WorkbenchActionStore,
    request: WorkbenchActionRequest,
    context: WorkbenchActionExecutionContext,
) -> WorkbenchActionResult:
    candidate_id = _candidate_id(request.target_id)
    candidate = _scoped_candidate(store, candidate_id, context)
    stale = _stale_candidate_result(request, context, candidate)
    if stale is not None:
        return stale
    if candidate.status != "approved":
        return _result(
            request,
            context,
            outcome="blocked",
            reason_code="candidate_not_approved",
            message="candidate must be approved before promotion",
            target_id=candidate_id,
            retryable=False,
        )
    evidence_refs = _payload_string_tuple(request.payload, "evidence_refs")
    if not evidence_refs:
        evidence_refs = tuple(ref.ref for ref in candidate.evidence_refs)
    if not evidence_refs:
        return _result(
            request,
            context,
            outcome="blocked",
            reason_code="missing_evidence",
            message="promotion requires explicit evidence refs",
            target_id=candidate_id,
            retryable=False,
        )
    target_scope = _payload_string(request.payload, "target_scope") or context.scope
    if target_scope != context.scope:
        return _scope_denied_result(request, context)
    events: list[MemoryAuditEvent] = []
    plan = build_candidate_promotion_plan(
        store,
        candidate_id=candidate_id,
        target_scope=target_scope,
        reviewer=context.principal_id,
        evidence_refs=evidence_refs,
        provenance={"request_id": context.request_id, "action_id": context.action_id},
    )
    applied = apply_candidate_promotion_plan(store, plan, audit_recorder=events.append)
    updated_candidate = store.get_candidate(candidate_id)
    return _result(
        request,
        context,
        outcome="applied",
        reason_code="applied",
        message="candidate promoted",
        target_id=candidate_id,
        affected_refs=(f"candidate:{candidate_id}", f"record:{applied.record_id}"),
        audit_refs=tuple(f"audit:{event.event_id}" for event in events),
        updated_at=(updated_candidate.updated_at if updated_candidate else "") or "",
        provider_payload={
            "candidate_status": "promoted",
            "record_id": applied.record_id,
            "promotion_plan_id": plan.plan_id,
        },
    )


def _execute_save_note(
    request: WorkbenchActionRequest,
    context: WorkbenchActionExecutionContext,
) -> WorkbenchActionResult:
    if not context.workspace_root or not context.source_root:
        return _result(
            request,
            context,
            outcome="blocked",
            reason_code="host_required",
            message="file-primary note save requires configured workspace and source roots",
            retryable=False,
        )
    note_key = _payload_string(request.payload, "note_key") or request.target_id
    title = _payload_string(request.payload, "title") or note_key
    body = _payload_string(request.payload, "body")
    if not body:
        return _result(
            request,
            context,
            outcome="failed",
            reason_code="invalid_payload",
            message="save_note requires body",
            retryable=False,
        )
    relative_path = _payload_string(request.payload, "relative_path") or None
    expected_hash = (
        _payload_string(request.payload, "expected_content_sha256")
        or context.expected_content_sha256
    )
    if relative_path is not None:
        target = Path(context.source_root) / normalize_workspace_relative_path(
            relative_path
        )
        if target.exists() and not expected_hash:
            return _result(
                request,
                context,
                outcome="conflict",
                reason_code="stale_precondition",
                message="existing note updates require expected_content_sha256",
                retryable=True,
            )
        if expected_hash and target.exists() and _sha256_file(target) != expected_hash:
            return _result(
                request,
                context,
                outcome="conflict",
                reason_code="stale_precondition",
                message="note content hash precondition failed",
                retryable=True,
            )
    saved = workspace_file_primary_note_put(
        context.workspace_root,
        context.source_root,
        options=WorkspaceFilePrimaryNoteOptions(
            note_key=note_key,
            title=title,
            body=body,
            tags=_payload_string_tuple(request.payload, "tags"),
            relative_path=relative_path,
        ),
    )
    return _result(
        request,
        context,
        outcome="applied",
        reason_code="applied",
        message="note saved",
        target_id=note_key,
        affected_refs=(f"record:{saved.record_id}", f"file:{saved.relative_path}"),
        updated_at=saved.written_at,
        provider_payload=saved.to_dict(),
    )


def _preflight_request(
    request: WorkbenchActionRequest,
    context: WorkbenchActionExecutionContext,
) -> WorkbenchActionResult | None:
    if request.actor_id != context.principal_id or request.workspace_id != (
        context.workspace_id
    ):
        return _result(
            request,
            context,
            outcome="blocked",
            reason_code="impersonation_denied",
            message="action identity must come from the trusted execution context",
            retryable=False,
        )
    if PAYLOAD_IDENTITY_KEYS.intersection(request.payload):
        return _result(
            request,
            context,
            outcome="blocked",
            reason_code="impersonation_denied",
            message="payload identity and scope fields are not accepted",
            retryable=False,
        )
    return None


def _result_for_existing_entry(
    entry: WorkbenchActionJournalEntry,
    request_hash: str,
    context: WorkbenchActionExecutionContext,
) -> WorkbenchActionResult | None:
    if entry.request_hash != request_hash:
        return WorkbenchActionResult(
            action_id=context.action_id,
            request_id=context.request_id,
            outcome="conflict",
            reason_code="idempotency_conflict",
            message="action_id was already used for a different request",
            action=entry.action,
            target_id=entry.target_id,
            retryable=False,
        )
    if entry.lifecycle == "terminal" and entry.result is not None:
        return entry.result
    if entry.lifecycle in {"reserved", "in_progress"}:
        return WorkbenchActionResult(
            action_id=context.action_id,
            request_id=context.request_id,
            outcome="blocked",
            reason_code="reservation_in_progress",
            message="action reservation is already in progress",
            action=entry.action,
            target_id=entry.target_id,
            retryable=True,
            provider_payload={"journal_lifecycle": entry.lifecycle},
        )
    return None


def _posture_result(
    request: WorkbenchActionRequest,
    context: WorkbenchActionExecutionContext,
) -> WorkbenchActionResult:
    if request.action in PREVIEW_ONLY_WORKBENCH_ACTIONS:
        return _result(
            request,
            context,
            outcome="preview_only",
            reason_code="preview_only",
            message="action is preview-only in Sophiagraph v1",
            retryable=False,
            provider_payload={"host_required": False},
        )
    if request.action in HOST_REQUIRED_WORKBENCH_ACTIONS:
        return _result(
            request,
            context,
            outcome="blocked",
            reason_code="host_required",
            message="action requires a host-owned restore workflow",
            retryable=False,
            provider_payload={"host_required": True},
        )
    return _result(
        request,
        context,
        outcome="unsupported",
        reason_code="review_not_persisted",
        message="review-only action has no persisted review owner in v1",
        retryable=False,
    )


def _typed_error_result(
    request: WorkbenchActionRequest,
    context: WorkbenchActionExecutionContext,
    exc: InvalidArgumentError | NotFoundError,
) -> WorkbenchActionResult:
    if isinstance(exc, NotFoundError):
        return _result(
            request,
            context,
            outcome="not_found",
            reason_code="target_not_found",
            message=exc.message,
            retryable=False,
        )
    reason: WorkbenchActionReasonCode = "invalid_payload"
    if "outside the authorized scope" in exc.message:
        return _scope_denied_result(request, context)
    if "unknown candidate_id" in exc.message:
        return _result(
            request,
            context,
            outcome="not_found",
            reason_code="target_not_found",
            message=exc.message,
            retryable=False,
        )
    if "approved before promotion" in exc.message:
        reason = "candidate_not_approved"
    if "evidence_refs" in exc.message:
        reason = "missing_evidence"
    return _result(
        request,
        context,
        outcome="blocked" if reason != "invalid_payload" else "failed",
        reason_code=reason,
        message=exc.message,
        retryable=False,
    )


def _result(
    request: WorkbenchActionRequest,
    context: WorkbenchActionExecutionContext,
    *,
    outcome: WorkbenchActionOutcome,
    reason_code: WorkbenchActionReasonCode,
    message: str,
    target_id: str = "",
    affected_refs: tuple[str, ...] = (),
    audit_refs: tuple[str, ...] = (),
    updated_at: str = "",
    retryable: bool = False,
    provider_payload: dict[str, Any] | None = None,
) -> WorkbenchActionResult:
    return WorkbenchActionResult(
        action_id=context.action_id,
        request_id=context.request_id,
        outcome=outcome,
        reason_code=reason_code,
        message=message,
        action=request.action,
        target_id=target_id or request.target_id,
        affected_refs=affected_refs,
        audit_refs=audit_refs,
        audit_durability="process_local",
        updated_at=updated_at,
        retryable=retryable,
        safe_refresh=True,
        provider_payload=dict(provider_payload or {}),
    )


def _with_action_audit_ref(
    store: WorkbenchActionStore,
    result: WorkbenchActionResult,
) -> WorkbenchActionResult:
    durability = _audit_durability(store)
    audit_refs = (f"action_journal:{result.action_id}", *result.audit_refs)
    return WorkbenchActionResult(
        action_id=result.action_id,
        request_id=result.request_id,
        outcome=result.outcome,
        reason_code=result.reason_code,
        message=result.message,
        action=result.action,
        target_id=result.target_id,
        affected_refs=result.affected_refs,
        audit_refs=audit_refs,
        audit_durability=durability,
        updated_at=result.updated_at,
        retryable=result.retryable,
        safe_refresh=result.safe_refresh,
        recovery_required=result.recovery_required,
        provider_payload=dict(result.provider_payload),
    )


def _audit_durability(store: WorkbenchActionStore) -> ActionAuditDurability:
    return "durable" if hasattr(store, "db_path") else "process_local"


def _candidate_id(target_id: str) -> str:
    return target_id.removeprefix("candidate:")


def _scoped_candidate(
    store: WorkbenchActionStore,
    candidate_id: str,
    context: WorkbenchActionExecutionContext,
) -> MemoryCandidate:
    candidate = store.get_candidate(candidate_id)
    if candidate is None:
        raise NotFoundError(f"unknown candidate_id: {candidate_id}")
    candidate_namespace = candidate.namespace or MemoryNamespace.from_scope(
        candidate.proposed_scope
    )
    if candidate.proposed_scope != context.scope or candidate_namespace != (
        context.namespace
    ):
        raise InvalidArgumentError("candidate is outside the authorized scope")
    return candidate


def _stale_candidate_result(
    request: WorkbenchActionRequest,
    context: WorkbenchActionExecutionContext,
    candidate: MemoryCandidate,
) -> WorkbenchActionResult | None:
    expected = (
        _payload_string(request.payload, "expected_updated_at")
        or context.expected_updated_at
    )
    if expected and candidate.updated_at != expected:
        return _result(
            request,
            context,
            outcome="conflict",
            reason_code="stale_precondition",
            message="candidate updated_at precondition failed",
            target_id=candidate.candidate_id,
            retryable=True,
        )
    return None


def _scope_denied_result(
    request: WorkbenchActionRequest,
    context: WorkbenchActionExecutionContext,
) -> WorkbenchActionResult:
    return _result(
        request,
        context,
        outcome="blocked",
        reason_code="scope_denied",
        message="requested target scope is outside the trusted context",
        retryable=False,
    )


def _payload_string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    return str(value).strip() if value is not None else ""


def _payload_string_tuple(payload: dict[str, Any], key: str) -> tuple[str, ...]:
    value = payload.get(key)
    if value is None:
        return ()
    if isinstance(value, str):
        return tuple(item.strip() for item in value.split(",") if item.strip())
    if isinstance(value, (list, tuple)):
        return tuple(str(item).strip() for item in value if str(item).strip())
    raise InvalidArgumentError(f"{key} must be a string or list of strings")


def _sha256_file(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _record_action_telemetry(
    sink: TelemetrySink,
    action: str,
    result: WorkbenchActionResult,
) -> None:
    sink.record(
        TelemetryEvent(
            name="sophiagraph.workbench.action",
            duration_ms=0.0,
            attributes=safe_telemetry_attributes(
                {
                    "operation": "workbench_action",
                    "action_kind": action,
                    "outcome": result.outcome,
                    "reason_code": result.reason_code,
                    "target_kind": result.action,
                }
            ),
        )
    )


ActionRequestMapper = Callable[
    [str, dict[str, Any], WorkbenchActionExecutionContext],
    WorkbenchActionRequest,
]


__all__ = [
    "EXECUTABLE_WORKBENCH_ACTIONS",
    "HOST_REQUIRED_WORKBENCH_ACTIONS",
    "PAYLOAD_IDENTITY_KEYS",
    "PREVIEW_ONLY_WORKBENCH_ACTIONS",
    "REVIEW_ONLY_WORKBENCH_ACTIONS",
    "ActionRequestMapper",
    "WorkbenchActionCrash",
    "WorkbenchActionStore",
    "execute_workbench_action",
    "preview_workbench_execution",
    "prune_workbench_action_journal",
    "workbench_action_request_hash",
    "workbench_action_status",
]
