"""In-memory standalone durable engine for the reusable ``sophiagraph`` package."""

from __future__ import annotations

from dataclasses import replace
from typing import Any
from uuid import uuid4

from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.contracts.types import MEMORY_CONTRACT_VERSION
from sophiagraph.models import (
    MemoryCandidate,
    MemoryNamespace,
    MemoryRecord,
    MemoryRelation,
    MemoryTierTransition,
    MemoryType,
    RelationDirection,
    StructuralLink,
)
from sophiagraph.portability.models import (
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
    RecordOrder,
    SearchQueryOptions,
    StructuralSearchQuery,
)
from sophiagraph.portability.codec import build_manifest, record_from_dict
from sophiagraph.storage.base import SophiaGraphStore
from sophiagraph.storage.helpers import (
    record_matches_namespaces,
    record_matches_query,
    utc_now_iso,
)
from sophiagraph.storage.graph_helpers import (
    graph_edge_from_link,
    graph_node_from_record,
    namespace_matches_filters,
    record_matches_structural_query,
)


class SophiaGraphMemoryStore(SophiaGraphStore):
    """In-memory implementation of the storage contract."""

    contract_version = MEMORY_CONTRACT_VERSION

    def __init__(self) -> None:
        self._records: dict[str, MemoryRecord] = {}
        self._relations: dict[str, MemoryRelation] = {}
        self._links: dict[str, StructuralLink] = {}
        self._candidates: dict[str, MemoryCandidate] = {}
        self._transitions: dict[str, MemoryTierTransition] = {}

    def put_record(self, record: MemoryRecord) -> str:
        self._records[record.id] = record
        return record.id

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

    def invalidate_record(
        self, record_id: str, *, valid_to: str, reason: str
    ) -> MemoryRecord:
        record = self.get_record(record_id)
        if record is None:
            raise InvalidArgumentError(f"unknown record_id: {record_id}")
        updated = replace(
            record,
            valid_to=str(valid_to),
            supersession_reason=str(reason or record.supersession_reason or ""),
            updated_at=utc_now_iso(),
        )
        self.put_record(updated)
        return updated

    def supersede_record(
        self, old_record_id: str, new_record_id: str, reason: str = ""
    ) -> MemoryRecord:
        record = self.get_record(old_record_id)
        if record is None:
            raise InvalidArgumentError(f"unknown record_id: {old_record_id}")
        new_record = self.get_record(new_record_id)
        valid_to = new_record.created_at if new_record is not None else utc_now_iso()
        updated = replace(
            record,
            valid_to=valid_to,
            superseded_by_id=new_record_id,
            supersession_reason=str(reason or "superseded"),
            updated_at=utc_now_iso(),
        )
        self.put_record(updated)
        return updated

    def put_relation(self, relation: MemoryRelation) -> str:
        self._relations[relation.relation_id] = relation
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
        return link.link_id

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
        seen_nodes: set[str] = set()
        frontier: list[tuple[str, int]] = [(options.record_id, 0)]
        edges: list[Any] = []
        edge_ids: set[str] = set()
        degree_in: dict[str, int] = {}
        degree_out: dict[str, int] = {}
        while frontier and len(seen_nodes) < options.max_nodes:
            record_id, depth = frontier.pop(0)
            if record_id in seen_nodes:
                continue
            seen_nodes.add(record_id)
            if depth >= options.depth:
                continue
            for link in self.list_links(
                LinkQueryOptions(
                    record_id=record_id,
                    direction=options.direction,
                    relation_types=options.relation_types,
                    namespaces=options.namespaces,
                    limit=None,
                )
            ):
                if link.link_id not in edge_ids and len(edges) < options.max_edges:
                    edges.append(graph_edge_from_link(link))
                    edge_ids.add(link.link_id)
                if link.target_record_id:
                    degree_out[link.source_record_id] = (
                        degree_out.get(link.source_record_id, 0) + 1
                    )
                    degree_in[link.target_record_id] = (
                        degree_in.get(link.target_record_id, 0) + 1
                    )
                next_id = (
                    link.target_record_id
                    if link.source_record_id == record_id
                    else link.source_record_id
                )
                if next_id and next_id not in seen_nodes:
                    frontier.append((next_id, depth + 1))
        records = [
            self._records[record_id]
            for record_id in sorted(seen_nodes)
            if record_id in self._records
            and namespace_matches_filters(
                self._records[record_id].effective_namespace, options.namespaces
            )
        ]
        nodes = [
            graph_node_from_record(
                record,
                degree_in=degree_in.get(record.id, 0),
                degree_out=degree_out.get(record.id, 0),
            )
            for record in records[: options.max_nodes]
        ]
        return GraphSnapshot(
            nodes=nodes,
            edges=edges,
            root_record_id=options.record_id,
            depth=options.depth,
            direction=options.direction,
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
        record_ids = {record.id for record in records}
        links = [
            link
            for link in self._links.values()
            if link.source_record_id in record_ids
            and (link.target_record_id is None or link.target_record_id in record_ids)
            and namespace_matches_filters(link.namespace, options.namespaces)
        ]
        if options.relation_types:
            allowed = {str(item) for item in options.relation_types}
            links = [link for link in links if link.relation_type in allowed]
        links = links[: options.max_edges]
        degree_in: dict[str, int] = {}
        degree_out: dict[str, int] = {}
        for link in links:
            if link.target_record_id:
                degree_out[link.source_record_id] = (
                    degree_out.get(link.source_record_id, 0) + 1
                )
                degree_in[link.target_record_id] = (
                    degree_in.get(link.target_record_id, 0) + 1
                )
        nodes = [
            graph_node_from_record(
                record,
                degree_in=degree_in.get(record.id, 0),
                degree_out=degree_out.get(record.id, 0),
            )
            for record in records
            if options.include_orphans
            or degree_in.get(record.id, 0)
            or degree_out.get(record.id, 0)
        ]
        return GraphSnapshot(
            nodes=nodes,
            edges=[graph_edge_from_link(link) for link in links],
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
            )
        ]
        if query.sort == "title":
            matches.sort(key=lambda record: record.title or "")
        if query.limit is not None:
            matches = matches[: int(query.limit)]
        return matches

    def put_candidate(self, candidate: MemoryCandidate) -> str:
        self._candidates[candidate.candidate_id] = candidate
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
        return transition.transition_id

    def history(self, scope: str, type: MemoryType, key: str) -> list[MemoryRecord]:
        records = [
            record
            for record in self._records.values()
            if record.scope == scope and record.type == type and record.key == key
        ]
        records.sort(key=lambda record: record.updated_at, reverse=True)
        return records

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
        transitions: list[MemoryTierTransition] = []
        if options.include_tier_history:
            transitions = self.list_tier_transitions(
                scopes=options.scopes, limit=options.limit
            )
        snapshot = MemoryBundleSnapshot(
            manifest={},
            records=records,
            candidates=candidates,
            relations=relations,
            tier_transitions=transitions,
            provenance_traces=[],
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

    def record_count(self) -> int:
        return len(self._records)

    def candidate_count(self) -> int:
        return len(self._candidates)
