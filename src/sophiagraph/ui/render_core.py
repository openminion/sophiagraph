"""Shared deterministic HTML helpers for package-local UI renderers."""

from __future__ import annotations

from html import escape
from math import cos, pi, sin

from sophiagraph.query import GraphSnapshot

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
    return f"{label}: {value}", tone


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
        f"{_badges(metrics)}</div></header>{body}"
        "</main></div></body></html>"
    )


def _split_layout(primary: str, secondary: str = "") -> str:
    if not secondary:
        return primary
    return (
        f"<div class='sg-layout'><div>{primary}</div><aside>{secondary}</aside></div>"
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
    return {node.record_id: node.title or node.record_id for node in snapshot.nodes}


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


__all__ = [
    "_actions",
    "_attr",
    "_badges",
    "_graph_svg",
    "_list",
    "_metric",
    "_page",
    "_record_title_by_id",
    "_section",
    "_split_layout",
]
