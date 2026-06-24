"""SQLite row and namespace helpers."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from sophiagraph.models import MemoryNamespace, MemoryRecord

NAMESPACE_COLUMNS = (
    "tenant_id",
    "org_id",
    "user_id",
    "agent_id",
    "session_id",
    "conversation_id",
    "project_id",
    "graph_id",
)


def row_json(row: sqlite3.Row, key: str = "payload_json") -> dict[str, Any]:
    raw = row[key]
    return json.loads(str(raw)) if raw else {}


def namespace_values(record: MemoryRecord) -> dict[str, str]:
    return record.effective_namespace.as_dict()


def namespace_from_payload(payload: dict[str, Any], scope: str) -> MemoryNamespace:
    raw_namespace = payload.get("namespace")
    if isinstance(raw_namespace, dict) and raw_namespace:
        return MemoryNamespace.from_dict(raw_namespace)
    return MemoryNamespace.from_scope(scope)


def namespace_filter_sql(
    namespaces: list[MemoryNamespace] | None,
) -> tuple[str, list[Any]]:
    if not namespaces:
        return "", []
    groups: list[str] = []
    params: list[Any] = []
    for namespace in namespaces:
        values = namespace.as_dict()
        clauses = [f"{column} = ?" for column in values]
        groups.append("(" + " AND ".join(clauses) + ")")
        params.extend(values.values())
    return "(" + " OR ".join(groups) + ")", params


__all__ = [
    "NAMESPACE_COLUMNS",
    "namespace_filter_sql",
    "namespace_from_payload",
    "namespace_values",
    "row_json",
]
