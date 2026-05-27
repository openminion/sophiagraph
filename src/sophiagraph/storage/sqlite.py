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
from sophiagraph.contracts.errors import InvalidArgumentError, NotFoundError
from sophiagraph.models import (
    MemoryBlock,
    MemoryCandidate,
    MemoryEmbedding,
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
    memory_embedding_from_dict,
)
from sophiagraph.portability.codec import (
    candidate_from_dict,
    change_event_from_dict,
    json_dumps,
    record_from_dict,
    relation_from_dict,
    tier_transition_from_dict,
)
from sophiagraph.query import (
    CandidateListOptions,
    EmbeddingListOptions,
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
    record_matches_query,
    utc_now_iso,
)
from sophiagraph.storage.graph_helpers import (
    block_from_dict,
    block_to_dict,
    link_from_dict,
    link_to_dict,
    memory_block_from_dict,
    memory_block_to_dict,
    record_matches_structural_query,
)
from sophiagraph.storage.memory_block_helpers import (
    enforce_block_edit_gate as _enforce_block_edit_gate,
)
from sophiagraph.storage.graph_queries import build_graph_snapshot, build_local_graph
from sophiagraph.storage.sqlite_support import (
    SQLITE_BUSY_TIMEOUT_MS,
    SQLITE_CONNECT_TIMEOUT_SECONDS,
    SQLITE_JOURNAL_MODE,
    SQLITE_SYNCHRONOUS,
    block_fts_candidate_record_ids,
    ensure_schema,
    fts_candidate_record_ids,
    namespace_filter_sql,
    namespace_values as record_namespace_values,
    replace_record_blocks_fts,
    replace_record_fts,
    row_json,
)
from sophiagraph.storage.sqlite_portability import SqlitePortabilityMixin


