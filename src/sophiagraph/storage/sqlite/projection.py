"""SQLite persistence for derived-index projection delivery state."""

from __future__ import annotations

import json
import sqlite3

from sophiagraph.contracts.errors import (
    NotFoundError,
    ProjectionCheckpointError,
    ProjectionFenceError,
    ProjectionLeaseHeldError,
)
from sophiagraph.models import (
    MemoryNamespace,
    ProjectionAttempt,
    ProjectionCheckpoint,
    ProjectionFailure,
    ProjectionLease,
    ProjectionTarget,
    projection_target_from_dict,
    projection_target_to_dict,
)
from sophiagraph.portability.codec import json_dumps
from sophiagraph.storage.projection_state import (
    bounded_error_message,
    is_expired,
    iso_after,
    target_matches_namespaces,
)


def _lease_from_row(row: sqlite3.Row) -> ProjectionLease:
    return ProjectionLease(
        target_id=str(row["target_id"]),
        owner_id=str(row["owner_id"]),
        fencing_token=int(row["fencing_token"]),
        acquired_at=str(row["acquired_at"]),
        expires_at=str(row["expires_at"]),
    )


def _attempt_from_row(row: sqlite3.Row) -> ProjectionAttempt:
    return ProjectionAttempt(
        attempt_id=str(row["attempt_id"]),
        target_id=str(row["target_id"]),
        event_id=str(row["event_id"]),
        cursor=int(row["cursor"]),
        attempt_number=int(row["attempt_number"]),
        status=str(row["status"]),  # type: ignore[arg-type]
        started_at=str(row["started_at"]),
        completed_at=row["completed_at"],
        next_retry_at=row["next_retry_at"],
        error_code=row["error_code"],
        error_message=row["error_message"],
    )


def _failure_from_row(row: sqlite3.Row) -> ProjectionFailure:
    return ProjectionFailure(
        target_id=str(row["target_id"]),
        event_id=str(row["event_id"]),
        cursor=int(row["cursor"]),
        attempt_count=int(row["attempt_count"]),
        reason=str(row["reason"]),  # type: ignore[arg-type]
        retryable=bool(row["retryable"]),
        dead_letter=bool(row["dead_letter"]),
        updated_at=str(row["updated_at"]),
        next_retry_at=row["next_retry_at"],
        error_message=row["error_message"],
    )


