"""Typed storage-operations helpers for backups, leases, snapshots, and compaction."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
import shutil
import sqlite3
import threading
from typing import Any
from uuid import uuid4

from sophiagraph.contracts.errors import (
    BackupIntegrityError,
    InvalidArgumentError,
    SnapshotNameConflictError,
    WriteLeaseExpiredError,
    WriteLeaseNotHeldError,
)
from sophiagraph.graph_backends import (
    FakeGraphBackendAdapter,
    KuzuGraphBackendAdapter,
    Neo4jGraphBackendAdapter,
)
from sophiagraph.models import (
    BackupDescriptor,
    BackupIntegrityReport,
    BackupManifestEntry,
    CompactionOutcome,
    CompactionPlan,
    CoordinatedBackupManifest,
    MemoryNamespace,
    MultiprocessLeaseToken,
    OperatorActionRequired,
    RestoreOptions,
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
from sophiagraph.storage.record_lifecycle import utc_now_iso
from sophiagraph.storage.memory import SophiaGraphMemoryStore
from sophiagraph.storage.sqlite import SophiaGraphSqliteStore

_LEASE_REGISTRY_LOCK = threading.Lock()
_LEASE_HEARTBEATS: dict[str, threading.Event] = {}
_MEMORY_WRITE_LEASES: dict[str, dict[str, Any]] = {}
_DEFAULT_RESOURCE_ID = "store:write"


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


def acquire_write_lease(
    store: SophiaGraphMemoryStore | SophiaGraphSqliteStore,
    *,
    owner: str,
    ttl_seconds: int = 30,
    heartbeat_seconds: int = 5,
) -> MultiprocessLeaseToken:
    if not owner:
        raise InvalidArgumentError("owner is required")
    if ttl_seconds <= 0 or heartbeat_seconds <= 0:
        raise InvalidArgumentError("lease durations must be positive")
    if isinstance(store, SophiaGraphSqliteStore):
        token = _acquire_sqlite_lease(
            store,
            owner=owner,
            ttl_seconds=ttl_seconds,
            heartbeat_seconds=heartbeat_seconds,
        )
    elif isinstance(store, SophiaGraphMemoryStore):
        token = _acquire_memory_lease(
            owner=owner,
            ttl_seconds=ttl_seconds,
            heartbeat_seconds=heartbeat_seconds,
        )
    else:
        raise InvalidArgumentError("unsupported store type for lease")
    _start_lease_heartbeat(token, store)
    return token


def release_write_lease(
    lease: MultiprocessLeaseToken,
    *,
    store: SophiaGraphMemoryStore | SophiaGraphSqliteStore,
) -> None:
    _stop_lease_heartbeat(lease.lease_id)
    if isinstance(store, SophiaGraphSqliteStore):
        _release_sqlite_lease(store, lease)
        return
    if isinstance(store, SophiaGraphMemoryStore):
        _release_memory_lease(lease)
        return
    raise InvalidArgumentError("unsupported store type for lease release")


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


def compact_store(
    target: SophiaGraphMemoryStore
    | SophiaGraphSqliteStore
    | KuzuGraphBackendAdapter
    | FakeGraphBackendAdapter
    | Neo4jGraphBackendAdapter,
    *,
    options: dict[str, Any] | None = None,
) -> CompactionOutcome:
    del options
    if isinstance(target, SophiaGraphMemoryStore):
        return CompactionOutcome(
            backend_name="memory",
            applied=True,
            bytes_before=0,
            bytes_after=0,
            reclaimed_bytes=0,
            notes={"strategy": "noop"},
        )
    if isinstance(target, SophiaGraphSqliteStore):
        before = target.db_path.stat().st_size if target.db_path.exists() else 0
        with target._write_connection() as conn:  # noqa: SLF001
            conn.execute("PRAGMA incremental_vacuum")
        after = target.db_path.stat().st_size if target.db_path.exists() else before
        return CompactionOutcome(
            backend_name="sqlite",
            applied=True,
            bytes_before=before,
            bytes_after=after,
            reclaimed_bytes=max(0, before - after),
            notes={"strategy": "incremental_vacuum"},
        )
    if isinstance(target, FakeGraphBackendAdapter):
        return CompactionOutcome(
            backend_name="fake",
            applied=True,
            bytes_before=0,
            bytes_after=0,
            reclaimed_bytes=0,
            notes={"strategy": "noop"},
        )
    if isinstance(target, KuzuGraphBackendAdapter):
        before = target._db_path.stat().st_size if target._db_path.exists() else 0  # noqa: SLF001
        target._execute("CHECKPOINT;")  # noqa: SLF001
        after = target._db_path.stat().st_size if target._db_path.exists() else before  # noqa: SLF001
        return CompactionOutcome(
            backend_name="kuzu",
            applied=True,
            bytes_before=before,
            bytes_after=after,
            reclaimed_bytes=max(0, before - after),
            notes={"strategy": "checkpoint"},
        )
    if isinstance(target, Neo4jGraphBackendAdapter):
        action = OperatorActionRequired(
            backend_name="neo4j",
            action="compact_database_copy",
            command="neo4j-admin database copy --compact-node-store <database> <database>-compacted",
            reason="Neo4j compaction is operator-owned outside the substrate runtime.",
        )
        return CompactionOutcome(
            backend_name="neo4j",
            applied=False,
            operator_action_required=action,
            notes={"strategy": "operator_delegation"},
        )
    raise InvalidArgumentError("unsupported compaction target")


def coordinated_backup(
    store: SophiaGraphSqliteStore,
    graph_backend: FakeGraphBackendAdapter | KuzuGraphBackendAdapter,
    target_dir: str | Path,
    *,
    namespaces: list[MemoryNamespace] | None = None,
) -> CoordinatedBackupManifest:
    target = _prepare_directory(target_dir)
    lease = acquire_write_lease(
        store,
        owner=f"coordinated-backup:{uuid4()}",
        ttl_seconds=30,
        heartbeat_seconds=5,
    )
    try:
        record_backup = create_backup(
            store, target / "record-store", namespaces=namespaces
        )
        graph_backup = _backup_graph_backend(graph_backend, target / "graph-backend")
        manifest = CoordinatedBackupManifest(
            backup_id=str(uuid4()),
            created_at=utc_now_iso(),
            target_dir=str(target),
            record_backup=record_backup,
            graph_backup=graph_backup,
            leases=[lease],
        )
        manifest_path = target / "coordinated-backup.json"
        manifest_path.write_text(
            json_dumps(
                {
                    "backup_id": manifest.backup_id,
                    "created_at": manifest.created_at,
                    "target_dir": manifest.target_dir,
                    "record_backup": manifest.record_backup.to_dict(),
                    "graph_backup": manifest.graph_backup.to_dict()
                    if manifest.graph_backup is not None
                    else None,
                    "leases": [asdict(item) for item in manifest.leases],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        return manifest
    finally:
        release_write_lease(lease, store=store)


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


def _acquire_sqlite_lease(
    store: SophiaGraphSqliteStore,
    *,
    owner: str,
    ttl_seconds: int,
    heartbeat_seconds: int,
) -> MultiprocessLeaseToken:
    now = _utc_now()
    expires_at = now + timedelta(seconds=ttl_seconds)
    lease_id = str(uuid4())
    with store._write_connection() as conn:  # noqa: SLF001
        row = conn.execute(
            """
            SELECT lease_id, owner, expires_at
              FROM sophiagraph_write_leases
             WHERE resource_id = ?
            """,
            (_DEFAULT_RESOURCE_ID,),
        ).fetchone()
        if row is not None and _parse_dt(str(row["expires_at"])) > now:
            raise WriteLeaseNotHeldError(
                "write lease is already held",
                details={
                    "resource_id": _DEFAULT_RESOURCE_ID,
                    "owner": row["owner"],
                },
            )
        conn.execute(
            """
            INSERT OR REPLACE INTO sophiagraph_write_leases(
                resource_id, lease_id, owner, acquired_at, expires_at, ttl_seconds, heartbeat_seconds
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _DEFAULT_RESOURCE_ID,
                lease_id,
                owner,
                _isoformat(now),
                _isoformat(expires_at),
                ttl_seconds,
                heartbeat_seconds,
            ),
        )
    return MultiprocessLeaseToken(
        lease_id=lease_id,
        resource_id=_DEFAULT_RESOURCE_ID,
        owner=owner,
        backend_name="sqlite",
        acquired_at=_isoformat(now),
        expires_at=_isoformat(expires_at),
        ttl_seconds=ttl_seconds,
        heartbeat_seconds=heartbeat_seconds,
        metadata={"db_path": str(store.db_path)},
    )


