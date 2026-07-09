"""SSSF-03 — Shared service-core contract drift tests.

These tests fail if transport payload names drift from package DTO names or
MCP contract names. They guard the parity rules declared in
``docs/specs/sophiagraph-service-surface-mcp-rest-spec.md`` (REST follow-on
design) so a future REST execution lane inherits MCP's field shapes
unchanged.
"""

from __future__ import annotations

from dataclasses import fields

import pytest

from sophiagraph.server.contracts import (
    JSONRPC_INTERNAL_ERROR,
    JSONRPC_INVALID_PARAMS,
    JSONRPC_INVALID_REQUEST,
    JSONRPC_METHOD_NOT_FOUND,
    JSONRPC_PARSE_ERROR,
    MCP_PROTOCOL_VERSION,
    TOOL_BACKEND_NOT_WIRED_CODE,
    TOOL_NOT_FOUND_CODE,
    TOOL_SEMANTIC_ENDPOINT_REFUSED_CODE,
)
from sophiagraph.server.service_core import (
    REQUEST_PAYLOAD_KEYS,
    RESPONSE_PAYLOAD_KEYS,
    assert_request_keys_subset,
    canonical_response_keys,
    to_json_dict,
)
from sophiagraph.server.tools import (
    BANNED_SEMANTIC_TOOL_NAMES,
    SUPPORTED_TOOL_NAMES,
)


# ---------------------------------------------------------------------------
# Registry alignment — closed enums must agree with the canonical tool list.
# ---------------------------------------------------------------------------


def test_request_keys_cover_every_supported_tool() -> None:
    assert set(REQUEST_PAYLOAD_KEYS.keys()) == set(SUPPORTED_TOOL_NAMES), (
        "REQUEST_PAYLOAD_KEYS drift vs SUPPORTED_TOOL_NAMES — "
        "any new MCP tool must declare its canonical request envelope here."
    )


def test_response_keys_cover_every_supported_tool() -> None:
    assert set(RESPONSE_PAYLOAD_KEYS.keys()) == set(SUPPORTED_TOOL_NAMES), (
        "RESPONSE_PAYLOAD_KEYS drift vs SUPPORTED_TOOL_NAMES — "
        "any new MCP tool must declare its canonical response envelope here."
    )


def test_no_banned_name_appears_in_request_or_response_keys() -> None:
    for banned in BANNED_SEMANTIC_TOOL_NAMES:
        assert banned not in REQUEST_PAYLOAD_KEYS
        assert banned not in RESPONSE_PAYLOAD_KEYS


# ---------------------------------------------------------------------------
# Field names — canonical envelope keys must match what backend.py emits.
# ---------------------------------------------------------------------------


def test_request_envelope_matches_backend_handler_kwargs() -> None:
    """Every backend handler's ``kwargs.get(...)`` call uses a canonical key.

    This is the contract: when the backend asks for ``record`` /``filters`` /
    ``query`` /etc., the key MUST be in REQUEST_PAYLOAD_KEYS for that tool.
    The test reads the source file to keep this honest if/when handlers move.
    """
    import inspect

    from sophiagraph.server import backend

    source = inspect.getsource(backend)
    # For each handler factory, look for the keys it actually pulls out of kwargs.
    for tool_name, allowed in REQUEST_PAYLOAD_KEYS.items():
        if not allowed:
            continue
        for key in allowed:
            pattern = f'kwargs.get("{key}"'
            assert pattern in source, (
                f"backend.py does not read canonical request key {key!r} "
                f"for tool {tool_name!r}"
            )


def test_response_envelope_keys_round_trip() -> None:
    """A handler invocation that succeeds returns exactly the canonical keys."""
    # Capabilities is the only handler we can drive without a wired store.
    from sophiagraph.server.backend import _capabilities_handler

    out = _capabilities_handler("memory")()
    assert set(out.keys()) == set(canonical_response_keys("knowledge_capabilities")), (
        "knowledge_capabilities returned keys do not match canonical envelope; "
        "REST execution lane will produce a different shape if this drifts."
    )


# ---------------------------------------------------------------------------
# DTO parity — the JSON shape of a sophiagraph DTO matches `asdict(...)` so
# that REST + MCP can serialize identically without a renaming layer.
# ---------------------------------------------------------------------------


