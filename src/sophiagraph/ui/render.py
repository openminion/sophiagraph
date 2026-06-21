"""Deterministic HTML renderers for package-local SophiaGraph UI packets."""

from __future__ import annotations

from html import escape
from math import cos, pi, sin
from typing import Any

from sophiagraph.query import GraphSnapshot

from .screens import (
    CandidateReviewScreen,
    CommunityStructureScreen,
    GraphViewScreen,
    KnowledgeExplorerScreen,
    OperationsConsoleScreen,
    RecordDetailScreen,
    RepairCenterScreen,
    SavedViewWorkbenchScreen,
    SchemaDeveloperScreen,
    TimelineScreen,
)

_SCREEN_NAV = (
    ("explore", "Explore"),
    ("record_detail", "Record"),
    ("graph", "Graph"),
    ("operations", "Operations"),
    ("repair", "Repair"),
    ("candidate_review", "Candidates"),
    ("saved_views", "Views"),
    ("community", "Community"),
    ("timeline", "Timeline"),
    ("schema", "Schema"),
)

_STYLE = """
<style>
:root {
  color-scheme: light;
  --sg-bg: #f7f8f5;
  --sg-ink: #18201c;
  --sg-muted: #5c6862;
  --sg-line: #d9ded6;
  --sg-panel: #ffffff;
  --sg-panel-soft: #eef3ee;
  --sg-accent: #1f7a5c;
  --sg-accent-soft: #dff1e9;
  --sg-blue: #345995;
  --sg-blue-soft: #e3ebfa;
  --sg-warn: #a86422;
  --sg-warn-soft: #fff0da;
  --sg-danger: #9a3b3b;
  --sg-danger-soft: #fde7e7;
}
* { box-sizing: border-box; }
body.sg-page {
  margin: 0;
  background: var(--sg-bg);
  color: var(--sg-ink);
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont,
    "Segoe UI", sans-serif;
  line-height: 1.45;
}
.sg-shell {
  min-height: 100vh;
  display: grid;
  grid-template-columns: 220px minmax(0, 1fr);
}
.sg-nav {
  border-right: 1px solid var(--sg-line);
  background: #fbfcfa;
  padding: 20px 14px;
}
.sg-brand {
  margin: 0 0 18px;
  font-size: 18px;
  font-weight: 720;
}
.sg-nav a {
  display: flex;
  align-items: center;
  min-height: 36px;
  margin: 4px 0;
  padding: 8px 10px;
  border-radius: 8px;
  color: var(--sg-muted);
  text-decoration: none;
  font-size: 14px;
}
.sg-nav a[aria-current="page"] {
  background: var(--sg-accent-soft);
  color: var(--sg-accent);
  font-weight: 700;
}
.sg-content {
  min-width: 0;
  padding: 24px;
}
.sg-header {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 16px;
  align-items: start;
  margin-bottom: 18px;
}
.sg-eyebrow {
  margin: 0 0 4px;
  color: var(--sg-muted);
  font-size: 13px;
  font-weight: 700;
  text-transform: uppercase;
}
.sg-header h1 {
  margin: 0;
  font-size: 30px;
  line-height: 1.1;
}
.sg-summary {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: flex-end;
}
.sg-layout {
  display: grid;
  grid-template-columns: minmax(0, 1.4fr) minmax(280px, .8fr);
  gap: 16px;
  align-items: start;
}
.sg-panel {
  background: var(--sg-panel);
  border: 1px solid var(--sg-line);
  border-radius: 8px;
  padding: 16px;
  margin-bottom: 16px;
}
.sg-panel h2 {
  margin: 0 0 12px;
  font-size: 16px;
}
.sg-list {
  display: grid;
  gap: 8px;
  list-style: none;
  margin: 0;
  padding: 0;
}
.sg-list li {
  border: 1px solid var(--sg-line);
  border-radius: 8px;
  padding: 10px 12px;
  background: #fff;
  overflow-wrap: anywhere;
}
.sg-compact li {
  padding: 7px 9px;
  font-size: 13px;
}
.sg-empty {
  margin: 0;
  color: var(--sg-muted);
}
.sg-badges {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.sg-badge {
  display: inline-flex;
  align-items: center;
  min-height: 26px;
  padding: 3px 8px;
  border-radius: 999px;
  background: var(--sg-panel-soft);
  color: var(--sg-muted);
  font-size: 12px;
  font-weight: 700;
}
.sg-badge[data-tone="accent"] { background: var(--sg-accent-soft); color: var(--sg-accent); }
.sg-badge[data-tone="blue"] { background: var(--sg-blue-soft); color: var(--sg-blue); }
.sg-badge[data-tone="warn"] { background: var(--sg-warn-soft); color: var(--sg-warn); }
.sg-badge[data-tone="danger"] { background: var(--sg-danger-soft); color: var(--sg-danger); }
.sg-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.sg-card {
  border: 1px solid var(--sg-line);
  border-radius: 8px;
  padding: 12px;
  background: #fff;
}
.sg-card + .sg-card {
  margin-top: 10px;
}
.sg-card h3 {
  margin: 0 0 8px;
  font-size: 15px;
}
.sg-card h4 {
  margin: 12px 0 6px;
  font-size: 13px;
}
.sg-card p {
  margin: 8px 0;
}
.sg-card-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 12px;
}
.sg-card-grid .sg-card + .sg-card {
  margin-top: 0;
}
.sg-action {
  border: 1px solid var(--sg-line);
  border-radius: 8px;
  background: #fff;
  color: var(--sg-ink);
  min-height: 34px;
  padding: 7px 10px;
  font: inherit;
  font-size: 13px;
  cursor: default;
}
.sg-action[data-kind*="repair"],
.sg-action[data-kind*="apply"] {
  border-color: #edcfaa;
  background: var(--sg-warn-soft);
  color: var(--sg-warn);
}
.sg-graph {
  width: 100%;
  min-height: 280px;
  border: 1px solid var(--sg-line);
  border-radius: 8px;
  background: #fbfcfa;
}
.sg-node circle {
  fill: var(--sg-accent-soft);
  stroke: var(--sg-accent);
  stroke-width: 2;
}
.sg-node[data-root="true"] circle {
  fill: var(--sg-blue-soft);
  stroke: var(--sg-blue);
}
.sg-node[data-orphan="true"] circle {
  fill: var(--sg-warn-soft);
  stroke: var(--sg-warn);
}
.sg-node text {
  fill: var(--sg-ink);
  font-size: 12px;
  font-weight: 700;
}
.sg-edge {
  stroke: #9ca8a1;
  stroke-width: 1.5;
}
.sg-edge.sg-path {
  stroke: var(--sg-blue);
  stroke-width: 3;
}
.sg-path {
  color: var(--sg-blue);
  font-weight: 700;
}
.sg-muted {
  color: var(--sg-muted);
}
@media (max-width: 860px) {
  .sg-shell { grid-template-columns: 1fr; }
  .sg-nav {
    border-right: 0;
    border-bottom: 1px solid var(--sg-line);
  }
  .sg-nav-links { display: flex; flex-wrap: wrap; gap: 4px; }
  .sg-header, .sg-layout { grid-template-columns: 1fr; }
  .sg-summary { justify-content: flex-start; }
}
</style>
"""