def _release_sqlite_lease(
    store: SophiaGraphSqliteStore,
    lease: MultiprocessLeaseToken,
) -> None:
    with store._write_connection() as conn:  # noqa: SLF001
        row = conn.execute(
            """
            SELECT lease_id, owner, expires_at
              FROM sophiagraph_write_leases
             WHERE resource_id = ?
            """,
            (lease.resource_id,),
        ).fetchone()
        if row is None or str(row["lease_id"]) != lease.lease_id:
            raise WriteLeaseNotHeldError(
                "write lease is not currently held",
                details={"lease_id": lease.lease_id},
            )
        if _parse_dt(str(row["expires_at"])) <= _utc_now():
            conn.execute(
                "DELETE FROM sophiagraph_write_leases WHERE resource_id = ?",
                (lease.resource_id,),
            )
            raise WriteLeaseExpiredError(
                "write lease expired before release",
                details={"lease_id": lease.lease_id},
            )
        conn.execute(
            "DELETE FROM sophiagraph_write_leases WHERE resource_id = ?",
            (lease.resource_id,),
        )


def _acquire_memory_lease(
    *,
    owner: str,
    ttl_seconds: int,
    heartbeat_seconds: int,
) -> MultiprocessLeaseToken:
    now = _utc_now()
    expires_at = now + timedelta(seconds=ttl_seconds)
    lease_id = str(uuid4())
    with _LEASE_REGISTRY_LOCK:
        current = _MEMORY_WRITE_LEASES.get(_DEFAULT_RESOURCE_ID)
        if current is not None and _parse_dt(str(current["expires_at"])) > now:
            raise WriteLeaseNotHeldError(
                "write lease is already held",
                details={
                    "resource_id": _DEFAULT_RESOURCE_ID,
                    "owner": current["owner"],
                },
            )
        _MEMORY_WRITE_LEASES[_DEFAULT_RESOURCE_ID] = {
            "lease_id": lease_id,
            "owner": owner,
            "expires_at": _isoformat(expires_at),
            "ttl_seconds": ttl_seconds,
            "heartbeat_seconds": heartbeat_seconds,
        }
    return MultiprocessLeaseToken(
        lease_id=lease_id,
        resource_id=_DEFAULT_RESOURCE_ID,
        owner=owner,
        backend_name="memory",
        acquired_at=_isoformat(now),
        expires_at=_isoformat(expires_at),
        ttl_seconds=ttl_seconds,
        heartbeat_seconds=heartbeat_seconds,
    )


