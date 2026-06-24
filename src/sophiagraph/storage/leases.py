"""Private write-lease helpers for storage operations."""

from __future__ import annotations

from datetime import timedelta
import threading
from typing import Any
from uuid import uuid4

from sophiagraph.contracts.errors import (
    InvalidArgumentError,
    WriteLeaseExpiredError,
    WriteLeaseNotHeldError,
)
from sophiagraph.models import MultiprocessLeaseToken
from sophiagraph.storage.memory import SophiaGraphMemoryStore
from sophiagraph.storage.operation_support import _isoformat, _parse_dt, _utc_now
from sophiagraph.storage.sqlite import SophiaGraphSqliteStore

_LEASE_REGISTRY_LOCK = threading.Lock()
_LEASE_HEARTBEATS: dict[str, threading.Event] = {}
_MEMORY_WRITE_LEASES: dict[str, dict[str, Any]] = {}
_DEFAULT_RESOURCE_ID = "store:write"


def acquire_write_lease(
    store: SophiaGraphMemoryStore | SophiaGraphSqliteStore,
    *,
    owner: str,
    ttl_seconds: int = 30,
    heartbeat_seconds: int = 5,
) -> MultiprocessLeaseToken:
    if not owner:
        raise InvalidArgumentError("owner is required")
    if ttl_seconds <= 0 or heartbeat_seconds <= 0:
        raise InvalidArgumentError("lease durations must be positive")
    if isinstance(store, SophiaGraphSqliteStore):
        token = _acquire_sqlite_lease(
            store,
            owner=owner,
            ttl_seconds=ttl_seconds,
            heartbeat_seconds=heartbeat_seconds,
        )
    elif isinstance(store, SophiaGraphMemoryStore):
        token = _acquire_memory_lease(
            owner=owner,
            ttl_seconds=ttl_seconds,
            heartbeat_seconds=heartbeat_seconds,
        )
    else:
        raise InvalidArgumentError("unsupported store type for lease")
    _start_lease_heartbeat(token, store)
    return token


def release_write_lease(
    lease: MultiprocessLeaseToken,
    *,
    store: SophiaGraphMemoryStore | SophiaGraphSqliteStore,
) -> None:
    _stop_lease_heartbeat(lease.lease_id)
    if isinstance(store, SophiaGraphSqliteStore):
        _release_sqlite_lease(store, lease)
        return
    if isinstance(store, SophiaGraphMemoryStore):
        _release_memory_lease(lease)
        return
    raise InvalidArgumentError("unsupported store type for lease release")