def _attr(value: object) -> str:
    return escape(str(value), quote=True)


def _section(title: str, body: str) -> str:
    return (
        f"<section class='sg-panel'><h2>{escape(title)}</h2>{body}</section>"
        if body
        else (
            f"<section class='sg-panel'><h2>{escape(title)}</h2>"
            "<p class='sg-empty'>None</p></section>"
        )
    )


def _list(items: list[str], *, compact: bool = False) -> str:
    if not items:
        return "<p class='sg-empty'>None</p>"
    class_name = "sg-list sg-compact" if compact else "sg-list"
    return (
        f"<ul class='{class_name}'>"
        + "".join(f"<li>{escape(item)}</li>" for item in items)
        + "</ul>"
    )


def _badges(items: list[tuple[str, str]] | list[str]) -> str:
    if not items:
        return "<p class='sg-empty'>None</p>"
    parts: list[str] = []
    for item in items:
        if isinstance(item, tuple):
            label, tone = item
        else:
            label, tone = item, ""
        tone_attr = f" data-tone='{_attr(tone)}'" if tone else ""
        parts.append(f"<span class='sg-badge'{tone_attr}>{escape(label)}</span>")
    return "<div class='sg-badges'>" + "".join(parts) + "</div>"


def _metric(label: str, value: int | str, *, tone: str = "") -> tuple[str, str]:
    rendered = f"{label}: {value}"
    return rendered, tone


