"""Public vault facade over typed contracts, import-export, and repair flows."""

from __future__ import annotations

from sophiagraph.vault_io import (
    build_vault_manifest,
    export_vault_files,
    import_vault_files,
)
from sophiagraph.vault_repairs import apply_vault_repair_plan, plan_vault_repairs
from sophiagraph.vault_types import (
    VaultDiagnostic,
    VaultDiagnosticSeverity,
    VaultExportOptions,
    VaultExportResult,
    VaultExportedFile,
    VaultFileKind,
    VaultFilePayload,
    VaultFileRecord,
    VaultImportOptions,
    VaultImportResult,
    VaultManifest,
    VaultRenameOperation,
    VaultRepairPlan,
    VaultStore,
)

__all__ = [
    "VaultDiagnostic",
    "VaultDiagnosticSeverity",
    "VaultExportOptions",
    "VaultExportResult",
    "VaultExportedFile",
    "VaultFileKind",
    "VaultFilePayload",
    "VaultFileRecord",
    "VaultImportOptions",
    "VaultImportResult",
    "VaultManifest",
    "VaultRenameOperation",
    "VaultRepairPlan",
    "VaultStore",
    "apply_vault_repair_plan",
    "build_vault_manifest",
    "export_vault_files",
    "import_vault_files",
    "plan_vault_repairs",
]
