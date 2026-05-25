from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import sqlite3

import pytest

from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.models import (
    MemoryCandidate,
    MemoryNamespace,
    MemoryRecord,
    MemoryRelation,
    MemoryTierTransition,
)
from sophiagraph.portability.models import (
    MemoryBundleExportOptions,
    MemoryBundleImportOptions,
)
from sophiagraph.query import CandidateListOptions, ListQueryOptions, SearchQueryOptions
from sophiagraph.storage import SophiaGraphSqliteStore
from sophiagraph.storage.sqlite_portability import SqlitePortabilityMixin
from sophiagraph.storage.sqlite_support import SCHEMA_VERSION, namespace_filter_sql


def _record(
    record_id: str = "rec-1",
    *,
    created_at: str = "2026-05-22T00:00:00+00:00",
    scope: str = "agent:test",
    namespace: MemoryNamespace | None = None,
) -> MemoryRecord:
    return MemoryRecord(
        id=record_id,
        scope=scope,
        type="fact",
        key="project:alpha",
        title="Alpha fact",
        content={"text": "alpha launched"},
        created_at=created_at,
        updated_at=created_at,
        source="validated",
        confidence=0.9,
        event_time=created_at,
        namespace=namespace,
    )


def test_sqlite_store_record_round_trip(tmp_path) -> None:
    store = SophiaGraphSqliteStore(tmp_path / "sophiagraph.sqlite3")
    assert isinstance(store, SqlitePortabilityMixin)
    record = _record()
    store.put_record(record)

    fetched = store.get_record(record.id)
    assert fetched is not None
    assert fetched.id == record.id
    assert fetched.content == record.content

    listed = store.list_records(ListQueryOptions(scopes=["agent:test"]))
    assert [item.id for item in listed] == [record.id]

    searched = store.search_records(
        SearchQueryOptions(query="launched", scopes=["agent:test"])
    )
    assert [item.id for item in searched] == [record.id]


def test_sqlite_schema_uses_sophiagraph_table_names(tmp_path) -> None:
    db_path = tmp_path / "sophiagraph.sqlite3"
    SophiaGraphSqliteStore(db_path)

    with sqlite3.connect(db_path) as conn:
        table_names = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }

    assert {
        "sophiagraph_records",
        "sophiagraph_relations",
        "sophiagraph_links",
        "sophiagraph_candidates",
        "sophiagraph_tier_transitions",
    } <= table_names
    assert not any(name.startswith("knowledge_") for name in table_names)


def test_sqlite_support_owns_schema_version_and_namespace_filters(tmp_path) -> None:
    db_path = tmp_path / "sophiagraph.sqlite3"
    SophiaGraphSqliteStore(db_path)

    with sqlite3.connect(db_path) as conn:
        schema_version = conn.execute("PRAGMA user_version").fetchone()[0]

    sql, params = namespace_filter_sql(
        [MemoryNamespace(agent_id="agent-a", graph_id="main")]
    )

    assert schema_version == SCHEMA_VERSION
    assert "agent_id = ?" in sql
    assert "graph_id = ?" in sql
    assert params == ["agent-a", "main"]


def test_sqlite_store_configures_write_safety_pragmas(tmp_path) -> None:
    store = SophiaGraphSqliteStore(tmp_path / "sophiagraph.sqlite3")

    with store._connect() as conn:
        journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        busy_timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]
        synchronous = conn.execute("PRAGMA synchronous").fetchone()[0]

    assert str(journal_mode).lower() == "wal"
    assert busy_timeout == 5000
    assert synchronous == 1


def test_sqlite_store_writes_while_reader_transaction_is_open(tmp_path) -> None:
    db_path = tmp_path / "sophiagraph.sqlite3"
    store = SophiaGraphSqliteStore(db_path)
    store.put_record(_record("rec-initial"))

    reader = sqlite3.connect(db_path, isolation_level=None)
    try:
        reader.execute("BEGIN")
        assert (
            reader.execute("SELECT COUNT(*) FROM sophiagraph_records").fetchone()[0]
            == 1
        )
        store.put_record(_record("rec-while-reader"))
        reader.execute("COMMIT")
    finally:
        reader.close()

    assert store.get_record("rec-while-reader") is not None


