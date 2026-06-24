"""Deterministic HTML rendering for the package-local human workbench packet."""

from __future__ import annotations

from html import escape

from .human_types import HumanWorkbenchPacket


def render_human_workbench_html(packet: HumanWorkbenchPacket) -> str:
    """Render a deterministic HTML preview for package-local human workflows."""
    notes_html = "".join(
        (
            "<li>"
            f"<strong>{escape(item.title)}</strong>"
            f" [{escape(item.note_key)}]"
            f" status={'archived' if item.archived else 'active'}"
            f" updated_at={escape(item.updated_at)}"
            "</li>"
        )
        for item in packet.workspace.notes
    )
    import_html = ""
    if packet.import_plan is not None:
        import_rows = "".join(
            (
                "<li>"
                f"{escape(item.path)} :: {escape(item.action)}"
                f" ({escape(item.reason)})"
                "</li>"
            )
            for item in packet.import_plan.items
        )
        import_html = (
            "<section><h2>Import Plan</h2>"
            f"<p>created={packet.import_plan.created_count} "
            f"updated={packet.import_plan.updated_count} "
            f"deleted={packet.import_plan.deleted_count} "
            f"unchanged={packet.import_plan.unchanged_count}</p>"
            f"<ul>{import_rows}</ul></section>"
        )
    source_html = ""
    if packet.source_console is not None:
        source_rows = "".join(
            (
                "<li>"
                f"{escape(item.display_name)} [{escape(item.source_id)}]"
                f" status={escape(item.freshness_status)}"
                f" conflicts={item.open_conflict_count}"
                "</li>"
            )
            for item in packet.source_console.sources
        )
        source_html = (
            "<section><h2>Source Console</h2>"
            f"<p>open_conflicts={packet.source_console.open_conflict_count}</p>"
            f"<ul>{source_rows}</ul></section>"
        )
    return (
        "<html><body>"
        "<h1>Human Workbench</h1>"
        f"<p>active_notes={packet.workspace.active_count} "
        f"archived_notes={packet.workspace.archived_count}</p>"
        f"<section><h2>Notes</h2><ul>{notes_html}</ul></section>"
        f"{import_html}{source_html}"
        "</body></html>"
    )
