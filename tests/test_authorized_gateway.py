from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from sophiagraph import (
    FederatedWorkspaceQuery,
    FederatedWorkspaceRef,
    KnowledgeExplorerRequest,
    MemoryCandidate,
    MemoryNamespace,
    MemoryRecord,
    StructuralLink,
    WorkspaceActionRequest,
    WorkspaceRoleBinding,
    evaluate_workspace_action,
)
from sophiagraph.access import (
    AccessConstraint,
    AuthorizedSophiaGraphGateway,
    DelegatedMemoryAccessDeniedError,
    DelegationMemoryGrant,
    MemoryAccessTelemetryEvent,
    MemoryAccessContext,
    MemoryAccessRequest,
)
from sophiagraph.query import (
    CandidateListOptions,
    ListQueryOptions,
    LocalGraphOptions,
    SearchQueryOptions,
)
from sophiagraph.storage import SophiaGraphMemoryStore, SophiaGraphSqliteStore
from sophiagraph.workspace_roles import delegated_scratch_namespace

_GATEWAY_TEST_NOW = datetime.now(UTC)


class Resolver:
    def __init__(self, grant: DelegationMemoryGrant) -> None:
        self.grant = grant
        self.calls = 0

    def resolve_grant(self, grant_id, *, context, operation):
        self.calls += 1
        return self.grant if grant_id == self.grant.grant_id else None


def _namespace(agent_id: str) -> MemoryNamespace:
    return MemoryNamespace(
        tenant_id="tenant",
        user_id="user",
        agent_id=agent_id,
        project_id="project",
        graph_id="main",
    )


def _record(record_id: str, namespace: MemoryNamespace) -> MemoryRecord:
    return MemoryRecord(
        id=record_id,
        scope=f"agent:{namespace.agent_id}",
        type="fact",
        content={"text": f"content {record_id}"},
        created_at="2026-08-06T00:00:00+00:00",
        updated_at="2026-08-06T00:00:00+00:00",
        namespace=namespace,
    )


def _grant(namespace: MemoryNamespace, **overrides) -> DelegationMemoryGrant:
    issued_at = _GATEWAY_TEST_NOW - timedelta(days=1)
    expires_at = _GATEWAY_TEST_NOW + timedelta(days=365)
    values = {
        "grant_id": "grant-1",
        "issuer_authority": "openminion-policy",
        "audience": "sophiagraph",
        "delegator_agent_id": "parent",
        "subject_agent_id": "child",
        "parent_run_id": "parent-run",
        "child_run_id": "child-run",
        "trace_parent_id": "trace-1",
        "namespaces": (namespace,),
        "workspace_ids": ("workspace-1",),
        "operations": ("read", "export"),
        "issued_at": issued_at.isoformat(),
        "expires_at": expires_at.isoformat(),
        "max_results": 2,
        "max_context_tokens": 1000,
    }
    values.update(overrides)
    return DelegationMemoryGrant(**values)


def _context(namespace: MemoryNamespace) -> MemoryAccessContext:
    return MemoryAccessContext(
        principal_id="child-principal",
        audience="sophiagraph",
        subject_agent_id="child",
        parent_run_id="parent-run",
        child_run_id="child-run",
        trace_parent_id="trace-1",
        delegated=True,
        constraints=(
            AccessConstraint(
                mode="allowlist",
                namespaces=(namespace,),
                workspace_ids=("workspace-1",),
                operations=("read", "export"),
                max_results=2,
            ),
        ),
    )


def _request(operation="read") -> MemoryAccessRequest:
    return MemoryAccessRequest(
        operation=operation,
        namespaces=(_namespace("child"),),
        workspace_ids=("workspace-1",),
        grant_id="grant-1",
        max_results=10,
    )


@pytest.fixture(params=["memory", "sqlite"])
def store(request, tmp_path):
    if request.param == "memory":
        return SophiaGraphMemoryStore()
    return SophiaGraphSqliteStore(tmp_path / "gateway.sqlite3")


