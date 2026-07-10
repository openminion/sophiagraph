"""Runtime-hardening coverage for auth, quotas, diagnostics, and webhooks."""

from __future__ import annotations

from sophiagraph.server.backend import BackendConfig, build_wired_registry
from sophiagraph.server.contracts import (
    AUTH_DENIED_CODE,
    QUOTA_EXCEEDED_CODE,
    TOOL_BACKEND_INVOCATION_FAILED_CODE,
)
from sophiagraph.server.runtime_hardening import (
    QuotaRule,
    RuntimePolicyEngine,
    ServerAuthConfig,
    WebhookSubscription,
    event_type_for_tool,
)
from sophiagraph.server.server import ServerInfo, dispatch
from sophiagraph.server.tools import ToolRegistry


def _registry() -> ToolRegistry:
    return ToolRegistry.default(backend="memory")


def _server_info() -> ServerInfo:
    return ServerInfo()


def test_backend_invocation_code_is_stable() -> None:
    assert TOOL_BACKEND_INVOCATION_FAILED_CODE == -32030


def test_static_bearer_auth_denies_tools_call_without_token() -> None:
    runtime = RuntimePolicyEngine(
        backend_name="memory",
        auth=ServerAuthConfig(mode="static_bearer", static_tokens=("secret",)),
    )
    response = dispatch(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "knowledge_capabilities", "arguments": {}},
        },
        registry=_registry(),
        server_info=_server_info(),
        runtime=runtime,
    )
    assert response is not None
    assert response["error"]["code"] == AUTH_DENIED_CODE
    assert response["error"]["data"]["reason"] == "missing_or_invalid_bearer_token"
    assert response["meta"]["requestId"] == "1"


def test_static_bearer_auth_allows_tools_call_with_token() -> None:
    runtime = RuntimePolicyEngine(
        backend_name="memory",
        auth=ServerAuthConfig(mode="static_bearer", static_tokens=("secret",)),
    )
    response = dispatch(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "knowledge_capabilities", "arguments": {}},
            "meta": {"authorization": "Bearer secret", "requestId": "req-auth-ok"},
        },
        registry=_registry(),
        server_info=_server_info(),
        runtime=runtime,
    )
    assert response is not None
    assert response["result"]["structuredContent"]["backend"] == "memory"
    assert response["meta"]["requestId"] == "req-auth-ok"


def test_runtime_health_ready_and_diagnostics_are_stable() -> None:
    runtime = RuntimePolicyEngine(
        backend_name="sqlite",
        quota=QuotaRule(
            rule_id="runtime-health",
            max_requests=3,
            window_seconds=60,
            scope="tenant",
        ),
    )
    health = dispatch(
        {
            "jsonrpc": "2.0",
            "id": "health",
            "method": "runtime/health",
            "meta": {"requestId": "health-req"},
        },
        registry=_registry(),
        server_info=_server_info(),
        runtime=runtime,
    )
    ready = dispatch(
        {
            "jsonrpc": "2.0",
            "id": "ready",
            "method": "runtime/ready",
            "meta": {"requestId": "ready-req"},
        },
        registry=_registry(),
        server_info=_server_info(),
        runtime=runtime,
    )
    diagnostics = dispatch(
        {
            "jsonrpc": "2.0",
            "id": "diagnostics",
            "method": "runtime/diagnostics",
            "meta": {
                "requestId": "diag-req",
                "authorization": "Bearer secret",
            },
        },
        registry=_registry(),
        server_info=_server_info(),
        runtime=RuntimePolicyEngine(
            backend_name="sqlite",
            auth=ServerAuthConfig(
                mode="static_bearer",
                static_tokens=("secret",),
            ),
        ),
    )
    assert health is not None
    assert ready is not None
    assert diagnostics is not None
    assert health["result"]["health"]["ready"] is True
    assert ready["result"]["ready"] is True
    assert diagnostics["result"]["diagnostics"]["diagnostics"]["backend"] == "sqlite"
    assert health["meta"]["requestId"] == "health-req"
    assert ready["meta"]["requestId"] == "ready-req"
    assert diagnostics["meta"]["requestId"] == "diag-req"


