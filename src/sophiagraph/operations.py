"""Operational envelopes over sync, freshness, connector, and repair primitives."""

from __future__ import annotations

from typing import cast

from sophiagraph.connectors import (
    decide_source_ingest,
    update_source_after_ingest,
)
from sophiagraph.freshness import (
    decide_replay,
)
from sophiagraph.inspection import (
    RepairCandidate,
    build_inspection_report,
)
from sophiagraph.sync import detect_sync_conflict

from .operations_codec import (
    operational_report_to_dict,
    operational_request_from_dict,
    operational_request_to_dict,
)
from .operations_types import (
    ConnectorReplayRequest,
    FreshnessReindexRequest,
    OperationalFollowUpAction,
    OperationalFollowUpActionKind,
    OperationalRunKind,
    OperationalRunReport,
    OperationalRunRequest,
    OperationalRunStatus,
    RepairFollowUpRequest,
    SyncRunRequest,
)


def execute_operational_run(request: OperationalRunRequest) -> OperationalRunReport:
    """Execute one deterministic operational run over existing public helpers."""
    if isinstance(request, SyncRunRequest):
        return _run_sync(request)
    if isinstance(request, ConnectorReplayRequest):
        return _run_connector_replay(request)
    if isinstance(request, FreshnessReindexRequest):
        return _run_freshness_reindex(request)
    if isinstance(request, RepairFollowUpRequest):
        return _run_repair_followup(request)
    raise TypeError(f"unsupported operational request: {type(request)!r}")


def _run_sync(request: SyncRunRequest) -> OperationalRunReport:
    result = detect_sync_conflict(request.sync_request, observed_at=request.observed_at)
    conflict_ids = [result.conflict.conflict_id] if result.conflict is not None else []
    actions: list[OperationalFollowUpAction] = []
    if result.conflict is not None:
        actions.append(
            OperationalFollowUpAction(
                action="resolve_conflict",
                namespace=request.sync_request.namespace,
                source_id=request.sync_request.source_id,
                conflict_id=result.conflict.conflict_id,
                details={
                    "sync_status": result.status,
                    "path": request.sync_request.path,
                },
            )
        )
    status: OperationalRunStatus = (
        "unchanged" if result.status == "unchanged" else "follow_up_required"
    )
    return OperationalRunReport(
        run_id=request.run_id,
        kind="sync_run",
        status=status,
        namespaces=[request.sync_request.namespace],
        source_ids=[request.sync_request.source_id],
        record_ids=[request.sync_request.record_id]
        if request.sync_request.record_id
        else [],
        conflict_ids=conflict_ids,
        follow_up_actions=actions,
        counts={
            "source_count": 1,
            "record_count": 1 if request.sync_request.record_id else 0,
            "conflict_count": len(conflict_ids),
        },
        sync_result=result,
    )


def _run_connector_replay(request: ConnectorReplayRequest) -> OperationalRunReport:
    ingest_result = decide_source_ingest(
        request.source,
        request.envelope,
        request.existing_freshness,
    )
    updated_source = (
        update_source_after_ingest(
            request.source, request.envelope, updated_at=request.updated_at
        )
        if ingest_result.accepted
        else request.source
    )
    actions = []
    if ingest_result.accepted:
        actions.append(
            OperationalFollowUpAction(
                action="ingest_source",
                namespace=request.source.namespace,
                source_id=request.source.source_id,
                details={
                    "payload_kind": request.envelope.payload_kind,
                    "ingest_id": request.envelope.ingest_id,
                },
            )
        )
    return OperationalRunReport(
        run_id=request.run_id,
        kind="connector_replay",
        status="accepted" if ingest_result.accepted else "skipped",
        namespaces=[request.source.namespace],
        source_ids=[request.source.source_id],
        follow_up_actions=actions,
        counts={
            "source_count": 1,
            "accepted_count": 1 if ingest_result.accepted else 0,
            "skipped_count": 0 if ingest_result.accepted else 1,
        },
        replay_decision=ingest_result.replay_decision,
        ingest_result=ingest_result,
        updated_source=updated_source,
    )


