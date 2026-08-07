"""Minimal JSON-RPC 2.0 over stdio runtime for sophiagraph-server.

The bounded runtime supports the MCP methods needed for handshake and dispatch:

1. `initialize` — protocol-version negotiation + server capability advertise
2. `tools/list` — list registered tool names + typed schemas
3. `tools/call` — dispatch to a registered handler

The v1 transport uses line-delimited JSON.

The module deliberately has no `openminion` dependency.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from typing import Any, BinaryIO, Mapping

from sophiagraph import __version__
from sophiagraph.server.contracts import (
    AuthDeniedError,
    JSONRPC_INTERNAL_ERROR,
    JSONRPC_INVALID_PARAMS,
    JSONRPC_INVALID_REQUEST,
    JSONRPC_METHOD_NOT_FOUND,
    JSONRPC_PARSE_ERROR,
    MCP_PROTOCOL_VERSION,
    QuotaExceededError,
    SophiagraphServerError,
)
from sophiagraph.server.runtime_hardening import (
    RuntimePolicyEngine,
    RuntimeRequestContext,
)
from sophiagraph.server.service_core import to_json_dict
from sophiagraph.server.tools import ToolRegistry, ToolSchema


@dataclass(frozen=True)
class ServerInfo:
    name: str = "sophiagraph-server"
    version: str = __version__


def _ok_response(request_id: Any, result: Mapping[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": dict(result)}


def _err_response(
    request_id: Any, code: int, message: str, details: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    error: dict[str, Any] = {"code": int(code), "message": str(message)}
    if details:
        error["data"] = dict(details)
    return {"jsonrpc": "2.0", "id": request_id, "error": error}


def _schema_to_payload(schema: ToolSchema) -> dict[str, Any]:
    return {
        "name": schema.name,
        "description": schema.description,
        "inputSchema": dict(schema.input_schema),
        "outputSchema": dict(schema.output_schema),
    }


def _handle_initialize(
    request_id: Any,
    params: Mapping[str, Any],
    server_info: ServerInfo,
) -> dict[str, Any]:
    requested_version = str(params.get("protocolVersion") or "")
    return _ok_response(
        request_id,
        {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": server_info.name, "version": server_info.version},
            "negotiated": {
                "client_requested": requested_version,
                "server_offered": MCP_PROTOCOL_VERSION,
            },
        },
    )


def _handle_tools_list(
    request_id: Any,
    registry: ToolRegistry,
) -> dict[str, Any]:
    return _ok_response(
        request_id,
        {"tools": [_schema_to_payload(schema) for schema in registry.schemas()]},
    )


def _handle_tools_call(
    request_id: Any,
    params: Mapping[str, Any],
    registry: ToolRegistry,
    runtime: RuntimePolicyEngine | None = None,
    context: RuntimeRequestContext | None = None,
) -> dict[str, Any]:
    name = str(params.get("name") or "")
    arguments = params.get("arguments") or {}
    if not isinstance(arguments, Mapping):
        return _err_response(
            request_id,
            JSONRPC_INVALID_PARAMS,
            "tools/call: 'arguments' must be an object",
        )
    try:
        handler = registry.get_handler(name)
    except KeyError:
        return _err_response(
            request_id,
            JSONRPC_METHOD_NOT_FOUND,
            f"tool {name!r} is not registered",
            {"tool_name": name},
        )
    except SophiagraphServerError as err:
        return _err_response(request_id, err.code, str(err), err.details)
    access_context, grant_id = _memory_access_for_request(runtime, context)
    try:
        result = handler(
            **dict(arguments),
            _memory_access_context=access_context,
            _memory_grant_id=grant_id,
        )
    except SophiagraphServerError as err:
        return _err_response(request_id, err.code, str(err), err.details)
    except Exception as err:  # pragma: no cover - defensive
        return _err_response(
            request_id,
            JSONRPC_INTERNAL_ERROR,
            f"tool {name!r} raised {type(err).__name__}: {err}",
        )
    structured = dict(result)
    return _ok_response(
        request_id,
        {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(structured, sort_keys=True, default=str),
                }
            ],
            "structuredContent": structured,
        },
    )


def _attach_meta(
    response: dict[str, Any],
    *,
    request_id: str | None,
    quota_snapshot: Any = None,
    webhook_batch: Any = None,
) -> dict[str, Any]:
    meta: dict[str, Any] = {}
    if request_id:
        meta["requestId"] = request_id
    if quota_snapshot is not None:
        meta["quota"] = to_json_dict(quota_snapshot)
    if webhook_batch is not None:
        meta["webhooks"] = to_json_dict(webhook_batch)
    if meta:
        response["meta"] = meta
    return response


def _enforce_runtime_policy(
    runtime: RuntimePolicyEngine,
    message: Mapping[str, Any],
    context: RuntimeRequestContext,
) -> None:
    runtime.enforce_deployment(message, context)
    runtime.authorize(context)


def _memory_access_for_request(
    runtime: RuntimePolicyEngine | None,
    context: RuntimeRequestContext | None,
) -> tuple[Any, str | None]:
    if runtime is None or context is None:
        return None, None
    principal = runtime.resolve_principal(context)
    return runtime.memory_access_context(context, principal), context.grant_id


def dispatch(
    message: Mapping[str, Any],
    *,
    registry: ToolRegistry,
    server_info: ServerInfo,
    runtime: RuntimePolicyEngine | None = None,
) -> dict[str, Any] | None:
    """Dispatch one parsed JSON-RPC message, returning None for notifications."""
    if not isinstance(message, Mapping):
        return _err_response(None, JSONRPC_INVALID_REQUEST, "request must be an object")
    if message.get("jsonrpc") != "2.0":
        return _err_response(
            message.get("id"), JSONRPC_INVALID_REQUEST, "missing jsonrpc=2.0"
        )
    method = message.get("method")
    request_id = message.get("id")
    params = message.get("params") or {}
    context = (
        runtime.context_from_message(message, transport="stdio")
        if runtime is not None
        else None
    )
    if not isinstance(params, Mapping):
        return _err_response(
            request_id, JSONRPC_INVALID_PARAMS, "params must be an object"
        )
    is_notification = "id" not in message
    try:
        if runtime is not None and context is not None:
            _enforce_runtime_policy(runtime, message, context)
        if method == "runtime/health" and runtime is not None:
            response = _ok_response(
                request_id,
                {
                    "health": to_json_dict(
                        runtime.health_report(
                            request_id=context.request_id if context else None,
                            registry_size=len(registry.names()),
                        )
                    )
                },
            )
            return _attach_meta(
                response, request_id=context.request_id if context else None
            )
        if method == "runtime/ready" and runtime is not None:
            report = runtime.health_report(
                request_id=context.request_id if context else None,
                registry_size=len(registry.names()),
            )
            response = _ok_response(request_id, {"ready": report.ready})
            return _attach_meta(
                response, request_id=context.request_id if context else None
            )
        if method == "runtime/diagnostics" and runtime is not None:
            report = runtime.health_report(
                request_id=context.request_id if context else None,
                registry_size=len(registry.names()),
            )
            response = _ok_response(request_id, {"diagnostics": to_json_dict(report)})
            return _attach_meta(
                response, request_id=context.request_id if context else None
            )
    except (AuthDeniedError, QuotaExceededError, SophiagraphServerError) as err:
        return _attach_meta(
            _err_response(request_id, err.code, str(err), err.details),
            request_id=context.request_id if context is not None else None,
        )
    if method == "initialize":
        response = _handle_initialize(request_id, params, server_info)
        return _attach_meta(
            response,
            request_id=context.request_id if context is not None else None,
        )
    if method == "initialized" or method == "notifications/initialized":
        return None if is_notification else _ok_response(request_id, {})
    if method == "tools/list":
        response = _handle_tools_list(request_id, registry)
        return _attach_meta(
            response,
            request_id=context.request_id if context is not None else None,
        )
    if method == "tools/call":
        try:
            quota_snapshot = (
                runtime.consume_quota(context)
                if runtime is not None and context is not None
                else None
            )
            response = _handle_tools_call(
                request_id, params, registry, runtime, context
            )
        except (AuthDeniedError, QuotaExceededError, SophiagraphServerError) as err:
            return _attach_meta(
                _err_response(request_id, err.code, str(err), err.details),
                request_id=context.request_id if context is not None else None,
            )
        webhook_batch = None
        if (
            runtime is not None
            and context is not None
            and "result" in response
            and isinstance(response["result"], Mapping)
        ):
            webhook_batch = runtime.deliver_tool_event(
                context,
                response["result"].get("structuredContent", {}),
            )
        return _attach_meta(
            response,
            request_id=context.request_id if context is not None else None,
            quota_snapshot=quota_snapshot,
            webhook_batch=webhook_batch,
        )
    if method == "ping":
        response = _ok_response(request_id, {})
        return _attach_meta(
            response,
            request_id=context.request_id if context is not None else None,
        )
    if is_notification:
        return None
    response = _err_response(
        request_id,
        JSONRPC_METHOD_NOT_FOUND,
        f"method {method!r} is not supported by sophiagraph-server v1",
    )
    return _attach_meta(
        response,
        request_id=context.request_id if context is not None else None,
    )


def serve_stdio(
    *,
    stdin: BinaryIO | None = None,
    stdout: BinaryIO | None = None,
    registry: ToolRegistry | None = None,
    server_info: ServerInfo | None = None,
    runtime: RuntimePolicyEngine | None = None,
) -> int:
    """Run the line-delimited JSON-RPC stdio loop until EOF.

    Returns process exit code (always 0 on clean EOF).
    """
    in_stream = stdin if stdin is not None else sys.stdin.buffer
    out_stream = stdout if stdout is not None else sys.stdout.buffer
    resolved_registry = registry if registry is not None else ToolRegistry.default()
    resolved_info = server_info if server_info is not None else ServerInfo()
    resolved_runtime = (
        runtime
        if runtime is not None
        else RuntimePolicyEngine(backend_name=resolved_registry.backend)
    )
    while True:
        raw_line = in_stream.readline()
        if not raw_line:
            return 0
        try:
            text = raw_line.decode("utf-8").strip()
        except UnicodeDecodeError:
            response = _err_response(None, JSONRPC_PARSE_ERROR, "non-utf-8 line")
            _write_response(out_stream, response)
            continue
        if not text:
            continue
        try:
            message = json.loads(text)
        except json.JSONDecodeError as err:
            response = _err_response(
                None,
                JSONRPC_PARSE_ERROR,
                f"invalid JSON: {err.msg} (line {err.lineno} col {err.colno})",
            )
            _write_response(out_stream, response)
            continue
        response = dispatch(
            message,
            registry=resolved_registry,
            server_info=resolved_info,
            runtime=resolved_runtime,
        )
        if response is not None:
            _write_response(out_stream, response)


def _write_response(out_stream: BinaryIO, response: Mapping[str, Any]) -> None:
    payload = json.dumps(response, ensure_ascii=False) + "\n"
    out_stream.write(payload.encode("utf-8"))
    out_stream.flush()


__all__ = ["ServerInfo", "dispatch", "serve_stdio"]
