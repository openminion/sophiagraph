"""In-memory changefeed helpers for storage backends."""

from __future__ import annotations

from dataclasses import replace
from typing import Any
from uuid import uuid4

from sophiagraph.models import MemoryEmbedding, MemoryNamespace, SophiaGraphChangeEvent
from sophiagraph.storage.projection_state import embedding_change_payload
from sophiagraph.storage.record_lifecycle import utc_now_iso


class MemoryChangefeedMixin:
    _changes: list[SophiaGraphChangeEvent]
    _next_cursor: int

    def _has_change(self, event: SophiaGraphChangeEvent) -> bool:
        return any(
            existing.event_id == event.event_id
            or (
                bool(event.idempotency_key)
                and existing.idempotency_key == event.idempotency_key
            )
            for existing in self._changes
        )

    def _append_change(self, event: SophiaGraphChangeEvent) -> None:
        if self._has_change(event):
            return
        self._changes.append(replace(event, cursor=self._next_cursor))
        self._next_cursor += 1

    def _emit_change(
        self,
        *,
        object_type: str,
        object_id: str,
        payload: dict[str, Any],
        namespace: MemoryNamespace,
        schema_identifiers: dict[str, str],
        operation: str = "put",
        idempotency_key: str | None = None,
    ) -> None:
        self._append_change(
            SophiaGraphChangeEvent(
                event_id=f"chg-{uuid4()}",
                object_type=object_type,  # type: ignore[arg-type]
                object_id=object_id,
                operation=operation,  # type: ignore[arg-type]
                changed_at=utc_now_iso(),
                payload=payload,
                namespace=namespace,
                schema_identifiers=schema_identifiers,
                idempotency_key=idempotency_key,
            )
        )

    def _emit_embedding_change(
        self, embedding: MemoryEmbedding, *, operation: str = "put"
    ) -> None:
        self._emit_change(
            object_type="embedding",
            object_id=embedding.key,
            payload=embedding_change_payload(embedding),
            namespace=embedding.namespace,
            schema_identifiers={"node_label": "embedding"},
            operation=operation,
            idempotency_key=(
                f"embedding:{embedding.key}:{embedding.updated_at}:{operation}"
            ),
        )


__all__ = ["MemoryChangefeedMixin"]
