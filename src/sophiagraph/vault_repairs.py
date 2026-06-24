"""Vault repair planning and application over structural link targets."""

from __future__ import annotations

from dataclasses import replace

from sophiagraph.query import LinkQueryOptions
from sophiagraph.vault_support import (
    record_vault_meta,
    records_for_vault,
    rewrite_link_target,
)
from sophiagraph.vault_types import (
    VaultDiagnostic,
    VaultExportOptions,
    VaultRenameOperation,
    VaultRepairPlan,
    VaultStore,
)


def plan_vault_repairs(
    store: VaultStore,
    operations: list[VaultRenameOperation],
    options: VaultExportOptions,
) -> VaultRepairPlan:
    records = records_for_vault(
        store,
        vault_id=options.vault_id,
        namespace=options.namespace,
        scope=options.scope,
        include_deleted=True,
    )
    affected: list[str] = []
    diagnostics: list[VaultDiagnostic] = []
    existing_paths = {
        str(record_vault_meta(record).get("path"))
        for record in records
        if record_vault_meta(record).get("path")
    }
    for operation in operations:
        if operation.new_path in existing_paths:
            diagnostics.append(
                VaultDiagnostic(
                    code="repair_target_conflict",
                    path=operation.new_path,
                    message=f"repair target already exists: {operation.new_path}",
                    severity="warning",
                )
            )
        for record in records:
            for link in store.list_links(
                LinkQueryOptions(
                    record_id=record.id,
                    direction="out",
                    namespaces=[options.namespace],
                )
            ):
                if link.target_path == operation.old_path or rewrite_link_target(
                    link.raw_target, operation
                ):
                    affected.append(link.link_id)
    return VaultRepairPlan(
        vault_id=options.vault_id,
        namespace=options.namespace,
        operations=list(operations),
        affected_link_ids=sorted(set(affected)),
        diagnostics=diagnostics,
    )


def apply_vault_repair_plan(
    store: VaultStore,
    plan: VaultRepairPlan,
    options: VaultExportOptions,
) -> VaultRepairPlan:
    records = records_for_vault(
        store,
        vault_id=options.vault_id,
        namespace=options.namespace,
        scope=options.scope,
        include_deleted=True,
    )
    changed: list[str] = []
    for record in records:
        outgoing = store.list_links(
            LinkQueryOptions(
                record_id=record.id,
                direction="out",
                namespaces=[options.namespace],
            )
        )
        rewritten = []
        touched = False
        for link in outgoing:
            updated = link
            for operation in plan.operations:
                new_raw = rewrite_link_target(link.raw_target, operation)
                if new_raw is None and link.target_path != operation.old_path:
                    continue
                updated = replace(
                    updated,
                    raw_target=new_raw or updated.raw_target,
                    target_path=operation.new_path
                    if updated.target_path == operation.old_path
                    else updated.target_path,
                    meta={
                        **dict(updated.meta),
                        "vault_repair": {
                            "old_path": operation.old_path,
                            "new_path": operation.new_path,
                        },
                    },
                )
                touched = True
                changed.append(updated.link_id)
            rewritten.append(updated)
        if touched:
            store.replace_record_links(record.id, rewritten)
    return VaultRepairPlan(
        vault_id=plan.vault_id,
        namespace=plan.namespace,
        operations=list(plan.operations),
        affected_link_ids=sorted(set(changed)),
        diagnostics=list(plan.diagnostics),
    )
