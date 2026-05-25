"""Saved view DTOs and deterministic in-package evaluation helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.models import MemoryRecord
from sophiagraph.query.structural import StructuralSearchQuery

ViewType = Literal["table", "list", "card", "map"]
ViewFilterOperator = Literal[
    "eq",
    "ne",
    "lt",
    "lte",
    "gt",
    "gte",
    "contains",
    "in",
    "exists",
    "link_to",
    "linked_from",
    "relation_type",
]
ViewBooleanOperator = Literal["and", "or", "not"]
ViewSummaryMetric = Literal["count", "count_distinct", "sum", "avg", "min", "max"]


@dataclass(frozen=True, slots=True)
class SavedViewFilter:
    field: str
    operator: ViewFilterOperator = "eq"
    value: Any = None

    def __post_init__(self) -> None:
        if not self.field:
            raise InvalidArgumentError("filter field is required")
        if self.operator not in {
            "eq",
            "ne",
            "lt",
            "lte",
            "gt",
            "gte",
            "contains",
            "in",
            "exists",
            "link_to",
            "linked_from",
            "relation_type",
        }:
            raise InvalidArgumentError(f"invalid filter operator: {self.operator!r}")


@dataclass(frozen=True, slots=True)
class SavedViewFilterGroup:
    operator: ViewBooleanOperator = "and"
    filters: list["SavedViewFilter | SavedViewFilterGroup"] = field(
        default_factory=list
    )

    def __post_init__(self) -> None:
        if self.operator not in {"and", "or", "not"}:
            raise InvalidArgumentError(
                f"invalid boolean filter operator: {self.operator!r}"
            )
        if self.operator == "not" and len(self.filters) != 1:
            raise InvalidArgumentError("not filter groups require exactly one child")


@dataclass(frozen=True, slots=True)
class SavedViewSummary:
    metric: ViewSummaryMetric
    field: str | None = None
    label: str | None = None

    def __post_init__(self) -> None:
        if self.metric not in {"count", "count_distinct", "sum", "avg", "min", "max"}:
            raise InvalidArgumentError(f"invalid summary metric: {self.metric!r}")
        if self.metric != "count" and not self.field:
            raise InvalidArgumentError(f"{self.metric} summaries require a field")


@dataclass(frozen=True, slots=True)
class SavedViewDefinition:
    view_id: str
    name: str
    view_type: ViewType = "table"
    query: StructuralSearchQuery = field(default_factory=StructuralSearchQuery)
    filters: SavedViewFilter | SavedViewFilterGroup | None = None
    projected_properties: list[str] = field(default_factory=list)
    sort: str | None = None
    group_by: str | None = None
    summaries: list[SavedViewSummary] = field(default_factory=list)
    formula: str | None = None

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
    groups: dict[str, list[str]] = field(default_factory=dict)
    summaries: dict[str, Any] = field(default_factory=dict)


def _record_properties(record: MemoryRecord) -> dict[str, Any]:
    document = record.meta.get("document")
    properties = record.meta.get("properties")
    merged: dict[str, Any] = {}
    if isinstance(document, dict):
        merged.update(document)
    if isinstance(properties, dict):
        merged.update(properties)
    merged.setdefault("id", record.id)
    merged.setdefault("title", record.title)
    merged.setdefault("scope", record.scope)
    merged.setdefault("type", record.type)
    merged.setdefault("key", record.key)
    merged.setdefault("tags", list(record.tags))
    merged.setdefault("tier", record.tier)
    merged.setdefault("source", record.source)
    merged.setdefault("created", record.created_at)
    merged.setdefault("updated", record.updated_at)
    return merged


def _to_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def _compare_values(actual: Any, expected: Any) -> int:
    actual_number = _to_number(actual)
    expected_number = _to_number(expected)
    if actual_number is not None and expected_number is not None:
        return (actual_number > expected_number) - (actual_number < expected_number)
    actual_text = "" if actual is None else str(actual)
    expected_text = "" if expected is None else str(expected)
    return (actual_text > expected_text) - (actual_text < expected_text)


def _link_values(
    record_id: str,
    operator: ViewFilterOperator,
    link_context: dict[str, dict[str, list[str]]],
) -> list[str]:
    return list(link_context.get(record_id, {}).get(operator, []))


def _filter_matches(
    record_id: str,
    properties: dict[str, Any],
    expression: SavedViewFilter | SavedViewFilterGroup | None,
    link_context: dict[str, dict[str, list[str]]],
) -> bool:
    if expression is None:
        return True
    if isinstance(expression, SavedViewFilterGroup):
        matches = [
            _filter_matches(record_id, properties, child, link_context)
            for child in expression.filters
        ]
        if expression.operator == "and":
            return all(matches)
        if expression.operator == "or":
            return any(matches)
        return not matches[0]

    if expression.operator in {"link_to", "linked_from", "relation_type"}:
        return str(expression.value) in _link_values(
            record_id, expression.operator, link_context
        )

    actual = properties.get(expression.field)
    if expression.operator == "exists":
        return actual is not None
    if expression.operator == "eq":
        return actual == expression.value
    if expression.operator == "ne":
        return actual != expression.value
    if expression.operator in {"lt", "lte", "gt", "gte"}:
        comparison = _compare_values(actual, expression.value)
        return {
            "lt": comparison < 0,
            "lte": comparison <= 0,
            "gt": comparison > 0,
            "gte": comparison >= 0,
        }[expression.operator]
    if expression.operator == "contains":
        if isinstance(actual, list | tuple | set):
            return str(expression.value) in {str(item) for item in actual}
        if isinstance(actual, dict):
            return str(expression.value) in {str(item) for item in actual}
        return str(expression.value) in str(actual or "")
    if expression.operator == "in":
        if not isinstance(expression.value, list | tuple | set):
            raise InvalidArgumentError("in filters require a list, tuple, or set value")
        return str(actual) in {str(item) for item in expression.value}
    raise InvalidArgumentError(f"unsupported filter operator: {expression.operator!r}")


def _summary_label(summary: SavedViewSummary) -> str:
    if summary.label:
        return summary.label
    return (
        summary.metric if summary.field is None else f"{summary.metric}:{summary.field}"
    )


def _summary_value(rows: list[SavedViewRow], summary: SavedViewSummary) -> Any:
    if summary.metric == "count":
        return len(rows)
    values = [
        row.properties.get(str(summary.field))
        for row in rows
        if row.properties.get(str(summary.field)) is not None
    ]
    if summary.metric == "count_distinct":
        return len({str(value) for value in values})
    if summary.metric in {"sum", "avg"}:
        total = 0.0
        count = 0
        for value in values:
            number = _to_number(value)
            if number is None:
                raise InvalidArgumentError(
                    f"{summary.metric} summary requires numeric values for {summary.field!r}"
                )
            total += number
            count += 1
        if summary.metric == "avg":
            return None if count == 0 else total / count
        return total
    if summary.metric == "min":
        return min(values) if values else None
    if summary.metric == "max":
        return max(values) if values else None
    raise InvalidArgumentError(f"unsupported summary metric: {summary.metric!r}")


def evaluate_saved_view(
    records: list[MemoryRecord],
    definition: SavedViewDefinition,
    *,
    link_context: dict[str, dict[str, list[str]]] | None = None,
) -> SavedViewResult:
    """Evaluate a saved view over already-selected records."""
    if definition.formula:
        raise InvalidArgumentError("saved view formula syntax is not supported")
    link_context = link_context or {}
    rows: list[SavedViewRow] = []
    for record in records:
        properties = _record_properties(record)
        if not _filter_matches(record.id, properties, definition.filters, link_context):
            continue
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
                provenance={
                    "source": "sophiagraph.views",
                    "view_type": definition.view_type,
                },
            )
        )
    sort_key = definition.sort or definition.query.sort
    sort_desc = False
    if sort_key and sort_key.startswith("-"):
        sort_key = sort_key[1:]
        sort_desc = True
    if sort_key:
        rows.sort(
            key=lambda row: str(row.properties.get(sort_key) or row.title or ""),
            reverse=sort_desc,
        )
    else:
        rows.sort(key=lambda row: row.record_id)
    groups: dict[str, list[str]] = {}
    for row in rows:
        if row.group is not None:
            groups.setdefault(row.group, []).append(row.record_id)
    summaries = {
        _summary_label(summary): _summary_value(rows, summary)
        for summary in definition.summaries
    }
    return SavedViewResult(
        view_id=definition.view_id, rows=rows, groups=groups, summaries=summaries
    )


__all__ = [
    "SavedViewDefinition",
    "SavedViewFilter",
    "SavedViewFilterGroup",
    "SavedViewResult",
    "SavedViewRow",
    "SavedViewSummary",
    "ViewBooleanOperator",
    "ViewFilterOperator",
    "ViewSummaryMetric",
    "ViewType",
    "evaluate_saved_view",
]