def _nav(active_screen: str) -> str:
    links = []
    for screen_id, label in _SCREEN_NAV:
        current = " aria-current='page'" if screen_id == active_screen else ""
        links.append(f"<a href='#{screen_id}'{current}>{escape(label)}</a>")
    return (
        "<aside class='sg-nav'><p class='sg-brand'>SophiaGraph</p>"
        "<nav class='sg-nav-links' aria-label='Workbench screens'>"
        + "".join(links)
        + "</nav></aside>"
    )


def _page(
    *,
    screen_id: str,
    title: str,
    eyebrow: str,
    metrics: list[tuple[str, str]] | list[str],
    body: str,
) -> str:
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>{escape(title)} - SophiaGraph</title>{_STYLE}</head>"
        "<body class='sg-page'><div class='sg-shell'>"
        f"{_nav(screen_id)}<main id='{_attr(screen_id)}' class='sg-content' "
        f"data-screen='{_attr(screen_id)}'>"
        "<header class='sg-header'><div>"
        f"<p class='sg-eyebrow'>{escape(eyebrow)}</p><h1>{escape(title)}</h1>"
        "</div><div class='sg-summary'>"
        f"{_badges(metrics)}</div></header>{body}</main></div></body></html>"
    )


def _split_layout(primary: str, secondary: str = "") -> str:
    if not secondary:
        return primary
    return (
        "<div class='sg-layout'><div>"
        f"{primary}</div><aside>{secondary}</aside></div>"
    )


def _actions(items: list[tuple[str, str | None, str | None]]) -> str:
    if not items:
        return "<p class='sg-empty'>None</p>"
    buttons = []
    for action, label, target_id in items:
        target_attr = f" data-target-id='{_attr(target_id)}'" if target_id else ""
        buttons.append(
            f"<button class='sg-action' type='button' data-kind='{_attr(action)}'"
            f"{target_attr}>{escape(label or action)}</button>"
        )
    return "<div class='sg-actions'>" + "".join(buttons) + "</div>"


def _record_title_by_id(snapshot: GraphSnapshot) -> dict[str, str]:
    return {
        node.record_id: node.title or node.record_id
        for node in snapshot.nodes
    }


