"""Provider-free MCP-style adapter for SophiaGraph stores."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.models import MemoryRecord
from sophiagraph.portability.codec import record_from_dict
from sophiagraph.query import ListQueryOptions, SearchQueryOptions
from sophiagraph.storage.base import SophiaGraphStore

McpOperation = Literal["create", "read", "update", "delete", "search"]


@dataclass(frozen=True, slots=True)
class McpMemoryRequest:
    operation: McpOperation
    payload: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.operation not in {"create", "read", "update", "delete", "search"}:
            raise InvalidArgumentError(f"invalid MCP operation: {self.operation!r}")


@dataclass(frozen=True, slots=True)
class McpMemoryResponse:
    ok: bool
    operation: McpOperation
    payload: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


class SophiaGraphMcpAdapter:
    """Thin MCP host bridge over a structural SophiaGraph store."""

    def __init__(self, store: SophiaGraphStore) -> None:
        self._store = store

    def handle(self, request: McpMemoryRequest) -> McpMemoryResponse:
        try:
            payload = self._dispatch(request)
        except Exception as exc:  # noqa: BLE001 - adapter envelope boundary
            return McpMemoryResponse(
                ok=False,
                operation=request.operation,
                error=str(exc),
            )
        return McpMemoryResponse(
            ok=True,
            operation=request.operation,
            payload=payload,
        )

    def _dispatch(self, request: McpMemoryRequest) -> dict[str, Any]:
        if request.operation == "create":
            record = record_from_dict(dict(request.payload["record"]))
            return {"record_id": self._store.put_record(record)}
        if request.operation == "read":
            record = self._store.get_record(str(request.payload["record_id"]))
            return {"record": asdict(record) if record is not None else None}
        if request.operation == "update":
            record = self._store.get_record(str(request.payload["record_id"]))
            if record is None:
                raise InvalidArgumentError("record not found")
            merged = asdict(record)
            merged.update(dict(request.payload.get("patch", {})))
            updated = record_from_dict(merged)
            return {"record_id": self._store.put_record(updated)}
        if request.operation == "delete":
            record = self._store.tombstone_record(
                str(request.payload["record_id"]),
                deleted_at=str(request.payload["deleted_at"]),
                reason=str(request.payload.get("reason", "")),
            )
            return {"record": asdict(record)}
        query = SearchQueryOptions(
            query=str(request.payload["query"]),
            scopes=[str(scope) for scope in request.payload.get("scopes", [])],
            limit=int(request.payload.get("limit", 20)),
        )
        if not query.scopes:
            fallback = request.payload.get("scope")
            if fallback is None:
                raise InvalidArgumentError("search scopes are required")
            query.scopes.append(str(fallback))
        return {
            "records": [asdict(record) for record in self._store.search_records(query)]
        }

    def list_records(self, *, scopes: list[str], limit: int = 20) -> list[MemoryRecord]:
        return self._store.list_records(ListQueryOptions(scopes=scopes, limit=limit))


__all__ = [
    "McpMemoryRequest",
    "McpMemoryResponse",
    "SophiaGraphMcpAdapter",
]
