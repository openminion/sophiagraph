from __future__ import annotations

import json
from threading import Thread
from typing import Any, Mapping, cast
from urllib.request import urlopen

import pytest

from sophiagraph import ArtifactRef, MemoryCandidate, MemoryNamespace
from sophiagraph.server.contracts import (
    ACTION_UNSUPPORTED_CODE,
    AUTH_DENIED_CODE,
    REQUEST_REJECTED_CODE,
    TOOL_SEMANTIC_ENDPOINT_REFUSED_CODE,
)
from sophiagraph.server.deployment import DeploymentProfile
from sophiagraph.server.http import (
    HttpTransportConfig,
    HttpWorkbenchConfig,
    SophiagraphHttpService,
    make_http_server,
)
from sophiagraph.server.runtime_hardening import (
    QuotaRule,
    RuntimePolicyEngine,
    ServerAuthConfig,
    ServerPrincipal,
)
from sophiagraph.storage import SophiaGraphMemoryStore


def _namespace() -> MemoryNamespace:
    return MemoryNamespace(agent_id="codex", graph_id="main")


def _namespace_key(namespace: MemoryNamespace) -> str:
    return "|".join(f"{key}={value}" for key, value in namespace.as_dict().items())


def _config(**overrides: Any) -> HttpTransportConfig:
    workbench = HttpWorkbenchConfig(
        workspace_id="workspace:local",
        scope="agent:codex",
        namespace=_namespace(),
    )
    values = {"workbench": workbench}
    values.update(overrides)
    return HttpTransportConfig(**values)


def _request(
    service: SophiagraphHttpService,
    method: str,
    path: str,
    payload: Mapping[str, Any] | None = None,
    *,
    headers: Mapping[str, str] | None = None,
):
    body = b"" if payload is None else json.dumps(dict(payload)).encode("utf-8")
    return service.handle(
        method,
        path,
        headers={"X-Request-Id": "req-http", **dict(headers or {})},
        body=body,
    )


def _record_payload(record_id: str) -> dict[str, Any]:
    return {
        "id": record_id,
        "scope": "agent:codex",
        "type": "fact",
        "content": {"text": "HTTP workbench routes are wired."},
        "created_at": "2026-07-17T10:00:00+00:00",
        "updated_at": "2026-07-17T10:00:00+00:00",
    }


def _candidate(candidate_id: str) -> MemoryCandidate:
    return MemoryCandidate(
        candidate_id=candidate_id,
        session_id="session-http",
        proposed_scope="agent:codex",
        type="fact",
        title="HTTP candidate",
        content={"text": "Candidate reachable through HTTP workbench action."},
        evidence_refs=(
            ArtifactRef(
                ref="artifact://http-source",
                mime="text/plain",
                sha256="a" * 64,
                size_bytes=12,
            ),
        ),
        status=cast(str, "proposed"),
        namespace=_namespace(),
        source_class="user_input",
        created_at="2026-07-17T10:00:00+00:00",
        updated_at="2026-07-17T10:00:00+00:00",
    )


def test_http_knowledge_routes_share_one_wired_store() -> None:
    service = SophiagraphHttpService(config=_config())

    put = _request(
        service,
        "PUT",
        "/v1/knowledge/records/rec-http",
        _record_payload("rec-http"),
    )
    fetched = _request(service, "GET", "/v1/knowledge/records/rec-http")
    listed = _request(
        service,
        "POST",
        "/v1/knowledge/records/list",
        {"scopes": ["agent:codex"]},
    )
    searched = _request(
        service,
        "POST",
        "/v1/knowledge/records/search",
        {"query": "workbench", "scopes": ["agent:codex"]},
    )
    exported = _request(
        service,
        "POST",
        "/v1/knowledge/snapshots/export",
        {"scopes": ["agent:codex"]},
    )

    assert put.status == 200
    assert put.payload["record_id"] == "rec-http"
    assert fetched.payload["record"]["id"] == "rec-http"
    assert listed.payload["records"][0]["id"] == "rec-http"
    assert searched.payload["results"][0]["id"] == "rec-http"
    assert exported.payload["bundle"]["records"][0]["id"] == "rec-http"


def test_http_refuses_banned_semantic_routes_and_large_bodies() -> None:
    service = SophiagraphHttpService(config=_config(max_body_bytes=16))

    banned = _request(service, "GET", "/v1/knowledge/summarize")
    too_large = _request(
        service,
        "POST",
        "/v1/knowledge/records/list",
        {"scopes": ["agent:codex"]},
    )

    assert banned.status == 403
    assert banned.payload["error"]["code"] == TOOL_SEMANTIC_ENDPOINT_REFUSED_CODE
    assert too_large.status == 413
    assert too_large.payload["error"]["code"] == REQUEST_REJECTED_CODE
    assert too_large.payload["error"]["data"]["reason"] == "body_too_large"


def test_http_refuses_wildcard_origin_and_unsafe_non_loopback() -> None:
    with pytest.raises(ValueError, match="wildcard origins"):
        HttpTransportConfig(allowed_origins=("*",))
    with pytest.raises(ValueError, match="non-loopback HTTP requires authentication"):
        make_http_server(config=_config(host="0.0.0.0", port=0))


