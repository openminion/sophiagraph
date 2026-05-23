"""SQLite-first standalone durable engine for the reusable ``sophiagraph`` package."""

from __future__ import annotations

from dataclasses import asdict, replace
import json
from pathlib import Path
import sqlite3
from typing import Any
from uuid import uuid4

from sophiagraph.contracts.types import MEMORY_CONTRACT_VERSION
from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.models import (
    MemoryCandidate,
    MemoryNamespace,
    MemoryRecord,
    MemoryRelation,
    MemoryTierTransition,
    MemoryType,
)
from sophiagraph.portability.codec import (
    _candidate_from_dict,
    _json_dumps,
    _record_from_dict,
    _relation_from_dict,
    _tier_transition_from_dict,
    build_manifest,
)
from sophiagraph.portability.models import (
    MemoryBundleExportOptions,
    MemoryBundleImportOptions,
    MemoryBundleImportResult,
    MemoryBundleSnapshot,
)
from sophiagraph.query import (
    CandidateListOptions,
    ListQueryOptions,
    RecordOrder,
    SearchQueryOptions,
)
from sophiagraph.storage.base import SophiaGraphStore
from sophiagraph.storage.helpers import (
    record_matches_namespaces,
    record_matches_query,
    utc_now_iso,
)


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


class SophiaGraphSqliteStore(SophiaGraphStore):
    """Small standalone SQLite-backed durable engine for ``sophiagraph``."""

    contract_version = MEMORY_CONTRACT_VERSION

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
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
                """
            )
            self._migrate_namespace_columns(conn)
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_sophiagraph_records_namespace
                    ON sophiagraph_records(
                        tenant_id, org_id, user_id, agent_id, session_id,
                        conversation_id, project_id, graph_id
                    )
                """
            )

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
                    _json_dumps(payload),
                    row["id"],
                ),
            )

    def _record_from_row(self, row: sqlite3.Row) -> MemoryRecord:
        return _record_from_dict(_row_json(row))

    def _candidate_from_row(self, row: sqlite3.Row) -> MemoryCandidate:
        return _candidate_from_dict(_row_json(row))

    def _relation_from_row(self, row: sqlite3.Row) -> MemoryRelation:
        return _relation_from_dict(_row_json(row))

    def _transition_from_row(self, row: sqlite3.Row) -> MemoryTierTransition:
        return _tier_transition_from_dict(_row_json(row))

    def put_record(self, record: MemoryRecord) -> str:
        payload = asdict(record)
        namespace_values = _namespace_values(record)
        with self._connect() as conn:
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
                    _json_dumps(payload),
                ),
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
            record = _record_from_dict(payload)
        else:
            payload = asdict(existing)
            payload.update(record_patch)
            payload["scope"] = scope
            payload["type"] = type
            payload["key"] = key
            payload["updated_at"] = now
            record = _record_from_dict(payload)
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
        order = "updated_at DESC"
        if options.order_by == RecordOrder.UPDATED_AT_ASC:
            order = "updated_at ASC"
        limit_sql = ""
        sql_limit = options.limit if not options.namespaces else None
        sql_offset = options.offset if not options.namespaces else None
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
        if not options.include_invalidated:
            records = [record for record in records if record.is_current_at()]
        records = [
            record
            for record in records
            if record_matches_namespaces(record, options.namespaces)
        ]
        if options.namespaces and options.offset is not None:
            records = records[int(options.offset) :]
        if options.namespaces and options.limit is not None:
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
            )
        )
        matches = [
            record
            for record in listed
            if record_matches_query(
                record,
                options.query,
                content_serializer=_json_dumps,
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
        with self._connect() as conn:
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
                    _json_dumps(asdict(relation)),
                ),
            )
        return relation.relation_id

    def list_relations(
        self,
        record_id: str,
        *,
        relation_types: list[Any] | None = None,
        limit: int | None = None,
    ) -> list[MemoryRelation]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT payload_json FROM sophiagraph_relations WHERE source_record_id = ? ORDER BY created_at DESC",
                (record_id,),
            ).fetchall()
        relations = [self._relation_from_row(row) for row in rows]
        if relation_types:
            allowed = {str(item) for item in relation_types}
            relations = [row for row in relations if row.relation_type in allowed]
        if limit is not None:
            relations = relations[: int(limit)]
        return relations

    def get_related_records(
        self,
        record_id: str,
        scopes: list[str],
        *,
        relation_types: list[Any] | None = None,
        limit: int | None = None,
    ) -> list[MemoryRecord]:
        relations = self.list_relations(
            record_id, relation_types=relation_types, limit=limit
        )
        records: list[MemoryRecord] = []
        scope_allow = set(scopes)
        for relation in relations:
            record = self.get_record(relation.target_record_id)
            if record is None:
                continue
            if record.scope not in scope_allow:
                continue
            records.append(record)
        return records[: int(limit)] if limit is not None else records

    def put_candidate(self, candidate: MemoryCandidate) -> str:
        with self._connect() as conn:
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
                    _json_dumps(asdict(candidate)),
                ),
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
        updated = _candidate_from_dict(payload)
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
        with self._connect() as conn:
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
                    _json_dumps(asdict(transition)),
                ),
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
