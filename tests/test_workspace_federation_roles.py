from __future__ import annotations

from sophiagraph import (
    FederatedWorkspaceQuery,
    FederatedWorkspaceRef,
    KnowledgeExplorerRequest,
    MemoryNamespace,
    MemoryRecord,
    SophiaGraphMemoryStore,
    WorkspaceActionRequest,
    WorkspaceReviewDecision,
    WorkspaceRoleBinding,
    apply_workspace_review_decision,
    create_workspace_review_request,
    evaluate_workspace_action,
    run_federated_workspace_query,
)


def _record(
    record_id: str,
    scope: str,
    text: str,
    *,
    namespace: MemoryNamespace | None = None,
) -> MemoryRecord:
    return MemoryRecord(
        id=record_id,
        scope=scope,
        type="fact",
        content=text,
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
        title=text,
        namespace=namespace,
    )


def test_federated_workspace_query_preserves_workspace_citations() -> None:
    namespace_a = MemoryNamespace(project_id="alpha")
    namespace_b = MemoryNamespace(project_id="beta")
    store_a = SophiaGraphMemoryStore()
    store_b = SophiaGraphMemoryStore()
    store_a.put_record(
        _record("shared", "project:alpha", "Roadmap", namespace=namespace_a)
    )
    store_b.put_record(
        _record("shared", "project:beta", "Roadmap", namespace=namespace_b)
    )
    store_b.put_record(
        _record("beta-only", "project:beta", "Budget", namespace=namespace_b)
    )

    result = run_federated_workspace_query(
        FederatedWorkspaceQuery(
            workspaces=(
                FederatedWorkspaceRef(
                    workspace_id="alpha",
                    store=store_a,
                    scope="project:alpha",
                    namespace=namespace_a,
                ),
                FederatedWorkspaceRef(
                    workspace_id="beta",
                    store=store_b,
                    scope="project:beta",
                    namespace=namespace_b,
                ),
            ),
            request=KnowledgeExplorerRequest(
                scopes=["project:alpha"],
                query="Roadmap",
                include_graph=False,
                include_backlinks=False,
                include_outgoing_links=False,
                include_paths=False,
            ),
        )
    )

    assert [hit.workspace_id for hit in result.hits] == ["alpha"]
    assert result.citations[0].workspace_id == "alpha"
    assert result.citations[0].namespace == namespace_a
    assert any(item.reason == "duplicate" for item in result.omissions)


def test_workspace_roles_gate_actions_and_emit_review_audit_event() -> None:
    bindings = (
        WorkspaceRoleBinding(
            workspace_id="workspace-1",
            actor_id="reader",
            role="viewer",
        ),
        WorkspaceRoleBinding(
            workspace_id="workspace-1",
            actor_id="maintainer",
            role="maintainer",
        ),
    )

    denied = evaluate_workspace_action(
        bindings,
        WorkspaceActionRequest(
            workspace_id="workspace-1",
            actor_id="reader",
            action="apply",
            target_id="rec-1",
        ),
    )
    allowed = evaluate_workspace_action(
        bindings,
        WorkspaceActionRequest(
            workspace_id="workspace-1",
            actor_id="maintainer",
            action="apply",
            target_id="rec-1",
        ),
    )

    assert denied.allowed is False
    assert denied.reason == "permission_denied"
    assert allowed.allowed is True
    review = create_workspace_review_request(
        workspace_id="workspace-1",
        proposer_id="reader",
        target_id="rec-1",
    )
    event = apply_workspace_review_decision(
        review,
        WorkspaceReviewDecision(
            review_id=review.review_id,
            reviewer_id="maintainer",
            decision="approved",
        ),
    )
    assert event.event_type == "workspace.review_decision"
    assert event.target_kind == "workspace_review"
    assert event.details["reviewer_id"] == "maintainer"
