"""In-memory store snapshot and delta portability methods."""

from __future__ import annotations

from dataclasses import replace
from typing import Any
from uuid import uuid4

from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.models import MemoryBlock, MemoryCandidate, MemoryNamespace
from sophiagraph.portability.codec import (
    build_manifest,
    candidate_from_dict,
    memory_block_from_dict,
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
from sophiagraph.storage.graph_helpers import block_from_dict, link_from_dict
from sophiagraph.storage.helpers import record_matches_namespaces
from sophiagraph.storage.graph_helpers import namespace_matches_filters


class MemoryPortabilityMixin:
    """Snapshot and changefeed operations for ``SophiaGraphMemoryStore``."""

    _records: dict[str, Any]
    _relations: dict[str, Any]
    _links: dict[str, Any]
    _blocks: dict[str, Any]
    _memory_blocks: dict[str, MemoryBlock]
    _candidates: dict[str, Any]
    _transitions: dict[str, Any]

    def export_snapshot(
        self, options: MemoryBundleExportOptions
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
        record_ids = {record.id for record in records}
        relations = []
        if options.include_relations:
            relations = [
                relation
                for relation in self._relations.values()
                if relation.source_record_id in record_ids
                and relation.target_record_id in record_ids
            ]
            relations.sort(key=lambda relation: relation.created_at)
        candidates: list[MemoryCandidate] = []
        if options.include_candidates:
            candidates = self.list_candidates(CandidateListOptions(limit=options.limit))
        transitions = []
        if options.include_tier_history:
            transitions = self.list_tier_transitions(
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
            tier_transitions=transitions,
            provenance_traces=[],
            memory_blocks=memory_blocks,
        )
        return replace(snapshot, manifest=build_manifest(snapshot=snapshot))

    def import_snapshot(
        self, snapshot: MemoryBundleSnapshot, options: MemoryBundleImportOptions
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
        imported_memory_blocks = 0
        for block in snapshot.memory_blocks:
            # Stored/portable path: bundle round-trips all four mode literals
            # without invoking ``validate_block_for_creation``. Callers that
            # want active-block guarantees should call the validator after
            # import.
            self.put_memory_block(block)
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

    def list_changes(
        self,
        *,
        since_cursor: int | None = None,
        limit: int | None = None,
        namespaces: list[MemoryNamespace] | None = None,
    ) -> list[Any]:
        changes = [
            event
            for event in self._changes
            if (since_cursor is None or (event.cursor or 0) > since_cursor)
            and namespace_matches_filters(event.namespace, namespaces)
        ]
        changes.sort(key=lambda event: event.cursor or 0)
        return changes[: int(limit)] if limit is not None else changes

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
        for event in delta.changes:
            if self._has_change(event):
                skipped.append(event.event_id)
                continue
            if event.object_type == "record":
                record = record_from_dict(event.payload)
                self._records[record.id] = record
            elif event.object_type == "relation":
                relation = relation_from_dict(event.payload)
                self._relations[relation.relation_id] = relation
            elif event.object_type == "link":
                link = link_from_dict(event.payload)
                self._links[link.link_id] = link
            elif event.object_type == "candidate":
                candidate = candidate_from_dict(event.payload)
                self._candidates[candidate.candidate_id] = candidate
            elif event.object_type == "tier_transition":
                transition = tier_transition_from_dict(event.payload)
                self._transitions[transition.transition_id] = transition
            elif event.object_type == "block":
                block = block_from_dict(event.payload)
                self._blocks[block.block_id] = block
            elif event.object_type == "memory_block":
                memory_block = memory_block_from_dict(event.payload)
                self._memory_blocks[memory_block.block_id] = memory_block
            else:
                skipped.append(event.event_id)
                continue
            self._append_change(event)
            imported += 1
        return MemoryDeltaImportResult(
            applied=True,
            imported_changes=imported,
            skipped_changes=len(skipped),
            skipped_event_ids=skipped,
        )


__all__ = ["MemoryPortabilityMixin"]
