"""Deterministic privacy, consent, redaction, retrieval, and export helpers."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Iterable, Protocol

from sophiagraph.audit.policy import (
    PolicyDecision,
    PolicyHookCallable,
    PolicyRequest,
    build_policy_denial_event,
    evaluate_policy_hooks,
)
from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.models import (
    MemoryRecord,
    PrivacyPolicyState,
    RedactionPlan,
    RedactionResult,
    RetentionOutcome,
)
from sophiagraph.portability.models import MemoryBundleSnapshot
from sophiagraph.privacy_types import (
    PRIVACY_META_KEY,
    PrivacyExportResult,
    PrivacyOmittedRecord,
    PrivacyRetrievalResult,
)


class _RetentionPolicyStore(Protocol):
    def put_record(self, record: MemoryRecord) -> str: ...

    def tombstone_record(
        self,
        record_id: str,
        *,
        deleted_at: str,
        reason: str,
    ) -> MemoryRecord: ...

    def cascade_tombstones(
        self,
        record_id: str,
        *,
        deleted_at: str,
        reason: str,
    ): ...


def privacy_policy_from_record(record: MemoryRecord) -> PrivacyPolicyState | None:
    """Decode the typed privacy state carried in ``record.meta`` when present."""

    raw = record.meta.get(PRIVACY_META_KEY)
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise InvalidArgumentError(
            f"record.meta[{PRIVACY_META_KEY!r}] must be a dict when present"
        )
    return PrivacyPolicyState.from_dict(raw)


def record_with_privacy_policy(
    record: MemoryRecord,
    policy: PrivacyPolicyState | None,
) -> MemoryRecord:
    """Return a record copy with typed privacy metadata applied or cleared."""

    meta = dict(record.meta)
    if policy is None:
        meta.pop(PRIVACY_META_KEY, None)
    else:
        meta[PRIVACY_META_KEY] = policy.to_dict()
    return replace(record, meta=meta)


def apply_redaction_plan(
    record: MemoryRecord,
    plan: RedactionPlan,
) -> tuple[MemoryRecord, RedactionResult]:
    """Apply one structural redaction plan to a record."""

    if not isinstance(record, MemoryRecord):
        raise InvalidArgumentError("record must be a MemoryRecord")
    if not isinstance(plan, RedactionPlan):
        raise InvalidArgumentError("plan must be a RedactionPlan")

    content = record.content
    meta = dict(record.meta)
    redacted_targets: list[str] = []
    skipped_targets: list[str] = []
    meta_keys_redacted: list[str] = []
    export_fields_redacted: list[str] = []
    block_ids_redacted: list[str] = []
    content_redacted = False

    for target in plan.targets:
        if target.kind == "record_content":
            redacted_targets.append("content")
            content_redacted = True
            if isinstance(content, str):
                content = plan.replace_with
            elif isinstance(content, dict):
                content = {
                    **content,
                    "_redacted": True,
                    "_redaction_reason": plan.reason,
                }
            else:
                skipped_targets.append(target.target_ref)
        elif target.kind == "metadata_key":
            if target.key in meta:
                meta[target.key] = plan.replace_with
                redacted_targets.append(f"meta:{target.key}")
                meta_keys_redacted.append(str(target.key))
            else:
                skipped_targets.append(target.target_ref)
        elif target.kind == "export_field":
            redacted_targets.append(f"export:{target.key}")
            export_fields_redacted.append(str(target.key))
        elif target.kind == "block_id":
            redacted_targets.append(f"block:{target.block_id}")
            block_ids_redacted.append(str(target.block_id))
        elif target.kind == "artifact_text":
            redacted_targets.append(f"artifact:{target.artifact_ref}")
        else:
            skipped_targets.append(target.target_ref)

    updated = replace(record, content=content, meta=meta)
    return updated, RedactionResult(
        record_id=record.id,
        plan_id=plan.plan_id,
        reason=plan.reason,
        redacted_targets=tuple(redacted_targets),
        skipped_targets=tuple(skipped_targets),
        content_redacted=content_redacted,
        meta_keys_redacted=tuple(meta_keys_redacted),
        export_fields_redacted=tuple(export_fields_redacted),
        block_ids_redacted=tuple(block_ids_redacted),
    )


def _evaluate_privacy_hooks(
    record: MemoryRecord,
    *,
    source_owner: str,
    surface: str,
    hooks: Iterable[PolicyHookCallable],
) -> PolicyDecision | None:
    hooks = tuple(hooks)
    if not hooks:
        return None
    request = PolicyRequest(
        namespace=record.effective_namespace,
        surface=surface,  # type: ignore[arg-type]
        source_owner=source_owner,
        target_kind="record",
        target_id=record.id,
        payload_kind=str(record.type),
        payload_meta={
            "privacy_policy": record.meta.get(PRIVACY_META_KEY),
            "record_meta": dict(record.meta),
        },
    )
    return evaluate_policy_hooks(request, hooks)


def _retention_outcome_for_policy(
    record: MemoryRecord,
    policy: PrivacyPolicyState | None,
) -> RetentionOutcome:
    if policy is None:
        return RetentionOutcome(
            record_id=record.id,
            kind="retain",
            retention_class="default",
            erase_intent="none",
        )
    if policy.erase_intent != "none" or policy.retention_class == "erase_requested":
        return RetentionOutcome(
            record_id=record.id,
            kind="erase",
            retention_class=policy.retention_class,
            erase_intent=policy.erase_intent,
            redaction_plan=policy.redaction_plan,
        )
    if policy.retention_class == "tombstone":
        return RetentionOutcome(
            record_id=record.id,
            kind="tombstone",
            retention_class=policy.retention_class,
            erase_intent=policy.erase_intent,
            redaction_plan=policy.redaction_plan,
        )
    if policy.retention_class == "redact_and_retain":
        return RetentionOutcome(
            record_id=record.id,
            kind="redact_and_retain",
            retention_class=policy.retention_class,
            erase_intent=policy.erase_intent,
            redaction_plan=policy.redaction_plan,
        )
    if policy.retention_class == "retain_hidden":
        return RetentionOutcome(
            record_id=record.id,
            kind="hide",
            retention_class=policy.retention_class,
            erase_intent=policy.erase_intent,
            redaction_plan=policy.redaction_plan,
        )
    return RetentionOutcome(
        record_id=record.id,
        kind="retain",
        retention_class=policy.retention_class,
        erase_intent=policy.erase_intent,
        redaction_plan=policy.redaction_plan,
    )


def retention_outcome_for_record(record: MemoryRecord) -> RetentionOutcome:
    """Return the typed retention outcome implied by a record's privacy policy."""

    return _retention_outcome_for_policy(record, privacy_policy_from_record(record))


