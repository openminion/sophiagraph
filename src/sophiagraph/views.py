"""Saved view DTOs and deterministic in-package evaluation helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.models import MemoryRecord
from sophiagraph.query.structural import StructuralSearchQuery

ViewType = Literal["table", "list", "card", "map"]


@dataclass(frozen=True, slots=True)
class SavedViewDefinition:
    view_id: str
    name: str
    view_type: ViewType = "table"
    query: StructuralSearchQuery = field(default_factory=StructuralSearchQuery)
    projected_properties: list[str] = field(default_factory=list)
    sort: str | None = None
    group_by: str | None = None

    def __post_init__(self) -> None:
        if not self.view_id:
            raise InvalidArgumentError("view_id is required")
        if not self.name:
            raise InvalidArgumentError("name is required")
        if self.view_type not in {"table", "list", "card", "map"}:
            raise InvalidArgumentError(f"invalid view_type: {self.view_type!r}")


@dataclass(frozen=True, slots=True)
class SavedViewRow:
    record_id: str
    title: str | None
    properties: dict[str, Any]
    group: str | None = None
    provenance: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SavedViewResult:
    view_id: str
    rows: list[SavedViewRow]


def _record_properties(record: MemoryRecord) -> dict[str, Any]:
    document = record.meta.get("document")
    properties = record.meta.get("properties")
    merged: dict[str, Any] = {}
    if isinstance(document, dict):
        merged.update(document)
    if isinstance(properties, dict):
        merged.update(properties)
    merged.setdefault("title", record.title)
    merged.setdefault("scope", record.scope)
    return merged


def evaluate_saved_view(
    records: list[MemoryRecord],
    definition: SavedViewDefinition,
) -> SavedViewResult:
    """Evaluate a saved view over already-selected records."""
    rows: list[SavedViewRow] = []
    for record in records:
        properties = _record_properties(record)
        selected = (
            properties
            if not definition.projected_properties
            else {
                key: properties.get(key)
                for key in definition.projected_properties
                if key in properties
            }
        )
        group = (
            str(properties.get(definition.group_by))
            if definition.group_by and properties.get(definition.group_by) is not None
            else None
        )
        rows.append(
            SavedViewRow(
                record_id=record.id,
                title=record.title,
                properties=selected,
                group=group,
                provenance={"source": "sophiagraph.views"},
            )
        )
    sort_key = definition.sort or definition.query.sort
    if sort_key in {"title", "path"}:
        rows.sort(key=lambda row: str(row.properties.get(sort_key) or row.title or ""))
    else:
        rows.sort(key=lambda row: row.record_id)
    return SavedViewResult(view_id=definition.view_id, rows=rows)


__all__ = [
    "SavedViewDefinition",
    "SavedViewResult",
    "SavedViewRow",
    "ViewType",
    "evaluate_saved_view",
]
