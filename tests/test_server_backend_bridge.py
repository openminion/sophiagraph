"""KMSR-02 backend-bridge tests.

Verifies that `build_wired_registry` produces a ToolRegistry where data-op
handlers execute against a live `sophiagraph` store rather than raising
`BackendNotWiredError`.

Uses the in-memory `SophiaGraphMemoryStore` for fast deterministic coverage;
sqlite is exercised by one round-trip test via `tmp_path`.
"""

from __future__ import annotations

import pytest

from sophiagraph.server.backend import (
    BackendConfig,
    build_wired_registry,
)
from sophiagraph.server.contracts import BackendNotWiredError
from sophiagraph.server.tools import SUPPORTED_TOOL_NAMES, ToolRegistry


@pytest.fixture
def memory_registry():
    return build_wired_registry(BackendConfig(backend="memory"))


def test_wired_registry_registers_exactly_the_supported_eight(memory_registry):
    assert memory_registry.names() == tuple(sorted(SUPPORTED_TOOL_NAMES))


def test_wired_capabilities_returns_memory_backend(memory_registry):
    handler = memory_registry.get_handler("knowledge_capabilities")
    payload = handler()
    assert payload["backend"] == "memory"
    assert set(payload["supported_tools"]) == set(SUPPORTED_TOOL_NAMES)


def test_wired_data_op_handlers_do_not_raise_backend_not_wired(memory_registry):
    """Confirm KMSR-02 replaced the KMSR-01 stub handlers."""
    handler = memory_registry.get_handler("knowledge_get_record")
    # Calling with a non-existent record returns {'record': None}, not raises.
    result = handler(record_id="nonexistent")
    assert result == {"record": None}


def test_stub_registry_still_raises_backend_not_wired_when_explicit():
    """KMSR-01 stub registry preserved for --no-wire-backend mode."""
    stub_registry = ToolRegistry.default(backend="memory")
    handler = stub_registry.get_handler("knowledge_get_record")
    with pytest.raises(BackendNotWiredError):
        handler(record_id="anything")


def test_put_and_get_round_trip_through_wired_registry(memory_registry):
    put_handler = memory_registry.get_handler("knowledge_put_record")
    record_payload = {
        "id": "rec-1",
        "scope": "agent:test",
        "type": "fact",
        "content": {"text": "hello"},
        "created_at": "2026-05-27T00:00:00+00:00",
        "updated_at": "2026-05-27T00:00:00+00:00",
    }
    put_result = put_handler(record=record_payload)
    assert put_result == {"record_id": "rec-1"}

    get_handler = memory_registry.get_handler("knowledge_get_record")
    get_result = get_handler(record_id="rec-1")
    assert get_result["record"] is not None
    assert get_result["record"]["id"] == "rec-1"
    assert get_result["record"]["content"] == {"text": "hello"}


def test_list_records_returns_typed_list(memory_registry):
    put_handler = memory_registry.get_handler("knowledge_put_record")
    for i in range(3):
        put_handler(
            record={
                "id": f"list-rec-{i}",
                "scope": "agent:test",
                "type": "fact",
                "content": {"i": i},
                "created_at": "2026-05-27T00:00:00+00:00",
                "updated_at": "2026-05-27T00:00:00+00:00",
            }
        )

    list_handler = memory_registry.get_handler("knowledge_list_records")
    result = list_handler(filters={"scopes": ["agent:test"]})
    assert "records" in result
    assert len(result["records"]) == 3


def test_put_record_with_invalid_payload_returns_typed_error(memory_registry):
    from sophiagraph.server.backend import BackendInvocationError

    put_handler = memory_registry.get_handler("knowledge_put_record")
    with pytest.raises(BackendInvocationError) as excinfo:
        put_handler(record={"missing_required_fields": True})
    assert excinfo.value.tool_name == "knowledge_put_record"


def test_sqlite_backend_round_trips(tmp_path):
    sqlite_path = tmp_path / "kmsr02.sqlite3"
    registry = build_wired_registry(
        BackendConfig(backend="sqlite", sqlite_path=str(sqlite_path))
    )
    assert sqlite_path.parent.exists()

    capabilities = registry.get_handler("knowledge_capabilities")()
    assert capabilities["backend"] == "sqlite"

    put_handler = registry.get_handler("knowledge_put_record")
    put_handler(
        record={
            "id": "sqlite-rec-1",
            "scope": "agent:sqlite-test",
            "type": "fact",
            "content": {"text": "persisted"},
            "created_at": "2026-05-27T00:00:00+00:00",
            "updated_at": "2026-05-27T00:00:00+00:00",
        }
    )

    get_handler = registry.get_handler("knowledge_get_record")
    result = get_handler(record_id="sqlite-rec-1")
    assert result["record"]["content"] == {"text": "persisted"}


def test_unknown_backend_raises_typed_error():
    from sophiagraph.server.contracts import SophiagraphServerError

    with pytest.raises(SophiagraphServerError) as excinfo:
        build_wired_registry(BackendConfig(backend="redis"))
    assert "redis" in str(excinfo.value)
    assert excinfo.value.code == -32602
