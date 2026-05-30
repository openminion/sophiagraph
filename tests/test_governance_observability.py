"""Governance, policy hook, and observability tests."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from sophiagraph.audit import (
    ExportEvent,
    GOVERNANCE_EVENT_KINDS,
    LIFECYCLE_ACTIONS,
    LifecycleActionEvent,
    POLICY_DECISION_ACTIONS,
    POLICY_DENIAL_REASON_CODES,
    POLICY_SURFACES,
    PolicyDecision,
    PolicyDenialEvent,
    PolicyRequest,
    QUALITY_EVAL_SIGNAL_KINDS,
    QualityEvalSignal,
    RetrievalEvent,
    RetrievalExplanation,
    WEBHOOK_DELIVERY_STATUSES,
    WebhookDeliveryAttemptEvent,
    WriteAcceptedEvent,
    WriteAttemptEvent,
    build_policy_denial_event,
    evaluate_policy_hooks,
)
from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.models import MemoryNamespace


def _ns() -> MemoryNamespace:
    return MemoryNamespace(agent_id="a", session_id="s")


# Closed-enum membership pins.


def test_governance_event_kinds_is_a_closed_set() -> None:
    assert GOVERNANCE_EVENT_KINDS == {
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


def test_policy_surfaces_is_a_closed_set() -> None:
    assert POLICY_SURFACES == {"write", "export", "retention", "deletion"}


def test_policy_decision_actions_is_a_closed_set() -> None:
    assert POLICY_DECISION_ACTIONS == {"allow", "deny"}


def test_policy_denial_reason_codes_is_a_closed_set() -> None:
    assert POLICY_DENIAL_REASON_CODES == {
        "POLICY_DENIED_BY_HOOK",
        "POLICY_REQUIRED_FIELDS_MISSING",
        "POLICY_NAMESPACE_FORBIDDEN",
        "POLICY_RETENTION_EXPIRED",
        "POLICY_QUOTA_EXCEEDED",
        "POLICY_TRUST_THRESHOLD_NOT_MET",
    }


def test_quality_eval_signal_kinds_is_a_closed_set() -> None:
    assert QUALITY_EVAL_SIGNAL_KINDS == {
        "explicit_user_correction",
        "validation_passed",
        "validation_failed",
        "retrieval_used",
        "retrieval_ignored",
    }


def test_lifecycle_actions_is_a_closed_set() -> None:
    assert LIFECYCLE_ACTIONS == {
        "ttl_active_elapsed",
        "ttl_cooling_elapsed",
        "promotion_applied",
        "archived",
        "deleted",
        "no_transition",
    }


def test_webhook_delivery_statuses_is_a_closed_set() -> None:
    assert WEBHOOK_DELIVERY_STATUSES == {
        "pending",
        "succeeded",
        "failed",
        "abandoned",
    }


# Write attempt + accepted.


def test_write_attempt_round_trips_through_memory_audit_event() -> None:
    evt = WriteAttemptEvent(
        namespace=_ns(),
        payload_kind="document",
        source_owner="task-runner",
        target_kind="record",
        target_id="rec-1",
        idempotency_key="idem-1",
        trust_mode="direct",
    )
    audit = evt.to_memory_audit_event()
    assert audit.event_type == "memory.write_attempt"
    assert audit.target_id == "rec-1"
    assert audit.details["payload_kind"] == "document"
    assert audit.details["source_owner"] == "task-runner"
    assert audit.details["trust_mode"] == "direct"
    assert audit.details["idempotency_key"] == "idem-1"
    assert audit.details["namespace"]["agent_id"] == "a"


def test_write_attempt_requires_typed_namespace() -> None:
    with pytest.raises(InvalidArgumentError):
        WriteAttemptEvent(
            namespace={"agent_id": "a"},  # type: ignore[arg-type]
            payload_kind="document",
            source_owner="x",
            target_kind="record",
        )


def test_write_attempt_requires_nonempty_strings() -> None:
    for field in ("payload_kind", "source_owner", "target_kind"):
        kwargs = {
            "namespace": _ns(),
            "payload_kind": "document",
            "source_owner": "x",
            "target_kind": "record",
        }
        kwargs[field] = ""
        with pytest.raises(InvalidArgumentError):
            WriteAttemptEvent(**kwargs)


def test_write_accepted_requires_target_id() -> None:
    with pytest.raises(InvalidArgumentError):
        WriteAcceptedEvent(
            namespace=_ns(),
            payload_kind="document",
            source_owner="x",
            target_kind="record",
            target_id="",
        )
    evt = WriteAcceptedEvent(
        namespace=_ns(),
        payload_kind="document",
        source_owner="x",
        target_kind="record",
        target_id="rec-1",
    )
    audit = evt.to_memory_audit_event()
    assert audit.event_type == "memory.write_accepted"
    assert audit.target_id == "rec-1"


# Retrieval event + explanation.


def test_retrieval_event_records_selected_ids_and_omitted_count() -> None:
    evt = RetrievalEvent(
        namespace=_ns(),
        source_owner="task-runner",
        selected_ids=("rec-1", "rec-2"),
        omitted_count=3,
        retrieval_mode="local_graph",
        session_id="s",
    )
    audit = evt.to_memory_audit_event()
    assert audit.event_type == "memory.retrieval"
    assert audit.details["selected_ids"] == ["rec-1", "rec-2"]
    assert audit.details["omitted_count"] == 3
    assert audit.details["retrieval_mode"] == "local_graph"
    assert audit.session_id == "s"


def test_retrieval_event_rejects_non_tuple_selected_ids() -> None:
    with pytest.raises(InvalidArgumentError):
        RetrievalEvent(
            namespace=_ns(),
            source_owner="x",
            selected_ids=["rec-1"],  # type: ignore[arg-type]
        )


def test_retrieval_event_rejects_negative_omitted_count() -> None:
    with pytest.raises(InvalidArgumentError):
        RetrievalEvent(
            namespace=_ns(),
            source_owner="x",
            selected_ids=("rec-1",),
            omitted_count=-1,
        )


def test_retrieval_event_rejects_empty_id_in_tuple() -> None:
    with pytest.raises(InvalidArgumentError):
        RetrievalEvent(
            namespace=_ns(),
            source_owner="x",
            selected_ids=("rec-1", ""),
        )


def test_retrieval_explanation_carries_structural_fields_only() -> None:
    explanation = RetrievalExplanation(
        namespace=_ns(),
        record_id="rec-1",
        structural_score=0.72,
        embedding_score=0.91,
        matched_filters=("scope:session", "type:fact"),
        graph_path_ids=("path-1", "path-2"),
        retrieval_mode="hybrid",
    )
    assert explanation.record_id == "rec-1"
    assert explanation.structural_score == 0.72
    assert explanation.embedding_score == 0.91
    assert explanation.matched_filters == ("scope:session", "type:fact")


def test_retrieval_explanation_rejects_non_numeric_scores() -> None:
    with pytest.raises(InvalidArgumentError):
        RetrievalExplanation(
            namespace=_ns(),
            record_id="rec-1",
            structural_score="high",  # type: ignore[arg-type]
        )
    with pytest.raises(InvalidArgumentError):
        RetrievalExplanation(
            namespace=_ns(),
            record_id="rec-1",
            structural_score=0.5,
            embedding_score="med",  # type: ignore[arg-type]
        )


def test_retrieval_explanation_rejects_empty_strings_in_tuples() -> None:
    with pytest.raises(InvalidArgumentError):
        RetrievalExplanation(
            namespace=_ns(),
            record_id="rec-1",
            structural_score=0.5,
            matched_filters=("scope:session", ""),
        )


# Quality eval signal.


def test_quality_eval_signal_round_trips_through_audit_event() -> None:
    signal = QualityEvalSignal(
        namespace=_ns(),
        record_id="rec-1",
        signal_kind="validation_passed",
        source_owner="ci-runner",
        details={"validator_id": "lint"},
    )
    audit = signal.to_memory_audit_event()
    assert audit.event_type == "memory.quality_eval_signal"
    assert audit.target_id == "rec-1"
    assert audit.details["signal_kind"] == "validation_passed"
    assert audit.details["validator_id"] == "lint"


def test_quality_eval_signal_rejects_unknown_kind() -> None:
    with pytest.raises(InvalidArgumentError):
        QualityEvalSignal(
            namespace=_ns(),
            record_id="rec-1",
            signal_kind="hallucinated",  # type: ignore[arg-type]
            source_owner="ci",
        )


# Export event.


def test_export_event_round_trips_with_required_counts() -> None:
    evt = ExportEvent(
        namespace=_ns(),
        source_owner="admin-cli",
        record_count=10,
        relation_count=4,
        candidate_count=2,
        block_count=3,
        document_count=1,
        bundle_id="bundle-1",
    )
    audit = evt.to_memory_audit_event()
    assert audit.event_type == "memory.export"
    assert audit.target_id == "bundle-1"
    assert audit.details["record_count"] == 10
    assert audit.details["block_count"] == 3


def test_export_event_rejects_negative_counts() -> None:
    with pytest.raises(InvalidArgumentError):
        ExportEvent(
            namespace=_ns(),
            source_owner="x",
            record_count=-1,
        )


# Policy denial + lifecycle action + webhook.


def test_policy_denial_event_round_trips() -> None:
    evt = PolicyDenialEvent(
        namespace=_ns(),
        surface="write",
        reason_code="POLICY_NAMESPACE_FORBIDDEN",
        policy_id="forbid-anon",
        source_owner="task-runner",
        target_kind="record",
        target_id="rec-1",
        details={"required": "agent_id"},
    )
    audit = evt.to_memory_audit_event()
    assert audit.event_type == "memory.policy_denial"
    assert audit.details["surface"] == "write"
    assert audit.details["reason_code"] == "POLICY_NAMESPACE_FORBIDDEN"
    assert audit.details["required"] == "agent_id"


def test_policy_denial_event_rejects_unknown_surface() -> None:
    with pytest.raises(InvalidArgumentError):
        PolicyDenialEvent(
            namespace=_ns(),
            surface="moderation",  # type: ignore[arg-type]
            reason_code="POLICY_DENIED_BY_HOOK",
            policy_id="p",
            source_owner="x",
            target_kind="record",
        )


def test_policy_denial_event_rejects_unknown_reason_code() -> None:
    with pytest.raises(InvalidArgumentError):
        PolicyDenialEvent(
            namespace=_ns(),
            surface="write",
            reason_code="UNSAFE_CONTENT",  # type: ignore[arg-type]
            policy_id="p",
            source_owner="x",
            target_kind="record",
        )


def test_lifecycle_action_event_round_trips() -> None:
    evt = LifecycleActionEvent(
        namespace=_ns(),
        record_id="rec-1",
        action="ttl_active_elapsed",
        policy_id="p-1",
        from_phase="active",
        to_phase="cooling",
        job_id="job-1",
    )
    audit = evt.to_memory_audit_event()
    assert audit.event_type == "memory.lifecycle_action"
    assert audit.details["action"] == "ttl_active_elapsed"
    assert audit.details["from_phase"] == "active"
    assert audit.details["to_phase"] == "cooling"
    assert audit.details["job_id"] == "job-1"


def test_lifecycle_action_event_rejects_unknown_action() -> None:
    with pytest.raises(InvalidArgumentError):
        LifecycleActionEvent(
            namespace=_ns(),
            record_id="rec-1",
            action="vibe_shift",  # type: ignore[arg-type]
            policy_id="p",
            from_phase="active",
            to_phase="cooling",
        )


def test_webhook_delivery_attempt_event_round_trips() -> None:
    evt = WebhookDeliveryAttemptEvent(
        webhook_id="wh-1",
        delivery_id="dlv-1",
        status="succeeded",
        attempt=2,
        target_url_host="hooks.example.com",
        response_status_code=200,
    )
    audit = evt.to_memory_audit_event()
    assert audit.event_type == "memory.webhook_delivery_attempt"
    assert audit.target_id == "wh-1"
    assert audit.details["status"] == "succeeded"
    assert audit.details["attempt"] == 2
    assert audit.details["target_url_host"] == "hooks.example.com"
    assert audit.details["response_status_code"] == 200


def test_webhook_delivery_attempt_event_rejects_zero_attempt() -> None:
    with pytest.raises(InvalidArgumentError):
        WebhookDeliveryAttemptEvent(
            webhook_id="wh",
            delivery_id="dlv",
            status="pending",
            attempt=0,
            target_url_host="x",
        )


def test_webhook_delivery_attempt_event_rejects_unknown_status() -> None:
    with pytest.raises(InvalidArgumentError):
        WebhookDeliveryAttemptEvent(
            webhook_id="wh",
            delivery_id="dlv",
            status="weird",  # type: ignore[arg-type]
            attempt=1,
            target_url_host="x",
        )


# Policy hooks.


def _req(**kw) -> PolicyRequest:
    base = dict(
        namespace=_ns(),
        surface="write",
        source_owner="task-runner",
        target_kind="record",
    )
    base.update(kw)
    return PolicyRequest(**base)


def test_policy_decision_allow_forbids_reason_code() -> None:
    PolicyDecision(action="allow", policy_id="p")
    with pytest.raises(InvalidArgumentError):
        PolicyDecision(
            action="allow",
            policy_id="p",
            reason_code="POLICY_DENIED_BY_HOOK",
        )


def test_policy_decision_deny_requires_reason_code() -> None:
    with pytest.raises(InvalidArgumentError):
        PolicyDecision(action="deny", policy_id="p")
    decision = PolicyDecision(
        action="deny", policy_id="p", reason_code="POLICY_DENIED_BY_HOOK"
    )
    assert decision.denied
    assert not decision.allowed


def test_policy_decision_rejects_unknown_action() -> None:
    with pytest.raises(InvalidArgumentError):
        PolicyDecision(action="maybe", policy_id="p")  # type: ignore[arg-type]


def test_evaluate_policy_hooks_short_circuits_on_first_deny() -> None:
    calls: list[str] = []

    def allow_hook(req: PolicyRequest) -> PolicyDecision:
        calls.append("allow")
        return PolicyDecision(action="allow", policy_id="allow-1")

    def deny_hook(req: PolicyRequest) -> PolicyDecision:
        calls.append("deny")
        return PolicyDecision(
            action="deny",
            policy_id="deny-1",
            reason_code="POLICY_DENIED_BY_HOOK",
        )

    def should_not_run(req: PolicyRequest) -> PolicyDecision:
        calls.append("after_deny")
        return PolicyDecision(action="allow", policy_id="after")

    decision = evaluate_policy_hooks(_req(), [allow_hook, deny_hook, should_not_run])
    assert decision.denied
    assert decision.policy_id == "deny-1"
    assert calls == ["allow", "deny"]


def test_evaluate_policy_hooks_all_allow_returns_aggregate_allow() -> None:
    def allow_hook(req: PolicyRequest) -> PolicyDecision:
        return PolicyDecision(action="allow", policy_id="p")

    decision = evaluate_policy_hooks(_req(), [allow_hook, allow_hook])
    assert decision.allowed
    assert decision.policy_id == "<aggregate>"


def test_evaluate_policy_hooks_empty_list_allows_by_default() -> None:
    decision = evaluate_policy_hooks(_req(), [])
    assert decision.allowed


def test_evaluate_policy_hooks_rejects_non_callable() -> None:
    with pytest.raises(InvalidArgumentError):
        evaluate_policy_hooks(_req(), ["not_callable"])  # type: ignore[list-item]


def test_evaluate_policy_hooks_rejects_non_decision_return() -> None:
    def bad_hook(req: PolicyRequest):
        return {"action": "allow"}

    with pytest.raises(InvalidArgumentError):
        evaluate_policy_hooks(_req(), [bad_hook])  # type: ignore[list-item]


def test_build_policy_denial_event_requires_deny_decision() -> None:
    with pytest.raises(InvalidArgumentError):
        build_policy_denial_event(
            _req(),
            PolicyDecision(action="allow", policy_id="p"),
        )


def test_build_policy_denial_event_carries_request_fields() -> None:
    evt = build_policy_denial_event(
        _req(target_id="rec-1", payload_kind="document"),
        PolicyDecision(
            action="deny",
            policy_id="deny-1",
            reason_code="POLICY_DENIED_BY_HOOK",
            details={"hint": "manual review required"},
        ),
    )
    assert isinstance(evt, PolicyDenialEvent)
    assert evt.surface == "write"
    assert evt.reason_code == "POLICY_DENIED_BY_HOOK"
    assert evt.policy_id == "deny-1"
    assert evt.target_id == "rec-1"
    assert evt.details["hint"] == "manual review required"


# Anti-LLM source-token regression.


def test_governance_module_contains_no_llm_call_tokens() -> None:
    for filename in ("governance.py", "policy.py"):
        path = Path(__file__).parent.parent / "src" / "sophiagraph" / "audit" / filename
        source = path.read_text(encoding="utf-8")
        banned = [
            r"\bopenai\b",
            r"\banthropic\b",
            r"\bClaude\b",
            r"\bllm_complete\b",
            r"\bsummarize\(",
            r"\bclassify\(",
            r"\binfer_\w+\(",
        ]
        for pattern in banned:
            assert re.search(pattern, source) is None, (
                f"banned LLM token {pattern!r} found in {filename}"
            )
