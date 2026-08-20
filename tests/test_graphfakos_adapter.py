from __future__ import annotations

import pytest
from graphfakos import (
    FileGraphProvider,
    GraphFakosGraphAction,
    GraphFakosKnowledgeCapture,
    GraphFakosRequest,
    render_static_html,
)
from graphfakos.artifacts import write_graph_artifact
from graphfakos.provider import load_provider_graph

from sophiagraph.models import (
    KnowledgeDocumentBlock,
    MemoryCandidate,
    MemoryNamespace,
    MemoryRecord,
    StructuralLink,
)
from sophiagraph.storage import SophiaGraphMemoryStore
from sophiagraph.ui.graphfakos_adapter import SophiagraphViewerProvider
from sophiagraph.ui.preview import UiPreviewRequest, handle_ui_preview_action
from sophiagraph.workspace import initialize_workspace, open_workspace_store


def test_sophiagraph_adapter_returns_second_brain_graphfakos_graph() -> None:
    namespace = MemoryNamespace(agent_id="codex", graph_id="main")
    store = SophiaGraphMemoryStore()
    store.put_record(
        MemoryRecord(
            id="auth",
            scope="agent:codex",
            type="fact",
            key="auth",
            title="Auth Decision",
            content={"text": "Use JWT auth for the operator console."},
            namespace=namespace,
            source="validated",
            confidence=0.91,
            created_at="2026-06-22T00:00:00+00:00",
            updated_at="2026-06-22T00:00:00+00:00",
        )
    )
    store.put_document_blocks(
        "auth",
        [
            KnowledgeDocumentBlock(
                block_id="block-auth",
                document_id="doc-auth",
                record_id="auth",
                block_type="heading",
                anchor="auth-heading",
                excerpt="JWT auth source excerpt.",
            )
        ],
    )
    store.put_candidate(
        MemoryCandidate(
            candidate_id="candidate-auth-rule",
            session_id="session-codex",
            proposed_scope="agent:codex",
            type="fact",
            title="Auth Rule Candidate",
            content={"text": "JWT auth should be promoted when confirmed."},
            source="agent_inferred",
            confidence=0.82,
            status="proposed",
            namespace=namespace,
            claim_key="auth.jwt",
            polarity="asserts",
            source_class="user_input",
            created_at="2026-06-22T00:05:00+00:00",
            updated_at="2026-06-22T00:05:00+00:00",
        )
    )
    store.put_record(
        MemoryRecord(
            id="refresh",
            scope="agent:codex",
            type="fact",
            key="refresh",
            title="Refresh Plan",
            content={"text": "Refresh visual graph previews after sync."},
            namespace=namespace,
            created_at="2026-06-22T00:00:00+00:00",
            updated_at="2026-06-22T00:00:00+00:00",
        )
    )
    store.put_link(
        StructuralLink(
            link_id="link-auth-refresh",
            source_record_id="auth",
            target_record_id="refresh",
            raw_target="Refresh Plan",
            link_kind="wikilink",
            resolution_status="resolved",
            namespace=namespace,
            relation_type="supports",
            created_at="2026-06-22T00:00:00+00:00",
        )
    )

    provider = SophiagraphViewerProvider(
        store=store,
        scope="agent:codex",
        namespace=namespace,
    )
    graphfakos_conformance = pytest.importorskip("graphfakos.testing.conformance")
    result = graphfakos_conformance.assert_provider_conformance(
        graphfakos_conformance.GraphFakosProviderConformanceCase(
            provider=provider,
            request=GraphFakosRequest(),
            expected_role="memory",
            expected_provider="Sophiagraph",
            expected_node="Auth Decision",
            expected_edge="supports",
            required_capabilities=(
                "search",
                "neighborhood",
                "path",
                "provenance",
                "timeline",
                "provider_status",
                "context_preview",
                "durable_memory",
                "static_export",
                "local_preview",
            ),
        )
    )
    graph = result.graph

    assert graph.provider_id == "sophiagraph"
    assert graph.graph_role == "memory"
    assert any(node.label == "Auth Decision" for node in graph.nodes)
    record = next(node for node in graph.nodes if node.label == "Auth Decision")
    assert record.provider_payload["record_id"] == "auth"
    assert record.provider_payload["scope"] == "agent:codex"
    assert record.provider_payload["namespace"] == namespace.as_dict()
    schemas = graph.provider_payload["inspector_schemas"]
    record_schema = next(
        schema for schema in schemas if schema["node_kind"] == "memory_record"
    )
    assert any(field["key"] == "scope" for field in record_schema["fields"])
    assert any(node.kind == "memory_candidate" for node in graph.nodes)
    candidate = next(node for node in graph.nodes if node.kind == "memory_candidate")
    candidate_schema = next(
        schema for schema in schemas if schema["node_kind"] == "memory_candidate"
    )
    assert any(field["key"] == "status" for field in candidate_schema["fields"])
    assert candidate.provider_payload["candidate_id"] == "candidate-auth-rule"
    assert candidate.provider_payload["claim_key"] == "auth.jwt"
    assert candidate.provider_payload["polarity"] == "asserts"
    assert candidate.provider_payload["source_class"] == "user_input"
    assert "proposed" in candidate.tags
    assert any(edge.kind == "supports" for edge in graph.edges)
    assert any(edge.kind == "promote_candidate" for edge in graph.edges)
    assert graph.citations
    assert graph.provenance