def _graph_svg(
    snapshot: GraphSnapshot | None,
    highlighted_ids: list[str] | None = None,
) -> str:
    if snapshot is None or not snapshot.nodes:
        return "<p class='sg-empty'>No graph nodes available.</p>"
    highlighted = set(highlighted_ids or [])
    width = 720
    height = 360
    center_x = width / 2
    center_y = height / 2
    radius = 125 if len(snapshot.nodes) > 2 else 95
    positions: dict[str, tuple[float, float]] = {}
    for index, node in enumerate(snapshot.nodes):
        if node.record_id == snapshot.root_record_id:
            positions[node.record_id] = (center_x, center_y)
            continue
        angle = (2 * pi * index) / max(1, len(snapshot.nodes))
        positions[node.record_id] = (
            center_x + radius * cos(angle),
            center_y + radius * sin(angle),
        )

    edge_parts = []
    for edge in snapshot.edges:
        if edge.target_record_id is None:
            continue
        if (
            edge.source_record_id not in positions
            or edge.target_record_id not in positions
        ):
            continue
        x1, y1 = positions[edge.source_record_id]
        x2, y2 = positions[edge.target_record_id]
        path_class = " sg-path" if edge.edge_id in highlighted else ""
        edge_parts.append(
            f"<line class='sg-edge{path_class}' x1='{x1:.1f}' y1='{y1:.1f}' "
            f"x2='{x2:.1f}' y2='{y2:.1f}' data-edge-id='{_attr(edge.edge_id)}'>"
            f"<title>{escape(edge.label or edge.relation_type or edge.edge_id)}</title>"
            "</line>"
        )

    node_parts = []
    for node in snapshot.nodes:
        x, y = positions[node.record_id]
        title = node.title or node.record_id
        node_parts.append(
            f"<g class='sg-node' data-node-id='{_attr(node.record_id)}' "
            f"data-root='{str(node.record_id == snapshot.root_record_id).lower()}' "
            f"data-orphan='{str(node.orphan).lower()}'>"
            f"<circle cx='{x:.1f}' cy='{y:.1f}' r='27'></circle>"
            f"<text x='{x:.1f}' y='{y + 45:.1f}' text-anchor='middle'>"
            f"{escape(title[:28])}</text><title>{escape(title)}</title></g>"
        )

    return (
        f"<svg class='sg-graph' viewBox='0 0 {width} {height}' role='img' "
        "aria-label='Knowledge graph viewport'>"
        + "".join(edge_parts)
        + "".join(node_parts)
        + "</svg>"
    )


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


def _candidate_content_text(content: object, *, limit: int = 180) -> str:
    text = str(content)
    if len(text) <= limit:
        return text
    return f"{text[:limit]}...[truncated]"


def _candidate_cards(screen: CandidateReviewScreen) -> str:
    if not screen.candidates:
        return "<p class='sg-empty'>No candidates match the current filters.</p>"
    cards = []
    for candidate in screen.candidates:
        title = candidate.title or candidate.key or candidate.candidate_id
        badges: list[tuple[str, str]] = [
            (candidate.status, "accent" if candidate.status == "proposed" else "blue"),
            (candidate.type, "blue"),
            (candidate.source, ""),
            (f"confidence: {candidate.confidence:g}", "accent"),
        ]
        if candidate.source_class:
            badges.append((f"source class: {candidate.source_class}", ""))
        if candidate.claim_key:
            badges.append((f"claim: {candidate.claim_key}", ""))
        if candidate.polarity:
            badges.append((f"polarity: {candidate.polarity}", ""))
        actions = [
            ("approve_candidate", "Approve", candidate.candidate_id),
            ("reject_candidate", "Reject", candidate.candidate_id),
        ]
        if candidate.status in {"approved", "proposed"}:
            actions.append(("promote_candidate", "Promote", candidate.candidate_id))
        cards.append(
            "<article class='sg-card' "
            f"data-candidate-id='{_attr(candidate.candidate_id)}' "
            f"data-status='{_attr(candidate.status)}'>"
            f"<h3>{escape(title)}</h3>"
            f"{_badges(badges)}"
            f"<p>{escape(_candidate_content_text(candidate.content))}</p>"
            f"{_list([f'scope={candidate.proposed_scope}', f'session={candidate.session_id}', f'evidence={len(candidate.evidence_refs)}'], compact=True)}"
            f"{_actions(actions)}</article>"
        )
    return "".join(cards)


def _candidate_status_counts(screen: CandidateReviewScreen) -> dict[str, int]:
    counts: dict[str, int] = {}
    for candidate in screen.candidates:
        counts[candidate.status] = counts.get(candidate.status, 0) + 1
    return counts


def _saved_view_row_label(row: Any) -> str:
    properties = ", ".join(
        f"{key}: {value}" for key, value in sorted(row.properties.items())
    )
    title = row.title or row.record_id
    if not properties:
        return title
    return f"{title} - {properties}"


