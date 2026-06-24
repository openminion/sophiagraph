"""Public storage-operations facade for backups, leases, snapshots, and compaction."""

from __future__ import annotations

from sophiagraph.models import (
    BackupDescriptor,
    BackupIntegrityReport,
    BackupManifestEntry,
    CompactionOutcome,
    CompactionPlan,
    CoordinatedBackupManifest,
    MultiprocessLeaseToken,
    OperatorActionRequired,
    RestoreOptions,
    RestoreOutcome,
    RetentionSnapshot,
)
from sophiagraph.storage.backups import (
    create_backup,
    create_retention_snapshot,
    list_retention_snapshots,
    restore_backup,
    verify_backup,
    verify_retention_snapshot,
)
from sophiagraph.storage.compaction import compact_store, coordinated_backup
from sophiagraph.storage.leases import acquire_write_lease, release_write_lease

__all__ = [
    "create_backup",
    "restore_backup",
    "verify_backup",
    "acquire_write_lease",
    "release_write_lease",
    "create_retention_snapshot",
    "list_retention_snapshots",
    "verify_retention_snapshot",
    "compact_store",
    "coordinated_backup",
    "BackupDescriptor",
    "BackupIntegrityReport",
    "BackupManifestEntry",
    "CompactionOutcome",
    "CompactionPlan",
    "CoordinatedBackupManifest",
    "MultiprocessLeaseToken",
    "OperatorActionRequired",
    "RestoreOptions",
    "RestoreOutcome",
    "RetentionSnapshot",
]
