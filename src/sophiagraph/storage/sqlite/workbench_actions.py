"""SQLite workbench action journal support."""

from __future__ import annotations

from dataclasses import replace
import sqlite3
from typing import Any

from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.models import (
    MemoryNamespace,
    WorkbenchActionJournalEntry,
    WorkbenchActionResult,
)
from sophiagraph.portability.codec import json_dumps

from .rows import row_json


class SqliteWorkbenchActionMixin:
    def _workbench_action_from_row(
        self,
        row: sqlite3.Row,
    ) -> WorkbenchActionJournalEntry:
        return WorkbenchActionJournalEntry.from_dict(row_json(row))

    def _persist_workbench_action(
        self,
        conn: sqlite3.Connection,
        entry: WorkbenchActionJournalEntry,
    ) -> None:
        namespace_values = entry.namespace.as_dict()
        conn.execute(
            """
            INSERT OR REPLACE INTO sophiagraph_workbench_actions(
                action_id, request_hash, action, principal_id, workspace_id,
                scope, tenant_id, org_id, user_id, agent_id, session_id,
                conversation_id, project_id, graph_id, target_id, lifecycle,
                fencing_token, created_at, updated_at, started_at, completed_at,
                recovery_required, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entry.action_id,
                entry.request_hash,
                entry.action,
                entry.principal_id,
                entry.workspace_id,
                entry.scope,
                namespace_values.get("tenant_id"),
                namespace_values.get("org_id"),
                namespace_values.get("user_id"),
                namespace_values.get("agent_id"),
                namespace_values.get("session_id"),
                namespace_values.get("conversation_id"),
                namespace_values.get("project_id"),
                namespace_values.get("graph_id"),
                entry.target_id,
                entry.lifecycle,
                entry.fencing_token,
                entry.created_at,
                entry.updated_at,
                entry.started_at,
                entry.completed_at,
                1 if entry.recovery_required else 0,
                json_dumps(entry.to_dict()),
            ),
        )

    def reserve_workbench_action(
        self,
        entry: WorkbenchActionJournalEntry,
    ) -> WorkbenchActionJournalEntry:
        with self._write_connection() as conn:
            row = conn.execute(
                """
                SELECT payload_json FROM sophiagraph_workbench_actions
                 WHERE action_id = ?
                """,
                (entry.action_id,),
            ).fetchone()
            if row is not None:
                return self._workbench_action_from_row(row)
            self._persist_workbench_action(conn, entry)
        return entry

    def get_workbench_action(
        self,
        action_id: str,
        *,
        scope: str,
        namespace: MemoryNamespace,
    ) -> WorkbenchActionJournalEntry | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT payload_json FROM sophiagraph_workbench_actions
                 WHERE action_id = ? AND scope = ?
                """,
                (action_id, scope),
            ).fetchone()
        if row is None:
            return None
        entry = self._workbench_action_from_row(row)
        return entry if entry.namespace == namespace else None

    def mark_workbench_action_in_progress(
        self,
        action_id: str,
        *,
        fencing_token: int,
        started_at: str,
    ) -> WorkbenchActionJournalEntry:
        with self._write_connection() as conn:
            row = conn.execute(
                """
                SELECT payload_json FROM sophiagraph_workbench_actions
                 WHERE action_id = ?
                """,
                (action_id,),
            ).fetchone()
            if row is None:
                raise InvalidArgumentError(f"unknown action_id: {action_id}")
            entry = self._workbench_action_from_row(row)
            if entry.fencing_token != fencing_token:
                raise InvalidArgumentError("action fencing token mismatch")
            if entry.lifecycle == "terminal":
                return entry
            updated = replace(
                entry,
                lifecycle="in_progress",
                started_at=started_at,
                updated_at=started_at,
            )
            self._persist_workbench_action(conn, updated)
        return updated

    def finalize_workbench_action(
        self,
        action_id: str,
        *,
        fencing_token: int,
        result: WorkbenchActionResult,
        completed_at: str,
    ) -> WorkbenchActionJournalEntry:
        with self._write_connection() as conn:
            row = conn.execute(
                """
                SELECT payload_json FROM sophiagraph_workbench_actions
                 WHERE action_id = ?
                """,
                (action_id,),
            ).fetchone()
            if row is None:
                raise InvalidArgumentError(f"unknown action_id: {action_id}")
            entry = self._workbench_action_from_row(row)
            if entry.fencing_token != fencing_token:
                raise InvalidArgumentError("action fencing token mismatch")
            updated = replace(
                entry,
                lifecycle="terminal",
                completed_at=completed_at,
                updated_at=completed_at,
                result=result,
                recovery_required=result.recovery_required,
            )
            self._persist_workbench_action(conn, updated)
        return updated

    def list_workbench_actions(
        self,
        *,
        scope: str | None = None,
        namespace: MemoryNamespace | None = None,
        lifecycle: str | None = None,
        limit: int | None = None,
    ) -> list[WorkbenchActionJournalEntry]:
        query = "SELECT payload_json FROM sophiagraph_workbench_actions WHERE 1=1"
        params: list[Any] = []
        if scope is not None:
            query += " AND scope = ?"
            params.append(scope)
        if lifecycle is not None:
            query += " AND lifecycle = ?"
            params.append(lifecycle)
        query += " ORDER BY updated_at DESC, action_id DESC"
        if limit is not None:
            query += " LIMIT ?"
            params.append(int(limit))
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        entries = [self._workbench_action_from_row(row) for row in rows]
        if namespace is not None:
            entries = [entry for entry in entries if entry.namespace == namespace]
        return entries

    def prune_workbench_actions(
        self,
        *,
        completed_before: str,
    ) -> int:
        with self._write_connection() as conn:
            rows = conn.execute(
                """
                SELECT action_id, payload_json FROM sophiagraph_workbench_actions
                 WHERE lifecycle = 'terminal'
                   AND recovery_required = 0
                   AND completed_at IS NOT NULL
                   AND completed_at < ?
                """,
                (completed_before,),
            ).fetchall()
            action_ids = [
                str(row["action_id"])
                for row in rows
                if not self._workbench_action_from_row(row).recovery_required
            ]
            for action_id in action_ids:
                conn.execute(
                    "DELETE FROM sophiagraph_workbench_actions WHERE action_id = ?",
                    (action_id,),
                )
        return len(action_ids)


__all__ = ["SqliteWorkbenchActionMixin"]