def _saved_view_panel_cards(screen: SavedViewWorkbenchScreen) -> str:
    if not screen.panels:
        return "<p class='sg-empty'>No saved views are configured.</p>"
    cards = []
    for panel in screen.panels:
        definition = panel.definition
        result = panel.result
        summary_badges = [
            (f"{key}: {value}", "accent")
            for key, value in sorted(result.summaries.items())
        ]
        if not summary_badges:
            summary_badges.append((f"rows: {len(result.rows)}", "blue"))
        group_lines = [
            f"{group}: {', '.join(record_ids)}"
            for group, record_ids in sorted(result.groups.items())
        ]
        filter_label = "filtered" if definition.filters else "all records"
        badges = [
            (definition.view_type, "blue"),
            (panel.status, "accent" if panel.status == "ready" else "warn"),
            (filter_label, ""),
        ]
        cards.append(
            "<article class='sg-card' "
            f"data-view-id='{_attr(definition.view_id)}' "
            f"data-status='{_attr(panel.status)}'>"
            f"<h3>{escape(definition.name)}</h3>"
            f"{_badges(badges)}"
            "<h4>Summaries</h4>"
            f"{_badges(summary_badges)}"
            "<h4>Rows</h4>"
            f"{_list([_saved_view_row_label(row) for row in result.rows[:6]])}"
            "<h4>Groups</h4>"
            f"{_list(group_lines, compact=True)}"
            "</article>"
        )
    return "<div class='sg-card-grid'>" + "".join(cards) + "</div>"


def render_explorer_html(screen: KnowledgeExplorerScreen) -> str:
    hit_items = [
        f"{hit.title or hit.record_id} ({hit.record_type}) "
        f"score={hit.score:g} fields={', '.join(hit.matched_fields) or 'stored'}"
        for hit in screen.result.hits
    ]
    selected_record_id = screen.result.hits[0].record_id if screen.result.hits else "none"
    graph = screen.result.graph
    graph_highlights = [
        edge_id
        for path in screen.result.paths
        for edge_id in path.edge_ids
    ]
    primary = _section("Graph Viewport", _graph_svg(graph, graph_highlights))
    primary += _section("Hits", _list(hit_items))
    primary += _section(
        "Path Evidence",
        _list([" -> ".join(path.record_ids) for path in screen.result.paths]),
    )
    secondary = _section(
        "Facets",
        _badges(
            [
                (f"{facet.field}: {facet.value} ({facet.count})", "blue")
                for facet in screen.result.facets
            ]
        ),
    )
    secondary += _section(
        "Navigation Actions",
        _actions(
            [
                (action.action, action.label, action.record_id or action.candidate_id)
                for action in screen.result.navigation
            ]
        ),
    )
    secondary += _section(
        "Backlinks",
        _list([link.link_id for link in screen.result.backlinks], compact=True),
    )
    secondary += _section(
        "Outgoing Links",
        _list([link.link_id for link in screen.result.outgoing_links], compact=True),
    )
    if screen.result.query_plan:
        secondary += _section(
            "Query Plan",
            _list(
                [
                    f"{stage.stage}: {stage.input_count} -> {stage.output_count}"
                    for stage in screen.result.query_plan.stages
                ],
                compact=True,
            ),
        )
    return _page(
        screen_id="explore",
        title="Knowledge Explorer",
        eyebrow="Search and navigate",
        metrics=[
            _metric("hits", len(screen.result.hits), tone="accent"),
            _metric("graph nodes", len(graph.nodes) if graph else 0),
            _metric("paths", len(screen.result.paths), tone="blue"),
            _metric("actions", len(screen.result.navigation)),
            _metric("selected", selected_record_id),
        ],
        body=_split_layout(primary, secondary),
    )


