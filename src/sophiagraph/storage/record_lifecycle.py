"""Record filtering and lifecycle helpers for storage backends."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Callable, Iterable

from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.models import MemoryRecord
from sophiagraph.temporal import utc_now_iso


def record_matches_query(
    record: MemoryRecord,
    query: str,
    *,
    content_serializer: Callable[[Any], str] | None = None,
) -> bool:
    needle = str(query or "").strip().lower()
    if not needle:
        return True
    serialize = str if content_serializer is None else content_serializer
    content = (
        record.content if isinstance(record.content, str) else serialize(record.content)
    )
    haystack = "\n".join(
        part
        for part in [
            record.title or "",
            record.key or "",
            content,
            " ".join(record.tags),
            " ".join(record.entities),
        ]
        if part
    ).lower()
    return needle in haystack


def record_matches_namespaces(
    record: MemoryRecord,
    namespaces: Iterable[Any] | None,
) -> bool:
    if not namespaces:
        return True
    record_namespace = record.effective_namespace
    return any(record_namespace.matches(namespace) for namespace in namespaces)


def require_record(record: MemoryRecord | None, record_id: str) -> MemoryRecord:
    if record is None:
        raise InvalidArgumentError(f"unknown record_id: {record_id}")
    return record


def invalidated_record(
    record: MemoryRecord,
    *,
    valid_to: str,
    reason: str,
) -> MemoryRecord:
    return replace(
        record,
        valid_to=str(valid_to),
        supersession_reason=str(reason or record.supersession_reason or ""),
        updated_at=utc_now_iso(),
    )


def superseded_record(
    record: MemoryRecord,
    *,
    new_record: MemoryRecord | None,
    new_record_id: str,
    reason: str,
) -> MemoryRecord:
    return replace(
        record,
        valid_to=new_record.created_at if new_record is not None else utc_now_iso(),
        superseded_by_id=new_record_id,
        supersession_reason=str(reason or "superseded"),
        updated_at=utc_now_iso(),
    )


class RecordLifecycleMixin:
    def get_record(self, record_id: str) -> MemoryRecord | None:
        raise NotImplementedError

    def put_record(self, record: MemoryRecord) -> str:
        raise NotImplementedError

    def invalidate_record(
        self,
        record_id: str,
        *,
        valid_to: str,
        reason: str,
    ) -> MemoryRecord:
        record = require_record(self.get_record(record_id), record_id)
        updated = invalidated_record(record, valid_to=valid_to, reason=reason)
        self.put_record(updated)
        return updated

    def supersede_record(
        self,
        old_record_id: str,
        new_record_id: str,
        reason: str = "",
    ) -> MemoryRecord:
        record = require_record(self.get_record(old_record_id), old_record_id)
        updated = superseded_record(
            record,
            new_record=self.get_record(new_record_id),
            new_record_id=new_record_id,
            reason=reason,
        )
        self.put_record(updated)
        return updated
