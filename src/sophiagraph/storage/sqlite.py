"""SQLite-first standalone durable engine for the reusable ``sophiagraph`` package."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, replace
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterator
from uuid import uuid4

from sophiagraph.contracts.types import MEMORY_CONTRACT_VERSION
from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.models import (
    MemoryCandidate,
    KnowledgeDocumentBlock,
    MemoryNamespace,
    MemoryRecord,
    MemoryRelation,
    MemoryTierTransition,
    MemoryType,
    RelationDirection,
    SophiaGraphChangeEvent,
    StructuralLink,
    default_change_namespace,
)
from sophiagraph.portability.codec import (
    build_manifest,
    candidate_from_dict,
    change_event_from_dict,
    json_dumps,
    record_from_dict,
    relation_from_dict,
    tier_transition_from_dict,
)
from sophiagraph.portability.models import (
    MemoryBundleExportOptions,
    MemoryBundleImportOptions,
    MemoryBundleImportResult,
    MemoryBundleSnapshot,
    MemoryDeltaImportResult,
    MemoryDeltaSnapshot,
)
from sophiagraph.query import (
    CandidateListOptions,
    GraphSnapshot,
    GraphSnapshotOptions,
    LinkQueryOptions,
    ListQueryOptions,
    LocalGraphOptions,
    RecordOrder,
    SearchQueryOptions,
    StructuralSearchQuery,
)
from sophiagraph.storage.base import SophiaGraphStore
from sophiagraph.storage.helpers import (
    record_matches_namespaces,
    record_matches_query,
    utc_now_iso,
)
from sophiagraph.storage.graph_helpers import (
    graph_edge_from_link,
    graph_node_from_record,
    block_from_dict,
    block_to_dict,
    link_from_dict,
    link_to_dict,
    namespace_matches_filters,
    record_matches_structural_query,
)

_SCHEMA_VERSION = 5
_SQLITE_BUSY_TIMEOUT_MS = 5000
_SQLITE_CONNECT_TIMEOUT_SECONDS = _SQLITE_BUSY_TIMEOUT_MS / 1000
_SQLITE_JOURNAL_MODE = "wal"
_SQLITE_SYNCHRONOUS = "normal"


def _row_json(row: sqlite3.Row, key: str = "payload_json") -> dict[str, Any]:
    raw = row[key]
    return json.loads(str(raw)) if raw else {}


_NAMESPACE_COLUMNS = (
    "tenant_id",
    "org_id",
    "user_id",
    "agent_id",
    "session_id",
    "conversation_id",
    "project_id",
    "graph_id",
)


def _namespace_values(record: MemoryRecord) -> dict[str, str]:
    return record.effective_namespace.as_dict()


def _namespace_from_payload(payload: dict[str, Any], scope: str) -> MemoryNamespace:
    raw_namespace = payload.get("namespace")
    if isinstance(raw_namespace, dict) and raw_namespace:
        return MemoryNamespace.from_dict(raw_namespace)
    return MemoryNamespace.from_scope(scope)


def _namespace_filter_sql(
    namespaces: list[MemoryNamespace] | None,
) -> tuple[str, list[Any]]:
    if not namespaces:
        return "", []
    groups: list[str] = []
    params: list[Any] = []
    for namespace in namespaces:
        values = namespace.as_dict()
        clauses = [f"{column} = ?" for column in values]
        groups.append("(" + " AND ".join(clauses) + ")")
        params.extend(values.values())
    return "(" + " OR ".join(groups) + ")", params


class SophiaGraphSqliteStore(SophiaGraphStore):
    """Small standalone SQLite-backed durable engine for ``sophiagraph``."""

    contract_version = MEMORY_CONTRACT_VERSION

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            self.db_path,
            timeout=_SQLITE_CONNECT_TIMEOUT_SECONDS,
        )
        conn.row_factory = sqlite3.Row
        conn.execute(f"PRAGMA busy_timeout = {_SQLITE_BUSY_TIMEOUT_MS}")
        conn.execute(f"PRAGMA journal_mode = {_SQLITE_JOURNAL_MODE}")
        conn.execute(f"PRAGMA synchronous = {_SQLITE_SYNCHRONOUS}")
        return conn

    @contextmanager
    def _write_connection(self) -> Iterator[sqlite3.Connection]:
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def backup(self, destination_path: str | Path) -> Path:
        destination = Path(destination_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as source, sqlite3.connect(destination) as target:
            target.execute(f"PRAGMA busy_timeout = {_SQLITE_BUSY_TIMEOUT_MS}")
            source.backup(target)
        return destination

    def _ensure_schema(self) -> None:
        with self._write_connection() as conn:
            schema_version = int(conn.execute("PRAGMA user_version").fetchone()[0])
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS sophiagraph_records (
                    id TEXT PRIMARY KEY,
                    scope TEXT NOT NULL,
                    record_type TEXT NOT NULL,
                    record_key TEXT,
                    title TEXT,
                    tenant_id TEXT,
                    org_id TEXT,
                    user_id TEXT,
                    agent_id TEXT,
                    session_id TEXT,
                    conversation_id TEXT,
                    project_id TEXT,
                    graph_id TEXT,
                    tier TEXT NOT NULL,
                    is_deleted INTEGER NOT NULL DEFAULT 0,
                    valid_to TEXT,
                    updated_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_sophiagraph_records_scope_type
                    ON sophiagraph_records(scope, record_type, updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_sophiagraph_records_key
                    ON sophiagraph_records(scope, record_type, record_key);
                CREATE TABLE IF NOT EXISTS sophiagraph_relations (
                    relation_id TEXT PRIMARY KEY,
                    source_record_id TEXT NOT NULL,
                    target_record_id TEXT NOT NULL,
                    relation_type TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_sophiagraph_relations_source
                    ON sophiagraph_relations(source_record_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_sophiagraph_relations_target
                    ON sophiagraph_relations(target_record_id, created_at DESC);

                CREATE TABLE IF NOT EXISTS sophiagraph_candidates (
                    candidate_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    proposed_scope TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT,
                    updated_at TEXT,
                    payload_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_sophiagraph_candidates_session
                    ON sophiagraph_candidates(session_id, updated_at DESC);

                CREATE TABLE IF NOT EXISTS sophiagraph_tier_transitions (
                    transition_id TEXT PRIMARY KEY,
                    record_id TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    record_type TEXT NOT NULL,
                    transition_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_sophiagraph_tier_transitions_record
                    ON sophiagraph_tier_transitions(record_id, transition_at DESC);

                CREATE TABLE IF NOT EXISTS sophiagraph_links (
                    link_id TEXT PRIMARY KEY,
                    source_record_id TEXT NOT NULL,
                    target_record_id TEXT,
                    raw_target TEXT NOT NULL,
                    link_kind TEXT NOT NULL,
                    resolution_status TEXT NOT NULL,
                    relation_type TEXT,
                    tenant_id TEXT,
                    org_id TEXT,
                    user_id TEXT,
                    agent_id TEXT,
                    session_id TEXT,
                    conversation_id TEXT,
                    project_id TEXT,
                    graph_id TEXT,
                    created_at TEXT,
                    payload_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_sophiagraph_links_source
                    ON sophiagraph_links(source_record_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_sophiagraph_links_target
                    ON sophiagraph_links(target_record_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_sophiagraph_links_namespace
                    ON sophiagraph_links(
                        tenant_id, org_id, user_id, agent_id, session_id,
                        conversation_id, project_id, graph_id
                    );

                CREATE TABLE IF NOT EXISTS sophiagraph_blocks (
                    block_id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL,
                    record_id TEXT NOT NULL,
                    block_type TEXT NOT NULL,
                    anchor TEXT NOT NULL,
                    line_start INTEGER,
                    line_end INTEGER,
                    excerpt TEXT,
                    payload_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_sophiagraph_blocks_record
                    ON sophiagraph_blocks(record_id, line_start, block_id);
                CREATE INDEX IF NOT EXISTS idx_sophiagraph_blocks_document
                    ON sophiagraph_blocks(document_id, line_start, block_id);
                CREATE INDEX IF NOT EXISTS idx_sophiagraph_blocks_anchor
                    ON sophiagraph_blocks(anchor);

                CREATE TABLE IF NOT EXISTS sophiagraph_change_events (
                    cursor INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    object_type TEXT NOT NULL,
                    object_id TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    changed_at TEXT NOT NULL,
                    tenant_id TEXT,
                    org_id TEXT,
                    user_id TEXT,
                    agent_id TEXT,
                    session_id TEXT,
                    conversation_id TEXT,
                    project_id TEXT,
                    graph_id TEXT,
                    idempotency_key TEXT UNIQUE,
                    source_operation_id TEXT,
                    schema_identifiers_json TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_sophiagraph_change_events_cursor
                    ON sophiagraph_change_events(cursor);
                CREATE INDEX IF NOT EXISTS idx_sophiagraph_change_events_namespace
                    ON sophiagraph_change_events(
                        tenant_id, org_id, user_id, agent_id, session_id,
                        conversation_id, project_id, graph_id
                    );
                """
            )
            self._ensure_fts_schema(conn)
            if schema_version < 2:
                self._migrate_namespace_columns(conn)
            if schema_version < _SCHEMA_VERSION:
                conn.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_sophiagraph_records_namespace
                    ON sophiagraph_records(
                        tenant_id, org_id, user_id, agent_id, session_id,
                        conversation_id, project_id, graph_id
                    )
                """
            )

    def _ensure_fts_schema(self, conn: sqlite3.Connection) -> None:
        try:
            conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS sophiagraph_record_fts
                USING fts5(record_id UNINDEXED, searchable)
                """
            )
        except sqlite3.OperationalError:
            return

    def _record_searchable_text(self, record: MemoryRecord) -> str:
        return " ".join(
            str(part)
            for part in (
                record.title,
                record.key,
                record.scope,
                record.type,
                record.tags,
                record.content,
                record.meta,
            )
            if part is not None
        )

    def _replace_record_fts(
        self,
        conn: sqlite3.Connection,
        record: MemoryRecord,
    ) -> None:
        try:
            conn.execute(
                "DELETE FROM sophiagraph_record_fts WHERE record_id = ?",
                (record.id,),
            )
            conn.execute(
                """
                INSERT INTO sophiagraph_record_fts(record_id, searchable)
                VALUES (?, ?)
                """,
                (record.id, self._record_searchable_text(record)),
            )
        except sqlite3.OperationalError:
            return

    def _fts_candidate_record_ids(
        self,
        conn: sqlite3.Connection,
        query: StructuralSearchQuery,
    ) -> set[str] | None:
        terms = list(query.text_terms)
        terms.extend(query.exact_phrases)
        if query.content:
            terms.append(query.content)
        if not terms:
            return None
        escaped = [
            '"' + str(term).replace('"', '""') + '"' for term in terms if str(term)
        ]
        if not escaped:
            return None
        try:
            rows = conn.execute(
                """
                SELECT record_id FROM sophiagraph_record_fts
                 WHERE sophiagraph_record_fts MATCH ?
                """,
                (" AND ".join(escaped),),
            ).fetchall()
        except sqlite3.OperationalError:
            return None
        return {str(row["record_id"]) for row in rows}

    def _migrate_namespace_columns(self, conn: sqlite3.Connection) -> None:
        columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(sophiagraph_records)")
        }
        for column in _NAMESPACE_COLUMNS:
            if column not in columns:
                conn.execute(
                    f"ALTER TABLE sophiagraph_records ADD COLUMN {column} TEXT"
                )
        rows = conn.execute(
            "SELECT id, scope, payload_json FROM sophiagraph_records"
        ).fetchall()
        for row in rows:
            payload = _row_json(row)
            namespace = _namespace_from_payload(payload, str(row["scope"]))
            namespace_values = namespace.as_dict()
            if not isinstance(payload.get("namespace"), dict):
                payload["namespace"] = namespace_values
            conn.execute(
                """
                UPDATE sophiagraph_records
                   SET tenant_id = ?, org_id = ?, user_id = ?, agent_id = ?,
                       session_id = ?, conversation_id = ?, project_id = ?,
                       graph_id = ?, payload_json = ?
                 WHERE id = ?
                """,
                (
                    namespace_values.get("tenant_id"),
                    namespace_values.get("org_id"),
                    namespace_values.get("user_id"),
                    namespace_values.get("agent_id"),
                    namespace_values.get("session_id"),
                    namespace_values.get("conversation_id"),
                    namespace_values.get("project_id"),
                    namespace_values.get("graph_id"),
                    json_dumps(payload),
                    row["id"],
                ),
            )

    def _record_from_row(self, row: sqlite3.Row) -> MemoryRecord:
        return record_from_dict(_row_json(row))

    def _candidate_from_row(self, row: sqlite3.Row) -> MemoryCandidate:
        return candidate_from_dict(_row_json(row))

    def _relation_from_row(self, row: sqlite3.Row) -> MemoryRelation:
        return relation_from_dict(_row_json(row))

    def _link_from_row(self, row: sqlite3.Row) -> StructuralLink:
        return link_from_dict(_row_json(row))

    def _block_from_row(self, row: sqlite3.Row) -> KnowledgeDocumentBlock:
        return block_from_dict(_row_json(row))

    def _transition_from_row(self, row: sqlite3.Row) -> MemoryTierTransition:
        return tier_transition_from_dict(_row_json(row))

    def _change_from_row(self, row: sqlite3.Row) -> SophiaGraphChangeEvent:
        namespace = MemoryNamespace(
            tenant_id=row["tenant_id"],
            org_id=row["org_id"],
            user_id=row["user_id"],
            agent_id=row["agent_id"],
            session_id=row["session_id"],
            conversation_id=row["conversation_id"],
            project_id=row["project_id"],
            graph_id=row["graph_id"],
        )
        return change_event_from_dict(
            {
                "cursor": row["cursor"],
                "event_id": row["event_id"],
                "object_type": row["object_type"],
                "object_id": row["object_id"],
                "operation": row["operation"],
                "changed_at": row["changed_at"],
                "namespace": namespace.as_dict(),
                "idempotency_key": row["idempotency_key"],
                "source_operation_id": row["source_operation_id"],
                "schema_identifiers": json.loads(row["schema_identifiers_json"]),
                "payload": json.loads(row["payload_json"]),
            }
        )

    def _insert_change_event(
        self,
        conn: sqlite3.Connection,
        event: SophiaGraphChangeEvent,
    ) -> None:
        namespace_values = event.namespace.as_dict()
        conn.execute(
            """
            INSERT OR IGNORE INTO sophiagraph_change_events(
                event_id, object_type, object_id, operation, changed_at,
                tenant_id, org_id, user_id, agent_id, session_id,
                conversation_id, project_id, graph_id, idempotency_key,
                source_operation_id, schema_identifiers_json, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.event_id,
                event.object_type,
                event.object_id,
                event.operation,
                event.changed_at,
                namespace_values.get("tenant_id"),
                namespace_values.get("org_id"),
                namespace_values.get("user_id"),
                namespace_values.get("agent_id"),
                namespace_values.get("session_id"),
                namespace_values.get("conversation_id"),
                namespace_values.get("project_id"),
                namespace_values.get("graph_id"),
                event.idempotency_key,
                event.source_operation_id,
                json_dumps(event.schema_identifiers),
                json_dumps(event.payload),
            ),
        )

    def _emit_change(
        self,
        conn: sqlite3.Connection,
        *,
        object_type: str,
        object_id: str,
        payload: dict[str, Any],
        namespace: MemoryNamespace,
        schema_identifiers: dict[str, str],
    ) -> None:
        self._insert_change_event(
            conn,
            SophiaGraphChangeEvent(
                event_id=f"chg-{uuid4()}",
                object_type=object_type,  # type: ignore[arg-type]
                object_id=object_id,
                operation="put",
                changed_at=utc_now_iso(),
                payload=payload,
                namespace=namespace,
                schema_identifiers=schema_identifiers,
            ),
        )

    def _put_record_payload(
        self,
        conn: sqlite3.Connection,
        record: MemoryRecord,
    ) -> None:
        payload = asdict(record)
        namespace_values = _namespace_values(record)
        conn.execute(
            """
            INSERT OR REPLACE INTO sophiagraph_records(
                id, scope, record_type, record_key, title, tenant_id, org_id,
                user_id, agent_id, session_id, conversation_id, project_id,
                graph_id, tier, is_deleted, valid_to, updated_at, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.id,
                record.scope,
                record.type,
                record.key,
                record.title,
                namespace_values.get("tenant_id"),
                namespace_values.get("org_id"),
                namespace_values.get("user_id"),
                namespace_values.get("agent_id"),
                namespace_values.get("session_id"),
                namespace_values.get("conversation_id"),
                namespace_values.get("project_id"),
                namespace_values.get("graph_id"),
                record.tier,
                1 if record.is_deleted else 0,
                record.valid_to,
                record.updated_at,
                json_dumps(payload),
            ),
        )
        self._replace_record_fts(conn, record)

    def _change_exists(
        self,
        conn: sqlite3.Connection,
        event: SophiaGraphChangeEvent,
    ) -> bool:
        row = conn.execute(
            """
            SELECT 1 FROM sophiagraph_change_events
             WHERE event_id = ?
                OR (? IS NOT NULL AND idempotency_key = ?)
            """,
            (event.event_id, event.idempotency_key, event.idempotency_key),
        ).fetchone()
        return row is not None

    def put_record(self, record: MemoryRecord) -> str:
        with self._write_connection() as conn:
            self._put_record_payload(conn, record)
            self._emit_change(
                conn,
                object_type="record",
                object_id=record.id,
                payload=asdict(record),
                namespace=record.effective_namespace,
                schema_identifiers={"node_label": str(record.type)},
            )
        return record.id

    def upsert_record(
        self,
        scope: str,
        type: MemoryType,
        key: str,
        record_patch: dict[str, Any],
    ) -> MemoryRecord:
        existing = next(iter(self.history(scope, type, key)), None)
        now = utc_now_iso()
        if existing is None:
            payload = dict(record_patch)
            payload.setdefault("id", str(uuid4()))
            payload.setdefault("scope", scope)
            payload.setdefault("type", type)
            payload.setdefault("key", key)
            payload.setdefault("created_at", now)
            payload.setdefault("updated_at", now)
            payload.setdefault("event_time", payload.get("created_at", now))
            payload.setdefault("tier", "working")
            payload.setdefault("content", {})
            payload.setdefault("meta", {})
            record = record_from_dict(payload)
        else:
            payload = asdict(existing)
            payload.update(record_patch)
            payload["scope"] = scope
            payload["type"] = type
            payload["key"] = key
            payload["updated_at"] = now
            record = record_from_dict(payload)
        self.put_record(record)
        return record

    def get_record(self, record_id: str) -> MemoryRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload_json FROM sophiagraph_records WHERE id = ?",
                (record_id,),
            ).fetchone()
        return None if row is None else self._record_from_row(row)

    def list_records(self, options: ListQueryOptions) -> list[MemoryRecord]:
        clauses = ["scope IN ({})".format(",".join("?" for _ in options.scopes))]
        params: list[Any] = list(options.scopes)
        if options.types:
            clauses.append(
                "record_type IN ({})".format(",".join("?" for _ in options.types))
            )
            params.extend(options.types)
        if options.tiers:
            clauses.append("tier IN ({})".format(",".join("?" for _ in options.tiers)))
            params.extend(options.tiers)
        if not options.include_invalidated:
            clauses.append("(valid_to IS NULL OR valid_to > ?)")
            params.append(utc_now_iso())
        namespace_sql, namespace_params = _namespace_filter_sql(options.namespaces)
        if namespace_sql:
            clauses.append(namespace_sql)
            params.extend(namespace_params)
        order = "updated_at DESC"
        if options.order_by == RecordOrder.UPDATED_AT_ASC:
            order = "updated_at ASC"
        limit_sql = ""
        sql_limit = options.limit
        sql_offset = options.offset
        if sql_limit is not None:
            limit_sql += " LIMIT ?"
            params.append(int(sql_limit))
        if sql_offset is not None:
            if sql_limit is None:
                limit_sql += " LIMIT -1"
            limit_sql += " OFFSET ?"
            params.append(int(sql_offset))
        query = (
            "SELECT payload_json FROM sophiagraph_records WHERE "
            + " AND ".join(clauses)
            + f" ORDER BY {order}{limit_sql}"
        )
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        records = [self._record_from_row(row) for row in rows]
        return records

    def search_records(self, options: SearchQueryOptions) -> list[MemoryRecord]:
        listed = self.list_records(
            ListQueryOptions(
                scopes=options.scopes,
                types=options.types,
                tiers=options.tiers,
                include_invalidated=options.include_invalidated,
                limit=None,
                offset=None,
                order_by=RecordOrder.UPDATED_AT_DESC,
                namespaces=options.namespaces,
            )
        )
        matches = [
            record
            for record in listed
            if record_matches_query(
                record,
                options.query,
                content_serializer=json_dumps,
            )
        ]
        if options.limit is not None:
            matches = matches[: int(options.limit)]
        return matches

    def invalidate_record(
        self,
        record_id: str,
        *,
        valid_to: str,
        reason: str,
    ) -> MemoryRecord:
        record = self.get_record(record_id)
        if record is None:
            raise InvalidArgumentError(f"unknown record_id: {record_id}")
        updated = replace(
            record,
            valid_to=str(valid_to),
            supersession_reason=str(reason or record.supersession_reason or ""),
            updated_at=utc_now_iso(),
        )
        self.put_record(updated)
        return updated

    def supersede_record(
        self,
        old_record_id: str,
        new_record_id: str,
        reason: str = "",
    ) -> MemoryRecord:
        record = self.get_record(old_record_id)
        if record is None:
            raise InvalidArgumentError(f"unknown record_id: {old_record_id}")
        new_record = self.get_record(new_record_id)
        valid_to = new_record.created_at if new_record is not None else utc_now_iso()
        updated = replace(
            record,
            valid_to=valid_to,
            superseded_by_id=new_record_id,
            supersession_reason=str(reason or "superseded"),
            updated_at=utc_now_iso(),
        )
        self.put_record(updated)
        return updated

    def put_relation(self, relation: MemoryRelation) -> str:
        with self._write_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO sophiagraph_relations(
                    relation_id, source_record_id, target_record_id,
                    relation_type, created_at, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    relation.relation_id,
                    relation.source_record_id,
                    relation.target_record_id,
                    relation.relation_type,
                    relation.created_at,
                    json_dumps(asdict(relation)),
                ),
            )
            source_row = conn.execute(
                "SELECT payload_json FROM sophiagraph_records WHERE id = ?",
                (relation.source_record_id,),
            ).fetchone()
            source_record = (
                self._record_from_row(source_row) if source_row is not None else None
            )
            self._emit_change(
                conn,
                object_type="relation",
                object_id=relation.relation_id,
                payload=asdict(relation),
                namespace=source_record.effective_namespace
                if source_record is not None
                else default_change_namespace(),
                schema_identifiers={"relation_type": str(relation.relation_type)},
            )
        return relation.relation_id

    def list_relations(
        self,
        record_id: str,
        *,
        direction: RelationDirection = "out",
        relation_types: list[Any] | None = None,
        limit: int | None = None,
    ) -> list[MemoryRelation]:
        if direction not in {"out", "in", "both"}:
            raise InvalidArgumentError(f"invalid relation direction: {direction!r}")
        clauses: list[str] = []
        params: list[Any] = []
        if direction == "out":
            clauses.append("source_record_id = ?")
            params.append(record_id)
        elif direction == "in":
            clauses.append("target_record_id = ?")
            params.append(record_id)
        else:
            clauses.append("(source_record_id = ? OR target_record_id = ?)")
            params.extend([record_id, record_id])
        if relation_types:
            allowed = [str(item) for item in relation_types]
            clauses.append(
                "relation_type IN ({})".format(",".join("?" for _ in allowed))
            )
            params.extend(allowed)
        query = (
            "SELECT payload_json FROM sophiagraph_relations WHERE "
            + " AND ".join(clauses)
            + " ORDER BY created_at DESC"
        )
        if limit is not None:
            query += " LIMIT ?"
            params.append(int(limit))
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        relations = [self._relation_from_row(row) for row in rows]
        return relations

    def get_related_records(
        self,
        record_id: str,
        scopes: list[str],
        *,
        direction: RelationDirection = "out",
        relation_types: list[Any] | None = None,
        limit: int | None = None,
    ) -> list[MemoryRecord]:
        relations = self.list_relations(
            record_id,
            direction=direction,
            relation_types=relation_types,
            limit=limit,
        )
        records: list[MemoryRecord] = []
        scope_allow = set(scopes)
        for relation in relations:
            related_id = (
                relation.target_record_id
                if relation.source_record_id == record_id
                else relation.source_record_id
            )
            record = self.get_record(related_id)
            if record is None:
                continue
            if record.scope not in scope_allow:
                continue
            records.append(record)
        return records[: int(limit)] if limit is not None else records

    def put_link(self, link: StructuralLink) -> str:
        payload = link_to_dict(link)
        namespace_values = link.namespace.as_dict()
        with self._write_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO sophiagraph_links(
                    link_id, source_record_id, target_record_id, raw_target,
                    link_kind, resolution_status, relation_type, tenant_id,
                    org_id, user_id, agent_id, session_id, conversation_id,
                    project_id, graph_id, created_at, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    link.link_id,
                    link.source_record_id,
                    link.target_record_id,
                    link.raw_target,
                    link.link_kind,
                    link.resolution_status,
                    link.relation_type,
                    namespace_values.get("tenant_id"),
                    namespace_values.get("org_id"),
                    namespace_values.get("user_id"),
                    namespace_values.get("agent_id"),
                    namespace_values.get("session_id"),
                    namespace_values.get("conversation_id"),
                    namespace_values.get("project_id"),
                    namespace_values.get("graph_id"),
                    link.created_at,
                    json_dumps(payload),
                ),
            )
            schema_identifiers = {}
            if link.relation_type:
                schema_identifiers["relation_type"] = link.relation_type
            self._emit_change(
                conn,
                object_type="link",
                object_id=link.link_id,
                payload=payload,
                namespace=link.namespace,
                schema_identifiers=schema_identifiers,
            )
        return link.link_id

    def list_links(self, options: LinkQueryOptions) -> list[StructuralLink]:
        if options.direction not in {"out", "in", "both"}:
            raise InvalidArgumentError(f"invalid link direction: {options.direction!r}")
        clauses: list[str] = []
        params: list[Any] = []
        if options.direction == "out":
            clauses.append("source_record_id = ?")
            params.append(options.record_id)
        elif options.direction == "in":
            clauses.append("target_record_id = ?")
            params.append(options.record_id)
        else:
            clauses.append("(source_record_id = ? OR target_record_id = ?)")
            params.extend([options.record_id, options.record_id])
        if options.relation_types:
            allowed = [str(item) for item in options.relation_types]
            clauses.append(
                "relation_type IN ({})".format(",".join("?" for _ in allowed))
            )
            params.extend(allowed)
        namespace_sql, namespace_params = _namespace_filter_sql(options.namespaces)
        if namespace_sql:
            clauses.append(namespace_sql)
            params.extend(namespace_params)
        query = (
            "SELECT payload_json FROM sophiagraph_links WHERE "
            + " AND ".join(clauses)
            + " ORDER BY COALESCE(created_at, ''), link_id DESC"
        )
        if options.limit is not None:
            query += " LIMIT ?"
            params.append(int(options.limit))
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [
            self._link_from_row(row).with_context_bounds(
                before=options.context_chars,
                after=options.context_chars,
            )
            for row in rows
        ]

    def get_outgoing_links(
        self, record_id: str, *, limit: int | None = None
    ) -> list[StructuralLink]:
        return self.list_links(
            LinkQueryOptions(record_id=record_id, direction="out", limit=limit)
        )

    def get_backlinks(
        self, record_id: str, *, limit: int | None = None
    ) -> list[StructuralLink]:
        return self.list_links(
            LinkQueryOptions(record_id=record_id, direction="in", limit=limit)
        )

    def get_local_graph(self, options: LocalGraphOptions) -> GraphSnapshot:
        seen_nodes: set[str] = set()
        frontier: list[tuple[str, int]] = [(options.record_id, 0)]
        edges: list[Any] = []
        edge_ids: set[str] = set()
        degree_in: dict[str, int] = {}
        degree_out: dict[str, int] = {}
        while frontier and len(seen_nodes) < options.max_nodes:
            record_id, depth = frontier.pop(0)
            if record_id in seen_nodes:
                continue
            seen_nodes.add(record_id)
            if depth >= options.depth:
                continue
            links = self.list_links(
                LinkQueryOptions(
                    record_id=record_id,
                    direction=options.direction,
                    relation_types=options.relation_types,
                    namespaces=options.namespaces,
                )
            )
            for link in links:
                if link.link_id not in edge_ids and len(edges) < options.max_edges:
                    edges.append(graph_edge_from_link(link))
                    edge_ids.add(link.link_id)
                if link.target_record_id:
                    degree_out[link.source_record_id] = (
                        degree_out.get(link.source_record_id, 0) + 1
                    )
                    degree_in[link.target_record_id] = (
                        degree_in.get(link.target_record_id, 0) + 1
                    )
                next_id = (
                    link.target_record_id
                    if link.source_record_id == record_id
                    else link.source_record_id
                )
                if next_id and next_id not in seen_nodes:
                    frontier.append((next_id, depth + 1))
        records: list[MemoryRecord] = []
        for node_id in sorted(seen_nodes):
            record = self.get_record(node_id)
            if record is not None and namespace_matches_filters(
                record.effective_namespace, options.namespaces
            ):
                records.append(record)
        return GraphSnapshot(
            nodes=[
                graph_node_from_record(
                    record,
                    degree_in=degree_in.get(record.id, 0),
                    degree_out=degree_out.get(record.id, 0),
                )
                for record in records[: options.max_nodes]
            ],
            edges=edges,
            root_record_id=options.record_id,
            depth=options.depth,
            direction=options.direction,
            provenance={"store": "sqlite"},
        )

    def get_graph_snapshot(self, options: GraphSnapshotOptions) -> GraphSnapshot:
        records = self.list_records(
            ListQueryOptions(
                scopes=options.scopes,
                namespaces=options.namespaces,
                limit=options.max_nodes,
                include_invalidated=False,
            )
        )
        record_ids = {record.id for record in records}
        namespace_sql, namespace_params = _namespace_filter_sql(options.namespaces)
        clauses = ["1=1"]
        params: list[Any] = []
        if namespace_sql:
            clauses.append(namespace_sql)
            params.extend(namespace_params)
        query = (
            "SELECT payload_json FROM sophiagraph_links WHERE "
            + " AND ".join(clauses)
            + " ORDER BY COALESCE(created_at, ''), link_id DESC LIMIT ?"
        )
        params.append(options.max_edges)
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        links = [
            self._link_from_row(row)
            for row in rows
            if self._link_from_row(row).source_record_id in record_ids
            and (
                self._link_from_row(row).target_record_id is None
                or self._link_from_row(row).target_record_id in record_ids
            )
        ]
        if options.relation_types:
            allowed = {str(item) for item in options.relation_types}
            links = [link for link in links if link.relation_type in allowed]
        degree_in: dict[str, int] = {}
        degree_out: dict[str, int] = {}
        for link in links:
            if link.target_record_id:
                degree_out[link.source_record_id] = (
                    degree_out.get(link.source_record_id, 0) + 1
                )
                degree_in[link.target_record_id] = (
                    degree_in.get(link.target_record_id, 0) + 1
                )
        nodes = [
            graph_node_from_record(
                record,
                degree_in=degree_in.get(record.id, 0),
                degree_out=degree_out.get(record.id, 0),
            )
            for record in records
            if options.include_orphans
            or degree_in.get(record.id, 0)
            or degree_out.get(record.id, 0)
        ]
        return GraphSnapshot(
            nodes=nodes,
            edges=[graph_edge_from_link(link) for link in links],
            provenance={"store": "sqlite"},
        )

    def structural_search_records(
        self,
        query: StructuralSearchQuery,
        *,
        scopes: list[str],
    ) -> list[MemoryRecord]:
        records = self.list_records(
            ListQueryOptions(scopes=scopes, namespaces=query.namespaces)
        )
        with self._connect() as conn:
            rows = conn.execute("SELECT payload_json FROM sophiagraph_links").fetchall()
            block_rows = conn.execute(
                "SELECT payload_json FROM sophiagraph_blocks"
            ).fetchall()
            fts_record_ids = self._fts_candidate_record_ids(conn, query)
        links = [self._link_from_row(row) for row in rows]
        blocks = [self._block_from_row(row) for row in block_rows]
        matches = [
            record
            for record in records
            if fts_record_ids is None or record.id in fts_record_ids
            if record_matches_structural_query(
                record,
                query,
                outgoing_targets=[
                    link.raw_target
                    for link in links
                    if link.source_record_id == record.id
                ],
                incoming_sources=[
                    link.source_record_id
                    for link in links
                    if link.target_record_id == record.id
                ],
                blocks=[block for block in blocks if block.record_id == record.id],
            )
        ]
        if query.sort == "title":
            matches.sort(key=lambda record: record.title or "")
        if query.limit is not None:
            matches = matches[: int(query.limit)]
        return matches

    def put_document_blocks(
        self,
        record_id: str,
        blocks: list[KnowledgeDocumentBlock],
    ) -> None:
        with self._write_connection() as conn:
            conn.execute(
                "DELETE FROM sophiagraph_blocks WHERE record_id = ?",
                (record_id,),
            )
            row = conn.execute(
                "SELECT payload_json FROM sophiagraph_records WHERE id = ?",
                (record_id,),
            ).fetchone()
            record = self._record_from_row(row) if row is not None else None
            namespace = (
                record.effective_namespace
                if record is not None
                else default_change_namespace()
            )
            for block in blocks:
                if block.record_id != record_id:
                    raise InvalidArgumentError("block record_id must match record_id")
                payload = block_to_dict(block)
                conn.execute(
                    """
                    INSERT OR REPLACE INTO sophiagraph_blocks(
                        block_id, document_id, record_id, block_type, anchor,
                        line_start, line_end, excerpt, payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        block.block_id,
                        block.document_id,
                        block.record_id,
                        block.block_type,
                        block.anchor,
                        block.line_start,
                        block.line_end,
                        block.excerpt,
                        json_dumps(payload),
                    ),
                )
                self._emit_change(
                    conn,
                    object_type="block",
                    object_id=block.block_id,
                    payload=payload,
                    namespace=namespace,
                    schema_identifiers={"node_label": "block"},
                )

    def list_document_blocks(
        self,
        *,
        record_id: str | None = None,
        document_id: str | None = None,
        block_id: str | None = None,
    ) -> list[KnowledgeDocumentBlock]:
        clauses = ["1=1"]
        params: list[Any] = []
        if record_id is not None:
            clauses.append("record_id = ?")
            params.append(record_id)
        if document_id is not None:
            clauses.append("document_id = ?")
            params.append(document_id)
        if block_id is not None:
            clauses.append("block_id = ?")
            params.append(block_id)
        query = (
            "SELECT payload_json FROM sophiagraph_blocks WHERE "
            + " AND ".join(clauses)
            + " ORDER BY record_id, COALESCE(line_start, 0), block_id"
        )
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._block_from_row(row) for row in rows]

    def put_candidate(self, candidate: MemoryCandidate) -> str:
        with self._write_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO sophiagraph_candidates(
                    candidate_id, session_id, proposed_scope, status, created_at,
                    updated_at, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    candidate.candidate_id,
                    candidate.session_id,
                    candidate.proposed_scope,
                    candidate.status,
                    candidate.created_at,
                    candidate.updated_at,
                    json_dumps(asdict(candidate)),
                ),
            )
            self._emit_change(
                conn,
                object_type="candidate",
                object_id=candidate.candidate_id,
                payload=asdict(candidate),
                namespace=candidate.namespace
                or MemoryNamespace.from_scope(candidate.proposed_scope),
                schema_identifiers={"node_label": str(candidate.type)},
            )
        return candidate.candidate_id

    def get_candidate(self, candidate_id: str) -> MemoryCandidate | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload_json FROM sophiagraph_candidates WHERE candidate_id = ?",
                (candidate_id,),
            ).fetchone()
        return None if row is None else self._candidate_from_row(row)

    def list_candidates(self, options: CandidateListOptions) -> list[MemoryCandidate]:
        query = "SELECT payload_json FROM sophiagraph_candidates WHERE 1=1"
        params: list[Any] = []
        if options.session_id is not None:
            query += " AND session_id = ?"
            params.append(options.session_id)
        if options.proposed_scope is not None:
            query += " AND proposed_scope = ?"
            params.append(options.proposed_scope)
        if options.status is not None:
            query += " AND status = ?"
            params.append(options.status)
        query += " ORDER BY COALESCE(updated_at, created_at, '') DESC"
        if options.limit is not None:
            query += " LIMIT ?"
            params.append(int(options.limit))
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._candidate_from_row(row) for row in rows]

    def update_candidate(
        self,
        candidate_id: str,
        patch: dict[str, Any],
    ) -> MemoryCandidate:
        candidate = self.get_candidate(candidate_id)
        if candidate is None:
            raise InvalidArgumentError(f"unknown candidate_id: {candidate_id}")
        payload = asdict(candidate)
        payload.update(patch)
        payload["updated_at"] = utc_now_iso()
        updated = candidate_from_dict(payload)
        self.put_candidate(updated)
        return updated

    def promote_candidate(
        self,
        candidate_id: str,
        target_scope: str,
    ) -> MemoryRecord:
        candidate = self.get_candidate(candidate_id)
        if candidate is None:
            raise InvalidArgumentError(f"unknown candidate_id: {candidate_id}")
        now = utc_now_iso()
        record = MemoryRecord(
            id=str(uuid4()),
            scope=target_scope,
            type=candidate.type,
            content=candidate.content,
            created_at=candidate.created_at or now,
            updated_at=now,
            key=candidate.key,
            title=candidate.title,
            tags=list(candidate.tags),
            entities=list(candidate.entities),
            source=candidate.source,
            confidence=candidate.confidence,
            evidence_refs=list(candidate.evidence_refs),
            meta=dict(candidate.meta),
            namespace=candidate.namespace or MemoryNamespace.from_scope(target_scope),
            event_time=candidate.created_at or now,
        )
        self.put_record(record)
        promoted = replace(candidate, status="promoted", updated_at=now)
        self.put_candidate(promoted)
        return record

    def list_tier_transitions(
        self,
        *,
        record_id: str | None = None,
        scopes: list[str] | None = None,
        limit: int | None = None,
    ) -> list[MemoryTierTransition]:
        query = "SELECT payload_json FROM sophiagraph_tier_transitions WHERE 1=1"
        params: list[Any] = []
        if record_id is not None:
            query += " AND record_id = ?"
            params.append(record_id)
        if scopes:
            query += " AND scope IN ({})".format(",".join("?" for _ in scopes))
            params.extend(scopes)
        query += " ORDER BY transition_at DESC"
        if limit is not None:
            query += " LIMIT ?"
            params.append(int(limit))
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._transition_from_row(row) for row in rows]

    def put_tier_transition(self, transition: MemoryTierTransition) -> str:
        with self._write_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO sophiagraph_tier_transitions(
                    transition_id, record_id, scope, record_type, transition_at, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    transition.transition_id,
                    transition.record_id,
                    transition.scope,
                    transition.record_type,
                    transition.transition_at,
                    json_dumps(asdict(transition)),
                ),
            )
            self._emit_change(
                conn,
                object_type="tier_transition",
                object_id=transition.transition_id,
                payload=asdict(transition),
                namespace=MemoryNamespace.from_scope(transition.scope),
                schema_identifiers={"node_label": str(transition.record_type)},
            )
        return transition.transition_id

    def history(
        self,
        scope: str,
        type: MemoryType,
        key: str,
    ) -> list[MemoryRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT payload_json FROM sophiagraph_records
                WHERE scope = ? AND record_type = ? AND record_key = ?
                ORDER BY updated_at DESC
                """,
                (scope, type, key),
            ).fetchall()
        return [self._record_from_row(row) for row in rows]

    def export_snapshot(
        self,
        options: MemoryBundleExportOptions,
    ) -> MemoryBundleSnapshot:
        records = self.list_records(
            ListQueryOptions(
                scopes=options.scopes,
                types=options.types,
                include_invalidated=True,
                limit=options.limit,
                offset=None,
                order_by=RecordOrder.UPDATED_AT_DESC,
                namespaces=options.namespaces,
            )
        )
        relations: list[MemoryRelation] = []
        if options.include_relations:
            record_ids = {record.id for record in records}
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT payload_json FROM sophiagraph_relations ORDER BY created_at ASC"
                ).fetchall()
            relations = [
                relation
                for relation in (self._relation_from_row(row) for row in rows)
                if relation.source_record_id in record_ids
                and relation.target_record_id in record_ids
            ]
        candidates: list[MemoryCandidate] = []
        if options.include_candidates:
            candidates = self.list_candidates(CandidateListOptions(limit=options.limit))
        tier_transitions: list[MemoryTierTransition] = []
        if options.include_tier_history:
            tier_transitions = self.list_tier_transitions(
                scopes=options.scopes, limit=options.limit
            )
        snapshot = MemoryBundleSnapshot(
            manifest={},
            records=records,
            candidates=candidates,
            relations=relations,
            tier_transitions=tier_transitions,
            provenance_traces=[],
        )
        return replace(snapshot, manifest=build_manifest(snapshot=snapshot))

    def import_snapshot(
        self,
        snapshot: MemoryBundleSnapshot,
        options: MemoryBundleImportOptions,
    ) -> MemoryBundleImportResult:
        imported_records = 0
        staged_candidates = 0
        imported_candidates = 0
        imported_relations = 0
        imported_tier_transitions = 0
        skipped_records = 0
        skipped_sections: list[str] = []
        rewrites: dict[str, str] = dict(options.scope_rewrites)
        if options.dry_run:
            records = [
                record
                for record in snapshot.records
                if record_matches_namespaces(record, options.namespace_allowlist)
            ]
            skipped_records = len(snapshot.records) - len(records)
            return MemoryBundleImportResult(
                applied=False,
                trust_mode=options.trust_mode,
                conflict_mode=options.conflict_mode,
                id_mode=options.id_mode,
                imported_records=len(records),
                staged_candidates=len(records)
                if options.trust_mode == "candidate"
                else 0,
                imported_candidates=len(snapshot.candidates)
                if options.trust_mode == "direct"
                else 0,
                imported_relations=len(snapshot.relations)
                if options.trust_mode == "direct"
                else 0,
                imported_tier_transitions=len(snapshot.tier_transitions)
                if options.trust_mode == "direct"
                else 0,
                skipped_records=skipped_records,
                skipped_sections=[],
                rewrites=rewrites,
            )
        for record in snapshot.records:
            resolved_scope = options.scope_rewrites.get(record.scope, record.scope)
            record = replace(record, scope=resolved_scope)
            if not record_matches_namespaces(record, options.namespace_allowlist):
                skipped_records += 1
                continue
            if self.get_record(record.id) is not None:
                if options.conflict_mode == "skip":
                    skipped_records += 1
                    continue
                if options.conflict_mode == "error":
                    raise InvalidArgumentError(f"record already exists: {record.id}")
            if options.trust_mode == "candidate":
                candidate = MemoryCandidate(
                    candidate_id=str(uuid4()),
                    session_id="bundle-import",
                    proposed_scope=resolved_scope,
                    type=record.type,
                    content=record.content,
                    tags=list(record.tags),
                    entities=list(record.entities),
                    source="imported",
                    confidence=record.confidence,
                    evidence_refs=list(record.evidence_refs),
                    key=record.key,
                    title=record.title,
                    meta=dict(record.meta),
                    namespace=record.effective_namespace,
                    created_at=record.created_at,
                    updated_at=record.updated_at,
                )
                self.put_candidate(candidate)
                staged_candidates += 1
                continue
            self.put_record(record)
            imported_records += 1
        if options.trust_mode == "candidate":
            skipped_sections.extend(["relations", "tier_transitions", "candidates"])
            return MemoryBundleImportResult(
                applied=True,
                trust_mode=options.trust_mode,
                conflict_mode=options.conflict_mode,
                id_mode=options.id_mode,
                imported_records=0,
                staged_candidates=staged_candidates,
                skipped_records=skipped_records,
                skipped_sections=skipped_sections,
                rewrites=rewrites,
            )
        for candidate in snapshot.candidates:
            self.put_candidate(candidate)
            imported_candidates += 1
        for relation in snapshot.relations:
            self.put_relation(relation)
            imported_relations += 1
        for transition in snapshot.tier_transitions:
            self.put_tier_transition(transition)
            imported_tier_transitions += 1
        return MemoryBundleImportResult(
            applied=True,
            trust_mode=options.trust_mode,
            conflict_mode=options.conflict_mode,
            id_mode=options.id_mode,
            imported_records=imported_records,
            staged_candidates=staged_candidates,
            imported_candidates=imported_candidates,
            imported_relations=imported_relations,
            imported_tier_transitions=imported_tier_transitions,
            skipped_records=skipped_records,
            skipped_sections=skipped_sections,
            rewrites=rewrites,
        )

    def list_changes(
        self,
        *,
        since_cursor: int | None = None,
        limit: int | None = None,
        namespaces: list[MemoryNamespace] | None = None,
    ) -> list[SophiaGraphChangeEvent]:
        clauses = ["1=1"]
        params: list[Any] = []
        if since_cursor is not None:
            clauses.append("cursor > ?")
            params.append(int(since_cursor))
        namespace_sql, namespace_params = _namespace_filter_sql(namespaces)
        if namespace_sql:
            clauses.append(namespace_sql)
            params.extend(namespace_params)
        query = (
            "SELECT * FROM sophiagraph_change_events WHERE "
            + " AND ".join(clauses)
            + " ORDER BY cursor ASC"
        )
        if limit is not None:
            query += " LIMIT ?"
            params.append(int(limit))
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._change_from_row(row) for row in rows]

    def export_delta(
        self,
        *,
        since_cursor: int | None = None,
        limit: int | None = None,
        namespaces: list[MemoryNamespace] | None = None,
    ) -> MemoryDeltaSnapshot:
        changes = self.list_changes(
            since_cursor=since_cursor,
            limit=limit,
            namespaces=namespaces,
        )
        return MemoryDeltaSnapshot(
            manifest={
                "delta_version": "sophiagraph_delta.v1",
                "change_count": len(changes),
            },
            changes=changes,
        )

    def import_delta(self, delta: MemoryDeltaSnapshot) -> MemoryDeltaImportResult:
        imported = 0
        skipped: list[str] = []
        with self._write_connection() as conn:
            for event in delta.changes:
                if self._change_exists(conn, event):
                    skipped.append(event.event_id)
                    continue
                if event.object_type == "record":
                    record = record_from_dict(event.payload)
                    self._put_record_payload(conn, record)
                elif event.object_type == "relation":
                    relation = relation_from_dict(event.payload)
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO sophiagraph_relations(
                            relation_id, source_record_id, target_record_id,
                            relation_type, created_at, payload_json
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            relation.relation_id,
                            relation.source_record_id,
                            relation.target_record_id,
                            relation.relation_type,
                            relation.created_at,
                            json_dumps(asdict(relation)),
                        ),
                    )
                elif event.object_type == "link":
                    link = link_from_dict(event.payload)
                    payload = link_to_dict(link)
                    namespace_values = link.namespace.as_dict()
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO sophiagraph_links(
                            link_id, source_record_id, target_record_id, raw_target,
                            link_kind, resolution_status, relation_type, tenant_id,
                            org_id, user_id, agent_id, session_id, conversation_id,
                            project_id, graph_id, created_at, payload_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            link.link_id,
                            link.source_record_id,
                            link.target_record_id,
                            link.raw_target,
                            link.link_kind,
                            link.resolution_status,
                            link.relation_type,
                            namespace_values.get("tenant_id"),
                            namespace_values.get("org_id"),
                            namespace_values.get("user_id"),
                            namespace_values.get("agent_id"),
                            namespace_values.get("session_id"),
                            namespace_values.get("conversation_id"),
                            namespace_values.get("project_id"),
                            namespace_values.get("graph_id"),
                            link.created_at,
                            json_dumps(payload),
                        ),
                    )
                elif event.object_type == "candidate":
                    candidate = candidate_from_dict(event.payload)
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO sophiagraph_candidates(
                            candidate_id, session_id, proposed_scope, status,
                            created_at, updated_at, payload_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            candidate.candidate_id,
                            candidate.session_id,
                            candidate.proposed_scope,
                            candidate.status,
                            candidate.created_at,
                            candidate.updated_at,
                            json_dumps(asdict(candidate)),
                        ),
                    )
                elif event.object_type == "tier_transition":
                    transition = tier_transition_from_dict(event.payload)
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO sophiagraph_tier_transitions(
                            transition_id, record_id, scope, record_type,
                            transition_at, payload_json
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            transition.transition_id,
                            transition.record_id,
                            transition.scope,
                            transition.record_type,
                            transition.transition_at,
                            json_dumps(asdict(transition)),
                        ),
                    )
                else:
                    skipped.append(event.event_id)
                    continue
                self._insert_change_event(conn, event)
                imported += 1
        return MemoryDeltaImportResult(
            applied=True,
            imported_changes=imported,
            skipped_changes=len(skipped),
            skipped_event_ids=skipped,
        )

    def record_count(self) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS count FROM sophiagraph_records"
            ).fetchone()
        return int(row["count"] if row is not None else 0)

    def candidate_count(self) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS count FROM sophiagraph_candidates"
            ).fetchone()
        return int(row["count"] if row is not None else 0)

    def list_all_records(self) -> list[MemoryRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT payload_json FROM sophiagraph_records ORDER BY updated_at DESC"
            ).fetchall()
        return [self._record_from_row(row) for row in rows]
