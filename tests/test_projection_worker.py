from __future__ import annotations

from dataclasses import replace

import pytest

from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.graph_backends import FakeGraphBackendAdapter
from sophiagraph.models import (
    MemoryEmbedding,
    MemoryNamespace,
    MemoryRecord,
    MemoryRelation,
    ProjectionHealth,
    ProjectionTarget,
)
from sophiagraph.projection import (
    GraphChangeProjector,
    VectorChangeProjector,
    get_projection_health,
    record_projection_health,
    run_projection_batch,
)
from sophiagraph.storage import SophiaGraphMemoryStore, SophiaGraphSqliteStore
from sophiagraph.telemetry import TelemetryEvent
from sophiagraph.vector_backends import FakeVectorBackend

NOW = "2026-07-16T12:00:00+00:00"


def _record(record_id: str, namespace: MemoryNamespace) -> MemoryRecord:
    return MemoryRecord(
        id=record_id,
        scope="agent:agent",
        type="fact",
        key=f"fact:{record_id}",
        title=record_id,
        content={"text": record_id},
        created_at=NOW,
        updated_at=NOW,
        namespace=namespace,
    )


def test_graph_projection_runs_in_cursor_order_and_reports_health() -> None:
    store = SophiaGraphMemoryStore()
    namespace = MemoryNamespace(agent_id="agent", graph_id="main")
    store.put_record(_record("a", namespace))
    store.put_record(_record("b", namespace))
    store.put_relation(MemoryRelation("edge", "a", "b", "supports", NOW))
    store.register_projection_target(
        ProjectionTarget("graph", "graph", "fake", namespace=namespace)
    )
    backend = FakeGraphBackendAdapter()
    result = run_projection_batch(
        store,
        target_id="graph",
        projector=GraphChangeProjector(backend),
        owner_id="worker",
        now=NOW,
    )
    assert result.applied == 3
    assert result.checkpoint_cursor == result.source_head_cursor
    assert backend.get_projection_watermark() == result.checkpoint_cursor
    assert get_projection_health(store, target_id="graph", now=NOW).lag == 0


def test_vector_projection_reads_vector_from_canonical_store() -> None:
    store = SophiaGraphMemoryStore()
    namespace = MemoryNamespace(agent_id="agent", graph_id="main")
    embedding = MemoryEmbedding(
        "record", "space", 2, "caller", "model", namespace, NOW, NOW, [1.0, 0.0]
    )
    store.put_embedding(embedding)
    store.register_projection_target(
        ProjectionTarget("vector", "vector", "fake", namespace=namespace)
    )
    backend = FakeVectorBackend()
    result = run_projection_batch(
        store,
        target_id="vector",
        projector=VectorChangeProjector(store, backend),
        owner_id="worker",
        now=NOW,
    )
    event = next(
        item for item in store.list_changes() if item.object_type == "embedding"
    )
    assert "vector" not in event.payload
    assert result.applied == 1
    assert backend.inventory()[0].object_id == embedding.key
    store.delete_embedding("record", "space")
    deleted = run_projection_batch(
        store,
        target_id="vector",
        projector=VectorChangeProjector(store, backend),
        owner_id="worker",
        now="2026-07-16T12:00:03+00:00",
    )
    assert deleted.applied == 1
    assert backend.inventory() == ()


class _FailingProjector:
    def apply(self, event):
        raise RuntimeError("secret payload must stay bounded")

    def set_watermark(self, cursor):
        return None

    def get_watermark(self):
        return None


