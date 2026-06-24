"""Private support helpers for the optional Kuzu backend."""

from __future__ import annotations

import importlib
import json
from typing import Any

from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.models import MemoryNamespace
from sophiagraph.schema import GraphSchema


def import_kuzu():
    """Import the optional Kuzu dependency lazily."""

    try:
        return importlib.import_module("kuzu")
    except ImportError as exc:
        raise ImportError(
            "KuzuGraphBackendAdapter requires the optional 'kuzu' dependency. "
            "Install it with `pip install sophiagraph[kuzu]`."
        ) from exc


def as_optional_str(value: Any) -> str | None:
    """Normalize an arbitrary row value into an optional string."""

    if value is None:
        return None
    return str(value)


def row_namespace(row: dict[str, Any], *, prefix: str) -> dict[str, str]:
    """Return the string namespace fields present in a backend row."""

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


def memory_namespace_from_row(row: dict[str, Any], *, prefix: str) -> MemoryNamespace:
    """Hydrate a ``MemoryNamespace`` from a backend row."""

    values = row_namespace(row, prefix=prefix)
    return MemoryNamespace.from_dict(values)


def graph_schema_from_payload(data: dict[str, Any]) -> GraphSchema:
    """Hydrate a ``GraphSchema`` from a stored JSON payload."""

    if not isinstance(data, dict):
        raise InvalidArgumentError("stored schema payload must be a dict")
    return GraphSchema(
        node_labels=[str(item) for item in data.get("node_labels", [])],
        relation_types=[str(item) for item in data.get("relation_types", [])],
        property_keys={
            str(key): [str(item) for item in values]
            for key, values in dict(data.get("property_keys", {})).items()
        },
        namespace_dimensions=[
            str(item) for item in data.get("namespace_dimensions", [])
        ],
        edge_constraints=[
            {str(key): str(value) for key, value in item.items()}
            for item in data.get("edge_constraints", [])
            if isinstance(item, dict)
        ],
        conflicts=[
            item for item in data.get("conflicts", []) if isinstance(item, dict)
        ],
    )


def load_schema_from_json(raw: str | None) -> GraphSchema | None:
    """Decode a stored schema JSON payload when present."""

    if not raw:
        return None
    data = json.loads(raw)
    return graph_schema_from_payload(data)


__all__ = [
    "as_optional_str",
    "graph_schema_from_payload",
    "import_kuzu",
    "load_schema_from_json",
    "memory_namespace_from_row",
    "row_namespace",
]