def test_memory_record_to_json_dict_has_package_field_names() -> None:
    """``to_json_dict(MemoryRecord)`` produces every public package field name.

    If a new field is added to ``MemoryRecord``, the REST contract picks it
    up automatically because the serializer is dataclass-shape-driven. This
    test guards against a refactor that introduces a renaming layer.
    """
    from sophiagraph import MemoryRecord
    from sophiagraph.models import MemoryNamespace

    record = MemoryRecord(
        id="rec-test",
        scope="session:test",
        type="fact",
        content="x",
        created_at="2026-05-29T00:00:00+00:00",
        updated_at="2026-05-29T00:00:00+00:00",
        namespace=MemoryNamespace(session_id="test"),
    )
    payload = to_json_dict(record)
    assert isinstance(payload, dict)
    package_fields = {field.name for field in fields(record)}
    assert set(payload.keys()) == package_fields, (
        "to_json_dict() introduced a renaming layer; REST + MCP parity broken"
    )


def test_to_json_dict_passthrough_for_primitives() -> None:
    assert to_json_dict(None) is None
    assert to_json_dict("foo") == "foo"
    assert to_json_dict(42) == 42
    assert to_json_dict({"a": 1}) == {"a": 1}


# ---------------------------------------------------------------------------
# Error code surface — exact codes that REST + MCP must both emit.
# ---------------------------------------------------------------------------


def test_jsonrpc_codes_are_stable_integers() -> None:
    assert JSONRPC_PARSE_ERROR == -32700
    assert JSONRPC_INVALID_REQUEST == -32600
    assert JSONRPC_METHOD_NOT_FOUND == -32601
    assert JSONRPC_INVALID_PARAMS == -32602
    assert JSONRPC_INTERNAL_ERROR == -32603


def test_sophiagraph_tool_codes_are_stable_integers() -> None:
    assert TOOL_NOT_FOUND_CODE == -32001
    assert TOOL_BACKEND_NOT_WIRED_CODE == -32010
    assert TOOL_SEMANTIC_ENDPOINT_REFUSED_CODE == -32020


def test_mcp_protocol_version_matches_handshake() -> None:
    """Capabilities response MUST advertise the same protocol version
    constant the contracts module pins. REST will mirror this exactly."""
    from sophiagraph.server.backend import _capabilities_handler

    out = _capabilities_handler("memory")()
    assert out["protocol_version"] == MCP_PROTOCOL_VERSION


# ---------------------------------------------------------------------------
# Unknown-key rejection — the validator catches drift before it reaches a
# backend.
# ---------------------------------------------------------------------------


def test_assert_request_keys_subset_accepts_canonical_keys() -> None:
    assert_request_keys_subset("knowledge_put_record", {"record"})
    assert_request_keys_subset("knowledge_list_relations", {"record_id", "filters"})
    assert_request_keys_subset("knowledge_capabilities", set())


def test_assert_request_keys_subset_rejects_unknown_key() -> None:
    with pytest.raises(ValueError):
        assert_request_keys_subset("knowledge_put_record", {"record", "extra_field"})


def test_assert_request_keys_subset_rejects_unknown_tool() -> None:
    with pytest.raises(ValueError):
        assert_request_keys_subset("knowledge_summarize", set())


def test_canonical_response_keys_rejects_unknown_tool() -> None:
    with pytest.raises(ValueError):
        canonical_response_keys("knowledge_summarize")


# ---------------------------------------------------------------------------
# Anti-LLM drift guard — banned set must remain rejected by the validators.
# ---------------------------------------------------------------------------


def test_banned_semantic_tool_names_remain_off_the_request_registry() -> None:
    for banned in BANNED_SEMANTIC_TOOL_NAMES:
        assert banned not in REQUEST_PAYLOAD_KEYS, (
            f"banned tool {banned!r} appeared in REQUEST_PAYLOAD_KEYS; "
            "anti-LLM boundary violation"
        )
        assert banned not in RESPONSE_PAYLOAD_KEYS, (
            f"banned tool {banned!r} appeared in RESPONSE_PAYLOAD_KEYS; "
            "anti-LLM boundary violation"
        )


def test_service_core_module_is_pure_python_no_openminion_import() -> None:
    """The shared service-core helpers must not pull openminion in.

    This is a structural drift guard: a refactor that imports an OpenMinion
    module here would break the import-boundary contract documented in the
    README and validated by test_imports.py.
    """
    import inspect

    from sophiagraph.server import service_core

    source = inspect.getsource(service_core)
    assert "openminion" not in source, (
        "service_core.py must not reference openminion; KMSR import boundary"
    )