def test_projection_failure_retries_then_dead_letters_and_can_be_released() -> None:
    store = SophiaGraphMemoryStore()
    namespace = MemoryNamespace(agent_id="agent", graph_id="main")
    store.put_record(_record("a", namespace))
    store.register_projection_target(
        ProjectionTarget("graph", "graph", "fake", namespace=namespace, max_attempts=2)
    )
    first = run_projection_batch(
        store,
        target_id="graph",
        projector=_FailingProjector(),
        owner_id="worker",
        now=NOW,
    )
    failure = store.list_projection_failures(target_id="graph")[0]
    store.release_projection_failure(
        target_id="graph", event_id=failure.event_id, now="2026-07-16T12:00:02+00:00"
    )
    second = run_projection_batch(
        store,
        target_id="graph",
        projector=_FailingProjector(),
        owner_id="worker",
        now="2026-07-16T12:00:02+00:00",
    )
    assert first.failed == second.failed == 1
    dead_letter = store.list_projection_failures(target_id="graph")[0]
    assert dead_letter.dead_letter is True
    assert dead_letter.error_message == "RuntimeError"
    store.release_projection_failure(
        target_id="graph",
        event_id=dead_letter.event_id,
        now="2026-07-16T12:00:03+00:00",
    )
    recovered = run_projection_batch(
        store,
        target_id="graph",
        projector=GraphChangeProjector(FakeGraphBackendAdapter()),
        owner_id="worker",
        now="2026-07-16T12:00:03+00:00",
    )
    assert recovered.checkpoint_cursor == 1
    assert store.list_projection_failures(target_id="graph") == []


def test_target_success_with_checkpoint_failure_replays_idempotently(
    monkeypatch,
) -> None:
    store = SophiaGraphMemoryStore()
    namespace = MemoryNamespace(agent_id="agent", graph_id="main")
    store.put_record(_record("a", namespace))
    store.register_projection_target(ProjectionTarget("graph", "graph", "fake"))
    backend = FakeGraphBackendAdapter()
    original = store.advance_projection_checkpoint
    calls = 0

    def fail_once(checkpoint, *, fencing_token, now):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("checkpoint unavailable")
        return original(checkpoint, fencing_token=fencing_token, now=now)

    monkeypatch.setattr(store, "advance_projection_checkpoint", fail_once)
    first = run_projection_batch(
        store,
        target_id="graph",
        projector=GraphChangeProjector(backend),
        owner_id="worker",
        now=NOW,
    )
    failure = store.list_projection_failures(target_id="graph")[0]
    store.release_projection_failure(
        target_id="graph", event_id=failure.event_id, now="2026-07-16T12:00:02+00:00"
    )
    second = run_projection_batch(
        store,
        target_id="graph",
        projector=GraphChangeProjector(backend),
        owner_id="worker",
        now="2026-07-16T12:00:02+00:00",
    )
    assert first.checkpoint_cursor == 0
    assert second.checkpoint_cursor == 1
    assert len(backend.inventory()) == 1


def test_sqlite_projection_restart_recovers_checkpoint_failure(
    monkeypatch, tmp_path
) -> None:
    path = tmp_path / "projection-restart.sqlite3"
    store = SophiaGraphSqliteStore(path)
    namespace = MemoryNamespace(agent_id="agent", graph_id="main")
    store.put_record(_record("a", namespace))
    store.register_projection_target(ProjectionTarget("graph", "graph", "fake"))
    backend = FakeGraphBackendAdapter()

    def fail_checkpoint(*args, **kwargs):
        raise RuntimeError("checkpoint unavailable")

    monkeypatch.setattr(store, "advance_projection_checkpoint", fail_checkpoint)
    first = run_projection_batch(
        store,
        target_id="graph",
        projector=GraphChangeProjector(backend),
        owner_id="worker",
        now=NOW,
    )
    assert first.checkpoint_cursor == 0

    reopened = SophiaGraphSqliteStore(path)
    failure = reopened.list_projection_failures(target_id="graph")[0]
    reopened.release_projection_failure(
        target_id="graph",
        event_id=failure.event_id,
        now="2026-07-16T12:00:02+00:00",
    )
    recovered = run_projection_batch(
        reopened,
        target_id="graph",
        projector=GraphChangeProjector(backend),
        owner_id="worker",
        now="2026-07-16T12:00:02+00:00",
    )
    assert recovered.checkpoint_cursor == 1
    assert len(backend.inventory()) == 1