class SophiaGraphSqliteStore(SqlitePortabilityMixin, SophiaGraphStore):
    """Small standalone SQLite-backed durable engine for ``sophiagraph``."""

    contract_version = MEMORY_CONTRACT_VERSION

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            self.db_path,
            timeout=SQLITE_CONNECT_TIMEOUT_SECONDS,
        )
        conn.row_factory = sqlite3.Row
        conn.execute(f"PRAGMA busy_timeout = {SQLITE_BUSY_TIMEOUT_MS}")
        conn.execute(f"PRAGMA journal_mode = {SQLITE_JOURNAL_MODE}")
        conn.execute(f"PRAGMA synchronous = {SQLITE_SYNCHRONOUS}")
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
            target.execute(f"PRAGMA busy_timeout = {SQLITE_BUSY_TIMEOUT_MS}")
            source.backup(target)
        return destination

    def _ensure_schema(self) -> None:
        with self._write_connection() as conn:
            ensure_schema(conn)

    def _record_from_row(self, row: sqlite3.Row) -> MemoryRecord:
        return record_from_dict(row_json(row))

    def _candidate_from_row(self, row: sqlite3.Row) -> MemoryCandidate:
        return candidate_from_dict(row_json(row))

    def _relation_from_row(self, row: sqlite3.Row) -> MemoryRelation:
        return relation_from_dict(row_json(row))

    def _link_from_row(self, row: sqlite3.Row) -> StructuralLink:
        return link_from_dict(row_json(row))

    def _block_from_row(self, row: sqlite3.Row) -> KnowledgeDocumentBlock:
        return block_from_dict(row_json(row))

    def _memory_block_from_row(self, row: sqlite3.Row) -> MemoryBlock:
        return memory_block_from_dict(row_json(row))

    def _transition_from_row(self, row: sqlite3.Row) -> MemoryTierTransition:
        return tier_transition_from_dict(row_json(row))

    def _embedding_from_row(self, row: sqlite3.Row) -> MemoryEmbedding:
        return memory_embedding_from_dict(row_json(row))

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
        namespace_values = record_namespace_values(record)
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
        replace_record_fts(conn, record)

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
        namespace_sql, namespace_params = namespace_filter_sql(options.namespaces)
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

    def replace_record_links(
        self,
        record_id: str,
        links: list[StructuralLink],
    ) -> None:
        with self._write_connection() as conn:
            conn.execute(
                "DELETE FROM sophiagraph_links WHERE source_record_id = ?",
                (record_id,),
            )
            for link in links:
                if link.source_record_id != record_id:
                    raise InvalidArgumentError(
                        "link source_record_id must match record_id"
                    )
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
        namespace_sql, namespace_params = namespace_filter_sql(options.namespaces)
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
        return build_local_graph(
            options,
            load_links=self.list_links,
            load_record=self.get_record,
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
        namespace_sql, namespace_params = namespace_filter_sql(options.namespaces)
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
        return build_graph_snapshot(
            records,
            [self._link_from_row(row) for row in rows],
            options,
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
            fts_record_ids = fts_candidate_record_ids(conn, query)
            block_fts_record_ids = block_fts_candidate_record_ids(conn, query)
        links = [self._link_from_row(row) for row in rows]
        blocks = [self._block_from_row(row) for row in block_rows]
        matches = [
            record
            for record in records
            if fts_record_ids is None or record.id in fts_record_ids
            if block_fts_record_ids is None or record.id in block_fts_record_ids
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
            replace_record_blocks_fts(conn, record_id, blocks)

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

    def _memory_block_namespace_values(self, block: MemoryBlock) -> dict[str, str]:
        return block.owner_namespace.as_dict()

    def _persist_memory_block(
        self,
        conn: sqlite3.Connection,
        block: MemoryBlock,
        *,
        operation: str,
    ) -> None:
        payload = memory_block_to_dict(block)
        namespace_values = self._memory_block_namespace_values(block)
        conn.execute(
            """
            INSERT OR REPLACE INTO sophiagraph_memory_blocks(
                block_id, class_name, mode, token_estimate, source,
                tenant_id, org_id, user_id, agent_id, session_id,
                conversation_id, project_id, graph_id,
                created_at, last_updated_at, last_updated_by, stale_after,
                payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                block.block_id,
                block.class_name,
                block.mode,
                int(block.token_estimate),
                block.source,
                namespace_values.get("tenant_id"),
                namespace_values.get("org_id"),
                namespace_values.get("user_id"),
                namespace_values.get("agent_id"),
                namespace_values.get("session_id"),
                namespace_values.get("conversation_id"),
                namespace_values.get("project_id"),
                namespace_values.get("graph_id"),
                block.created_at,
                block.last_updated_at,
                block.last_updated_by,
                block.stale_after,
                json_dumps(payload),
            ),
        )
        self._emit_change(
            conn,
            object_type="memory_block",
            object_id=block.block_id,
            payload=payload,
            namespace=block.owner_namespace,
            schema_identifiers={
                "node_label": "memory_block",
                "class_name": block.class_name,
                "mode": block.mode,
                "operation": operation,
            },
        )

    def put_memory_block(self, block: MemoryBlock) -> str:
        with self._write_connection() as conn:
            self._persist_memory_block(conn, block, operation="put")
        return block.block_id

    def get_memory_block(self, block_id: str) -> MemoryBlock | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload_json FROM sophiagraph_memory_blocks WHERE block_id = ?",
                (block_id,),
            ).fetchone()
        return None if row is None else self._memory_block_from_row(row)

    def list_memory_blocks(
        self,
        *,
        namespaces: list[MemoryNamespace] | None = None,
        class_names: list[str] | None = None,
        include_stale: bool = True,
        limit: int | None = None,
    ) -> list[MemoryBlock]:
        clauses = ["1=1"]
        params: list[Any] = []
        if class_names:
            placeholders = ",".join("?" for _ in class_names)
            clauses.append(f"class_name IN ({placeholders})")
            params.extend(class_names)
        ns_sql, ns_params = namespace_filter_sql(namespaces)
        if ns_sql:
            clauses.append(ns_sql)
            params.extend(ns_params)
        if not include_stale:
            clauses.append("(stale_after IS NULL OR stale_after > ?)")
            params.append(utc_now_iso())
        sql = (
            "SELECT payload_json FROM sophiagraph_memory_blocks WHERE "
            + " AND ".join(clauses)
            + " ORDER BY class_name ASC, created_at ASC, block_id ASC"
        )
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._memory_block_from_row(row) for row in rows]

    def update_memory_block_content(
        self,
        block_id: str,
        *,
        new_content: str,
        actor: str,
        operator_action: bool = False,
    ) -> MemoryBlock:
        block = self.get_memory_block(block_id)
        if block is None:
            raise NotFoundError(
                f"memory block {block_id!r} not found",
                details={"block_id": block_id},
            )
        _enforce_block_edit_gate(
            block,
            operator_action=operator_action,
            actor=actor,
            operation="update_content",
        )
        if not isinstance(new_content, str):
            raise InvalidArgumentError("new_content must be a string")
        updated = replace(
            block,
            content=new_content,
            last_updated_at=utc_now_iso(),
            last_updated_by=actor,
        )
        with self._write_connection() as conn:
            self._persist_memory_block(conn, updated, operation="update_content")
        return updated

    def delete_memory_block(
        self,
        block_id: str,
        *,
        actor: str,
        operator_action: bool = False,
    ) -> bool:
        block = self.get_memory_block(block_id)
        if block is None:
            return False
        _enforce_block_edit_gate(
            block,
            operator_action=operator_action,
            actor=actor,
            operation="delete",
        )
        with self._write_connection() as conn:
            conn.execute(
                "DELETE FROM sophiagraph_memory_blocks WHERE block_id = ?",
                (block_id,),
            )
            self._emit_change(
                conn,
                object_type="memory_block",
                object_id=block_id,
                payload=memory_block_to_dict(block),
                namespace=block.owner_namespace,
                schema_identifiers={
                    "node_label": "memory_block",
                    "class_name": block.class_name,
                    "mode": block.mode,
                    "operation": "delete",
                },
            )
        return True

    def mark_memory_block_stale_after(
        self,
        block_id: str,
        *,
        stale_after: str | None,
    ) -> MemoryBlock:
        block = self.get_memory_block(block_id)
        if block is None:
            raise NotFoundError(
                f"memory block {block_id!r} not found",
                details={"block_id": block_id},
            )
        updated = replace(block, stale_after=stale_after)
        with self._write_connection() as conn:
            self._persist_memory_block(conn, updated, operation="mark_stale_after")
        return updated

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

    def put_embedding(self, embedding: MemoryEmbedding) -> str:
        existing = self.get_embedding(
            embedding.record_id,
            embedding.vector_space,
            include_vector=True,
        )
        if existing is not None and existing.dimension != embedding.dimension:
            raise InvalidArgumentError("embedding dimension cannot change for key")
        payload = asdict(embedding)
        namespace_values = embedding.namespace.as_dict()
        with self._write_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO sophiagraph_embeddings(
                    record_id, vector_space, dimension, provider, model,
                    tenant_id, org_id, user_id, agent_id, session_id,
                    conversation_id, project_id, graph_id, external_vector_id,
                    updated_at, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    embedding.record_id,
                    embedding.vector_space,
                    embedding.dimension,
                    embedding.provider,
                    embedding.model,
                    namespace_values.get("tenant_id"),
                    namespace_values.get("org_id"),
                    namespace_values.get("user_id"),
                    namespace_values.get("agent_id"),
                    namespace_values.get("session_id"),
                    namespace_values.get("conversation_id"),
                    namespace_values.get("project_id"),
                    namespace_values.get("graph_id"),
                    embedding.external_vector_id,
                    embedding.updated_at,
                    json_dumps(payload),
                ),
            )
        return embedding.key

    def get_embedding(
        self,
        record_id: str,
        vector_space: str,
        *,
        include_vector: bool = True,
    ) -> MemoryEmbedding | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT payload_json FROM sophiagraph_embeddings
                 WHERE record_id = ? AND vector_space = ?
                """,
                (record_id, vector_space),
            ).fetchone()
        if row is None:
            return None
        embedding = self._embedding_from_row(row)
        return embedding if include_vector else embedding.without_vector()

    def list_embeddings(
        self,
        options: EmbeddingListOptions,
    ) -> list[MemoryEmbedding]:
        clauses = ["1=1"]
        params: list[Any] = []
        if options.record_id is not None:
            clauses.append("record_id = ?")
            params.append(options.record_id)
        if options.vector_space is not None:
            clauses.append("vector_space = ?")
            params.append(options.vector_space)
        namespace_sql, namespace_params = namespace_filter_sql(options.namespaces)
        if namespace_sql:
            clauses.append(namespace_sql)
            params.extend(namespace_params)
        query = (
            "SELECT payload_json FROM sophiagraph_embeddings WHERE "
            + " AND ".join(clauses)
            + " ORDER BY updated_at DESC"
        )
        if options.limit is not None:
            query += " LIMIT ?"
            params.append(int(options.limit))
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        embeddings = [self._embedding_from_row(row) for row in rows]
        if not options.include_vectors:
            embeddings = [embedding.without_vector() for embedding in embeddings]
        return embeddings

    def delete_embedding(self, record_id: str, vector_space: str) -> bool:
        with self._write_connection() as conn:
            cursor = conn.execute(
                """
                DELETE FROM sophiagraph_embeddings
                 WHERE record_id = ? AND vector_space = ?
                """,
                (record_id, vector_space),
            )
            return cursor.rowcount > 0

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
