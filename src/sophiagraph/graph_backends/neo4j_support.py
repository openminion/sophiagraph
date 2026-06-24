"""Private support helpers for the optional Neo4j backend adapter."""

from __future__ import annotations

import importlib
from typing import Any


def import_neo4j() -> Any:
    try:
        return importlib.import_module("neo4j")
    except ImportError as exc:
        raise ImportError(
            "Neo4jGraphBackendAdapter requires the optional 'neo4j' dependency. "
            "Install it with `pip install sophiagraph[neo4j]`."
        ) from exc


def as_optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def row_namespace(row: dict[str, Any], *, prefix: str) -> dict[str, str]:
    return {
        field: str(row[f"{prefix}{field}"])
        for field in (
            "tenant_id",
            "org_id",
            "user_id",
            "agent_id",
            "session_id",
            "conversation_id",
            "project_id",
            "graph_id",
        )
        if row.get(f"{prefix}{field}") is not None
    }
