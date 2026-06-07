"""Deterministic HTML renderers for package-local SophiaGraph UI packets."""

from __future__ import annotations

from html import escape
from typing import Any

from .screens import (
    CommunityStructureScreen,
    GraphViewScreen,
    KnowledgeExplorerScreen,
    OperationsConsoleScreen,
    RecordDetailScreen,
    RepairCenterScreen,
    SchemaDeveloperScreen,
    TimelineScreen,
)


def _section(title: str, body: str) -> str:
    return (
        f"<section><h2>{escape(title)}</h2>{body}</section>"
        if body
        else f"<section><h2>{escape(title)}</h2><p>None</p></section>"
    )


def _list(items: list[str]) -> str:
    if not items:
        return "<p>None</p>"
    return "<ul>" + "".join(f"<li>{escape(item)}</li>" for item in items) + "</ul>"


def _follow_up_action_items(screen: OperationsConsoleScreen) -> list[str]:
    items: list[str] = []
    for action in screen.report.follow_up_actions:
        item = action.action
        if action.source_id:
            item += f" source={action.source_id}"
        if action.conflict_id:
            item += f" conflict={action.conflict_id}"
        if action.finding_id:
            item += f" finding={action.finding_id}"
        if action.candidate_id:
            item += f" candidate={action.candidate_id}"
        items.append(item)
    return items


def _record_field_items(screen: RecordDetailScreen) -> list[str]:
    record = screen.packet.record
    items = [
        f"id={record.id}",
        f"type={record.type}",
        f"source={record.source}",
        f"tier={record.tier}",
        f"created_at={record.created_at}",
        f"updated_at={record.updated_at}",
        f"is_deleted={record.is_deleted}",
        f"access_count={record.access_count}",
    ]
    optional_pairs = (
        ("title", record.title),
        ("key", record.key),
        ("event_time", record.event_time),
        ("valid_to", record.valid_to),
        ("expires_at", record.expires_at),
        ("last_hit_at", record.last_hit_at),
        ("deleted_at", record.deleted_at),
        ("deleted_reason", record.deleted_reason),
        ("supersedes_id", record.supersedes_id),
        ("superseded_by_id", record.superseded_by_id),
        ("integrity_hash", record.integrity_hash),
    )
    for key, value in optional_pairs:
        if value:
            items.append(f"{key}={value}")
    return items


def _record_meta_items(screen: RecordDetailScreen) -> list[str]:
    meta = screen.packet.record.meta
    items: list[str] = []
    for key in ("document", "properties", "provenance"):
        if key in meta:
            items.append(f"{key}={meta[key]}")
    return items


def render_explorer_html(screen: KnowledgeExplorerScreen) -> str:
    hits = _list(
        [
            f"{hit.record_id} ({hit.record_type}) [{', '.join(hit.matched_fields)}]"
            for hit in screen.result.hits
        ]
    )
    facets = _list(
        [
            f"{facet.field}={facet.value} ({facet.count})"
            for facet in screen.result.facets
        ]
    )
    navigation = _list(
        [action.label or action.action for action in screen.result.navigation]
    )
    return (
        "<main data-screen='explore'>"
        f"<h1>Knowledge Explorer</h1>{_section('Hits', hits)}"
        f"{_section('Facets', facets)}"
        f"{_section('Backlinks', _list([link.link_id for link in screen.result.backlinks]))}"
        f"{_section('Outgoing Links', _list([link.link_id for link in screen.result.outgoing_links]))}"
        f"{_section('Path Evidence', _list([' -> '.join(path.record_ids) for path in screen.result.paths]))}"
        f"{_section('Navigation Actions', navigation)}</main>"
    )


def render_record_detail_html(screen: RecordDetailScreen) -> str:
    packet = screen.packet
    namespace_items = [
        f"{key}={value}"
        for key, value in packet.record.effective_namespace.as_dict().items()
    ]
    return (
        "<main data-screen='record_detail'>"
        f"<h1>{escape(packet.record.title or packet.record.id)}</h1>"
        f"{_section('Stored Fields', _list(_record_field_items(screen)))}"
        f"{_section('Namespace', _list(namespace_items))}"
        f"{_section('Metadata', _list(_record_meta_items(screen)))}"
        f"{_section('Relations', _list([relation.relation_id for relation in packet.relations]))}"
        f"{_section('Backlinks', _list([link.link_id for link in packet.backlinks]))}"
        f"{_section('Outgoing Links', _list([link.link_id for link in packet.outgoing_links]))}"
        f"{_section('Blocks', _list([block.block_id for block in packet.document_blocks]))}"
        f"{_section('Graph Nodes', _list([node.record_id for node in (packet.graph.nodes if packet.graph else [])]))}"
        "</main>"
    )