def _run_freshness_reindex(request: FreshnessReindexRequest) -> OperationalRunReport:
    decision = decide_replay(
        request.existing_freshness,
        incoming_cursor=request.incoming_cursor,
        incoming_hash=request.incoming_hash,
        force_rebuild=request.force_rebuild,
    )
    actions = []
    if decision.decision in {"ingest_changed", "retry_failed", "rebuild_required"}:
        actions.append(
            OperationalFollowUpAction(
                action="reindex_source",
                namespace=request.namespace,
                source_id=request.source_id,
                details={
                    "decision": decision.decision,
                    "source_kind": request.source_kind,
                },
            )
        )
    open_conflicts = [
        conflict for conflict in request.stale_conflicts if conflict.is_open
    ]
    status_map: dict[str, OperationalRunStatus] = {
        "skip_unchanged": "skipped",
        "rebuild_required": "rebuild_required",
    }
    status = status_map.get(decision.decision, "accepted")
    return OperationalRunReport(
        run_id=request.run_id,
        kind="freshness_reindex",
        status=status,
        namespaces=[request.namespace],
        source_ids=[request.source_id],
        conflict_ids=[conflict.conflict_id for conflict in open_conflicts],
        stale_source_ids=[source.source_id for source in request.stale_sources],
        follow_up_actions=actions,
        counts={
            "source_count": 1,
            "stale_source_count": len(request.stale_sources),
            "open_conflict_count": len(open_conflicts),
        },
        replay_decision=decision,
    )


def _run_repair_followup(request: RepairFollowUpRequest) -> OperationalRunReport:
    report = build_inspection_report(
        report_id=f"{request.run_id}:inspection",
        namespace=request.namespace,
        generated_at=request.generated_at,
        records=request.records,
        links=request.links,
        facts=request.facts,
        freshness_entries=request.freshness_entries,
        conflicts=request.conflicts,
    )
    actions: list[OperationalFollowUpAction] = []
    broken_source_ids: list[str] = []
    conflict_ids: list[str] = []
    for finding in report.findings:
        if finding.kind == "broken_source_reference":
            source_id = finding.evidence.get("source_id")
            if isinstance(source_id, str):
                broken_source_ids.append(source_id)
            actions.append(
                OperationalFollowUpAction(
                    action="repair_broken_source",
                    namespace=request.namespace,
                    source_id=source_id if isinstance(source_id, str) else None,
                    finding_id=finding.finding_id,
                    details={"kind": finding.kind, "subject_id": finding.subject_id},
                )
            )
            continue
        if finding.kind == "open_conflict":
            conflict_ids.append(finding.subject_id)
            actions.append(
                OperationalFollowUpAction(
                    action="resolve_conflict",
                    namespace=request.namespace,
                    conflict_id=finding.subject_id,
                    finding_id=finding.finding_id,
                    details={"kind": finding.kind},
                )
            )
            continue
        actions.append(
            OperationalFollowUpAction(
                action="review_finding",
                namespace=request.namespace,
                finding_id=finding.finding_id,
                details={"kind": finding.kind, "subject_id": finding.subject_id},
            )
        )
    pending_candidates = [
        candidate
        for candidate in request.repair_candidates
        if candidate.status == "pending"
    ]
    for candidate in pending_candidates:
        actions.append(
            OperationalFollowUpAction(
                action="apply_repair_candidate",
                namespace=candidate.namespace,
                candidate_id=candidate.candidate_id,
                finding_id=candidate.finding_id,
                details={"action": candidate.action},
            )
        )
    status: OperationalRunStatus = "follow_up_required" if actions else "unchanged"
    return OperationalRunReport(
        run_id=request.run_id,
        kind="repair_followup",
        status=status,
        namespaces=[request.namespace],
        source_ids=sorted(set(broken_source_ids)),
        record_ids=sorted(record.id for record in request.records),
        conflict_ids=sorted(set(conflict_ids)),
        broken_source_ids=sorted(set(broken_source_ids)),
        follow_up_actions=actions,
        counts={
            "finding_count": len(report.findings),
            "repair_candidate_count": len(pending_candidates),
            "broken_source_count": len(set(broken_source_ids)),
        },
        inspection_report=report,
        repair_candidates=cast(list[RepairCandidate], pending_candidates),
    )


__all__ = [
    "ConnectorReplayRequest",
    "FreshnessReindexRequest",
    "OperationalFollowUpAction",
    "OperationalFollowUpActionKind",
    "OperationalRunKind",
    "OperationalRunReport",
    "OperationalRunRequest",
    "OperationalRunStatus",
    "RepairFollowUpRequest",
    "SyncRunRequest",
    "execute_operational_run",
    "operational_report_to_dict",
    "operational_request_from_dict",
    "operational_request_to_dict",
]
