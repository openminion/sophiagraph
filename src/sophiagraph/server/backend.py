"""Backend bridge wiring the bounded KMSR v1 MCP tool surface onto
package-owned `sophiagraph` stores.

KMSR-02: replaces the `BackendNotWiredError` handlers in
`sophiagraph.server.tools.ToolRegistry.default()` with real invocations
against either `SophiaGraphMemoryStore` or `SophiaGraphSqliteStore` via the
public `sophiagraph` API only.

Import-boundary contract: ONLY public `sophiagraph` imports (verified by
`tests/test_imports.py`). No `openminion` import allowed.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from sophiagraph import (
    DEFAULT_DB_FILENAME,
    ListQueryOptions,
    MemoryRecord,
    SearchQueryOptions,
    create_memory_store,
    create_sqlite_store,
    default_db_path,
)
from sophiagraph.portability.models import (
    MemoryBundleExportOptions,
    MemoryBundleImportOptions,
)
from sophiagraph.storage.base import SophiaGraphStore

from sophiagraph.server.contracts import SophiagraphServerError
from sophiagraph.server.service_core import to_json_dict as _to_json_dict
from sophiagraph.server.tools import (
    SUPPORTED_TOOL_NAMES,
    ToolHandler,
    ToolRegistry,
)


@dataclass(frozen=True)
class BackendConfig:
    """Operator-config for backend selection.

    `backend` selects sqlite or memory; for sqlite, `sqlite_path` is the
    on-disk path (None uses `sophiagraph.default_db_path()`).
    """

    backend: str = "memory"
    sqlite_path: str | None = None


class BackendInvocationError(SophiagraphServerError):
    """Raised when a backend invocation fails structurally (typed wrap of
    sophiagraph errors). KMSR-02 maps these to the JSON-RPC error envelope."""

    def __init__(self, tool_name: str, original: Exception) -> None:
        super().__init__(
            f"backend invocation failed for {tool_name!r}: "
            f"{type(original).__name__}: {original}",
            code=-32030,
            details={
                "tool_name": tool_name,
                "original_type": type(original).__name__,
                "original_message": str(original),
            },
        )
        self.tool_name = tool_name
        self.original = original


def _resolve_store(config: BackendConfig) -> SophiaGraphStore:
    if config.backend == "memory":
        return create_memory_store()
    if config.backend == "sqlite":
        path = (
            Path(config.sqlite_path)
            if config.sqlite_path is not None
            else default_db_path() / DEFAULT_DB_FILENAME
        )
        return create_sqlite_store(path)
    raise SophiagraphServerError(
        f"unknown backend {config.backend!r}; supported: memory|sqlite",
        code=-32602,
        details={"backend": config.backend},
    )


def _wrap(tool_name: str, fn):
    def _handler(**kwargs: Any) -> Mapping[str, Any]:
        try:
            return fn(**kwargs)
        except SophiagraphServerError:
            raise
        except Exception as err:  # pragma: no cover - structural wrap
            raise BackendInvocationError(tool_name, err) from err

    return _handler


def _capabilities_handler(backend: str) -> ToolHandler:
    def _handler(**_kwargs: Any) -> Mapping[str, Any]:
        return {
            "protocol_version": "2025-06-18",
            "backend": backend,
            "supported_tools": list(SUPPORTED_TOOL_NAMES),
        }

    return _handler


def _put_record_handler(store: SophiaGraphStore) -> ToolHandler:
    def _handler(**kwargs: Any) -> Mapping[str, Any]:
        record_payload = kwargs.get("record") or {}
        if not isinstance(record_payload, Mapping):
            raise SophiagraphServerError(
                "knowledge_put_record: 'record' must be an object",
                code=-32602,
                details={"got_type": type(record_payload).__name__},
            )
        record = MemoryRecord(**dict(record_payload))
        record_id = store.put_record(record)
        return {"record_id": record_id}

    return _wrap("knowledge_put_record", _handler)


def _get_record_handler(store: SophiaGraphStore) -> ToolHandler:
    def _handler(**kwargs: Any) -> Mapping[str, Any]:
        record_id = str(kwargs.get("record_id") or "").strip()
        if not record_id:
            raise SophiagraphServerError(
                "knowledge_get_record: 'record_id' is required",
                code=-32602,
                details={},
            )
        record = store.get_record(record_id)
        return {"record": _to_json_dict(record)}

    return _wrap("knowledge_get_record", _handler)


def _list_records_handler(store: SophiaGraphStore) -> ToolHandler:
    def _handler(**kwargs: Any) -> Mapping[str, Any]:
        filters_payload = kwargs.get("filters") or {}
        if not isinstance(filters_payload, Mapping):
            raise SophiagraphServerError(
                "knowledge_list_records: 'filters' must be an object",
                code=-32602,
                details={"got_type": type(filters_payload).__name__},
            )
        options = ListQueryOptions(**dict(filters_payload))
        records = store.list_records(options)
        return {"records": [_to_json_dict(r) for r in records]}

    return _wrap("knowledge_list_records", _handler)


def _search_records_handler(store: SophiaGraphStore) -> ToolHandler:
    def _handler(**kwargs: Any) -> Mapping[str, Any]:
        query_payload = kwargs.get("query") or {}
        if not isinstance(query_payload, Mapping):
            raise SophiagraphServerError(
                "knowledge_search_records: 'query' must be an object",
                code=-32602,
                details={"got_type": type(query_payload).__name__},
            )
        options = SearchQueryOptions(**dict(query_payload))
        results = store.search_records(options)
        return {"results": [_to_json_dict(r) for r in results]}

    return _wrap("knowledge_search_records", _handler)


def _list_relations_handler(store: SophiaGraphStore) -> ToolHandler:
    def _handler(**kwargs: Any) -> Mapping[str, Any]:
        record_id = str(kwargs.get("record_id") or "").strip()
        if not record_id:
            raise SophiagraphServerError(
                "knowledge_list_relations: 'record_id' is required",
                code=-32602,
                details={},
            )
        filters_payload = kwargs.get("filters") or {}
        relations = store.list_relations(record_id, **dict(filters_payload))
        return {"relations": [_to_json_dict(r) for r in relations]}

    return _wrap("knowledge_list_relations", _handler)


def _export_snapshot_handler(store: SophiaGraphStore) -> ToolHandler:
    def _handler(**kwargs: Any) -> Mapping[str, Any]:
        options_payload = kwargs.get("options") or {}
        if not isinstance(options_payload, Mapping):
            raise SophiagraphServerError(
                "knowledge_export_snapshot: 'options' must be an object",
                code=-32602,
                details={"got_type": type(options_payload).__name__},
            )
        options = MemoryBundleExportOptions(**dict(options_payload))
        snapshot = store.export_snapshot(options)
        return {"bundle": _to_json_dict(snapshot)}

    return _wrap("knowledge_export_snapshot", _handler)


def _import_snapshot_handler(store: SophiaGraphStore) -> ToolHandler:
    def _handler(**kwargs: Any) -> Mapping[str, Any]:
        bundle_payload = kwargs.get("bundle") or {}
        if not isinstance(bundle_payload, Mapping):
            raise SophiagraphServerError(
                "knowledge_import_snapshot: 'bundle' must be an object",
                code=-32602,
                details={"got_type": type(bundle_payload).__name__},
            )
        options_payload = kwargs.get("options") or {}
        # Re-import the snapshot type from sophiagraph for validation
        from sophiagraph.portability.models import MemoryBundleSnapshot

        snapshot = MemoryBundleSnapshot(**dict(bundle_payload))
        options = MemoryBundleImportOptions(**dict(options_payload))
        result = store.import_snapshot(snapshot, options)
        return {"imported_count": int(result.imported_record_count)}

    return _wrap("knowledge_import_snapshot", _handler)


def build_wired_registry(config: BackendConfig | None = None) -> ToolRegistry:
    """Construct a ToolRegistry where data-op handlers are wired to a real store.

    Replaces ToolRegistry.default()'s BackendNotWiredError handlers. Schemas
    are reused verbatim from the closed surface in `sophiagraph.server.tools`.
    """

    resolved_config = config if config is not None else BackendConfig()
    store = _resolve_store(resolved_config)
    registry = ToolRegistry(backend=resolved_config.backend)

    from sophiagraph.server.tools import _TOOL_SCHEMAS  # type: ignore[attr-defined]

    handler_factories: dict[str, Any] = {
        "knowledge_capabilities": lambda: _capabilities_handler(
            resolved_config.backend
        ),
        "knowledge_put_record": lambda: _put_record_handler(store),
        "knowledge_get_record": lambda: _get_record_handler(store),
        "knowledge_list_records": lambda: _list_records_handler(store),
        "knowledge_search_records": lambda: _search_records_handler(store),
        "knowledge_list_relations": lambda: _list_relations_handler(store),
        "knowledge_export_snapshot": lambda: _export_snapshot_handler(store),
        "knowledge_import_snapshot": lambda: _import_snapshot_handler(store),
    }

    for schema in _TOOL_SCHEMAS:
        factory = handler_factories.get(schema.name)
        if factory is None:
            raise SophiagraphServerError(
                f"no backend handler factory registered for {schema.name!r}",
                code=-32603,
                details={"tool_name": schema.name},
            )
        registry.register(schema, factory())

    return registry


__all__ = [
    "BackendConfig",
    "BackendInvocationError",
    "build_wired_registry",
]
