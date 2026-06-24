from __future__ import annotations

from pathlib import Path

from sophiagraph import (
    CandidateListOptions,
    CommunityDetectionOptions,
    CommunityQueryOptions,
    ConnectorReplayRequest,
    KnowledgeDocumentBlock,
    KnowledgeExplorerRequest,
    ListQueryOptions,
    MemoryCandidate,
    LocalSyncRequest,
    MemoryNamespace,
    MemoryRecord,
    RepairCandidate,
    SourceIngestEnvelope,
    SourceRegistryEntry,
    StructuralLink,
    SyncRunRequest,
)
from sophiagraph.sync import detect_sync_conflict
from sophiagraph.views import (
    SavedViewDefinition,
    SavedViewFilter,
    SavedViewSummary,
)
from sophiagraph.ui import (
    SavedViewWorkbenchRequest,
    UiAppState,
    build_candidate_review_screen,
    build_community_structure_screen,
    build_explorer_screen,
    build_graph_view_screen,
    build_operations_console_screen,
    build_record_detail_packet,
    build_record_detail_screen,
    build_repair_center_screen,
    build_saved_view_workbench_screen,
    build_schema_developer_screen,
    build_timeline_screen,
    render_screen_html,
    screen_to_dict,
)
from sophiagraph.ui.screens import GraphViewRequest
from sophiagraph.storage import SophiaGraphMemoryStore


def _ns() -> MemoryNamespace:
    return MemoryNamespace(tenant_id="tenant", agent_id="ui", graph_id="main")


def _record(record_id: str, title: str, text: str) -> MemoryRecord:
    return MemoryRecord(
        id=record_id,
        scope="agent:ui",
        type="fact",
        key=record_id,
        title=title,
        content={"text": text},
        created_at="2026-06-06T00:00:00+00:00",
        updated_at="2026-06-06T00:00:00+00:00",
        namespace=_ns(),
        meta={"document": {"path": f"{record_id}.md"}, "properties": {"status": "ok"}},
    )


def _link(link_id: str, source: str, target: str, raw_target: str) -> StructuralLink:
    return StructuralLink(
        link_id=link_id,
        source_record_id=source,
        target_record_id=target,
        raw_target=raw_target,
        link_kind="wikilink",
        resolution_status="resolved",
        namespace=_ns(),
        relation_type="supports",
        created_at="2026-06-06T00:00:00+00:00",
    )


def _seed_store() -> SophiaGraphMemoryStore:
    store = SophiaGraphMemoryStore()
    auth = _record("auth", "Auth Decision", "JWT auth")
    refresh = _record("refresh", "Refresh Plan", "Extends auth")
    store.put_record(auth)
    store.put_record(refresh)
    store.put_link(_link("link-auth-refresh", "auth", "refresh", "Refresh Plan"))
    store.put_document_blocks(
        "auth",
        [
            KnowledgeDocumentBlock(
                block_id="block-auth",
                document_id="doc-auth",
                record_id="auth",
                block_type="heading",
                anchor="auth-heading",
                excerpt="JWT auth",
            )
        ],
    )
    store.put_candidate(
        MemoryCandidate(
            candidate_id="candidate-auth-rule",
            session_id="session-ui",
            proposed_scope="agent:ui",
            type="fact",
            title="Auth rule candidate",
            content={"text": "JWT auth should be remembered"},
            tags=["auth"],
            source="agent_inferred",
            confidence=0.82,
            status="proposed",
            namespace=_ns(),
            claim_key="auth.jwt",
            polarity="asserts",
            source_class="user_input",
            created_at="2026-06-06T00:05:00+00:00",
            updated_at="2026-06-06T00:05:00+00:00",
        )
    )
    return store


