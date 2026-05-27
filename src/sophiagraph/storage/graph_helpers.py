"""Shared structural-link and graph helpers for package stores."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from sophiagraph.models import (
    KnowledgeDocumentBlock,
    MemoryBlock,
    MemoryNamespace,
    MemoryRecord,
    StructuralLink,
)
from sophiagraph.query import GraphEdge, GraphNode, StructuralSearchQuery


def namespace_matches_filters(
    namespace: MemoryNamespace,
    filters: list[MemoryNamespace] | None,
) -> bool:
    if not filters:
        return True
    return any(namespace.matches(item) for item in filters)


def link_to_dict(link: StructuralLink) -> dict[str, Any]:
    return asdict(link)


def link_from_dict(data: dict[str, Any]) -> StructuralLink:
    payload = dict(data)
    raw_namespace = payload.get("namespace")
    if isinstance(raw_namespace, dict):
        payload["namespace"] = MemoryNamespace.from_dict(raw_namespace)
    return StructuralLink(**payload)


def block_to_dict(block: KnowledgeDocumentBlock) -> dict[str, Any]:
    return asdict(block)


def block_from_dict(data: dict[str, Any]) -> KnowledgeDocumentBlock:
    return KnowledgeDocumentBlock(**dict(data))


def memory_block_to_dict(block: MemoryBlock) -> dict[str, Any]:
    """Serialize a ``MemoryBlock`` to a portable dict."""
    payload = asdict(block)
    namespace = payload.get("owner_namespace")
    if isinstance(namespace, MemoryNamespace):
        payload["owner_namespace"] = namespace.as_dict()
    if isinstance(block.provenance, dict):
        payload["provenance"] = dict(block.provenance)
    else:
        payload["provenance"] = dict(block.provenance)
    return payload


def memory_block_from_dict(data: dict[str, Any]) -> MemoryBlock:
    """Hydrate a ``MemoryBlock`` from a portable dict."""
    payload = dict(data)
    raw_namespace = payload.get("owner_namespace")
    if isinstance(raw_namespace, dict):
        payload["owner_namespace"] = MemoryNamespace.from_dict(raw_namespace)
    return MemoryBlock(**payload)


def graph_node_from_record(
    record: MemoryRecord,
    *,
    degree_in: int = 0,
    degree_out: int = 0,
) -> GraphNode:
    document = record.meta.get("document")
    properties = record.meta.get("properties")
    document_meta = document if isinstance(document, dict) else {}
    property_meta = properties if isinstance(properties, dict) else {}
    return GraphNode(
        record_id=record.id,
        title=record.title,
        path=document_meta.get("path"),
        tags=list(record.tags),
        properties=dict(property_meta),
        degree_in=degree_in,
        degree_out=degree_out,
        orphan=(degree_in + degree_out) == 0,
        namespace=record.effective_namespace,
        provenance={"scope": record.scope},
    )


def graph_edge_from_link(link: StructuralLink, *, direction: str = "out") -> GraphEdge:
    return GraphEdge(
        edge_id=link.link_id,
        source_record_id=link.source_record_id,
        target_record_id=link.target_record_id,
        relation_type=link.relation_type,
        direction=direction,
        unresolved_target=None if link.target_record_id else link.raw_target,
        label=link.display_text,
        provenance={
            "link_kind": link.link_kind,
            "resolution_status": link.resolution_status,
            "source_path": link.source_path,
        },
    )


def record_matches_structural_query(
    record: MemoryRecord,
    query: StructuralSearchQuery,
    *,
    outgoing_targets: list[str] | None = None,
    incoming_sources: list[str] | None = None,
    blocks: list[KnowledgeDocumentBlock] | None = None,
) -> bool:
    if query.namespaces and not namespace_matches_filters(
        record.effective_namespace, query.namespaces
    ):
        return False
    document = record.meta.get("document")
    properties = record.meta.get("properties")
    document_meta = document if isinstance(document, dict) else {}
    property_meta = properties if isinstance(properties, dict) else {}
    haystack = " ".join(
        str(part)
        for part in [
            record.title,
            record.key,
            record.content,
            document_meta.get("path"),
            property_meta,
        ]
    ).lower()
    for phrase in query.exact_phrases:
        if phrase.lower() not in haystack:
            return False
    for term in query.text_terms:
        if term.lower() not in haystack:
            return False
    record_tags = {tag.lower().lstrip("#") for tag in record.tags}
    property_tags = property_meta.get("tags")
    if isinstance(property_tags, list):
        record_tags.update(str(tag).lower().lstrip("#") for tag in property_tags)
    for tag in query.tags:
        if tag.lower().lstrip("#") not in record_tags:
            return False
    for key, value in query.properties.items():
        if str(property_meta.get(key)) != value:
            return False
    path = str(document_meta.get("path") or "")
    if query.path and query.path.lower() not in path.lower():
        return False
    if query.file and query.file.lower() != path.rsplit("/", 1)[-1].lower():
        return False
    if query.content and query.content.lower() not in str(record.content).lower():
        return False
    if query.link_to and query.link_to not in set(outgoing_targets or []):
        return False
    if query.linked_from and query.linked_from not in set(incoming_sources or []):
        return False
    if query.block and query.block not in {block.block_id for block in blocks or []}:
        return False
    if query.section and query.section not in {block.anchor for block in blocks or []}:
        return False
    if query.task:
        task = query.task.lower()
        if not any(
            block.excerpt and task in block.excerpt.lower() for block in blocks or []
        ):
            return False
    return True


__all__ = [
    "graph_edge_from_link",
    "graph_node_from_record",
    "block_from_dict",
    "block_to_dict",
    "link_from_dict",
    "link_to_dict",
    "memory_block_from_dict",
    "memory_block_to_dict",
    "namespace_matches_filters",
    "record_matches_structural_query",
]