def _release_memory_lease(lease: MultiprocessLeaseToken) -> None:
    with _LEASE_REGISTRY_LOCK:
        current = _MEMORY_WRITE_LEASES.get(lease.resource_id)
        if current is None or str(current["lease_id"]) != lease.lease_id:
            raise WriteLeaseNotHeldError(
                "write lease is not currently held",
                details={"lease_id": lease.lease_id},
            )
        if _parse_dt(str(current["expires_at"])) <= _utc_now():
            _MEMORY_WRITE_LEASES.pop(lease.resource_id, None)
            raise WriteLeaseExpiredError(
                "write lease expired before release",
                details={"lease_id": lease.lease_id},
            )
        _MEMORY_WRITE_LEASES.pop(lease.resource_id, None)


def _start_lease_heartbeat(
    lease: MultiprocessLeaseToken,
    store: SophiaGraphMemoryStore | SophiaGraphSqliteStore,
) -> None:
    stop = threading.Event()
    with _LEASE_REGISTRY_LOCK:
        _LEASE_HEARTBEATS[lease.lease_id] = stop

    def _run() -> None:
        while not stop.wait(float(lease.heartbeat_seconds)):
            try:
                _heartbeat_lease(lease, store)
            except Exception:
                stop.set()

    thread = threading.Thread(
        target=_run,
        name=f"sophiagraph-lease-{lease.lease_id}",
        daemon=True,
    )
    thread.start()


def _stop_lease_heartbeat(lease_id: str) -> None:
    with _LEASE_REGISTRY_LOCK:
        stop = _LEASE_HEARTBEATS.pop(lease_id, None)
    if stop is not None:
        stop.set()


