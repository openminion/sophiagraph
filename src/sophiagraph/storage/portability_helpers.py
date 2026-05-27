"""Shared snapshot and delta helpers for storage portability mixins."""

from __future__ import annotations

from dataclasses import replace
from typing import Any
from uuid import uuid4

from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.models import MemoryCandidate, SophiaGraphChangeEvent
from sophiagraph.portability.models import (
    MemoryBundleImportOptions,
    MemoryBundleImportResult,
    MemoryBundleSnapshot,
    MemoryDeltaSnapshot,
)
from sophiagraph.storage.helpers import record_matches_namespaces


def import_snapshot_into_store(
    store: Any,
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
            staged_candidates=len(records) if options.trust_mode == "candidate" else 0,
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
        if store.get_record(record.id) is not None:
            if options.conflict_mode == "skip":
                skipped_records += 1
                continue
            if options.conflict_mode == "error":
                raise InvalidArgumentError(f"record already exists: {record.id}")
        if options.trust_mode == "candidate":
            store.put_candidate(
                MemoryCandidate(
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
            )
            staged_candidates += 1
            continue
        store.put_record(record)
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
        store.put_candidate(candidate)
        imported_candidates += 1
    for relation in snapshot.relations:
        store.put_relation(relation)
        imported_relations += 1
    for transition in snapshot.tier_transitions:
        store.put_tier_transition(transition)
        imported_tier_transitions += 1
    imported_memory_blocks = 0
    for block in snapshot.memory_blocks:
        store.put_memory_block(block)
        imported_memory_blocks += 1
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
        imported_memory_blocks=imported_memory_blocks,
        skipped_records=skipped_records,
        skipped_sections=skipped_sections,
        rewrites=rewrites,
    )


def export_change_delta(changes: list[SophiaGraphChangeEvent]) -> MemoryDeltaSnapshot:
    return MemoryDeltaSnapshot(
        manifest={
            "delta_version": "sophiagraph_delta.v1",
            "change_count": len(changes),
        },
        changes=changes,
    )


class SnapshotImportExportDeltaMixin:
    def import_snapshot(
        self,
        snapshot: MemoryBundleSnapshot,
        options: MemoryBundleImportOptions,
    ) -> MemoryBundleImportResult:
        return import_snapshot_into_store(self, snapshot, options)

    def export_delta(
        self,
        *,
        since_cursor: int | None = None,
        limit: int | None = None,
        namespaces: list[Any] | None = None,
    ) -> MemoryDeltaSnapshot:
        return export_change_delta(
            self.list_changes(
                since_cursor=since_cursor,
                limit=limit,
                namespaces=namespaces,
            )
        )