def filter_records_for_retrieval(
    records: list[MemoryRecord],
    *,
    source_owner: str,
    hooks: Iterable[PolicyHookCallable] = (),
) -> PrivacyRetrievalResult:
    """Apply deterministic retrieval visibility and hook-based denies."""

    kept: list[MemoryRecord] = []
    omitted: list[PrivacyOmittedRecord] = []
    denial_events: list[Any] = []
    redactions: list[RedactionResult] = []
    for record in records:
        policy = privacy_policy_from_record(record)
        if policy is not None:
            if policy.retrieval_visibility == "hidden":
                omitted.append(
                    PrivacyOmittedRecord(
                        record_id=record.id,
                        reason="hidden_by_visibility",
                        detail={"decision_reason": policy.decision_reason},
                    )
                )
                continue
            if policy.retrieval_visibility == "audit_only":
                omitted.append(
                    PrivacyOmittedRecord(
                        record_id=record.id,
                        reason="audit_only",
                        detail={"decision_reason": policy.decision_reason},
                    )
                )
                continue
        decision = _evaluate_privacy_hooks(
            record,
            source_owner=source_owner,
            surface="retrieval",
            hooks=hooks,
        )
        if decision is not None and decision.denied:
            denial_events.append(
                build_policy_denial_event(
                    PolicyRequest(
                        namespace=record.effective_namespace,
                        surface="retrieval",
                        source_owner=source_owner,
                        target_kind="record",
                        target_id=record.id,
                        payload_kind=str(record.type),
                        payload_meta={
                            "privacy_policy": record.meta.get(PRIVACY_META_KEY),
                            "record_meta": dict(record.meta),
                        },
                    ),
                    decision,
                )
            )
            omitted.append(
                PrivacyOmittedRecord(
                    record_id=record.id,
                    reason="denied_by_policy_hook",
                    detail={
                        "policy_id": decision.policy_id,
                        "reason_code": decision.reason_code,
                        "details": dict(decision.details),
                    },
                )
            )
            continue
        redacted = record
        if policy is not None and policy.retrieval_visibility == "redacted":
            if policy.redaction_plan is None:
                raise InvalidArgumentError(
                    "retrieval_visibility='redacted' requires redaction_plan"
                )
            redacted, result = apply_redaction_plan(record, policy.redaction_plan)
            redactions.append(result)
        kept.append(redacted)
    return PrivacyRetrievalResult(
        records=kept,
        omitted=omitted,
        denial_events=denial_events,
        redactions=redactions,
    )