def test_http_refuses_unexpected_mutating_origin() -> None:
    service = SophiagraphHttpService(
        config=_config(allowed_origins=("http://localhost:3000",))
    )

    response = _request(
        service,
        "POST",
        "/v1/knowledge/records/list",
        {"scopes": ["agent:codex"]},
        headers={"Origin": "http://evil.invalid"},
    )

    assert response.status == 403
    assert response.payload["error"]["data"]["reason"] == "origin_not_allowed"


def test_http_quota_denial_uses_locked_status() -> None:
    runtime = RuntimePolicyEngine(
        backend_name="memory",
        quota=QuotaRule(
            rule_id="http-quota",
            max_requests=1,
            window_seconds=60,
            scope="server",
        ),
        deployment_profile=DeploymentProfile(
            allowed_transports=("http",),
            require_request_id=False,
        ),
    )
    service = SophiagraphHttpService(config=_config(), runtime=runtime)

    first = _request(service, "GET", "/v1/knowledge/capabilities")
    second = _request(service, "GET", "/v1/knowledge/capabilities")

    assert first.status == 200
    assert second.status == 429
    assert second.payload["error"]["data"]["rule_id"] == "http-quota"


def test_http_workbench_preview_execute_and_status_are_scoped() -> None:
    store = SophiaGraphMemoryStore()
    store.put_candidate(_candidate("cand-http"))
    service = SophiagraphHttpService(config=_config(), store=store)

    preview = _request(
        service,
        "POST",
        "/v1/workbench/actions/preview",
        {
            "action_id": "preview-cand-http",
            "action": "approve_candidate",
            "target_id": "candidate:cand-http",
        },
    )
    executed = _request(
        service,
        "POST",
        "/v1/workbench/actions/execute",
        {
            "action_id": "approve-cand-http",
            "action": "approve_candidate",
            "target_id": "candidate:cand-http",
        },
    )
    replayed = _request(
        service,
        "POST",
        "/v1/workbench/actions/execute",
        {
            "action_id": "approve-cand-http",
            "action": "approve_candidate",
            "target_id": "candidate:cand-http",
        },
    )
    status = _request(service, "GET", "/v1/workbench/actions/approve-cand-http")

    assert preview.payload["result"]["outcome"] == "preview_only"
    assert executed.status == 200
    assert executed.payload["result"]["outcome"] == "applied"
    assert replayed.payload["result"] == executed.payload["result"]
    assert status.payload["entry"]["action_id"] == "approve-cand-http"
    assert status.payload["entry"]["scope"] == "agent:codex"
    assert store.get_candidate("cand-http").status == "approved"


def test_http_workbench_reports_unsupported_and_identity_denials() -> None:
    store = SophiaGraphMemoryStore()
    store.put_candidate(_candidate("cand-denied"))
    service = SophiagraphHttpService(config=_config(), store=store)

    unsupported = _request(
        service,
        "POST",
        "/v1/workbench/actions/execute",
        {
            "action_id": "unsupported-action",
            "action": "invent_fact",
            "target_id": "candidate:cand-denied",
        },
    )
    impersonation = _request(
        service,
        "POST",
        "/v1/workbench/actions/execute",
        {
            "action_id": "identity-action",
            "action": "approve_candidate",
            "target_id": "candidate:cand-denied",
            "actor_id": "mallory",
            "scope": "agent:mallory",
        },
    )

    assert unsupported.status == 422
    assert unsupported.payload["error"]["code"] == ACTION_UNSUPPORTED_CODE
    assert impersonation.status == 403
    assert impersonation.payload["error"]["code"] == AUTH_DENIED_CODE
    assert impersonation.payload["error"]["data"]["fields"] == ["actor_id", "scope"]
    assert store.get_candidate("cand-denied").status == "proposed"


def test_http_static_bearer_resolves_principal_limits() -> None:
    store = SophiaGraphMemoryStore()
    store.put_candidate(_candidate("cand-auth"))
    token = "secret-token"
    principal = ServerPrincipal(
        principal_id="alice",
        allowed_scopes=("agent:codex",),
        allowed_namespaces=(_namespace_key(_namespace()),),
        allowed_workspaces=("workspace:local",),
    )
    runtime = RuntimePolicyEngine(
        backend_name="memory",
        auth=ServerAuthConfig(
            mode="static_bearer",
            static_tokens=(token,),
            token_principals={token: principal},
        ),
        deployment_profile=DeploymentProfile(
            allowed_transports=("http",),
            require_auth=True,
            require_request_id=False,
        ),
    )
    service = SophiagraphHttpService(config=_config(), runtime=runtime, store=store)

    missing_auth = _request(service, "GET", "/v1/knowledge/capabilities")
    executed = _request(
        service,
        "POST",
        "/v1/workbench/actions/execute",
        {
            "action_id": "approve-auth-http",
            "action": "approve_candidate",
            "target_id": "candidate:cand-auth",
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert missing_auth.status == 401
    assert missing_auth.payload["error"]["code"] == AUTH_DENIED_CODE
    assert executed.status == 200
    entry = store.get_workbench_action(
        "approve-auth-http",
        scope="agent:codex",
        namespace=_namespace(),
    )
    assert entry is not None
    assert entry.principal_id == "alice"


def test_make_http_server_serves_health_over_a_real_socket() -> None:
    server = make_http_server(config=_config(port=0))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with urlopen(f"{server.url}/health", timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert payload["health"]["ready"] is True
    assert payload["request_id"]
