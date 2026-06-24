"""Core store protocol slices for records, links, blocks, and sync."""

from __future__ import annotations

from typing import Any, Protocol

from sophiagraph.models import (
    ActiveEmbeddingModelSet,
    KnowledgeDocumentBlock,
    MemoryBlock,
    MemoryCandidate,
    MemoryEmbedding,
    MemoryNamespace,
    MemoryRecord,
    MemoryRelation,
    MemoryTierTransition,
    MemoryType,
    RelationDirection,
    RetentionSnapshot,
    SophiaGraphChangeEvent,
    StructuralLink,
)
from sophiagraph.connectors import SourceIngestEnvelope, SourceRegistryEntry
from sophiagraph.freshness import FreshnessLedgerEntry
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
    EmbeddingListOptions,
    GraphSnapshot,
    GraphSnapshotOptions,
    LinkQueryOptions,
    ListQueryOptions,
    LocalGraphOptions,
    SearchQueryOptions,
    StructuralSearchQuery,
)
from sophiagraph.shared_blocks import (
    SharedBlockAttachment,
    SharedBlockEditConflict,
    SharedBlockMirror,
    SharedBlockUsageEvent,
)
from sophiagraph.sync import SyncConflictRecord


class CoreSophiaGraphStore(Protocol):
    """Core protocol surface reused across all SophiaGraph stores."""

    def put_record(self, record: MemoryRecord) -> str: ...

    def upsert_record(
        self,
        scope: str,
        type: MemoryType,
        key: str,
        record_patch: dict[str, Any],
    ) -> MemoryRecord: ...

    def get_record(self, record_id: str) -> MemoryRecord | None: ...

    def list_records(self, options: ListQueryOptions) -> list[MemoryRecord]: ...

    def search_records(self, options: SearchQueryOptions) -> list[MemoryRecord]: ...

    def invalidate_record(
        self,
        record_id: str,
        *,
        valid_to: str,
        reason: str,
    ) -> MemoryRecord: ...

    def supersede_record(
        self,
        old_record_id: str,
        new_record_id: str,
        reason: str = "",
    ) -> MemoryRecord: ...

    def put_relation(self, relation: MemoryRelation) -> str: ...

    def list_relations(
        self,
        record_id: str,
        *,
        direction: RelationDirection = "out",
        relation_types: list[Any] | None = None,
        limit: int | None = None,
    ) -> list[MemoryRelation]: ...

    def get_related_records(
        self,
        record_id: str,
        scopes: list[str],
        *,
        direction: RelationDirection = "out",
        relation_types: list[Any] | None = None,
        limit: int | None = None,
    ) -> list[MemoryRecord]: ...

    def put_link(self, link: StructuralLink) -> str: ...

    def replace_record_links(
        self,
        record_id: str,
        links: list[StructuralLink],
    ) -> None: ...

    def list_links(self, options: LinkQueryOptions) -> list[StructuralLink]: ...

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

    def get_local_graph(self, options: LocalGraphOptions) -> GraphSnapshot: ...

    def get_graph_snapshot(self, options: GraphSnapshotOptions) -> GraphSnapshot: ...

    def structural_search_records(
        self,
        query: StructuralSearchQuery,
        *,
        scopes: list[str],
    ) -> list[MemoryRecord]: ...

    def put_document_blocks(
        self,
        record_id: str,
        blocks: list[KnowledgeDocumentBlock],
    ) -> None: ...

    def list_document_blocks(
        self,
        *,
        record_id: str | None = None,
        document_id: str | None = None,
        block_id: str | None = None,
    ) -> list[KnowledgeDocumentBlock]: ...

    def put_candidate(self, candidate: MemoryCandidate) -> str: ...

    def get_candidate(self, candidate_id: str) -> MemoryCandidate | None: ...

    def list_candidates(
        self, options: CandidateListOptions
    ) -> list[MemoryCandidate]: ...

    def update_candidate(
        self,
        candidate_id: str,
        patch: dict[str, Any],
    ) -> MemoryCandidate: ...

    def promote_candidate(
        self,
        candidate_id: str,
        target_scope: str,
    ) -> MemoryRecord: ...

    def list_tier_transitions(
        self,
        *,
        record_id: str | None = None,
        scopes: list[str] | None = None,
        limit: int | None = None,
    ) -> list[MemoryTierTransition]: ...

    def put_tier_transition(self, transition: MemoryTierTransition) -> str: ...

    def put_memory_block(self, block: MemoryBlock) -> str: ...

    def get_memory_block(self, block_id: str) -> MemoryBlock | None: ...

    def list_memory_blocks(
        self,
        *,
        namespaces: list[MemoryNamespace] | None = None,
        class_names: list[str] | None = None,
        include_stale: bool = True,
        limit: int | None = None,
    ) -> list[MemoryBlock]: ...

    def update_memory_block_content(
        self,
        block_id: str,
        *,
        new_content: str,
        actor: str,
        operator_action: bool = False,
    ) -> MemoryBlock: ...

    def delete_memory_block(
        self,
        block_id: str,
        *,
        actor: str,
        operator_action: bool = False,
    ) -> bool: ...

    def mark_memory_block_stale_after(
        self,
        block_id: str,
        *,
        stale_after: str | None,
    ) -> MemoryBlock: ...

    def put_sync_conflict(self, conflict: SyncConflictRecord) -> str: ...

    def get_sync_conflict(self, conflict_id: str) -> SyncConflictRecord | None: ...

    def list_sync_conflicts(
        self,
        *,
        namespaces: list[MemoryNamespace] | None = None,
        status: str | None = None,
        source_id: str | None = None,
        limit: int | None = None,
    ) -> list[SyncConflictRecord]: ...

    def put_freshness_entry(self, entry: FreshnessLedgerEntry) -> str: ...

    def get_freshness_entry(self, ledger_id: str) -> FreshnessLedgerEntry | None: ...

    def list_freshness_entries(
        self,
        *,
        namespaces: list[MemoryNamespace] | None = None,
        source_kind: str | None = None,
        source_id: str | None = None,
        status: str | None = None,
        limit: int | None = None,
    ) -> list[FreshnessLedgerEntry]: ...

    def put_source_entry(self, source: SourceRegistryEntry) -> str: ...

    def get_source_entry(self, source_id: str) -> SourceRegistryEntry | None: ...

    def list_source_entries(
        self,
        *,
        namespaces: list[MemoryNamespace] | None = None,
        source_type: str | None = None,
        permission_scope: str | None = None,
        limit: int | None = None,
    ) -> list[SourceRegistryEntry]: ...

    def put_source_ingest(self, envelope: SourceIngestEnvelope) -> str: ...

    def get_source_ingest(self, ingest_id: str) -> SourceIngestEnvelope | None: ...

    def put_shared_block_attachment(
        self,
        attachment: SharedBlockAttachment,
    ) -> str: ...

    def list_shared_block_attachments(
        self,
        *,
        block_id: str | None = None,
        namespaces: list[MemoryNamespace] | None = None,
        attached_agent_id: str | None = None,
        status: str | None = None,
        limit: int | None = None,
    ) -> list[SharedBlockAttachment]: ...

    def put_shared_block_mirror(self, mirror: SharedBlockMirror) -> str: ...

    def get_shared_block_mirror(self, mirror_id: str) -> SharedBlockMirror | None: ...

    def list_shared_block_mirrors(
        self,
        *,
        block_id: str | None = None,
        namespaces: list[MemoryNamespace] | None = None,
        status: str | None = None,
        limit: int | None = None,
    ) -> list[SharedBlockMirror]: ...

    def put_shared_block_conflict(self, conflict: SharedBlockEditConflict) -> str: ...

    def list_shared_block_conflicts(
        self,
        *,
        block_id: str | None = None,
        namespaces: list[MemoryNamespace] | None = None,
        status: str | None = None,
        limit: int | None = None,
    ) -> list[SharedBlockEditConflict]: ...

    def put_shared_block_usage_event(self, event: SharedBlockUsageEvent) -> str: ...

    def list_shared_block_usage_events(
        self,
        *,
        block_id: str | None = None,
        namespaces: list[MemoryNamespace] | None = None,
        action: str | None = None,
        limit: int | None = None,
    ) -> list[SharedBlockUsageEvent]: ...

    def put_embedding(self, embedding: MemoryEmbedding) -> str: ...

    def get_embedding(
        self,
        record_id: str,
        vector_space: str,
        *,
        include_vector: bool = True,
    ) -> MemoryEmbedding | None: ...

    def list_embeddings(
        self,
        options: EmbeddingListOptions,
    ) -> list[MemoryEmbedding]: ...

    def delete_embedding(self, record_id: str, vector_space: str) -> bool: ...

    def put_active_model_set(self, model_set: ActiveEmbeddingModelSet) -> str: ...

    def get_active_model_set(
        self,
        *,
        namespace: MemoryNamespace,
        vector_space: str,
    ) -> ActiveEmbeddingModelSet | None: ...

    def list_active_model_sets(
        self,
        *,
        namespaces: list[MemoryNamespace] | None = None,
        vector_space: str | None = None,
        limit: int | None = None,
    ) -> list[ActiveEmbeddingModelSet]: ...

    def list_orphan_external_vector_ids(
        self,
        *,
        namespace: MemoryNamespace,
        since: str | None = None,
    ) -> list[tuple[str, str]]: ...

    def put_retention_snapshot(self, snapshot: RetentionSnapshot) -> str: ...

    def get_retention_snapshot(
        self,
        *,
        name: str,
        namespace: MemoryNamespace,
    ) -> RetentionSnapshot | None: ...

    def list_retention_snapshots(
        self,
        *,
        namespaces: list[MemoryNamespace] | None = None,
        limit: int | None = None,
    ) -> list[RetentionSnapshot]: ...

    def export_snapshot(
        self,
        options: MemoryBundleExportOptions,
    ) -> MemoryBundleSnapshot: ...

    def import_snapshot(
        self,
        snapshot: MemoryBundleSnapshot,
        options: MemoryBundleImportOptions,
    ) -> MemoryBundleImportResult: ...

    def list_changes(
        self,
        *,
        since_cursor: int | None = None,
        limit: int | None = None,
        namespaces: list[MemoryNamespace] | None = None,
    ) -> list[SophiaGraphChangeEvent]: ...

    def export_delta(
        self,
        *,
        since_cursor: int | None = None,
        limit: int | None = None,
        namespaces: list[MemoryNamespace] | None = None,
    ) -> MemoryDeltaSnapshot: ...

    def import_delta(self, delta: MemoryDeltaSnapshot) -> MemoryDeltaImportResult: ...
