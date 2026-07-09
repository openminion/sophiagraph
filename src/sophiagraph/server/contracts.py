"""MCP protocol constants and error types for the sophiagraph-server runtime.

Mirrors the JSON-RPC + MCP-version vocabulary used by the OpenMinion MCP client
without reaching into `openminion`. This module is dependency-free apart from
the standard library; tool-level types live in `tools.py`.
"""

from __future__ import annotations

from typing import Any

# Pin to a published MCP protocol version. Negotiation at handshake time may
# downgrade to a floor; KMSR-01 advertises a single supported version.
MCP_PROTOCOL_VERSION = "2025-06-18"
MCP_PROTOCOL_VERSION_FLOOR = "2025-03-26"

# JSON-RPC 2.0 error codes used by the runtime. Public surface so contract
# tests and downstream consumers can assert on exact codes.
JSONRPC_PARSE_ERROR = -32700
JSONRPC_INVALID_REQUEST = -32600
JSONRPC_METHOD_NOT_FOUND = -32601
JSONRPC_INVALID_PARAMS = -32602
JSONRPC_INTERNAL_ERROR = -32603

# Tool-call failure codes specific to the sophiagraph-server surface.
TOOL_NOT_FOUND_CODE = -32001
TOOL_BACKEND_NOT_WIRED_CODE = -32010
TOOL_SEMANTIC_ENDPOINT_REFUSED_CODE = -32020
TOOL_BACKEND_INVOCATION_FAILED_CODE = -32030
AUTH_DENIED_CODE = -32040
QUOTA_EXCEEDED_CODE = -32041


class SophiagraphServerError(RuntimeError):
    """Base error for sophiagraph-server runtime failures."""

    def __init__(
        self,
        message: str,
        *,
        code: int,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = int(code)
        self.details = dict(details or {})


class BackendNotWiredError(SophiagraphServerError):
    """Raised when a registered tool has no backend wired yet.

    KMSR-01 ships the typed contract layer + protocol handshake; KMSR-02 wires
    the backend onto package-owned `sophiagraph` stores. Until KMSR-02 lands,
    data-operation tools raise this error and the runtime returns a
    deterministic JSON-RPC error payload.
    """

    def __init__(self, tool_name: str) -> None:
        super().__init__(
            f"tool {tool_name!r} has no backend wired yet (KMSR-02 pending)",
            code=TOOL_BACKEND_NOT_WIRED_CODE,
            details={"tool_name": tool_name, "blocker": "KMSR-02"},
        )
        self.tool_name = tool_name


class SemanticEndpointRefusedError(SophiagraphServerError):
    """Raised on attempts to invoke explicitly banned semantic endpoints.

    The anti-LLM boundary forbids runtime-owned summarize/classify/extract
    endpoints. Any incoming tool call whose name matches the banned set is
    deterministically refused with this error rather than being silently
    routed away.
    """

    def __init__(self, tool_name: str) -> None:
        super().__init__(
            (
                f"tool {tool_name!r} is a banned semantic endpoint; runtime "
                "must remain plumbing-only per KMSR/AIBR anti-LLM lock"
            ),
            code=TOOL_SEMANTIC_ENDPOINT_REFUSED_CODE,
            details={"tool_name": tool_name, "boundary": "anti_llm"},
        )
        self.tool_name = tool_name


class AuthDeniedError(SophiagraphServerError):
    """Raised when runtime auth rejects a request deterministically."""

    def __init__(self, *, request_id: str, reason: str, auth_mode: str) -> None:
        super().__init__(
            f"request {request_id!r} denied by auth policy: {reason}",
            code=AUTH_DENIED_CODE,
            details={
                "request_id": request_id,
                "reason": reason,
                "auth_mode": auth_mode,
            },
        )


class QuotaExceededError(SophiagraphServerError):
    """Raised when a request exceeds the configured runtime quota."""

    def __init__(
        self,
        *,
        request_id: str,
        rule_id: str,
        scope_key: str,
        used_requests: int,
        max_requests: int,
    ) -> None:
        super().__init__(
            f"request {request_id!r} exceeded quota {rule_id!r} for {scope_key!r}",
            code=QUOTA_EXCEEDED_CODE,
            details={
                "request_id": request_id,
                "rule_id": rule_id,
                "scope_key": scope_key,
                "used_requests": int(used_requests),
                "max_requests": int(max_requests),
            },
        )


__all__ = [
    "MCP_PROTOCOL_VERSION",
    "MCP_PROTOCOL_VERSION_FLOOR",
    "JSONRPC_PARSE_ERROR",
    "JSONRPC_INVALID_REQUEST",
    "JSONRPC_METHOD_NOT_FOUND",
    "JSONRPC_INVALID_PARAMS",
    "JSONRPC_INTERNAL_ERROR",
    "TOOL_NOT_FOUND_CODE",
    "TOOL_BACKEND_NOT_WIRED_CODE",
    "TOOL_SEMANTIC_ENDPOINT_REFUSED_CODE",
    "TOOL_BACKEND_INVOCATION_FAILED_CODE",
    "AUTH_DENIED_CODE",
    "QUOTA_EXCEEDED_CODE",
    "SophiagraphServerError",
    "BackendNotWiredError",
    "SemanticEndpointRefusedError",
    "AuthDeniedError",
    "QuotaExceededError",
]
