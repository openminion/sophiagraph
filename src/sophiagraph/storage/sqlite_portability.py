"""SQLite store snapshot and delta portability methods."""

from __future__ import annotations

from dataclasses import asdict, replace
from typing import Any
from uuid import uuid4

from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.models import (
    MemoryCandidate,
    MemoryNamespace,
    MemoryRelation,
    MemoryTierTransition,
    SophiaGraphChangeEvent,
)
from sophiagraph.portability.codec import (
    build_manifest,
    candidate_from_dict,
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
from sophiagraph.query import CandidateListOptions, ListQueryOptions, RecordOrder
from sophiagraph.storage.graph_helpers import link_from_dict, link_to_dict
from sophiagraph.storage.helpers import record_matches_namespaces
from sophiagraph.storage.sqlite_support import namespace_filter_sql


class SqlitePortabilityMixin:
    """Snapshot and changefeed operations for ``SophiaGraphSqliteStore``."""

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
        namespace_sql, namespace_params = namespace_filter_sql(namespaces)
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
                    values = link.namespace.as_dict()
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
                            values.get("tenant_id"),
                            values.get("org_id"),
                            values.get("user_id"),
                            values.get("agent_id"),
                            values.get("session_id"),
                            values.get("conversation_id"),
                            values.get("project_id"),
                            values.get("graph_id"),
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


__all__ = ["SqlitePortabilityMixin"]
