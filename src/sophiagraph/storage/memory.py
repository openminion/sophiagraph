"""In-memory standalone durable engine for the reusable ``sophiagraph`` package."""

from __future__ import annotations

from dataclasses import asdict, replace
from typing import Any
from uuid import uuid4

from sophiagraph.contracts.errors import (
    InvalidArgumentError,
    NotFoundError,
)
from sophiagraph.contracts.types import MEMORY_CONTRACT_VERSION
from sophiagraph.deletion import (
    DeletionCascadeResult,
    ErasureAuditEntry,
    ErasureAuditExport,
)
from sophiagraph.integrity import populate_integrity_hash
from sophiagraph.models import (
    ActiveEmbeddingModelSet,
    MemoryBlock,
    MemoryCandidate,
    MemoryEmbedding,
    KnowledgeDocumentBlock,
    MemoryNamespace,
    MemoryRecord,
    MemoryRelation,
    RetentionSnapshot,
    MemoryTierTransition,
    MemoryType,
    RelationDirection,
    StructuralLink,
    default_change_namespace,
)
from sophiagraph.models.embedding_lifecycle import namespace_key
from sophiagraph.portability.codec import record_from_dict
from sophiagraph.query import (
    CandidateListOptions,
    EmbeddingListOptions,
    GraphSnapshot,
    GraphSnapshotOptions,
    LinkQueryOptions,
    ListQueryOptions,
    LocalGraphOptions,
    RecordOrder,
    SearchQueryOptions,
    StructuralSearchQuery,
    has_bitemporal_filter,
    record_matches_bitemporal,
)
from sophiagraph.storage.base import SophiaGraphStore
from sophiagraph.storage.record_lifecycle import (
    RecordLifecycleMixin,
    record_matches_namespaces,
    record_matches_query,
    utc_now_iso,
)
from sophiagraph.storage.graph_helpers import (
    block_to_dict,
    memory_block_to_dict,
    namespace_matches_filters,
    record_matches_structural_query,
)
from sophiagraph.storage.memory_block_helpers import (
    enforce_block_edit_gate as _enforce_block_edit_gate,
)
from sophiagraph.storage.memory_changefeed import MemoryChangefeedMixin
from sophiagraph.storage.graph_queries import build_graph_snapshot, build_local_graph
from sophiagraph.storage.memory_portability import MemoryPortabilityMixin