def test_ui_mvp_screens_render_structural_content() -> None:
    store = _seed_store()
    explorer = build_explorer_screen(
        store,
        KnowledgeExplorerRequest(
            scopes=["agent:ui"],
            namespaces=[_ns()],
            query="auth",
            root_record_id="auth",
        ),
    )
    detail = build_record_detail_screen(store, record_id="auth")
    graph = build_graph_view_screen(
        store,
        GraphViewRequest(
            root_record_id="auth",
            scopes=["agent:ui"],
            namespaces=[_ns()],
            target_record_id="refresh",
        ),
    )
    operations = build_operations_console_screen(
        SyncRunRequest(
            run_id="sync-ui",
            observed_at="2026-06-06T01:00:00+00:00",
            sync_request=LocalSyncRequest(
                mode="file_primary",
                namespace=_ns(),
                source_id="vault:ui",
                path="auth.md",
                record_id="auth",
                previous_file_hash="h1",
                previous_record_hash="r1",
                current_file_hash="h2",
                current_record_hash="r2",
            ),
        )
    )
    repair = build_repair_center_screen(
        report_id="repair-ui",
        namespace=_ns(),
        generated_at="2026-06-06T02:00:00+00:00",
        records=store.list_records(ListQueryOptions(scopes=["agent:ui"])),
        links=store.get_outgoing_links("auth"),
        conflicts=[
            detect_sync_conflict(
                LocalSyncRequest(
                    mode="file_primary",
                    namespace=_ns(),
                    source_id="vault:ui",
                    path="auth.md",
                    previous_file_hash="h1",
                    previous_record_hash="r1",
                    current_file_hash="h2",
                    current_record_hash="r2",
                ),
                observed_at="2026-06-06T02:00:00+00:00",
            ).conflict
        ],
        repair_candidates=[
            RepairCandidate(
                candidate_id="repair-1",
                finding_id="finding-1",
                action="caller_patch",
                namespace=_ns(),
                patch={"target_record_id": "refresh"},
            )
        ],
    )
    candidates = build_candidate_review_screen(
        store,
        CandidateListOptions(status="proposed", limit=10),
    )
    saved_views = build_saved_view_workbench_screen(
        store,
        SavedViewWorkbenchRequest(
            scopes=["agent:ui"],
            namespaces=[_ns()],
            definitions=[
                SavedViewDefinition(
                    view_id="view-ready",
                    name="Ready Records",
                    filters=SavedViewFilter("status", "eq", "ok"),
                    projected_properties=["status", "path"],
                    summaries=[SavedViewSummary("count")],
                )
            ],
        ),
    )

    explorer_html = render_screen_html(explorer)
    assert "Knowledge Explorer" in explorer_html
    assert "OpenMinion Integration" not in explorer_html
    detail_html = render_screen_html(detail)
    graph_html = render_screen_html(graph)
    operations_html = render_screen_html(operations)
    repair_html = render_screen_html(repair)
    candidate_html = render_screen_html(candidates)
    saved_view_html = render_screen_html(saved_views)

    assert "Auth Decision" in detail_html
    assert "created_at=2026-06-06T00:00:00+00:00" in detail_html
    assert "document={&#x27;path&#x27;: &#x27;auth.md&#x27;}" in detail_html
    assert "auth" in graph_html
    assert "auth -&gt; refresh" in graph_html
    assert "Operations Console" in operations_html
    assert "sync-ui" in operations_html
    assert "Repair Center" in repair_html
    assert "Candidate Review" in candidate_html
    assert "Auth rule candidate" in candidate_html
    assert "Saved Views" in saved_view_html
    assert "Ready Records" in saved_view_html

    packet = build_record_detail_packet(store, record_id="auth")
    assert [block.block_id for block in packet.document_blocks] == ["block-auth"]


def test_ui_renderer_exposes_workbench_navigation_and_graph_affordances() -> None:
    store = _seed_store()
    explorer = build_explorer_screen(
        store,
        KnowledgeExplorerRequest(
            scopes=["agent:ui"],
            namespaces=[_ns()],
            query="auth",
            root_record_id="auth",
        ),
    )
    graph = build_graph_view_screen(
        store,
        GraphViewRequest(
            root_record_id="auth",
            scopes=["agent:ui"],
            namespaces=[_ns()],
            target_record_id="refresh",
        ),
    )

    explorer_html = render_screen_html(explorer)
    graph_html = render_screen_html(graph)

    assert explorer_html.startswith("<!doctype html>")
    assert "class='sg-shell'" in explorer_html
    assert "aria-current='page'>Explore</a>" in explorer_html
    assert "class='sg-summary'" in explorer_html
    assert "data-kind='open_root'" in explorer_html

    assert "aria-current='page'>Graph</a>" in graph_html
    assert "class='sg-graph'" in graph_html
    assert "role='img' aria-label='Knowledge graph viewport'" in graph_html
    assert "data-node-id='auth'" in graph_html
    assert "data-node-id='refresh'" in graph_html
    assert "data-edge-id='link-auth-refresh'" in graph_html
    assert "sg-edge sg-path" in graph_html


def test_ui_candidate_review_screen_surfaces_structural_review_actions() -> None:
    store = _seed_store()
    screen = build_candidate_review_screen(
        store,
        CandidateListOptions(status="proposed", limit=5),
    )

    html = render_screen_html(screen)

    assert screen.screen_id == "candidate_review"
    assert [candidate.candidate_id for candidate in screen.candidates] == [
        "candidate-auth-rule"
    ]
    assert "aria-current='page'>Candidates</a>" in html
    assert "data-candidate-id='candidate-auth-rule'" in html
    assert "claim: auth.jwt" in html
    assert "source class: user_input" in html
    assert "data-kind='approve_candidate'" in html
    assert "data-kind='reject_candidate'" in html
    assert "data-kind='promote_candidate'" in html


