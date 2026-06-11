from __future__ import annotations

import json
from pathlib import Path
import threading
import time

import pytest

from sophiagraph import (
    FakeGraphBackendAdapter,
    KuzuGraphBackendAdapter,
    MemoryNamespace,
    MemoryRecord,
    Neo4jGraphBackendAdapter,
    SophiaGraphMemoryStore,
    SophiaGraphSqliteStore,
    compact_store,
    coordinated_backup,
    create_backup,
    create_retention_snapshot,
    release_write_lease,
    restore_backup,
    verify_backup,
    verify_retention_snapshot,
)
from sophiagraph.storage.operations import acquire_write_lease
from sophiagraph.portability import read_bundle_snapshot, write_bundle_snapshot
from sophiagraph.portability.models import (
    MemoryBundleExportOptions,
    MemoryBundleImportOptions,
)
from sophiagraph.contracts.errors import (
    SnapshotNameConflictError,
    WriteLeaseNotHeldError,
)


def _namespace(agent_id: str = "agent") -> MemoryNamespace:
    return MemoryNamespace(tenant_id="tenant", agent_id=agent_id, graph_id="main")


def _record(record_id: str, *, agent_id: str = "agent") -> MemoryRecord:
    return MemoryRecord(
        id=record_id,
        scope=f"agent:{agent_id}",
        type="fact",
        key=record_id,
        title=record_id,
        content={"text": record_id},
        created_at="2026-06-10T00:00:00+00:00",
        updated_at="2026-06-10T00:00:00+00:00",
        namespace=_namespace(agent_id),
    )


@pytest.fixture(params=["memory", "sqlite"])
def store(request, tmp_path: Path):
    if request.param == "memory":
        instance = SophiaGraphMemoryStore()
    else:
        instance = SophiaGraphSqliteStore(tmp_path / "ops.sqlite3")
    instance.put_record(_record("rec-a"))
    instance.put_record(_record("rec-b"))
    return instance


def test_storage_operation_dtos_validate_fields() -> None:
    from sophiagraph import (
        BackupDescriptor,
        BackupManifestEntry,
        MultiprocessLeaseToken,
    )

    entry = BackupManifestEntry(
        table_group="records",
        row_count=2,
        sha256="abc",
        byte_size=42,
    )
    descriptor = BackupDescriptor(
        backup_id="bk-1",
        kind="physical_memory",
        backend_name="memory",
        created_at="2026-06-10T00:00:00+00:00",
        target_path="/tmp/backup",
        manifest_entries=[entry],
    )
    lease = MultiprocessLeaseToken(
        lease_id="lease-1",
        resource_id="store:write",
        owner="tester",
        backend_name="sqlite",
        acquired_at="2026-06-10T00:00:00+00:00",
        expires_at="2026-06-10T00:00:30+00:00",
        ttl_seconds=30,
        heartbeat_seconds=5,
    )

    assert descriptor.kind == "physical_memory"
    assert descriptor.manifest_entries[0].row_count == 2
    assert lease.owner == "tester"


def test_create_backup_and_restore_roundtrip(store, tmp_path: Path) -> None:
    backup_dir = tmp_path / f"{type(store).__name__}-backup"
    descriptor = create_backup(store, backup_dir)
    report = verify_backup(backup_dir)

    assert descriptor.manifest_entries
    assert report.verified is True

    if isinstance(store, SophiaGraphMemoryStore):
        outcome = restore_backup(SophiaGraphMemoryStore(), backup_dir)
        restored = outcome.restored_store
        assert isinstance(restored, SophiaGraphMemoryStore)
        assert restored.get_record("rec-a") is not None
        assert restored.get_record("rec-b") is not None
    else:
        target = SophiaGraphSqliteStore(tmp_path / "restored.sqlite3")
        outcome = restore_backup(target, backup_dir)
        assert outcome.restored is True
        assert target.get_record("rec-a") is not None
        assert target.get_record("rec-b") is not None


def test_tampered_backup_fails_integrity(store, tmp_path: Path) -> None:
    backup_dir = tmp_path / "tampered"
    create_backup(store, backup_dir)
    manifest_path = backup_dir / "backup_manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["manifest_entries"][0]["sha256"] = "tampered"
    manifest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    report = verify_backup(backup_dir)
    assert report.verified is False
    assert report.mismatches or report.missing_entries


def test_sqlite_online_backup_tolerates_concurrent_writer(tmp_path: Path) -> None:
    db_path = tmp_path / "live.sqlite3"
    store = SophiaGraphSqliteStore(db_path)
    store.put_record(_record("rec-before"))
    writer = SophiaGraphSqliteStore(db_path)
    started = threading.Event()
    finished = threading.Event()

    def _write_later() -> None:
        started.wait(timeout=2)
        writer.put_record(_record("rec-during"))
        finished.set()

    thread = threading.Thread(target=_write_later, daemon=True)
    thread.start()
    started.set()
    descriptor = create_backup(store, tmp_path / "backup-live")
    finished.wait(timeout=5)
    report = verify_backup(tmp_path / "backup-live")

    assert descriptor.kind == "physical_sqlite"
    assert report.verified is True
    restored = SophiaGraphSqliteStore(tmp_path / "restored-live.sqlite3")
    restore_backup(restored, tmp_path / "backup-live")
    assert restored.get_record("rec-before") is not None