def render_record_detail_html(screen: RecordDetailScreen) -> str:
    packet = screen.packet
    record = packet.record
    namespace_items = [
        f"{key}={value}"
        for key, value in record.effective_namespace.as_dict().items()
    ]
    primary = _section("Local Graph", _graph_svg(packet.graph))
    primary += _section("Stored Fields", _list(_record_field_items(screen)))
    primary += _section(
        "Document Blocks",
        _list([block.block_id for block in packet.document_blocks]),
    )
    secondary = _section("Namespace", _list(namespace_items, compact=True))
    secondary += _section("Metadata", _list(_record_meta_items(screen), compact=True))
    secondary += _section(
        "Relations",
        _list([relation.relation_id for relation in packet.relations], compact=True),
    )
    secondary += _section(
        "Backlinks",
        _list([link.link_id for link in packet.backlinks], compact=True),
    )
    secondary += _section(
        "Outgoing Links",
        _list([link.link_id for link in packet.outgoing_links], compact=True),
    )
    lifecycle_tone = "danger" if record.is_deleted else "accent"
    return _page(
        screen_id="record_detail",
        title=record.title or record.id,
        eyebrow="Record detail",
        metrics=[
            _metric("type", record.type, tone="blue"),
            _metric("tier", record.tier),
            _metric("deleted", str(record.is_deleted).lower(), tone=lifecycle_tone),
            _metric("links", len(packet.backlinks) + len(packet.outgoing_links)),
        ],
        body=_split_layout(primary, secondary),
    )


def render_graph_view_html(screen: GraphViewScreen) -> str:
    highlighted_edge_ids = (
        screen.highlighted_path.edge_ids if screen.highlighted_path else []
    )
    primary = _section(
        "Interactive Graph",
        _graph_svg(screen.snapshot, highlighted_edge_ids),
    )
    node_titles = _record_title_by_id(screen.snapshot)
    primary += _section(
        "Nodes",
        _list(
            [
                f"{node_titles[node.record_id]} degree={node.degree_in + node.degree_out}"
                for node in screen.snapshot.nodes
            ]
        ),
    )
    secondary = _section(
        "Edges",
        _list(
            [
                f"{edge.source_record_id} -> {edge.target_record_id or edge.unresolved_target}"
                for edge in screen.snapshot.edges
            ],
            compact=True,
        ),
    )
    secondary += _section(
        "Highlighted Path",
        _list(
            [" -> ".join(screen.highlighted_path.record_ids)]
            if screen.highlighted_path
            else [],
            compact=True,
        ),
    )
    secondary += _section(
        "Shared Neighbors",
        _list(
            screen.shared_neighbors.neighbor_record_ids
            if screen.shared_neighbors
            else [],
            compact=True,
        ),
    )
    secondary += _section(
        "Communities",
        _list(
            [community.community_id for community in screen.communities],
            compact=True,
        ),
    )
    return _page(
        screen_id="graph",
        title="Graph View",
        eyebrow=f"{screen.request.mode} mode",
        metrics=[
            _metric("nodes", len(screen.snapshot.nodes), tone="accent"),
            _metric("edges", len(screen.snapshot.edges), tone="blue"),
            _metric("depth", screen.request.depth),
            _metric("components", len(screen.components)),
        ],
        body=_split_layout(primary, secondary),
    )


def render_operations_console_html(screen: OperationsConsoleScreen) -> str:
    primary = _section(
        "Run",
        _list([screen.report.run_id, screen.report.kind, screen.report.status]),
    )
    primary += _section(
        "Counts",
        _badges(
            [
                f"{key}: {value}"
                for key, value in sorted(screen.report.counts.items())
            ]
        ),
    )
    secondary = _section(
        "Follow Up",
        _actions(
            [
                (
                    action.action,
                    action.action,
                    action.source_id
                    or action.conflict_id
                    or action.finding_id
                    or action.candidate_id,
                )
                for action in screen.report.follow_up_actions
            ]
        ),
    )
    return _page(
        screen_id="operations",
        title="Operations Console",
        eyebrow="Sync and source health",
        metrics=[
            _metric("status", screen.report.status, tone="accent"),
            _metric("kind", screen.report.kind, tone="blue"),
            _metric("follow up", len(screen.report.follow_up_actions), tone="warn"),
        ],
        body=_split_layout(primary, secondary),
    )


