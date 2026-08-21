"""Local UI workbench memory-review walkthrough."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile

from graphfakos import GraphFakosGraphAction, GraphFakosRequest
from graphfakos.artifacts import write_graph_artifact
from graphfakos.provider import load_provider_graph
from graphfakos.static import render_static_html

from sophiagraph.models import (
    ArtifactRef,
    KnowledgeDocumentBlock,
    MemoryCandidate,
    MemoryNamespace,
    MemoryRecord,
    StructuralLink,
)
from sophiagraph.storage import SophiaGraphMemoryStore
from sophiagraph.ui.graphfakos_adapter import SophiagraphViewerProvider

SCOPE = "agent:demo"
AUTH_RECORD_ID = "auth-decision"
REFRESH_RECORD_ID = "refresh-plan"
CANDIDATE_ID = "candidate-graph-navigation"
OPERATOR_NOTE_REF = "artifact:operator-note"
STAMP = "2026-06-22T00:00:00+00:00"
REVIEW_STAMP = "2026-06-22T00:05:00+00:00"


def run_example(root: str | Path) -> dict[str, object]:
    root = Path(root)
    namespace = MemoryNamespace(agent_id="demo", graph_id="main")
    store = SophiaGraphMemoryStore()
    seed_review_store(store, namespace=namespace)
    provider = SophiagraphViewerProvider(
        store=store,
        scope=SCOPE,
        namespace=namespace,
        principal_id="local-operator",
    )
    request = GraphFakosRequest(screen="explore", focus_node_id=AUTH_RECORD_ID)
    graph = load_provider_graph(provider, request)
    html = render_static_html(provider, request)
    artifact_path = root / "sophiagraph-artifact.json"
    write_graph_artifact(graph, str(artifact_path))

    approve = provider.submit_graph_action(
        GraphFakosGraphAction(
            action_id="approve-demo-candidate",
            action_type="approve_candidate",
            target_id=f"candidate:{CANDIDATE_ID}",
        )
    )
    promote = provider.submit_graph_action(
        GraphFakosGraphAction(
            action_id="promote-demo-candidate",
            action_type="promote_candidate",
            target_id=f"candidate:{CANDIDATE_ID}",
            provider_payload={"evidence_refs": [OPERATOR_NOTE_REF]},
        )
    )
    reviewed_candidate = store.get_candidate(CANDIDATE_ID)
    promoted_payload = promote.provider_payload["result"]["provider_payload"]
    promoted_record_id = str(promoted_payload["record_id"])
    return {
        "provider_id": graph.provider_id,
        "graph_role": graph.graph_role,
        "node_count": len(graph.nodes),
        "edge_count": len(graph.edges),
        "candidate_status": reviewed_candidate.status if reviewed_candidate else "",
        "promoted_record_exists": store.get_record(promoted_record_id) is not None,
        "approve_status": approve.status,
        "promote_status": promote.status,
        "artifact_written": artifact_path.exists(),
        "html_mentions_candidate": "Navigation Candidate" in html,
    }


def seed_review_store(
    store: SophiaGraphMemoryStore,
    *,
    namespace: MemoryNamespace,
) -> None:
    auth = MemoryRecord(
        id=AUTH_RECORD_ID,
        scope=SCOPE,
        type="fact",
        key="auth.decision",
        title="Auth Decision",
        content={"text": "Use JWT auth for the operator console."},
        namespace=namespace,
        source="validated",
        confidence=0.91,
        tier="archival",
        created_at=STAMP,
        updated_at=STAMP,
        evidence_refs=[operator_note_ref()],
    )
    refresh = MemoryRecord(
        id=REFRESH_RECORD_ID,
        scope=SCOPE,
        type="procedure",
        key="ui.refresh",
        title="Preview Refresh Plan",
        content={"text": "Refresh graph previews after local workspace sync."},
        namespace=namespace,
        source="agent_inferred",
        confidence=0.83,
        tier="working",
        created_at=STAMP,
        updated_at=STAMP,
    )
    store.put_record(auth)
    store.put_record(refresh)
    store.put_link(
        StructuralLink(
            link_id="link-auth-refresh",
            source_record_id=auth.id,
            target_record_id=refresh.id,
            raw_target=refresh.title or refresh.id,
            link_kind="wikilink",
            resolution_status="resolved",
            namespace=namespace,
            relation_type="supports",
            created_at=STAMP,
        )
    )
    store.put_document_blocks(
        auth.id,
        [
            KnowledgeDocumentBlock(
                block_id="block-auth",
                document_id="docs/operator.md",
                record_id=auth.id,
                block_type="heading",
                anchor="auth",
                excerpt="JWT auth source excerpt.",
            )
        ],
    )
    store.put_candidate(
        MemoryCandidate(
            candidate_id=CANDIDATE_ID,
            session_id="session-demo",
            proposed_scope=SCOPE,
            type="fact",
            title="Navigation Candidate",
            content={
                "text": "Show provenance, trust, and candidate state in the graph inspector."
            },
            source="agent_inferred",
            confidence=0.86,
            status="proposed",
            namespace=namespace,
            claim_key="ui.graph.inspector",
            polarity="asserts",
            source_class="user_input",
            evidence_refs=[operator_note_ref()],
            created_at=REVIEW_STAMP,
            updated_at=REVIEW_STAMP,
        )
    )


def operator_note_ref() -> ArtifactRef:
    return ArtifactRef(
        ref=OPERATOR_NOTE_REF,
        mime="text/markdown",
        sha256="demo-auth-note",
        size_bytes=128,
        label="operator note",
    )


def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="sophiagraph-ui-example-"))
    print(json.dumps(run_example(root), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
