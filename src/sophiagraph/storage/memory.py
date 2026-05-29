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
from sophiagraph.integrity import populate_integrity_hash
from sophiagraph.models import (
    MemoryBlock,
    MemoryCandidate,
    MemoryEmbedding,
    KnowledgeDocumentBlock,
    MemoryNamespace,
    MemoryRecord,
    MemoryRelation,
    MemoryTierTransition,
    MemoryType,
    RelationDirection,
    SophiaGraphChangeEvent,
    StructuralLink,
    default_change_namespace,
)
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
from sophiagraph.storage.graph_queries import build_graph_snapshot, build_local_graph
from sophiagraph.storage.memory_portability import MemoryPortabilityMixin


class SophiaGraphMemoryStore(
    MemoryPortabilityMixin,
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
        self._changes: list[SophiaGraphChangeEvent] = []
        self._next_cursor = 1
        # Operator-config flag (default off = backward-compat). When
        # enabled, ``put_record`` stamps an integrity hash on every
        # record at write time via ``populate_integrity_hash``.
        self._integrity_hash_enabled = integrity_hash_enabled

    def _has_change(self, event: SophiaGraphChangeEvent) -> bool:
        return any(
            existing.event_id == event.event_id
            or (
                bool(event.idempotency_key)
                and existing.idempotency_key == event.idempotency_key
            )
            for existing in self._changes
        )

    def _append_change(self, event: SophiaGraphChangeEvent) -> None:
        if self._has_change(event):
            return
        self._changes.append(replace(event, cursor=self._next_cursor))
        self._next_cursor += 1

    def _emit_change(
        self,
        *,
        object_type: str,
        object_id: str,
        payload: dict[str, Any],
        namespace: MemoryNamespace,
        schema_identifiers: dict[str, str],
    ) -> None:
        self._append_change(
            SophiaGraphChangeEvent(
                event_id=f"chg-{uuid4()}",
                object_type=object_type,  # type: ignore[arg-type]
                object_id=object_id,
                operation="put",
                changed_at=utc_now_iso(),
                payload=payload,
                namespace=namespace,
                schema_identifiers=schema_identifiers,
            )
        )

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
        if not options.include_invalidated:
            records = [record for record in records if record.is_current_at()]
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

    def put_embedding(self, embedding: MemoryEmbedding) -> str:
        key = (embedding.record_id, embedding.vector_space)
        existing = self._embeddings.get(key)
        if existing is not None and existing.dimension != embedding.dimension:
            raise InvalidArgumentError("embedding dimension cannot change for key")
        self._embeddings[key] = embedding
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
        return self._embeddings.pop((record_id, vector_space), None) is not None

    def history(self, scope: str, type: MemoryType, key: str) -> list[MemoryRecord]:
        records = [
            record
            for record in self._records.values()
            if record.scope == scope and record.type == type and record.key == key
        ]
        records.sort(key=lambda record: record.updated_at, reverse=True)
        return records

    def record_count(self) -> int:
        return len(self._records)

    def candidate_count(self) -> int:
        return len(self._candidates)
