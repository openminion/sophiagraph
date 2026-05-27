"""In-memory store snapshot and delta portability methods."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

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
    MemoryBundleSnapshot,
    MemoryDeltaImportResult,
    MemoryDeltaSnapshot,
)
from sophiagraph.query import CandidateListOptions, ListQueryOptions, RecordOrder
from sophiagraph.storage.graph_helpers import block_from_dict, link_from_dict
from sophiagraph.storage.graph_helpers import namespace_matches_filters
from sophiagraph.storage.portability_helpers import SnapshotImportExportDeltaMixin


class MemoryPortabilityMixin(SnapshotImportExportDeltaMixin):
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