class SqliteProjectionStateMixin:
    def register_projection_target(self, target: ProjectionTarget) -> str:
        namespace_json = (
            json_dumps(target.namespace.as_dict())
            if target.namespace is not None
            else None
        )
        with self._write_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO sophiagraph_projection_targets(
                    target_id, target_kind, adapter_name, enabled,
                    max_attempts, lease_seconds, namespace_json, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    target.target_id,
                    target.kind,
                    target.adapter_name,
                    int(target.enabled),
                    target.max_attempts,
                    target.lease_seconds,
                    namespace_json,
                    json_dumps(projection_target_to_dict(target)),
                ),
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO sophiagraph_projection_checkpoints(
                    target_id, cursor, event_id, updated_at, target_watermark
                ) VALUES (?, 0, NULL, '', NULL)
                """,
                (target.target_id,),
            )
        return target.target_id

    def get_projection_target(self, target_id: str) -> ProjectionTarget | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload_json FROM sophiagraph_projection_targets WHERE target_id = ?",
                (target_id,),
            ).fetchone()
        return (
            projection_target_from_dict(json.loads(row["payload_json"]))
            if row is not None
            else None
        )

    def list_projection_targets(
        self,
        *,
        namespaces: list[MemoryNamespace] | None = None,
        enabled_only: bool = False,
    ) -> list[ProjectionTarget]:
        query = "SELECT payload_json FROM sophiagraph_projection_targets"
        if enabled_only:
            query += " WHERE enabled = 1"
        query += " ORDER BY target_id"
        with self._connect() as conn:
            rows = conn.execute(query).fetchall()
        targets = [
            projection_target_from_dict(json.loads(row["payload_json"])) for row in rows
        ]
        return [
            target
            for target in targets
            if target_matches_namespaces(target, namespaces)
        ]

    def get_projection_checkpoint(self, target_id: str) -> ProjectionCheckpoint:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM sophiagraph_projection_checkpoints WHERE target_id = ?",
                (target_id,),
            ).fetchone()
        if row is None:
            raise NotFoundError("projection target not found")
        return ProjectionCheckpoint(
            target_id=target_id,
            cursor=int(row["cursor"]),
            event_id=row["event_id"],
            updated_at=str(row["updated_at"]),
            target_watermark=row["target_watermark"],
        )

    def get_projection_lease(self, target_id: str) -> ProjectionLease | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM sophiagraph_projection_leases WHERE target_id = ?",
                (target_id,),
            ).fetchone()
        return _lease_from_row(row) if row is not None else None

    def acquire_projection_lease(
        self, *, target_id: str, owner_id: str, now: str
    ) -> ProjectionLease:
        target = self.get_projection_target(target_id)
        if target is None:
            raise NotFoundError("projection target not found")
        with self._write_connection() as conn:
            row = conn.execute(
                "SELECT * FROM sophiagraph_projection_leases WHERE target_id = ?",
                (target_id,),
            ).fetchone()
            current = _lease_from_row(row) if row is not None else None
            if current is not None and not is_expired(current.expires_at, now):
                if current.owner_id != owner_id:
                    raise ProjectionLeaseHeldError(
                        "projection target is already leased"
                    )
            token = (current.fencing_token if current is not None else 0) + 1
            lease = ProjectionLease(
                target_id=target_id,
                owner_id=owner_id,
                fencing_token=token,
                acquired_at=now,
                expires_at=iso_after(now, target.lease_seconds),
            )
            conn.execute(
                """
                INSERT OR REPLACE INTO sophiagraph_projection_leases(
                    target_id, owner_id, fencing_token, acquired_at, expires_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    lease.target_id,
                    lease.owner_id,
                    lease.fencing_token,
                    lease.acquired_at,
                    lease.expires_at,
                ),
            )
        return lease

    def release_projection_lease(
        self, *, target_id: str, owner_id: str, fencing_token: int
    ) -> None:
        with self._write_connection() as conn:
            row = conn.execute(
                "SELECT * FROM sophiagraph_projection_leases WHERE target_id = ?",
                (target_id,),
            ).fetchone()
            if row is None:
                return
            lease = _lease_from_row(row)
            if lease.owner_id != owner_id or lease.fencing_token != fencing_token:
                raise ProjectionFenceError("projection lease fencing token rejected")
            conn.execute(
                "DELETE FROM sophiagraph_projection_leases WHERE target_id = ?",
                (target_id,),
            )

    def advance_projection_checkpoint(
        self,
        checkpoint: ProjectionCheckpoint,
        *,
        fencing_token: int,
        now: str,
    ) -> None:
        with self._write_connection() as conn:
            lease_row = conn.execute(
                "SELECT * FROM sophiagraph_projection_leases WHERE target_id = ?",
                (checkpoint.target_id,),
            ).fetchone()
            if lease_row is None:
                raise ProjectionFenceError("projection lease is not held")
            lease = _lease_from_row(lease_row)
            if lease.fencing_token != fencing_token or is_expired(
                lease.expires_at, now
            ):
                raise ProjectionFenceError("projection lease fencing token rejected")
            current = conn.execute(
                "SELECT cursor FROM sophiagraph_projection_checkpoints WHERE target_id = ?",
                (checkpoint.target_id,),
            ).fetchone()
            if current is None:
                raise NotFoundError("projection target not found")
            if checkpoint.cursor <= int(current["cursor"]):
                raise ProjectionCheckpointError("checkpoint cursor must advance")
            conn.execute(
                """
                UPDATE sophiagraph_projection_checkpoints
                   SET cursor = ?, event_id = ?, updated_at = ?, target_watermark = ?
                 WHERE target_id = ?
                """,
                (
                    checkpoint.cursor,
                    checkpoint.event_id,
                    checkpoint.updated_at,
                    checkpoint.target_watermark,
                    checkpoint.target_id,
                ),
            )

    def record_projection_attempt(self, attempt: ProjectionAttempt) -> None:
        with self._write_connection() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO sophiagraph_projection_attempts(
                    attempt_id, target_id, event_id, cursor, attempt_number,
                    status, started_at, completed_at, next_retry_at,
                    error_code, error_message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    attempt.attempt_id,
                    attempt.target_id,
                    attempt.event_id,
                    attempt.cursor,
                    attempt.attempt_number,
                    attempt.status,
                    attempt.started_at,
                    attempt.completed_at,
                    attempt.next_retry_at,
                    attempt.error_code,
                    bounded_error_message(attempt.error_message),
                ),
            )

    def list_projection_attempts(
        self, *, target_id: str, event_id: str | None = None
    ) -> list[ProjectionAttempt]:
        query = "SELECT * FROM sophiagraph_projection_attempts WHERE target_id = ?"
        params: list[object] = [target_id]
        if event_id is not None:
            query += " AND event_id = ?"
            params.append(event_id)
        query += " ORDER BY cursor, attempt_number"
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [_attempt_from_row(row) for row in rows]

    def put_projection_failure(self, failure: ProjectionFailure) -> None:
        with self._write_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO sophiagraph_projection_failures(
                    target_id, event_id, cursor, attempt_count, reason,
                    retryable, dead_letter, updated_at, next_retry_at,
                    error_message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    failure.target_id,
                    failure.event_id,
                    failure.cursor,
                    failure.attempt_count,
                    failure.reason,
                    int(failure.retryable),
                    int(failure.dead_letter),
                    failure.updated_at,
                    failure.next_retry_at,
                    bounded_error_message(failure.error_message),
                ),
            )

    def clear_projection_failure(self, *, target_id: str, event_id: str) -> None:
        with self._write_connection() as conn:
            conn.execute(
                "DELETE FROM sophiagraph_projection_failures WHERE target_id = ? AND event_id = ?",
                (target_id, event_id),
            )

    def release_projection_failure(
        self, *, target_id: str, event_id: str, now: str
    ) -> ProjectionFailure:
        with self._write_connection() as conn:
            row = conn.execute(
                """
                SELECT * FROM sophiagraph_projection_failures
                 WHERE target_id = ? AND event_id = ?
                """,
                (target_id, event_id),
            ).fetchone()
            if row is None:
                raise NotFoundError("projection failure not found")
            conn.execute(
                """
                UPDATE sophiagraph_projection_failures
                   SET retryable = 1, dead_letter = 0,
                       next_retry_at = ?, updated_at = ?
                 WHERE target_id = ? AND event_id = ?
                """,
                (now, now, target_id, event_id),
            )
            released = _failure_from_row(row)
        return ProjectionFailure(
            target_id=released.target_id,
            event_id=released.event_id,
            cursor=released.cursor,
            attempt_count=released.attempt_count,
            reason=released.reason,
            retryable=True,
            dead_letter=False,
            updated_at=now,
            next_retry_at=now,
            error_message=released.error_message,
        )

    def list_projection_failures(
        self,
        *,
        target_id: str,
        dead_letter: bool | None = None,
    ) -> list[ProjectionFailure]:
        query = "SELECT * FROM sophiagraph_projection_failures WHERE target_id = ?"
        params: list[object] = [target_id]
        if dead_letter is not None:
            query += " AND dead_letter = ?"
            params.append(int(dead_letter))
        query += " ORDER BY cursor, event_id"
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [_failure_from_row(row) for row in rows]


__all__ = ["SqliteProjectionStateMixin"]
