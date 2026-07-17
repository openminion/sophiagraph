"""Deterministic projection inventory comparison and explicit repair plans."""

from __future__ import annotations

from typing import Callable, Iterable

from sophiagraph.contracts.errors import (
    InvalidArgumentError,
    ProjectionRepairDeniedError,
)
from sophiagraph.models import (
    ProjectionFinding,
    ProjectionInventoryItem,
    ProjectionReconciliationReport,
    ProjectionRepairAction,
    ProjectionRepairPlan,
    ProjectionTargetKind,
    SophiaGraphChangeEvent,
)
from sophiagraph.storage.projection_state import structural_hash


def canonical_projection_inventory(
    events: Iterable[SophiaGraphChangeEvent], *, target_kind: ProjectionTargetKind
) -> tuple[ProjectionInventoryItem, ...]:
    items: dict[tuple[str, str], ProjectionInventoryItem] = {}
    if target_kind == "graph":
        allowed = {"record": "node", "relation": "edge", "link": "edge"}
    elif target_kind == "vector":
        allowed = {"embedding": "embedding"}
    else:
        raise InvalidArgumentError(f"invalid projection target kind: {target_kind!r}")
    for event in sorted(events, key=lambda item: int(item.cursor or 0)):
        object_kind = allowed.get(event.object_type)
        if object_kind is None:
            continue
        object_id = (
            str(event.payload.get("point_id") or event.object_id)
            if object_kind == "embedding"
            else event.object_id
        )
        key = (object_kind, object_id)
        if event.operation == "delete":
            items.pop(key, None)
            continue
        items[key] = ProjectionInventoryItem(
            object_id=object_id,
            object_kind=object_kind,
            version_hash=str(
                event.payload.get("version_hash") or structural_hash(event.payload)
            ),
        )
    return tuple(
        sorted(items.values(), key=lambda item: (item.object_kind, item.object_id))
    )


def _inventory_findings(
    canonical: dict[tuple[str, str], ProjectionInventoryItem],
    target: dict[tuple[str, str], ProjectionInventoryItem] | None,
    *,
    target_id: str,
    source_cursor: int,
    target_watermark: str | None,
) -> list[ProjectionFinding]:
    if target is None:
        findings = [
            ProjectionFinding(
                kind="unverifiable",
                object_id=target_id,
                object_kind="target",
            )
        ]
    else:
        findings = []
        for key in sorted(canonical):
            source_item = canonical[key]
            target_item = target.get(key)
            if target_item is None:
                findings.append(
                    ProjectionFinding(
                        kind="missing",
                        object_id=source_item.object_id,
                        object_kind=source_item.object_kind,
                        canonical_hash=source_item.version_hash,
                    )
                )
            elif source_item.version_hash != target_item.version_hash:
                findings.append(
                    ProjectionFinding(
                        kind="stale",
                        object_id=source_item.object_id,
                        object_kind=source_item.object_kind,
                        canonical_hash=source_item.version_hash,
                        target_hash=target_item.version_hash,
                    )
                )
        findings.extend(
            ProjectionFinding(
                kind="orphan",
                object_id=target[key].object_id,
                object_kind=target[key].object_kind,
                target_hash=target[key].version_hash,
            )
            for key in sorted(set(target) - set(canonical))
        )
    if target_watermark is not None and target_watermark != str(source_cursor):
        findings.append(
            ProjectionFinding(
                kind="watermark_mismatch",
                object_id=target_id,
                object_kind="target",
                canonical_hash=str(source_cursor),
                target_hash=target_watermark,
            )
        )
    return sorted(
        findings, key=lambda item: (item.kind, item.object_kind, item.object_id)
    )


def reconcile_projection_target(
    *,
    target_id: str,
    source_cursor: int,
    canonical_inventory: Iterable[ProjectionInventoryItem],
    target_inventory: Iterable[ProjectionInventoryItem] | None,
    target_watermark: str | None,
) -> tuple[ProjectionReconciliationReport, ProjectionRepairPlan]:
    canonical = {
        (item.object_kind, item.object_id): item for item in canonical_inventory
    }
    target = (
        {(item.object_kind, item.object_id): item for item in target_inventory}
        if target_inventory is not None
        else None
    )
    findings = _inventory_findings(
        canonical,
        target,
        target_id=target_id,
        source_cursor=source_cursor,
        target_watermark=target_watermark,
    )
    report_seed = [
        target_id,
        source_cursor,
        target_watermark,
        [
            (
                item.kind,
                item.object_kind,
                item.object_id,
                item.canonical_hash,
                item.target_hash,
            )
            for item in findings
        ],
    ]
    report_id = structural_hash(report_seed)
    report = ProjectionReconciliationReport(
        report_id=report_id,
        target_id=target_id,
        source_cursor=source_cursor,
        target_watermark=target_watermark,
        findings=tuple(findings),
    )
    actions = tuple(
        ProjectionRepairAction(
            operation="delete" if finding.kind == "orphan" else "upsert",
            object_id=finding.object_id,
            object_kind=finding.object_kind,
            version_hash=finding.canonical_hash,
        )
        for finding in findings
        if finding.kind in {"missing", "stale", "orphan"}
    )
    return report, ProjectionRepairPlan(
        plan_id=structural_hash(
            [
                report_id,
                [
                    (item.operation, item.object_kind, item.object_id)
                    for item in actions
                ],
            ]
        ),
        report_id=report_id,
        target_id=target_id,
        source_cursor=source_cursor,
        actions=actions,
    )


def apply_projection_repair_plan(
    plan: ProjectionRepairPlan,
    *,
    expected_report_id: str,
    current_source_cursor: int,
    authorized: bool,
    upsert: Callable[[ProjectionRepairAction], None],
    delete: Callable[[ProjectionRepairAction], None],
) -> int:
    if not authorized:
        raise ProjectionRepairDeniedError("projection repair requires authorization")
    if plan.report_id != expected_report_id:
        raise ProjectionRepairDeniedError("projection repair report binding rejected")
    if plan.source_cursor != current_source_cursor:
        raise ProjectionRepairDeniedError("projection repair plan is stale")
    for action in plan.actions:
        (upsert if action.operation == "upsert" else delete)(action)
    return len(plan.actions)


__all__ = [
    "apply_projection_repair_plan",
    "canonical_projection_inventory",
    "reconcile_projection_target",
]