def render_repair_center_html(screen: RepairCenterScreen) -> str:
    primary = _section(
        "Findings",
        _list([finding.finding_id for finding in screen.report.findings]),
    )
    secondary = _section(
        "Repair Candidates",
        _actions(
            [
                (candidate.action, candidate.candidate_id, candidate.candidate_id)
                for candidate in screen.repair_candidates
            ]
        ),
    )
    return _page(
        screen_id="repair",
        title="Repair Center",
        eyebrow="Structural inspection",
        metrics=[
            _metric("findings", len(screen.report.findings), tone="warn"),
            _metric("candidates", len(screen.repair_candidates), tone="accent"),
        ],
        body=_split_layout(primary, secondary),
    )


def render_candidate_review_html(screen: CandidateReviewScreen) -> str:
    counts = _candidate_status_counts(screen)
    primary = _section("Review Queue", _candidate_cards(screen))
    secondary = _section(
        "Active Filters",
        _badges(
            [
                f"session: {screen.options.session_id or 'any'}",
                f"scope: {screen.options.proposed_scope or 'any'}",
                f"status: {screen.options.status or 'any'}",
                f"limit: {screen.options.limit or 'none'}",
            ]
        ),
    )
    secondary += _section(
        "Status Counts",
        _badges(
            [
                (f"{status}: {count}", "accent" if status == "proposed" else "blue")
                for status, count in sorted(counts.items())
            ]
        ),
    )
    secondary += _section(
        "Operator Actions",
        _list(
            [
                "Approve keeps the candidate reviewable.",
                "Reject records an explicit operator decision.",
                "Promote must call the store promotion path.",
            ],
            compact=True,
        ),
    )
    return _page(
        screen_id="candidate_review",
        title="Candidate Review",
        eyebrow="Memory curation",
        metrics=[
            _metric("candidates", len(screen.candidates), tone="accent"),
            _metric("proposed", counts.get("proposed", 0), tone="warn"),
            _metric("approved", counts.get("approved", 0), tone="blue"),
            _metric("promoted", counts.get("promoted", 0)),
        ],
        body=_split_layout(primary, secondary),
    )


def render_saved_view_workbench_html(screen: SavedViewWorkbenchScreen) -> str:
    total_rows = sum(len(panel.result.rows) for panel in screen.panels)
    empty_count = sum(1 for panel in screen.panels if panel.status == "empty")
    primary = _section("Live Panels", _saved_view_panel_cards(screen))
    secondary = _section(
        "Scope",
        _badges(
            [
                f"scopes: {', '.join(screen.request.scopes)}",
                f"live: {str(screen.request.live).lower()}",
                f"include invalidated: {str(screen.request.include_invalidated).lower()}",
            ]
        ),
    )
    secondary += _section(
        "Configured Views",
        _list(
            [
                f"{panel.definition.view_id} ({panel.definition.view_type})"
                for panel in screen.panels
            ],
            compact=True,
        ),
    )
    secondary += _section(
        "Refresh Actions",
        _actions(
            [
                ("refresh_saved_views", "Refresh", None),
                ("pin_saved_view_panel", "Pin Panel", None),
            ]
        ),
    )
    return _page(
        screen_id="saved_views",
        title="Saved Views",
        eyebrow="Live workbench panels",
        metrics=[
            _metric("panels", len(screen.panels), tone="accent"),
            _metric("rows", total_rows, tone="blue"),
            _metric("empty", empty_count, tone="warn" if empty_count else ""),
            _metric("live", str(screen.request.live).lower()),
        ],
        body=_split_layout(primary, secondary),
    )


