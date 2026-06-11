"""SQLite schema, namespace, and FTS helpers for the durable store."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from sophiagraph.models import KnowledgeDocumentBlock, MemoryNamespace, MemoryRecord
from sophiagraph.portability.codec import json_dumps
from sophiagraph.query import StructuralSearchQuery

SCHEMA_VERSION = 17
SQLITE_BUSY_TIMEOUT_MS = 5000
SQLITE_CONNECT_TIMEOUT_SECONDS = SQLITE_BUSY_TIMEOUT_MS / 1000
SQLITE_JOURNAL_MODE = "wal"
SQLITE_SYNCHRONOUS = "normal"

NAMESPACE_COLUMNS = (
    "tenant_id",
    "org_id",
    "user_id",
    "agent_id",
    "session_id",
    "conversation_id",
    "project_id",
    "graph_id",
)


def row_json(row: sqlite3.Row, key: str = "payload_json") -> dict[str, Any]:
    raw = row[key]
    return json.loads(str(raw)) if raw else {}


def namespace_values(record: MemoryRecord) -> dict[str, str]:
    return record.effective_namespace.as_dict()


def namespace_from_payload(payload: dict[str, Any], scope: str) -> MemoryNamespace:
    raw_namespace = payload.get("namespace")
    if isinstance(raw_namespace, dict) and raw_namespace:
        return MemoryNamespace.from_dict(raw_namespace)
    return MemoryNamespace.from_scope(scope)


def namespace_filter_sql(
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


def ensure_schema(conn: sqlite3.Connection) -> None:
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

        CREATE TABLE IF NOT EXISTS sophiagraph_embeddings (
            record_id TEXT NOT NULL,
            vector_space TEXT NOT NULL,
            dimension INTEGER NOT NULL,
            provider TEXT NOT NULL,
            model TEXT NOT NULL,
            tenant_id TEXT,
            org_id TEXT,
            user_id TEXT,
            agent_id TEXT,
            session_id TEXT,
            conversation_id TEXT,
            project_id TEXT,
            graph_id TEXT,
            external_vector_id TEXT,
            updated_at TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            PRIMARY KEY(record_id, vector_space)
        );
        CREATE INDEX IF NOT EXISTS idx_sophiagraph_embeddings_record
            ON sophiagraph_embeddings(record_id, vector_space);
        CREATE INDEX IF NOT EXISTS idx_sophiagraph_embeddings_namespace
            ON sophiagraph_embeddings(
                tenant_id, org_id, user_id, agent_id, session_id,
                conversation_id, project_id, graph_id
            );

        CREATE TABLE IF NOT EXISTS sophiagraph_active_embedding_model_sets (
            namespace_key TEXT NOT NULL,
            vector_space TEXT NOT NULL,
            tenant_id TEXT,
            org_id TEXT,
            user_id TEXT,
            agent_id TEXT,
            session_id TEXT,
            conversation_id TEXT,
            project_id TEXT,
            graph_id TEXT,
            updated_at TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            PRIMARY KEY(namespace_key, vector_space)
        );
        CREATE INDEX IF NOT EXISTS idx_sophiagraph_active_embedding_model_sets_namespace
            ON sophiagraph_active_embedding_model_sets(
                tenant_id, org_id, user_id, agent_id, session_id,
                conversation_id, project_id, graph_id
            );

        CREATE TABLE IF NOT EXISTS sophiagraph_orphan_external_vector_ids (
            namespace_key TEXT NOT NULL,
            external_vector_id TEXT NOT NULL,
            tenant_id TEXT,
            org_id TEXT,
            user_id TEXT,
            agent_id TEXT,
            session_id TEXT,
            conversation_id TEXT,
            project_id TEXT,
            graph_id TEXT,
            last_seen_at TEXT NOT NULL,
            PRIMARY KEY(namespace_key, external_vector_id)
        );
        CREATE INDEX IF NOT EXISTS idx_sophiagraph_orphan_external_vector_ids_namespace
            ON sophiagraph_orphan_external_vector_ids(
                tenant_id, org_id, user_id, agent_id, session_id,
                conversation_id, project_id, graph_id
            );

        CREATE TABLE IF NOT EXISTS sophiagraph_memory_blocks (
            block_id TEXT PRIMARY KEY,
            class_name TEXT NOT NULL,
            mode TEXT NOT NULL,
            token_estimate INTEGER NOT NULL,
            source TEXT NOT NULL,
            tenant_id TEXT,
            org_id TEXT,
            user_id TEXT,
            agent_id TEXT,
            session_id TEXT,
            conversation_id TEXT,
            project_id TEXT,
            graph_id TEXT,
            created_at TEXT NOT NULL,
            last_updated_at TEXT NOT NULL,
            last_updated_by TEXT NOT NULL,
            stale_after TEXT,
            payload_json TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_sophiagraph_memory_blocks_class
            ON sophiagraph_memory_blocks(class_name, last_updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_sophiagraph_memory_blocks_namespace
            ON sophiagraph_memory_blocks(
                tenant_id, org_id, user_id, agent_id, session_id,
                conversation_id, project_id, graph_id
            );

        CREATE TABLE IF NOT EXISTS sophiagraph_entities (
            entity_id TEXT PRIMARY KEY,
            canonical_name TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            confidence REAL NOT NULL,
            invalidated_at TEXT,
            tenant_id TEXT, org_id TEXT, user_id TEXT, agent_id TEXT,
            session_id TEXT, conversation_id TEXT, project_id TEXT, graph_id TEXT,
            created_at TEXT, updated_at TEXT,
            payload_json TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_sophiagraph_entities_name
            ON sophiagraph_entities(canonical_name, entity_type);
        CREATE INDEX IF NOT EXISTS idx_sophiagraph_entities_namespace
            ON sophiagraph_entities(
                tenant_id, org_id, user_id, agent_id, session_id,
                conversation_id, project_id, graph_id
            );

        CREATE TABLE IF NOT EXISTS sophiagraph_entity_aliases (
            alias_id TEXT PRIMARY KEY,
            alias_name TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            original_entity_id TEXT NOT NULL,
            is_primary INTEGER NOT NULL DEFAULT 0,
            tenant_id TEXT, org_id TEXT, user_id TEXT, agent_id TEXT,
            session_id TEXT, conversation_id TEXT, project_id TEXT, graph_id TEXT,
            created_at TEXT,
            payload_json TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_sophiagraph_entity_aliases_lookup
            ON sophiagraph_entity_aliases(alias_name, entity_id);
        CREATE INDEX IF NOT EXISTS idx_sophiagraph_entity_aliases_entity
            ON sophiagraph_entity_aliases(entity_id);
        CREATE INDEX IF NOT EXISTS idx_sophiagraph_entity_aliases_namespace
            ON sophiagraph_entity_aliases(
                tenant_id, org_id, user_id, agent_id, session_id,
                conversation_id, project_id, graph_id
            );

        CREATE TABLE IF NOT EXISTS sophiagraph_facts (
            fact_id TEXT PRIMARY KEY,
            subject_entity_id TEXT NOT NULL,
            predicate TEXT NOT NULL,
            object_entity_id TEXT,
            object_literal TEXT,
            confidence REAL NOT NULL,
            valid_from TEXT,
            valid_to TEXT,
            observed_at TEXT,
            invalidated_at TEXT,
            superseded_by_fact_id TEXT,
            tenant_id TEXT, org_id TEXT, user_id TEXT, agent_id TEXT,
            session_id TEXT, conversation_id TEXT, project_id TEXT, graph_id TEXT,
            created_at TEXT, updated_at TEXT,
            payload_json TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_sophiagraph_facts_subject
            ON sophiagraph_facts(subject_entity_id, predicate);
        CREATE INDEX IF NOT EXISTS idx_sophiagraph_facts_object
            ON sophiagraph_facts(object_entity_id);
        CREATE INDEX IF NOT EXISTS idx_sophiagraph_facts_validity
            ON sophiagraph_facts(valid_from, valid_to, invalidated_at);
        CREATE INDEX IF NOT EXISTS idx_sophiagraph_facts_namespace
            ON sophiagraph_facts(
                tenant_id, org_id, user_id, agent_id, session_id,
                conversation_id, project_id, graph_id
            );

        CREATE TABLE IF NOT EXISTS sophiagraph_contradictions (
            contradiction_id TEXT PRIMARY KEY,
            target_fact_id TEXT NOT NULL,
            contradicting_fact_id TEXT NOT NULL,
            decision TEXT NOT NULL,
            deciding_actor TEXT NOT NULL,
            decided_at TEXT NOT NULL,
            tenant_id TEXT, org_id TEXT, user_id TEXT, agent_id TEXT,
            session_id TEXT, conversation_id TEXT, project_id TEXT, graph_id TEXT,
            payload_json TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_sophiagraph_contradictions_target
            ON sophiagraph_contradictions(target_fact_id);
        CREATE INDEX IF NOT EXISTS idx_sophiagraph_contradictions_contra
            ON sophiagraph_contradictions(contradicting_fact_id);

        CREATE TABLE IF NOT EXISTS sophiagraph_entity_summaries (
            summary_id TEXT PRIMARY KEY,
            entity_id TEXT NOT NULL,
            tenant_id TEXT, org_id TEXT, user_id TEXT, agent_id TEXT,
            session_id TEXT, conversation_id TEXT, project_id TEXT, graph_id TEXT,
            created_at TEXT, updated_at TEXT,
            invalidated_at TEXT,
            payload_json TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_sophiagraph_entity_summaries_entity
            ON sophiagraph_entity_summaries(entity_id, updated_at DESC);

        CREATE TABLE IF NOT EXISTS sophiagraph_episodes (
            episode_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            status TEXT NOT NULL,
            started_at TEXT NOT NULL,
            ended_at TEXT,
            parent_episode_id TEXT,
            task_id TEXT,
            tenant_id TEXT, org_id TEXT, user_id TEXT, agent_id TEXT,
            session_id TEXT, conversation_id TEXT, project_id TEXT, graph_id TEXT,
            payload_json TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_sophiagraph_episodes_status
            ON sophiagraph_episodes(status, started_at DESC);
        CREATE INDEX IF NOT EXISTS idx_sophiagraph_episodes_task
            ON sophiagraph_episodes(task_id);
        CREATE INDEX IF NOT EXISTS idx_sophiagraph_episodes_namespace
            ON sophiagraph_episodes(
                tenant_id, org_id, user_id, agent_id, session_id,
                conversation_id, project_id, graph_id
            );

        CREATE TABLE IF NOT EXISTS sophiagraph_episode_steps (
            step_id TEXT PRIMARY KEY,
            episode_id TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            kind TEXT NOT NULL,
            occurred_at TEXT NOT NULL,
            tool_id TEXT,
            tool_call_id TEXT,
            artifact_id TEXT,
            file_path TEXT,
            tenant_id TEXT, org_id TEXT, user_id TEXT, agent_id TEXT,
            session_id TEXT, conversation_id TEXT, project_id TEXT, graph_id TEXT,
            payload_json TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_sophiagraph_episode_steps_episode
            ON sophiagraph_episode_steps(episode_id, sequence);

        CREATE TABLE IF NOT EXISTS sophiagraph_outcomes (
            outcome_id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            occurred_at TEXT NOT NULL,
            episode_id TEXT,
            step_id TEXT,
            tenant_id TEXT, org_id TEXT, user_id TEXT, agent_id TEXT,
            session_id TEXT, conversation_id TEXT, project_id TEXT, graph_id TEXT,
            payload_json TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_sophiagraph_outcomes_episode
            ON sophiagraph_outcomes(episode_id, occurred_at DESC);
        CREATE INDEX IF NOT EXISTS idx_sophiagraph_outcomes_step
            ON sophiagraph_outcomes(step_id);

        CREATE TABLE IF NOT EXISTS sophiagraph_decisions (
            decision_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            chosen TEXT NOT NULL,
            occurred_at TEXT NOT NULL,
            episode_id TEXT,
            step_id TEXT,
            tenant_id TEXT, org_id TEXT, user_id TEXT, agent_id TEXT,
            session_id TEXT, conversation_id TEXT, project_id TEXT, graph_id TEXT,
            payload_json TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_sophiagraph_decisions_episode
            ON sophiagraph_decisions(episode_id, occurred_at DESC);

        CREATE TABLE IF NOT EXISTS sophiagraph_procedures (
            procedure_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            promotion_tier TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT,
            invalidated_at TEXT,
            tenant_id TEXT, org_id TEXT, user_id TEXT, agent_id TEXT,
            session_id TEXT, conversation_id TEXT, project_id TEXT, graph_id TEXT,
            payload_json TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_sophiagraph_procedures_tier
            ON sophiagraph_procedures(promotion_tier, updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_sophiagraph_procedures_namespace
            ON sophiagraph_procedures(
                tenant_id, org_id, user_id, agent_id, session_id,
                conversation_id, project_id, graph_id
            );

        CREATE TABLE IF NOT EXISTS sophiagraph_raw_episodes (
            episode_id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            source TEXT NOT NULL,
            source_id TEXT NOT NULL,
            occurred_at TEXT NOT NULL,
            ingested_at TEXT NOT NULL,
            invalidated_at TEXT,
            actor TEXT,
            tenant_id TEXT, org_id TEXT, user_id TEXT, agent_id TEXT,
            session_id TEXT, conversation_id TEXT, project_id TEXT, graph_id TEXT,
            payload_json TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_sophiagraph_raw_episodes_source
            ON sophiagraph_raw_episodes(source, source_id);
        CREATE INDEX IF NOT EXISTS idx_sophiagraph_raw_episodes_kind_time
            ON sophiagraph_raw_episodes(kind, occurred_at DESC);
        CREATE INDEX IF NOT EXISTS idx_sophiagraph_raw_episodes_namespace
            ON sophiagraph_raw_episodes(
                tenant_id, org_id, user_id, agent_id, session_id,
                conversation_id, project_id, graph_id
            );

        CREATE TABLE IF NOT EXISTS sophiagraph_ontologies (
            ontology_id TEXT NOT NULL,
            version TEXT NOT NULL,
            owner TEXT NOT NULL,
            compatibility TEXT NOT NULL,
            tenant_id TEXT, org_id TEXT, user_id TEXT, agent_id TEXT,
            session_id TEXT, conversation_id TEXT, project_id TEXT, graph_id TEXT,
            created_at TEXT,
            payload_json TEXT NOT NULL,
            PRIMARY KEY(ontology_id, version)
        );
        CREATE INDEX IF NOT EXISTS idx_sophiagraph_ontologies_owner
            ON sophiagraph_ontologies(owner);
        CREATE INDEX IF NOT EXISTS idx_sophiagraph_ontologies_namespace
            ON sophiagraph_ontologies(
                tenant_id, org_id, user_id, agent_id, session_id,
                conversation_id, project_id, graph_id
            );

        CREATE TABLE IF NOT EXISTS sophiagraph_artifacts (
            artifact_id TEXT PRIMARY KEY,
            uri TEXT NOT NULL,
            sha256 TEXT NOT NULL,
            mime TEXT NOT NULL,
            size_bytes INTEGER NOT NULL,
            source_class TEXT NOT NULL,
            retention TEXT NOT NULL,
            source_owner TEXT NOT NULL,
            target_record_id TEXT,
            derived_text_record_id TEXT,
            tenant_id TEXT, org_id TEXT, user_id TEXT, agent_id TEXT,
            session_id TEXT, conversation_id TEXT, project_id TEXT, graph_id TEXT,
            created_at TEXT,
            payload_json TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_sophiagraph_artifacts_namespace
            ON sophiagraph_artifacts(
                tenant_id, org_id, user_id, agent_id, session_id,
                conversation_id, project_id, graph_id
            );
        CREATE INDEX IF NOT EXISTS idx_sophiagraph_artifacts_target
            ON sophiagraph_artifacts(target_record_id);
        CREATE INDEX IF NOT EXISTS idx_sophiagraph_artifacts_source_class
            ON sophiagraph_artifacts(source_class);

        CREATE TABLE IF NOT EXISTS sophiagraph_canvas_boards (
            board_id TEXT PRIMARY KEY,
            tenant_id TEXT, org_id TEXT, user_id TEXT, agent_id TEXT,
            session_id TEXT, conversation_id TEXT, project_id TEXT, graph_id TEXT,
            created_at TEXT,
            payload_json TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_sophiagraph_canvas_boards_namespace
            ON sophiagraph_canvas_boards(
                tenant_id, org_id, user_id, agent_id, session_id,
                conversation_id, project_id, graph_id
            );

        CREATE TABLE IF NOT EXISTS sophiagraph_lifecycle_policies (
            policy_id TEXT PRIMARY KEY,
            ttl_active_iso TEXT,
            ttl_cooling_iso TEXT,
            tenant_id TEXT, org_id TEXT, user_id TEXT, agent_id TEXT,
            session_id TEXT, conversation_id TEXT, project_id TEXT, graph_id TEXT,
            created_at TEXT,
            payload_json TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_sophiagraph_lifecycle_policies_namespace
            ON sophiagraph_lifecycle_policies(
                tenant_id, org_id, user_id, agent_id, session_id,
                conversation_id, project_id, graph_id
            );

        CREATE TABLE IF NOT EXISTS sophiagraph_fact_convergence_links (
            link_id TEXT PRIMARY KEY,
            fact_id TEXT NOT NULL,
            episode_id TEXT NOT NULL,
            role TEXT NOT NULL,
            confidence REAL NOT NULL,
            created_at TEXT,
            tenant_id TEXT, org_id TEXT, user_id TEXT, agent_id TEXT,
            session_id TEXT, conversation_id TEXT, project_id TEXT, graph_id TEXT,
            payload_json TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_sophiagraph_fact_conv_links_fact
            ON sophiagraph_fact_convergence_links(fact_id);
        CREATE INDEX IF NOT EXISTS idx_sophiagraph_fact_conv_links_episode
            ON sophiagraph_fact_convergence_links(episode_id);
        CREATE INDEX IF NOT EXISTS idx_sophiagraph_fact_conv_links_namespace
            ON sophiagraph_fact_convergence_links(
                tenant_id, org_id, user_id, agent_id, session_id,
                conversation_id, project_id, graph_id
            );

        CREATE TABLE IF NOT EXISTS sophiagraph_aux_objects (
            object_kind TEXT NOT NULL,
            object_id TEXT NOT NULL,
            tenant_id TEXT, org_id TEXT, user_id TEXT, agent_id TEXT,
            session_id TEXT, conversation_id TEXT, project_id TEXT, graph_id TEXT,
            updated_at TEXT,
            payload_json TEXT NOT NULL,
            PRIMARY KEY(object_kind, object_id)
        );
        CREATE INDEX IF NOT EXISTS idx_sophiagraph_aux_objects_kind
            ON sophiagraph_aux_objects(object_kind, updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_sophiagraph_aux_objects_namespace
            ON sophiagraph_aux_objects(
                tenant_id, org_id, user_id, agent_id, session_id,
                conversation_id, project_id, graph_id
            );

        CREATE TABLE IF NOT EXISTS sophiagraph_write_leases (
            resource_id TEXT PRIMARY KEY,
            lease_id TEXT NOT NULL,
            owner TEXT NOT NULL,
            acquired_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            ttl_seconds INTEGER NOT NULL,
            heartbeat_seconds INTEGER NOT NULL
        );
        """
    )
    ensure_fts_schema(conn)
    if schema_version < 2:
        migrate_namespace_columns(conn)
    if schema_version < SCHEMA_VERSION:
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_sophiagraph_records_namespace
            ON sophiagraph_records(
                tenant_id, org_id, user_id, agent_id, session_id,
                conversation_id, project_id, graph_id
            )
        """
    )


def ensure_fts_schema(conn: sqlite3.Connection) -> None:
    try:
        conn.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS sophiagraph_record_fts
            USING fts5(record_id UNINDEXED, searchable)
            """
        )
        conn.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS sophiagraph_block_fts
            USING fts5(block_id UNINDEXED, record_id UNINDEXED, searchable)
            """
        )
    except sqlite3.OperationalError:
        return


def record_searchable_text(record: MemoryRecord) -> str:
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


def replace_record_fts(
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
            (record.id, record_searchable_text(record)),
        )
    except sqlite3.OperationalError:
        return


def block_searchable_text(block: KnowledgeDocumentBlock) -> str:
    return " ".join(
        str(part)
        for part in (
            block.block_id,
            block.document_id,
            block.record_id,
            block.block_type,
            block.anchor,
            block.excerpt,
        )
        if part is not None
    )


def replace_record_blocks_fts(
    conn: sqlite3.Connection,
    record_id: str,
    blocks: list[KnowledgeDocumentBlock],
) -> None:
    try:
        conn.execute(
            "DELETE FROM sophiagraph_block_fts WHERE record_id = ?",
            (record_id,),
        )
        conn.executemany(
            """
            INSERT INTO sophiagraph_block_fts(block_id, record_id, searchable)
            VALUES (?, ?, ?)
            """,
            [
                (block.block_id, block.record_id, block_searchable_text(block))
                for block in blocks
            ],
        )
    except sqlite3.OperationalError:
        return


def block_fts_candidate_record_ids(
    conn: sqlite3.Connection,
    query: StructuralSearchQuery,
) -> set[str] | None:
    terms = [query.block, query.section, query.task]
    escaped = [
        '"' + str(term).replace('"', '""') + '"'
        for term in terms
        if term is not None and str(term)
    ]
    if not escaped:
        return None
    try:
        rows = conn.execute(
            """
            SELECT DISTINCT record_id FROM sophiagraph_block_fts
             WHERE sophiagraph_block_fts MATCH ?
            """,
            (" AND ".join(escaped),),
        ).fetchall()
    except sqlite3.OperationalError:
        return None
    return {str(row["record_id"]) for row in rows}


def fts_candidate_record_ids(
    conn: sqlite3.Connection,
    query: StructuralSearchQuery,
) -> set[str] | None:
    terms = list(query.text_terms)
    terms.extend(query.exact_phrases)
    if query.content:
        terms.append(query.content)
    if not terms:
        return None
    escaped = ['"' + str(term).replace('"', '""') + '"' for term in terms if str(term)]
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


def migrate_namespace_columns(conn: sqlite3.Connection) -> None:
    columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(sophiagraph_records)")
    }
    for column in NAMESPACE_COLUMNS:
        if column not in columns:
            conn.execute(f"ALTER TABLE sophiagraph_records ADD COLUMN {column} TEXT")
    rows = conn.execute(
        "SELECT id, scope, payload_json FROM sophiagraph_records"
    ).fetchall()
    for row in rows:
        payload = row_json(row)
        namespace = namespace_from_payload(payload, str(row["scope"]))
        values = namespace.as_dict()
        if not isinstance(payload.get("namespace"), dict):
            payload["namespace"] = values
        conn.execute(
            """
            UPDATE sophiagraph_records
               SET tenant_id = ?, org_id = ?, user_id = ?, agent_id = ?,
                   session_id = ?, conversation_id = ?, project_id = ?,
                   graph_id = ?, payload_json = ?
             WHERE id = ?
            """,
            (
                values.get("tenant_id"),
                values.get("org_id"),
                values.get("user_id"),
                values.get("agent_id"),
                values.get("session_id"),
                values.get("conversation_id"),
                values.get("project_id"),
                values.get("graph_id"),
                json_dumps(payload),
                row["id"],
            ),
        )


__all__ = [
    "SCHEMA_VERSION",
    "SQLITE_BUSY_TIMEOUT_MS",
    "SQLITE_CONNECT_TIMEOUT_SECONDS",
    "SQLITE_JOURNAL_MODE",
    "SQLITE_SYNCHRONOUS",
    "NAMESPACE_COLUMNS",
    "block_fts_candidate_record_ids",
    "block_searchable_text",
    "ensure_schema",
    "fts_candidate_record_ids",
    "namespace_filter_sql",
    "namespace_from_payload",
    "namespace_values",
    "record_searchable_text",
    "replace_record_fts",
    "replace_record_blocks_fts",
    "row_json",
]
