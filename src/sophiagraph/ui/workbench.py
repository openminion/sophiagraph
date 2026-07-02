"""Deterministic HTML renderer for collaborative workbench packets."""

from __future__ import annotations

from html import escape

from sophiagraph.workbench import (
    WorkbenchActionPreview,
    WorkbenchGraphPanelState,
    WorkbenchReviewInbox,
    WorkspaceWorkbenchPacket,
)

from .render_core import (
    _actions,
    _badges,
    _list,
    _metric,
    _page,
    _section,
    _split_layout,
)


def render_collaborative_workbench_html(packet: WorkspaceWorkbenchPacket) -> str:
    """Render a host-neutral collaborative second-brain workbench snapshot."""

    metrics = [
        _metric("reviews", packet.review_inbox.pending_count, tone="warn"),
        _metric("actions", len(packet.action_previews), tone="blue"),
        _metric(
            "graph",
            packet.graph_panel.node_count if packet.graph_panel else 0,
            tone="accent",
        ),
    ]
    primary = (
        _note_panel(packet)
        + _review_inbox(packet.review_inbox)
        + _graph_panel(packet.graph_panel)
    )
    secondary = (
        _action_previews(packet.action_previews)
        + _publish_panel(packet)
        + _workspace_activity(packet)
    )
    return _page(
        screen_id="workbench",
        title=f"{packet.request.workspace_id} Workbench",
        eyebrow="Collaborative second brain",
        metrics=metrics,
        body=_split_layout(primary, secondary),
    )


def _note_panel(packet: WorkspaceWorkbenchPacket) -> str:
    panel = packet.note_panel
    if panel is None:
        return _section("Active Note", "")
    badges = _badges(
        [
            (panel.record_type, "blue"),
            (panel.policy.visibility, "accent"),
            (panel.policy.retention_class, ""),
        ]
    )
    related = _list(list(panel.related_record_ids), compact=True)
    actions = _actions(
        [
            (
                preview.request.action,
                f"{preview.request.action}: {preview.status}",
                preview.request.target_id,
            )
            for preview in panel.action_previews
        ]
    )
    body = (
        f"<div class='sg-card'><h3>{escape(panel.title)}</h3>"
        f"<p class='sg-muted'>{escape(panel.record_id)}</p>{badges}"
        f"<p>Backlinks: {panel.backlink_count} · outgoing: {panel.outgoing_count} · "
        f"blocks: {panel.block_count}</p><h4>Related</h4>{related}"
        f"<h4>Actions</h4>{actions}</div>"
    )
    return _section("Active Note", body)


def _review_inbox(inbox: WorkbenchReviewInbox) -> str:
    if not inbox.items:
        return _section("Review Inbox", "")
    cards = []
    for item in inbox.items:
        badges = _badges(
            [(item.kind, "blue"), (item.status, _tone_for_status(item.status))]
        )
        actions = _actions(
            [
                (action, action.replace("_", " "), item.target_id)
                for action in item.allowed_actions
            ]
        )
        cards.append(
            "<article class='sg-card'>"
            f"<h3>{escape(item.title)}</h3>"
            f"{badges}"
            f"<p class='sg-muted'>{escape(item.target_id)}</p>"
            f"<p>{escape(item.preview or 'Awaiting explicit review action.')}</p>"
            f"{actions}"
            "</article>"
        )
    return _section("Review Inbox", "".join(cards))


def _graph_panel(panel: WorkbenchGraphPanelState | None) -> str:
    if panel is None:
        return _section("Graph View", "")
    body = (
        "<div class='sg-card'>"
        f"{_badges([(panel.provider_id, 'accent'), (panel.graph_role, 'blue')])}"
        f"<p>Nodes: {panel.node_count} · edges: {panel.edge_count}</p>"
        f"<p class='sg-muted'>Selected: {escape(panel.selected_node_id or 'None')}</p>"
        "</div>"
    )
    if panel.embed_html:
        body += (
            f"<div class='sg-card' data-provider='graphfakos'>{panel.embed_html}</div>"
        )
    return _section("GraphFakos View", body)


def _action_previews(previews: tuple[WorkbenchActionPreview, ...]) -> str:
    if not previews:
        return _section("Action Preview", "")
    rows = []
    for preview in previews:
        messages = ", ".join(preview.policy_messages) or preview.reason
        rows.append(
            f"{preview.request.action} on {preview.request.target_id}: "
            f"{preview.status} ({messages})"
        )
    return _section("Action Preview", _list(rows, compact=True))


def _publish_panel(packet: WorkspaceWorkbenchPacket) -> str:
    publish = packet.publish
    if publish is None:
        return _section("Publish and Sharing", "")
    body = (
        f"{_badges([(publish.profile_kind, 'blue'), (publish.profile_id, '')])}"
        f"<p>Included: {publish.included_count} · omitted: {publish.omitted_count}</p>"
    )
    if publish.delivery_target:
        body += (
            f"<p class='sg-muted'>{escape(publish.delivery_target)}: "
            f"{escape(publish.payload_ref)}</p>"
        )
    return _section("Publish and Sharing", body)


def _workspace_activity(packet: WorkspaceWorkbenchPacket) -> str:
    items = [
        f"revisions:{len(packet.workspace_revisions)}",
        f"diffs:{len(packet.workspace_diffs)}",
    ]
    if packet.sync_status is not None:
        items.append(
            "sync:"
            f"{packet.sync_status.fresh_count} fresh/"
            f"{packet.sync_status.stale_count} stale"
        )
    if packet.sync_plan is not None:
        items.append(f"sync-plan:{len(packet.sync_plan.deltas)}")
    return _section("Workspace Activity", _list(items, compact=True))


def _tone_for_status(status: str) -> str:
    if status in {"blocked", "rejected"}:
        return "danger"
    if status in {"pending", "proposed"}:
        return "warn"
    if status in {"approved", "promoted", "applied"}:
        return "accent"
    return ""


__all__ = ["render_collaborative_workbench_html"]