def render_graph_view_html(screen: GraphViewScreen) -> str:
    return (
        "<main data-screen='graph'>"
        f"<h1>Graph View</h1>"
        f"{_section('Nodes', _list([node.record_id for node in screen.snapshot.nodes]))}"
        f"{_section('Edges', _list([edge.edge_id for edge in screen.snapshot.edges]))}"
        f"{_section('Highlighted Path', _list([' -> '.join(screen.highlighted_path.record_ids)] if screen.highlighted_path else []))}"
        f"{_section('Shared Neighbors', _list(screen.shared_neighbors.neighbor_record_ids if screen.shared_neighbors else []))}"
        f"{_section('Communities', _list([community.community_id for community in screen.communities]))}"
        "</main>"
    )


def render_operations_console_html(screen: OperationsConsoleScreen) -> str:
    return (
        "<main data-screen='operations'>"
        f"<h1>Operations Console</h1>"
        f"{_section('Run', _list([screen.report.run_id, screen.report.kind, screen.report.status]))}"
        f"{_section('Counts', _list([f'{key}={value}' for key, value in sorted(screen.report.counts.items())]))}"
        f"{_section('Follow Up', _list(_follow_up_action_items(screen)))}"
        "</main>"
    )


def render_repair_center_html(screen: RepairCenterScreen) -> str:
    return (
        "<main data-screen='repair'>"
        f"<h1>Repair Center</h1>"
        f"{_section('Findings', _list([finding.finding_id for finding in screen.report.findings]))}"
        f"{_section('Repair Candidates', _list([candidate.candidate_id for candidate in screen.repair_candidates]))}"
        "</main>"
    )


def render_community_structure_html(screen: CommunityStructureScreen) -> str:
    return (
        "<main data-screen='community'>"
        f"<h1>Community Structure</h1>"
        f"{_section('Communities', _list([community.community_id for community in screen.result.communities]))}"
        f"{_section('Hits', _list([hit.community_id for hit in screen.result.hits]))}"
        f"{_section('Omitted', _list([item.reason for item in screen.result.omitted]))}"
        "</main>"
    )


def render_timeline_html(screen: TimelineScreen) -> str:
    return (
        "<main data-screen='timeline'>"
        f"<h1>Timeline</h1>"
        f"{_section('Records', _list([record.id for record in screen.records]))}"
        f"{_section('Deleted', _list([record.id for record in screen.records if record.is_deleted]))}"
        "</main>"
    )


def render_schema_developer_html(screen: SchemaDeveloperScreen) -> str:
    return (
        "<main data-screen='schema'>"
        f"<h1>Schema And Developer Panel</h1>"
        f"{_section('Node Labels', _list(screen.schema.node_labels))}"
        f"{_section('Relation Types', _list(screen.schema.relation_types))}"
        f"{_section('Namespace Dimensions', _list(screen.schema.namespace_dimensions))}"
        f"{_section('Request Payload', _list([str(screen.last_request_payload or {})]))}"
        f"{_section('Response Payload', _list([str(screen.last_response_payload or {})]))}"
        "</main>"
    )


def render_screen_html(screen: Any) -> str:
    if isinstance(screen, KnowledgeExplorerScreen):
        return render_explorer_html(screen)
    if isinstance(screen, RecordDetailScreen):
        return render_record_detail_html(screen)
    if isinstance(screen, GraphViewScreen):
        return render_graph_view_html(screen)
    if isinstance(screen, OperationsConsoleScreen):
        return render_operations_console_html(screen)
    if isinstance(screen, RepairCenterScreen):
        return render_repair_center_html(screen)
    if isinstance(screen, CommunityStructureScreen):
        return render_community_structure_html(screen)
    if isinstance(screen, TimelineScreen):
        return render_timeline_html(screen)
    if isinstance(screen, SchemaDeveloperScreen):
        return render_schema_developer_html(screen)
    raise TypeError(f"unsupported screen type: {type(screen)!r}")


__all__ = [
    "render_community_structure_html",
    "render_explorer_html",
    "render_graph_view_html",
    "render_operations_console_html",
    "render_record_detail_html",
    "render_repair_center_html",
    "render_schema_developer_html",
    "render_screen_html",
    "render_timeline_html",
]