def test_retention_snapshot_collision_and_verify(store, tmp_path: Path) -> None:
    namespace = _namespace()
    snapshot = create_retention_snapshot(store, name="legal-hold", namespace=namespace)

    assert snapshot.name == "legal-hold"
    assert verify_retention_snapshot(
        store, name="legal-hold", namespace=namespace
    ).verified
    with pytest.raises(SnapshotNameConflictError):
        create_retention_snapshot(store, name="legal-hold", namespace=namespace)

    bundle = store.export_snapshot(
        MemoryBundleExportOptions(
            scopes=["agent:agent"],
            include_relations=True,
        )
    )
    bundle_path = write_bundle_snapshot(bundle, tmp_path / "retention.tar.gz")
    restored_bundle = read_bundle_snapshot(bundle_path)
    if isinstance(store, SophiaGraphMemoryStore):
        target = SophiaGraphMemoryStore()
    else:
        target = SophiaGraphSqliteStore(tmp_path / "retention.sqlite3")
    target.import_snapshot(restored_bundle, MemoryBundleImportOptions())
    assert (
        target.get_retention_snapshot(name="legal-hold", namespace=namespace)
        is not None
    )


def test_list_retention_snapshots_filters_namespace(store) -> None:
    first = _namespace("alpha")
    second = _namespace("beta")
    store.put_record(_record("rec-alpha", agent_id="alpha"))
    store.put_record(_record("rec-beta", agent_id="beta"))
    create_retention_snapshot(store, name="snap-alpha", namespace=first)
    create_retention_snapshot(store, name="snap-beta", namespace=second)

    filtered = [
        item.name for item in store.list_retention_snapshots(namespaces=[first])
    ]
    assert filtered == ["snap-alpha"]


def test_compaction_outcomes_cover_backends(tmp_path: Path, monkeypatch) -> None:
    memory = SophiaGraphMemoryStore()
    sqlite_store = SophiaGraphSqliteStore(tmp_path / "compact.sqlite3")
    sqlite_store.put_record(_record("rec-compact"))
    fake = FakeGraphBackendAdapter()

    memory_outcome = compact_store(memory)
    sqlite_outcome = compact_store(sqlite_store)
    fake_outcome = compact_store(fake)

    assert memory_outcome.applied is True
    assert sqlite_outcome.backend_name == "sqlite"
    assert fake_outcome.backend_name == "fake"

    pytest.importorskip("kuzu")
    kuzu = KuzuGraphBackendAdapter(tmp_path / "compact.kuzu")
    kuzu_outcome = compact_store(kuzu)
    assert kuzu_outcome.backend_name == "kuzu"

    from sophiagraph.graph_backends import neo4j as neo4j_module

    real_import = neo4j_module.importlib.import_module

    class _Driver:
        def session(self, database=None):  # noqa: ARG002
            class _Session:
                def __enter__(self):
                    return self

                def __exit__(self, exc_type, exc, tb):  # noqa: ARG002
                    return None

                def run(self, statement, params=None):  # noqa: ARG002
                    class _Result:
                        def __iter__(self):
                            return iter([])

                    return _Result()

            return _Session()

        def close(self) -> None:
            return None

    class _GraphDatabase:
        @staticmethod
        def driver(uri, auth=None):  # noqa: ARG002
            return _Driver()

    def _fake_import(name: str):
        if name == "neo4j":
            return type("_Module", (), {"GraphDatabase": _GraphDatabase})()
        return real_import(name)

    monkeypatch.setattr(neo4j_module.importlib, "import_module", _fake_import)
    neo4j = Neo4jGraphBackendAdapter("neo4j://fixture")
    neo4j_outcome = compact_store(neo4j)
    assert neo4j_outcome.operator_action_required is not None
    assert "neo4j-admin database copy --compact-node-store" in (
        neo4j_outcome.operator_action_required.command
    )


def test_coordinated_backup_covers_sqlite_and_fake(tmp_path: Path) -> None:
    store = SophiaGraphSqliteStore(tmp_path / "coord.sqlite3")
    store.put_record(_record("rec-coord"))
    fake = FakeGraphBackendAdapter()
    manifest = coordinated_backup(store, fake, tmp_path / "coordinated")

    assert manifest.record_backup.backend_name == "sqlite"
    assert manifest.graph_backup is not None
    assert manifest.graph_backup.backend_name == "fake"
    assert (tmp_path / "coordinated" / "coordinated-backup.json").is_file()


def test_coordinated_backup_raises_when_store_lease_is_held(tmp_path: Path) -> None:
    store = SophiaGraphSqliteStore(tmp_path / "coord-blocked.sqlite3")
    store.put_record(_record("rec-coord-blocked"))
    lease = acquire_write_lease(
        store,
        owner="blocked-owner",
        ttl_seconds=5,
        heartbeat_seconds=10,
    )
    try:
        with pytest.raises(WriteLeaseNotHeldError):
            coordinated_backup(store, FakeGraphBackendAdapter(), tmp_path / "blocked")
    finally:
        time.sleep(0.1)
        release_write_lease(lease, store=store)
