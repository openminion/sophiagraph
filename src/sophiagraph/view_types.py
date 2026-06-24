"""Typed saved-view contracts for deterministic in-package view evaluation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from sophiagraph.contracts.errors import InvalidArgumentError
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
]
