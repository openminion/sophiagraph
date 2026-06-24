"""Private mechanics for structural explorer packets."""

from __future__ import annotations

from collections import Counter
from time import perf_counter
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from sophiagraph.models import MemoryRecord, StructuralLink
from sophiagraph.query.algorithms import GraphCommonNeighbors, GraphPath
from sophiagraph.query.community import GraphCommunity
from sophiagraph.query.graph import (
    GraphSnapshot,
    GraphSnapshotOptions,
    LinkQueryOptions,
)
from sophiagraph.query.options import ListQueryOptions, SearchQueryOptions

from .explorer_types import (
    FacetField,
    KnowledgeContextExcerpt,
    KnowledgeExplorerFilters,
    KnowledgeExplorerRequest,
    KnowledgeExplorerStore,
    KnowledgeFacet,
    KnowledgeHit,
    KnowledgeNavigationAction,
    KnowledgeQueryPlanStage,
    MentionMatchKind,
    QueryPlanStageName,
    UnlinkedMentionCandidate,
)


def load_records(
    store: KnowledgeExplorerStore,
    request: KnowledgeExplorerRequest,
) -> list[MemoryRecord]:
    common = {
        "scopes": request.scopes,
        "types": request.filters.types,
        "tiers": request.filters.tiers,
        "include_invalidated": bool(
            request.as_of
            or request.valid_at
            or request.effective_during
            or request.believed_at
        ),
        "limit": None,
        "namespaces": request.namespaces,
        "as_of": request.as_of,
        "valid_at": request.valid_at,
        "effective_during": request.effective_during,
        "believed_at": request.believed_at,
    }
    if request.query and request.query.strip():
        return store.search_records(SearchQueryOptions(query=request.query, **common))
    return store.list_records(ListQueryOptions(**common))


def filter_records(
    records: list[MemoryRecord],
    filters: KnowledgeExplorerFilters,
) -> list[MemoryRecord]:
    filtered = list(records)
    if filters.sources:
        allowed = set(filters.sources)
        filtered = [record for record in filtered if record.source in allowed]
    if filters.tags:
        allowed_tags = {tag.lower().lstrip("#") for tag in filters.tags}
        filtered = [
            record
            for record in filtered
            if allowed_tags.intersection(
                {tag.lower().lstrip("#") for tag in record.tags}
            )
        ]
    if filters.properties:
        filtered = [
            record
            for record in filtered
            if record_has_properties(record, filters.properties)
        ]
    return filtered


def filter_orphans(
    store: KnowledgeExplorerStore,
    records: list[MemoryRecord],
    request: KnowledgeExplorerRequest,
) -> list[MemoryRecord]:
    if request.filters.include_orphans:
        return records
    snapshot = store.get_graph_snapshot(
        GraphSnapshotOptions(
            scopes=request.scopes,
            namespaces=request.namespaces,
            include_orphans=True,
            max_nodes=max(len(records), 1),
        )
    )
    connected = {node.record_id for node in snapshot.nodes if not node.orphan}
    return [record for record in records if record.id in connected]


def record_has_properties(record: MemoryRecord, expected: dict[str, Any]) -> bool:
    properties = record_properties(record)
    for key, value in expected.items():
        if properties.get(key) != value:
            return False
    return True


def filter_links(
    links: list[StructuralLink],
    filters: KnowledgeExplorerFilters,
) -> list[StructuralLink]:
    if not filters.link_kinds:
        return links
    allowed = set(filters.link_kinds)
    return [link for link in links if link.link_kind in allowed]


def hit_for_record(
    record: MemoryRecord,
    query: str,
    context_chars: int,
) -> KnowledgeHit:
    matched = matched_fields(record, query)
    score = 1.0 + (0.25 * len(matched))
    return KnowledgeHit(
        record_id=record.id,
        title=record.title,
        record_type=record.type,
        score=score,
        matched_fields=matched,
        score_components={"keyword": score},
        context=record_excerpt(record, context_chars),
    )


def matched_fields(record: MemoryRecord, query: str) -> list[str]:
    if not query:
        return []
    needle = query.lower()
    fields: list[str] = []
    if record.title and needle in record.title.lower():
        fields.append("title")
    if record.key and needle in record.key.lower():
        fields.append("key")
    if any(needle in tag.lower() for tag in record.tags):
        fields.append("tags")
    if needle in content_text(record).lower():
        fields.append("content")
    if needle in str(record.meta).lower():
        fields.append("meta")
    return fields


