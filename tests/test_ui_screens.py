from __future__ import annotations

from pathlib import Path

from sophiagraph import (
    CommunityDetectionOptions,
    CommunityQueryOptions,
    ConnectorReplayRequest,
    KnowledgeDocumentBlock,
    KnowledgeExplorerRequest,
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
from sophiagraph.ui import (
    UiAppState,
    build_community_structure_screen,
    build_explorer_screen,
    build_graph_view_screen,
    build_operations_console_screen,
    build_record_detail_packet,
    build_record_detail_screen,
    build_repair_center_screen,
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
        records=store.list_records(
            __import__("sophiagraph").ListQueryOptions(scopes=["agent:ui"])
        ),
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

    assert "Knowledge Explorer" in render_screen_html(explorer)
    detail_html = render_screen_html(detail)
    graph_html = render_screen_html(graph)
    operations_html = render_screen_html(operations)
    repair_html = render_screen_html(repair)

    assert "Auth Decision" in detail_html
    assert "created_at=2026-06-06T00:00:00+00:00" in detail_html
    assert "document={&#x27;path&#x27;: &#x27;auth.md&#x27;}" in detail_html
    assert "auth" in graph_html
    assert "auth -&gt; refresh" in graph_html
    assert "Operations Console" in operations_html
    assert "sync-ui" in operations_html
    assert "Repair Center" in repair_html

    packet = build_record_detail_packet(store, record_id="auth")
    assert [block.block_id for block in packet.document_blocks] == ["block-auth"]


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
        __import__("sophiagraph").ListQueryOptions(
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
        graph_depth=1,
        graph_mode="neighborhood",
        last_request_payload={"query": "auth"},
        last_response_payload={"hit_count": len(explorer.result.hits)},
    )

    payload = screen_to_dict(explorer)
    assert payload["screen_id"] == "explore"
    assert payload["result"]["hits"][0]["record_id"] == "auth"
    assert state.selected_record_id == "auth"


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
