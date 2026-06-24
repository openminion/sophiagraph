"""GraphFakos adapter for Sophiagraph durable memory previews."""

from __future__ import annotations

from graphfakos import (
    GraphFakosCitation,
    GraphFakosEdge,
    GraphFakosGraph,
    GraphFakosNode,
    GraphFakosProvenance,
    GraphFakosProvider,
    GraphFakosRequest,
)

from sophiagraph.query import CandidateListOptions, LinkQueryOptions, ListQueryOptions


class SophiagraphViewerProvider(GraphFakosProvider):
    provider_id = "sophiagraph"
    provider_label = "Sophiagraph"
    graph_role = "memory"
    capabilities = (
        "search",
        "neighborhood",
        "path",
        "provenance",
        "timeline",
        "provider_status",
        "context_preview",
        "durable_memory",
        "static_export",
        "local_preview",
    )

    def __init__(self, *, store: object, scope: str, namespace: object) -> None:
        self._store = store
        self._scope = scope
        self._namespace = namespace

    def load_graph(self, request: GraphFakosRequest) -> GraphFakosGraph:
        records = tuple(
            self._store.list_records(
                ListQueryOptions(scopes=[self._scope], namespaces=[self._namespace])
            )
        )
        links = _record_links(self._store, records, self._namespace)
        candidates = tuple(
            self._store.list_candidates(
                CandidateListOptions(status=None, limit=max(request.limit, 25))
            )
        )
        blocks = {
            block.record_id: block
            for record in records
            for block in self._store.list_document_blocks(record_id=record.id)
        }
        provenance = tuple(_record_provenance(record) for record in records)
        citations = tuple(
            GraphFakosCitation(
                id=f"citation:{block.block_id}",
                label=block.anchor or block.block_id,
                path=block.document_id,
                excerpt=block.excerpt,
                provider_payload={"record_id": block.record_id},
            )
            for block in blocks.values()
        )
        nodes = tuple(
            _record_node(record, blocks.get(record.id)) for record in records
        ) + tuple(_candidate_node(candidate) for candidate in candidates)
        edges = tuple(_link_edge(link) for link in links) + tuple(
            _candidate_edge(candidate, records) for candidate in candidates
        )
        edges = tuple(edge for edge in edges if edge is not None)
        return GraphFakosGraph(
            graph_id=_graph_id(self._namespace),
            label="Sophiagraph Durable Memory",
            provider_id=self.provider_id,
            provider_label=self.provider_label,
            graph_role=self.graph_role,
            capabilities=self.capabilities,
            nodes=nodes,
            edges=edges,
            provenance=provenance,
            citations=citations,
            stats={
                "scope": self._scope,
                "records": len(records),
                "candidates": len(candidates),
                "links": len(links),
            },
            generated_at="2026-06-22T00:00:00+00:00",
            provider_payload={
                "integration_commands": (
                    "sophiagraph-ui --workspace <workspace-root> --screen explore --serve --open",
                    "python -m sophiagraph ui-preview --screen views --serve",
                )
            },
        )


def _graph_id(namespace: object) -> str:
    graph_id = getattr(namespace, "graph_id", None)
    agent_id = getattr(namespace, "agent_id", None)
    return ":".join(part for part in (agent_id, graph_id) if part) or "sophiagraph"


