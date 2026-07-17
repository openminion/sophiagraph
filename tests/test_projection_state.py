from __future__ import annotations

import sqlite3

import pytest

from sophiagraph.contracts.errors import (
    InvalidArgumentError,
    ProjectionCheckpointError,
    ProjectionFenceError,
    ProjectionLeaseHeldError,
)
from sophiagraph.models import (
    MemoryEmbedding,
    MemoryNamespace,
    ProjectionAttempt,
    ProjectionCheckpoint,
    ProjectionTarget,
)
from sophiagraph.projections import run_projection_batch
from sophiagraph.storage import SophiaGraphMemoryStore, SophiaGraphSqliteStore
from sophiagraph.storage.sqlite.schema import SCHEMA_VERSION

NOW = "2026-07-16T12:00:00+00:00"


@pytest.fixture(params=["memory", "sqlite"])
def store(request, tmp_path):
    if request.param == "memory":
        return SophiaGraphMemoryStore()
    return SophiaGraphSqliteStore(tmp_path / "projection.sqlite3")


def _target(target_id: str = "graph-main") -> ProjectionTarget:
    return ProjectionTarget(
        target_id=target_id,
        kind="graph",
        adapter_name="fake",
        namespace=MemoryNamespace(agent_id="agent", graph_id="main"),
        lease_seconds=10,
    )


def test_projection_contracts_reject_unknown_or_incomplete_values() -> None:
    with pytest.raises(InvalidArgumentError, match="target_id"):
        ProjectionTarget(target_id="", kind="graph", adapter_name="fake")
    with pytest.raises(InvalidArgumentError, match="target kind"):
        ProjectionTarget(target_id="bad", kind="other", adapter_name="fake")  # type: ignore[arg-type]
    with pytest.raises(InvalidArgumentError, match="attempt status"):
        ProjectionAttempt(
            attempt_id="attempt-1",
            target_id="graph-main",
            event_id="event-1",
            cursor=1,
            attempt_number=1,
            status="unknown",  # type: ignore[arg-type]
            started_at=NOW,
        )
    with pytest.raises(InvalidArgumentError, match="diagnostic bound"):
        ProjectionAttempt(
            attempt_id="attempt-1",
            target_id="graph-main",
            event_id="event-1",
            cursor=1,
            attempt_number=1,
            status="failed",
            started_at=NOW,
            error_message="x" * 513,
        )


def test_projection_api_uses_the_stable_advanced_import_root() -> None:
    assert callable(run_projection_batch)


def test_projection_state_enforces_namespace_lease_and_monotonic_checkpoint(
    store,
) -> None:
    target = _target()
    store.register_projection_target(target)
    lease = store.acquire_projection_lease(
        target_id=target.target_id, owner_id="worker-a", now=NOW
    )
    with pytest.raises(ProjectionLeaseHeldError):
        store.acquire_projection_lease(
            target_id=target.target_id,
            owner_id="worker-b",
            now="2026-07-16T12:00:01+00:00",
        )
    store.advance_projection_checkpoint(
        ProjectionCheckpoint(
            target_id=target.target_id,
            cursor=1,
            event_id="event-1",
            updated_at=NOW,
        ),
        fencing_token=lease.fencing_token,
        now=NOW,
    )
    with pytest.raises(ProjectionCheckpointError):
        store.advance_projection_checkpoint(
            ProjectionCheckpoint(target_id=target.target_id, cursor=1),
            fencing_token=lease.fencing_token,
            now=NOW,
        )
    with pytest.raises(ProjectionFenceError):
        store.release_projection_lease(
            target_id=target.target_id,
            owner_id="worker-a",
            fencing_token=lease.fencing_token + 1,
        )
    assert (
        store.list_projection_targets(namespaces=[MemoryNamespace(agent_id="other")])
        == []
    )


def test_projection_lease_renews_and_expired_lease_changes_owner(store) -> None:
    target = _target()
    store.register_projection_target(target)
    first = store.acquire_projection_lease(
        target_id=target.target_id, owner_id="worker-a", now=NOW
    )
    renewed = store.acquire_projection_lease(
        target_id=target.target_id,
        owner_id="worker-a",
        now="2026-07-16T12:00:01+00:00",
    )
    replacement = store.acquire_projection_lease(
        target_id=target.target_id,
        owner_id="worker-b",
        now="2026-07-16T12:00:12+00:00",
    )

    assert renewed.fencing_token == first.fencing_token + 1
    assert replacement.owner_id == "worker-b"
    assert replacement.fencing_token == renewed.fencing_token + 1
    with pytest.raises(ProjectionFenceError):
        store.release_projection_lease(
            target_id=target.target_id,
            owner_id="worker-a",
            fencing_token=renewed.fencing_token,
        )


def test_sqlite_projection_schema_migrates_and_persists(tmp_path) -> None:
    path = tmp_path / "old.sqlite3"
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA user_version = 18")
    store = SophiaGraphSqliteStore(path)
    store.register_projection_target(_target())
    reopened = SophiaGraphSqliteStore(path)
    assert reopened.get_projection_target("graph-main") == _target()
    with sqlite3.connect(path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION


def test_embedding_changes_are_privacy_bounded_and_keep_delete_keys(store) -> None:
    namespace = MemoryNamespace(agent_id="agent", graph_id="main")
    embedding = MemoryEmbedding(
        record_id="record-1",
        vector_space="space",
        dimension=2,
        provider="caller",
        model="model",
        namespace=namespace,
        created_at=NOW,
        updated_at=NOW,
        vector=[0.2, 0.8],
    )
    store.put_embedding(embedding)
    store.delete_embedding("record-1", "space")
    events = [item for item in store.list_changes() if item.object_type == "embedding"]
    assert [item.operation for item in events] == ["put", "delete"]
    assert all("vector" not in item.payload for item in events)
    assert events[1].payload["point_id"] == embedding.key
    assert events[0].idempotency_key != events[1].idempotency_key


def test_embedding_delta_replays_event_without_recreating_private_vector(
    store, tmp_path
) -> None:
    embedding = MemoryEmbedding(
        record_id="record-1",
        vector_space="space",
        dimension=2,
        provider="caller",
        model="model",
        namespace=MemoryNamespace(agent_id="agent", graph_id="main"),
        created_at=NOW,
        updated_at=NOW,
        vector=[0.2, 0.8],
    )
    store.put_embedding(embedding)
    delta = store.export_delta()
    target = (
        SophiaGraphMemoryStore()
        if isinstance(store, SophiaGraphMemoryStore)
        else SophiaGraphSqliteStore(tmp_path / "projection-delta-target.sqlite3")
    )

    result = target.import_delta(delta)

    assert result.imported_changes == 1
    assert target.get_embedding(embedding.record_id, embedding.vector_space) is None
    imported = target.list_changes()
    assert len(imported) == 1
    assert imported[0].object_type == "embedding"
    assert "vector" not in imported[0].payload
