"""SQLite changefeed row codecs and writers."""

from __future__ import annotations

import json
import sqlite3
from typing import Any
from uuid import uuid4

from sophiagraph.models import MemoryNamespace, SophiaGraphChangeEvent
from sophiagraph.portability.codec import change_event_from_dict, json_dumps
from sophiagraph.storage.record_lifecycle import utc_now_iso


class SqliteChangefeedMixin:
    def _change_from_row(self, row: sqlite3.Row) -> SophiaGraphChangeEvent:
        namespace = MemoryNamespace(
            tenant_id=row["tenant_id"],
            org_id=row["org_id"],
            user_id=row["user_id"],
            agent_id=row["agent_id"],
            session_id=row["session_id"],
            conversation_id=row["conversation_id"],
            project_id=row["project_id"],
            graph_id=row["graph_id"],
        )
        return change_event_from_dict(
            {
                "cursor": row["cursor"],
                "event_id": row["event_id"],
                "object_type": row["object_type"],
                "object_id": row["object_id"],
                "operation": row["operation"],
                "changed_at": row["changed_at"],
                "namespace": namespace.as_dict(),
                "idempotency_key": row["idempotency_key"],
                "source_operation_id": row["source_operation_id"],
                "schema_identifiers": json.loads(row["schema_identifiers_json"]),
                "payload": json.loads(row["payload_json"]),
            }
        )

    def _insert_change_event(
        self,
        conn: sqlite3.Connection,
        event: SophiaGraphChangeEvent,
    ) -> None:
        namespace_values = event.namespace.as_dict()
        conn.execute(
            """
            INSERT OR IGNORE INTO sophiagraph_change_events(
                event_id, object_type, object_id, operation, changed_at,
                tenant_id, org_id, user_id, agent_id, session_id,
                conversation_id, project_id, graph_id, idempotency_key,
                source_operation_id, schema_identifiers_json, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.event_id,
                event.object_type,
                event.object_id,
                event.operation,
                event.changed_at,
                namespace_values.get("tenant_id"),
                namespace_values.get("org_id"),
                namespace_values.get("user_id"),
                namespace_values.get("agent_id"),
                namespace_values.get("session_id"),
                namespace_values.get("conversation_id"),
                namespace_values.get("project_id"),
                namespace_values.get("graph_id"),
                event.idempotency_key,
                event.source_operation_id,
                json_dumps(event.schema_identifiers),
                json_dumps(event.payload),
            ),
        )

    def _emit_change(
        self,
        conn: sqlite3.Connection,
        *,
        object_type: str,
        object_id: str,
        payload: dict[str, Any],
        namespace: MemoryNamespace,
        schema_identifiers: dict[str, str],
        operation: str = "put",
    ) -> None:
        self._insert_change_event(
            conn,
            SophiaGraphChangeEvent(
                event_id=f"chg-{uuid4()}",
                object_type=object_type,  # type: ignore[arg-type]
                object_id=object_id,
                operation=operation,  # type: ignore[arg-type]
                changed_at=utc_now_iso(),
                payload=payload,
                namespace=namespace,
                schema_identifiers=schema_identifiers,
            ),
        )

    def _change_exists(
        self,
        conn: sqlite3.Connection,
        event: SophiaGraphChangeEvent,
    ) -> bool:
        row = conn.execute(
            """
            SELECT 1 FROM sophiagraph_change_events
             WHERE event_id = ?
                OR (? IS NOT NULL AND idempotency_key = ?)
            """,
            (event.event_id, event.idempotency_key, event.idempotency_key),
        ).fetchone()
        return row is not None


__all__ = ["SqliteChangefeedMixin"]
