"""Deterministic saved-view evaluation helpers."""

from __future__ import annotations

import ast
from datetime import datetime
from typing import Any

from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.models import MemoryRecord

from .view_types import (
    SavedViewDefinition,
    SavedViewFilter,
    SavedViewFilterGroup,
    SavedViewResult,
    SavedViewRow,
    SavedViewSummary,
    ViewFilterOperator,
)


def record_properties(record: MemoryRecord) -> dict[str, Any]:
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


def to_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def compare_values(actual: Any, expected: Any) -> int:
    actual_number = to_number(actual)
    expected_number = to_number(expected)
    if actual_number is not None and expected_number is not None:
        return (actual_number > expected_number) - (actual_number < expected_number)
    actual_text = "" if actual is None else str(actual)
    expected_text = "" if expected is None else str(expected)
    return (actual_text > expected_text) - (actual_text < expected_text)


def link_values(
    record_id: str,
    operator: ViewFilterOperator,
    link_context: dict[str, dict[str, list[str]]],
) -> list[str]:
    return list(link_context.get(record_id, {}).get(operator, []))


def filter_matches(
    record_id: str,
    properties: dict[str, Any],
    expression: SavedViewFilter | SavedViewFilterGroup | None,
    link_context: dict[str, dict[str, list[str]]],
) -> bool:
    if expression is None:
        return True
    if isinstance(expression, SavedViewFilterGroup):
        matches = [
            filter_matches(record_id, properties, child, link_context)
            for child in expression.filters
        ]
        if expression.operator == "and":
            return all(matches)
        if expression.operator == "or":
            return any(matches)
        return not matches[0]

    if expression.operator in {"link_to", "linked_from", "relation_type"}:
        return str(expression.value) in link_values(
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
        comparison = compare_values(actual, expression.value)
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


def summary_label(summary: SavedViewSummary) -> str:
    if summary.label:
        return summary.label
    return (
        summary.metric if summary.field is None else f"{summary.metric}:{summary.field}"
    )


def summary_value(rows: list[SavedViewRow], summary: SavedViewSummary) -> Any:
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
            number = to_number(value)
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


_ALLOWED_FUNCTIONS = {"len"}


def normalize_formula_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): normalize_formula_value(item) for key, item in value.items()}
    if isinstance(value, list | tuple | set):
        return [normalize_formula_value(item) for item in value]
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value
    return value


class FormulaValidator(ast.NodeVisitor):
    _ALLOWED_NODES = (
        ast.Expression,
        ast.BinOp,
        ast.UnaryOp,
        ast.Compare,
        ast.BoolOp,
        ast.IfExp,
        ast.Name,
        ast.Constant,
        ast.Subscript,
        ast.Load,
        ast.List,
        ast.Tuple,
        ast.Dict,
        ast.keyword,
        ast.Call,
        ast.Add,
        ast.Sub,
        ast.Mult,
        ast.Div,
        ast.FloorDiv,
        ast.Mod,
        ast.Pow,
        ast.USub,
        ast.UAdd,
        ast.Not,
        ast.And,
        ast.Or,
        ast.Eq,
        ast.NotEq,
        ast.Lt,
        ast.LtE,
        ast.Gt,
        ast.GtE,
        ast.In,
        ast.NotIn,
    )

    def __init__(self, allowed_names: set[str]) -> None:
        self._allowed_names = allowed_names

    def generic_visit(self, node: ast.AST) -> None:
        if not isinstance(node, self._ALLOWED_NODES):
            raise InvalidArgumentError(
                f"unsupported formula syntax: {node.__class__.__name__}"
            )
        super().generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if node.id not in self._allowed_names and node.id not in _ALLOWED_FUNCTIONS:
            raise InvalidArgumentError(f"unknown formula field: {node.id!r}")

    def visit_Attribute(self, node: ast.Attribute) -> None:
        raise InvalidArgumentError("attribute access is not allowed in formulas")

    def visit_Call(self, node: ast.Call) -> None:
        if (
            not isinstance(node.func, ast.Name)
            or node.func.id not in _ALLOWED_FUNCTIONS
        ):
            raise InvalidArgumentError("formula calls must use allowlisted helpers")
        for keyword in node.keywords:
            if keyword.arg is None:
                raise InvalidArgumentError("formula star-args are not allowed")
        self.generic_visit(node)


