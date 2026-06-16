"""SQLite-first standalone durable engine for the reusable ``sophiagraph`` package."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, replace
from pathlib import Path
import sqlite3
from typing import Any, Iterator
from uuid import uuid4

from sophiagraph.contracts.types import MEMORY_CONTRACT_VERSION
from sophiagraph.contracts.errors import InvalidArgumentError, NotFoundError
from sophiagraph.deletion import (
    DeletionCascadeResult,
    ErasureAuditEntry,
    ErasureAuditExport,
)
from sophiagraph.integrity import populate_integrity_hash
from sophiagraph.models import (
    ActiveEmbeddingModelSet,
    MemoryBlock,
    MemoryCandidate,
    MemoryEmbedding,
    KnowledgeDocumentBlock,
    MemoryNamespace,
    MemoryRecord,
    MemoryRelation,
    RetentionSnapshot,
    MemoryTierTransition,
    MemoryType,
    RelationDirection,
    StructuralLink,
    default_change_namespace,
    memory_embedding_from_dict,
)
from sophiagraph.models.embedding_lifecycle import namespace_key
from sophiagraph.portability.codec import (
    candidate_from_dict,
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
    has_bitemporal_filter,
    record_matches_bitemporal,
)
from sophiagraph.storage.base import SophiaGraphStore
from sophiagraph.storage.record_lifecycle import (
    RecordLifecycleMixin,
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
from sophiagraph.storage.sqlite_aux import SqliteAuxObjectMixin
from sophiagraph.storage.sqlite_changefeed import SqliteChangefeedMixin
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


class SophiaGraphSqliteStore(
    SqlitePortabilityMixin,
    SqliteChangefeedMixin,
    SqliteAuxObjectMixin,
    RecordLifecycleMixin,
    SophiaGraphStore,
):
    """Small standalone SQLite-backed durable engine for ``sophiagraph``."""

    contract_version = MEMORY_CONTRACT_VERSION

    def __init__(
        self,
        db_path: str | Path,
        *,
        integrity_hash_enabled: bool = False,
    ) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # Integrity hashing stays opt-in for backward compatibility.
        self._integrity_hash_enabled = integrity_hash_enabled
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

    def put_record(self, record: MemoryRecord) -> str:
        stamped = populate_integrity_hash(record, enabled=self._integrity_hash_enabled)
        with self._write_connection() as conn:
            self._put_record_payload(conn, stamped)
            self._emit_change(
                conn,
                object_type="record",
                object_id=stamped.id,
                payload=asdict(stamped),
                namespace=stamped.effective_namespace,
                schema_identifiers={"node_label": str(stamped.type)},
            )
        return stamped.id

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
        temporal_filter = has_bitemporal_filter(options)
        if not options.include_invalidated and not temporal_filter:
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
        if temporal_filter:
            sql_limit = None
            sql_offset = None
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
        if temporal_filter:
            records = [
                record
                for record in records
                if record_matches_bitemporal(record, options)
            ]
            if options.offset is not None:
                records = records[int(options.offset) :]
            if options.limit is not None:
                records = records[: int(options.limit)]
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
                as_of=options.as_of,
                valid_at=options.valid_at,
                effective_during=options.effective_during,
                believed_at=options.believed_at,
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

    def _mark_external_vector_active(
        self,
        conn: sqlite3.Connection,
        embedding: MemoryEmbedding,
    ) -> None:
        if not embedding.external_vector_id:
            return
        conn.execute(
            """
            DELETE FROM sophiagraph_orphan_external_vector_ids
             WHERE namespace_key = ? AND external_vector_id = ?
            """,
            (namespace_key(embedding.namespace), embedding.external_vector_id),
        )

    def _maybe_mark_external_vector_orphan(
        self,
        conn: sqlite3.Connection,
        embedding: MemoryEmbedding,
    ) -> None:
        if not embedding.external_vector_id:
            return
        row = conn.execute(
            """
            SELECT 1 FROM sophiagraph_embeddings
             WHERE external_vector_id = ?
               AND tenant_id IS ?
               AND org_id IS ?
               AND user_id IS ?
               AND agent_id IS ?
               AND session_id IS ?
               AND conversation_id IS ?
               AND project_id IS ?
               AND graph_id IS ?
             LIMIT 1
            """,
            (
                embedding.external_vector_id,
                embedding.namespace.tenant_id,
                embedding.namespace.org_id,
                embedding.namespace.user_id,
                embedding.namespace.agent_id,
                embedding.namespace.session_id,
                embedding.namespace.conversation_id,
                embedding.namespace.project_id,
                embedding.namespace.graph_id,
            ),
        ).fetchone()
        if row is not None:
            return
        values = embedding.namespace.as_dict()
        conn.execute(
            """
            INSERT OR REPLACE INTO sophiagraph_orphan_external_vector_ids(
                namespace_key, external_vector_id, tenant_id, org_id, user_id, agent_id,
                session_id, conversation_id, project_id, graph_id, last_seen_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                namespace_key(embedding.namespace),
                embedding.external_vector_id,
                values.get("tenant_id"),
                values.get("org_id"),
                values.get("user_id"),
                values.get("agent_id"),
                values.get("session_id"),
                values.get("conversation_id"),
                values.get("project_id"),
                values.get("graph_id"),
                embedding.updated_at,
            ),
        )

    def _persist_active_model_set(
        self,
        conn: sqlite3.Connection,
        model_set: ActiveEmbeddingModelSet,
        *,
        emit_change: bool = True,
    ) -> str:
        values = model_set.namespace.as_dict()
        ns_key = namespace_key(model_set.namespace)
        conn.execute(
            """
            INSERT OR REPLACE INTO sophiagraph_active_embedding_model_sets(
                namespace_key, vector_space, tenant_id, org_id, user_id, agent_id,
                session_id, conversation_id, project_id, graph_id, updated_at, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ns_key,
                model_set.vector_space,
                values.get("tenant_id"),
                values.get("org_id"),
                values.get("user_id"),
                values.get("agent_id"),
                values.get("session_id"),
                values.get("conversation_id"),
                values.get("project_id"),
                values.get("graph_id"),
                model_set.updated_at,
                json_dumps(model_set.to_dict()),
            ),
        )
        if emit_change:
            self._emit_change(
                conn,
                object_type="active_embedding_model_set",
                object_id=f"{ns_key}:{model_set.vector_space}",
                payload=model_set.to_dict(),
                namespace=model_set.namespace,
                schema_identifiers={"node_label": "active_embedding_model_set"},
            )
        return f"{ns_key}:{model_set.vector_space}"

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
            if (
                existing is not None
                and existing.external_vector_id != embedding.external_vector_id
            ):
                self._maybe_mark_external_vector_orphan(conn, existing)
            self._mark_external_vector_active(conn, embedding)
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
        existing = self.get_embedding(record_id, vector_space, include_vector=True)
        if existing is None:
            return False
        with self._write_connection() as conn:
            cursor = conn.execute(
                """
                DELETE FROM sophiagraph_embeddings
                 WHERE record_id = ? AND vector_space = ?
                """,
                (record_id, vector_space),
            )
            deleted = cursor.rowcount > 0
            if deleted:
                self._maybe_mark_external_vector_orphan(conn, existing)
            return deleted

    def put_active_model_set(self, model_set: ActiveEmbeddingModelSet) -> str:
        with self._write_connection() as conn:
            return self._persist_active_model_set(conn, model_set)

    def get_active_model_set(
        self,
        *,
        namespace: MemoryNamespace,
        vector_space: str,
    ) -> ActiveEmbeddingModelSet | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT payload_json
                  FROM sophiagraph_active_embedding_model_sets
                 WHERE namespace_key = ? AND vector_space = ?
                """,
                (namespace_key(namespace), vector_space),
            ).fetchone()
        if row is None:
            return None
        payload = row_json(row)
        return ActiveEmbeddingModelSet.from_dict(payload)

    def list_active_model_sets(
        self,
        *,
        namespaces: list[MemoryNamespace] | None = None,
        vector_space: str | None = None,
        limit: int | None = None,
    ) -> list[ActiveEmbeddingModelSet]:
        clauses = ["1=1"]
        params: list[Any] = []
        if vector_space is not None:
            clauses.append("vector_space = ?")
            params.append(vector_space)
        namespace_sql, namespace_params = namespace_filter_sql(namespaces)
        if namespace_sql:
            clauses.append(namespace_sql)
            params.extend(namespace_params)
        query = (
            "SELECT payload_json FROM sophiagraph_active_embedding_model_sets WHERE "
            + " AND ".join(clauses)
            + " ORDER BY namespace_key ASC, vector_space ASC"
        )
        if limit is not None:
            query += " LIMIT ?"
            params.append(int(limit))
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [ActiveEmbeddingModelSet.from_dict(row_json(row)) for row in rows]

    def list_orphan_external_vector_ids(
        self,
        *,
        namespace: MemoryNamespace,
        since: str | None = None,
    ) -> list[tuple[str, str]]:
        query = (
            "SELECT external_vector_id, last_seen_at "
            "FROM sophiagraph_orphan_external_vector_ids WHERE namespace_key = ?"
        )
        params: list[Any] = [namespace_key(namespace)]
        if since is not None:
            query += " AND last_seen_at >= ?"
            params.append(since)
        query += " ORDER BY last_seen_at ASC, external_vector_id ASC"
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [(str(row[0]), str(row[1])) for row in rows]

    def tombstone_record(
        self,
        record_id: str,
        *,
        deleted_at: str,
        reason: str,
    ) -> MemoryRecord:
        record = self.get_record(record_id)
        if record is None:
            raise NotFoundError(f"record not found: {record_id}")
        tombstone = replace(
            record,
            is_deleted=True,
            deleted_at=deleted_at,
            deleted_reason=reason,
            valid_to=record.valid_to or deleted_at,
            updated_at=deleted_at,
        )
        with self._write_connection() as conn:
            self._put_record_payload(conn, tombstone)
            self._emit_change(
                conn,
                object_type="record",
                object_id=record_id,
                payload={
                    "record_id": record_id,
                    "deleted_at": deleted_at,
                    "reason": reason,
                },
                namespace=tombstone.effective_namespace,
                schema_identifiers={"node_label": str(tombstone.type)},
                operation="delete",
            )
        return tombstone

    def cascade_tombstones(
        self,
        record_id: str,
        *,
        deleted_at: str,
        reason: str,
    ) -> DeletionCascadeResult:
        tombstone = self.tombstone_record(
            record_id,
            deleted_at=deleted_at,
            reason=reason,
        )
        removed_embedding_keys = [
            f"{embedding.record_id}:{embedding.vector_space}"
            for embedding in self.list_embeddings(
                EmbeddingListOptions(record_id=record_id)
            )
        ]
        with self._write_connection() as conn:
            relation_rows = conn.execute(
                """
                SELECT relation_id FROM sophiagraph_relations
                 WHERE source_record_id = ? OR target_record_id = ?
                """,
                (record_id, record_id),
            ).fetchall()
            relation_ids = [str(row["relation_id"]) for row in relation_rows]
            conn.execute(
                """
                DELETE FROM sophiagraph_relations
                 WHERE source_record_id = ? OR target_record_id = ?
                """,
                (record_id, record_id),
            )
            link_rows = conn.execute(
                """
                SELECT link_id FROM sophiagraph_links
                 WHERE source_record_id = ? OR target_record_id = ?
                """,
                (record_id, record_id),
            ).fetchall()
            link_ids = [str(row["link_id"]) for row in link_rows]
            conn.execute(
                """
                DELETE FROM sophiagraph_links
                 WHERE source_record_id = ? OR target_record_id = ?
                """,
                (record_id, record_id),
            )
            block_rows = conn.execute(
                "SELECT block_id FROM sophiagraph_blocks WHERE record_id = ?",
                (record_id,),
            ).fetchall()
            block_ids = [str(row["block_id"]) for row in block_rows]
            conn.execute(
                "DELETE FROM sophiagraph_blocks WHERE record_id = ?",
                (record_id,),
            )
            conn.execute(
                "DELETE FROM sophiagraph_embeddings WHERE record_id = ?",
                (record_id,),
            )
        return DeletionCascadeResult(
            root_record_id=record_id,
            tombstoned_record_ids=[tombstone.id],
            removed_relation_ids=relation_ids,
            removed_link_ids=link_ids,
            removed_block_ids=block_ids,
            removed_embedding_keys=removed_embedding_keys,
        )

    def erasure_audit_export(
        self,
        *,
        record_id: str | None = None,
        namespaces: list[MemoryNamespace] | None = None,
    ) -> ErasureAuditExport:
        with self._connect() as conn:
            clauses = ["is_deleted = 1"]
            params: list[Any] = []
            if record_id is not None:
                clauses.append("id = ?")
                params.append(record_id)
            namespace_sql, namespace_params = namespace_filter_sql(namespaces)
            if namespace_sql:
                clauses.append(namespace_sql)
                params.extend(namespace_params)
            rows = conn.execute(
                "SELECT payload_json FROM sophiagraph_records WHERE "
                + " AND ".join(clauses),
                params,
            ).fetchall()
        records = [self._record_from_row(row) for row in rows]
        return ErasureAuditExport(
            entries=[
                ErasureAuditEntry(
                    record_id=record.id,
                    namespace=record.effective_namespace,
                    deleted_at=record.deleted_at or record.updated_at,
                    reason=record.deleted_reason or "",
                    cascaded=bool(record.meta.get("cascade_deleted", False)),
                )
                for record in records
            ]
        )

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

    def put_retention_snapshot(self, snapshot: RetentionSnapshot) -> str:
        with self._write_connection() as conn:
            self._put_aux_object(
                conn,
                object_kind="retention_snapshot",
                object_id=f"{namespace_key(snapshot.namespace)}:{snapshot.name}",
                namespace=snapshot.namespace,
                updated_at=snapshot.created_at,
                payload=snapshot.to_dict(),
            )
            self._emit_change(
                conn,
                object_type="retention_snapshot",
                object_id=snapshot.snapshot_id,
                payload=snapshot.to_dict(),
                namespace=snapshot.namespace,
                schema_identifiers={"node_label": "retention_snapshot"},
            )
        return snapshot.snapshot_id

    def get_retention_snapshot(
        self,
        *,
        name: str,
        namespace: MemoryNamespace,
    ) -> RetentionSnapshot | None:
        payload = self._get_aux_object(
            "retention_snapshot",
            f"{namespace_key(namespace)}:{name}",
        )
        return None if payload is None else RetentionSnapshot.from_dict(payload)

    def list_retention_snapshots(
        self,
        *,
        namespaces: list[MemoryNamespace] | None = None,
        limit: int | None = None,
    ) -> list[RetentionSnapshot]:
        payloads = self._list_aux_objects(
            "retention_snapshot",
            namespaces=namespaces,
            limit=limit,
        )
        return [RetentionSnapshot.from_dict(payload) for payload in payloads]

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

    # SEFT-02 + SEFT-03 + SEFT-04 entity/fact/contradiction/summary helpers.
    # SEPM-02 + SEPM-03 episode/step/outcome/decision/procedure helpers.

    def _ns_values(self, namespace) -> dict[str, Any]:
        return namespace.as_dict()

    def _ns_columns_clause(self, namespace_values: dict[str, Any]):
        cols = (
            "tenant_id",
            "org_id",
            "user_id",
            "agent_id",
            "session_id",
            "conversation_id",
            "project_id",
            "graph_id",
        )
        return tuple(namespace_values.get(col) for col in cols)

    def _ns_filter(self, namespaces):
        from sophiagraph.storage.sqlite_support import namespace_filter_sql

        return namespace_filter_sql(namespaces)

    def put_entity(self, entity) -> str:
        from sophiagraph.storage.graph_helpers import entity_to_dict

        payload = entity_to_dict(entity)
        ns_vals = self._ns_values(entity.namespace)
        cols = self._ns_columns_clause(ns_vals)
        with self._write_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO sophiagraph_entities(
                    entity_id, canonical_name, entity_type, confidence,
                    invalidated_at,
                    tenant_id, org_id, user_id, agent_id, session_id,
                    conversation_id, project_id, graph_id,
                    created_at, updated_at, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entity.entity_id,
                    entity.canonical_name,
                    entity.entity_type,
                    float(entity.confidence),
                    entity.invalidated_at,
                    *cols,
                    entity.created_at,
                    entity.updated_at,
                    json_dumps(payload),
                ),
            )
            self._emit_change(
                conn,
                object_type="entity",
                object_id=entity.entity_id,
                payload=payload,
                namespace=entity.namespace,
                schema_identifiers={
                    "node_label": "entity",
                    "entity_type": entity.entity_type,
                },
            )
        return entity.entity_id

    def get_entity(self, entity_id):
        from sophiagraph.storage.graph_helpers import entity_from_dict

        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload_json FROM sophiagraph_entities WHERE entity_id = ?",
                (entity_id,),
            ).fetchone()
        return None if row is None else entity_from_dict(row_json(row))

    def list_entities(
        self,
        *,
        namespaces=None,
        canonical_name=None,
        entity_type=None,
        include_invalidated=False,
        limit=None,
    ):
        from sophiagraph.storage.graph_helpers import entity_from_dict

        clauses = ["1=1"]
        params: list[Any] = []
        if canonical_name:
            clauses.append("canonical_name = ?")
            params.append(canonical_name)
        if entity_type:
            clauses.append("entity_type = ?")
            params.append(entity_type)
        if not include_invalidated:
            clauses.append("invalidated_at IS NULL")
        ns_sql, ns_params = self._ns_filter(namespaces)
        if ns_sql:
            clauses.append(ns_sql)
            params.extend(ns_params)
        sql = (
            "SELECT payload_json FROM sophiagraph_entities WHERE "
            + " AND ".join(clauses)
            + " ORDER BY canonical_name ASC, entity_id ASC"
        )
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [entity_from_dict(row_json(row)) for row in rows]

    def put_entity_alias(self, alias) -> str:
        from sophiagraph.storage.graph_helpers import entity_alias_to_dict

        payload = entity_alias_to_dict(alias)
        ns_vals = self._ns_values(alias.namespace)
        cols = self._ns_columns_clause(ns_vals)
        with self._write_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO sophiagraph_entity_aliases(
                    alias_id, alias_name, entity_id, original_entity_id, is_primary,
                    tenant_id, org_id, user_id, agent_id, session_id,
                    conversation_id, project_id, graph_id,
                    created_at, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    alias.alias_id,
                    alias.alias_name,
                    alias.entity_id,
                    alias.original_entity_id,
                    1 if alias.is_primary else 0,
                    *cols,
                    alias.created_at,
                    json_dumps(payload),
                ),
            )
            self._emit_change(
                conn,
                object_type="entity_alias",
                object_id=alias.alias_id,
                payload=payload,
                namespace=alias.namespace,
                schema_identifiers={
                    "node_label": "entity_alias",
                    "entity_id": alias.entity_id,
                },
            )
        return alias.alias_id

    def list_entity_aliases(
        self,
        *,
        entity_id=None,
        alias_name=None,
        namespaces=None,
        limit=None,
    ):
        from sophiagraph.storage.graph_helpers import entity_alias_from_dict

        clauses = ["1=1"]
        params: list[Any] = []
        if entity_id:
            clauses.append("entity_id = ?")
            params.append(entity_id)
        if alias_name:
            clauses.append("alias_name = ?")
            params.append(alias_name)
        ns_sql, ns_params = self._ns_filter(namespaces)
        if ns_sql:
            clauses.append(ns_sql)
            params.extend(ns_params)
        sql = (
            "SELECT payload_json FROM sophiagraph_entity_aliases WHERE "
            + " AND ".join(clauses)
            + " ORDER BY alias_name ASC, alias_id ASC"
        )
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [entity_alias_from_dict(row_json(row)) for row in rows]

    def put_fact(self, fact) -> str:
        from sophiagraph.storage.graph_helpers import fact_to_dict

        payload = fact_to_dict(fact)
        ns_vals = self._ns_values(fact.namespace)
        cols = self._ns_columns_clause(ns_vals)
        with self._write_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO sophiagraph_facts(
                    fact_id, subject_entity_id, predicate, object_entity_id,
                    object_literal, confidence, valid_from, valid_to,
                    observed_at, invalidated_at, superseded_by_fact_id,
                    tenant_id, org_id, user_id, agent_id, session_id,
                    conversation_id, project_id, graph_id,
                    created_at, updated_at, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    fact.fact_id,
                    fact.subject_entity_id,
                    fact.predicate,
                    fact.object_entity_id,
                    fact.object_literal,
                    float(fact.confidence),
                    fact.valid_from,
                    fact.valid_to,
                    fact.observed_at,
                    fact.invalidated_at,
                    fact.superseded_by_fact_id,
                    *cols,
                    fact.created_at,
                    fact.updated_at,
                    json_dumps(payload),
                ),
            )
            self._emit_change(
                conn,
                object_type="fact",
                object_id=fact.fact_id,
                payload=payload,
                namespace=fact.namespace,
                schema_identifiers={
                    "node_label": "fact",
                    "predicate": fact.predicate,
                },
            )
        return fact.fact_id

    def get_fact(self, fact_id):
        from sophiagraph.storage.graph_helpers import fact_from_dict

        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload_json FROM sophiagraph_facts WHERE fact_id = ?",
                (fact_id,),
            ).fetchone()
        return None if row is None else fact_from_dict(row_json(row))

    def list_facts(
        self,
        *,
        namespaces=None,
        subject_entity_id=None,
        object_entity_id=None,
        predicate=None,
        valid_at=None,
        learned_at=None,
        active_state="active",
        source_episode_id=None,
        include_invalidated=False,
        limit=None,
    ):
        from sophiagraph.storage.graph_helpers import fact_from_dict

        clauses = ["1=1"]
        params: list[Any] = []
        if subject_entity_id:
            clauses.append("subject_entity_id = ?")
            params.append(subject_entity_id)
        if object_entity_id:
            clauses.append("object_entity_id = ?")
            params.append(object_entity_id)
        if predicate:
            clauses.append("predicate = ?")
            params.append(predicate)
        # to ``active_state="all"``.
        effective_state = "all" if include_invalidated else active_state
        if effective_state == "active":
            clauses.append("invalidated_at IS NULL AND superseded_by_fact_id IS NULL")
        elif effective_state == "historical":
            clauses.append(
                "(invalidated_at IS NOT NULL OR superseded_by_fact_id IS NOT NULL)"
            )
        if valid_at is not None:
            clauses.append("(valid_from IS NULL OR valid_from <= ?)")
            params.append(valid_at)
            clauses.append("(valid_to IS NULL OR valid_to > ?)")
            params.append(valid_at)
        if learned_at is not None:
            clauses.append("(observed_at IS NULL OR observed_at <= ?)")
            params.append(learned_at)
        ns_sql, ns_params = self._ns_filter(namespaces)
        if ns_sql:
            clauses.append(ns_sql)
            params.extend(ns_params)
        sql = (
            "SELECT payload_json FROM sophiagraph_facts WHERE "
            + " AND ".join(clauses)
            + " ORDER BY observed_at DESC, fact_id ASC"
        )
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        facts = [fact_from_dict(row_json(row)) for row in rows]
        if source_episode_id:
            facts = [f for f in facts if source_episode_id in f.source_episode_ids]
        return facts

    def record_contradiction(self, contradiction):
        from dataclasses import replace as dc_replace

        from sophiagraph.storage.entity_episode_store import (
            validate_contradiction_references,
        )
        from sophiagraph.storage.graph_helpers import contradiction_to_dict

        # Load known fact IDs first.
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT fact_id FROM sophiagraph_facts WHERE fact_id IN (?, ?)",
                (contradiction.target_fact_id, contradiction.contradicting_fact_id),
            ).fetchall()
        known = {row["fact_id"] for row in rows}
        validate_contradiction_references(contradiction, known_fact_ids=known)

        # Apply decision semantics in-place, preserving evidence.
        if contradiction.decision in ("supersedes", "invalidates_target"):
            target = self.get_fact(contradiction.target_fact_id)
            if target is None:  # pragma: no cover - guarded above
                from sophiagraph.contracts.errors import InvalidSupersessionError

                raise InvalidSupersessionError(
                    f"target fact missing after preflight: {contradiction.target_fact_id!r}"
                )
            if contradiction.decision == "supersedes":
                updated = dc_replace(
                    target,
                    invalidated_at=contradiction.decided_at,
                    superseded_by_fact_id=contradiction.contradicting_fact_id,
                )
            else:
                updated = dc_replace(target, invalidated_at=contradiction.decided_at)
            self.put_fact(updated)

        payload = contradiction_to_dict(contradiction)
        ns_vals = self._ns_values(contradiction.namespace)
        cols = self._ns_columns_clause(ns_vals)
        with self._write_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO sophiagraph_contradictions(
                    contradiction_id, target_fact_id, contradicting_fact_id,
                    decision, deciding_actor, decided_at,
                    tenant_id, org_id, user_id, agent_id, session_id,
                    conversation_id, project_id, graph_id, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    contradiction.contradiction_id,
                    contradiction.target_fact_id,
                    contradiction.contradicting_fact_id,
                    contradiction.decision,
                    contradiction.deciding_actor,
                    contradiction.decided_at,
                    *cols,
                    json_dumps(payload),
                ),
            )
            self._emit_change(
                conn,
                object_type="contradiction",
                object_id=contradiction.contradiction_id,
                payload=payload,
                namespace=contradiction.namespace,
                schema_identifiers={
                    "node_label": "contradiction",
                    "decision": contradiction.decision,
                },
            )
        return contradiction

    def list_contradictions(
        self,
        *,
        target_fact_id=None,
        contradicting_fact_id=None,
        namespaces=None,
        limit=None,
    ):
        from sophiagraph.storage.graph_helpers import contradiction_from_dict

        clauses = ["1=1"]
        params: list[Any] = []
        if target_fact_id:
            clauses.append("target_fact_id = ?")
            params.append(target_fact_id)
        if contradicting_fact_id:
            clauses.append("contradicting_fact_id = ?")
            params.append(contradicting_fact_id)
        ns_sql, ns_params = self._ns_filter(namespaces)
        if ns_sql:
            clauses.append(ns_sql)
            params.extend(ns_params)
        sql = (
            "SELECT payload_json FROM sophiagraph_contradictions WHERE "
            + " AND ".join(clauses)
            + " ORDER BY decided_at DESC, contradiction_id ASC"
        )
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [contradiction_from_dict(row_json(row)) for row in rows]

    def put_entity_summary(self, summary) -> str:
        from sophiagraph.storage.graph_helpers import entity_summary_to_dict

        payload = entity_summary_to_dict(summary)
        ns_vals = self._ns_values(summary.namespace)
        cols = self._ns_columns_clause(ns_vals)
        with self._write_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO sophiagraph_entity_summaries(
                    summary_id, entity_id,
                    tenant_id, org_id, user_id, agent_id, session_id,
                    conversation_id, project_id, graph_id,
                    created_at, updated_at, invalidated_at, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    summary.summary_id,
                    summary.entity_id,
                    *cols,
                    summary.created_at,
                    summary.updated_at,
                    summary.invalidated_at,
                    json_dumps(payload),
                ),
            )
            self._emit_change(
                conn,
                object_type="entity_summary",
                object_id=summary.summary_id,
                payload=payload,
                namespace=summary.namespace,
                schema_identifiers={
                    "node_label": "entity_summary",
                    "entity_id": summary.entity_id,
                },
            )
        return summary.summary_id

    def get_entity_summary(self, summary_id):
        from sophiagraph.storage.graph_helpers import entity_summary_from_dict

        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT payload_json
                FROM sophiagraph_entity_summaries
                WHERE summary_id = ?
                """,
                (summary_id,),
            ).fetchone()
        return None if row is None else entity_summary_from_dict(row_json(row))

    def list_entity_summaries(
        self,
        *,
        entity_id=None,
        namespaces=None,
        include_invalidated=False,
        limit=None,
    ):
        from sophiagraph.storage.graph_helpers import entity_summary_from_dict

        clauses = ["1=1"]
        params: list[Any] = []
        if entity_id:
            clauses.append("entity_id = ?")
            params.append(entity_id)
        if not include_invalidated:
            clauses.append("invalidated_at IS NULL")
        ns_sql, ns_params = self._ns_filter(namespaces)
        if ns_sql:
            clauses.append(ns_sql)
            params.extend(ns_params)
        sql = (
            "SELECT payload_json FROM sophiagraph_entity_summaries WHERE "
            + " AND ".join(clauses)
            + " ORDER BY updated_at DESC, summary_id ASC"
        )
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [entity_summary_from_dict(row_json(row)) for row in rows]

    # Episode + procedure rows.

    def put_episode(self, episode) -> str:
        from sophiagraph.storage.graph_helpers import episode_to_dict

        payload = episode_to_dict(episode)
        cols = self._ns_columns_clause(self._ns_values(episode.namespace))
        with self._write_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO sophiagraph_episodes(
                    episode_id, title, status, started_at, ended_at,
                    parent_episode_id, task_id,
                    tenant_id, org_id, user_id, agent_id, session_id,
                    conversation_id, project_id, graph_id, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    episode.episode_id,
                    episode.title,
                    episode.status,
                    episode.started_at,
                    episode.ended_at,
                    episode.parent_episode_id,
                    episode.task_id,
                    *cols,
                    json_dumps(payload),
                ),
            )
            self._emit_change(
                conn,
                object_type="episode",
                object_id=episode.episode_id,
                payload=payload,
                namespace=episode.namespace,
                schema_identifiers={"node_label": "episode", "status": episode.status},
            )
        return episode.episode_id

    def get_episode(self, episode_id):
        from sophiagraph.storage.graph_helpers import episode_from_dict

        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload_json FROM sophiagraph_episodes WHERE episode_id = ?",
                (episode_id,),
            ).fetchone()
        return None if row is None else episode_from_dict(row_json(row))

    def list_episodes(
        self,
        *,
        namespaces=None,
        status=None,
        task_id=None,
        artifact_id=None,
        tool_id=None,
        started_after=None,
        started_before=None,
        limit=None,
    ):
        from sophiagraph.storage.graph_helpers import episode_from_dict

        clauses = ["1=1"]
        params: list[Any] = []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if task_id:
            clauses.append("task_id = ?")
            params.append(task_id)
        if started_after:
            clauses.append("started_at >= ?")
            params.append(started_after)
        if started_before:
            clauses.append("started_at <= ?")
            params.append(started_before)
        ns_sql, ns_params = self._ns_filter(namespaces)
        if ns_sql:
            clauses.append(ns_sql)
            params.extend(ns_params)
        sql = (
            "SELECT payload_json FROM sophiagraph_episodes WHERE "
            + " AND ".join(clauses)
            + " ORDER BY started_at DESC, episode_id ASC"
        )
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        episodes = [episode_from_dict(row_json(row)) for row in rows]
        # artifact_id / tool_id filters apply post-hydration (they live
        # in the JSON list payload, not first-class columns).
        if artifact_id:
            episodes = [ep for ep in episodes if artifact_id in ep.artifact_ids]
        if tool_id:
            episodes = [ep for ep in episodes if tool_id in ep.tool_ids]
        return episodes

    def put_episode_step(self, step) -> str:
        from sophiagraph.storage.graph_helpers import episode_step_to_dict

        payload = episode_step_to_dict(step)
        cols = self._ns_columns_clause(self._ns_values(step.namespace))
        with self._write_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO sophiagraph_episode_steps(
                    step_id, episode_id, sequence, kind, occurred_at,
                    tool_id, tool_call_id, artifact_id, file_path,
                    tenant_id, org_id, user_id, agent_id, session_id,
                    conversation_id, project_id, graph_id, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    step.step_id,
                    step.episode_id,
                    int(step.sequence),
                    step.kind,
                    step.occurred_at,
                    step.tool_id,
                    step.tool_call_id,
                    step.artifact_id,
                    step.file_path,
                    *cols,
                    json_dumps(payload),
                ),
            )
            self._emit_change(
                conn,
                object_type="episode_step",
                object_id=step.step_id,
                payload=payload,
                namespace=step.namespace,
                schema_identifiers={"node_label": "episode_step", "kind": step.kind},
            )
        return step.step_id

    def list_episode_steps(self, *, episode_id, kind=None, limit=None):
        from sophiagraph.storage.graph_helpers import episode_step_from_dict

        clauses = ["episode_id = ?"]
        params: list[Any] = [episode_id]
        if kind:
            clauses.append("kind = ?")
            params.append(kind)
        sql = (
            "SELECT payload_json FROM sophiagraph_episode_steps WHERE "
            + " AND ".join(clauses)
            + " ORDER BY sequence ASC, step_id ASC"
        )
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [episode_step_from_dict(row_json(row)) for row in rows]

    def put_outcome(self, outcome) -> str:
        from sophiagraph.storage.graph_helpers import outcome_to_dict

        payload = outcome_to_dict(outcome)
        cols = self._ns_columns_clause(self._ns_values(outcome.namespace))
        with self._write_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO sophiagraph_outcomes(
                    outcome_id, status, occurred_at, episode_id, step_id,
                    tenant_id, org_id, user_id, agent_id, session_id,
                    conversation_id, project_id, graph_id, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    outcome.outcome_id,
                    outcome.status,
                    outcome.occurred_at,
                    outcome.episode_id,
                    outcome.step_id,
                    *cols,
                    json_dumps(payload),
                ),
            )
            self._emit_change(
                conn,
                object_type="outcome",
                object_id=outcome.outcome_id,
                payload=payload,
                namespace=outcome.namespace,
                schema_identifiers={"node_label": "outcome", "status": outcome.status},
            )
        return outcome.outcome_id

    def list_outcomes(
        self,
        *,
        episode_id=None,
        step_id=None,
        status=None,
        namespaces=None,
        limit=None,
    ):
        from sophiagraph.storage.graph_helpers import outcome_from_dict

        clauses = ["1=1"]
        params: list[Any] = []
        if episode_id:
            clauses.append("episode_id = ?")
            params.append(episode_id)
        if step_id:
            clauses.append("step_id = ?")
            params.append(step_id)
        if status:
            clauses.append("status = ?")
            params.append(status)
        ns_sql, ns_params = self._ns_filter(namespaces)
        if ns_sql:
            clauses.append(ns_sql)
            params.extend(ns_params)
        sql = (
            "SELECT payload_json FROM sophiagraph_outcomes WHERE "
            + " AND ".join(clauses)
            + " ORDER BY occurred_at DESC, outcome_id ASC"
        )
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [outcome_from_dict(row_json(row)) for row in rows]

    def put_decision(self, decision) -> str:
        from sophiagraph.storage.graph_helpers import decision_to_dict

        payload = decision_to_dict(decision)
        cols = self._ns_columns_clause(self._ns_values(decision.namespace))
        with self._write_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO sophiagraph_decisions(
                    decision_id, title, chosen, occurred_at, episode_id, step_id,
                    tenant_id, org_id, user_id, agent_id, session_id,
                    conversation_id, project_id, graph_id, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    decision.decision_id,
                    decision.title,
                    decision.chosen,
                    decision.occurred_at,
                    decision.episode_id,
                    decision.step_id,
                    *cols,
                    json_dumps(payload),
                ),
            )
            self._emit_change(
                conn,
                object_type="decision",
                object_id=decision.decision_id,
                payload=payload,
                namespace=decision.namespace,
                schema_identifiers={"node_label": "decision"},
            )
        return decision.decision_id

    def list_decisions(self, *, episode_id=None, namespaces=None, limit=None):
        from sophiagraph.storage.graph_helpers import decision_from_dict

        clauses = ["1=1"]
        params: list[Any] = []
        if episode_id:
            clauses.append("episode_id = ?")
            params.append(episode_id)
        ns_sql, ns_params = self._ns_filter(namespaces)
        if ns_sql:
            clauses.append(ns_sql)
            params.extend(ns_params)
        sql = (
            "SELECT payload_json FROM sophiagraph_decisions WHERE "
            + " AND ".join(clauses)
            + " ORDER BY occurred_at DESC, decision_id ASC"
        )
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [decision_from_dict(row_json(row)) for row in rows]

    def put_procedure(self, procedure) -> str:
        from sophiagraph.storage.graph_helpers import procedure_to_dict

        payload = procedure_to_dict(procedure)
        cols = self._ns_columns_clause(self._ns_values(procedure.namespace))
        with self._write_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO sophiagraph_procedures(
                    procedure_id, title, promotion_tier, created_at,
                    updated_at, invalidated_at,
                    tenant_id, org_id, user_id, agent_id, session_id,
                    conversation_id, project_id, graph_id, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    procedure.procedure_id,
                    procedure.title,
                    procedure.promotion_tier,
                    procedure.created_at,
                    procedure.updated_at,
                    procedure.invalidated_at,
                    *cols,
                    json_dumps(payload),
                ),
            )
            self._emit_change(
                conn,
                object_type="procedure",
                object_id=procedure.procedure_id,
                payload=payload,
                namespace=procedure.namespace,
                schema_identifiers={
                    "node_label": "procedure",
                    "promotion_tier": procedure.promotion_tier,
                },
            )
        return procedure.procedure_id

    def get_procedure(self, procedure_id):
        from sophiagraph.storage.graph_helpers import procedure_from_dict

        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload_json FROM sophiagraph_procedures WHERE procedure_id = ?",
                (procedure_id,),
            ).fetchone()
        return None if row is None else procedure_from_dict(row_json(row))

    def list_procedures(
        self,
        *,
        namespaces=None,
        promotion_tier=None,
        include_invalidated=False,
        limit=None,
    ):
        from sophiagraph.storage.graph_helpers import procedure_from_dict

        clauses = ["1=1"]
        params: list[Any] = []
        if promotion_tier:
            clauses.append("promotion_tier = ?")
            params.append(promotion_tier)
        if not include_invalidated:
            clauses.append("invalidated_at IS NULL")
        ns_sql, ns_params = self._ns_filter(namespaces)
        if ns_sql:
            clauses.append(ns_sql)
            params.extend(ns_params)
        sql = (
            "SELECT payload_json FROM sophiagraph_procedures WHERE "
            + " AND ".join(clauses)
            + " ORDER BY updated_at DESC, procedure_id ASC"
        )
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [procedure_from_dict(row_json(row)) for row in rows]

    def put_raw_episode(self, episode) -> str:
        from sophiagraph.storage.graph_helpers import raw_episode_to_dict

        payload = raw_episode_to_dict(episode)
        cols = self._ns_columns_clause(self._ns_values(episode.namespace))
        with self._write_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO sophiagraph_raw_episodes(
                    episode_id, kind, source, source_id, occurred_at, ingested_at,
                    invalidated_at, actor,
                    tenant_id, org_id, user_id, agent_id, session_id,
                    conversation_id, project_id, graph_id, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    episode.episode_id,
                    episode.kind,
                    episode.source,
                    episode.source_id,
                    episode.occurred_at,
                    episode.ingested_at,
                    episode.invalidated_at,
                    episode.actor,
                    *cols,
                    json_dumps(payload),
                ),
            )
            self._emit_change(
                conn,
                object_type="raw_episode",
                object_id=episode.episode_id,
                payload=payload,
                namespace=episode.namespace,
                schema_identifiers={
                    "node_label": "raw_episode",
                    "kind": episode.kind,
                },
            )
        return episode.episode_id

    def get_raw_episode(self, episode_id):
        from sophiagraph.storage.graph_helpers import raw_episode_from_dict

        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload_json FROM sophiagraph_raw_episodes WHERE episode_id = ?",
                (episode_id,),
            ).fetchone()
        return None if row is None else raw_episode_from_dict(row_json(row))

    def list_raw_episodes(
        self,
        *,
        namespaces=None,
        kind=None,
        source=None,
        occurred_after=None,
        occurred_before=None,
        include_invalidated=False,
        limit=None,
    ):
        from sophiagraph.storage.entity_episode_store import RawEpisodeListOptions
        from sophiagraph.storage.graph_helpers import raw_episode_from_dict

        options = RawEpisodeListOptions(
            namespaces=namespaces,
            kind=kind,
            source=source,
            occurred_after=occurred_after,
            occurred_before=occurred_before,
            include_invalidated=include_invalidated,
            limit=limit,
        )
        clauses = ["1=1"]
        params: list[Any] = []
        if options.kind:
            clauses.append("kind = ?")
            params.append(options.kind)
        if options.source:
            clauses.append("source = ?")
            params.append(options.source)
        if options.occurred_after:
            clauses.append("occurred_at >= ?")
            params.append(options.occurred_after)
        if options.occurred_before:
            clauses.append("occurred_at <= ?")
            params.append(options.occurred_before)
        if not options.include_invalidated:
            clauses.append("invalidated_at IS NULL")
        ns_sql, ns_params = self._ns_filter(options.namespaces)
        if ns_sql:
            clauses.append(ns_sql)
            params.extend(ns_params)
        sql = (
            "SELECT payload_json FROM sophiagraph_raw_episodes WHERE "
            + " AND ".join(clauses)
            + " ORDER BY occurred_at DESC, episode_id ASC"
        )
        if options.limit is not None:
            sql += " LIMIT ?"
            params.append(int(options.limit))
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [raw_episode_from_dict(row_json(row)) for row in rows]

    def put_fact_convergence_link(self, link) -> str:
        from sophiagraph.storage.graph_helpers import fact_convergence_link_to_dict

        payload = fact_convergence_link_to_dict(link)
        cols = self._ns_columns_clause(self._ns_values(link.namespace))
        with self._write_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO sophiagraph_fact_convergence_links(
                    link_id, fact_id, episode_id, role, confidence, created_at,
                    tenant_id, org_id, user_id, agent_id, session_id,
                    conversation_id, project_id, graph_id, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    link.link_id,
                    link.fact_id,
                    link.episode_id,
                    link.role,
                    float(link.confidence),
                    link.created_at,
                    *cols,
                    json_dumps(payload),
                ),
            )
            self._emit_change(
                conn,
                object_type="fact_convergence_link",
                object_id=link.link_id,
                payload=payload,
                namespace=link.namespace,
                schema_identifiers={
                    "node_label": "fact_convergence_link",
                    "role": link.role,
                },
            )
        return link.link_id

    def list_fact_convergence_links(
        self,
        *,
        fact_id=None,
        episode_id=None,
        namespaces=None,
        limit=None,
    ):
        from sophiagraph.storage.graph_helpers import fact_convergence_link_from_dict

        clauses = ["1=1"]
        params: list[Any] = []
        if fact_id:
            clauses.append("fact_id = ?")
            params.append(fact_id)
        if episode_id:
            clauses.append("episode_id = ?")
            params.append(episode_id)
        ns_sql, ns_params = self._ns_filter(namespaces)
        if ns_sql:
            clauses.append(ns_sql)
            params.extend(ns_params)
        sql = (
            "SELECT payload_json FROM sophiagraph_fact_convergence_links WHERE "
            + " AND ".join(clauses)
            + " ORDER BY created_at ASC, link_id ASC"
        )
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [fact_convergence_link_from_dict(row_json(row)) for row in rows]

    # Ontology storage.

    def put_ontology(self, ontology):
        from sophiagraph.contracts.errors import OntologyVersionConflictError
        from sophiagraph.storage.graph_helpers import (
            ontology_from_dict,
            ontology_to_dict,
        )

        payload = ontology_to_dict(ontology)
        cols = self._ns_columns_clause(self._ns_values(ontology.namespace))
        # Detect conflicting re-registration.
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload_json FROM sophiagraph_ontologies "
                "WHERE ontology_id = ? AND version = ?",
                (ontology.ontology_id, ontology.version),
            ).fetchone()
        if row is not None:
            existing = ontology_from_dict(row_json(row))
            if ontology_to_dict(existing) != payload:
                raise OntologyVersionConflictError(
                    f"ontology {ontology.ontology_id!r}@{ontology.version!r} already "
                    "exists with a different payload; pick a new version",
                    details={
                        "ontology_id": ontology.ontology_id,
                        "version": ontology.version,
                    },
                )
        with self._write_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO sophiagraph_ontologies(
                    ontology_id, version, owner, compatibility,
                    tenant_id, org_id, user_id, agent_id, session_id,
                    conversation_id, project_id, graph_id,
                    created_at, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ontology.ontology_id,
                    ontology.version,
                    ontology.owner,
                    ontology.compatibility,
                    *cols,
                    ontology.created_at,
                    json_dumps(payload),
                ),
            )
            self._emit_change(
                conn,
                object_type="ontology",
                object_id=f"{ontology.ontology_id}@{ontology.version}",
                payload=payload,
                namespace=ontology.namespace,
                schema_identifiers={
                    "node_label": "ontology",
                    "ontology_id": ontology.ontology_id,
                    "version": ontology.version,
                },
            )
        return (ontology.ontology_id, ontology.version)

    def get_ontology(self, *, ontology_id, version):
        from sophiagraph.storage.graph_helpers import ontology_from_dict

        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload_json FROM sophiagraph_ontologies "
                "WHERE ontology_id = ? AND version = ?",
                (ontology_id, version),
            ).fetchone()
        return None if row is None else ontology_from_dict(row_json(row))

    def list_ontologies(
        self,
        *,
        ontology_id=None,
        owner=None,
        namespaces=None,
        limit=None,
    ):
        from sophiagraph.storage.graph_helpers import ontology_from_dict

        clauses = ["1=1"]
        params: list[Any] = []
        if ontology_id:
            clauses.append("ontology_id = ?")
            params.append(ontology_id)
        if owner:
            clauses.append("owner = ?")
            params.append(owner)
        ns_sql, ns_params = self._ns_filter(namespaces)
        if ns_sql:
            clauses.append(ns_sql)
            params.extend(ns_params)
        sql = (
            "SELECT payload_json FROM sophiagraph_ontologies WHERE "
            + " AND ".join(clauses)
            + " ORDER BY ontology_id ASC, version ASC"
        )
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [ontology_from_dict(row_json(row)) for row in rows]

    # Artifact reference storage.

    def put_artifact(self, artifact):
        from dataclasses import asdict

        payload = asdict(artifact)
        payload["namespace"] = artifact.namespace.as_dict()
        cols = self._ns_columns_clause(self._ns_values(artifact.namespace))
        with self._write_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO sophiagraph_artifacts(
                    artifact_id, uri, sha256, mime, size_bytes,
                    source_class, retention, source_owner,
                    target_record_id, derived_text_record_id,
                    tenant_id, org_id, user_id, agent_id, session_id,
                    conversation_id, project_id, graph_id,
                    created_at, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    artifact.artifact_id,
                    artifact.uri,
                    artifact.sha256,
                    artifact.mime,
                    artifact.size_bytes,
                    artifact.source_class,
                    artifact.retention,
                    artifact.source_owner,
                    artifact.target_record_id,
                    artifact.derived_text_record_id,
                    *cols,
                    artifact.created_at,
                    json_dumps(payload),
                ),
            )
            self._emit_change(
                conn,
                object_type="artifact",
                object_id=artifact.artifact_id,
                payload=payload,
                namespace=artifact.namespace,
                schema_identifiers={
                    "node_label": "artifact",
                    "artifact_id": artifact.artifact_id,
                },
            )
        return artifact.artifact_id

    def get_artifact(self, artifact_id):
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload_json FROM sophiagraph_artifacts WHERE artifact_id = ?",
                (artifact_id,),
            ).fetchone()
        return None if row is None else self._artifact_from_payload(row_json(row))

    def list_artifacts(
        self,
        *,
        namespaces=None,
        target_record_id=None,
        source_class=None,
        limit=None,
    ):
        clauses = ["1=1"]
        params: list[Any] = []
        if target_record_id is not None:
            clauses.append("target_record_id = ?")
            params.append(target_record_id)
        if source_class is not None:
            clauses.append("source_class = ?")
            params.append(source_class)
        ns_sql, ns_params = self._ns_filter(namespaces)
        if ns_sql:
            clauses.append(ns_sql)
            params.extend(ns_params)
        sql = (
            "SELECT payload_json FROM sophiagraph_artifacts WHERE "
            + " AND ".join(clauses)
            + " ORDER BY artifact_id ASC"
        )
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._artifact_from_payload(row_json(row)) for row in rows]

    @staticmethod
    def _artifact_from_payload(data):
        from sophiagraph.models import ArtifactRecord, MemoryNamespace

        payload = dict(data)
        ns = payload.get("namespace")
        if isinstance(ns, dict):
            payload["namespace"] = MemoryNamespace.from_dict(ns)
        return ArtifactRecord(**payload)

    # Canvas board storage.

    def put_canvas_board(self, board):
        from sophiagraph.canvas import canvas_board_to_dict

        payload = canvas_board_to_dict(board)
        cols = self._ns_columns_clause(self._ns_values(board.namespace))
        with self._write_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO sophiagraph_canvas_boards(
                    board_id,
                    tenant_id, org_id, user_id, agent_id, session_id,
                    conversation_id, project_id, graph_id,
                    created_at, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (board.board_id, *cols, None, json_dumps(payload)),
            )
            self._emit_change(
                conn,
                object_type="canvas",
                object_id=board.board_id,
                payload=payload,
                namespace=board.namespace,
                schema_identifiers={
                    "node_label": "canvas_board",
                    "board_id": board.board_id,
                },
            )
        return board.board_id

    def get_canvas_board(self, board_id):
        from sophiagraph.canvas import canvas_board_from_dict

        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload_json FROM sophiagraph_canvas_boards WHERE board_id = ?",
                (board_id,),
            ).fetchone()
        return None if row is None else canvas_board_from_dict(row_json(row))

    def list_canvas_boards(self, *, namespaces=None, limit=None):
        from sophiagraph.canvas import canvas_board_from_dict

        clauses = ["1=1"]
        params: list[Any] = []
        ns_sql, ns_params = self._ns_filter(namespaces)
        if ns_sql:
            clauses.append(ns_sql)
            params.extend(ns_params)
        sql = (
            "SELECT payload_json FROM sophiagraph_canvas_boards WHERE "
            + " AND ".join(clauses)
            + " ORDER BY board_id ASC"
        )
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [canvas_board_from_dict(row_json(row)) for row in rows]

    def delete_canvas_board(self, board_id):
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload_json FROM sophiagraph_canvas_boards WHERE board_id = ?",
                (board_id,),
            ).fetchone()
        if row is None:
            return False
        from sophiagraph.canvas import canvas_board_from_dict

        board = canvas_board_from_dict(row_json(row))
        with self._write_connection() as conn:
            conn.execute(
                "DELETE FROM sophiagraph_canvas_boards WHERE board_id = ?",
                (board_id,),
            )
            self._emit_change(
                conn,
                object_type="canvas",
                object_id=board_id,
                operation="delete",
                payload={"board_id": board_id, "deleted": True},
                namespace=board.namespace,
                schema_identifiers={
                    "node_label": "canvas_board",
                    "board_id": board_id,
                },
            )
            return True

    # Lifecycle policy storage.

    def put_lifecycle_policy(self, policy):
        from sophiagraph.storage.graph_helpers import lifecycle_policy_to_dict

        payload = lifecycle_policy_to_dict(policy)
        cols = self._ns_columns_clause(self._ns_values(policy.namespace_filter))
        with self._write_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO sophiagraph_lifecycle_policies(
                    policy_id, ttl_active_iso, ttl_cooling_iso,
                    tenant_id, org_id, user_id, agent_id, session_id,
                    conversation_id, project_id, graph_id,
                    created_at, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    policy.policy_id,
                    policy.ttl_active_iso,
                    policy.ttl_cooling_iso,
                    *cols,
                    policy.created_at_iso,
                    json_dumps(payload),
                ),
            )
            self._emit_change(
                conn,
                object_type="lifecycle_policy",
                object_id=policy.policy_id,
                payload=payload,
                namespace=policy.namespace_filter,
                schema_identifiers={
                    "node_label": "lifecycle_policy",
                    "policy_id": policy.policy_id,
                },
            )
        return policy.policy_id

    def get_lifecycle_policy(self, policy_id):
        from sophiagraph.storage.graph_helpers import lifecycle_policy_from_dict

        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload_json FROM sophiagraph_lifecycle_policies "
                "WHERE policy_id = ?",
                (policy_id,),
            ).fetchone()
        return None if row is None else lifecycle_policy_from_dict(row_json(row))

    def list_lifecycle_policies(
        self,
        *,
        namespaces=None,
        limit=None,
    ):
        from sophiagraph.storage.graph_helpers import lifecycle_policy_from_dict

        clauses = ["1=1"]
        params: list[Any] = []
        ns_sql, ns_params = self._ns_filter(namespaces)
        if ns_sql:
            clauses.append(ns_sql)
            params.extend(ns_params)
        sql = (
            "SELECT payload_json FROM sophiagraph_lifecycle_policies WHERE "
            + " AND ".join(clauses)
            + " ORDER BY policy_id ASC"
        )
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [lifecycle_policy_from_dict(row_json(row)) for row in rows]

    # Local-first sync, freshness, connector, and shared-block storage.

    def put_sync_conflict(self, conflict):
        from sophiagraph.sync import sync_conflict_to_dict

        payload = sync_conflict_to_dict(conflict)
        with self._write_connection() as conn:
            self._put_aux_object(
                conn,
                object_kind="sync_conflict",
                object_id=conflict.conflict_id,
                namespace=conflict.namespace,
                updated_at=conflict.created_at,
                payload=payload,
            )
            self._emit_change(
                conn,
                object_type="sync_conflict",
                object_id=conflict.conflict_id,
                payload=payload,
                namespace=conflict.namespace,
                schema_identifiers={
                    "node_label": "sync_conflict",
                    "kind": conflict.kind,
                },
            )
        return conflict.conflict_id

    def get_sync_conflict(self, conflict_id):
        from sophiagraph.sync import sync_conflict_from_dict

        payload = self._get_aux_object("sync_conflict", conflict_id)
        return None if payload is None else sync_conflict_from_dict(payload)

    def list_sync_conflicts(
        self,
        *,
        namespaces=None,
        status=None,
        source_id=None,
        limit=None,
    ):
        from sophiagraph.sync import sync_conflict_from_dict

        rows = [
            sync_conflict_from_dict(payload)
            for payload in self._list_aux_objects(
                "sync_conflict", namespaces=namespaces, limit=limit
            )
        ]
        if status is not None:
            rows = [row for row in rows if row.status == status]
        if source_id is not None:
            rows = [row for row in rows if row.source_id == source_id]
        return rows[: int(limit)] if limit is not None else rows

    def put_freshness_entry(self, entry):
        from sophiagraph.freshness import freshness_entry_to_dict

        payload = freshness_entry_to_dict(entry)
        with self._write_connection() as conn:
            self._put_aux_object(
                conn,
                object_kind="freshness_entry",
                object_id=entry.ledger_id,
                namespace=entry.namespace,
                updated_at=entry.updated_at,
                payload=payload,
            )
            self._emit_change(
                conn,
                object_type="freshness_entry",
                object_id=entry.ledger_id,
                payload=payload,
                namespace=entry.namespace,
                schema_identifiers={
                    "node_label": "freshness_entry",
                    "source_kind": entry.source_kind,
                },
            )
        return entry.ledger_id

    def get_freshness_entry(self, ledger_id):
        from sophiagraph.freshness import freshness_entry_from_dict

        payload = self._get_aux_object("freshness_entry", ledger_id)
        return None if payload is None else freshness_entry_from_dict(payload)

    def list_freshness_entries(
        self,
        *,
        namespaces=None,
        source_kind=None,
        source_id=None,
        status=None,
        limit=None,
    ):
        from sophiagraph.freshness import freshness_entry_from_dict

        rows = [
            freshness_entry_from_dict(payload)
            for payload in self._list_aux_objects(
                "freshness_entry", namespaces=namespaces, limit=limit
            )
        ]
        if source_kind is not None:
            rows = [row for row in rows if row.source_kind == source_kind]
        if source_id is not None:
            rows = [row for row in rows if row.source_id == source_id]
        if status is not None:
            rows = [row for row in rows if row.status == status]
        return rows[: int(limit)] if limit is not None else rows

    def put_source_entry(self, source):
        from sophiagraph.connectors import source_entry_to_dict

        payload = source_entry_to_dict(source)
        with self._write_connection() as conn:
            self._put_aux_object(
                conn,
                object_kind="source_registry",
                object_id=source.source_id,
                namespace=source.namespace,
                updated_at=source.updated_at,
                payload=payload,
            )
            self._emit_change(
                conn,
                object_type="source_registry",
                object_id=source.source_id,
                payload=payload,
                namespace=source.namespace,
                schema_identifiers={
                    "node_label": "source_registry",
                    "source_type": source.source_type,
                },
            )
        return source.source_id

    def get_source_entry(self, source_id):
        from sophiagraph.connectors import source_entry_from_dict

        payload = self._get_aux_object("source_registry", source_id)
        return None if payload is None else source_entry_from_dict(payload)

    def list_source_entries(
        self,
        *,
        namespaces=None,
        source_type=None,
        permission_scope=None,
        limit=None,
    ):
        from sophiagraph.connectors import source_entry_from_dict

        rows = [
            source_entry_from_dict(payload)
            for payload in self._list_aux_objects(
                "source_registry", namespaces=namespaces, limit=limit
            )
        ]
        if source_type is not None:
            rows = [row for row in rows if row.source_type == source_type]
        if permission_scope is not None:
            rows = [row for row in rows if row.permission_scope == permission_scope]
        return rows[: int(limit)] if limit is not None else rows

    def put_source_ingest(self, envelope):
        from sophiagraph.connectors import source_ingest_to_dict

        payload = source_ingest_to_dict(envelope)
        with self._write_connection() as conn:
            self._put_aux_object(
                conn,
                object_kind="source_ingest",
                object_id=envelope.ingest_id,
                namespace=envelope.namespace,
                updated_at=envelope.cursor,
                payload=payload,
            )
            self._emit_change(
                conn,
                object_type="source_ingest",
                object_id=envelope.ingest_id,
                payload=payload,
                namespace=envelope.namespace,
                schema_identifiers={
                    "node_label": "source_ingest",
                    "payload_kind": envelope.payload_kind,
                },
            )
        return envelope.ingest_id

    def get_source_ingest(self, ingest_id):
        from sophiagraph.connectors import source_ingest_from_dict

        payload = self._get_aux_object("source_ingest", ingest_id)
        return None if payload is None else source_ingest_from_dict(payload)

    def put_shared_block_attachment(self, attachment):
        from sophiagraph.shared_blocks import shared_attachment_to_dict

        payload = shared_attachment_to_dict(attachment)
        with self._write_connection() as conn:
            self._put_aux_object(
                conn,
                object_kind="shared_block_attachment",
                object_id=attachment.attachment_id,
                namespace=attachment.namespace,
                updated_at=attachment.attached_at,
                payload=payload,
            )
            self._emit_change(
                conn,
                object_type="shared_block_attachment",
                object_id=attachment.attachment_id,
                payload=payload,
                namespace=attachment.namespace,
                schema_identifiers={"node_label": "shared_block_attachment"},
            )
        return attachment.attachment_id

    def list_shared_block_attachments(
        self,
        *,
        block_id=None,
        namespaces=None,
        attached_agent_id=None,
        status=None,
        limit=None,
    ):
        from sophiagraph.shared_blocks import shared_attachment_from_dict

        rows = [
            shared_attachment_from_dict(payload)
            for payload in self._list_aux_objects(
                "shared_block_attachment", namespaces=namespaces, limit=limit
            )
        ]
        if block_id is not None:
            rows = [row for row in rows if row.block_id == block_id]
        if attached_agent_id is not None:
            rows = [row for row in rows if row.attached_agent_id == attached_agent_id]
        if status is not None:
            rows = [row for row in rows if row.status == status]
        return rows[: int(limit)] if limit is not None else rows

    def put_shared_block_mirror(self, mirror):
        from sophiagraph.shared_blocks import shared_mirror_to_dict

        payload = shared_mirror_to_dict(mirror)
        with self._write_connection() as conn:
            self._put_aux_object(
                conn,
                object_kind="shared_block_mirror",
                object_id=mirror.mirror_id,
                namespace=mirror.mirror_namespace,
                updated_at=mirror.last_synced_at,
                payload=payload,
            )
            self._emit_change(
                conn,
                object_type="shared_block_mirror",
                object_id=mirror.mirror_id,
                payload=payload,
                namespace=mirror.mirror_namespace,
                schema_identifiers={"node_label": "shared_block_mirror"},
            )
        return mirror.mirror_id

    def get_shared_block_mirror(self, mirror_id):
        from sophiagraph.shared_blocks import shared_mirror_from_dict

        payload = self._get_aux_object("shared_block_mirror", mirror_id)
        return None if payload is None else shared_mirror_from_dict(payload)

    def list_shared_block_mirrors(
        self,
        *,
        block_id=None,
        namespaces=None,
        status=None,
        limit=None,
    ):
        from sophiagraph.shared_blocks import shared_mirror_from_dict

        rows = [
            shared_mirror_from_dict(payload)
            for payload in self._list_aux_objects(
                "shared_block_mirror", namespaces=namespaces, limit=limit
            )
        ]
        if block_id is not None:
            rows = [row for row in rows if row.block_id == block_id]
        if status is not None:
            rows = [row for row in rows if row.status == status]
        return rows[: int(limit)] if limit is not None else rows

    def put_shared_block_conflict(self, conflict):
        from sophiagraph.shared_blocks import shared_conflict_to_dict

        payload = shared_conflict_to_dict(conflict)
        with self._write_connection() as conn:
            self._put_aux_object(
                conn,
                object_kind="shared_block_conflict",
                object_id=conflict.conflict_id,
                namespace=conflict.namespace,
                updated_at=conflict.created_at,
                payload=payload,
            )
            self._emit_change(
                conn,
                object_type="shared_block_conflict",
                object_id=conflict.conflict_id,
                payload=payload,
                namespace=conflict.namespace,
                schema_identifiers={"node_label": "shared_block_conflict"},
            )
        return conflict.conflict_id

    def list_shared_block_conflicts(
        self,
        *,
        block_id=None,
        namespaces=None,
        status=None,
        limit=None,
    ):
        from sophiagraph.shared_blocks import shared_conflict_from_dict

        rows = [
            shared_conflict_from_dict(payload)
            for payload in self._list_aux_objects(
                "shared_block_conflict", namespaces=namespaces, limit=limit
            )
        ]
        if block_id is not None:
            rows = [row for row in rows if row.block_id == block_id]
        if status is not None:
            rows = [row for row in rows if row.status == status]
        return rows[: int(limit)] if limit is not None else rows

    def put_shared_block_usage_event(self, event):
        from sophiagraph.shared_blocks import shared_usage_to_dict

        payload = shared_usage_to_dict(event)
        with self._write_connection() as conn:
            self._put_aux_object(
                conn,
                object_kind="shared_block_usage",
                object_id=event.event_id,
                namespace=event.namespace,
                updated_at=event.occurred_at,
                payload=payload,
            )
            self._emit_change(
                conn,
                object_type="shared_block_usage",
                object_id=event.event_id,
                payload=payload,
                namespace=event.namespace,
                schema_identifiers={
                    "node_label": "shared_block_usage",
                    "action": event.action,
                },
            )
        return event.event_id

    def list_shared_block_usage_events(
        self,
        *,
        block_id=None,
        namespaces=None,
        action=None,
        limit=None,
    ):
        from sophiagraph.shared_blocks import shared_usage_from_dict

        rows = [
            shared_usage_from_dict(payload)
            for payload in self._list_aux_objects(
                "shared_block_usage", namespaces=namespaces, limit=limit
            )
        ]
        if block_id is not None:
            rows = [row for row in rows if row.block_id == block_id]
        if action is not None:
            rows = [row for row in rows if row.action == action]
        return rows[: int(limit)] if limit is not None else rows