def test_direct_id_list_search_and_pagination_are_namespace_bounded(store) -> None:
    child = _namespace("child")
    sibling = _namespace("sibling")
    for record_id, namespace in (
        ("allowed-1", child),
        ("allowed-2", child),
        ("allowed-3", child),
        ("hidden", sibling),
    ):
        store.put_record(_record(record_id, namespace))
    resolver = Resolver(_grant(child))
    gateway = AuthorizedSophiaGraphGateway(store, resolver=resolver)
    context = _context(child)
    request = _request()

    assert gateway.get_record("hidden", context=context, request=request) is None
    assert gateway.get_record("missing", context=context, request=request) is None
    listed = gateway.list_records(
        ListQueryOptions(scopes=["agent:child", "agent:sibling"], limit=10),
        context=context,
        request=request,
    )
    searched = gateway.search_records(
        SearchQueryOptions(
            query="content", scopes=["agent:child", "agent:sibling"], limit=10
        ),
        context=context,
        request=request,
    )
    second_page = gateway.list_records(
        ListQueryOptions(scopes=["agent:child"], limit=2, offset=2),
        context=context,
        request=request,
    )
    assert len(listed) == len(searched) == 2
    assert {item.id for item in listed}.issubset(
        {"allowed-1", "allowed-2", "allowed-3"}
    )
    assert second_page == []
    assert resolver.calls >= 5


def test_hidden_graph_endpoint_cannot_become_an_observable_bridge(store) -> None:
    child = _namespace("child")
    sibling = _namespace("sibling")
    store.put_record(_record("root", child))
    store.put_record(_record("hidden", sibling))
    store.put_record(_record("visible", child))
    store.put_link(
        StructuralLink(
            link_id="root-hidden",
            source_record_id="root",
            target_record_id="hidden",
            raw_target="hidden",
            link_kind="wikilink",
            resolution_status="resolved",
            namespace=child,
        )
    )
    store.put_link(
        StructuralLink(
            link_id="hidden-visible",
            source_record_id="hidden",
            target_record_id="visible",
            raw_target="visible",
            link_kind="wikilink",
            resolution_status="resolved",
            namespace=sibling,
        )
    )
    gateway = AuthorizedSophiaGraphGateway(store, resolver=Resolver(_grant(child)))
    graph = gateway.get_local_graph(
        LocalGraphOptions(record_id="root", depth=2, max_nodes=10, max_edges=10),
        context=_context(child),
        request=_request(),
    )
    assert [node.record_id for node in graph.nodes] == ["root"]
    assert graph.edges == []


def test_federation_intersects_workspaces_and_global_result_budget(store) -> None:
    child = _namespace("child")
    allowed_store = SophiaGraphMemoryStore()
    hidden_store = SophiaGraphMemoryStore()
    for index in range(3):
        allowed_store.put_record(_record(f"allowed-{index}", child))
        hidden_store.put_record(_record(f"hidden-{index}", child))
    gateway = AuthorizedSophiaGraphGateway(store, resolver=Resolver(_grant(child)))
    result = gateway.run_federated_query(
        FederatedWorkspaceQuery(
            workspaces=(
                FederatedWorkspaceRef(
                    workspace_id="workspace-1",
                    store=allowed_store,
                    namespace=child,
                ),
                FederatedWorkspaceRef(
                    workspace_id="workspace-hidden",
                    store=hidden_store,
                    namespace=child,
                ),
            ),
            request=KnowledgeExplorerRequest(
                scopes=["agent:child"],
                query="content",
                include_graph=False,
                include_backlinks=False,
                include_outgoing_links=False,
                include_paths=False,
                limit=10,
            ),
            limit=10,
        ),
        context=_context(child),
        request=_request(),
    )
    assert len(result.hits) == 2
    assert {hit.workspace_id for hit in result.hits} == {"workspace-1"}
    assert {citation.workspace_id for citation in result.citations} == {"workspace-1"}


