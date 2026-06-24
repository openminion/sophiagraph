"""Stable public facade for saved-view DTOs and deterministic evaluation."""

from __future__ import annotations

from .view_eval import evaluate_saved_view
from .view_types import (
    SavedViewDefinition,
    SavedViewFilter,
    SavedViewFilterGroup,
    SavedViewResult,
    SavedViewRow,
    SavedViewSummary,
    ViewBooleanOperator,
    ViewFilterOperator,
    ViewSummaryMetric,
    ViewType,
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