def test_sqlite_store_accepts_multiple_writer_instances(tmp_path) -> None:
    db_path = tmp_path / "sophiagraph.sqlite3"
    SophiaGraphSqliteStore(db_path)

    def write_record(index: int) -> str:
        writer = SophiaGraphSqliteStore(db_path)
        record_id = f"rec-concurrent-{index}"
        writer.put_record(_record(record_id))
        return record_id

    with ThreadPoolExecutor(max_workers=4) as executor:
        record_ids = list(executor.map(write_record, range(12)))

    store = SophiaGraphSqliteStore(db_path)
    listed = store.list_records(ListQueryOptions(scopes=["agent:test"], limit=20))

    assert {record.id for record in listed} == set(record_ids)


def test_sqlite_store_backup_copies_live_database(tmp_path) -> None:
    db_path = tmp_path / "sophiagraph.sqlite3"
    backup_path = tmp_path / "backups" / "sophiagraph-backup.sqlite3"
    store = SophiaGraphSqliteStore(db_path)
    store.put_record(_record("rec-backup"))

    returned_path = store.backup(backup_path)

    assert returned_path == backup_path
    backup_store = SophiaGraphSqliteStore(backup_path)
    assert backup_store.get_record("rec-backup") is not None


def test_sqlite_store_persists_namespace_columns_and_payload(tmp_path) -> None:
    store = SophiaGraphSqliteStore(tmp_path / "sophiagraph.sqlite3")
    namespace = MemoryNamespace(
        tenant_id="tenant-acme",
        user_id="user-j",
        agent_id="test",
        session_id="session-1",
        graph_id="main",
    )
    record = _record("rec-ns", namespace=namespace)
    store.put_record(record)

    fetched = store.get_record(record.id)
    assert fetched is not None
    assert fetched.namespace == namespace

    listed = store.list_records(
        ListQueryOptions(
            scopes=["agent:test"],
            namespaces=[MemoryNamespace(tenant_id="tenant-acme", agent_id="test")],
        )
    )
    assert [item.id for item in listed] == [record.id]

    with sqlite3.connect(tmp_path / "sophiagraph.sqlite3") as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT tenant_id, user_id, agent_id, session_id, graph_id FROM sophiagraph_records WHERE id = ?",
            (record.id,),
        ).fetchone()
    assert dict(row) == {
        "tenant_id": "tenant-acme",
        "user_id": "user-j",
        "agent_id": "test",
        "session_id": "session-1",
        "graph_id": "main",
    }


def test_sqlite_store_migrates_legacy_scope_records_to_namespace(tmp_path) -> None:
    db_path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE sophiagraph_records (
                id TEXT PRIMARY KEY,
                scope TEXT NOT NULL,
                record_type TEXT NOT NULL,
                record_key TEXT,
                title TEXT,
                tier TEXT NOT NULL,
                is_deleted INTEGER NOT NULL DEFAULT 0,
                valid_to TEXT,
                updated_at TEXT NOT NULL,
                payload_json TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            INSERT INTO sophiagraph_records(
                id, scope, record_type, record_key, title, tier, updated_at, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "rec-legacy",
                "agent:legacy",
                "fact",
                "project:alpha",
                "Legacy",
                "working",
                "2026-05-22T00:00:00+00:00",
                '{"id":"rec-legacy","scope":"agent:legacy","type":"fact","key":"project:alpha","title":"Legacy","content":{"text":"old"},"created_at":"2026-05-22T00:00:00+00:00","updated_at":"2026-05-22T00:00:00+00:00"}',
            ),
        )

    store = SophiaGraphSqliteStore(db_path)
    fetched = store.get_record("rec-legacy")
    assert fetched is not None
    assert fetched.namespace == MemoryNamespace(agent_id="legacy")

    with sqlite3.connect(db_path) as conn:
        agent_id = conn.execute(
            "SELECT agent_id FROM sophiagraph_records WHERE id = ?",
            ("rec-legacy",),
        ).fetchone()[0]
    assert agent_id == "legacy"


