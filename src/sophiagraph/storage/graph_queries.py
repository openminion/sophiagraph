"""Store-neutral graph query builders."""

from __future__ import annotations

from collections.abc import Callable

from sophiagraph.models import MemoryRecord, StructuralLink
from sophiagraph.query import (
    GraphSnapshot,
    GraphSnapshotOptions,
    LinkQueryOptions,
    LocalGraphOptions,
)
from sophiagraph.storage.graph_helpers import (
    graph_edge_from_link,
    graph_node_from_record,
    namespace_matches_filters,
)


def build_local_graph(
    options: LocalGraphOptions,
    *,
    load_links: Callable[[LinkQueryOptions], list[StructuralLink]],
    load_record: Callable[[str], MemoryRecord | None],
    provenance: dict[str, str],
) -> GraphSnapshot:
    seen_nodes: set[str] = set()
    frontier: list[tuple[str, int]] = [(options.record_id, 0)]
    edges = []
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
        links = load_links(
            LinkQueryOptions(
                record_id=record_id,
                direction=options.direction,
                relation_types=options.relation_types,
                namespaces=options.namespaces,
            )
        )
        for link in links:
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
        record
        for record_id in sorted(seen_nodes)
        if (record := load_record(record_id)) is not None
        and namespace_matches_filters(record.effective_namespace, options.namespaces)
    ]
    return GraphSnapshot(
        nodes=[
            graph_node_from_record(
                record,
                degree_in=degree_in.get(record.id, 0),
                degree_out=degree_out.get(record.id, 0),
            )
            for record in records[: options.max_nodes]
        ],
        edges=edges,
        root_record_id=options.record_id,
        depth=options.depth,
        direction=options.direction,
        provenance=provenance,
    )


def build_graph_snapshot(
    records: list[MemoryRecord],
    links: list[StructuralLink],
    options: GraphSnapshotOptions,
    *,
    provenance: dict[str, str],
) -> GraphSnapshot:
    record_ids = {record.id for record in records}
    filtered_links = [
        link
        for link in links
        if link.source_record_id in record_ids
        and (link.target_record_id is None or link.target_record_id in record_ids)
        and namespace_matches_filters(link.namespace, options.namespaces)
    ]
    if options.relation_types:
        allowed = {str(item) for item in options.relation_types}
        filtered_links = [
            link for link in filtered_links if link.relation_type in allowed
        ]
    filtered_links = filtered_links[: options.max_edges]
    degree_in: dict[str, int] = {}
    degree_out: dict[str, int] = {}
    for link in filtered_links:
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
        edges=[graph_edge_from_link(link) for link in filtered_links],
        provenance=provenance,
    )


__all__ = ["build_graph_snapshot", "build_local_graph"]