def _acquire_sqlite_lease(
    store: SophiaGraphSqliteStore,
    *,
    owner: str,
    ttl_seconds: int,
    heartbeat_seconds: int,
) -> MultiprocessLeaseToken:
    now = _utc_now()
    expires_at = now + timedelta(seconds=ttl_seconds)
    lease_id = str(uuid4())
    with store._write_connection() as conn:  # noqa: SLF001
        row = conn.execute(
            """
            SELECT lease_id, owner, expires_at
              FROM sophiagraph_write_leases
             WHERE resource_id = ?
            """,
            (_DEFAULT_RESOURCE_ID,),
        ).fetchone()
        if row is not None and _parse_dt(str(row["expires_at"])) > now:
            raise WriteLeaseNotHeldError(
                "write lease is already held",
                details={
                    "resource_id": _DEFAULT_RESOURCE_ID,
                    "owner": row["owner"],
                },
            )
        conn.execute(
            """
            INSERT OR REPLACE INTO sophiagraph_write_leases(
                resource_id, lease_id, owner, acquired_at, expires_at, ttl_seconds, heartbeat_seconds
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _DEFAULT_RESOURCE_ID,
                lease_id,
                owner,
                _isoformat(now),
                _isoformat(expires_at),
                ttl_seconds,
                heartbeat_seconds,
            ),
        )
    return MultiprocessLeaseToken(
        lease_id=lease_id,
        resource_id=_DEFAULT_RESOURCE_ID,
        owner=owner,
        backend_name="sqlite",
        acquired_at=_isoformat(now),
        expires_at=_isoformat(expires_at),
        ttl_seconds=ttl_seconds,
        heartbeat_seconds=heartbeat_seconds,
        metadata={"db_path": str(store.db_path)},
    )


def _release_sqlite_lease(
    store: SophiaGraphSqliteStore,
    lease: MultiprocessLeaseToken,
) -> None:
    with store._write_connection() as conn:  # noqa: SLF001
        row = conn.execute(
            """
            SELECT lease_id, owner, expires_at
              FROM sophiagraph_write_leases
             WHERE resource_id = ?
            """,
            (lease.resource_id,),
        ).fetchone()
        if row is None or str(row["lease_id"]) != lease.lease_id:
            raise WriteLeaseNotHeldError(
                "write lease is not currently held",
                details={"lease_id": lease.lease_id},
            )
        if _parse_dt(str(row["expires_at"])) <= _utc_now():
            conn.execute(
                "DELETE FROM sophiagraph_write_leases WHERE resource_id = ?",
                (lease.resource_id,),
            )
            raise WriteLeaseExpiredError(
                "write lease expired before release",
                details={"lease_id": lease.lease_id},
            )
        conn.execute(
            "DELETE FROM sophiagraph_write_leases WHERE resource_id = ?",
            (lease.resource_id,),
        )


def _acquire_memory_lease(
    *,
    owner: str,
    ttl_seconds: int,
    heartbeat_seconds: int,
) -> MultiprocessLeaseToken:
    now = _utc_now()
    expires_at = now + timedelta(seconds=ttl_seconds)
    lease_id = str(uuid4())
    with _LEASE_REGISTRY_LOCK:
        current = _MEMORY_WRITE_LEASES.get(_DEFAULT_RESOURCE_ID)
        if current is not None and _parse_dt(str(current["expires_at"])) > now:
            raise WriteLeaseNotHeldError(
                "write lease is already held",
                details={
                    "resource_id": _DEFAULT_RESOURCE_ID,
                    "owner": current["owner"],
                },
            )
        _MEMORY_WRITE_LEASES[_DEFAULT_RESOURCE_ID] = {
            "lease_id": lease_id,
            "owner": owner,
            "expires_at": _isoformat(expires_at),
            "ttl_seconds": ttl_seconds,
            "heartbeat_seconds": heartbeat_seconds,
        }
    return MultiprocessLeaseToken(
        lease_id=lease_id,
        resource_id=_DEFAULT_RESOURCE_ID,
        owner=owner,
        backend_name="memory",
        acquired_at=_isoformat(now),
        expires_at=_isoformat(expires_at),
        ttl_seconds=ttl_seconds,
        heartbeat_seconds=heartbeat_seconds,
    )


def _release_memory_lease(lease: MultiprocessLeaseToken) -> None:
    with _LEASE_REGISTRY_LOCK:
        current = _MEMORY_WRITE_LEASES.get(lease.resource_id)
        if current is None or str(current["lease_id"]) != lease.lease_id:
            raise WriteLeaseNotHeldError(
                "write lease is not currently held",
                details={"lease_id": lease.lease_id},
            )
        if _parse_dt(str(current["expires_at"])) <= _utc_now():
            _MEMORY_WRITE_LEASES.pop(lease.resource_id, None)
            raise WriteLeaseExpiredError(
                "write lease expired before release",
                details={"lease_id": lease.lease_id},
            )
        _MEMORY_WRITE_LEASES.pop(lease.resource_id, None)


def _start_lease_heartbeat(
    lease: MultiprocessLeaseToken,
    store: SophiaGraphMemoryStore | SophiaGraphSqliteStore,
) -> None:
    stop = threading.Event()
    with _LEASE_REGISTRY_LOCK:
        _LEASE_HEARTBEATS[lease.lease_id] = stop

    def _run() -> None:
        while not stop.wait(float(lease.heartbeat_seconds)):
            try:
                _heartbeat_lease(lease, store)
            except Exception:
                stop.set()

    thread = threading.Thread(
        target=_run,
        name=f"sophiagraph-lease-{lease.lease_id}",
        daemon=True,
    )
    thread.start()


def _stop_lease_heartbeat(lease_id: str) -> None:
    with _LEASE_REGISTRY_LOCK:
        stop = _LEASE_HEARTBEATS.pop(lease_id, None)
    if stop is not None:
        stop.set()


def _heartbeat_lease(
    lease: MultiprocessLeaseToken,
    store: SophiaGraphMemoryStore | SophiaGraphSqliteStore,
) -> None:
    new_expiry = _utc_now() + timedelta(seconds=lease.ttl_seconds)
    if isinstance(store, SophiaGraphSqliteStore):
        with store._write_connection() as conn:  # noqa: SLF001
            row = conn.execute(
                """
                SELECT lease_id, expires_at FROM sophiagraph_write_leases
                 WHERE resource_id = ?
                """,
                (lease.resource_id,),
            ).fetchone()
            if row is None or str(row["lease_id"]) != lease.lease_id:
                raise WriteLeaseNotHeldError("write lease is not currently held")
            if _parse_dt(str(row["expires_at"])) <= _utc_now():
                raise WriteLeaseExpiredError("write lease expired during heartbeat")
            conn.execute(
                """
                UPDATE sophiagraph_write_leases
                   SET expires_at = ?
                 WHERE resource_id = ? AND lease_id = ?
                """,
                (_isoformat(new_expiry), lease.resource_id, lease.lease_id),
            )
        return
    with _LEASE_REGISTRY_LOCK:
        current = _MEMORY_WRITE_LEASES.get(lease.resource_id)
        if current is None or str(current["lease_id"]) != lease.lease_id:
            raise WriteLeaseNotHeldError("write lease is not currently held")
        if _parse_dt(str(current["expires_at"])) <= _utc_now():
            raise WriteLeaseExpiredError("write lease expired during heartbeat")
        current["expires_at"] = _isoformat(new_expiry)