def _record_node(record: object, block: object | None) -> GraphFakosNode:
    meta = getattr(record, "meta", {}) or {}
    title = getattr(record, "title", None) or getattr(record, "id")
    content = getattr(record, "content", {}) or {}
    text = (
        content.get("text", str(content)) if isinstance(content, dict) else str(content)
    )
    tags = (
        "record",
        str(getattr(record, "type", "memory")),
        str(getattr(record, "tier", "stored")),
    )
    citation_ids = (f"citation:{block.block_id}",) if block else ()
    return GraphFakosNode(
        id=str(getattr(record, "id")),
        label=str(title),
        kind="memory_record",
        summary=text,
        tags=tags,
        confidence=getattr(record, "confidence", None),
        source=str(getattr(record, "source", "") or meta.get("document", "")),
        timestamps={
            "created_at": str(getattr(record, "created_at", "")),
            "updated_at": str(getattr(record, "updated_at", "")),
        },
        provenance_ids=(f"provenance:{getattr(record, 'id')}",),
        citation_ids=citation_ids,
        provider_payload={
            "key": getattr(record, "key", None),
            "scope": getattr(record, "scope", None),
            "claim_key": getattr(record, "claim_key", None),
            "source_class": getattr(record, "source_class", None),
            "polarity": getattr(record, "polarity", None),
        },
    )


def _record_links(
    store: object,
    records: tuple[object, ...],
    namespace: object,
) -> tuple[object, ...]:
    links_by_id: dict[str, object] = {}
    for record in records:
        for link in store.list_links(
            LinkQueryOptions(
                record_id=str(getattr(record, "id")),
                direction="both",
                namespaces=[namespace],
            )
        ):
            links_by_id[str(getattr(link, "link_id"))] = link
    return tuple(links_by_id.values())


def _candidate_node(candidate: object) -> GraphFakosNode:
    title = getattr(candidate, "title", None) or getattr(candidate, "candidate_id")
    content = getattr(candidate, "content", {}) or {}
    text = (
        content.get("text", str(content)) if isinstance(content, dict) else str(content)
    )
    return GraphFakosNode(
        id=f"candidate:{getattr(candidate, 'candidate_id')}",
        label=str(title),
        kind="memory_candidate",
        summary=text,
        tags=(
            "candidate",
            str(getattr(candidate, "status", "")),
            str(getattr(candidate, "type", "")),
        ),
        confidence=getattr(candidate, "confidence", None),
        source=str(getattr(candidate, "source", "")),
        timestamps={
            "created_at": str(getattr(candidate, "created_at", "")),
            "updated_at": str(getattr(candidate, "updated_at", "")),
        },
        provider_payload={
            "claim_key": getattr(candidate, "claim_key", None),
            "polarity": getattr(candidate, "polarity", None),
            "source_class": getattr(candidate, "source_class", None),
            "proposed_scope": getattr(candidate, "proposed_scope", None),
        },
    )


def _record_provenance(record: object) -> GraphFakosProvenance:
    record_id = getattr(record, "id")
    source = str(getattr(record, "source", "") or "sophiagraph")
    return GraphFakosProvenance(
        id=f"provenance:{record_id}",
        provider_id="sophiagraph",
        source_type="durable_memory",
        source_label=source,
        excerpt=str(getattr(record, "title", None) or record_id),
        created_at=str(getattr(record, "created_at", "")),
        updated_at=str(getattr(record, "updated_at", "")),
        confidence=getattr(record, "confidence", None),
    )


def _link_edge(link: object) -> GraphFakosEdge:
    return GraphFakosEdge(
        id=str(getattr(link, "link_id")),
        source_id=str(getattr(link, "source_record_id")),
        target_id=str(getattr(link, "target_record_id")),
        kind=str(
            getattr(link, "relation_type", None) or getattr(link, "link_kind", "")
        ),
        label=str(
            getattr(link, "relation_type", None) or getattr(link, "link_kind", "")
        ),
        confidence=1.0,
    )


def _candidate_edge(
    candidate: object,
    records: tuple[object, ...],
) -> GraphFakosEdge | None:
    if not records:
        return None
    return GraphFakosEdge(
        id=f"edge:candidate:{getattr(candidate, 'candidate_id')}",
        source_id=f"candidate:{getattr(candidate, 'candidate_id')}",
        target_id=str(getattr(records[0], "id")),
        kind="promote_candidate",
        label="promote candidate",
        confidence=getattr(candidate, "confidence", None),
    )


__all__ = [
    "SophiagraphViewerProvider",
]
