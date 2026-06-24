"""Screen-specific deterministic HTML renderers for package-local UI packets."""

from __future__ import annotations

from html import escape
from typing import Any

from .render_core import (
    _actions,
    _attr,
    _badges,
    _graph_svg,
    _list,
    _metric,
    _page,
    _record_title_by_id,
    _section,
    _split_layout,
)
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
    return title if not properties else f"{title} - {properties}"


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
    selected_record_id = (
        screen.result.hits[0].record_id if screen.result.hits else "none"
    )
    graph = screen.result.graph
    graph_highlights = [
        edge_id for path in screen.result.paths for edge_id in path.edge_ids
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
        f"{key}={value}" for key, value in record.effective_namespace.as_dict().items()
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
            [community.community_id for community in screen.communities], compact=True
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
            [f"{key}: {value}" for key, value in sorted(screen.report.counts.items())]
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
            [f"{record.id} updated={record.updated_at}" for record in screen.records]
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