def record_excerpt(record: MemoryRecord, context_chars: int) -> KnowledgeContextExcerpt:
    text = content_text(record).strip().replace("\n", " ")
    bounded = text[:context_chars] if context_chars else ""
    return KnowledgeContextExcerpt(
        record_id=record.id,
        text=bounded,
        source_path=document_path(record),
        char_budget=context_chars,
    )


def content_text(record: MemoryRecord) -> str:
    if isinstance(record.content, str):
        return record.content
    text = record.content.get("text")
    if isinstance(text, str):
        return text
    return str(record.content)


def record_properties(record: MemoryRecord) -> dict[str, Any]:
    properties: dict[str, Any] = {
        "scope": record.scope,
        "type": record.type,
        "tier": record.tier,
        "source": record.source,
        "key": record.key,
        "title": record.title,
    }
    document = record.meta.get("document")
    if isinstance(document, dict):
        properties.update(document)
    extra = record.meta.get("properties")
    if isinstance(extra, dict):
        properties.update(extra)
    return properties


def document_path(record: MemoryRecord) -> str | None:
    document = record.meta.get("document")
    if isinstance(document, dict) and isinstance(document.get("path"), str):
        return document["path"]
    return None


def facets(
    records: list[MemoryRecord],
    graph: GraphSnapshot | None,
    links: list[StructuralLink],
    *,
    communities: list[GraphCommunity],
) -> list[KnowledgeFacet]:
    counters: dict[FacetField, Counter[str]] = {
        "scope": Counter(),
        "type": Counter(),
        "tier": Counter(),
        "source": Counter(),
        "tag": Counter(),
        "community": Counter(),
        "orphan": Counter(),
        "relation_type": Counter(),
        "link_kind": Counter(),
    }
    for record in records:
        counters["scope"][record.scope] += 1
        counters["type"][record.type] += 1
        counters["tier"][record.tier] += 1
        counters["source"][record.source] += 1
        for tag in record.tags:
            counters["tag"][tag] += 1
    if graph is not None:
        for node in graph.nodes:
            counters["orphan"][str(bool(node.orphan)).lower()] += 1
    for community in communities:
        counters["community"][community.community_id] += len(community.record_ids)
    for link in links:
        counters["link_kind"][link.link_kind] += 1
        if link.relation_type:
            counters["relation_type"][link.relation_type] += 1
    result: list[KnowledgeFacet] = []
    for field_name, counter in counters.items():
        for value, count in sorted(counter.items()):
            result.append(KnowledgeFacet(field=field_name, value=value, count=count))
    return result


def unlinked_mentions(
    store: KnowledgeExplorerStore,
    records: list[MemoryRecord],
    request: KnowledgeExplorerRequest,
) -> list[UnlinkedMentionCandidate]:
    mentions: list[UnlinkedMentionCandidate] = []
    candidates = mention_targets(store, records)
    for source in records:
        text = content_text(source)
        if not text:
            continue
        linked_targets = {
            link.target_record_id
            for link in store.list_links(
                LinkQueryOptions(
                    record_id=source.id,
                    direction="out",
                    namespaces=request.namespaces,
                    context_chars=request.context_chars,
                )
            )
            if link.target_record_id
        }
        lowered = text.lower()
        for target_id, match_text, kind in candidates:
            if target_id == source.id or target_id in linked_targets:
                continue
            if len(match_text.strip()) < 3:
                continue
            index = lowered.find(match_text.lower())
            if index < 0:
                continue
            context = bounded_text(text, index, len(match_text), request.context_chars)
            candidate_id = stable_id("mention", source.id, target_id, kind, match_text)
            mentions.append(
                UnlinkedMentionCandidate(
                    candidate_id=candidate_id,
                    source_record_id=source.id,
                    target_record_id=target_id,
                    matched_text=match_text,
                    match_kind=kind,
                    context=KnowledgeContextExcerpt(
                        record_id=source.id,
                        text=context,
                        source_path=document_path(source),
                        char_budget=request.context_chars,
                    ),
                )
            )
            if len(mentions) >= request.limit:
                return mentions
    return mentions


