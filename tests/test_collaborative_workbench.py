from __future__ import annotations

import ast
from pathlib import Path

from graphfakos import GraphFakosRequest, GraphFakosViewerState, render_embeddable_html

from sophiagraph import (
    CandidateListOptions,
    CandidateQueueOptions,
    KnowledgeExplorerRequest,
    ListQueryOptions,
    MemoryCandidate,
    MemoryNamespace,
    MemoryRecord,
    PublishProfile,
    RepairCandidate,
    SophiaGraphMemoryStore,
    StructuralLink,
    WorkbenchActionRequest,
    WorkbenchPolicyOverlay,
    WorkspaceActionRequest,
    WorkspaceFileDelta,
    WorkspaceSyncPlan,
    WorkspaceSyncStatus,
    WorkspaceWorkbenchRequest,
    build_publish_plan,
    build_workbench_graph_panel,
    build_workbench_review_inbox,
    build_workspace_workbench_packet,
    evaluate_workspace_action,
    list_candidate_queue,
    preview_workbench_action,
    publish_overlay_from_plan,
    workbench_to_dict,
    WorkspaceRoleBinding,
)
from sophiagraph.ui.screens import GraphViewRequest
from sophiagraph.ui import (
    SophiagraphViewerProvider,
    build_candidate_review_screen,
    build_explorer_screen,
    build_graph_view_screen,
    build_record_detail_screen,
    render_collaborative_workbench_html,
)


def _ns() -> MemoryNamespace:
    return MemoryNamespace(tenant_id="tenant", agent_id="workbench", graph_id="main")


def _record(record_id: str, title: str, text: str) -> MemoryRecord:
    return MemoryRecord(
        id=record_id,
        scope="agent:workbench",
        type="fact",
        key=record_id,
        title=title,
        content={"text": text},
        namespace=_ns(),
        created_at="2026-07-01T00:00:00+00:00",
        updated_at="2026-07-01T00:00:00+00:00",
    )


def _seed_store() -> SophiaGraphMemoryStore:
    store = SophiaGraphMemoryStore()
    store.put_record(_record("note-1", "Workbench Note", "Human-owned note body."))
    store.put_record(_record("note-2", "Related Note", "Linked context."))
    store.put_link(
        StructuralLink(
            link_id="link-1",
            source_record_id="note-1",
            target_record_id="note-2",
            raw_target="Related Note",
            link_kind="wikilink",
            resolution_status="resolved",
            namespace=_ns(),
            relation_type="supports",
            created_at="2026-07-01T00:00:00+00:00",
        )
    )
    store.put_candidate(
        MemoryCandidate(
            candidate_id="candidate-1",
            session_id="agent-session",
            proposed_scope="agent:workbench",
            type="fact",
            title="Agent proposed note",
            content={"text": "A candidate memory needs human review."},
            source="agent_inferred",
            confidence=0.8,
            status="proposed",
            namespace=_ns(),
            claim_key="workbench.candidate",
            polarity="asserts",
            source_class="user_input",
            created_at="2026-07-01T00:01:00+00:00",
            updated_at="2026-07-01T00:01:00+00:00",
        )
    )
    return store


