"""Private compaction and coordinated-backup helpers for storage operations."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
import shutil
from typing import Any
from uuid import uuid4

from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.graph_backends import (
    FakeGraphBackendAdapter,
    KuzuGraphBackendAdapter,
    Neo4jGraphBackendAdapter,
)
from sophiagraph.models import (
    BackupDescriptor,
    BackupManifestEntry,
    CompactionOutcome,
    CoordinatedBackupManifest,
    MemoryNamespace,
    OperatorActionRequired,
)
from sophiagraph.portability.codec import json_dumps
from sophiagraph.storage.backups import create_backup
from sophiagraph.storage.leases import acquire_write_lease, release_write_lease
from sophiagraph.storage.memory import SophiaGraphMemoryStore
from sophiagraph.storage.operation_support import (
    _prepare_directory,
    _sha256_bytes,
    _write_backup_descriptor,
)
from sophiagraph.storage.record_lifecycle import utc_now_iso
from sophiagraph.storage.sqlite import SophiaGraphSqliteStore


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