def test_denied_mutation_raises_typed_error(store) -> None:
    child = _namespace("child")
    gateway = AuthorizedSophiaGraphGateway(store, resolver=Resolver(_grant(child)))
    with pytest.raises(DelegatedMemoryAccessDeniedError) as exc:
        gateway.put_record(
            _record("new", child),
            context=_context(child),
            request=_request(operation="mutate"),
        )
    assert exc.value.code == "MEMORY_DELEGATED_ACCESS_DENIED"


def test_workspace_role_binding_is_namespace_scoped() -> None:
    child = _namespace("child")
    sibling = _namespace("sibling")
    binding = WorkspaceRoleBinding(
        workspace_id="workspace-1",
        actor_id="child",
        role="viewer",
        namespace=child,
    )
    allowed = evaluate_workspace_action(
        (binding,),
        WorkspaceActionRequest(
            workspace_id="workspace-1",
            actor_id="child",
            action="read",
            target_id="allowed",
            namespace=child,
        ),
    )
    denied = evaluate_workspace_action(
        (binding,),
        WorkspaceActionRequest(
            workspace_id="workspace-1",
            actor_id="child",
            action="read",
            target_id="hidden",
            namespace=sibling,
        ),
    )
    assert allowed.allowed
    assert not denied.allowed


def test_delegated_scratch_namespaces_isolate_siblings() -> None:
    first = delegated_scratch_namespace(
        child_agent_id="child-a",
        context_id="context-a",
        project_id="project",
    )
    second = delegated_scratch_namespace(
        child_agent_id="child-b",
        context_id="context-b",
        project_id="project",
    )
    assert not first.matches(second)
    assert first.conversation_id == "context-a"
    assert first.agent_id == "child-a"


def test_candidate_namespace_filter_applies_before_limit(store) -> None:
    child = _namespace("child")
    sibling = _namespace("sibling")
    for index in range(3):
        store.put_candidate(
            MemoryCandidate(
                candidate_id=f"hidden-{index}",
                session_id="session",
                proposed_scope="agent:sibling",
                type="fact",
                content={"text": "hidden"},
                namespace=sibling,
                updated_at=f"2026-08-06T00:00:0{9 - index}+00:00",
            )
        )
    store.put_candidate(
        MemoryCandidate(
            candidate_id="visible",
            session_id="session",
            proposed_scope="agent:child",
            type="fact",
            content={"text": "visible"},
            namespace=child,
            updated_at="2026-08-06T00:00:01+00:00",
        )
    )
    gateway = AuthorizedSophiaGraphGateway(store, resolver=Resolver(_grant(child)))
    candidates = gateway.list_candidates(
        CandidateListOptions(limit=1),
        context=_context(child),
        request=_request(),
    )
    assert [candidate.candidate_id for candidate in candidates] == ["visible"]


def test_direct_id_denial_records_sanitized_audit_and_closed_telemetry(store) -> None:
    child = _namespace("child")
    store.put_record(_record("hidden", _namespace("sibling")))
    audit_events = []
    telemetry_events: list[MemoryAccessTelemetryEvent] = []
    gateway = AuthorizedSophiaGraphGateway(
        store,
        resolver=Resolver(_grant(child)),
        audit_recorder=audit_events.append,
        telemetry_recorder=telemetry_events.append,
    )
    assert (
        gateway.get_record("hidden", context=_context(child), request=_request())
        is None
    )
    assert audit_events[-1].details["reason"] == "selector_denied"
    assert "hidden" not in repr(audit_events[-1].details)
    assert "child-principal" not in repr(audit_events[-1].details)
    assert "grant-1" not in repr(audit_events[-1].details)
    assert telemetry_events[-1].outcome == "deny"
    assert not any(
        forbidden in telemetry_events[-1].__dataclass_fields__
        for forbidden in ("principal_id", "grant_id", "record_id", "query", "token")
    )
