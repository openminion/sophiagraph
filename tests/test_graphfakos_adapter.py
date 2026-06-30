from __future__ import annotations

from graphfakos import FileGraphProvider, GraphFakosRequest, render_static_html
from graphfakos.artifacts import write_graph_artifact
from graphfakos.provider import load_provider_graph
from graphfakos.testing import assert_graph_viewer_contract

from sophiagraph.models import (
    KnowledgeDocumentBlock,
    MemoryCandidate,
    MemoryNamespace,
    MemoryRecord,
    StructuralLink,
)
from sophiagraph.storage import SophiaGraphMemoryStore
from sophiagraph.ui.graphfakos_adapter import SophiagraphViewerProvider


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
    graph = provider.load_graph(GraphFakosRequest())
    html = render_static_html(provider, GraphFakosRequest())

    assert graph.provider_id == "sophiagraph"
    assert graph.graph_role == "memory"
    assert any(node.label == "Auth Decision" for node in graph.nodes)
    assert any(node.kind == "memory_candidate" for node in graph.nodes)
    candidate = next(node for node in graph.nodes if node.kind == "memory_candidate")
    assert candidate.provider_payload["claim_key"] == "auth.jwt"
    assert candidate.provider_payload["polarity"] == "asserts"
    assert candidate.provider_payload["source_class"] == "user_input"
    assert "proposed" in candidate.tags
    assert any(edge.kind == "supports" for edge in graph.edges)
    assert any(edge.kind == "promote_candidate" for edge in graph.edges)
    assert graph.citations
    assert graph.provenance
    assert_graph_viewer_contract(
        html,
        expected_role="memory",
        expected_provider="Sophiagraph",
        expected_node="Auth Decision",
        expected_edge="supports",
    )


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
