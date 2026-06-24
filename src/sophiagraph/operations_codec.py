"""Typed dict codecs for operational request and report payloads."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from sophiagraph.connectors import SourceIngestEnvelope, SourceRegistryEntry
from sophiagraph.freshness import FreshnessLedgerEntry
from sophiagraph.inspection import InspectionReport, RepairCandidate
from sophiagraph.models import Fact, MemoryNamespace, MemoryRecord, StructuralLink
from sophiagraph.sync import LocalSyncRequest, SyncConflictRecord

from .operations_types import (
    ConnectorReplayRequest,
    FreshnessReindexRequest,
    OperationalRunReport,
    OperationalRunRequest,
    RepairFollowUpRequest,
    SyncRunRequest,
)


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
            _sync_conflict_from_dict(conflict) for conflict in data.get("conflicts", [])
        ],
        repair_candidates=[
            _repair_candidate_from_dict(candidate)
            for candidate in data.get("repair_candidates", [])
        ],
    )


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
