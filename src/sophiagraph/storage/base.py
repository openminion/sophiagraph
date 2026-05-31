"""Standalone storage contract for the reusable ``sophiagraph`` package."""

from __future__ import annotations

from typing import Any, Protocol

from sophiagraph.contracts.types import MEMORY_CONTRACT_VERSION
from sophiagraph.deletion import DeletionCascadeResult, ErasureAuditExport
from sophiagraph.models import (
    Contradiction,
    Decision,
    Entity,
    EntityAlias,
    EntitySummary,
    Episode,
    EpisodeStep,
    Fact,
    FactConvergenceLink,
    MemoryBlock,
    MemoryCandidate,
    MemoryEmbedding,
    KnowledgeDocumentBlock,
    MemoryRecord,
    MemoryRelation,
    OntologyDefinition,
    Outcome,
    Procedure,
    RawEpisode,
    RelationDirection,
    MemoryNamespace,
    MemoryTierTransition,
    MemoryType,
    SophiaGraphChangeEvent,
    StructuralLink,
)
from sophiagraph.connectors import SourceIngestEnvelope, SourceRegistryEntry
from sophiagraph.freshness import FreshnessLedgerEntry
from sophiagraph.portability.models import (
    MemoryDeltaImportResult,
    MemoryDeltaSnapshot,
    MemoryBundleExportOptions,
    MemoryBundleImportOptions,
    MemoryBundleImportResult,
    MemoryBundleSnapshot,
)
from sophiagraph.shared_blocks import (
    SharedBlockAttachment,
    SharedBlockEditConflict,
    SharedBlockMirror,
    SharedBlockUsageEvent,
)
from sophiagraph.sync import SyncConflictRecord
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


class SophiaGraphStore(Protocol):
    """Standalone durable engine contract for ``sophiagraph`` consumers."""

    contract_version: str = MEMORY_CONTRACT_VERSION

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

    # Entity / fact / contradiction (SEFT-02 + SEFT-03 + SEFT-04).

    def put_entity(self, entity: Entity) -> str: ...

    def get_entity(self, entity_id: str) -> Entity | None: ...

    def list_entities(
        self,
        *,
        namespaces: list[MemoryNamespace] | None = None,
        canonical_name: str | None = None,
        entity_type: str | None = None,
        include_invalidated: bool = False,
        limit: int | None = None,
    ) -> list[Entity]: ...

    def put_entity_alias(self, alias: EntityAlias) -> str: ...

    def list_entity_aliases(
        self,
        *,
        entity_id: str | None = None,
        alias_name: str | None = None,
        namespaces: list[MemoryNamespace] | None = None,
        limit: int | None = None,
    ) -> list[EntityAlias]: ...

    def put_fact(self, fact: Fact) -> str: ...

    def get_fact(self, fact_id: str) -> Fact | None: ...

    def list_facts(
        self,
        *,
        namespaces: list[MemoryNamespace] | None = None,
        subject_entity_id: str | None = None,
        object_entity_id: str | None = None,
        predicate: str | None = None,
        valid_at: str | None = None,
        learned_at: str | None = None,
        active_state: str = "active",
        source_episode_id: str | None = None,
        include_invalidated: bool = False,
        limit: int | None = None,
    ) -> list[Fact]: ...

    def put_raw_episode(self, episode: RawEpisode) -> str: ...

    def get_raw_episode(self, episode_id: str) -> RawEpisode | None: ...

    def list_raw_episodes(
        self,
        *,
        namespaces: list[MemoryNamespace] | None = None,
        kind: str | None = None,
        source: str | None = None,
        occurred_after: str | None = None,
        occurred_before: str | None = None,
        include_invalidated: bool = False,
        limit: int | None = None,
    ) -> list[RawEpisode]: ...

    def put_fact_convergence_link(self, link: FactConvergenceLink) -> str: ...

    def list_fact_convergence_links(
        self,
        *,
        fact_id: str | None = None,
        episode_id: str | None = None,
        namespaces: list[MemoryNamespace] | None = None,
        limit: int | None = None,
    ) -> list[FactConvergenceLink]: ...

    # Custom ontology and categories.

    def put_ontology(self, ontology: OntologyDefinition) -> tuple[str, str]: ...

    def get_ontology(
        self,
        *,
        ontology_id: str,
        version: str,
    ) -> OntologyDefinition | None: ...

    def list_ontologies(
        self,
        *,
        ontology_id: str | None = None,
        owner: str | None = None,
        namespaces: list[MemoryNamespace] | None = None,
        limit: int | None = None,
    ) -> list[OntologyDefinition]: ...

    def record_contradiction(self, contradiction: Contradiction) -> Contradiction: ...

    def list_contradictions(
        self,
        *,
        target_fact_id: str | None = None,
        contradicting_fact_id: str | None = None,
        namespaces: list[MemoryNamespace] | None = None,
        limit: int | None = None,
    ) -> list[Contradiction]: ...

    def put_entity_summary(self, summary: EntitySummary) -> str: ...

    def list_entity_summaries(
        self,
        *,
        entity_id: str | None = None,
        namespaces: list[MemoryNamespace] | None = None,
        include_invalidated: bool = False,
        limit: int | None = None,
    ) -> list[EntitySummary]: ...

    # Episode / procedure (SEPM-02 + SEPM-03).

    def put_episode(self, episode: Episode) -> str: ...

    def get_episode(self, episode_id: str) -> Episode | None: ...

    def list_episodes(
        self,
        *,
        namespaces: list[MemoryNamespace] | None = None,
        status: str | None = None,
        task_id: str | None = None,
        artifact_id: str | None = None,
        tool_id: str | None = None,
        started_after: str | None = None,
        started_before: str | None = None,
        limit: int | None = None,
    ) -> list[Episode]: ...

    def put_episode_step(self, step: EpisodeStep) -> str: ...

    def list_episode_steps(
        self,
        *,
        episode_id: str,
        kind: str | None = None,
        limit: int | None = None,
    ) -> list[EpisodeStep]: ...

    def put_outcome(self, outcome: Outcome) -> str: ...

    def list_outcomes(
        self,
        *,
        episode_id: str | None = None,
        step_id: str | None = None,
        status: str | None = None,
        namespaces: list[MemoryNamespace] | None = None,
        limit: int | None = None,
    ) -> list[Outcome]: ...

    def put_decision(self, decision: Decision) -> str: ...

    def list_decisions(
        self,
        *,
        episode_id: str | None = None,
        namespaces: list[MemoryNamespace] | None = None,
        limit: int | None = None,
    ) -> list[Decision]: ...

    def put_procedure(self, procedure: Procedure) -> str: ...

    def get_procedure(self, procedure_id: str) -> Procedure | None: ...

    def list_procedures(
        self,
        *,
        namespaces: list[MemoryNamespace] | None = None,
        promotion_tier: str | None = None,
        include_invalidated: bool = False,
        limit: int | None = None,
    ) -> list[Procedure]: ...

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

    def tombstone_record(
        self,
        record_id: str,
        *,
        deleted_at: str,
        reason: str,
    ) -> MemoryRecord: ...

    def cascade_tombstones(
        self,
        record_id: str,
        *,
        deleted_at: str,
        reason: str,
    ) -> DeletionCascadeResult: ...

    def erasure_audit_export(
        self,
        *,
        record_id: str | None = None,
        namespaces: list[MemoryNamespace] | None = None,
    ) -> ErasureAuditExport: ...

    def history(
        self,
        scope: str,
        type: MemoryType,
        key: str,
    ) -> list[MemoryRecord]: ...

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
