"""Saved-view rollups and embedded live-query composition helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.models import MemoryRecord
from sophiagraph.view_eval import evaluate_saved_view
from sophiagraph.view_types import SavedViewDefinition, SavedViewResult

RollupMetric = Literal["count", "count_distinct", "sum"]


@dataclass(frozen=True, slots=True)
class RelationRollupDefinition:
    """Deterministic rollup over explicit relation/link fields."""

    rollup_id: str
    source_view_id: str
    relation_type: str | None = None
    metric: RollupMetric = "count"
    field: str | None = None

    def __post_init__(self) -> None:
        if not self.rollup_id:
            raise InvalidArgumentError("rollup_id is required")
        if not self.source_view_id:
            raise InvalidArgumentError("source_view_id is required")
        if self.metric not in {"count", "count_distinct", "sum"}:
            raise InvalidArgumentError(f"invalid rollup metric: {self.metric!r}")
        if self.metric != "count" and not self.field:
            raise InvalidArgumentError(f"{self.metric} rollups require field")


@dataclass(frozen=True, slots=True)
class RelationRollupResult:
    """Computed rollup values keyed by record id."""

    rollup_id: str
    values: dict[str, Any]
    diagnostics: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class EmbeddedQueryPanel:
    """One typed live panel embedding an existing saved view."""

    panel_id: str
    title: str
    view: SavedViewDefinition
    max_rows: int = 25

    def __post_init__(self) -> None:
        if not self.panel_id:
            raise InvalidArgumentError("panel_id is required")
        if not self.title:
            raise InvalidArgumentError("title is required")
        if self.max_rows <= 0:
            raise InvalidArgumentError("max_rows must be positive")


@dataclass(frozen=True, slots=True)
class LiveQueryPanelResult:
    """Live panel result with structural explain evidence."""

    panel_id: str
    result: SavedViewResult
    explain: tuple[str, ...]


def evaluate_relation_rollup(
    rollup: RelationRollupDefinition,
    records: list[MemoryRecord],
) -> RelationRollupResult:
    """Evaluate a bounded rollup over record metadata produced by existing views."""

    values: dict[str, Any] = {}
    for record in records:
        related = _related_ids(record, rollup.relation_type)
        if rollup.metric == "count":
            values[record.id] = len(related)
        elif rollup.metric == "count_distinct":
            values[record.id] = len(set(related))
        else:
            values[record.id] = sum(_numeric_values(record, rollup.field or ""))
    return RelationRollupResult(
        rollup_id=rollup.rollup_id,
        values=values,
        diagnostics={"record_count": len(records), "metric": rollup.metric},
    )


def evaluate_live_query_panels(
    panels: tuple[EmbeddedQueryPanel, ...],
    records: list[MemoryRecord],
) -> tuple[LiveQueryPanelResult, ...]:
    """Evaluate embedded saved-view panels without adding a second query language."""

    results: list[LiveQueryPanelResult] = []
    for panel in panels:
        view_result = evaluate_saved_view(records, panel.view)
        trimmed = SavedViewResult(
            view_id=view_result.view_id,
            rows=view_result.rows[: panel.max_rows],
            groups=view_result.groups,
            summaries=view_result.summaries,
        )
        results.append(
            LiveQueryPanelResult(
                panel_id=panel.panel_id,
                result=trimmed,
                explain=(
                    f"view:{panel.view.view_id}",
                    f"input_records:{len(records)}",
                    f"output_rows:{len(trimmed.rows)}",
                ),
            )
        )
    return tuple(results)


def _related_ids(record: MemoryRecord, relation_type: str | None) -> list[str]:
    relations = record.meta.get("relations", [])
    if not isinstance(relations, list):
        return []
    related: list[str] = []
    for item in relations:
        if not isinstance(item, dict):
            continue
        if (
            relation_type is not None
            and str(item.get("relation_type")) != relation_type
        ):
            continue
        target_id = item.get("target_record_id") or item.get("record_id")
        if target_id:
            related.append(str(target_id))
    return related


def _numeric_values(record: MemoryRecord, field: str) -> list[float]:
    properties = record.meta.get("properties", {})
    if not isinstance(properties, dict):
        return []
    value = properties.get(field)
    if isinstance(value, list):
        values = value
    else:
        values = [value]
    numbers: list[float] = []
    for item in values:
        if isinstance(item, bool):
            continue
        if isinstance(item, int | float):
            numbers.append(float(item))
    return numbers


__all__ = [
    "EmbeddedQueryPanel",
    "LiveQueryPanelResult",
    "RelationRollupDefinition",
    "RelationRollupResult",
    "evaluate_live_query_panels",
    "evaluate_relation_rollup",
]
