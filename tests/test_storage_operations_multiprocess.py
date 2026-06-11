from __future__ import annotations

from multiprocessing import Process, Queue
from pathlib import Path
import time

from sophiagraph import MemoryRecord, SophiaGraphSqliteStore
from sophiagraph.contracts.errors import WriteLeaseNotHeldError
from sophiagraph.storage.operations import acquire_write_lease


def _record(record_id: str) -> MemoryRecord:
    return MemoryRecord(
        id=record_id,
        scope="agent:lease",
        type="fact",
        key=record_id,
        title=record_id,
        content={"text": record_id},
        created_at="2026-06-10T00:00:00+00:00",
        updated_at="2026-06-10T00:00:00+00:00",
    )


def _hold_lease(db_path: str, queue: Queue) -> None:
    store = SophiaGraphSqliteStore(db_path)
    try:
        lease = acquire_write_lease(
            store,
            owner="proc-1",
            ttl_seconds=2,
            heartbeat_seconds=10,
        )
        queue.put(("held", lease.lease_id))
        time.sleep(1.0)
    except Exception as exc:  # pragma: no cover - child-process evidence
        queue.put(("error", type(exc).__name__))


def _contend_lease(db_path: str, queue: Queue) -> None:
    store = SophiaGraphSqliteStore(db_path)
    try:
        acquire_write_lease(
            store,
            owner="proc-2",
            ttl_seconds=2,
            heartbeat_seconds=10,
        )
        queue.put(("unexpected", "acquired"))
    except WriteLeaseNotHeldError:
        queue.put(("blocked", "write_lease_not_held"))
    except Exception as exc:  # pragma: no cover - child-process evidence
        queue.put(("error", type(exc).__name__))


def test_sqlite_write_lease_serializes_real_processes_and_expires(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "lease.sqlite3"
    seed = SophiaGraphSqliteStore(db_path)
    seed.put_record(_record("rec-lease"))
    queue: Queue = Queue()

    first = Process(target=_hold_lease, args=(str(db_path), queue))
    second = Process(target=_contend_lease, args=(str(db_path), queue))
    first.start()
    held = queue.get(timeout=5)
    second.start()
    blocked = queue.get(timeout=5)
    first.join(timeout=5)
    second.join(timeout=5)

    assert held[0] == "held"
    assert blocked == ("blocked", "write_lease_not_held")

    time.sleep(2.2)
    recovered = acquire_write_lease(
        SophiaGraphSqliteStore(db_path),
        owner="parent",
        ttl_seconds=2,
        heartbeat_seconds=10,
    )
    assert recovered.owner == "parent"