def test_out_of_order_batch_is_rejected_before_target_mutation(monkeypatch) -> None:
    store = SophiaGraphMemoryStore()
    namespace = MemoryNamespace(agent_id="agent", graph_id="main")
    store.put_record(_record("a", namespace))
    store.put_record(_record("b", namespace))
    store.register_projection_target(ProjectionTarget("graph", "graph", "fake"))
    backend = FakeGraphBackendAdapter()
    original = store.list_changes
    calls = 0

    def reverse_batch(**kwargs):
        nonlocal calls
        calls += 1
        changes = original(**kwargs)
        return list(reversed(changes)) if calls == 2 else changes

    monkeypatch.setattr(store, "list_changes", reverse_batch)

    with pytest.raises(InvalidArgumentError, match="out of order"):
        run_projection_batch(
            store,
            target_id="graph",
            projector=GraphChangeProjector(backend),
            owner_id="worker",
            now=NOW,
        )

    assert backend.inventory() == ()
    assert store.get_projection_checkpoint("graph").cursor == 0
    assert store.get_projection_lease("graph") is None


def test_privacy_update_removes_derived_node_and_later_put_wins_tombstone() -> None:
    store = SophiaGraphMemoryStore()
    namespace = MemoryNamespace(agent_id="agent", graph_id="main")
    store.put_record(_record("a", namespace))
    store.register_projection_target(
        ProjectionTarget("graph", "graph", "fake", namespace=namespace)
    )
    backend = FakeGraphBackendAdapter()
    run_projection_batch(
        store,
        target_id="graph",
        projector=GraphChangeProjector(backend),
        owner_id="worker",
        now=NOW,
    )
    hidden = replace(
        _record("a", namespace),
        meta={"sophiagraph_privacy": {"export_visibility": "hidden"}},
    )
    store.put_record(hidden)
    run_projection_batch(
        store,
        target_id="graph",
        projector=GraphChangeProjector(backend),
        owner_id="worker",
        now="2026-07-16T12:00:01+00:00",
    )
    assert backend.inventory() == ()

    store.tombstone_record("a", deleted_at=NOW, reason="test")
    store.put_record(_record("a", namespace))
    run_projection_batch(
        store,
        target_id="graph",
        projector=GraphChangeProjector(backend),
        owner_id="worker",
        now="2026-07-16T12:00:02+00:00",
    )
    assert [item.object_id for item in backend.inventory()] == ["a"]


class _TelemetrySink:
    def __init__(self) -> None:
        self.events: list[TelemetryEvent] = []

    def record(self, event: TelemetryEvent) -> None:
        self.events.append(event)


def test_projection_health_telemetry_has_bounded_labels() -> None:
    store = SophiaGraphMemoryStore()
    target = ProjectionTarget("graph", "graph", "fake")
    store.register_projection_target(target)
    sink = _TelemetrySink()
    health = get_projection_health(store, target_id="graph", now=NOW)
    record_projection_health(health, target=target, sink=sink)
    attributes = sink.events[0].attributes
    assert attributes["health_state"] == "healthy"
    assert "target_id" not in attributes
    assert "payload" not in attributes


@pytest.mark.parametrize(
    ("health", "state"),
    [
        (ProjectionHealth("graph", 2, 1, 1, 0, 0), "lagging"),
        (ProjectionHealth("graph", 2, 1, 1, 1, 0), "retrying"),
        (ProjectionHealth("graph", 2, 1, 1, 1, 1), "dead_lettered"),
    ],
)
def test_projection_health_telemetry_reports_bounded_failure_states(
    health, state
) -> None:
    sink = _TelemetrySink()
    record_projection_health(
        health,
        target=ProjectionTarget("graph", "graph", "fake"),
        sink=sink,
    )

    assert sink.events[0].attributes["health_state"] == state
    assert set(sink.events[0].attributes) <= {
        "backend",
        "target_kind",
        "health_state",
        "reason_code",
        "cursor_lag",
        "retry_count",
        "dead_letter_count",
        "lease_active",
    }
