"""Handshake + dispatch smoke for the bounded KMSR v1 MCP stdio server.

Uses an in-process dispatch path (not a subprocess) for fast deterministic
coverage. A subprocess smoke is also exercised via the CLI test to ensure
`serve-stdio` actually wires the dispatcher.
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

from sophiagraph.server.contracts import (
    JSONRPC_INVALID_REQUEST,
    JSONRPC_METHOD_NOT_FOUND,
    MCP_PROTOCOL_VERSION,
    TOOL_BACKEND_NOT_WIRED_CODE,
    TOOL_SEMANTIC_ENDPOINT_REFUSED_CODE,
)
from sophiagraph.server.server import ServerInfo, dispatch, serve_stdio
from sophiagraph.server.tools import SUPPORTED_TOOL_NAMES, ToolRegistry


def _registry() -> ToolRegistry:
    return ToolRegistry.default(backend="memory")


def test_initialize_returns_protocol_version_and_server_info() -> None:
    response = dispatch(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "clientInfo": {"name": "test"}},
        },
        registry=_registry(),
        server_info=ServerInfo(),
    )
    assert response is not None
    assert response["id"] == 1
    result = response["result"]
    assert result["protocolVersion"] == MCP_PROTOCOL_VERSION
    assert result["serverInfo"]["name"] == "sophiagraph-server"
    assert result["capabilities"]["tools"] == {"listChanged": False}


def test_initialized_notification_produces_no_response() -> None:
    response = dispatch(
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        registry=_registry(),
        server_info=ServerInfo(),
    )
    assert response is None


def test_tools_list_returns_exactly_the_supported_eight() -> None:
    response = dispatch(
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        registry=_registry(),
        server_info=ServerInfo(),
    )
    assert response is not None
    tool_names = {tool["name"] for tool in response["result"]["tools"]}
    assert tool_names == set(SUPPORTED_TOOL_NAMES)


def test_tools_call_capabilities_is_fully_wired() -> None:
    response = dispatch(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "knowledge_capabilities", "arguments": {}},
        },
        registry=_registry(),
        server_info=ServerInfo(),
    )
    assert response is not None
    content = response["result"]["structuredContent"]
    assert response["result"]["content"][0]["type"] == "text"
    assert content["protocol_version"] == MCP_PROTOCOL_VERSION
    assert content["backend"] == "memory"


def test_tools_call_data_op_returns_backend_not_wired_error() -> None:
    response = dispatch(
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "knowledge_get_record", "arguments": {"record_id": "x"}},
        },
        registry=_registry(),
        server_info=ServerInfo(),
    )
    assert response is not None
    error = response["error"]
    assert error["code"] == TOOL_BACKEND_NOT_WIRED_CODE
    assert error["data"]["blocker"] == "KMSR-02"


def test_tools_call_banned_semantic_endpoint_returns_typed_refusal() -> None:
    response = dispatch(
        {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {"name": "summarize", "arguments": {}},
        },
        registry=_registry(),
        server_info=ServerInfo(),
    )
    assert response is not None
    error = response["error"]
    assert error["code"] == TOOL_SEMANTIC_ENDPOINT_REFUSED_CODE
    assert error["data"]["boundary"] == "anti_llm"


def test_unknown_method_returns_method_not_found() -> None:
    response = dispatch(
        {"jsonrpc": "2.0", "id": 6, "method": "does/not/exist"},
        registry=_registry(),
        server_info=ServerInfo(),
    )
    assert response is not None
    assert response["error"]["code"] == JSONRPC_METHOD_NOT_FOUND


def test_missing_jsonrpc_version_returns_invalid_request() -> None:
    response = dispatch(
        {"id": 7, "method": "initialize"},
        registry=_registry(),
        server_info=ServerInfo(),
    )
    assert response is not None
    assert response["error"]["code"] == JSONRPC_INVALID_REQUEST


def test_stdio_loop_processes_initialize_and_tools_list_in_sequence() -> None:
    init_msg = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-06-18"},
        }
    )
    list_msg = json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    stdin = io.BytesIO((init_msg + "\n" + list_msg + "\n").encode("utf-8"))
    stdout = io.BytesIO()
    exit_code = serve_stdio(stdin=stdin, stdout=stdout, registry=_registry())
    assert exit_code == 0
    lines = [line for line in stdout.getvalue().decode("utf-8").splitlines() if line]
    assert len(lines) == 2
    init_response = json.loads(lines[0])
    list_response = json.loads(lines[1])
    assert init_response["result"]["protocolVersion"] == MCP_PROTOCOL_VERSION
    list_tool_names = {tool["name"] for tool in list_response["result"]["tools"]}
    assert list_tool_names == set(SUPPORTED_TOOL_NAMES)


def test_serve_stdio_subprocess_completes_initialize_handshake() -> None:
    root = Path(__file__).resolve().parents[1]
    env = {"PYTHONPATH": str(root / "src")}
    init_msg = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-06-18"},
        }
    )
    proc = subprocess.run(
        [sys.executable, "-m", "sophiagraph.server", "serve-stdio"],
        input=init_msg + "\n",
        cwd=root,
        env=env,
        text=True,
        capture_output=True,
        check=True,
        timeout=10,
    )
    lines = [line for line in proc.stdout.splitlines() if line.strip()]
    assert lines, "serve-stdio produced no response"
    response = json.loads(lines[0])
    assert response["id"] == 1
    assert response["result"]["protocolVersion"] == MCP_PROTOCOL_VERSION


def test_invalid_json_line_returns_parse_error_and_loop_continues() -> None:
    bad_input = "this is not json\n"
    init_msg = json.dumps(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
    )
    stdin = io.BytesIO((bad_input + init_msg + "\n").encode("utf-8"))
    stdout = io.BytesIO()
    exit_code = serve_stdio(stdin=stdin, stdout=stdout, registry=_registry())
    assert exit_code == 0
    lines = [line for line in stdout.getvalue().decode("utf-8").splitlines() if line]
    assert len(lines) == 2
    parse_error = json.loads(lines[0])
    init_ok = json.loads(lines[1])
    assert "error" in parse_error
    assert init_ok["result"]["protocolVersion"] == MCP_PROTOCOL_VERSION


@pytest.mark.parametrize(
    "banned",
    ["summarize", "classify", "knowledge_extract_claims"],
)
def test_handshake_run_with_banned_tool_call_returns_typed_refusal(banned: str) -> None:
    call_msg = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 10,
            "method": "tools/call",
            "params": {"name": banned, "arguments": {}},
        }
    )
    stdin = io.BytesIO((call_msg + "\n").encode("utf-8"))
    stdout = io.BytesIO()
    exit_code = serve_stdio(stdin=stdin, stdout=stdout, registry=_registry())
    assert exit_code == 0
    response = json.loads(stdout.getvalue().decode("utf-8").strip())
    assert response["error"]["code"] == TOOL_SEMANTIC_ENDPOINT_REFUSED_CODE
