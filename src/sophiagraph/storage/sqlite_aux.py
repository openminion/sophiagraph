"""SQLite auxiliary-object persistence helpers."""

from __future__ import annotations

import sqlite3
from typing import Any

from sophiagraph.models import MemoryNamespace
from sophiagraph.portability.codec import json_dumps
from sophiagraph.storage.sqlite_support import namespace_filter_sql, row_json


class SqliteAuxObjectMixin:
    def _connect(self) -> sqlite3.Connection:
        raise NotImplementedError

    def _put_aux_object(
        self,
        conn: sqlite3.Connection,
        *,
        object_kind: str,
        object_id: str,
        namespace: MemoryNamespace,
        updated_at: str | None,
        payload: dict[str, Any],
    ) -> None:
        values = namespace.as_dict()
        conn.execute(
            """
            INSERT OR REPLACE INTO sophiagraph_aux_objects(
                object_kind, object_id, tenant_id, org_id, user_id, agent_id,
                session_id, conversation_id, project_id, graph_id, updated_at,
                payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                object_kind,
                object_id,
                values.get("tenant_id"),
                values.get("org_id"),
                values.get("user_id"),
                values.get("agent_id"),
                values.get("session_id"),
                values.get("conversation_id"),
                values.get("project_id"),
                values.get("graph_id"),
                updated_at,
                json_dumps(payload),
            ),
        )

    def _get_aux_object(
        self, object_kind: str, object_id: str
    ) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT payload_json FROM sophiagraph_aux_objects
                 WHERE object_kind = ? AND object_id = ?
                """,
                (object_kind, object_id),
            ).fetchone()
        return None if row is None else row_json(row)

    def _list_aux_objects(
        self,
        object_kind: str,
        *,
        namespaces: list[MemoryNamespace] | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        clauses = ["object_kind = ?"]
        params: list[Any] = [object_kind]
        namespace_sql, namespace_params = namespace_filter_sql(namespaces)
        if namespace_sql:
            clauses.append(namespace_sql)
            params.extend(namespace_params)
        query = (
            "SELECT payload_json FROM sophiagraph_aux_objects WHERE "
            + " AND ".join(clauses)
            + " ORDER BY updated_at DESC, object_id ASC"
        )
        if limit is not None:
            query += " LIMIT ?"
            params.append(int(limit))
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [row_json(row) for row in rows]


__all__ = ["SqliteAuxObjectMixin"]
