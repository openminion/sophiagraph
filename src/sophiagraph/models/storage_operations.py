"""Typed storage-operations DTOs for backup, leases, snapshots, and compaction."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Final, Literal

from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.models.namespace import MemoryNamespace

BackupKind = Literal["physical_sqlite", "physical_memory", "coordinated"]
BACKUP_KINDS: Final[frozenset[str]] = frozenset(
    {"physical_sqlite", "physical_memory", "coordinated"}
)


@dataclass(frozen=True, slots=True)
class BackupManifestEntry:
    table_group: str
    row_count: int
    sha256: str
    byte_size: int

    def __post_init__(self) -> None:
        if not self.table_group:
            raise InvalidArgumentError("table_group is required")
        if self.row_count < 0:
            raise InvalidArgumentError("row_count must be non-negative")
        if not self.sha256:
            raise InvalidArgumentError("sha256 is required")
        if self.byte_size < 0:
            raise InvalidArgumentError("byte_size must be non-negative")


@dataclass(frozen=True, slots=True)
class BackupDescriptor:
    backup_id: str
    kind: BackupKind
    backend_name: str
    created_at: str
    target_path: str
    manifest_entries: list[BackupManifestEntry] = field(default_factory=list)
    wal_frame_position: int | None = None
    namespaces: list[MemoryNamespace] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.backup_id:
            raise InvalidArgumentError("backup_id is required")
        if self.kind not in BACKUP_KINDS:
            raise InvalidArgumentError(f"invalid backup kind: {self.kind!r}")
        if not self.backend_name:
            raise InvalidArgumentError("backend_name is required")
        if not self.created_at:
            raise InvalidArgumentError("created_at is required")
        if not self.target_path:
            raise InvalidArgumentError("target_path is required")
        if self.wal_frame_position is not None and self.wal_frame_position < 0:
            raise InvalidArgumentError("wal_frame_position must be non-negative")

    def to_dict(self) -> dict[str, Any]:
        return {
            "backup_id": self.backup_id,
            "kind": self.kind,
            "backend_name": self.backend_name,
            "created_at": self.created_at,
            "target_path": self.target_path,
            "manifest_entries": [
                {
                    "table_group": entry.table_group,
                    "row_count": entry.row_count,
                    "sha256": entry.sha256,
                    "byte_size": entry.byte_size,
                }
                for entry in self.manifest_entries
            ],
            "wal_frame_position": self.wal_frame_position,
            "namespaces": [ns.as_dict() for ns in self.namespaces or []],
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "BackupDescriptor":
        namespaces = [
            MemoryNamespace.from_dict(item)
            for item in payload.get("namespaces", [])
            if isinstance(item, dict)
        ]
        return cls(
            backup_id=str(payload.get("backup_id", "")),
            kind=str(payload.get("kind", "")),  # type: ignore[arg-type]
            backend_name=str(payload.get("backend_name", "")),
            created_at=str(payload.get("created_at", "")),
            target_path=str(payload.get("target_path", "")),
            manifest_entries=[
                BackupManifestEntry(
                    table_group=str(item.get("table_group", "")),
                    row_count=int(item.get("row_count", 0) or 0),
                    sha256=str(item.get("sha256", "")),
                    byte_size=int(item.get("byte_size", 0) or 0),
                )
                for item in payload.get("manifest_entries", [])
                if isinstance(item, dict)
            ],
            wal_frame_position=(
                int(payload["wal_frame_position"])
                if payload.get("wal_frame_position") is not None
                else None
            ),
            namespaces=namespaces or None,
            metadata=dict(payload.get("metadata", {}))
            if isinstance(payload.get("metadata"), dict)
            else {},
        )


@dataclass(frozen=True, slots=True)
class BackupIntegrityReport:
    backup_id: str
    verified: bool
    checked_entries: int
    mismatches: list[str] = field(default_factory=list)
    missing_entries: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.backup_id:
            raise InvalidArgumentError("backup_id is required")
        if self.checked_entries < 0:
            raise InvalidArgumentError("checked_entries must be non-negative")


@dataclass(frozen=True, slots=True)
class RestoreOptions:
    verify: bool = True
    overwrite: bool = True


@dataclass(frozen=True, slots=True)
class RestoreOutcome:
    backup_id: str
    restored: bool
    backend_name: str
    restored_path: str | None = None
    report: BackupIntegrityReport | None = None
    restored_store: Any | None = None

    def __post_init__(self) -> None:
        if not self.backup_id:
            raise InvalidArgumentError("backup_id is required")
        if not self.backend_name:
            raise InvalidArgumentError("backend_name is required")


@dataclass(frozen=True, slots=True)
class MultiprocessLeaseToken:
    lease_id: str
    resource_id: str
    owner: str
    backend_name: str
    acquired_at: str
    expires_at: str
    ttl_seconds: int
    heartbeat_seconds: int
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.lease_id:
            raise InvalidArgumentError("lease_id is required")
        if not self.resource_id:
            raise InvalidArgumentError("resource_id is required")
        if not self.owner:
            raise InvalidArgumentError("owner is required")
        if not self.backend_name:
            raise InvalidArgumentError("backend_name is required")
        if not self.acquired_at or not self.expires_at:
            raise InvalidArgumentError("lease timestamps are required")
        if self.ttl_seconds <= 0:
            raise InvalidArgumentError("ttl_seconds must be positive")
        if self.heartbeat_seconds <= 0:
            raise InvalidArgumentError("heartbeat_seconds must be positive")


@dataclass(frozen=True, slots=True)
class RetentionSnapshot:
    snapshot_id: str
    name: str
    namespace: MemoryNamespace
    created_at: str
    as_of_cursor: int | None
    backup_descriptor: BackupDescriptor
    payload: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.snapshot_id:
            raise InvalidArgumentError("snapshot_id is required")
        if not self.name:
            raise InvalidArgumentError("name is required")
        if not self.created_at:
            raise InvalidArgumentError("created_at is required")
        if self.as_of_cursor is not None and self.as_of_cursor < 0:
            raise InvalidArgumentError("as_of_cursor must be non-negative")

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "name": self.name,
            "namespace": self.namespace.as_dict(),
            "created_at": self.created_at,
            "as_of_cursor": self.as_of_cursor,
            "backup_descriptor": self.backup_descriptor.to_dict(),
            "payload": dict(self.payload),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RetentionSnapshot":
        return cls(
            snapshot_id=str(payload.get("snapshot_id", "")),
            name=str(payload.get("name", "")),
            namespace=MemoryNamespace.from_dict(
                dict(payload.get("namespace", {}))
                if isinstance(payload.get("namespace"), dict)
                else {}
            ),
            created_at=str(payload.get("created_at", "")),
            as_of_cursor=(
                int(payload["as_of_cursor"])
                if payload.get("as_of_cursor") is not None
                else None
            ),
            backup_descriptor=BackupDescriptor.from_dict(
                dict(payload.get("backup_descriptor", {}))
                if isinstance(payload.get("backup_descriptor"), dict)
                else {}
            ),
            payload=dict(payload.get("payload", {}))
            if isinstance(payload.get("payload"), dict)
            else {},
        )


@dataclass(frozen=True, slots=True)
class RetentionSnapshotManifest:
    name: str
    namespace: MemoryNamespace
    entry_count: int
    sha256: str

    def __post_init__(self) -> None:
        if not self.name:
            raise InvalidArgumentError("name is required")
        if self.entry_count < 0:
            raise InvalidArgumentError("entry_count must be non-negative")
        if not self.sha256:
            raise InvalidArgumentError("sha256 is required")


@dataclass(frozen=True, slots=True)
class OperatorActionRequired:
    backend_name: str
    action: str
    command: str
    reason: str

    def __post_init__(self) -> None:
        if not self.backend_name:
            raise InvalidArgumentError("backend_name is required")
        if not self.action:
            raise InvalidArgumentError("action is required")
        if not self.command:
            raise InvalidArgumentError("command is required")
        if not self.reason:
            raise InvalidArgumentError("reason is required")


@dataclass(frozen=True, slots=True)
class CompactionPlan:
    backend_name: str
    strategy: str
    target: str
    notes: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.backend_name:
            raise InvalidArgumentError("backend_name is required")
        if not self.strategy:
            raise InvalidArgumentError("strategy is required")
        if not self.target:
            raise InvalidArgumentError("target is required")


@dataclass(frozen=True, slots=True)
class CompactionOutcome:
    backend_name: str
    applied: bool
    bytes_before: int | None = None
    bytes_after: int | None = None
    reclaimed_bytes: int | None = None
    operator_action_required: OperatorActionRequired | None = None
    notes: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.backend_name:
            raise InvalidArgumentError("backend_name is required")
        if self.bytes_before is not None and self.bytes_before < 0:
            raise InvalidArgumentError("bytes_before must be non-negative")
        if self.bytes_after is not None and self.bytes_after < 0:
            raise InvalidArgumentError("bytes_after must be non-negative")
        if self.reclaimed_bytes is not None and self.reclaimed_bytes < 0:
            raise InvalidArgumentError("reclaimed_bytes must be non-negative")


@dataclass(frozen=True, slots=True)
class CoordinatedBackupManifest:
    backup_id: str
    created_at: str
    target_dir: str
    record_backup: BackupDescriptor
    graph_backup: BackupDescriptor | None = None
    leases: list[MultiprocessLeaseToken] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.backup_id:
            raise InvalidArgumentError("backup_id is required")
        if not self.created_at:
            raise InvalidArgumentError("created_at is required")
        if not self.target_dir:
            raise InvalidArgumentError("target_dir is required")
