from __future__ import annotations

import json

from sophiagraph.access import DelegationMemoryGrant
from sophiagraph.models import MemoryNamespace, MemoryRecord
from sophiagraph.server.backend import BackendConfig, build_wired_registry
from sophiagraph.server.deployment import DeploymentProfile
from sophiagraph.server.http import SophiagraphHttpService
from sophiagraph.server.runtime_hardening import (
    RuntimePolicyEngine,
    ServerAuthConfig,
    ServerPrincipal,
)
from sophiagraph.server.server import ServerInfo, dispatch
from sophiagraph.storage import SophiaGraphMemoryStore


class _Resolver:
    def __init__(self, grant: DelegationMemoryGrant) -> None:
        self.grant = grant
        self.active = True
        self.calls = 0

    def resolve_grant(self, grant_id, *, context, operation):
        self.calls += 1
        if not self.active or grant_id != self.grant.grant_id:
            return None
        return self.grant


def _namespace(agent_id: str) -> MemoryNamespace:
    return MemoryNamespace(agent_id=agent_id, project_id="project", graph_id="main")


def _grant(namespace: MemoryNamespace) -> DelegationMemoryGrant:
    return DelegationMemoryGrant(
        grant_id="grant-http",
        issuer_authority="openminion-policy",
        audience="sophiagraph",
        delegator_agent_id="parent",
        subject_agent_id="child",
        parent_run_id="parent-run",
        child_run_id="child-run",
        trace_parent_id="trace",
        namespaces=(namespace,),
        workspace_ids=("workspace",),
        operations=("read",),
        issued_at="2026-08-06T00:00:00+00:00",
        expires_at="2099-08-07T00:00:00+00:00",
        max_results=10,
        max_context_tokens=1000,
    )


def _record(record_id: str, namespace: MemoryNamespace) -> MemoryRecord:
    return MemoryRecord(
        id=record_id,
        scope=f"agent:{namespace.agent_id}",
        type="fact",
        content={"text": record_id},
        namespace=namespace,
        created_at="2026-08-06T00:00:00+00:00",
        updated_at="2026-08-06T00:00:00+00:00",
    )


def _runtime(namespace: MemoryNamespace) -> RuntimePolicyEngine:
    token = "restricted-token"
    return RuntimePolicyEngine(
        auth=ServerAuthConfig(
            mode="static_bearer",
            static_tokens=(token,),
            token_principals={
                token: ServerPrincipal(
                    principal_id="child-principal",
                    access_mode="allowlist",
                    allowed_namespaces=(
                        "|".join(
                            f"{key}={value}"
                            for key, value in namespace.as_dict().items()
                        ),
                    ),
                    allowed_workspaces=("workspace",),
                )
            },
        ),
        deployment_profile=DeploymentProfile(
            allowed_transports=("http", "stdio"),
            require_request_id=False,
            require_auth=True,
        ),
    )


def _headers(**overrides: str) -> dict[str, str]:
    values = {
        "Authorization": "Bearer restricted-token",
        "X-Sophiagraph-Grant-Id": "grant-http",
        "X-Sophiagraph-Subject-Agent": "child",
        "X-Sophiagraph-Parent-Run": "parent-run",
        "X-Sophiagraph-Child-Run": "child-run",
        "X-Sophiagraph-Trace-Parent": "trace",
        "X-Sophiagraph-Audience": "attacker-controlled",
    }
    values.update(overrides)
    return values


def test_http_delegated_direct_id_is_fail_closed_and_refreshes_resolver() -> None:
    allowed = _namespace("child")
    store = SophiaGraphMemoryStore()
    store.put_record(_record("visible", allowed))
    store.put_record(_record("hidden", _namespace("sibling")))
    resolver = _Resolver(_grant(allowed))
    service = SophiagraphHttpService(
        store=store,
        runtime=_runtime(allowed),
        resolver=resolver,
    )

    visible = service.handle("GET", "/v1/knowledge/records/visible", headers=_headers())
    hidden = service.handle("GET", "/v1/knowledge/records/hidden", headers=_headers())
    resolver.active = False
    revoked = service.handle("GET", "/v1/knowledge/records/visible", headers=_headers())
    copied = service.handle(
        "GET",
        "/v1/knowledge/records/visible",
        headers=_headers(**{"X-Sophiagraph-Grant-Id": "copied"}),
    )

    assert visible.payload["record"]["id"] == "visible"
    assert hidden.payload["record"] is None
    assert revoked.payload["record"] is None
    assert copied.payload["record"] is None
    assert resolver.calls == 4


def test_http_delegated_payload_cannot_impersonate_or_write() -> None:
    allowed = _namespace("child")
    resolver = _Resolver(_grant(allowed))
    service = SophiagraphHttpService(
        store=SophiaGraphMemoryStore(),
        runtime=_runtime(allowed),
        resolver=resolver,
    )
    payload = {
        "id": "forbidden-write",
        "scope": "agent:child",
        "type": "fact",
        "content": {"text": "write"},
        "created_at": "2026-08-06T00:00:00+00:00",
        "updated_at": "2026-08-06T00:00:00+00:00",
    }
    response = service.handle(
        "PUT",
        "/v1/knowledge/records/forbidden-write",
        headers=_headers(),
        body=json.dumps(payload).encode(),
    )
    assert response.payload["error"]["code"] == -32031
    assert response.payload["error"]["data"] == {
        "operation": "mutate",
        "reason": "operation_denied",
    }


def test_mcp_delegated_context_uses_gateway_before_disclosure() -> None:
    allowed = _namespace("child")
    store = SophiaGraphMemoryStore()
    store.put_record(_record("visible", allowed))
    store.put_record(_record("hidden", _namespace("sibling")))
    resolver = _Resolver(_grant(allowed))
    runtime = _runtime(allowed)
    registry = build_wired_registry(
        BackendConfig(backend="memory"), store=store, resolver=resolver
    )

    def call(record_id: str):
        return dispatch(
            {
                "jsonrpc": "2.0",
                "id": record_id,
                "method": "tools/call",
                "params": {
                    "name": "knowledge_get_record",
                    "arguments": {"record_id": record_id},
                },
                "meta": {
                    "authorization": "Bearer restricted-token",
                    "grant_id": "grant-http",
                    "subject_agent_id": "child",
                    "parent_run_id": "parent-run",
                    "child_run_id": "child-run",
                    "trace_parent_id": "trace",
                    "audience": "wrong-ignored",
                },
            },
            registry=registry,
            server_info=ServerInfo(),
            runtime=runtime,
        )

    assert call("visible")["result"]["structuredContent"]["record"]["id"] == "visible"
    assert call("hidden")["result"]["structuredContent"]["record"] is None