def render_community_structure_html(screen: CommunityStructureScreen) -> str:
    primary = _section(
        "Communities",
        _list(
            [
                f"{community.community_id} members={len(community.record_ids)}"
                for community in screen.result.communities
            ]
        ),
    )
    primary += _section("Hits", _list([hit.community_id for hit in screen.result.hits]))
    secondary = _section(
        "Source Sets",
        _list(
            [source_set.source_set_id for source_set in screen.result.source_sets],
            compact=True,
        ),
    )
    secondary += _section(
        "Omitted",
        _list([item.reason for item in screen.result.omitted], compact=True),
    )
    return _page(
        screen_id="community",
        title="Community Structure",
        eyebrow="Global graph structure",
        metrics=[
            _metric("communities", len(screen.result.communities), tone="accent"),
            _metric("hits", len(screen.result.hits), tone="blue"),
            _metric("omitted", len(screen.result.omitted), tone="warn"),
        ],
        body=_split_layout(primary, secondary),
    )


def render_timeline_html(screen: TimelineScreen) -> str:
    deleted = [record.id for record in screen.records if record.is_deleted]
    primary = _section(
        "Records",
        _list(
            [
                f"{record.id} updated={record.updated_at}"
                for record in screen.records
            ]
        ),
    )
    secondary = _section("Deleted", _list(deleted, compact=True))
    secondary += _section(
        "Lifecycle",
        _badges(
            [
                (f"active: {len(screen.records) - len(deleted)}", "accent"),
                (f"deleted: {len(deleted)}", "danger" if deleted else ""),
            ]
        ),
    )
    return _page(
        screen_id="timeline",
        title="Timeline",
        eyebrow="Temporal inspection",
        metrics=[
            _metric("records", len(screen.records), tone="accent"),
            _metric("deleted", len(deleted), tone="danger" if deleted else ""),
        ],
        body=_split_layout(primary, secondary),
    )


def render_schema_developer_html(screen: SchemaDeveloperScreen) -> str:
    primary = _section(
        "Node Labels",
        _badges([(label, "blue") for label in screen.schema.node_labels]),
    )
    primary += _section(
        "Relation Types",
        _badges([(relation, "accent") for relation in screen.schema.relation_types]),
    )
    primary += _section(
        "Namespace Dimensions",
        _list(screen.schema.namespace_dimensions),
    )
    secondary = _section(
        "Backend Capabilities",
        _list(
            [
                f"{key}={value}"
                for key, value in sorted((screen.backend_capabilities or {}).items())
            ],
            compact=True,
        ),
    )
    secondary += _section(
        "Request Payload",
        _list([str(screen.last_request_payload or {})], compact=True),
    )
    secondary += _section(
        "Response Payload",
        _list([str(screen.last_response_payload or {})], compact=True),
    )
    return _page(
        screen_id="schema",
        title="Schema And Developer Panel",
        eyebrow="Contracts and payloads",
        metrics=[
            _metric("labels", len(screen.schema.node_labels), tone="blue"),
            _metric("relations", len(screen.schema.relation_types), tone="accent"),
            _metric("namespaces", len(screen.schema.namespace_dimensions)),
        ],
        body=_split_layout(primary, secondary),
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
    if isinstance(screen, CandidateReviewScreen):
        return render_candidate_review_html(screen)
    if isinstance(screen, SavedViewWorkbenchScreen):
        return render_saved_view_workbench_html(screen)
    if isinstance(screen, CommunityStructureScreen):
        return render_community_structure_html(screen)
    if isinstance(screen, TimelineScreen):
        return render_timeline_html(screen)
    if isinstance(screen, SchemaDeveloperScreen):
        return render_schema_developer_html(screen)
    raise TypeError(f"unsupported screen type: {type(screen)!r}")


__all__ = [
    "render_candidate_review_html",
    "render_community_structure_html",
    "render_explorer_html",
    "render_graph_view_html",
    "render_operations_console_html",
    "render_record_detail_html",
    "render_repair_center_html",
    "render_saved_view_workbench_html",
    "render_schema_developer_html",
    "render_screen_html",
    "render_timeline_html",
]