def test_sophiagraph_adapter_artifact_round_trip_matches_loaded_graph(tmp_path) -> None:
    namespace = MemoryNamespace(agent_id="codex", graph_id="main")
    store = SophiaGraphMemoryStore()
    store.put_record(
        MemoryRecord(
            id="auth",
            scope="agent:codex",
            type="fact",
            key="auth",
            title="Auth Decision",
            content={"text": "Use JWT auth for the operator console."},
            namespace=namespace,
            source="validated",
            confidence=0.91,
            created_at="2026-06-22T00:00:00+00:00",
            updated_at="2026-06-22T00:00:00+00:00",
        )
    )
    provider = SophiagraphViewerProvider(
        store=store,
        scope="agent:codex",
        namespace=namespace,
    )
    request = GraphFakosRequest(screen="provider_status")
    graph = load_provider_graph(provider, request)
    artifact_path = tmp_path / "sophiagraph-artifact.json"
    write_graph_artifact(graph, str(artifact_path))
    replay_provider = FileGraphProvider(str(artifact_path))
    replay_graph = load_provider_graph(replay_provider, request)
    replay_html = render_static_html(replay_provider, request)

    assert replay_graph.to_dict() == graph.to_dict()
    assert "Sophiagraph Durable Memory" in replay_html
    assert "Auth Decision" in replay_html


def test_sophiagraph_adapter_executes_candidate_action_through_provider() -> None:
    namespace = MemoryNamespace(agent_id="codex", graph_id="main")
    store = SophiaGraphMemoryStore()
    store.put_candidate(
        MemoryCandidate(
            candidate_id="candidate-action",
            session_id="session-codex",
            proposed_scope="agent:codex",
            type="fact",
            title="Action Candidate",
            content={"text": "Review from GraphFakos."},
            status="proposed",
            namespace=namespace,
            created_at="2026-06-22T00:00:00+00:00",
            updated_at="2026-06-22T00:00:00+00:00",
        )
    )
    provider = SophiagraphViewerProvider(
        store=store,
        scope="agent:codex",
        namespace=namespace,
        principal_id="local-operator",
    )

    status = provider.submit_graph_action(
        GraphFakosGraphAction(
            action_id="gf-approve",
            action_type="approve_candidate",
            target_id="candidate:candidate-action",
            provider_payload={"expected_updated_at": "2026-06-22T00:00:00+00:00"},
        )
    )

    assert status.status == "applied"
    assert status.provider_payload["reason_code"] == "applied"
    assert status.provider_payload["audit_refs"][0] == "action_journal:gf-approve"
    assert store.get_candidate("candidate-action").status == "approved"