def mention_targets(
    store: KnowledgeExplorerStore,
    records: list[MemoryRecord],
) -> list[tuple[str, str, MentionMatchKind]]:
    targets: list[tuple[str, str, MentionMatchKind]] = []
    for record in records:
        if record.title:
            targets.append((record.id, record.title, "title"))
        aliases = record.meta.get("aliases")
        if isinstance(aliases, list):
            targets.extend((record.id, str(alias), "alias") for alias in aliases)
        path = document_path(record)
        if path:
            targets.append((record.id, path, "path"))
        try:
            blocks = store.list_document_blocks(record_id=record.id)
        except Exception:  # allow-bare-raise: optional store method guard
            blocks = []
        for block in blocks:
            if block.block_type == "heading":
                targets.append((record.id, block.anchor, "heading"))
            targets.append((record.id, block.block_id, "block_id"))
    return targets


def bounded_text(text: str, index: int, length: int, budget: int) -> str:
    if budget <= 0:
        return ""
    half = max(0, (budget - length) // 2)
    start = max(0, index - half)
    end = min(len(text), index + length + half)
    return text[start:end].replace("\n", " ")


def navigation(
    *,
    root_record_id: str | None,
    hits: list[KnowledgeHit],
    backlinks: list[StructuralLink],
    outgoing_links: list[StructuralLink],
    paths: list[GraphPath],
    common: list[GraphCommonNeighbors],
    graph: GraphSnapshot | None,
    communities: list[GraphCommunity],
    mentions: list[UnlinkedMentionCandidate],
) -> list[KnowledgeNavigationAction]:
    actions: list[KnowledgeNavigationAction] = []
    if root_record_id:
        actions.append(
            KnowledgeNavigationAction(
                action="open_root",
                record_id=root_record_id,
                label="Open root",
            )
        )
    for hit in hits:
        actions.append(
            KnowledgeNavigationAction(
                action="open_hit",
                record_id=hit.record_id,
                label=hit.title or hit.record_id,
            )
        )
    for link in backlinks:
        actions.append(
            KnowledgeNavigationAction(
                action="follow_backlink",
                record_id=link.source_record_id,
                link_id=link.link_id,
                label=link.display_text or link.raw_target,
            )
        )
    for link in outgoing_links:
        if link.target_record_id:
            actions.append(
                KnowledgeNavigationAction(
                    action="follow_outgoing_link",
                    record_id=link.target_record_id,
                    link_id=link.link_id,
                    label=link.display_text or link.raw_target,
                )
            )
    for path in paths:
        actions.append(
            KnowledgeNavigationAction(
                action="inspect_path",
                path=path,
                label=f"{path.hop_count} hop path",
            )
        )
    for neighbors in common:
        for record_id in neighbors.neighbor_record_ids:
            actions.append(
                KnowledgeNavigationAction(
                    action="open_common_neighbor",
                    record_id=record_id,
                    label="Open common neighbor",
                )
            )
    if graph is not None:
        for node in graph.nodes:
            if node.orphan:
                actions.append(
                    KnowledgeNavigationAction(
                        action="open_orphan",
                        record_id=node.record_id,
                        label=node.title or node.record_id,
                    )
                )
    for community in communities:
        actions.append(
            KnowledgeNavigationAction(
                action="open_community",
                record_id=community.seed_record_id or community.record_ids[0],
                label=f"Open community ({len(community.record_ids)})",
            )
        )
        actions.append(
            KnowledgeNavigationAction(
                action="filter_community",
                record_id=community.seed_record_id or community.record_ids[0],
                label=f"Filter community ({len(community.record_ids)})",
            )
        )
    for mention in mentions:
        actions.append(
            KnowledgeNavigationAction(
                action="apply_repair_candidate",
                candidate_id=mention.candidate_id,
                label=f"Review mention: {mention.matched_text}",
            )
        )
    return actions


def stage(
    stage_name: QueryPlanStageName,
    input_count: int,
    output_count: int,
    started: float,
    details: dict[str, Any],
) -> KnowledgeQueryPlanStage:
    return KnowledgeQueryPlanStage(
        stage=stage_name,
        input_count=input_count,
        output_count=output_count,
        elapsed_ms=round((perf_counter() - started) * 1000, 3),
        details=details,
    )


def filter_details(filters: KnowledgeExplorerFilters) -> dict[str, Any]:
    return {
        "types": list(filters.types or []),
        "tiers": list(filters.tiers or []),
        "sources": list(filters.sources or []),
        "tags": list(filters.tags or []),
        "properties": dict(filters.properties),
        "relation_types": list(filters.relation_types or []),
        "link_kinds": list(filters.link_kinds or []),
        "include_orphans": filters.include_orphans,
    }


def stable_id(prefix: str, *parts: str) -> str:
    return f"{prefix}-{uuid5(NAMESPACE_URL, ':'.join(str(part) for part in parts))}"
