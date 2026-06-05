from __future__ import annotations

from sophiagraph import (
    ConnectorReplayRequest,
    FreshnessLedgerEntry,
    FreshnessReindexRequest,
    MemoryNamespace,
    MemoryRecord,
    RepairCandidate,
    RepairFollowUpRequest,
    SourceIngestEnvelope,
    SourceRegistryEntry,
    SyncRunRequest,
    execute_operational_run,
    operational_report_to_dict,
    operational_request_from_dict,
    operational_request_to_dict,
)
from sophiagraph.models import Fact, StructuralLink
from sophiagraph.sync import LocalSyncRequest, detect_sync_conflict


def _ns(agent_id: str = "agent") -> MemoryNamespace:
    return MemoryNamespace(tenant_id="tenant", agent_id=agent_id, graph_id="main")


def _record(record_id: str, *, source_id: str | None = None) -> MemoryRecord:
    meta = {"properties": {"kind": "task"}}
    if source_id is not None:
        meta["source_id"] = source_id
    return MemoryRecord(
        id=record_id,
        scope="agent:agent",
        type="fact",
        key=record_id,
        title=record_id,
        content={"text": record_id},
        created_at="2026-06-04T00:00:00+00:00",
        updated_at="2026-06-04T00:00:00+00:00",
        source="validated",
        namespace=_ns(),
        meta=meta,
    )


def test_sync_run_request_round_trip_and_conflict_follow_up() -> None:
    request = SyncRunRequest(
        run_id="sync-1",
        observed_at="2026-06-04T01:00:00+00:00",
        sync_request=LocalSyncRequest(
            mode="file_primary",
            namespace=_ns(),
            source_id="vault:main",
            path="Notes/A.md",
            record_id="rec-a",
            previous_file_hash="h1",
            previous_record_hash="r1",
            current_file_hash="h2",
            current_record_hash="r2",
        ),
    )

    restored = operational_request_from_dict(operational_request_to_dict(request))
    report = execute_operational_run(restored)

    assert restored == request
    assert report.kind == "sync_run"
    assert report.status == "follow_up_required"
    assert report.conflict_ids
    assert report.follow_up_actions[0].action == "resolve_conflict"


def test_connector_replay_uses_freshness_and_returns_ingest_action() -> None:
    source = SourceRegistryEntry(
        source_id="source:fake",
        source_type="test_fake",
        namespace=_ns(),
        display_name="Fake source",
        permission_scope="read_only",
    )
    envelope = SourceIngestEnvelope.create(
        source_id=source.source_id,
        namespace=source.namespace,
        payload_kind="document",
        payload={"id": "doc-1"},
        cursor="cursor-2",
        content_hash="hash-2",
    )
    existing = FreshnessLedgerEntry.create(
        namespace=_ns(),
        source_kind="connector",
        source_id=source.source_id,
        status="fresh",
        cursor="cursor-1",
        content_hash="hash-1",
    )

    report = execute_operational_run(
        ConnectorReplayRequest(
            run_id="connector-1",
            source=source,
            envelope=envelope,
            existing_freshness=existing,
            updated_at="2026-06-04T01:00:00+00:00",
        )
    )

    assert report.status == "accepted"
    assert report.replay_decision is not None
    assert report.replay_decision.decision == "ingest_changed"
    assert [action.action for action in report.follow_up_actions] == ["ingest_source"]


def test_freshness_reindex_carries_stale_sources_and_open_conflicts() -> None:
    conflict = detect_sync_conflict(
        LocalSyncRequest(
            mode="file_primary",
            namespace=_ns(),
            source_id="vault:main",
            path="Notes/A.md",
            previous_file_hash="h1",
            previous_record_hash="r1",
            current_file_hash="h2",
            current_record_hash="r2",
        ),
        observed_at="2026-06-04T01:00:00+00:00",
    ).conflict
    assert conflict is not None
    stale_source = SourceRegistryEntry(
        source_id="source:stale",
        source_type="test_fake",
        namespace=_ns(),
        display_name="Stale source",
        permission_scope="read_only",
    )

    report = execute_operational_run(
        FreshnessReindexRequest(
            run_id="reindex-1",
            namespace=_ns(),
            source_kind="connector",
            source_id="source:stale",
            force_rebuild=True,
            stale_conflicts=[conflict],
            stale_sources=[stale_source],
        )
    )

    assert report.status == "rebuild_required"
    assert report.stale_source_ids == ["source:stale"]
    assert report.conflict_ids == [conflict.conflict_id]
    assert [action.action for action in report.follow_up_actions] == ["reindex_source"]


def test_repair_followup_surfaces_findings_and_pending_candidates() -> None:
    conflict = detect_sync_conflict(
        LocalSyncRequest(
            mode="file_primary",
            namespace=_ns(),
            source_id="vault:main",
            path="Notes/A.md",
            previous_file_hash="h1",
            previous_record_hash="r1",
            current_file_hash="h2",
            current_record_hash="r2",
        ),
        observed_at="2026-06-04T01:00:00+00:00",
    ).conflict
    assert conflict is not None
    request = RepairFollowUpRequest(
        run_id="repair-1",
        namespace=_ns(),
        generated_at="2026-06-04T02:00:00+00:00",
        records=[
            _record("rec-a", source_id="known"),
            _record("rec-b", source_id="missing"),
        ],
        links=[
            StructuralLink(
                link_id="link-broken",
                source_record_id="rec-a",
                raw_target="Missing",
                link_kind="wikilink",
                resolution_status="unresolved",
                namespace=_ns(),
            )
        ],
        facts=[
            Fact(
                fact_id="fact-stale",
                namespace=_ns(),
                subject_entity_id="ent-a",
                predicate="status",
                object_literal="old",
                valid_to="2026-01-01T00:00:00+00:00",
            )
        ],
        freshness_entries=[
            FreshnessLedgerEntry.create(
                namespace=_ns(),
                source_kind="connector",
                source_id="known",
                status="fresh",
            )
        ],
        conflicts=[conflict],
        repair_candidates=[
            RepairCandidate(
                candidate_id="repair-candidate-1",
                finding_id="finding-1",
                action="caller_patch",
                namespace=_ns(),
                patch={"target_record_id": "rec-b"},
            )
        ],
    )

    restored = operational_request_from_dict(operational_request_to_dict(request))
    report = execute_operational_run(restored)
    payload = operational_report_to_dict(report)

    assert restored == request
    assert report.status == "follow_up_required"
    assert report.broken_source_ids == ["missing"]
    assert {action.action for action in report.follow_up_actions} >= {
        "review_finding",
        "repair_broken_source",
        "resolve_conflict",
        "apply_repair_candidate",
    }
    assert payload["kind"] == "repair_followup"
    assert payload["counts"]["finding_count"] >= 1