def evaluate_formula_expression(
    formula: str,
    properties: dict[str, Any],
) -> Any:
    try:
        tree = ast.parse(formula, mode="eval")
    except SyntaxError as exc:
        raise InvalidArgumentError("invalid formula syntax") from exc
    FormulaValidator(set(properties)).visit(tree)
    normalized = {
        key: normalize_formula_value(value) for key, value in properties.items()
    }

    def _eval(node: ast.AST) -> Any:
        if isinstance(node, ast.Expression):
            return _eval(node.body)
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            return normalized[node.id]
        if isinstance(node, ast.List):
            return [_eval(item) for item in node.elts]
        if isinstance(node, ast.Tuple):
            return tuple(_eval(item) for item in node.elts)
        if isinstance(node, ast.Dict):
            return {
                _eval(key): _eval(value) for key, value in zip(node.keys, node.values)
            }
        if isinstance(node, ast.Subscript):
            container = _eval(node.value)
            if isinstance(node.slice, ast.Slice):
                raise InvalidArgumentError("slice access is not allowed in formulas")
            return container[_eval(node.slice)]
        if isinstance(node, ast.UnaryOp):
            operand = _eval(node.operand)
            if isinstance(node.op, ast.USub):
                return -operand
            if isinstance(node.op, ast.UAdd):
                return +operand
            if isinstance(node.op, ast.Not):
                return not operand
        if isinstance(node, ast.BinOp):
            left = _eval(node.left)
            right = _eval(node.right)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if isinstance(node.op, ast.Div):
                return left / right
            if isinstance(node.op, ast.FloorDiv):
                return left // right
            if isinstance(node.op, ast.Mod):
                return left % right
            if isinstance(node.op, ast.Pow):
                return left**right
        if isinstance(node, ast.BoolOp):
            values = [_eval(value) for value in node.values]
            if isinstance(node.op, ast.And):
                return all(values)
            if isinstance(node.op, ast.Or):
                return any(values)
        if isinstance(node, ast.Compare):
            left = _eval(node.left)
            for operator, comparator in zip(node.ops, node.comparators):
                right = _eval(comparator)
                if isinstance(operator, ast.Eq):
                    matched = left == right
                elif isinstance(operator, ast.NotEq):
                    matched = left != right
                elif isinstance(operator, ast.Lt):
                    matched = left < right
                elif isinstance(operator, ast.LtE):
                    matched = left <= right
                elif isinstance(operator, ast.Gt):
                    matched = left > right
                elif isinstance(operator, ast.GtE):
                    matched = left >= right
                elif isinstance(operator, ast.In):
                    matched = left in right
                elif isinstance(operator, ast.NotIn):
                    matched = left not in right
                else:
                    raise InvalidArgumentError("unsupported comparison operator")
                if not matched:
                    return False
                left = right
            return True
        if isinstance(node, ast.IfExp):
            return _eval(node.body if _eval(node.test) else node.orelse)
        if isinstance(node, ast.Call):
            assert isinstance(node.func, ast.Name)
            args = [_eval(arg) for arg in node.args]
            if node.func.id == "len":
                if len(args) != 1:
                    raise InvalidArgumentError("len() formulas require one argument")
                return len(args[0])
        raise InvalidArgumentError("unsupported formula syntax")

    try:
        return _eval(tree)
    except (KeyError, TypeError, ValueError, ZeroDivisionError) as exc:
        raise InvalidArgumentError("formula evaluation failed") from exc


def evaluate_saved_view(
    records: list[MemoryRecord],
    definition: SavedViewDefinition,
    *,
    link_context: dict[str, dict[str, list[str]]] | None = None,
) -> SavedViewResult:
    """Evaluate a saved view over already-selected records."""
    link_context = link_context or {}
    rows: list[SavedViewRow] = []
    for record in records:
        properties = record_properties(record)
        if not filter_matches(record.id, properties, definition.filters, link_context):
            continue
        if definition.formula:
            properties = dict(properties)
            properties["formula"] = evaluate_formula_expression(
                definition.formula,
                properties,
            )
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
        summary_label(summary): summary_value(rows, summary)
        for summary in definition.summaries
    }
    return SavedViewResult(
        view_id=definition.view_id, rows=rows, groups=groups, summaries=summaries
    )


__all__ = ["evaluate_saved_view"]