def test_collaborative_workbench_packet_composes_existing_surfaces() -> None:
    store = _seed_store()
    explorer = build_explorer_screen(
        store,
        KnowledgeExplorerRequest(
            scopes=["agent:workbench"],
            namespaces=[_ns()],
            query="note",
            root_record_id="note-1",
        ),
    )
    record_detail = build_record_detail_screen(store, record_id="note-1")
    candidate_screen = build_candidate_review_screen(
        store,
        CandidateListOptions(status="proposed"),
    )
    _graph_screen = build_graph_view_screen(
        store,
        GraphViewRequest(root_record_id="note-1", scopes=["agent:workbench"]),
    )
    candidate_items = tuple(
        list_candidate_queue(store, CandidateQueueOptions(status="proposed"))
    )
    repair = RepairCandidate(
        candidate_id="repair-1",
        finding_id="finding-1",
        action="caller_patch",
        namespace=_ns(),
        patch={"target_record_id": "note-2"},
    )
    profile = PublishProfile(profile_id="share-local", kind="read_only_share")
    publish_plan = build_publish_plan(
        profile,
        store.list_records(ListQueryOptions(scopes=["agent:workbench"])),
    )
    policy = WorkbenchPolicyOverlay(
        visibility="visible",
        retention_class="standard",
        review_required=True,
        publish_profile_id=profile.profile_id,
        messages=("human review required",),
    )
    gate = evaluate_workspace_action(
        (
            WorkspaceRoleBinding(
                workspace_id="workspace-main",
                actor_id="agent-a",
                role="reviewer",
                namespace=_ns(),
            ),
        ),
        WorkspaceActionRequest(
            workspace_id="workspace-main",
            actor_id="agent-a",
            action="apply",
            target_id="note-1",
        ),
    )
    action_preview = preview_workbench_action(
        WorkbenchActionRequest(
            action="propose_note_edit",
            target_id="note-1",
            actor_id="agent-a",
            workspace_id="workspace-main",
            requires_review=True,
        ),
        gate=gate,
        policy=policy,
        publish_plan=publish_plan,
        provenance_refs=("note-1",),
    )
    provider = SophiagraphViewerProvider(
        store=store,
        scope="agent:workbench",
        namespace=_ns(),
    )
    graph_request = GraphFakosRequest(focus_node_id="note-1", screen="neighborhood")
    graph = provider.load_graph(graph_request)
    graph_panel = build_workbench_graph_panel(
        graph,
        viewer_state=GraphFakosViewerState.from_request(graph_request),
        selected_node_id="note-1",
        embed_html=render_embeddable_html(provider, graph_request),
    )
    sync_status = WorkspaceSyncStatus(
        workspace_root="workspace",
        source_root="workspace/notes",
        namespace=_ns(),
        tracked_count=1,
        active_file_count=1,
        fresh_count=1,
        stale_count=0,
        failed_count=0,
        open_conflict_count=0,
        pending_delta_count=1,
        last_scan_at="2026-07-01T00:02:00+00:00",
    )
    sync_plan = WorkspaceSyncPlan(
        workspace_root="workspace",
        source_root="workspace/notes",
        namespace=_ns(),
        observed_at="2026-07-01T00:03:00+00:00",
        deltas=(
            WorkspaceFileDelta(
                kind="modified",
                relative_path="note-1.md",
                source_id="workspace-file:note-1.md",
            ),
        ),
        tracked_count=1,
    )

    packet = build_workspace_workbench_packet(
        WorkspaceWorkbenchRequest(
            workspace_id="workspace-main",
            actor_id="agent-a",
            root_record_id="note-1",
            query="note",
        ),
        explorer=explorer,
        record_detail=record_detail,
        candidate_review=candidate_screen,
        review_inbox=build_workbench_review_inbox(
            candidates=candidate_items,
            repairs=(repair,),
            publish_plans=(publish_plan,),
        ),
        graph_panel=graph_panel,
        publish=publish_overlay_from_plan(publish_plan),
        sync_status=sync_status,
        sync_plan=sync_plan,
        action_previews=(action_preview,),
        policy=policy,
    )
    payload = workbench_to_dict(packet)
    html = render_collaborative_workbench_html(packet)

    assert packet.note_panel is not None
    assert packet.note_panel.backlink_count == 0
    assert packet.graph_panel is not None
    assert packet.graph_panel.provider_id == "sophiagraph"
    assert packet.review_inbox.pending_count == 3
    assert packet.publish is not None
    assert packet.publish.included_count == 2
    assert payload["state"]["selected_record_id"] == "note-1"
    assert "workspace-main Workbench" in html
    assert "GraphFakos View" in html
    assert "graphfakos" in html.lower()
    assert "human review required" in html


def test_workbench_blocks_unauthorized_workspace_action() -> None:
    decision = evaluate_workspace_action(
        (
            WorkspaceRoleBinding(
                workspace_id="workspace-main",
                actor_id="viewer",
                role="viewer",
                namespace=_ns(),
            ),
        ),
        WorkspaceActionRequest(
            workspace_id="workspace-main",
            actor_id="viewer",
            action="apply",
            target_id="note-1",
        ),
    )

    preview = preview_workbench_action(
        WorkbenchActionRequest(
            action="save_note",
            target_id="note-1",
            actor_id="viewer",
            workspace_id="workspace-main",
        ),
        gate=decision,
    )

    assert preview.status == "blocked"
    assert preview.reason == "permission_denied"
    assert preview.allowed is False


def test_workbench_surface_avoids_semantic_runtime_shortcuts() -> None:
    source_paths = [
        Path("src/sophiagraph/workbench.py"),
        Path("src/sophiagraph/ui/workbench.py"),
    ]
    forbidden = {
        "auto_merge",
        "infer_semantic",
        "generate_summary",
        "text_to_cypher",
        "nl_to_query",
        "auto_promote",
    }
    for path in source_paths:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        assert names.isdisjoint(forbidden)
        for token in forbidden:
            assert token not in source
