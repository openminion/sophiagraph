"""Optional asyncio facade over synchronous stores."""

from __future__ import annotations

import asyncio
from typing import Any


class AsyncSophiaGraphStore:
    def __init__(self, store: Any) -> None:
        self.store = store

    async def put_record(self, record: Any) -> str:
        return await asyncio.to_thread(self.store.put_record, record)

    async def get_record(self, record_id: str) -> Any:
        return await asyncio.to_thread(self.store.get_record, record_id)

    async def list_changes(self, **kwargs: Any) -> Any:
        return await asyncio.to_thread(self.store.list_changes, **kwargs)

    async def structural_search_records(self, query: Any, *, scopes: list[str]) -> Any:
        return await asyncio.to_thread(
            self.store.structural_search_records,
            query,
            scopes=scopes,
        )


def async_store(store: Any) -> AsyncSophiaGraphStore:
    return AsyncSophiaGraphStore(store)


__all__ = ["AsyncSophiaGraphStore", "async_store"]