def test_sqlite_store_namespace_migration_is_version_gated(tmp_path) -> None:
    db_path = tmp_path / "legacy-version.sqlite3"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE sophiagraph_records (
                id TEXT PRIMARY KEY,
                scope TEXT NOT NULL,
                record_type TEXT NOT NULL,
                record_key TEXT,
                title TEXT,
                tier TEXT NOT NULL,
                is_deleted INTEGER NOT NULL DEFAULT 0,
                valid_to TEXT,
                updated_at TEXT NOT NULL,
                payload_json TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            INSERT INTO sophiagraph_records(
                id, scope, record_type, record_key, title, tier, updated_at, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "rec-legacy",
                "agent:legacy",
                "fact",
                "project:alpha",
                "Legacy",
                "working",
                "2026-05-22T00:00:00+00:00",
                '{"id":"rec-legacy","scope":"agent:legacy","type":"fact","key":"project:alpha","title":"Legacy","content":{"text":"old"},"created_at":"2026-05-22T00:00:00+00:00","updated_at":"2026-05-22T00:00:00+00:00"}',
            ),
        )

    SophiaGraphSqliteStore(db_path)
    with sqlite3.connect(db_path) as conn:
        first_version = conn.execute("PRAGMA user_version").fetchone()[0]
        first_payload = conn.execute(
            "SELECT payload_json FROM sophiagraph_records WHERE id = 'rec-legacy'"
        ).fetchone()[0]

    SophiaGraphSqliteStore(db_path)
    with sqlite3.connect(db_path) as conn:
        second_version = conn.execute("PRAGMA user_version").fetchone()[0]
        second_payload = conn.execute(
            "SELECT payload_json FROM sophiagraph_records WHERE id = 'rec-legacy'"
        ).fetchone()[0]

    assert first_version == SCHEMA_VERSION
    assert second_version == SCHEMA_VERSION
    assert second_payload == first_payload


