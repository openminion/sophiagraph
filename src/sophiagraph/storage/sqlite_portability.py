"""SQLite store snapshot and delta portability methods."""

from __future__ import annotations

from dataclasses import asdict, replace
from typing import Any

from sophiagraph.models import (
    MemoryBlock,
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
    memory_block_from_dict,
    record_from_dict,
    relation_from_dict,
    tier_transition_from_dict,
)
from sophiagraph.portability.models import (
    MemoryBundleExportOptions,
    MemoryBundleSnapshot,
    MemoryDeltaImportResult,
    MemoryDeltaSnapshot,
)
from sophiagraph.query import CandidateListOptions, ListQueryOptions, RecordOrder
from sophiagraph.storage.graph_helpers import link_from_dict, link_to_dict
from sophiagraph.storage.portability_helpers import SnapshotImportExportDeltaMixin
from sophiagraph.storage.sqlite_support import namespace_filter_sql


class SqlitePortabilityMixin(SnapshotImportExportDeltaMixin):
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
        memory_blocks: list[MemoryBlock] = []
        if options.include_memory_blocks:
            memory_blocks = self.list_memory_blocks(
                namespaces=options.namespaces,
                limit=options.limit,
            )
        snapshot = MemoryBundleSnapshot(
            manifest={},
            records=records,
            candidates=candidates,
            relations=relations,
            tier_transitions=tier_transitions,
            provenance_traces=[],
            memory_blocks=memory_blocks,
        )
        return replace(snapshot, manifest=build_manifest(snapshot=snapshot))

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
                elif event.object_type == "memory_block":
                    block = memory_block_from_dict(event.payload)
                    # Reuse the SQLite store's persistence path so namespace
                    # columns + structural fields stay in sync. Pass the live
                    # ``conn`` so the delta runs inside the open transaction.
                    self._persist_memory_block(conn, block, operation="delta_import")
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
