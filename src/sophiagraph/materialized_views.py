"""Changefeed-aware materialized saved-view cache."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Protocol

from sophiagraph.models import MemoryRecord, SophiaGraphChangeEvent
from sophiagraph.views import SavedViewDefinition, SavedViewResult, evaluate_saved_view


@dataclass(frozen=True, slots=True)
class MaterializedViewEntry:
    view_id: str
    source_cursor: int
    result: SavedViewResult


class MaterializedViewCache(Protocol):
    def get(self, view_id: str) -> MaterializedViewEntry | None: ...

    def put(self, entry: MaterializedViewEntry) -> None: ...

    def delete(self, view_id: str) -> None: ...


class InMemoryMaterializedViewCache:
    def __init__(self) -> None:
        self._entries: dict[str, MaterializedViewEntry] = {}

    def get(self, view_id: str) -> MaterializedViewEntry | None:
        return self._entries.get(view_id)

    def put(self, entry: MaterializedViewEntry) -> None:
        self._entries[entry.view_id] = entry

    def delete(self, view_id: str) -> None:
        self._entries.pop(view_id, None)


def refresh_materialized_view(
    definition: SavedViewDefinition,
    records: list[MemoryRecord],
    *,
    source_cursor: int,
    cache: MaterializedViewCache,
) -> MaterializedViewEntry:
    result = evaluate_saved_view(records, definition)
    entry = MaterializedViewEntry(
        view_id=definition.view_id,
        source_cursor=source_cursor,
        result=result,
    )
    cache.put(entry)
    return entry


def view_requires_refresh(
    entry: MaterializedViewEntry | None,
    events: Iterable[SophiaGraphChangeEvent],
) -> bool:
    if entry is None:
        return True
    relevant_types = {"record", "relation", "link", "view", "schema", "ontology"}
    return any(
        event.object_type in relevant_types
        and event.cursor is not None
        and event.cursor > entry.source_cursor
        for event in events
    )


__all__ = [
    "InMemoryMaterializedViewCache",
    "MaterializedViewCache",
    "MaterializedViewEntry",
    "refresh_materialized_view",
    "view_requires_refresh",
]
