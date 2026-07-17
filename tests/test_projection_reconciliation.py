from __future__ import annotations

import pytest

from sophiagraph.contracts.errors import (
    InvalidArgumentError,
    ProjectionRepairDeniedError,
)
from sophiagraph.models import ProjectionInventoryItem
from sophiagraph.projection_reconciliation import (
    apply_projection_repair_plan,
    canonical_projection_inventory,
    reconcile_projection_target,
)


def test_reconciliation_is_stable_and_classifies_structural_drift() -> None:
    canonical = (
        ProjectionInventoryItem("missing", "node", "v1"),
        ProjectionInventoryItem("stale", "node", "v2"),
    )
    target = (
        ProjectionInventoryItem("stale", "node", "v1"),
        ProjectionInventoryItem("orphan", "node", "v1"),
    )
    first = reconcile_projection_target(
        target_id="graph",
        source_cursor=9,
        canonical_inventory=canonical,
        target_inventory=target,
        target_watermark="8",
    )
    second = reconcile_projection_target(
        target_id="graph",
        source_cursor=9,
        canonical_inventory=reversed(canonical),
        target_inventory=reversed(target),
        target_watermark="8",
    )
    assert first == second
    assert {item.kind for item in first[0].findings} == {
        "missing",
        "stale",
        "orphan",
        "watermark_mismatch",
    }


def test_repair_requires_authorization_and_current_report_cursor() -> None:
    report, plan = reconcile_projection_target(
        target_id="graph",
        source_cursor=3,
        canonical_inventory=(ProjectionInventoryItem("missing", "node", "v1"),),
        target_inventory=(),
        target_watermark="3",
    )
    applied = []
    with pytest.raises(ProjectionRepairDeniedError):
        apply_projection_repair_plan(
            plan,
            expected_report_id=report.report_id,
            current_source_cursor=3,
            authorized=False,
            upsert=applied.append,
            delete=applied.append,
        )
    with pytest.raises(ProjectionRepairDeniedError, match="stale"):
        apply_projection_repair_plan(
            plan,
            expected_report_id=report.report_id,
            current_source_cursor=4,
            authorized=True,
            upsert=applied.append,
            delete=applied.append,
        )
    assert (
        apply_projection_repair_plan(
            plan,
            expected_report_id=report.report_id,
            current_source_cursor=3,
            authorized=True,
            upsert=applied.append,
            delete=applied.append,
        )
        == 1
    )
    assert applied[0].operation == "upsert"


def test_canonical_inventory_rejects_unknown_target_kind() -> None:
    with pytest.raises(InvalidArgumentError, match="target kind"):
        canonical_projection_inventory([], target_kind="other")  # type: ignore[arg-type]