class SophiaGraphMemoryStore(
    MemoryPortabilityMixin,
    MemoryChangefeedMixin,
    RecordLifecycleMixin,
    SophiaGraphStore,
):
    """In-memory implementation of the storage contract."""

    contract_version = MEMORY_CONTRACT_VERSION

    def __init__(self, *, integrity_hash_enabled: bool = False) -> None:
        self._records: dict[str, MemoryRecord] = {}
        self._relations: dict[str, MemoryRelation] = {}
        self._links: dict[str, StructuralLink] = {}
        self._blocks: dict[str, KnowledgeDocumentBlock] = {}
        self._memory_blocks: dict[str, MemoryBlock] = {}
        self._candidates: dict[str, MemoryCandidate] = {}
        self._transitions: dict[str, MemoryTierTransition] = {}
        self._embeddings: dict[tuple[str, str], MemoryEmbedding] = {}
        self._active_model_sets: dict[tuple[str, str], ActiveEmbeddingModelSet] = {}
        self._orphan_external_vector_ids: dict[tuple[str, str], str] = {}
        self._retention_snapshots: dict[tuple[str, str], RetentionSnapshot] = {}
        # SEFT-02 / SEPM-02 — entity/fact/episode rows.
        self._entities: dict[str, Any] = {}
        self._entity_aliases: dict[str, Any] = {}
        self._facts: dict[str, Any] = {}
        self._contradictions: dict[str, Any] = {}
        self._entity_summaries: dict[str, Any] = {}
        self._episodes: dict[str, Any] = {}
        self._episode_steps: dict[str, Any] = {}
        self._outcomes: dict[str, Any] = {}
        self._decisions: dict[str, Any] = {}
        self._procedures: dict[str, Any] = {}
        self._raw_episodes: dict[str, Any] = {}
        self._fact_convergence_links: dict[str, Any] = {}
        self._sync_conflicts: dict[str, Any] = {}
        self._freshness_entries: dict[str, Any] = {}
        self._source_entries: dict[str, Any] = {}
        self._source_ingests: dict[str, Any] = {}
        self._shared_attachments: dict[str, Any] = {}
        self._shared_mirrors: dict[str, Any] = {}
        self._shared_conflicts: dict[str, Any] = {}
        self._shared_usage_events: dict[str, Any] = {}
        self._changes: list[Any] = []
        self._next_cursor = 1
        # Integrity hashing stays opt-in for backward compatibility.
        self._integrity_hash_enabled = integrity_hash_enabled

    def put_record(self, record: MemoryRecord) -> str:
        stamped = populate_integrity_hash(record, enabled=self._integrity_hash_enabled)
        self._records[stamped.id] = stamped
        self._emit_change(
            object_type="record",
            object_id=stamped.id,
            payload=asdict(stamped),
            namespace=stamped.effective_namespace,
            schema_identifiers={"node_label": str(stamped.type)},
        )
        return stamped.id

    def upsert_record(
        self, scope: str, type: MemoryType, key: str, record_patch: dict[str, Any]
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
            record = record_from_dict(payload)
        else:
            payload = existing.__dict__.copy()
            payload.update(record_patch)
            payload["scope"] = scope
            payload["type"] = type
            payload["key"] = key
            payload["updated_at"] = now
            record = record_from_dict(payload)
        self.put_record(record)
        return record

    def get_record(self, record_id: str) -> MemoryRecord | None:
        return self._records.get(record_id)

    def list_records(self, options: ListQueryOptions) -> list[MemoryRecord]:
        records = [
            record
            for record in self._records.values()
            if record.scope in options.scopes
        ]
        records = [
            record
            for record in records
            if record_matches_namespaces(record, options.namespaces)
        ]
        if options.types:
            type_allow = set(options.types)
            records = [record for record in records if record.type in type_allow]
        if options.tiers:
            tier_allow = set(options.tiers)
            records = [record for record in records if record.tier in tier_allow]
        if not options.include_invalidated and not has_bitemporal_filter(options):
            records = [record for record in records if record.is_current_at()]
        if has_bitemporal_filter(options):
            records = [
                record
                for record in records
                if record_matches_bitemporal(record, options)
            ]
        reverse = options.order_by != RecordOrder.UPDATED_AT_ASC
        records.sort(key=lambda record: record.updated_at, reverse=reverse)
        if options.offset is not None:
            records = records[int(options.offset) :]
        if options.limit is not None:
            records = records[: int(options.limit)]
        return records

    def search_records(self, options: SearchQueryOptions) -> list[MemoryRecord]:
        records = self.list_records(
            ListQueryOptions(
                scopes=options.scopes,
                types=options.types,
                tiers=options.tiers,
                include_invalidated=options.include_invalidated,
                limit=None,
                offset=None,
                order_by=RecordOrder.UPDATED_AT_DESC,
                namespaces=options.namespaces,
                as_of=options.as_of,
                valid_at=options.valid_at,
                effective_during=options.effective_during,
                believed_at=options.believed_at,
            )
        )
        matches = [
            record for record in records if record_matches_query(record, options.query)
        ]
        if options.limit is not None:
            matches = matches[: int(options.limit)]
        return matches

    def put_relation(self, relation: MemoryRelation) -> str:
        self._relations[relation.relation_id] = relation
        namespace = self._records.get(relation.source_record_id)
        self._emit_change(
            object_type="relation",
            object_id=relation.relation_id,
            payload=asdict(relation),
            namespace=namespace.effective_namespace
            if namespace is not None
            else default_change_namespace(),
            schema_identifiers={"relation_type": str(relation.relation_type)},
        )
        return relation.relation_id

    def list_relations(
        self,
        record_id: str,
        *,
        direction: RelationDirection = "out",
        relation_types: list[Any] | None = None,
        limit: int | None = None,
    ) -> list[MemoryRelation]:
        if direction not in {"out", "in", "both"}:
            raise InvalidArgumentError(f"invalid relation direction: {direction!r}")
        relations = [
            relation
            for relation in self._relations.values()
            if (direction in {"out", "both"} and relation.source_record_id == record_id)
            or (direction in {"in", "both"} and relation.target_record_id == record_id)
        ]
        relations.sort(key=lambda relation: relation.created_at, reverse=True)
        if relation_types:
            allowed = {str(item) for item in relation_types}
            relations = [
                relation for relation in relations if relation.relation_type in allowed
            ]
        if limit is not None:
            relations = relations[: int(limit)]
        return relations

    def get_related_records(
        self,
        record_id: str,
        scopes: list[str],
        *,
        direction: RelationDirection = "out",
        relation_types: list[Any] | None = None,
        limit: int | None = None,
    ) -> list[MemoryRecord]:
        relations = self.list_relations(
            record_id,
            direction=direction,
            relation_types=relation_types,
            limit=limit,
        )
        scope_allow = set(scopes)
        records: list[MemoryRecord] = []
        for relation in relations:
            related_id = (
                relation.target_record_id
                if relation.source_record_id == record_id
                else relation.source_record_id
            )
            record = self.get_record(related_id)
            if record is not None and record.scope in scope_allow:
                records.append(record)
        return records[: int(limit)] if limit is not None else records

    def put_link(self, link: StructuralLink) -> str:
        self._links[link.link_id] = link
        schema_identifiers = {}
        if link.relation_type:
            schema_identifiers["relation_type"] = link.relation_type
        self._emit_change(
            object_type="link",
            object_id=link.link_id,
            payload=asdict(link),
            namespace=link.namespace,
            schema_identifiers=schema_identifiers,
        )
        return link.link_id

    def replace_record_links(
        self,
        record_id: str,
        links: list[StructuralLink],
    ) -> None:
        stale_ids = [
            link_id
            for link_id, link in self._links.items()
            if link.source_record_id == record_id
        ]
        for link_id in stale_ids:
            del self._links[link_id]
        for link in links:
            if link.source_record_id != record_id:
                raise InvalidArgumentError("link source_record_id must match record_id")
            self.put_link(link)

    def list_links(self, options: LinkQueryOptions) -> list[StructuralLink]:
        links = [
            link
            for link in self._links.values()
            if (
                options.direction in {"out", "both"}
                and link.source_record_id == options.record_id
            )
            or (
                options.direction in {"in", "both"}
                and link.target_record_id == options.record_id
            )
        ]
        links = [
            link
            for link in links
            if namespace_matches_filters(link.namespace, options.namespaces)
        ]
        if options.relation_types:
            allowed = {str(item) for item in options.relation_types}
            links = [link for link in links if link.relation_type in allowed]
        links.sort(key=lambda link: (link.created_at or "", link.link_id), reverse=True)
        bounded = [
            link.with_context_bounds(
                before=options.context_chars,
                after=options.context_chars,
            )
            for link in links
        ]
        if options.limit is not None:
            bounded = bounded[: int(options.limit)]
        return bounded

    def get_local_graph(self, options: LocalGraphOptions) -> GraphSnapshot:
        return build_local_graph(
            options,
            load_links=self.list_links,
            load_record=self.get_record,
            provenance={"store": "memory"},
        )

    def get_graph_snapshot(self, options: GraphSnapshotOptions) -> GraphSnapshot:
        records = self.list_records(
            ListQueryOptions(
                scopes=options.scopes,
                namespaces=options.namespaces,
                limit=options.max_nodes,
                include_invalidated=False,
            )
        )
        return build_graph_snapshot(
            records,
            list(self._links.values()),
            options,
            provenance={"store": "memory"},
        )

    def structural_search_records(
        self,
        query: StructuralSearchQuery,
        *,
        scopes: list[str],
    ) -> list[MemoryRecord]:
        records = self.list_records(
            ListQueryOptions(scopes=scopes, namespaces=query.namespaces)
        )
        matches = [
            record
            for record in records
            if record_matches_structural_query(
                record,
                query,
                outgoing_targets=[
                    link.raw_target
                    for link in self._links.values()
                    if link.source_record_id == record.id
                ],
                incoming_sources=[
                    link.source_record_id
                    for link in self._links.values()
                    if link.target_record_id == record.id
                ],
                blocks=[
                    block
                    for block in self._blocks.values()
                    if block.record_id == record.id
                ],
            )
        ]
        if query.sort == "title":
            matches.sort(key=lambda record: record.title or "")
        if query.limit is not None:
            matches = matches[: int(query.limit)]
        return matches

    def put_document_blocks(
        self,
        record_id: str,
        blocks: list[KnowledgeDocumentBlock],
    ) -> None:
        stale_ids = [
            block_id
            for block_id, block in self._blocks.items()
            if block.record_id == record_id
        ]
        for block_id in stale_ids:
            del self._blocks[block_id]
        record = self.get_record(record_id)
        namespace = (
            record.effective_namespace
            if record is not None
            else default_change_namespace()
        )
        for block in blocks:
            if block.record_id != record_id:
                raise InvalidArgumentError("block record_id must match record_id")
            self._blocks[block.block_id] = block
            self._emit_change(
                object_type="block",
                object_id=block.block_id,
                payload=block_to_dict(block),
                namespace=namespace,
                schema_identifiers={"node_label": "block"},
            )

    def list_document_blocks(
        self,
        *,
        record_id: str | None = None,
        document_id: str | None = None,
        block_id: str | None = None,
    ) -> list[KnowledgeDocumentBlock]:
        blocks = list(self._blocks.values())
        if record_id is not None:
            blocks = [block for block in blocks if block.record_id == record_id]
        if document_id is not None:
            blocks = [block for block in blocks if block.document_id == document_id]
        if block_id is not None:
            blocks = [block for block in blocks if block.block_id == block_id]
        blocks.sort(
            key=lambda block: (block.record_id, block.line_start or 0, block.block_id)
        )
        return blocks

    def put_memory_block(self, block: MemoryBlock) -> str:
        self._memory_blocks[block.block_id] = block
        self._emit_change(
            object_type="memory_block",
            object_id=block.block_id,
            payload=memory_block_to_dict(block),
            namespace=block.owner_namespace,
            schema_identifiers={
                "node_label": "memory_block",
                "class_name": block.class_name,
                "mode": block.mode,
            },
        )
        return block.block_id

    def get_memory_block(self, block_id: str) -> MemoryBlock | None:
        return self._memory_blocks.get(block_id)

    def list_memory_blocks(
        self,
        *,
        namespaces: list[MemoryNamespace] | None = None,
        class_names: list[str] | None = None,
        include_stale: bool = True,
        limit: int | None = None,
    ) -> list[MemoryBlock]:
        blocks = list(self._memory_blocks.values())
        if namespaces:
            blocks = [
                block
                for block in blocks
                if namespace_matches_filters(block.owner_namespace, namespaces)
            ]
        if class_names:
            allow = set(class_names)
            blocks = [block for block in blocks if block.class_name in allow]
        if not include_stale:
            now = utc_now_iso()
            blocks = [
                block
                for block in blocks
                if not (block.stale_after is not None and block.stale_after <= now)
            ]
        blocks.sort(
            key=lambda block: (block.class_name, block.created_at, block.block_id)
        )
        if limit is not None:
            blocks = blocks[: int(limit)]
        return blocks

    def update_memory_block_content(
        self,
        block_id: str,
        *,
        new_content: str,
        actor: str,
        operator_action: bool = False,
    ) -> MemoryBlock:
        block = self._memory_blocks.get(block_id)
        if block is None:
            raise NotFoundError(
                f"memory block {block_id!r} not found",
                details={"block_id": block_id},
            )
        _enforce_block_edit_gate(
            block,
            operator_action=operator_action,
            actor=actor,
            operation="update_content",
        )
        if not isinstance(new_content, str):
            raise InvalidArgumentError("new_content must be a string")
        updated = replace(
            block,
            content=new_content,
            last_updated_at=utc_now_iso(),
            last_updated_by=actor,
        )
        self._memory_blocks[block_id] = updated
        self._emit_change(
            object_type="memory_block",
            object_id=block_id,
            payload=memory_block_to_dict(updated),
            namespace=updated.owner_namespace,
            schema_identifiers={
                "node_label": "memory_block",
                "class_name": updated.class_name,
                "mode": updated.mode,
                "operation": "update_content",
            },
        )
        return updated

    def delete_memory_block(
        self,
        block_id: str,
        *,
        actor: str,
        operator_action: bool = False,
    ) -> bool:
        block = self._memory_blocks.get(block_id)
        if block is None:
            return False
        _enforce_block_edit_gate(
            block,
            operator_action=operator_action,
            actor=actor,
            operation="delete",
        )
        del self._memory_blocks[block_id]
        self._emit_change(
            object_type="memory_block",
            object_id=block_id,
            payload=memory_block_to_dict(block),
            namespace=block.owner_namespace,
            schema_identifiers={
                "node_label": "memory_block",
                "class_name": block.class_name,
                "mode": block.mode,
                "operation": "delete",
            },
        )
        return True

    def mark_memory_block_stale_after(
        self,
        block_id: str,
        *,
        stale_after: str | None,
    ) -> MemoryBlock:
        block = self._memory_blocks.get(block_id)
        if block is None:
            raise NotFoundError(
                f"memory block {block_id!r} not found",
                details={"block_id": block_id},
            )
        updated = replace(block, stale_after=stale_after)
        self._memory_blocks[block_id] = updated
        return updated

    def put_candidate(self, candidate: MemoryCandidate) -> str:
        self._candidates[candidate.candidate_id] = candidate
        self._emit_change(
            object_type="candidate",
            object_id=candidate.candidate_id,
            payload=asdict(candidate),
            namespace=candidate.namespace
            or MemoryNamespace.from_scope(candidate.proposed_scope),
            schema_identifiers={"node_label": str(candidate.type)},
        )
        return candidate.candidate_id

    def get_candidate(self, candidate_id: str) -> MemoryCandidate | None:
        return self._candidates.get(candidate_id)

    def list_candidates(self, options: CandidateListOptions) -> list[MemoryCandidate]:
        candidates = list(self._candidates.values())
        if options.session_id is not None:
            candidates = [
                candidate
                for candidate in candidates
                if candidate.session_id == options.session_id
            ]
        if options.proposed_scope is not None:
            candidates = [
                candidate
                for candidate in candidates
                if candidate.proposed_scope == options.proposed_scope
            ]
        if options.status is not None:
            candidates = [
                candidate
                for candidate in candidates
                if candidate.status == options.status
            ]
        candidates.sort(
            key=lambda candidate: candidate.updated_at or candidate.created_at or "",
            reverse=True,
        )
        if options.limit is not None:
            candidates = candidates[: int(options.limit)]
        return candidates

    def update_candidate(
        self, candidate_id: str, patch: dict[str, Any]
    ) -> MemoryCandidate:
        candidate = self.get_candidate(candidate_id)
        if candidate is None:
            raise InvalidArgumentError(f"unknown candidate_id: {candidate_id}")
        payload = candidate.__dict__.copy()
        payload.update(patch)
        payload["updated_at"] = utc_now_iso()
        updated = MemoryCandidate(**payload)
        self.put_candidate(updated)
        return updated

    def promote_candidate(self, candidate_id: str, target_scope: str) -> MemoryRecord:
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
            namespace=candidate.namespace or MemoryNamespace.from_scope(target_scope),
            event_time=candidate.created_at or now,
        )
        self.put_record(record)
        self.put_candidate(replace(candidate, status="promoted", updated_at=now))
        return record

    def list_tier_transitions(
        self,
        *,
        record_id: str | None = None,
        scopes: list[str] | None = None,
        limit: int | None = None,
    ) -> list[MemoryTierTransition]:
        transitions = list(self._transitions.values())
        if record_id is not None:
            transitions = [
                transition
                for transition in transitions
                if transition.record_id == record_id
            ]
        if scopes:
            scope_allow = set(scopes)
            transitions = [
                transition
                for transition in transitions
                if transition.scope in scope_allow
            ]
        transitions.sort(key=lambda transition: transition.transition_at, reverse=True)
        if limit is not None:
            transitions = transitions[: int(limit)]
        return transitions

    def put_tier_transition(self, transition: MemoryTierTransition) -> str:
        self._transitions[transition.transition_id] = transition
        self._emit_change(
            object_type="tier_transition",
            object_id=transition.transition_id,
            payload=asdict(transition),
            namespace=MemoryNamespace.from_scope(transition.scope),
            schema_identifiers={"node_label": str(transition.record_type)},
        )
        return transition.transition_id

    def _mark_external_vector_active(self, embedding: MemoryEmbedding) -> None:
        if not embedding.external_vector_id:
            return
        orphan_key = (namespace_key(embedding.namespace), embedding.external_vector_id)
        self._orphan_external_vector_ids.pop(orphan_key, None)

    def _maybe_mark_external_vector_orphan(self, embedding: MemoryEmbedding) -> None:
        if not embedding.external_vector_id:
            return
        still_referenced = any(
            candidate.external_vector_id == embedding.external_vector_id
            and candidate.namespace == embedding.namespace
            for candidate in self._embeddings.values()
        )
        if still_referenced:
            return
        orphan_key = (namespace_key(embedding.namespace), embedding.external_vector_id)
        self._orphan_external_vector_ids[orphan_key] = embedding.updated_at

    def put_embedding(self, embedding: MemoryEmbedding) -> str:
        key = (embedding.record_id, embedding.vector_space)
        existing = self._embeddings.get(key)
        if existing is not None and existing.dimension != embedding.dimension:
            raise InvalidArgumentError("embedding dimension cannot change for key")
        self._embeddings[key] = embedding
        if (
            existing is not None
            and existing.external_vector_id != embedding.external_vector_id
        ):
            self._maybe_mark_external_vector_orphan(existing)
        self._mark_external_vector_active(embedding)
        return embedding.key

    def get_embedding(
        self,
        record_id: str,
        vector_space: str,
        *,
        include_vector: bool = True,
    ) -> MemoryEmbedding | None:
        embedding = self._embeddings.get((record_id, vector_space))
        if embedding is None:
            return None
        return embedding if include_vector else embedding.without_vector()

    def list_embeddings(
        self,
        options: EmbeddingListOptions,
    ) -> list[MemoryEmbedding]:
        embeddings = list(self._embeddings.values())
        if options.record_id is not None:
            embeddings = [
                embedding
                for embedding in embeddings
                if embedding.record_id == options.record_id
            ]
        if options.vector_space is not None:
            embeddings = [
                embedding
                for embedding in embeddings
                if embedding.vector_space == options.vector_space
            ]
        if options.namespaces:
            embeddings = [
                embedding
                for embedding in embeddings
                if any(
                    embedding.namespace.matches(namespace)
                    for namespace in options.namespaces
                )
            ]
        embeddings.sort(key=lambda embedding: embedding.updated_at, reverse=True)
        if options.limit is not None:
            embeddings = embeddings[: int(options.limit)]
        if not options.include_vectors:
            embeddings = [embedding.without_vector() for embedding in embeddings]
        return embeddings

    def delete_embedding(self, record_id: str, vector_space: str) -> bool:
        embedding = self._embeddings.pop((record_id, vector_space), None)
        if embedding is None:
            return False
        self._maybe_mark_external_vector_orphan(embedding)
        return True

    def put_active_model_set(self, model_set: ActiveEmbeddingModelSet) -> str:
        self._active_model_sets[model_set.key] = model_set
        self._emit_change(
            object_type="active_embedding_model_set",
            object_id=f"{model_set.key[0]}:{model_set.vector_space}",
            payload=model_set.to_dict(),
            namespace=model_set.namespace,
            schema_identifiers={"node_label": "active_embedding_model_set"},
        )
        return f"{model_set.key[0]}:{model_set.vector_space}"

    def get_active_model_set(
        self,
        *,
        namespace: MemoryNamespace,
        vector_space: str,
    ) -> ActiveEmbeddingModelSet | None:
        return self._active_model_sets.get((namespace_key(namespace), vector_space))

    def list_active_model_sets(
        self,
        *,
        namespaces: list[MemoryNamespace] | None = None,
        vector_space: str | None = None,
        limit: int | None = None,
    ) -> list[ActiveEmbeddingModelSet]:
        model_sets = list(self._active_model_sets.values())
        if namespaces:
            model_sets = [
                model_set
                for model_set in model_sets
                if any(
                    model_set.namespace.matches(namespace) for namespace in namespaces
                )
            ]
        if vector_space is not None:
            model_sets = [
                model_set
                for model_set in model_sets
                if model_set.vector_space == vector_space
            ]
        model_sets.sort(
            key=lambda model_set: (
                namespace_key(model_set.namespace),
                model_set.vector_space,
            )
        )
        if limit is not None:
            model_sets = model_sets[: int(limit)]
        return model_sets

    def list_orphan_external_vector_ids(
        self,
        *,
        namespace: MemoryNamespace,
        since: str | None = None,
    ) -> list[tuple[str, str]]:
        prefix = namespace_key(namespace)
        pairs = [
            (external_vector_id, last_seen_at)
            for (
                namespace_id,
                external_vector_id,
            ), last_seen_at in self._orphan_external_vector_ids.items()
            if namespace_id == prefix and (since is None or last_seen_at >= since)
        ]
        pairs.sort(key=lambda item: (item[1], item[0]))
        return pairs

    def tombstone_record(
        self,
        record_id: str,
        *,
        deleted_at: str,
        reason: str,
    ) -> MemoryRecord:
        record = self.get_record(record_id)
        if record is None:
            raise NotFoundError(f"record not found: {record_id}")
        tombstone = replace(
            record,
            is_deleted=True,
            deleted_at=deleted_at,
            deleted_reason=reason,
            valid_to=record.valid_to or deleted_at,
            updated_at=deleted_at,
        )
        self.put_record(tombstone)
        self._emit_change(
            object_type="record",
            object_id=record_id,
            payload={
                "record_id": record_id,
                "deleted_at": deleted_at,
                "reason": reason,
            },
            namespace=tombstone.effective_namespace,
            schema_identifiers={"node_label": str(tombstone.type)},
            operation="delete",
        )
        return tombstone

    def cascade_tombstones(
        self,
        record_id: str,
        *,
        deleted_at: str,
        reason: str,
    ) -> DeletionCascadeResult:
        tombstone = self.tombstone_record(
            record_id,
            deleted_at=deleted_at,
            reason=reason,
        )
        relation_ids = [
            relation_id
            for relation_id, relation in self._relations.items()
            if relation.source_record_id == record_id
            or relation.target_record_id == record_id
        ]
        for relation_id in relation_ids:
            self._relations.pop(relation_id, None)
        link_ids = [
            link_id
            for link_id, link in self._links.items()
            if link.source_record_id == record_id or link.target_record_id == record_id
        ]
        for link_id in link_ids:
            self._links.pop(link_id, None)
        block_ids = [
            block_id
            for block_id, block in self._blocks.items()
            if block.record_id == record_id
        ]
        for block_id in block_ids:
            self._blocks.pop(block_id, None)
        embedding_keys = [
            f"{embedding.record_id}:{embedding.vector_space}"
            for embedding in self.list_embeddings(
                EmbeddingListOptions(record_id=record_id)
            )
        ]
        for embedding in list(
            self.list_embeddings(EmbeddingListOptions(record_id=record_id))
        ):
            self.delete_embedding(embedding.record_id, embedding.vector_space)
        return DeletionCascadeResult(
            root_record_id=record_id,
            tombstoned_record_ids=[tombstone.id],
            removed_relation_ids=relation_ids,
            removed_link_ids=link_ids,
            removed_block_ids=block_ids,
            removed_embedding_keys=embedding_keys,
        )

    def erasure_audit_export(
        self,
        *,
        record_id: str | None = None,
        namespaces: list[MemoryNamespace] | None = None,
    ) -> ErasureAuditExport:
        records = [
            record
            for record in self._records.values()
            if record.is_deleted
            and (record_id is None or record.id == record_id)
            and record_matches_namespaces(record, namespaces)
        ]
        return ErasureAuditExport(
            entries=[
                ErasureAuditEntry(
                    record_id=record.id,
                    namespace=record.effective_namespace,
                    deleted_at=record.deleted_at or record.updated_at,
                    reason=record.deleted_reason or "",
                    cascaded=bool(record.meta.get("cascade_deleted", False)),
                )
                for record in records
            ]
        )

    def history(self, scope: str, type: MemoryType, key: str) -> list[MemoryRecord]:
        records = [
            record
            for record in self._records.values()
            if record.scope == scope and record.type == type and record.key == key
        ]
        records.sort(key=lambda record: record.updated_at, reverse=True)
        return records

    def put_retention_snapshot(self, snapshot: RetentionSnapshot) -> str:
        key = (namespace_key(snapshot.namespace), snapshot.name)
        self._retention_snapshots[key] = snapshot
        self._emit_change(
            object_type="retention_snapshot",
            object_id=snapshot.snapshot_id,
            payload=snapshot.to_dict(),
            namespace=snapshot.namespace,
            schema_identifiers={"node_label": "retention_snapshot"},
        )
        return snapshot.snapshot_id

    def get_retention_snapshot(
        self,
        *,
        name: str,
        namespace: MemoryNamespace,
    ) -> RetentionSnapshot | None:
        return self._retention_snapshots.get((namespace_key(namespace), name))

    def list_retention_snapshots(
        self,
        *,
        namespaces: list[MemoryNamespace] | None = None,
        limit: int | None = None,
    ) -> list[RetentionSnapshot]:
        rows = list(self._retention_snapshots.values())
        if namespaces:
            rows = [
                snapshot
                for snapshot in rows
                if any(
                    snapshot.namespace.matches(namespace) for namespace in namespaces
                )
            ]
        rows.sort(
            key=lambda snapshot: (
                namespace_key(snapshot.namespace),
                snapshot.name,
                snapshot.created_at,
            )
        )
        if limit is not None:
            rows = rows[: int(limit)]
        return rows

    def record_count(self) -> int:
        return len(self._records)

    def candidate_count(self) -> int:
        return len(self._candidates)

    # SEFT-02 + SEFT-03 + SEFT-04 — entity / fact / contradiction / summary.

    def put_entity(self, entity) -> str:
        from sophiagraph.storage.graph_helpers import entity_to_dict

        self._entities[entity.entity_id] = entity
        self._emit_change(
            object_type="entity",
            object_id=entity.entity_id,
            payload=entity_to_dict(entity),
            namespace=entity.namespace,
            schema_identifiers={
                "node_label": "entity",
                "entity_type": entity.entity_type,
            },
        )
        return entity.entity_id

    def get_entity(self, entity_id):
        return self._entities.get(entity_id)

    def list_entities(
        self,
        *,
        namespaces=None,
        canonical_name=None,
        entity_type=None,
        include_invalidated=False,
        limit=None,
    ):
        from sophiagraph.storage.entity_episode_store import entity_passes

        rows = [
            entity
            for entity in self._entities.values()
            if entity_passes(
                entity,
                namespaces=namespaces,
                canonical_name=canonical_name,
                entity_type=entity_type,
                include_invalidated=include_invalidated,
            )
        ]
        rows.sort(key=lambda e: (e.canonical_name, e.entity_id))
        if limit is not None:
            rows = rows[: int(limit)]
        return rows

    def put_entity_alias(self, alias) -> str:
        from sophiagraph.storage.graph_helpers import entity_alias_to_dict

        self._entity_aliases[alias.alias_id] = alias
        self._emit_change(
            object_type="entity_alias",
            object_id=alias.alias_id,
            payload=entity_alias_to_dict(alias),
            namespace=alias.namespace,
            schema_identifiers={
                "node_label": "entity_alias",
                "entity_id": alias.entity_id,
            },
        )
        return alias.alias_id

    def list_entity_aliases(
        self,
        *,
        entity_id=None,
        alias_name=None,
        namespaces=None,
        limit=None,
    ):
        from sophiagraph.storage.entity_episode_store import entity_alias_passes

        rows = [
            alias
            for alias in self._entity_aliases.values()
            if entity_alias_passes(
                alias,
                namespaces=namespaces,
                entity_id=entity_id,
                alias_name=alias_name,
            )
        ]
        rows.sort(key=lambda a: (a.alias_name, a.alias_id))
        if limit is not None:
            rows = rows[: int(limit)]
        return rows

    def put_fact(self, fact) -> str:
        from sophiagraph.storage.graph_helpers import fact_to_dict

        self._facts[fact.fact_id] = fact
        self._emit_change(
            object_type="fact",
            object_id=fact.fact_id,
            payload=fact_to_dict(fact),
            namespace=fact.namespace,
            schema_identifiers={
                "node_label": "fact",
                "predicate": fact.predicate,
            },
        )
        return fact.fact_id

    def get_fact(self, fact_id):
        return self._facts.get(fact_id)

    def list_facts(
        self,
        *,
        namespaces=None,
        subject_entity_id=None,
        object_entity_id=None,
        predicate=None,
        valid_at=None,
        learned_at=None,
        active_state="active",
        source_episode_id=None,
        include_invalidated=False,
        limit=None,
    ):
        from sophiagraph.storage.entity_episode_store import fact_passes

        rows = [
            fact
            for fact in self._facts.values()
            if fact_passes(
                fact,
                namespaces=namespaces,
                subject_entity_id=subject_entity_id,
                object_entity_id=object_entity_id,
                predicate=predicate,
                valid_at=valid_at,
                learned_at=learned_at,
                active_state=active_state,
                source_episode_id=source_episode_id,
                include_invalidated=include_invalidated,
            )
        ]
        rows.sort(key=lambda f: (f.observed_at or "", f.fact_id))
        if limit is not None:
            rows = rows[: int(limit)]
        return rows

    def record_contradiction(self, contradiction):
        from dataclasses import replace

        from sophiagraph.storage.entity_episode_store import (
            validate_contradiction_references,
        )
        from sophiagraph.storage.graph_helpers import contradiction_to_dict

        validate_contradiction_references(
            contradiction, known_fact_ids=self._facts.keys()
        )
        # Apply decision semantics while preserving both facts.
        target = self._facts[contradiction.target_fact_id]
        if contradiction.decision == "supersedes":
            updated = replace(
                target,
                invalidated_at=contradiction.decided_at,
                superseded_by_fact_id=contradiction.contradicting_fact_id,
            )
            self._facts[contradiction.target_fact_id] = updated
        elif contradiction.decision == "invalidates_target":
            updated = replace(target, invalidated_at=contradiction.decided_at)
            self._facts[contradiction.target_fact_id] = updated
        # "both_valid" leaves both facts intact.
        self._contradictions[contradiction.contradiction_id] = contradiction
        self._emit_change(
            object_type="contradiction",
            object_id=contradiction.contradiction_id,
            payload=contradiction_to_dict(contradiction),
            namespace=contradiction.namespace,
            schema_identifiers={
                "node_label": "contradiction",
                "decision": contradiction.decision,
            },
        )
        return contradiction

    def list_contradictions(
        self,
        *,
        target_fact_id=None,
        contradicting_fact_id=None,
        namespaces=None,
        limit=None,
    ):
        from sophiagraph.storage.entity_episode_store import contradiction_passes

        rows = [
            c
            for c in self._contradictions.values()
            if contradiction_passes(
                c,
                namespaces=namespaces,
                target_fact_id=target_fact_id,
                contradicting_fact_id=contradicting_fact_id,
            )
        ]
        rows.sort(key=lambda c: (c.decided_at, c.contradiction_id))
        if limit is not None:
            rows = rows[: int(limit)]
        return rows

    def put_entity_summary(self, summary) -> str:
        from sophiagraph.storage.graph_helpers import entity_summary_to_dict

        self._entity_summaries[summary.summary_id] = summary
        self._emit_change(
            object_type="entity_summary",
            object_id=summary.summary_id,
            payload=entity_summary_to_dict(summary),
            namespace=summary.namespace,
            schema_identifiers={
                "node_label": "entity_summary",
                "entity_id": summary.entity_id,
            },
        )
        return summary.summary_id

    def list_entity_summaries(
        self,
        *,
        entity_id=None,
        namespaces=None,
        include_invalidated=False,
        limit=None,
    ):
        from sophiagraph.storage.entity_episode_store import entity_summary_passes

        rows = [
            s
            for s in self._entity_summaries.values()
            if entity_summary_passes(
                s,
                namespaces=namespaces,
                entity_id=entity_id,
                include_invalidated=include_invalidated,
            )
        ]
        rows.sort(key=lambda s: (s.updated_at or s.created_at or "", s.summary_id))
        if limit is not None:
            rows = rows[: int(limit)]
        return rows

    # SEPM-02 + SEPM-03 — episode / step / outcome / decision / procedure.

    def put_episode(self, episode) -> str:
        from sophiagraph.storage.graph_helpers import episode_to_dict

        self._episodes[episode.episode_id] = episode
        self._emit_change(
            object_type="episode",
            object_id=episode.episode_id,
            payload=episode_to_dict(episode),
            namespace=episode.namespace,
            schema_identifiers={"node_label": "episode", "status": episode.status},
        )
        return episode.episode_id

    def get_episode(self, episode_id):
        return self._episodes.get(episode_id)

    def list_episodes(
        self,
        *,
        namespaces=None,
        status=None,
        task_id=None,
        artifact_id=None,
        tool_id=None,
        started_after=None,
        started_before=None,
        limit=None,
    ):
        from sophiagraph.storage.entity_episode_store import episode_passes

        rows = [
            ep
            for ep in self._episodes.values()
            if episode_passes(
                ep,
                namespaces=namespaces,
                status=status,
                task_id=task_id,
                artifact_id=artifact_id,
                tool_id=tool_id,
                started_after=started_after,
                started_before=started_before,
            )
        ]
        rows.sort(key=lambda e: (e.started_at, e.episode_id), reverse=True)
        if limit is not None:
            rows = rows[: int(limit)]
        return rows

    def put_episode_step(self, step) -> str:
        from sophiagraph.storage.graph_helpers import episode_step_to_dict

        self._episode_steps[step.step_id] = step
        self._emit_change(
            object_type="episode_step",
            object_id=step.step_id,
            payload=episode_step_to_dict(step),
            namespace=step.namespace,
            schema_identifiers={"node_label": "episode_step", "kind": step.kind},
        )
        return step.step_id

    def list_episode_steps(self, *, episode_id, kind=None, limit=None):
        from sophiagraph.storage.entity_episode_store import episode_step_passes

        rows = [
            s
            for s in self._episode_steps.values()
            if episode_step_passes(s, episode_id=episode_id, kind=kind)
        ]
        rows.sort(key=lambda s: (s.sequence, s.step_id))
        if limit is not None:
            rows = rows[: int(limit)]
        return rows

    def put_outcome(self, outcome) -> str:
        from sophiagraph.storage.graph_helpers import outcome_to_dict

        self._outcomes[outcome.outcome_id] = outcome
        self._emit_change(
            object_type="outcome",
            object_id=outcome.outcome_id,
            payload=outcome_to_dict(outcome),
            namespace=outcome.namespace,
            schema_identifiers={"node_label": "outcome", "status": outcome.status},
        )
        return outcome.outcome_id

    def list_outcomes(
        self,
        *,
        episode_id=None,
        step_id=None,
        status=None,
        namespaces=None,
        limit=None,
    ):
        from sophiagraph.storage.entity_episode_store import outcome_passes

        rows = [
            o
            for o in self._outcomes.values()
            if outcome_passes(
                o,
                episode_id=episode_id,
                step_id=step_id,
                status=status,
                namespaces=namespaces,
            )
        ]
        rows.sort(key=lambda o: (o.occurred_at, o.outcome_id), reverse=True)
        if limit is not None:
            rows = rows[: int(limit)]
        return rows

    def put_decision(self, decision) -> str:
        from sophiagraph.storage.graph_helpers import decision_to_dict

        self._decisions[decision.decision_id] = decision
        self._emit_change(
            object_type="decision",
            object_id=decision.decision_id,
            payload=decision_to_dict(decision),
            namespace=decision.namespace,
            schema_identifiers={"node_label": "decision"},
        )
        return decision.decision_id

    def list_decisions(self, *, episode_id=None, namespaces=None, limit=None):
        from sophiagraph.storage.entity_episode_store import decision_passes

        rows = [
            d
            for d in self._decisions.values()
            if decision_passes(d, episode_id=episode_id, namespaces=namespaces)
        ]
        rows.sort(key=lambda d: (d.occurred_at, d.decision_id), reverse=True)
        if limit is not None:
            rows = rows[: int(limit)]
        return rows

    def put_procedure(self, procedure) -> str:
        from sophiagraph.storage.graph_helpers import procedure_to_dict

        self._procedures[procedure.procedure_id] = procedure
        self._emit_change(
            object_type="procedure",
            object_id=procedure.procedure_id,
            payload=procedure_to_dict(procedure),
            namespace=procedure.namespace,
            schema_identifiers={
                "node_label": "procedure",
                "promotion_tier": procedure.promotion_tier,
            },
        )
        return procedure.procedure_id

    def get_procedure(self, procedure_id):
        return self._procedures.get(procedure_id)

    def list_procedures(
        self,
        *,
        namespaces=None,
        promotion_tier=None,
        include_invalidated=False,
        limit=None,
    ):
        from sophiagraph.storage.entity_episode_store import procedure_passes

        rows = [
            p
            for p in self._procedures.values()
            if procedure_passes(
                p,
                namespaces=namespaces,
                promotion_tier=promotion_tier,
                include_invalidated=include_invalidated,
            )
        ]
        rows.sort(
            key=lambda p: (p.updated_at or p.created_at, p.procedure_id), reverse=True
        )
        if limit is not None:
            rows = rows[: int(limit)]
        return rows

    def put_raw_episode(self, episode) -> str:
        from sophiagraph.storage.graph_helpers import raw_episode_to_dict

        self._raw_episodes[episode.episode_id] = episode
        self._emit_change(
            object_type="raw_episode",
            object_id=episode.episode_id,
            payload=raw_episode_to_dict(episode),
            namespace=episode.namespace,
            schema_identifiers={
                "node_label": "raw_episode",
                "kind": episode.kind,
            },
        )
        return episode.episode_id

    def get_raw_episode(self, episode_id):
        return self._raw_episodes.get(episode_id)

    def list_raw_episodes(
        self,
        *,
        namespaces=None,
        kind=None,
        source=None,
        occurred_after=None,
        occurred_before=None,
        include_invalidated=False,
        limit=None,
    ):
        from sophiagraph.storage.entity_episode_store import (
            RawEpisodeListOptions,
            raw_episode_passes,
        )

        options = RawEpisodeListOptions(
            namespaces=namespaces,
            kind=kind,
            source=source,
            occurred_after=occurred_after,
            occurred_before=occurred_before,
            include_invalidated=include_invalidated,
            limit=limit,
        )

        rows = [
            e
            for e in self._raw_episodes.values()
            if raw_episode_passes(e, options=options)
        ]
        rows.sort(key=lambda e: (e.occurred_at, e.episode_id), reverse=True)
        if limit is not None:
            rows = rows[: int(limit)]
        return rows

    def put_fact_convergence_link(self, link) -> str:
        from sophiagraph.storage.graph_helpers import fact_convergence_link_to_dict

        self._fact_convergence_links[link.link_id] = link
        self._emit_change(
            object_type="fact_convergence_link",
            object_id=link.link_id,
            payload=fact_convergence_link_to_dict(link),
            namespace=link.namespace,
            schema_identifiers={
                "node_label": "fact_convergence_link",
                "role": link.role,
            },
        )
        return link.link_id

    def list_fact_convergence_links(
        self,
        *,
        fact_id=None,
        episode_id=None,
        namespaces=None,
        limit=None,
    ):
        from sophiagraph.storage.entity_episode_store import (
            fact_convergence_link_passes,
        )

        rows = [
            link
            for link in self._fact_convergence_links.values()
            if fact_convergence_link_passes(
                link,
                fact_id=fact_id,
                episode_id=episode_id,
                namespaces=namespaces,
            )
        ]
        rows.sort(key=lambda link: (link.created_at, link.link_id))
        if limit is not None:
            rows = rows[: int(limit)]
        return rows

    # Ontology storage.

    def put_ontology(self, ontology):
        from sophiagraph.contracts.errors import OntologyVersionConflictError
        from sophiagraph.storage.graph_helpers import ontology_to_dict

        key = (ontology.ontology_id, ontology.version)
        existing = self._ontologies.get(key) if hasattr(self, "_ontologies") else None
        if not hasattr(self, "_ontologies"):
            self._ontologies = {}
        if existing is not None and ontology_to_dict(existing) != ontology_to_dict(
            ontology
        ):
            raise OntologyVersionConflictError(
                f"ontology {ontology.ontology_id!r}@{ontology.version!r} already exists "
                f"with a different payload; pick a new version or call delete+put",
                details={
                    "ontology_id": ontology.ontology_id,
                    "version": ontology.version,
                },
            )
        self._ontologies[key] = ontology
        self._emit_change(
            object_type="ontology",
            object_id=f"{ontology.ontology_id}@{ontology.version}",
            payload=ontology_to_dict(ontology),
            namespace=ontology.namespace,
            schema_identifiers={
                "node_label": "ontology",
                "ontology_id": ontology.ontology_id,
                "version": ontology.version,
            },
        )
        return key

    def get_ontology(self, *, ontology_id, version):
        if not hasattr(self, "_ontologies"):
            self._ontologies = {}
        return self._ontologies.get((ontology_id, version))

    def list_ontologies(
        self,
        *,
        ontology_id=None,
        owner=None,
        namespaces=None,
        limit=None,
    ):
        from sophiagraph.storage.graph_helpers import namespace_matches_filters

        if not hasattr(self, "_ontologies"):
            self._ontologies = {}
        rows = list(self._ontologies.values())
        if ontology_id:
            rows = [o for o in rows if o.ontology_id == ontology_id]
        if owner:
            rows = [o for o in rows if o.owner == owner]
        rows = [o for o in rows if namespace_matches_filters(o.namespace, namespaces)]
        rows.sort(key=lambda o: (o.ontology_id, o.version))
        if limit is not None:
            rows = rows[: int(limit)]
        return rows

    # Artifact reference storage.

    def put_artifact(self, artifact):
        from dataclasses import asdict

        if not hasattr(self, "_artifacts"):
            self._artifacts = {}
        self._artifacts[artifact.artifact_id] = artifact
        payload = asdict(artifact)
        payload["namespace"] = artifact.namespace.as_dict()
        self._emit_change(
            object_type="artifact",
            object_id=artifact.artifact_id,
            payload=payload,
            namespace=artifact.namespace,
            schema_identifiers={
                "node_label": "artifact",
                "artifact_id": artifact.artifact_id,
            },
        )
        return artifact.artifact_id

    def get_artifact(self, artifact_id):
        if not hasattr(self, "_artifacts"):
            self._artifacts = {}
        return self._artifacts.get(artifact_id)

    def list_artifacts(
        self,
        *,
        namespaces=None,
        target_record_id=None,
        source_class=None,
        limit=None,
    ):
        from sophiagraph.storage.graph_helpers import namespace_matches_filters

        if not hasattr(self, "_artifacts"):
            self._artifacts = {}
        rows = list(self._artifacts.values())
        rows = [a for a in rows if namespace_matches_filters(a.namespace, namespaces)]
        if target_record_id is not None:
            rows = [a for a in rows if a.target_record_id == target_record_id]
        if source_class is not None:
            rows = [a for a in rows if a.source_class == source_class]
        rows.sort(key=lambda a: a.artifact_id)
        if limit is not None:
            rows = rows[: int(limit)]
        return rows

    # Canvas board storage.

    def put_canvas_board(self, board):
        from sophiagraph.canvas import canvas_board_to_dict

        if not hasattr(self, "_canvas_boards"):
            self._canvas_boards = {}
        self._canvas_boards[board.board_id] = board
        self._emit_change(
            object_type="canvas",
            object_id=board.board_id,
            payload=canvas_board_to_dict(board),
            namespace=board.namespace,
            schema_identifiers={
                "node_label": "canvas_board",
                "board_id": board.board_id,
            },
        )
        return board.board_id

    def get_canvas_board(self, board_id):
        if not hasattr(self, "_canvas_boards"):
            self._canvas_boards = {}
        return self._canvas_boards.get(board_id)

    def list_canvas_boards(self, *, namespaces=None, limit=None):
        from sophiagraph.storage.graph_helpers import namespace_matches_filters

        if not hasattr(self, "_canvas_boards"):
            self._canvas_boards = {}
        rows = list(self._canvas_boards.values())
        rows = [b for b in rows if namespace_matches_filters(b.namespace, namespaces)]
        rows.sort(key=lambda b: b.board_id)
        if limit is not None:
            rows = rows[: int(limit)]
        return rows

    def delete_canvas_board(self, board_id):
        if not hasattr(self, "_canvas_boards"):
            self._canvas_boards = {}
        if board_id in self._canvas_boards:
            board = self._canvas_boards.pop(board_id)
            self._emit_change(
                object_type="canvas",
                object_id=board_id,
                operation="delete",
                payload={"board_id": board_id},
                namespace=board.namespace,
                schema_identifiers={
                    "node_label": "canvas_board",
                    "board_id": board_id,
                },
            )
            return True
        return False

    # Lifecycle policy storage.

    def put_lifecycle_policy(self, policy):
        if not hasattr(self, "_lifecycle_policies"):
            self._lifecycle_policies = {}
        self._lifecycle_policies[policy.policy_id] = policy
        self._emit_change(
            object_type="lifecycle_policy",
            object_id=policy.policy_id,
            payload={
                "policy_id": policy.policy_id,
                "namespace_filter": policy.namespace_filter.as_dict(),
                "ttl_active_iso": policy.ttl_active_iso,
                "ttl_cooling_iso": policy.ttl_cooling_iso,
            },
            namespace=policy.namespace_filter,
            schema_identifiers={
                "node_label": "lifecycle_policy",
                "policy_id": policy.policy_id,
            },
        )
        return policy.policy_id

    def get_lifecycle_policy(self, policy_id):
        if not hasattr(self, "_lifecycle_policies"):
            self._lifecycle_policies = {}
        return self._lifecycle_policies.get(policy_id)

    def list_lifecycle_policies(
        self,
        *,
        namespaces=None,
        limit=None,
    ):
        from sophiagraph.storage.graph_helpers import namespace_matches_filters

        if not hasattr(self, "_lifecycle_policies"):
            self._lifecycle_policies = {}
        rows = list(self._lifecycle_policies.values())
        rows = [
            p for p in rows if namespace_matches_filters(p.namespace_filter, namespaces)
        ]
        rows.sort(key=lambda p: p.policy_id)
        if limit is not None:
            rows = rows[: int(limit)]
        return rows

    # Local-first sync, freshness, connector, and shared-block storage.

    def put_sync_conflict(self, conflict):
        from sophiagraph.sync import sync_conflict_to_dict

        self._sync_conflicts[conflict.conflict_id] = conflict
        self._emit_change(
            object_type="sync_conflict",
            object_id=conflict.conflict_id,
            payload=sync_conflict_to_dict(conflict),
            namespace=conflict.namespace,
            schema_identifiers={"node_label": "sync_conflict", "kind": conflict.kind},
        )
        return conflict.conflict_id

    def get_sync_conflict(self, conflict_id):
        return self._sync_conflicts.get(conflict_id)

    def list_sync_conflicts(
        self,
        *,
        namespaces=None,
        status=None,
        source_id=None,
        limit=None,
    ):
        from sophiagraph.storage.graph_helpers import namespace_matches_filters

        rows = [
            row
            for row in self._sync_conflicts.values()
            if namespace_matches_filters(row.namespace, namespaces)
        ]
        if status is not None:
            rows = [row for row in rows if row.status == status]
        if source_id is not None:
            rows = [row for row in rows if row.source_id == source_id]
        rows.sort(key=lambda row: (row.created_at, row.conflict_id), reverse=True)
        return rows[: int(limit)] if limit is not None else rows

    def put_freshness_entry(self, entry):
        from sophiagraph.freshness import freshness_entry_to_dict

        self._freshness_entries[entry.ledger_id] = entry
        self._emit_change(
            object_type="freshness_entry",
            object_id=entry.ledger_id,
            payload=freshness_entry_to_dict(entry),
            namespace=entry.namespace,
            schema_identifiers={
                "node_label": "freshness_entry",
                "source_kind": entry.source_kind,
            },
        )
        return entry.ledger_id

    def get_freshness_entry(self, ledger_id):
        return self._freshness_entries.get(ledger_id)

    def list_freshness_entries(
        self,
        *,
        namespaces=None,
        source_kind=None,
        source_id=None,
        status=None,
        limit=None,
    ):
        from sophiagraph.storage.graph_helpers import namespace_matches_filters

        rows = [
            row
            for row in self._freshness_entries.values()
            if namespace_matches_filters(row.namespace, namespaces)
        ]
        if source_kind is not None:
            rows = [row for row in rows if row.source_kind == source_kind]
        if source_id is not None:
            rows = [row for row in rows if row.source_id == source_id]
        if status is not None:
            rows = [row for row in rows if row.status == status]
        rows.sort(key=lambda row: (row.updated_at, row.ledger_id), reverse=True)
        return rows[: int(limit)] if limit is not None else rows

    def put_source_entry(self, source):
        from sophiagraph.connectors import source_entry_to_dict

        self._source_entries[source.source_id] = source
        self._emit_change(
            object_type="source_registry",
            object_id=source.source_id,
            payload=source_entry_to_dict(source),
            namespace=source.namespace,
            schema_identifiers={
                "node_label": "source_registry",
                "source_type": source.source_type,
            },
        )
        return source.source_id

    def get_source_entry(self, source_id):
        return self._source_entries.get(source_id)

    def list_source_entries(
        self,
        *,
        namespaces=None,
        source_type=None,
        permission_scope=None,
        limit=None,
    ):
        from sophiagraph.storage.graph_helpers import namespace_matches_filters

        rows = [
            row
            for row in self._source_entries.values()
            if namespace_matches_filters(row.namespace, namespaces)
        ]
        if source_type is not None:
            rows = [row for row in rows if row.source_type == source_type]
        if permission_scope is not None:
            rows = [row for row in rows if row.permission_scope == permission_scope]
        rows.sort(key=lambda row: row.source_id)
        return rows[: int(limit)] if limit is not None else rows

    def put_source_ingest(self, envelope):
        from sophiagraph.connectors import source_ingest_to_dict

        self._source_ingests[envelope.ingest_id] = envelope
        self._emit_change(
            object_type="source_ingest",
            object_id=envelope.ingest_id,
            payload=source_ingest_to_dict(envelope),
            namespace=envelope.namespace,
            schema_identifiers={
                "node_label": "source_ingest",
                "payload_kind": envelope.payload_kind,
            },
        )
        return envelope.ingest_id

    def get_source_ingest(self, ingest_id):
        return self._source_ingests.get(ingest_id)

    def put_shared_block_attachment(self, attachment):
        from sophiagraph.shared_blocks import shared_attachment_to_dict

        self._shared_attachments[attachment.attachment_id] = attachment
        self._emit_change(
            object_type="shared_block_attachment",
            object_id=attachment.attachment_id,
            payload=shared_attachment_to_dict(attachment),
            namespace=attachment.namespace,
            schema_identifiers={"node_label": "shared_block_attachment"},
        )
        return attachment.attachment_id

    def list_shared_block_attachments(
        self,
        *,
        block_id=None,
        namespaces=None,
        attached_agent_id=None,
        status=None,
        limit=None,
    ):
        from sophiagraph.storage.graph_helpers import namespace_matches_filters

        rows = [
            row
            for row in self._shared_attachments.values()
            if namespace_matches_filters(row.namespace, namespaces)
        ]
        if block_id is not None:
            rows = [row for row in rows if row.block_id == block_id]
        if attached_agent_id is not None:
            rows = [row for row in rows if row.attached_agent_id == attached_agent_id]
        if status is not None:
            rows = [row for row in rows if row.status == status]
        rows.sort(key=lambda row: row.attachment_id)
        return rows[: int(limit)] if limit is not None else rows

    def put_shared_block_mirror(self, mirror):
        from sophiagraph.shared_blocks import shared_mirror_to_dict

        self._shared_mirrors[mirror.mirror_id] = mirror
        self._emit_change(
            object_type="shared_block_mirror",
            object_id=mirror.mirror_id,
            payload=shared_mirror_to_dict(mirror),
            namespace=mirror.mirror_namespace,
            schema_identifiers={"node_label": "shared_block_mirror"},
        )
        return mirror.mirror_id

    def get_shared_block_mirror(self, mirror_id):
        return self._shared_mirrors.get(mirror_id)

    def list_shared_block_mirrors(
        self,
        *,
        block_id=None,
        namespaces=None,
        status=None,
        limit=None,
    ):
        from sophiagraph.storage.graph_helpers import namespace_matches_filters

        rows = [
            row
            for row in self._shared_mirrors.values()
            if namespace_matches_filters(row.mirror_namespace, namespaces)
        ]
        if block_id is not None:
            rows = [row for row in rows if row.block_id == block_id]
        if status is not None:
            rows = [row for row in rows if row.status == status]
        rows.sort(key=lambda row: row.mirror_id)
        return rows[: int(limit)] if limit is not None else rows

    def put_shared_block_conflict(self, conflict):
        from sophiagraph.shared_blocks import shared_conflict_to_dict

        self._shared_conflicts[conflict.conflict_id] = conflict
        self._emit_change(
            object_type="shared_block_conflict",
            object_id=conflict.conflict_id,
            payload=shared_conflict_to_dict(conflict),
            namespace=conflict.namespace,
            schema_identifiers={"node_label": "shared_block_conflict"},
        )
        return conflict.conflict_id

    def list_shared_block_conflicts(
        self,
        *,
        block_id=None,
        namespaces=None,
        status=None,
        limit=None,
    ):
        from sophiagraph.storage.graph_helpers import namespace_matches_filters

        rows = [
            row
            for row in self._shared_conflicts.values()
            if namespace_matches_filters(row.namespace, namespaces)
        ]
        if block_id is not None:
            rows = [row for row in rows if row.block_id == block_id]
        if status is not None:
            rows = [row for row in rows if row.status == status]
        rows.sort(key=lambda row: row.created_at, reverse=True)
        return rows[: int(limit)] if limit is not None else rows

    def put_shared_block_usage_event(self, event):
        from sophiagraph.shared_blocks import shared_usage_to_dict

        self._shared_usage_events[event.event_id] = event
        self._emit_change(
            object_type="shared_block_usage",
            object_id=event.event_id,
            payload=shared_usage_to_dict(event),
            namespace=event.namespace,
            schema_identifiers={
                "node_label": "shared_block_usage",
                "action": event.action,
            },
        )
        return event.event_id

    def list_shared_block_usage_events(
        self,
        *,
        block_id=None,
        namespaces=None,
        action=None,
        limit=None,
    ):
        from sophiagraph.storage.graph_helpers import namespace_matches_filters

        rows = [
            row
            for row in self._shared_usage_events.values()
            if namespace_matches_filters(row.namespace, namespaces)
        ]
        if block_id is not None:
            rows = [row for row in rows if row.block_id == block_id]
        if action is not None:
            rows = [row for row in rows if row.action == action]
        rows.sort(key=lambda row: row.occurred_at, reverse=True)
        return rows[: int(limit)] if limit is not None else rows
