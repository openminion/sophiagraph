"""Operational envelopes over sync, freshness, connector, and repair primitives."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from sophiagraph.connectors import (
    SourceIngestEnvelope,
    SourceIngestResult,
    SourceRegistryEntry,
    decide_source_ingest,
    update_source_after_ingest,
)
from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.freshness import (
    FreshnessLedgerEntry,
    FreshnessSourceKind,
    ReplayDecision,
    decide_replay,
)
from sophiagraph.inspection import (
    InspectionReport,
    RepairCandidate,
    build_inspection_report,
)
from sophiagraph.models import Fact, MemoryNamespace, MemoryRecord, StructuralLink
from sophiagraph.sync import (
    LocalSyncRequest,
    LocalSyncResult,
    SyncConflictRecord,
    detect_sync_conflict,
)

OperationalRunKind = Literal[
    "sync_run",
    "connector_replay",
    "freshness_reindex",
    "repair_followup",
]
OperationalRunStatus = Literal[
    "unchanged",
    "accepted",
    "skipped",
    "rebuild_required",
    "follow_up_required",
]
OperationalFollowUpActionKind = Literal[
    "ingest_source",
    "reindex_source",
    "resolve_conflict",
    "repair_broken_source",
    "review_finding",
    "apply_repair_candidate",
]

_RUN_KINDS: frozenset[str] = frozenset(
    {"sync_run", "connector_replay", "freshness_reindex", "repair_followup"}
)
_RUN_STATUSES: frozenset[str] = frozenset(
    {"unchanged", "accepted", "skipped", "rebuild_required", "follow_up_required"}
)
_FOLLOW_UP_ACTIONS: frozenset[str] = frozenset(
    {
        "ingest_source",
        "reindex_source",
        "resolve_conflict",
        "repair_broken_source",
        "review_finding",
        "apply_repair_candidate",
    }
)


@dataclass(frozen=True, slots=True)
class SyncRunRequest:
    run_id: str
    sync_request: LocalSyncRequest
    observed_at: str = ""

    def __post_init__(self) -> None:
        if not self.run_id:
            raise InvalidArgumentError("run_id is required")


@dataclass(frozen=True, slots=True)
class ConnectorReplayRequest:
    run_id: str
    source: SourceRegistryEntry
    envelope: SourceIngestEnvelope
    existing_freshness: FreshnessLedgerEntry | None = None
    updated_at: str = ""

    def __post_init__(self) -> None:
        if not self.run_id:
            raise InvalidArgumentError("run_id is required")


@dataclass(frozen=True, slots=True)
class FreshnessReindexRequest:
    run_id: str
    namespace: MemoryNamespace
    source_kind: FreshnessSourceKind
    source_id: str
    existing_freshness: FreshnessLedgerEntry | None = None
    incoming_cursor: str | None = None
    incoming_hash: str | None = None
    force_rebuild: bool = False
    stale_conflicts: list[SyncConflictRecord] = field(default_factory=list)
    stale_sources: list[SourceRegistryEntry] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.run_id:
            raise InvalidArgumentError("run_id is required")
        if not isinstance(self.namespace, MemoryNamespace):
            raise TypeError("namespace must be MemoryNamespace")
        if not self.source_id:
            raise InvalidArgumentError("source_id is required")


@dataclass(frozen=True, slots=True)
class RepairFollowUpRequest:
    run_id: str
    namespace: MemoryNamespace
    generated_at: str
    records: list[MemoryRecord]
    links: list[StructuralLink] = field(default_factory=list)
    facts: list[Fact] = field(default_factory=list)
    freshness_entries: list[FreshnessLedgerEntry] = field(default_factory=list)
    conflicts: list[SyncConflictRecord] = field(default_factory=list)
    repair_candidates: list[RepairCandidate] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.run_id:
            raise InvalidArgumentError("run_id is required")
        if not isinstance(self.namespace, MemoryNamespace):
            raise TypeError("namespace must be MemoryNamespace")
        if not self.generated_at:
            raise InvalidArgumentError("generated_at is required")


OperationalRunRequest = (
    SyncRunRequest
    | ConnectorReplayRequest
    | FreshnessReindexRequest
    | RepairFollowUpRequest
)


@dataclass(frozen=True, slots=True)
class OperationalFollowUpAction:
    action: OperationalFollowUpActionKind
    namespace: MemoryNamespace
    source_id: str | None = None
    conflict_id: str | None = None
    finding_id: str | None = None
    candidate_id: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.action not in _FOLLOW_UP_ACTIONS:
            raise InvalidArgumentError(f"invalid follow-up action: {self.action!r}")
        if not isinstance(self.namespace, MemoryNamespace):
            raise TypeError("namespace must be MemoryNamespace")


@dataclass(frozen=True, slots=True)
class OperationalRunReport:
    run_id: str
    kind: OperationalRunKind
    status: OperationalRunStatus
    namespaces: list[MemoryNamespace]
    source_ids: list[str] = field(default_factory=list)
    record_ids: list[str] = field(default_factory=list)
    conflict_ids: list[str] = field(default_factory=list)
    stale_source_ids: list[str] = field(default_factory=list)
    broken_source_ids: list[str] = field(default_factory=list)
    follow_up_actions: list[OperationalFollowUpAction] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    replay_decision: ReplayDecision | None = None
    sync_result: LocalSyncResult | None = None
    ingest_result: SourceIngestResult | None = None
    updated_source: SourceRegistryEntry | None = None
    inspection_report: InspectionReport | None = None
    repair_candidates: list[RepairCandidate] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.run_id:
            raise InvalidArgumentError("run_id is required")
        if self.kind not in _RUN_KINDS:
            raise InvalidArgumentError(f"invalid run kind: {self.kind!r}")
        if self.status not in _RUN_STATUSES:
            raise InvalidArgumentError(f"invalid run status: {self.status!r}")
        if not self.namespaces:
            raise InvalidArgumentError("report requires at least one namespace")


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


def operational_request_to_dict(request: OperationalRunRequest) -> dict[str, Any]:
    """Serialize any operational request to a typed plain dict."""
    if isinstance(request, SyncRunRequest):
        return {
            "kind": "sync_run",
            "run_id": request.run_id,
            "observed_at": request.observed_at,
            "sync_request": _local_sync_request_to_dict(request.sync_request),
        }
    if isinstance(request, ConnectorReplayRequest):
        return {
            "kind": "connector_replay",
            "run_id": request.run_id,
            "updated_at": request.updated_at,
            "source": _source_to_dict(request.source),
            "envelope": _source_ingest_to_dict(request.envelope),
            "existing_freshness": _freshness_to_dict(request.existing_freshness),
        }
    if isinstance(request, FreshnessReindexRequest):
        return {
            "kind": "freshness_reindex",
            "run_id": request.run_id,
            "namespace": request.namespace.as_dict(),
            "source_kind": request.source_kind,
            "source_id": request.source_id,
            "incoming_cursor": request.incoming_cursor,
            "incoming_hash": request.incoming_hash,
            "force_rebuild": request.force_rebuild,
            "existing_freshness": _freshness_to_dict(request.existing_freshness),
            "stale_conflicts": [
                _sync_conflict_to_dict(conflict) for conflict in request.stale_conflicts
            ],
            "stale_sources": [
                _source_to_dict(source) for source in request.stale_sources
            ],
        }
    return {
        "kind": "repair_followup",
        "run_id": request.run_id,
        "namespace": request.namespace.as_dict(),
        "generated_at": request.generated_at,
        "records": [_record_to_dict(record) for record in request.records],
        "links": [_link_to_dict(link) for link in request.links],
        "facts": [_fact_to_dict(fact) for fact in request.facts],
        "freshness_entries": [
            _freshness_to_dict(entry) for entry in request.freshness_entries
        ],
        "conflicts": [
            _sync_conflict_to_dict(conflict) for conflict in request.conflicts
        ],
        "repair_candidates": [
            _repair_candidate_to_dict(candidate)
            for candidate in request.repair_candidates
        ],
    }


def operational_request_from_dict(data: dict[str, Any]) -> OperationalRunRequest:
    """Hydrate an operational request from a typed plain dict."""
    kind = data.get("kind")
    if kind == "sync_run":
        return SyncRunRequest(
            run_id=data["run_id"],
            observed_at=data.get("observed_at", ""),
            sync_request=_local_sync_request_from_dict(data["sync_request"]),
        )
    if kind == "connector_replay":
        return ConnectorReplayRequest(
            run_id=data["run_id"],
            updated_at=data.get("updated_at", ""),
            source=_source_from_dict(data["source"]),
            envelope=_source_ingest_from_dict(data["envelope"]),
            existing_freshness=_freshness_from_dict(data.get("existing_freshness")),
        )
    if kind == "freshness_reindex":
        return FreshnessReindexRequest(
            run_id=data["run_id"],
            namespace=MemoryNamespace.from_dict(data["namespace"]),
            source_kind=data["source_kind"],
            source_id=data["source_id"],
            incoming_cursor=data.get("incoming_cursor"),
            incoming_hash=data.get("incoming_hash"),
            force_rebuild=bool(data.get("force_rebuild", False)),
            existing_freshness=_freshness_from_dict(data.get("existing_freshness")),
            stale_conflicts=[
                _sync_conflict_from_dict(conflict)
                for conflict in data.get("stale_conflicts", [])
            ],
            stale_sources=[
                _source_from_dict(source) for source in data.get("stale_sources", [])
            ],
        )
    if kind == "repair_followup":
        return RepairFollowUpRequest(
            run_id=data["run_id"],
            namespace=MemoryNamespace.from_dict(data["namespace"]),
            generated_at=data["generated_at"],
            records=[_record_from_dict(record) for record in data.get("records", [])],
            links=[_link_from_dict(link) for link in data.get("links", [])],
            facts=[_fact_from_dict(fact) for fact in data.get("facts", [])],
            freshness_entries=[
                _freshness_from_dict(entry)
                for entry in data.get("freshness_entries", [])
                if entry is not None
            ],
            conflicts=[
                _sync_conflict_from_dict(conflict)
                for conflict in data.get("conflicts", [])
            ],
            repair_candidates=[
                _repair_candidate_from_dict(candidate)
                for candidate in data.get("repair_candidates", [])
            ],
        )
    raise InvalidArgumentError(f"unknown operational request kind: {kind!r}")


def operational_report_to_dict(report: OperationalRunReport) -> dict[str, Any]:
    """Serialize an operational run report to a plain dict."""
    return {
        "run_id": report.run_id,
        "kind": report.kind,
        "status": report.status,
        "namespaces": [namespace.as_dict() for namespace in report.namespaces],
        "source_ids": list(report.source_ids),
        "record_ids": list(report.record_ids),
        "conflict_ids": list(report.conflict_ids),
        "stale_source_ids": list(report.stale_source_ids),
        "broken_source_ids": list(report.broken_source_ids),
        "follow_up_actions": [
            {
                **asdict(action),
                "namespace": action.namespace.as_dict(),
            }
            for action in report.follow_up_actions
        ],
        "counts": dict(report.counts),
        "replay_decision": asdict(report.replay_decision)
        if report.replay_decision is not None
        else None,
        "sync_result": asdict(report.sync_result)
        if report.sync_result is not None
        else None,
        "ingest_result": asdict(report.ingest_result)
        if report.ingest_result is not None
        else None,
        "updated_source": _source_to_dict(report.updated_source),
        "inspection_report": _inspection_report_to_dict(report.inspection_report),
        "repair_candidates": [
            _repair_candidate_to_dict(candidate)
            for candidate in report.repair_candidates
        ],
    }


def _run_sync(request: SyncRunRequest) -> OperationalRunReport:
    result = detect_sync_conflict(request.sync_request, observed_at=request.observed_at)
    conflict_ids = [result.conflict.conflict_id] if result.conflict is not None else []
    actions = []
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
    status: OperationalRunStatus
    if decision.decision == "skip_unchanged":
        status = "skipped"
    elif decision.decision == "rebuild_required":
        status = "rebuild_required"
    else:
        status = "accepted"
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
        repair_candidates=pending_candidates,
    )


def _local_sync_request_to_dict(request: LocalSyncRequest) -> dict[str, Any]:
    return {**asdict(request), "namespace": request.namespace.as_dict()}


def _local_sync_request_from_dict(data: dict[str, Any]) -> LocalSyncRequest:
    payload = dict(data)
    if isinstance(payload.get("namespace"), dict):
        payload["namespace"] = MemoryNamespace.from_dict(payload["namespace"])
    return LocalSyncRequest(**payload)


def _source_to_dict(source: SourceRegistryEntry | None) -> dict[str, Any] | None:
    if source is None:
        return None
    return {**asdict(source), "namespace": source.namespace.as_dict()}


def _source_from_dict(data: dict[str, Any]) -> SourceRegistryEntry:
    payload = dict(data)
    if isinstance(payload.get("namespace"), dict):
        payload["namespace"] = MemoryNamespace.from_dict(payload["namespace"])
    return SourceRegistryEntry(**payload)


def _source_ingest_to_dict(
    envelope: SourceIngestEnvelope | None,
) -> dict[str, Any] | None:
    if envelope is None:
        return None
    return {**asdict(envelope), "namespace": envelope.namespace.as_dict()}


def _source_ingest_from_dict(data: dict[str, Any]) -> SourceIngestEnvelope:
    payload = dict(data)
    if isinstance(payload.get("namespace"), dict):
        payload["namespace"] = MemoryNamespace.from_dict(payload["namespace"])
    return SourceIngestEnvelope(**payload)


def _freshness_to_dict(
    entry: FreshnessLedgerEntry | None,
) -> dict[str, Any] | None:
    if entry is None:
        return None
    return {**asdict(entry), "namespace": entry.namespace.as_dict()}


def _freshness_from_dict(
    data: dict[str, Any] | None,
) -> FreshnessLedgerEntry | None:
    if data is None:
        return None
    payload = dict(data)
    if isinstance(payload.get("namespace"), dict):
        payload["namespace"] = MemoryNamespace.from_dict(payload["namespace"])
    return FreshnessLedgerEntry(**payload)


def _sync_conflict_to_dict(conflict: SyncConflictRecord) -> dict[str, Any]:
    return {**asdict(conflict), "namespace": conflict.namespace.as_dict()}


def _sync_conflict_from_dict(data: dict[str, Any]) -> SyncConflictRecord:
    payload = dict(data)
    if isinstance(payload.get("namespace"), dict):
        payload["namespace"] = MemoryNamespace.from_dict(payload["namespace"])
    return SyncConflictRecord(**payload)


def _record_to_dict(record: MemoryRecord) -> dict[str, Any]:
    return {
        **asdict(record),
        "namespace": record.namespace.as_dict()
        if record.namespace is not None
        else None,
    }


def _record_from_dict(data: dict[str, Any]) -> MemoryRecord:
    payload = dict(data)
    if isinstance(payload.get("namespace"), dict):
        payload["namespace"] = MemoryNamespace.from_dict(payload["namespace"])
    return MemoryRecord(**payload)


def _link_to_dict(link: StructuralLink) -> dict[str, Any]:
    return {**asdict(link), "namespace": link.namespace.as_dict()}


def _link_from_dict(data: dict[str, Any]) -> StructuralLink:
    payload = dict(data)
    if isinstance(payload.get("namespace"), dict):
        payload["namespace"] = MemoryNamespace.from_dict(payload["namespace"])
    return StructuralLink(**payload)


def _fact_to_dict(fact: Fact) -> dict[str, Any]:
    return {
        **asdict(fact),
        "namespace": fact.namespace.as_dict(),
    }


def _fact_from_dict(data: dict[str, Any]) -> Fact:
    payload = dict(data)
    if isinstance(payload.get("namespace"), dict):
        payload["namespace"] = MemoryNamespace.from_dict(payload["namespace"])
    return Fact(**payload)


def _repair_candidate_to_dict(candidate: RepairCandidate) -> dict[str, Any]:
    return {**asdict(candidate), "namespace": candidate.namespace.as_dict()}


def _repair_candidate_from_dict(data: dict[str, Any]) -> RepairCandidate:
    payload = dict(data)
    if isinstance(payload.get("namespace"), dict):
        payload["namespace"] = MemoryNamespace.from_dict(payload["namespace"])
    return RepairCandidate(**payload)


def _inspection_report_to_dict(
    report: InspectionReport | None,
) -> dict[str, Any] | None:
    if report is None:
        return None
    return {
        **asdict(report),
        "namespace": report.namespace.as_dict(),
        "findings": [
            {**asdict(finding), "namespace": finding.namespace.as_dict()}
            for finding in report.findings
        ],
    }


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
