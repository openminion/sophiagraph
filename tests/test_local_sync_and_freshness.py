from __future__ import annotations

import pytest

from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.freshness import FreshnessLedgerEntry, decide_replay
from sophiagraph.models import MemoryNamespace
from sophiagraph.storage import SophiaGraphMemoryStore, SophiaGraphSqliteStore
from sophiagraph.sync import (
    LocalSyncRequest,
    SyncResolution,
    detect_sync_conflict,
    resolve_sync_conflict,
)


def _ns(agent_id: str = "agent") -> MemoryNamespace:
    return MemoryNamespace(tenant_id="tenant", agent_id=agent_id, graph_id="main")


@pytest.fixture(params=["memory", "sqlite"])
def store(request, tmp_path):
    if request.param == "memory":
        return SophiaGraphMemoryStore()
    return SophiaGraphSqliteStore(tmp_path / "sync.sqlite3")


def _request(**overrides) -> LocalSyncRequest:
    data = {
        "mode": "file_primary",
        "namespace": _ns(),
        "source_id": "vault:main",
        "path": "Notes/A.md",
        "record_id": "rec-a",
        "previous_file_hash": "h1",
        "previous_record_hash": "r1",
        "current_file_hash": "h1",
        "current_record_hash": "r1",
        "file_modified_at": "2026-05-31T00:00:00+00:00",
        "record_updated_at": "2026-05-31T00:00:00+00:00",
    }
    data.update(overrides)
    return LocalSyncRequest(**data)


@pytest.mark.parametrize(
    ("overrides", "status", "kind"),
    [
        ({}, "unchanged", None),
        ({"current_file_hash": "h2"}, "file_changed", "file_changed"),
        ({"current_record_hash": "r2"}, "record_changed", "record_changed"),
        (
            {"current_file_hash": "h2", "current_record_hash": "r2"},
            "conflict",
            "both_changed",
        ),
        ({"file_exists": False}, "missing_file", "missing_file"),
        ({"record_exists": False}, "missing_record", "missing_record"),
    ],
)
def test_detect_sync_conflict_structural_cases(overrides, status, kind) -> None:
    result = detect_sync_conflict(
        _request(**overrides), observed_at="2026-05-31T01:00:00+00:00"
    )

    assert result.status == status
    if kind is None:
        assert result.conflict is None
    else:
        assert result.conflict is not None
        assert result.conflict.kind == kind
        assert result.conflict.namespace.agent_id == "agent"


def test_sync_conflicts_round_trip_across_stores(store) -> None:
    result = detect_sync_conflict(
        _request(current_file_hash="h2", current_record_hash="r2"),
        observed_at="2026-05-31T01:00:00+00:00",
    )
    assert result.conflict is not None
    store.put_sync_conflict(result.conflict)

    fetched = store.get_sync_conflict(result.conflict.conflict_id)
    listed = store.list_sync_conflicts(namespaces=[MemoryNamespace(agent_id="agent")])
    other = store.list_sync_conflicts(namespaces=[MemoryNamespace(agent_id="other")])

    assert fetched == result.conflict
    assert listed == [result.conflict]
    assert other == []


def test_sync_resolution_requires_explicit_patch() -> None:
    result = detect_sync_conflict(
        _request(current_file_hash="h2", current_record_hash="r2"),
        observed_at="2026-05-31T01:00:00+00:00",
    )
    assert result.conflict is not None

    with pytest.raises(InvalidArgumentError, match="patch"):
        SyncResolution(
            conflict_id=result.conflict.conflict_id,
            action="caller_patch",
            resolved_by="operator",
            resolved_at="2026-05-31T02:00:00+00:00",
        )

    resolved = resolve_sync_conflict(
        result.conflict,
        SyncResolution(
            conflict_id=result.conflict.conflict_id,
            action="caller_patch",
            resolved_by="operator",
            resolved_at="2026-05-31T02:00:00+00:00",
            patch={"content_hash": "merged"},
        ),
    )
    assert resolved.status == "resolved"
    assert resolved.resolution_patch == {"content_hash": "merged"}


def test_freshness_replay_and_storage_are_idempotent(store) -> None:
    entry = FreshnessLedgerEntry.create(
        namespace=_ns(),
        source_kind="connector",
        source_id="connector:fake",
        status="fresh",
        cursor="cur-1",
        content_hash="hash-1",
        updated_at="2026-05-31T00:00:00+00:00",
        record_ids=["rec-a"],
    )
    store.put_freshness_entry(entry)
    store.put_freshness_entry(entry)

    same = decide_replay(entry, incoming_cursor="cur-1", incoming_hash="hash-1")
    changed = decide_replay(entry, incoming_cursor="cur-2", incoming_hash="hash-2")
    listed = store.list_freshness_entries(
        source_kind="connector", source_id="connector:fake"
    )

    assert same.decision == "skip_unchanged"
    assert changed.decision == "ingest_changed"
    assert listed == [entry]


def test_failed_freshness_retries(store) -> None:
    entry = FreshnessLedgerEntry.create(
        namespace=_ns(),
        source_kind="bundle_import",
        source_id="bundle:1",
        status="failed",
        updated_at="2026-05-31T00:00:00+00:00",
        error_code="IMPORT_FAILED",
    )
    store.put_freshness_entry(entry)

    decision = decide_replay(entry, incoming_cursor="cur-2", incoming_hash="hash-2")

    assert decision.decision == "retry_failed"
    assert store.get_freshness_entry(entry.ledger_id) == entry
