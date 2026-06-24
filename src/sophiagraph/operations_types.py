"""Typed operational request and report contracts over existing package helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from sophiagraph.connectors import (
    SourceIngestEnvelope,
    SourceIngestResult,
    SourceRegistryEntry,
)
from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.freshness import (
    FreshnessLedgerEntry,
    FreshnessSourceKind,
    ReplayDecision,
)
from sophiagraph.inspection import InspectionReport, RepairCandidate
from sophiagraph.models import Fact, MemoryNamespace, MemoryRecord, StructuralLink
from sophiagraph.sync import LocalSyncRequest, LocalSyncResult, SyncConflictRecord

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

RUN_KINDS: frozenset[str] = frozenset(
    {"sync_run", "connector_replay", "freshness_reindex", "repair_followup"}
)
RUN_STATUSES: frozenset[str] = frozenset(
    {"unchanged", "accepted", "skipped", "rebuild_required", "follow_up_required"}
)
FOLLOW_UP_ACTIONS: frozenset[str] = frozenset(
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
        if self.action not in FOLLOW_UP_ACTIONS:
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
        if self.kind not in RUN_KINDS:
            raise InvalidArgumentError(f"invalid run kind: {self.kind!r}")
        if self.status not in RUN_STATUSES:
            raise InvalidArgumentError(f"invalid run status: {self.status!r}")
        if not self.namespaces:
            raise InvalidArgumentError("report requires at least one namespace")


__all__ = [
    "ConnectorReplayRequest",
    "FOLLOW_UP_ACTIONS",
    "FreshnessReindexRequest",
    "OperationalFollowUpAction",
    "OperationalFollowUpActionKind",
    "OperationalRunKind",
    "OperationalRunReport",
    "OperationalRunRequest",
    "OperationalRunStatus",
    "RUN_KINDS",
    "RUN_STATUSES",
    "RepairFollowUpRequest",
    "SyncRunRequest",
]
