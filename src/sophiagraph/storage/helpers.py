"""Shared storage helpers for package-local record filtering and timestamps."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Iterable

from sophiagraph.models import MemoryRecord


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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