def test_sqlite_store_migrates_mixed_legacy_and_explicit_namespace_rows(
    tmp_path,
) -> None:
    db_path = tmp_path / "mixed-legacy.sqlite3"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE sophiagraph_records (
                id TEXT PRIMARY KEY,
                scope TEXT NOT NULL,
                record_type TEXT NOT NULL,
                record_key TEXT,
                title TEXT,
                tier TEXT NOT NULL,
                is_deleted INTEGER NOT NULL DEFAULT 0,
                valid_to TEXT,
                updated_at TEXT NOT NULL,
                payload_json TEXT NOT NULL
            )
            """
        )
        conn.executemany(
            """
            INSERT INTO sophiagraph_records(
                id, scope, record_type, record_key, title, tier, updated_at, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    "rec-explicit",
                    "agent:legacy",
                    "fact",
                    "project:explicit",
                    "Explicit",
                    "working",
                    "2026-05-22T00:00:00+00:00",
                    '{"id":"rec-explicit","scope":"agent:legacy","type":"fact","key":"project:explicit","title":"Explicit","content":{"text":"explicit namespace survives"},"created_at":"2026-05-22T00:00:00+00:00","updated_at":"2026-05-22T00:00:00+00:00","namespace":{"tenant_id":"tenant-explicit","user_id":"user-explicit","agent_id":"agent-explicit","graph_id":"graph-explicit"}}',
                ),
                (
                    "rec-fallback",
                    "project:fallback",
                    "fact",
                    "project:fallback",
                    "Fallback",
                    "working",
                    "2026-05-22T00:00:00+00:00",
                    '{"id":"rec-fallback","scope":"project:fallback","type":"fact","key":"project:fallback","title":"Fallback","content":{"text":"scope namespace fills"},"created_at":"2026-05-22T00:00:00+00:00","updated_at":"2026-05-22T00:00:00+00:00"}',
                ),
            ],
        )

    store = SophiaGraphSqliteStore(db_path)
    explicit = store.get_record("rec-explicit")
    fallback = store.get_record("rec-fallback")
    assert explicit.namespace == MemoryNamespace(
        tenant_id="tenant-explicit",
        user_id="user-explicit",
        agent_id="agent-explicit",
        graph_id="graph-explicit",
    )
    assert fallback.namespace == MemoryNamespace(project_id="fallback")

    SophiaGraphSqliteStore(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = {
            row["id"]: dict(row)
            for row in conn.execute(
                """
                SELECT id, tenant_id, user_id, agent_id, project_id, graph_id
                  FROM sophiagraph_records
                 ORDER BY id
                """
            ).fetchall()
        }
    assert rows["rec-explicit"]["tenant_id"] == "tenant-explicit"
    assert rows["rec-explicit"]["agent_id"] == "agent-explicit"
    assert rows["rec-fallback"]["project_id"] == "fallback"


def test_sqlite_store_candidate_promotion_and_relations(tmp_path) -> None:
    store = SophiaGraphSqliteStore(tmp_path / "sophiagraph.sqlite3")
    anchor = _record("rec-anchor")
    store.put_record(anchor)
    candidate = MemoryCandidate(
        candidate_id="cand-1",
        session_id="session-1",
        proposed_scope="agent:test",
        type="fact",
        content={"text": "beta launched"},
        title="Beta fact",
        source="imported",
        confidence=0.7,
    )
    store.put_candidate(candidate)
    promoted = store.promote_candidate("cand-1", "agent:test")
    assert promoted.scope == "agent:test"

    relation = MemoryRelation(
        relation_id="rel-1",
        source_record_id=anchor.id,
        target_record_id=promoted.id,
        relation_type="supports",
        created_at="2026-05-22T00:00:00+00:00",
    )
    store.put_relation(relation)
    related = store.get_related_records(anchor.id, ["agent:test"])
    assert [item.id for item in related] == [promoted.id]
    assert (
        store.list_candidates(CandidateListOptions(status="promoted"))[0].candidate_id
        == "cand-1"
    )


def test_sqlite_store_candidate_promotion_preserves_candidate_namespace(
    tmp_path,
) -> None:
    store = SophiaGraphSqliteStore(tmp_path / "sophiagraph.sqlite3")
    namespace = MemoryNamespace(
        tenant_id="tenant-acme",
        user_id="user-j",
        agent_id="test",
        session_id="session-1",
    )
    candidate = MemoryCandidate(
        candidate_id="cand-ns",
        session_id="session-1",
        proposed_scope="agent:test",
        type="fact",
        content={"text": "candidate namespace persists"},
        namespace=namespace,
    )
    store.put_candidate(candidate)

    promoted = store.promote_candidate("cand-ns", "agent:test")

    assert promoted.namespace == namespace
    assert store.get_record(promoted.id).namespace == namespace


def test_sqlite_store_relation_direction_contract(tmp_path) -> None:
    store = SophiaGraphSqliteStore(tmp_path / "sophiagraph.sqlite3")
    first = _record("rec-1")
    second = _record("rec-2")
    third = _record("rec-3")
    store.put_record(first)
    store.put_record(second)
    store.put_record(third)
    store.put_relation(
        MemoryRelation(
            relation_id="rel-out",
            source_record_id=first.id,
            target_record_id=second.id,
            relation_type="supports",
            created_at="2026-05-22T00:00:00+00:00",
        )
    )
    store.put_relation(
        MemoryRelation(
            relation_id="rel-in",
            source_record_id=third.id,
            target_record_id=first.id,
            relation_type="depends_on",
            created_at="2026-05-22T01:00:00+00:00",
        )
    )

    assert [item.relation_id for item in store.list_relations(first.id)] == ["rel-out"]
    assert [
        item.relation_id for item in store.list_relations(first.id, direction="in")
    ] == ["rel-in"]
    assert [
        item.relation_id for item in store.list_relations(first.id, direction="both")
    ] == ["rel-in", "rel-out"]
    assert [
        item.id
        for item in store.get_related_records(
            first.id,
            ["agent:test"],
            direction="both",
        )
    ] == [third.id, second.id]

    with pytest.raises(InvalidArgumentError, match="invalid relation direction"):
        store.list_relations(first.id, direction="sideways")


def test_sqlite_store_invalidation_supersession_and_history(tmp_path) -> None:
    store = SophiaGraphSqliteStore(tmp_path / "sophiagraph.sqlite3")
    original = _record("rec-original", created_at="2026-05-22T00:00:00+00:00")
    replacement = _record("rec-replacement", created_at="2026-05-23T00:00:00+00:00")
    store.put_record(original)
    invalidated = store.invalidate_record(
        original.id, valid_to="2026-05-22T12:00:00+00:00", reason="stale"
    )
    assert invalidated.valid_to == "2026-05-22T12:00:00+00:00"
    assert store.list_records(ListQueryOptions(scopes=["agent:test"])) == []
    assert (
        store.list_records(
            ListQueryOptions(scopes=["agent:test"], include_invalidated=True)
        )[0].id
        == original.id
    )

    store.put_record(replacement)
    superseded = store.supersede_record(
        original.id, replacement.id, reason="newer fact"
    )
    history = store.history("agent:test", "fact", "project:alpha")
    assert superseded.superseded_by_id == replacement.id
    assert len(history) == 2
    assert {item.id for item in history} == {original.id, replacement.id}


def test_sqlite_store_export_import_snapshot_with_relations_and_tier_history(
    tmp_path,
) -> None:
    source = SophiaGraphSqliteStore(tmp_path / "source.sqlite3")
    first = _record("rec-1")
    second = _record("rec-2", created_at="2026-05-22T01:00:00+00:00")
    source.put_record(first)
    source.put_record(second)
    source.put_relation(
        MemoryRelation(
            relation_id="rel-1",
            source_record_id=first.id,
            target_record_id=second.id,
            relation_type="supports",
            created_at="2026-05-22T02:00:00+00:00",
        )
    )
    source.put_tier_transition(
        MemoryTierTransition(
            transition_id="tt-1",
            record_id=first.id,
            scope=first.scope,
            record_type=first.type,
            from_tier="working",
            to_tier="archival",
            transition_reason="manual_override",
            transition_at="2026-05-22T03:00:00+00:00",
            access_count=3,
        )
    )
    snapshot = source.export_snapshot(
        MemoryBundleExportOptions(
            scopes=["agent:test"],
            include_relations=True,
            include_tier_history=True,
            include_candidates=False,
        )
    )
    assert snapshot.manifest["counts"]["records"] == 2
    assert snapshot.manifest["counts"]["relations"] == 1
    assert snapshot.manifest["counts"]["tier_transitions"] == 1

    dest = SophiaGraphSqliteStore(tmp_path / "dest.sqlite3")
    result = dest.import_snapshot(snapshot, MemoryBundleImportOptions())
    assert result.applied is True
    assert result.imported_records == 2
    assert result.imported_relations == 1
    assert result.imported_tier_transitions == 1
    assert len(dest.get_related_records(first.id, ["agent:test"])) == 1
    assert len(dest.list_tier_transitions(scopes=["agent:test"])) == 1


def test_sqlite_store_export_import_snapshot_candidate_mode(tmp_path) -> None:
    source = SophiaGraphSqliteStore(tmp_path / "source.sqlite3")
    source.put_record(_record())
    snapshot = source.export_snapshot(
        MemoryBundleExportOptions(scopes=["agent:test"], include_relations=True)
    )

    staged = SophiaGraphSqliteStore(tmp_path / "staged.sqlite3")
    staged_result = staged.import_snapshot(
        snapshot,
        MemoryBundleImportOptions(trust_mode="candidate"),
    )
    assert staged_result.staged_candidates == 1
    assert staged.record_count() == 0
    assert len(staged.list_candidates(CandidateListOptions())) == 1
