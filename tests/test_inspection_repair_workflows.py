from __future__ import annotations

import pytest

from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.freshness import FreshnessLedgerEntry
from sophiagraph.inspection import (
    RepairCandidate,
    apply_repair_candidate,
    build_inspection_report,
)
from sophiagraph.models import Fact, MemoryNamespace, MemoryRecord, StructuralLink
from sophiagraph.sync import LocalSyncRequest, detect_sync_conflict


def _ns() -> MemoryNamespace:
    return MemoryNamespace(tenant_id="tenant", agent_id="agent", graph_id="main")


def _record(record_id: str, aliases=None, source_id: str | None = None) -> MemoryRecord:
    meta = {}
    if aliases is not None:
        meta["aliases"] = aliases
    if source_id is not None:
        meta["source_id"] = source_id
    return MemoryRecord(
        id=record_id,
        scope="agent:agent",
        type="fact",
        key=record_id,
        title=record_id,
        content={"text": record_id},
        created_at="2026-05-31T00:00:00+00:00",
        updated_at="2026-05-31T00:00:00+00:00",
        namespace=_ns(),
        meta=meta,
    )


def test_inspection_report_detects_structural_findings() -> None:
    records = [
        _record("rec-a", aliases=["same"], source_id="known"),
        _record("rec-b", aliases=["same"], source_id="missing"),
        _record("orphan"),
    ]
    links = [
        StructuralLink(
            link_id="link-broken",
            source_record_id="rec-a",
            raw_target="Missing",
            link_kind="wikilink",
            resolution_status="unresolved",
            namespace=_ns(),
        )
    ]
    fact = Fact(
        fact_id="fact-stale",
        namespace=_ns(),
        subject_entity_id="ent-a",
        predicate="status",
        object_literal="old",
        valid_to="2026-01-01T00:00:00+00:00",
    )
    freshness = FreshnessLedgerEntry.create(
        namespace=_ns(),
        source_kind="connector",
        source_id="known",
        status="fresh",
    )
    conflict = detect_sync_conflict(
        LocalSyncRequest(
            mode="file_primary",
            namespace=_ns(),
            source_id="vault",
            path="A.md",
            previous_file_hash="h1",
            previous_record_hash="r1",
            current_file_hash="h2",
            current_record_hash="r2",
        ),
        observed_at="2026-05-31T00:00:00+00:00",
    ).conflict
    assert conflict is not None

    report = build_inspection_report(
        report_id="report-1",
        namespace=_ns(),
        generated_at="2026-05-31T00:00:00+00:00",
        records=records,
        links=links,
        facts=[fact],
        freshness_entries=[freshness],
        conflicts=[conflict],
    )

    kinds = {finding.kind for finding in report.findings}
    assert kinds >= {
        "unresolved_link",
        "orphan_record",
        "duplicate_alias",
        "stale_fact",
        "broken_source_reference",
        "open_conflict",
    }


def test_repair_candidate_requires_explicit_candidate_id() -> None:
    candidate = RepairCandidate(
        candidate_id="repair-1",
        finding_id="finding-1",
        action="caller_patch",
        namespace=_ns(),
        patch={"target_record_id": "rec-b"},
    )

    with pytest.raises(InvalidArgumentError, match="candidate_id"):
        apply_repair_candidate(
            candidate,
            candidate_id="repair-other",
            applied_at="2026-05-31T00:00:00+00:00",
        )

    applied = apply_repair_candidate(
        candidate,
        candidate_id="repair-1",
        applied_at="2026-05-31T00:00:00+00:00",
    )
    assert applied.status == "applied"
