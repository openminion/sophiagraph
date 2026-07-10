"""Surface-lock contract tests for the bounded KMSR v1 MCP tool registry.

Hard-locks the closed set of supported tools and the closed set of banned
semantic endpoints. Any drift fails the test immediately.
"""

from __future__ import annotations

import pytest

from sophiagraph.server.contracts import (
    BackendNotWiredError,
    SemanticEndpointRefusedError,
    TOOL_BACKEND_NOT_WIRED_CODE,
    TOOL_SEMANTIC_ENDPOINT_REFUSED_CODE,
)
from sophiagraph.server.tools import (
    BANNED_SEMANTIC_TOOL_NAMES,
    SUPPORTED_TOOL_NAMES,
    ToolRegistry,
    ToolSchema,
)


def test_supported_tool_set_is_exactly_the_kmsr_v1_eight() -> None:
    assert SUPPORTED_TOOL_NAMES == (
        "knowledge_capabilities",
        "knowledge_put_record",
        "knowledge_get_record",
        "knowledge_list_records",
        "knowledge_search_records",
        "knowledge_list_relations",
        "knowledge_export_snapshot",
        "knowledge_import_snapshot",
    )


def test_default_registry_registers_exactly_the_supported_eight() -> None:
    registry = ToolRegistry.default()
    assert registry.names() == tuple(sorted(SUPPORTED_TOOL_NAMES))


def test_banned_semantic_endpoints_are_a_nonempty_closed_set() -> None:
    assert isinstance(BANNED_SEMANTIC_TOOL_NAMES, frozenset)
    # Core anti-LLM bans listed in the spec
    for required in ("summarize", "classify", "extract_claims", "infer_category"):
        assert required in BANNED_SEMANTIC_TOOL_NAMES
    # The knowledge-prefixed mirror is also banned
    for required in (
        "knowledge_summarize",
        "knowledge_classify",
        "knowledge_extract_claims",
        "knowledge_infer_category",
    ):
        assert required in BANNED_SEMANTIC_TOOL_NAMES
    # Supported and banned sets are disjoint
    assert set(SUPPORTED_TOOL_NAMES).isdisjoint(BANNED_SEMANTIC_TOOL_NAMES)


@pytest.mark.parametrize(
    "banned_name",
    sorted(BANNED_SEMANTIC_TOOL_NAMES),
)
def test_registry_refuses_to_register_banned_semantic_tools(banned_name: str) -> None:
    registry = ToolRegistry()
    schema = ToolSchema(
        name=banned_name,
        description="anti-LLM lock violation attempt",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
    )
    with pytest.raises(SemanticEndpointRefusedError) as excinfo:
        registry.register(schema, lambda **_: {})
    assert excinfo.value.code == TOOL_SEMANTIC_ENDPOINT_REFUSED_CODE


def test_registry_refuses_to_register_unknown_tools() -> None:
    registry = ToolRegistry()
    schema = ToolSchema(
        name="knowledge_invent_a_new_tool",
        description="surface-widening attempt",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
    )
    with pytest.raises(ValueError, match="not in the bounded v1 supported set"):
        registry.register(schema, lambda **_: {})


def test_registry_get_handler_for_banned_name_raises_typed_refusal() -> None:
    registry = ToolRegistry.default()
    with pytest.raises(SemanticEndpointRefusedError):
        registry.get_handler("summarize")


def test_data_op_handlers_raise_backend_not_wired_until_kmsr_02() -> None:
    registry = ToolRegistry.default()
    handler = registry.get_handler("knowledge_get_record")
    with pytest.raises(BackendNotWiredError) as excinfo:
        handler(record_id="rec-1")
    assert excinfo.value.code == TOOL_BACKEND_NOT_WIRED_CODE
    assert excinfo.value.details == {
        "tool_name": "knowledge_get_record",
        "blocker": "KMSR-02",
    }


def test_capabilities_handler_returns_typed_payload_without_backend() -> None:
    registry = ToolRegistry.default(backend="sqlite")
    handler = registry.get_handler("knowledge_capabilities")
    payload = handler()
    assert payload["backend"] == "sqlite"
    assert payload["protocol_version"] == "2025-06-18"
    assert set(payload["supported_tools"]) == set(SUPPORTED_TOOL_NAMES)


def test_each_supported_tool_has_typed_input_and_output_schema() -> None:
    registry = ToolRegistry.default()
    for schema in registry.schemas():
        assert schema.input_schema.get("type") == "object"
        assert schema.output_schema.get("type") == "object"
        assert schema.description
