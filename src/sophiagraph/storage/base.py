"""Standalone storage contract for the reusable ``sophiagraph`` package."""

from __future__ import annotations

from typing import Any, Protocol

from sophiagraph.contracts.types import MEMORY_CONTRACT_VERSION
from sophiagraph.models import (
    MemoryCandidate,
    KnowledgeDocumentBlock,
    MemoryRecord,
    MemoryRelation,
    RelationDirection,
    MemoryNamespace,
    MemoryTierTransition,
    MemoryType,
    SophiaGraphChangeEvent,
    StructuralLink,
)
from sophiagraph.portability.models import (
    MemoryDeltaImportResult,
    MemoryDeltaSnapshot,
    MemoryBundleExportOptions,
    MemoryBundleImportOptions,
    MemoryBundleImportResult,
    MemoryBundleSnapshot,
)
from sophiagraph.query import (
    CandidateListOptions,
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
    ) -> list[StructuralLink]: ...

    def get_backlinks(
        self, record_id: str, *, limit: int | None = None
    ) -> list[StructuralLink]: ...

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