def filter_snapshot_for_export(
    snapshot: MemoryBundleSnapshot,
    *,
    source_owner: str,
    hooks: Iterable[PolicyHookCallable] = (),
) -> PrivacyExportResult:
    """Apply export-time visibility and structural redaction to a bundle snapshot."""

    kept_records: list[MemoryRecord] = []
    omitted: list[PrivacyOmittedRecord] = []
    denial_events: list[Any] = []
    redactions: list[RedactionResult] = []
    for record in snapshot.records:
        policy = privacy_policy_from_record(record)
        if policy is not None:
            if policy.export_visibility == "hidden":
                omitted.append(
                    PrivacyOmittedRecord(
                        record_id=record.id,
                        reason="hidden_by_visibility",
                        detail={"decision_reason": policy.decision_reason},
                    )
                )
                continue
            if policy.export_visibility == "audit_only":
                omitted.append(
                    PrivacyOmittedRecord(
                        record_id=record.id,
                        reason="audit_only",
                        detail={"decision_reason": policy.decision_reason},
                    )
                )
                continue
        decision = _evaluate_privacy_hooks(
            record,
            source_owner=source_owner,
            surface="export",
            hooks=hooks,
        )
        if decision is not None and decision.denied:
            denial_events.append(
                build_policy_denial_event(
                    PolicyRequest(
                        namespace=record.effective_namespace,
                        surface="export",
                        source_owner=source_owner,
                        target_kind="record",
                        target_id=record.id,
                        payload_kind=str(record.type),
                        payload_meta={
                            "privacy_policy": record.meta.get(PRIVACY_META_KEY),
                            "record_meta": dict(record.meta),
                        },
                    ),
                    decision,
                )
            )
            omitted.append(
                PrivacyOmittedRecord(
                    record_id=record.id,
                    reason="denied_by_policy_hook",
                    detail={
                        "policy_id": decision.policy_id,
                        "reason_code": decision.reason_code,
                        "details": dict(decision.details),
                    },
                )
            )
            continue
        export_record = record
        if policy is not None and policy.export_visibility == "redacted":
            if policy.redaction_plan is None:
                raise InvalidArgumentError(
                    "export_visibility='redacted' requires redaction_plan"
                )
            export_record, result = apply_redaction_plan(record, policy.redaction_plan)
            redactions.append(result)
        kept_records.append(export_record)

    kept_ids = {record.id for record in kept_records}
    filtered_snapshot = replace(
        snapshot,
        records=kept_records,
        relations=[
            relation
            for relation in snapshot.relations
            if relation.source_record_id in kept_ids
            and relation.target_record_id in kept_ids
        ],
    )
    return PrivacyExportResult(
        snapshot=filtered_snapshot,
        omitted=omitted,
        denial_events=denial_events,
        redactions=redactions,
    )


def apply_retention_policy(
    store: _RetentionPolicyStore,
    record: MemoryRecord,
    *,
    deleted_at: str,
    reason: str,
) -> RetentionOutcome:
    """Apply the typed retention outcome through existing store owners."""

    outcome = retention_outcome_for_record(record)
    if outcome.kind == "retain":
        return outcome
    if outcome.kind == "hide":
        policy = privacy_policy_from_record(record)
        assert policy is not None
        hidden_policy = replace(
            policy,
            retrieval_visibility="hidden",
            export_visibility="hidden",
        )
        store.put_record(record_with_privacy_policy(record, hidden_policy))
        return outcome
    if outcome.kind == "redact_and_retain":
        if outcome.redaction_plan is None:
            raise InvalidArgumentError(
                "redact_and_retain outcome requires a redaction plan"
            )
        redacted_record, _ = apply_redaction_plan(record, outcome.redaction_plan)
        store.put_record(redacted_record)
        return outcome
    if outcome.kind == "tombstone":
        store.tombstone_record(record.id, deleted_at=deleted_at, reason=reason)
        return outcome
    store.cascade_tombstones(record.id, deleted_at=deleted_at, reason=reason)
    return outcome


def privacy_policy_to_meta_dict(policy: PrivacyPolicyState) -> dict[str, Any]:
    """Return a standalone serialized metadata payload for callers."""

    return {PRIVACY_META_KEY: policy.to_dict()}


__all__ = [
    "apply_redaction_plan",
    "apply_retention_policy",
    "filter_records_for_retrieval",
    "filter_snapshot_for_export",
    "privacy_policy_from_record",
    "privacy_policy_to_meta_dict",
    "record_with_privacy_policy",
    "retention_outcome_for_record",
]
