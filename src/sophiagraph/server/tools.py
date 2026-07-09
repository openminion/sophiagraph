"""Typed MCP tool surface for the bounded sophiagraph-server v1.

Defines exactly the eight tools listed in the KMSR spec's "Proposed MCP v1
surface" section. KMSR-01 (this file) ships the typed contract and registry;
KMSR-02 will replace the `BackendNotWiredError`-raising handlers with real
`sophiagraph` backend calls.

The anti-LLM boundary is enforced as a closed set of banned tool names; any
attempt to register or invoke a name in the banned set is refused.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from sophiagraph.server.contracts import (
    BackendNotWiredError,
    SemanticEndpointRefusedError,
)


# Closed enum of supported tool names. The runtime registers exactly these
# eight and refuses to register anything else. Contract tests assert the
# registry contents equal this set exactly.
SUPPORTED_TOOL_NAMES: tuple[str, ...] = (
    "knowledge_capabilities",
    "knowledge_put_record",
    "knowledge_get_record",
    "knowledge_list_records",
    "knowledge_search_records",
    "knowledge_list_relations",
    "knowledge_export_snapshot",
    "knowledge_import_snapshot",
)

# Closed enum of explicitly banned semantic endpoints. Refusal is
# deterministic via `SemanticEndpointRefusedError`; the runtime does NOT
# silently drop or 404 these — it returns the typed refusal error so callers
# get an unambiguous signal.
BANNED_SEMANTIC_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "summarize",
        "classify",
        "extract_claims",
        "infer_category",
        "promote_memory_importance",
        "knowledge_summarize",
        "knowledge_classify",
        "knowledge_extract_claims",
        "knowledge_infer_category",
        "knowledge_promote_memory_importance",
    }
)


@dataclass(frozen=True)
class ToolSchema:
    """Typed schema for a single MCP tool.

    `input_schema` and `output_schema` are JSON-Schema-compatible dicts using
    only primitive types + references to canonical `sophiagraph` contract
    field names. KMSR-02 will replace placeholders with full canonical schemas
    drawn directly from `sophiagraph` public types.
    """

    name: str
    description: str
    input_schema: Mapping[str, Any]
    output_schema: Mapping[str, Any]


# JSON-Schema-ish typed surface for the 8 supported tools. KMSR-02 will refine
# `output_schema` shapes against canonical sophiagraph dataclasses.
_TOOL_SCHEMAS: tuple[ToolSchema, ...] = (
    ToolSchema(
        name="knowledge_capabilities",
        description=(
            "Return supported backend type and runtime capabilities. "
            "Plumbing-only; never invokes an LLM."
        ),
        input_schema={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "required": ["protocol_version", "backend", "supported_tools"],
            "properties": {
                "protocol_version": {"type": "string"},
                "backend": {"type": "string", "enum": ["sqlite", "memory"]},
                "supported_tools": {"type": "array", "items": {"type": "string"}},
            },
            "additionalProperties": False,
        },
    ),
    ToolSchema(
        name="knowledge_put_record",
        description=(
            "Create or replace a record using the canonical sophiagraph "
            "MemoryRecord contract. Operator-authored payload; runtime does "
            "not synthesize content."
        ),
        input_schema={
            "type": "object",
            "required": ["record"],
            "properties": {"record": {"type": "object"}},
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "required": ["record_id"],
            "properties": {"record_id": {"type": "string"}},
            "additionalProperties": False,
        },
    ),
    ToolSchema(
        name="knowledge_get_record",
        description="Fetch a record by id from the package-owned store.",
        input_schema={
            "type": "object",
            "required": ["record_id"],
            "properties": {"record_id": {"type": "string"}},
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "required": ["record"],
            "properties": {"record": {"type": "object"}},
            "additionalProperties": False,
        },
    ),
    ToolSchema(
        name="knowledge_list_records",
        description=(
            "List records by typed filters (scopes/types/tier). Filter "
            "semantics are operator-supplied; runtime does not LLM-rewrite "
            "queries."
        ),
        input_schema={
            "type": "object",
            "properties": {"filters": {"type": "object"}},
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "required": ["records"],
            "properties": {"records": {"type": "array", "items": {"type": "object"}}},
            "additionalProperties": False,
        },
    ),
    ToolSchema(
        name="knowledge_search_records",
        description=(
            "Search records using the package's typed search contract "
            "(SearchQueryOptions). Runtime does not LLM-rerank results."
        ),
        input_schema={
            "type": "object",
            "required": ["query"],
            "properties": {"query": {"type": "object"}},
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "required": ["results"],
            "properties": {"results": {"type": "array", "items": {"type": "object"}}},
            "additionalProperties": False,
        },
    ),
    ToolSchema(
        name="knowledge_list_relations",
        description="Inspect relation edges for a record by typed filter.",
        input_schema={
            "type": "object",
            "required": ["record_id"],
            "properties": {
                "record_id": {"type": "string"},
                "filters": {"type": "object"},
            },
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "required": ["relations"],
            "properties": {"relations": {"type": "array", "items": {"type": "object"}}},
            "additionalProperties": False,
        },
    ),
    ToolSchema(
        name="knowledge_export_snapshot",
        description=(
            "Export a typed portability bundle via the package's portability "
            "codec. Runtime does not summarize or transform records on export."
        ),
        input_schema={
            "type": "object",
            "properties": {"options": {"type": "object"}},
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "required": ["bundle"],
            "properties": {"bundle": {"type": "object"}},
            "additionalProperties": False,
        },
    ),
    ToolSchema(
        name="knowledge_import_snapshot",
        description=(
            "Import a typed portability bundle via the package's portability "
            "codec. Runtime does not synthesize or filter records on import."
        ),
        input_schema={
            "type": "object",
            "required": ["bundle"],
            "properties": {
                "bundle": {"type": "object"},
                "options": {"type": "object"},
            },
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "required": ["imported_count"],
            "properties": {"imported_count": {"type": "integer", "minimum": 0}},
            "additionalProperties": False,
        },
    ),
)


# Handler signature: synchronous, takes typed kwargs from JSON-RPC params,
# returns a JSON-serializable mapping. KMSR-01 ships handlers that raise
# `BackendNotWiredError`; KMSR-02 swaps these for real backend invocations.
ToolHandler = Callable[..., Mapping[str, Any]]


def _backend_not_wired_handler(tool_name: str) -> ToolHandler:
    def _handler(**_kwargs: Any) -> Mapping[str, Any]:
        raise BackendNotWiredError(tool_name)

    return _handler


def _capabilities_handler_factory(backend: str) -> ToolHandler:
    """Handler for `knowledge_capabilities`. Backend wiring still pending."""

    def _handler(**_kwargs: Any) -> Mapping[str, Any]:
        return {
            "protocol_version": "2025-06-18",
            "backend": backend,
            "supported_tools": list(SUPPORTED_TOOL_NAMES),
        }

    return _handler


@dataclass
class ToolRegistry:
    """Closed-surface registry for the bounded MCP v1 tool set.

    Construction enforces the SUPPORTED/BANNED contract:
    - `register` refuses any name outside `SUPPORTED_TOOL_NAMES`
    - `register` refuses any name inside `BANNED_SEMANTIC_TOOL_NAMES`
    - `default(backend)` returns a registry pre-populated with all 8 supported
      tools, with all data-op handlers raising `BackendNotWiredError`
    """

    backend: str = "memory"
    _handlers: dict[str, ToolHandler] = field(default_factory=dict)
    _schemas: dict[str, ToolSchema] = field(default_factory=dict)

    @classmethod
    def default(cls, *, backend: str = "memory") -> "ToolRegistry":
        registry = cls(backend=backend)
        for schema in _TOOL_SCHEMAS:
            if schema.name == "knowledge_capabilities":
                handler = _capabilities_handler_factory(backend)
            else:
                handler = _backend_not_wired_handler(schema.name)
            registry.register(schema, handler)
        return registry

    def register(self, schema: ToolSchema, handler: ToolHandler) -> None:
        if schema.name in BANNED_SEMANTIC_TOOL_NAMES:
            raise SemanticEndpointRefusedError(schema.name)
        if schema.name not in SUPPORTED_TOOL_NAMES:
            raise ValueError(
                f"tool {schema.name!r} is not in the bounded v1 supported set; "
                "widening requires a spec update"
            )
        self._handlers[schema.name] = handler
        self._schemas[schema.name] = schema

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._handlers.keys()))

    def schemas(self) -> tuple[ToolSchema, ...]:
        return tuple(self._schemas[name] for name in sorted(self._schemas.keys()))

    def get_handler(self, name: str) -> ToolHandler:
        if name in BANNED_SEMANTIC_TOOL_NAMES:
            raise SemanticEndpointRefusedError(name)
        if name not in self._handlers:
            raise KeyError(name)
        return self._handlers[name]

    def get_schema(self, name: str) -> ToolSchema:
        if name not in self._schemas:
            raise KeyError(name)
        return self._schemas[name]


__all__ = [
    "SUPPORTED_TOOL_NAMES",
    "BANNED_SEMANTIC_TOOL_NAMES",
    "ToolHandler",
    "ToolRegistry",
    "ToolSchema",
]
