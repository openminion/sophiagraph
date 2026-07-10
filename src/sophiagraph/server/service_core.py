"""Shared service-core helpers for MCP and future REST transports (SSSF-03).

This module owns the **single source of truth** for service-level DTO names,
field shapes, and the JSON serialization boundary. Both the MCP runtime
(today) and the future REST runtime (per SSSF-02) MUST consume these helpers
rather than re-deriving payload shapes. Contract drift tests fail if any
transport payload name diverges from the canonical names declared here.

Three layers:

1. ``REQUEST_PAYLOAD_KEYS`` — closed registry mapping each
   ``SUPPORTED_TOOL_NAMES`` entry to the canonical request envelope keys it
   accepts (e.g. ``knowledge_put_record`` → ``("record",)``).
2. ``RESPONSE_PAYLOAD_KEYS`` — closed registry of canonical response envelope
   keys (e.g. ``knowledge_get_record`` → ``("record",)``).
3. ``to_json_dict`` — the canonical serializer for ``sophiagraph`` package
   DTOs into a JSON-friendly dict. Promoted from the previously-private
   ``backend._to_json_dict``.

Anti-LLM boundary: this module never invents fields, summaries, or labels.
It transports typed structural data only.
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any, Mapping

from sophiagraph.server.tools import SUPPORTED_TOOL_NAMES


# ---------------------------------------------------------------------------
# Canonical request and response envelope key registries.
# ---------------------------------------------------------------------------


REQUEST_PAYLOAD_KEYS: Mapping[str, tuple[str, ...]] = {
    "knowledge_capabilities": (),
    "knowledge_put_record": ("record",),
    "knowledge_get_record": ("record_id",),
    "knowledge_list_records": ("filters",),
    "knowledge_search_records": ("query",),
    "knowledge_list_relations": ("record_id", "filters"),
    "knowledge_export_snapshot": ("options",),
    "knowledge_import_snapshot": ("bundle", "options"),
}


RESPONSE_PAYLOAD_KEYS: Mapping[str, tuple[str, ...]] = {
    "knowledge_capabilities": ("protocol_version", "backend", "supported_tools"),
    "knowledge_put_record": ("record_id",),
    "knowledge_get_record": ("record",),
    "knowledge_list_records": ("records",),
    "knowledge_search_records": ("results",),
    "knowledge_list_relations": ("relations",),
    "knowledge_export_snapshot": ("bundle",),
    "knowledge_import_snapshot": ("imported_count",),
}


# ---------------------------------------------------------------------------
# Canonical serializer for sophiagraph DTOs.
# ---------------------------------------------------------------------------


def to_json_dict(obj: Any) -> Any:
    """Serialize a sophiagraph dataclass or Pydantic model to a JSON-friendly dict.

    Promoted from ``backend._to_json_dict`` to public service-core surface so
    both the MCP runtime and the future REST runtime use the same boundary
    function. Behavior is intentionally simple — no field renaming, no NLP, no
    semantic enrichment.
    """

    if obj is None:
        return None
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    if is_dataclass(obj):
        return asdict(obj)
    return obj


# ---------------------------------------------------------------------------
# Contract surface validators (used by tests; cheap enough to expose).
# ---------------------------------------------------------------------------


def assert_request_keys_subset(tool_name: str, payload_keys: set[str]) -> None:
    """Raise ``ValueError`` if ``payload_keys`` is not a subset of the canonical
    request envelope for ``tool_name``.

    Used by transport-layer parsers (MCP today, REST tomorrow) to deterministically
    reject unknown fields with ``JSONRPC_INVALID_PARAMS`` semantics.
    """

    if tool_name not in REQUEST_PAYLOAD_KEYS:
        raise ValueError(
            f"unknown tool name {tool_name!r}; not in SUPPORTED_TOOL_NAMES"
        )
    allowed = set(REQUEST_PAYLOAD_KEYS[tool_name])
    extras = payload_keys - allowed
    if extras:
        raise ValueError(
            f"tool {tool_name!r}: unknown request fields {sorted(extras)}; "
            f"allowed: {sorted(allowed)}"
        )


def canonical_response_keys(tool_name: str) -> tuple[str, ...]:
    """Return the canonical response envelope keys for ``tool_name``.

    Future REST handlers MUST emit exactly these keys in their response body.
    """

    if tool_name not in RESPONSE_PAYLOAD_KEYS:
        raise ValueError(
            f"unknown tool name {tool_name!r}; not in SUPPORTED_TOOL_NAMES"
        )
    return RESPONSE_PAYLOAD_KEYS[tool_name]


# ---------------------------------------------------------------------------
# Self-test the registry stays aligned with SUPPORTED_TOOL_NAMES at import.
# ---------------------------------------------------------------------------


def _verify_registry_alignment() -> None:
    supported = set(SUPPORTED_TOOL_NAMES)
    request_keyset = set(REQUEST_PAYLOAD_KEYS.keys())
    response_keyset = set(RESPONSE_PAYLOAD_KEYS.keys())
    if request_keyset != supported:
        raise RuntimeError(
            "REQUEST_PAYLOAD_KEYS is not aligned with SUPPORTED_TOOL_NAMES; "
            f"only in request: {sorted(request_keyset - supported)}; "
            f"only in supported: {sorted(supported - request_keyset)}"
        )
    if response_keyset != supported:
        raise RuntimeError(
            "RESPONSE_PAYLOAD_KEYS is not aligned with SUPPORTED_TOOL_NAMES; "
            f"only in response: {sorted(response_keyset - supported)}; "
            f"only in supported: {sorted(supported - response_keyset)}"
        )


_verify_registry_alignment()


__all__ = [
    "REQUEST_PAYLOAD_KEYS",
    "RESPONSE_PAYLOAD_KEYS",
    "assert_request_keys_subset",
    "canonical_response_keys",
    "to_json_dict",
]