def test_ui_saved_view_workbench_surfaces_live_panels() -> None:
    store = _seed_store()
    screen = build_saved_view_workbench_screen(
        store,
        SavedViewWorkbenchRequest(
            scopes=["agent:ui"],
            namespaces=[_ns()],
            definitions=[
                SavedViewDefinition(
                    view_id="view-ready",
                    name="Ready Records",
                    view_type="table",
                    filters=SavedViewFilter("status", "eq", "ok"),
                    projected_properties=["status", "path"],
                    group_by="status",
                    summaries=[SavedViewSummary("count")],
                )
            ],
            live=True,
        ),
    )

    html = render_screen_html(screen)

    assert screen.screen_id == "saved_views"
    assert len(screen.panels) == 1
    assert screen.panels[0].result.summaries == {"count": 2}
    assert screen.panels[0].result.groups == {"ok": ["auth", "refresh"]}
    assert "aria-current='page'>Views</a>" in html
    assert "data-view-id='view-ready'" in html
    assert "Ready Records" in html
    assert "count: 2" in html
    assert "status: ok" in html
    assert "data-kind='refresh_saved_views'" in html


def test_ui_secondary_screens_cover_community_timeline_and_schema() -> None:
    store = _seed_store()
    community = build_community_structure_screen(
        store,
        CommunityQueryOptions(
            detection=CommunityDetectionOptions(
                scopes=["agent:ui"],
                namespaces=[_ns()],
            ),
            limit=10,
        ),
    )
    timeline = build_timeline_screen(
        store,
        ListQueryOptions(
            scopes=["agent:ui"],
            namespaces=[_ns()],
            include_invalidated=True,
        ),
    )
    schema = build_schema_developer_screen(
        records=timeline.records,
        links=store.get_outgoing_links("auth"),
        blocks=store.list_document_blocks(record_id="auth"),
        backend_capabilities={"neighbors": True},
        last_request_payload={"kind": "schema"},
        last_response_payload={"ok": True},
    )

    assert "Community Structure" in render_screen_html(community)
    assert "Timeline" in render_screen_html(timeline)
    assert "Schema And Developer Panel" in render_screen_html(schema)
    assert schema.schema.node_labels


def test_ui_state_and_screen_dicts_stay_structural() -> None:
    store = _seed_store()
    explorer = build_explorer_screen(
        store,
        KnowledgeExplorerRequest(scopes=["agent:ui"], namespaces=[_ns()], query="auth"),
    )
    state = UiAppState(
        active_namespace=_ns(),
        explorer_request=explorer.request,
        selected_record_id="auth",
        selected_candidate_id="candidate-auth-rule",
        candidate_status_filter="proposed",
        active_saved_view_id="view-ready",
        saved_view_live=True,
        graph_depth=1,
        graph_mode="neighborhood",
        last_request_payload={"query": "auth"},
        last_response_payload={"hit_count": len(explorer.result.hits)},
    )

    payload = screen_to_dict(explorer)
    assert payload["screen_id"] == "explore"
    assert payload["result"]["hits"][0]["record_id"] == "auth"
    assert state.selected_record_id == "auth"
    assert state.selected_candidate_id == "candidate-auth-rule"
    assert state.active_saved_view_id == "view-ready"


def test_ui_source_files_stay_structural_and_query_builder_free() -> None:
    forbidden = {
        "text_to_cypher",
        "generate_cypher",
        "cypher_from_prompt",
        "nl_to_cypher",
        "summarize_community",
        "generate_community_summary",
        "infer_topic",
    }
    root = Path(__file__).resolve().parents[1] / "src" / "sophiagraph" / "ui"
    for relative_path in ("render.py", "screens.py", "state.py"):
        text = (root / relative_path).read_text(encoding="utf-8").lower()
        leaked = [token for token in forbidden if token in text]
        assert not leaked, f"{relative_path} contains forbidden UI tokens: {leaked}"


def test_ui_operations_screen_supports_connector_requests() -> None:
    source = SourceRegistryEntry(
        source_id="source:ui",
        source_type="test_fake",
        namespace=_ns(),
        display_name="UI Source",
        permission_scope="read_only",
    )
    envelope = SourceIngestEnvelope.create(
        source_id=source.source_id,
        namespace=source.namespace,
        payload_kind="document",
        payload={"id": "doc-1"},
        cursor="cursor-2",
        content_hash="hash-2",
    )
    screen = build_operations_console_screen(
        ConnectorReplayRequest(
            run_id="connector-ui",
            source=source,
            envelope=envelope,
            existing_freshness=None,
            updated_at="2026-06-06T03:00:00+00:00",
        )
    )

    html = render_screen_html(screen)
    assert "connector-ui" in html
    assert "Operations Console" in html