def test_sophiagraph_adapter_refuses_unknown_and_impersonating_actions() -> None:
    namespace = MemoryNamespace(agent_id="codex", graph_id="main")
    store = SophiaGraphMemoryStore()
    store.put_candidate(
        MemoryCandidate(
            candidate_id="candidate-deny",
            session_id="session-codex",
            proposed_scope="agent:codex",
            type="fact",
            content={"text": "Do not trust browser identity."},
            namespace=namespace,
        )
    )
    provider = SophiagraphViewerProvider(
        store=store,
        scope="agent:codex",
        namespace=namespace,
        principal_id="local-operator",
    )

    unknown = provider.submit_graph_action(
        GraphFakosGraphAction(
            action_id="gf-unknown",
            action_type="merge_alias",
            target_id="candidate:candidate-deny",
        )
    )
    denied = provider.submit_graph_action(
        GraphFakosGraphAction(
            action_id="gf-denied",
            action_type="approve_candidate",
            target_id="candidate:candidate-deny",
            provider_payload={"principal_id": "mallory"},
        )
    )

    assert unknown.status == "unsupported"
    assert denied.status == "blocked"
    assert denied.provider_payload["reason_code"] == "impersonation_denied"
    assert store.get_candidate("candidate-deny").status == "proposed"


def test_sophiagraph_adapter_capture_saves_file_primary_note(tmp_path) -> None:
    namespace = MemoryNamespace(agent_id="codex", graph_id="main")
    workspace_root = tmp_path / "workspace"
    source_root = tmp_path / "source"
    initialize_workspace(
        workspace_root,
        scope="agent:codex",
        namespace=namespace,
        overwrite=True,
    )
    provider = SophiagraphViewerProvider(
        store=open_workspace_store(workspace_root),
        scope="agent:codex",
        namespace=namespace,
        principal_id="local-operator",
        workspace_id=str(workspace_root),
        workspace_root=str(workspace_root),
        source_root=str(source_root),
    )

    result = provider.capture_knowledge(
        GraphFakosKnowledgeCapture(
            text="Captured from GraphFakos.",
            tags=("capture",),
            provider_payload={
                "action_id": "capture-note",
                "note_key": "capture-note",
                "title": "Capture Note",
                "relative_path": "notes/capture-note.md",
            },
        )
    )

    assert result["ok"] is True
    assert result["status"]["status"] == "applied"
    assert (source_root / "notes" / "capture-note.md").exists()


def test_ui_preview_action_handler_uses_live_workspace_context(tmp_path) -> None:
    namespace = MemoryNamespace(agent_id="codex", graph_id="main")
    workspace_root = tmp_path / "workspace"
    source_root = tmp_path / "source"
    initialize_workspace(
        workspace_root,
        scope="agent:codex",
        namespace=namespace,
        overwrite=True,
    )
    store = open_workspace_store(workspace_root)
    store.put_candidate(
        MemoryCandidate(
            candidate_id="candidate-handler",
            session_id="session-codex",
            proposed_scope="agent:codex",
            type="fact",
            content={"text": "Handler candidate."},
            namespace=namespace,
        )
    )
    response = handle_ui_preview_action(
        UiPreviewRequest(
            workspace=str(workspace_root),
            source_root=str(source_root),
        ),
        "/api/action",
        GraphFakosGraphAction(
            action_id="handler-approve",
            action_type="approve_candidate",
            target_id="candidate:candidate-handler",
        ).to_dict(),
    )

    assert response["ok"] is True
    assert response["status"]["status"] == "applied"
    assert (
        open_workspace_store(workspace_root).get_candidate("candidate-handler").status
        == "approved"
    )
