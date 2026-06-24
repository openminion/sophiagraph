"""Private backup, restore, and retention helpers for storage operations."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
import shutil
import sqlite3
from typing import Any
from uuid import uuid4

from sophiagraph.contracts.errors import (
    BackupIntegrityError,
    InvalidArgumentError,
    SnapshotNameConflictError,
)
from sophiagraph.models import (
    BackupDescriptor,
    BackupIntegrityReport,
    BackupManifestEntry,
    MemoryNamespace,
    RestoreOutcome,
    RetentionSnapshot,
)
from sophiagraph.portability import read_bundle_snapshot, write_bundle_snapshot
from sophiagraph.portability.codec import json_dumps
from sophiagraph.portability.models import (
    MemoryBundleExportOptions,
    MemoryBundleImportOptions,
    MemoryBundleSnapshot,
)
from sophiagraph.storage.memory import SophiaGraphMemoryStore
from sophiagraph.storage.operation_support import (
    _prepare_directory,
    _read_backup_descriptor,
    _sha256_bytes,
    _sqlite_wal_frame_position,
    _write_backup_descriptor,
)
from sophiagraph.storage.record_lifecycle import utc_now_iso
from sophiagraph.storage.sqlite import SophiaGraphSqliteStore


def create_backup(
    store: SophiaGraphMemoryStore | SophiaGraphSqliteStore,
    target_path: str | Path,
    *,
    namespaces: list[MemoryNamespace] | None = None,
) -> BackupDescriptor:
    target_dir = _prepare_directory(target_path)
    if isinstance(store, SophiaGraphSqliteStore):
        return _create_sqlite_backup(store, target_dir)
    if isinstance(store, SophiaGraphMemoryStore):
        return _create_memory_backup(store, target_dir, namespaces=namespaces)
    raise InvalidArgumentError("unsupported store type for backup")


def restore_backup(
    target_store: SophiaGraphMemoryStore | SophiaGraphSqliteStore,
    source_path: str | Path,
    *,
    verify: bool = True,
) -> RestoreOutcome:
    source_dir = Path(source_path).expanduser().resolve(strict=False)
    descriptor = _read_backup_descriptor(source_dir)
    report = verify_backup(source_dir) if verify else None
    if report is not None and not report.verified:
        raise BackupIntegrityError(
            "backup integrity verification failed",
            details=report.details,
        )
    if descriptor.kind == "physical_sqlite":
        if not isinstance(target_store, SophiaGraphSqliteStore):
            raise InvalidArgumentError("physical_sqlite backup requires SQLite target")
        backup_db = source_dir / "store.sqlite3"
        shutil.copy2(backup_db, target_store.db_path)
        return RestoreOutcome(
            backup_id=descriptor.backup_id,
            restored=True,
            backend_name="sqlite",
            restored_path=str(target_store.db_path),
            report=report,
            restored_store=target_store,
        )
    if descriptor.kind == "physical_memory":
        bundle = read_bundle_snapshot(source_dir / "store.bundle.tar.gz")
        restored = SophiaGraphMemoryStore(
            integrity_hash_enabled=getattr(
                target_store, "_integrity_hash_enabled", False
            )
        )
        restored.import_snapshot(bundle, MemoryBundleImportOptions())
        return RestoreOutcome(
            backup_id=descriptor.backup_id,
            restored=True,
            backend_name="memory",
            restored_path=str(source_dir / "store.bundle.tar.gz"),
            report=report,
            restored_store=restored,
        )
    raise InvalidArgumentError(f"unsupported backup kind: {descriptor.kind!r}")


def verify_backup(source_path: str | Path) -> BackupIntegrityReport:
    source_dir = Path(source_path).expanduser().resolve(strict=False)
    descriptor = _read_backup_descriptor(source_dir)
    if descriptor.kind == "physical_sqlite":
        entries = _sqlite_table_group_entries(source_dir / "store.sqlite3")
    elif descriptor.kind == "physical_memory":
        entries = _bundle_archive_entries(source_dir / "store.bundle.tar.gz")
    else:
        raise InvalidArgumentError(f"unsupported backup kind: {descriptor.kind!r}")
    expected = {entry.table_group: entry for entry in descriptor.manifest_entries}
    actual = {entry.table_group: entry for entry in entries}
    mismatches: list[str] = []
    missing: list[str] = []
    for group, expected_entry in expected.items():
        actual_entry = actual.get(group)
        if actual_entry is None:
            missing.append(group)
            continue
        if (
            actual_entry.row_count != expected_entry.row_count
            or actual_entry.sha256 != expected_entry.sha256
            or actual_entry.byte_size != expected_entry.byte_size
        ):
            mismatches.append(group)
    verified = not mismatches and not missing
    return BackupIntegrityReport(
        backup_id=descriptor.backup_id,
        verified=verified,
        checked_entries=len(expected),
        mismatches=mismatches,
        missing_entries=missing,
        details={
            "kind": descriptor.kind,
            "source_path": str(source_dir),
        },
    )


def create_retention_snapshot(
    store: SophiaGraphMemoryStore | SophiaGraphSqliteStore,
    *,
    name: str,
    namespace: MemoryNamespace,
    as_of_cursor: int | None = None,
    overwrite: bool = False,
) -> RetentionSnapshot:
    if not name:
        raise InvalidArgumentError("name is required")
    existing = store.get_retention_snapshot(name=name, namespace=namespace)
    if existing is not None and not overwrite:
        raise SnapshotNameConflictError(
            f"retention snapshot already exists: {name}",
            details={"name": name, "namespace": namespace.as_dict()},
        )
    snapshot_bundle = _bundle_snapshot_for_namespace(store, namespace)
    payload = _snapshot_to_payload(snapshot_bundle)
    payload_bytes = json_dumps(payload).encode("utf-8")
    descriptor = BackupDescriptor(
        backup_id=f"snapshot-{uuid4()}",
        kind="physical_memory",
        backend_name="retention_snapshot",
        created_at=utc_now_iso(),
        target_path=f"snapshot:{name}",
        manifest_entries=[
            BackupManifestEntry(
                table_group="snapshot_payload",
                row_count=len(snapshot_bundle.records),
                sha256=_sha256_bytes(payload_bytes),
                byte_size=len(payload_bytes),
            )
        ],
        namespaces=[namespace],
        metadata={"retention_snapshot": True},
    )
    snapshot = RetentionSnapshot(
        snapshot_id=str(uuid4()),
        name=name,
        namespace=namespace,
        created_at=descriptor.created_at,
        as_of_cursor=as_of_cursor,
        backup_descriptor=descriptor,
        payload=payload,
    )
    store.put_retention_snapshot(snapshot)
    return snapshot


def list_retention_snapshots(
    store: SophiaGraphMemoryStore | SophiaGraphSqliteStore,
    *,
    namespace: MemoryNamespace | None = None,
) -> list[RetentionSnapshot]:
    namespaces = [namespace] if namespace is not None else None
    return store.list_retention_snapshots(namespaces=namespaces)


def verify_retention_snapshot(
    store: SophiaGraphMemoryStore | SophiaGraphSqliteStore,
    *,
    name: str,
    namespace: MemoryNamespace,
) -> BackupIntegrityReport:
    snapshot = store.get_retention_snapshot(name=name, namespace=namespace)
    if snapshot is None:
        raise InvalidArgumentError(f"retention snapshot not found: {name}")
    actual_bytes = json_dumps(snapshot.payload).encode("utf-8")
    expected = snapshot.backup_descriptor.manifest_entries[0]
    mismatches = []
    if expected.sha256 != _sha256_bytes(actual_bytes) or expected.byte_size != len(
        actual_bytes
    ):
        mismatches.append(expected.table_group)
    return BackupIntegrityReport(
        backup_id=snapshot.backup_descriptor.backup_id,
        verified=not mismatches,
        checked_entries=1,
        mismatches=mismatches,
        details={"snapshot_id": snapshot.snapshot_id, "name": snapshot.name},
    )


def _create_sqlite_backup(
    store: SophiaGraphSqliteStore,
    target_dir: Path,
) -> BackupDescriptor:
    backup_path = target_dir / "store.sqlite3"
    wal_frame_position = _sqlite_wal_frame_position(store.db_path)
    store.backup(backup_path)
    entries = _sqlite_table_group_entries(backup_path)
    descriptor = BackupDescriptor(
        backup_id=str(uuid4()),
        kind="physical_sqlite",
        backend_name="sqlite",
        created_at=utc_now_iso(),
        target_path=str(target_dir),
        manifest_entries=entries,
        wal_frame_position=wal_frame_position,
        metadata={"db_filename": backup_path.name},
    )
    _write_backup_descriptor(target_dir, descriptor)
    return descriptor


def _create_memory_backup(
    store: SophiaGraphMemoryStore,
    target_dir: Path,
    *,
    namespaces: list[MemoryNamespace] | None,
) -> BackupDescriptor:
    snapshot = _bundle_snapshot_for_memory_store(store, namespaces)
    bundle_path = write_bundle_snapshot(snapshot, target_dir / "store.bundle.tar.gz")
    entries = _bundle_archive_entries(bundle_path)
    descriptor = BackupDescriptor(
        backup_id=str(uuid4()),
        kind="physical_memory",
        backend_name="memory",
        created_at=utc_now_iso(),
        target_path=str(target_dir),
        manifest_entries=entries,
        namespaces=namespaces,
        metadata={"bundle_filename": bundle_path.name},
    )
    _write_backup_descriptor(target_dir, descriptor)
    return descriptor


def _bundle_snapshot_for_memory_store(
    store: SophiaGraphMemoryStore,
    namespaces: list[MemoryNamespace] | None,
) -> MemoryBundleSnapshot:
    scopes = sorted({record.scope for record in store._records.values()})  # noqa: SLF001
    return store.export_snapshot(
        MemoryBundleExportOptions(
            scopes=scopes,
            include_candidates=True,
            include_relations=True,
            include_tier_history=True,
            include_memory_blocks=True,
            include_ontologies=True,
            include_embedding_lifecycle=True,
            namespaces=namespaces,
        )
    )


def _bundle_snapshot_for_namespace(
    store: SophiaGraphMemoryStore | SophiaGraphSqliteStore,
    namespace: MemoryNamespace,
) -> MemoryBundleSnapshot:
    scopes = _scopes_for_namespace(store, namespace)
    return store.export_snapshot(
        MemoryBundleExportOptions(
            scopes=scopes,
            include_candidates=True,
            include_relations=True,
            include_tier_history=True,
            include_memory_blocks=True,
            include_ontologies=True,
            include_embedding_lifecycle=True,
            namespaces=[namespace],
        )
    )


def _scopes_for_namespace(
    store: SophiaGraphMemoryStore | SophiaGraphSqliteStore,
    namespace: MemoryNamespace,
) -> list[str]:
    if isinstance(store, SophiaGraphMemoryStore):
        return sorted(
            {
                record.scope
                for record in store._records.values()  # noqa: SLF001
                if record.effective_namespace.matches(namespace)
            }
        )
    clauses = []
    params: list[Any] = []
    for field, value in namespace.as_dict().items():
        clauses.append(f"{field} = ?")
        params.append(value)
    query = "SELECT DISTINCT scope FROM sophiagraph_records"
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY scope ASC"
    with store._connect() as conn:  # noqa: SLF001
        rows = conn.execute(query, params).fetchall()
    return [str(row["scope"]) for row in rows]


def _snapshot_to_payload(snapshot: MemoryBundleSnapshot) -> dict[str, Any]:
    return {
        "manifest": dict(snapshot.manifest),
        "records": [asdict(record) for record in snapshot.records],
        "candidates": [asdict(candidate) for candidate in snapshot.candidates],
        "relations": [asdict(relation) for relation in snapshot.relations],
        "tier_transitions": [asdict(item) for item in snapshot.tier_transitions],
        "memory_blocks": [asdict(block) for block in snapshot.memory_blocks],
        "ontologies": [asdict(item) for item in snapshot.ontologies],
        "active_embedding_model_sets": [
            item.to_dict() for item in snapshot.active_embedding_model_sets
        ],
        "retention_snapshots": [
            item.to_dict() for item in snapshot.retention_snapshots
        ],
    }


def _bundle_archive_entries(bundle_path: Path) -> list[BackupManifestEntry]:
    snapshot = read_bundle_snapshot(bundle_path)
    files = dict(snapshot.manifest.get("files", {}))
    counts = dict(snapshot.manifest.get("counts", {}))
    name_map = {
        "records.jsonl": "records",
        "candidates.jsonl": "candidates",
        "relations.jsonl": "relations",
        "tier_transitions.jsonl": "tier_transitions",
        "memory_blocks.jsonl": "memory_blocks",
        "ontologies.jsonl": "ontologies",
        "embedding_lifecycle.jsonl": "active_embedding_model_sets",
        "retention_snapshots.jsonl": "retention_snapshots",
    }
    entries: list[BackupManifestEntry] = []
    for filename, group in name_map.items():
        meta = files.get(filename)
        if not isinstance(meta, dict):
            entries.append(
                BackupManifestEntry(
                    table_group=group,
                    row_count=int(counts.get(group, 0) or 0),
                    sha256=_sha256_bytes(b""),
                    byte_size=0,
                )
            )
            continue
        entries.append(
            BackupManifestEntry(
                table_group=group,
                row_count=int(counts.get(group, 0) or 0),
                sha256=str(meta.get("sha256", "")),
                byte_size=int(meta.get("byte_count", 0) or 0),
            )
        )
    entries.sort(key=lambda item: item.table_group)
    return entries


def _sqlite_table_group_entries(db_path: Path) -> list[BackupManifestEntry]:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        tables = [
            str(row["name"])
            for row in conn.execute(
                """
                SELECT name
                  FROM sqlite_master
                 WHERE type = 'table' AND name LIKE 'sophiagraph_%'
                 ORDER BY name ASC
                """
            ).fetchall()
        ]
        entries: list[BackupManifestEntry] = []
        for table in tables:
            columns = [
                str(item["name"])
                for item in conn.execute(f"PRAGMA table_info({table})").fetchall()
            ]
            order_by = ""
            if columns:
                quoted = ", ".join(f'"{column}"' for column in columns)
                order_by = f" ORDER BY {quoted}"
            rows = conn.execute(f"SELECT * FROM {table}{order_by}").fetchall()
            payload = [{key: row[key] for key in row.keys()} for row in rows]
            payload_bytes = json_dumps(payload).encode("utf-8")
            entries.append(
                BackupManifestEntry(
                    table_group=table,
                    row_count=len(payload),
                    sha256=_sha256_bytes(payload_bytes),
                    byte_size=len(payload_bytes),
                )
            )
        return entries
