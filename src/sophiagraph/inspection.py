"""Structural inspection and explicit repair workflow primitives."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field, replace
from typing import Any, Literal
from uuid import NAMESPACE_URL, uuid5

from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.freshness import FreshnessLedgerEntry
from sophiagraph.models import Fact, MemoryNamespace, MemoryRecord, StructuralLink
from sophiagraph.sync import SyncConflictRecord

InspectionFindingKind = Literal[
    "unresolved_link",
    "orphan_record",
    "duplicate_alias",
    "stale_fact",
    "broken_source_reference",
    "open_conflict",
]
RepairAction = Literal["update_link_target", "mark_resolved", "caller_patch"]
RepairStatus = Literal["pending", "applied"]


def _stable_id(prefix: str, *parts: str) -> str:
    return f"{prefix}-{uuid5(NAMESPACE_URL, ':'.join(str(part) for part in parts))}"


@dataclass(frozen=True, slots=True)
class InspectionFinding:
    finding_id: str
    kind: InspectionFindingKind
    namespace: MemoryNamespace
    subject_id: str
    message: str
    evidence: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.finding_id:
            raise InvalidArgumentError("finding_id is required")
        if self.kind not in {
            "unresolved_link",
            "orphan_record",
            "duplicate_alias",
            "stale_fact",
            "broken_source_reference",
            "open_conflict",
        }:
            raise InvalidArgumentError(f"invalid finding kind: {self.kind!r}")
        if not isinstance(self.namespace, MemoryNamespace):
            raise TypeError("namespace must be MemoryNamespace")
        if not self.subject_id:
            raise InvalidArgumentError("subject_id is required")
        if not self.message:
            raise InvalidArgumentError("message is required")


@dataclass(frozen=True, slots=True)
class InspectionReport:
    report_id: str
    namespace: MemoryNamespace
    generated_at: str
    findings: list[InspectionFinding] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.report_id:
            raise InvalidArgumentError("report_id is required")
        if not isinstance(self.namespace, MemoryNamespace):
            raise TypeError("namespace must be MemoryNamespace")
        if not self.generated_at:
            raise InvalidArgumentError("generated_at is required")


@dataclass(frozen=True, slots=True)
class RepairCandidate:
    candidate_id: str
    finding_id: str
    action: RepairAction
    namespace: MemoryNamespace
    patch: dict[str, Any]
    status: RepairStatus = "pending"
    applied_at: str | None = None

    def __post_init__(self) -> None:
        if not self.candidate_id:
            raise InvalidArgumentError("candidate_id is required")
        if not self.finding_id:
            raise InvalidArgumentError("finding_id is required")
        if self.action not in {"update_link_target", "mark_resolved", "caller_patch"}:
            raise InvalidArgumentError(f"invalid repair action: {self.action!r}")
        if not isinstance(self.namespace, MemoryNamespace):
            raise TypeError("namespace must be MemoryNamespace")
        if not self.patch:
            raise InvalidArgumentError("repair candidates require explicit patch data")
        if self.status not in {"pending", "applied"}:
            raise InvalidArgumentError(f"invalid repair status: {self.status!r}")


@dataclass(frozen=True, slots=True)
class RepairApplicationResult:
    candidate_id: str
    applied: bool
    affected_ids: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.candidate_id:
            raise InvalidArgumentError("candidate_id is required")


def build_inspection_report(
    *,
    report_id: str,
    namespace: MemoryNamespace,
    generated_at: str,
    records: list[MemoryRecord],
    links: list[StructuralLink] | None = None,
    facts: list[Fact] | None = None,
    freshness_entries: list[FreshnessLedgerEntry] | None = None,
    conflicts: list[SyncConflictRecord] | None = None,
) -> InspectionReport:
    findings: list[InspectionFinding] = []
    record_ids = {record.id for record in records}
    linked_ids = {link.source_record_id for link in links or []}
    linked_ids.update(
        link.target_record_id for link in links or [] if link.target_record_id
    )
    for link in links or []:
        if link.resolution_status == "unresolved" or (
            link.target_record_id and link.target_record_id not in record_ids
        ):
            findings.append(
                _finding(
                    "unresolved_link",
                    namespace,
                    link.link_id,
                    "link target is unresolved or missing",
                    {"raw_target": link.raw_target},
                )
            )
    for record in records:
        if record.id not in linked_ids:
            findings.append(
                _finding(
                    "orphan_record",
                    namespace,
                    record.id,
                    "record has no incident structural links",
                    {"title": record.title},
                )
            )
    aliases: list[str] = []
    for record in records:
        raw_aliases = record.meta.get("aliases")
        if isinstance(raw_aliases, list):
            aliases.extend(str(alias) for alias in raw_aliases)
    for alias, count in Counter(aliases).items():
        if count > 1:
            findings.append(
                _finding(
                    "duplicate_alias",
                    namespace,
                    alias,
                    "alias appears on multiple explicit records",
                    {"count": count},
                )
            )
    for fact in facts or []:
        if fact.invalidated_at or fact.valid_to:
            findings.append(
                _finding(
                    "stale_fact",
                    namespace,
                    fact.fact_id,
                    "fact is invalidated or has closed validity",
                    {"predicate": fact.predicate},
                )
            )
    known_sources = {entry.source_id for entry in freshness_entries or []}
    if known_sources:
        for record in records:
            source_id = record.meta.get("source_id")
            if isinstance(source_id, str) and source_id not in known_sources:
                findings.append(
                    _finding(
                        "broken_source_reference",
                        namespace,
                        record.id,
                        "record source_id is not present in freshness ledger",
                        {"source_id": source_id},
                    )
                )
    for conflict in conflicts or []:
        if conflict.status == "open":
            findings.append(
                _finding(
                    "open_conflict",
                    namespace,
                    conflict.conflict_id,
                    "sync conflict is still open",
                    {"kind": conflict.kind},
                )
            )
    return InspectionReport(
        report_id=report_id,
        namespace=namespace,
        generated_at=generated_at,
        findings=findings,
    )


def _finding(
    kind: InspectionFindingKind,
    namespace: MemoryNamespace,
    subject_id: str,
    message: str,
    evidence: dict[str, Any],
) -> InspectionFinding:
    return InspectionFinding(
        finding_id=_stable_id("finding", kind, subject_id),
        kind=kind,
        namespace=namespace,
        subject_id=subject_id,
        message=message,
        evidence=evidence,
    )


def apply_repair_candidate(
    candidate: RepairCandidate,
    *,
    candidate_id: str,
    applied_at: str,
) -> RepairCandidate:
    if candidate.candidate_id != candidate_id:
        raise InvalidArgumentError("explicit candidate_id is required to apply repair")
    return replace(candidate, status="applied", applied_at=applied_at)


def inspection_report_to_dict(report: InspectionReport) -> dict[str, Any]:
    return asdict(report)


def inspection_report_from_dict(data: dict[str, Any]) -> InspectionReport:
    payload = dict(data)
    if isinstance(payload.get("namespace"), dict):
        payload["namespace"] = MemoryNamespace.from_dict(payload["namespace"])
    payload["findings"] = [
        inspection_finding_from_dict(item) if isinstance(item, dict) else item
        for item in payload.get("findings", [])
    ]
    return InspectionReport(**payload)


def inspection_finding_from_dict(data: dict[str, Any]) -> InspectionFinding:
    payload = dict(data)
    if isinstance(payload.get("namespace"), dict):
        payload["namespace"] = MemoryNamespace.from_dict(payload["namespace"])
    return InspectionFinding(**payload)


def repair_candidate_to_dict(candidate: RepairCandidate) -> dict[str, Any]:
    return asdict(candidate)


def repair_candidate_from_dict(data: dict[str, Any]) -> RepairCandidate:
    payload = dict(data)
    if isinstance(payload.get("namespace"), dict):
        payload["namespace"] = MemoryNamespace.from_dict(payload["namespace"])
    return RepairCandidate(**payload)


__all__ = [
    "InspectionFinding",
    "InspectionFindingKind",
    "InspectionReport",
    "RepairAction",
    "RepairApplicationResult",
    "RepairCandidate",
    "RepairStatus",
    "apply_repair_candidate",
    "build_inspection_report",
    "inspection_finding_from_dict",
    "inspection_report_from_dict",
    "inspection_report_to_dict",
    "repair_candidate_from_dict",
    "repair_candidate_to_dict",
]