def test_quota_snapshot_and_exceeded_error_are_deterministic() -> None:
    runtime = RuntimePolicyEngine(
        backend_name="memory",
        quota=QuotaRule(
            rule_id="tools-per-tenant",
            max_requests=1,
            window_seconds=30,
            scope="tenant",
        ),
    )
    first = dispatch(
        {
            "jsonrpc": "2.0",
            "id": "quota-1",
            "method": "tools/call",
            "params": {"name": "knowledge_capabilities", "arguments": {}},
            "meta": {"tenant": "tenant-a", "requestId": "quota-req-1"},
        },
        registry=_registry(),
        server_info=_server_info(),
        runtime=runtime,
    )
    second = dispatch(
        {
            "jsonrpc": "2.0",
            "id": "quota-2",
            "method": "tools/call",
            "params": {"name": "knowledge_capabilities", "arguments": {}},
            "meta": {"tenant": "tenant-a", "requestId": "quota-req-2"},
        },
        registry=_registry(),
        server_info=_server_info(),
        runtime=runtime,
    )
    assert first is not None
    assert second is not None
    assert first["meta"]["quota"]["rule_id"] == "tools-per-tenant"
    assert first["meta"]["quota"]["scope_key"] == "tenant-a"
    assert first["meta"]["quota"]["used_requests"] == 1
    assert first["meta"]["quota"]["remaining_requests"] == 0
    assert second["error"]["code"] == QUOTA_EXCEEDED_CODE
    assert second["error"]["data"]["rule_id"] == "tools-per-tenant"
    assert second["error"]["data"]["scope_key"] == "tenant-a"
    assert second["meta"]["requestId"] == "quota-req-2"


def test_webhook_delivery_reports_structural_event_attempts() -> None:
    attempts: list[tuple[str, str]] = []

    def _sender(subscription: WebhookSubscription, event) -> tuple[int, str | None]:
        attempts.append((subscription.subscription_id, event.event_type))
        return (202, None)

    runtime = RuntimePolicyEngine(
        backend_name="memory",
        webhook_subscriptions=(
            WebhookSubscription(
                subscription_id="sub-records",
                event_types=("knowledge.record.put",),
            ),
            WebhookSubscription(
                subscription_id="sub-inactive",
                event_types=("*",),
                active=False,
            ),
        ),
        webhook_sender=_sender,
    )
    registry = build_wired_registry(BackendConfig(backend="memory"))
    response = dispatch(
        {
            "jsonrpc": "2.0",
            "id": "put-1",
            "method": "tools/call",
            "params": {
                "name": "knowledge_put_record",
                "arguments": {
                    "record": {
                        "id": "rec-webhook",
                        "scope": "agent:test",
                        "type": "fact",
                        "content": {"text": "hello"},
                        "created_at": "2026-06-15T00:00:00+00:00",
                        "updated_at": "2026-06-15T00:00:00+00:00",
                    }
                },
            },
            "meta": {"requestId": "put-webhook"},
        },
        registry=registry,
        server_info=_server_info(),
        runtime=runtime,
    )
    assert response is not None
    assert attempts == [("sub-records", "knowledge.record.put")]
    batch = response["meta"]["webhooks"]
    assert batch["event"]["event_type"] == "knowledge.record.put"
    statuses = {item["subscription_id"]: item["status"] for item in batch["attempts"]}
    assert statuses == {
        "sub-records": "delivered",
        "sub-inactive": "skipped",
    }


def test_event_type_mapping_stays_structural_only() -> None:
    assert event_type_for_tool("knowledge_put_record") == "knowledge.record.put"
    assert (
        event_type_for_tool("knowledge_export_snapshot") == "knowledge.snapshot.export"
    )
    assert event_type_for_tool("knowledge_search_records") is None
    assert event_type_for_tool("summarize") is None