def _heartbeat_lease(
    lease: MultiprocessLeaseToken,
    store: SophiaGraphMemoryStore | SophiaGraphSqliteStore,
) -> None:
    new_expiry = _utc_now() + timedelta(seconds=lease.ttl_seconds)
    if isinstance(store, SophiaGraphSqliteStore):
        with store._write_connection() as conn:  # noqa: SLF001
            row = conn.execute(
                """
                SELECT lease_id, expires_at FROM sophiagraph_write_leases
                 WHERE resource_id = ?
                """,
                (lease.resource_id,),
            ).fetchone()
            if row is None or str(row["lease_id"]) != lease.lease_id:
                raise WriteLeaseNotHeldError("write lease is not currently held")
            if _parse_dt(str(row["expires_at"])) <= _utc_now():
                raise WriteLeaseExpiredError("write lease expired during heartbeat")
            conn.execute(
                """
                UPDATE sophiagraph_write_leases
                   SET expires_at = ?
                 WHERE resource_id = ? AND lease_id = ?
                """,
                (_isoformat(new_expiry), lease.resource_id, lease.lease_id),
            )
        return
    with _LEASE_REGISTRY_LOCK:
        current = _MEMORY_WRITE_LEASES.get(lease.resource_id)
        if current is None or str(current["lease_id"]) != lease.lease_id:
            raise WriteLeaseNotHeldError("write lease is not currently held")
        if _parse_dt(str(current["expires_at"])) <= _utc_now():
            raise WriteLeaseExpiredError("write lease expired during heartbeat")
        current["expires_at"] = _isoformat(new_expiry)


def _backup_graph_backend(
    graph_backend: FakeGraphBackendAdapter | KuzuGraphBackendAdapter,
    target_dir: Path,
) -> BackupDescriptor:
    target_dir.mkdir(parents=True, exist_ok=True)
    created_at = utc_now_iso()
    if isinstance(graph_backend, FakeGraphBackendAdapter):
        payload = {
            "capabilities": asdict(graph_backend.capabilities()),
            "batch": asdict(graph_backend._batch)
            if graph_backend._batch is not None
            else None,  # noqa: SLF001
        }
        payload_bytes = json_dumps(payload, indent=2).encode("utf-8")
        out_path = target_dir / "graph.json"
        out_path.write_bytes(payload_bytes)
        entry = BackupManifestEntry(
            table_group="fake_graph_backend",
            row_count=0 if payload["batch"] is None else 1,
            sha256=_sha256_bytes(payload_bytes),
            byte_size=len(payload_bytes),
        )
        descriptor = BackupDescriptor(
            backup_id=str(uuid4()),
            kind="coordinated",
            backend_name="fake",
            created_at=created_at,
            target_path=str(target_dir),
            manifest_entries=[entry],
            metadata={"filename": out_path.name},
        )
        _write_backup_descriptor(target_dir, descriptor)
        return descriptor
    graph_backend._execute("CHECKPOINT;")  # noqa: SLF001
    out_path = target_dir / graph_backend._db_path.name  # noqa: SLF001
    shutil.copy2(graph_backend._db_path, out_path)  # noqa: SLF001
    payload = out_path.read_bytes()
    entry = BackupManifestEntry(
        table_group="kuzu_graph_backend",
        row_count=1,
        sha256=_sha256_bytes(payload),
        byte_size=len(payload),
    )
    descriptor = BackupDescriptor(
        backup_id=str(uuid4()),
        kind="coordinated",
        backend_name="kuzu",
        created_at=created_at,
        target_path=str(target_dir),
        manifest_entries=[entry],
        metadata={"filename": out_path.name},
    )
    _write_backup_descriptor(target_dir, descriptor)
    return descriptor


def _write_backup_descriptor(target_dir: Path, descriptor: BackupDescriptor) -> None:
    (target_dir / "backup_manifest.json").write_text(
        json_dumps(descriptor.to_dict(), indent=2),
        encoding="utf-8",
    )


def _read_backup_descriptor(source_dir: Path) -> BackupDescriptor:
    manifest_path = source_dir / "backup_manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise InvalidArgumentError("backup manifest must decode to an object")
    return BackupDescriptor.from_dict(payload)


def _prepare_directory(target_path: str | Path) -> Path:
    target_dir = Path(target_path).expanduser().resolve(strict=False)
    target_dir.mkdir(parents=True, exist_ok=True)
    return target_dir


def _sha256_bytes(data: bytes) -> str:
    return sha256(data).hexdigest()


def _sqlite_wal_frame_position(db_path: Path) -> int:
    wal_path = db_path.with_name(f"{db_path.name}-wal")
    if not wal_path.exists():
        return 0
    with sqlite3.connect(db_path) as conn:
        page_size = int(conn.execute("PRAGMA page_size").fetchone()[0])
    if page_size <= 0:
        return 0
    wal_size = wal_path.stat().st_size
    return max(0, wal_size // page_size)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _isoformat(value: datetime) -> str:
    return value.isoformat()


def _parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


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
