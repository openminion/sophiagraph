"""Durable at-least-once delivery from the canonical changefeed to indexes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from sophiagraph.contracts.errors import InvalidArgumentError, ProjectionFenceError
from sophiagraph.graph_backends import (
    GraphBackendAdapter,
    GraphExportBatch,
    GraphExportEdge,
    GraphExportNode,
)
from sophiagraph.models import (
    MemoryEmbedding,
    MemoryNamespace,
    ProjectionAttempt,
    ProjectionBatchResult,
    ProjectionCheckpoint,
    ProjectionFailure,
    ProjectionFailureReason,
    ProjectionHealth,
    ProjectionLease,
    ProjectionTarget,
    SophiaGraphChangeEvent,
)
from sophiagraph.schema import GraphSchema
from sophiagraph.storage.projection_state import (
    bounded_error_message,
    is_expired,
    iso_after,
    structural_hash,
)
from sophiagraph.telemetry import (
    NullTelemetrySink,
    TelemetryEvent,
    TelemetrySink,
    safe_telemetry_attributes,
    trace_operation,
)
from sophiagraph.vector_backends import StoredVectorBackend, VectorPoint

ProjectionApplyStatus = Literal["applied", "skipped"]


class ProjectionStateStore(Protocol):
    def get_projection_target(self, target_id: str) -> ProjectionTarget | None: ...
    def get_projection_checkpoint(self, target_id: str) -> ProjectionCheckpoint: ...
    def get_projection_lease(self, target_id: str) -> ProjectionLease | None: ...
    def acquire_projection_lease(
        self, *, target_id: str, owner_id: str, now: str
    ) -> ProjectionLease: ...
    def release_projection_lease(
        self, *, target_id: str, owner_id: str, fencing_token: int
    ) -> None: ...
    def advance_projection_checkpoint(
        self, checkpoint: ProjectionCheckpoint, *, fencing_token: int, now: str
    ) -> None: ...
    def record_projection_attempt(self, attempt: ProjectionAttempt) -> None: ...
    def list_projection_attempts(
        self, *, target_id: str, event_id: str | None = None
    ) -> list[ProjectionAttempt]: ...
    def put_projection_failure(self, failure: ProjectionFailure) -> None: ...
    def clear_projection_failure(self, *, target_id: str, event_id: str) -> None: ...
    def list_projection_failures(
        self, *, target_id: str, dead_letter: bool | None = None
    ) -> list[ProjectionFailure]: ...
    def list_changes(
        self,
        *,
        since_cursor: int | None = None,
        limit: int | None = None,
        namespaces: list[MemoryNamespace] | None = None,
    ) -> list[SophiaGraphChangeEvent]: ...
    def get_embedding(
        self, record_id: str, vector_space: str
    ) -> MemoryEmbedding | None: ...


class ChangeProjector(Protocol):
    def apply(self, event: SophiaGraphChangeEvent) -> ProjectionApplyStatus: ...
    def set_watermark(self, cursor: int) -> str | None: ...
    def get_watermark(self) -> str | None: ...


@dataclass(frozen=True, slots=True)
class _EventProjectionResult:
    checkpoint: ProjectionCheckpoint | None
    status: ProjectionApplyStatus | None
    failure: ProjectionFailure | None
    target_watermark: str | None


def _event_hash(event: SophiaGraphChangeEvent) -> str:
    return str(event.payload.get("version_hash") or structural_hash(event.payload))


def _privacy_allows_projection(event: SophiaGraphChangeEvent) -> bool:
    meta = event.payload.get("meta")
    if not isinstance(meta, dict):
        return True
    privacy = meta.get("sophiagraph_privacy")
    if not isinstance(privacy, dict):
        return True
    return privacy.get("export_visibility") == "visible"


class GraphChangeProjector:
    def __init__(self, adapter: GraphBackendAdapter) -> None:
        self._adapter = adapter

    def apply(self, event: SophiaGraphChangeEvent) -> ProjectionApplyStatus:
        if event.object_type == "record":
            if event.operation == "delete" or not _privacy_allows_projection(event):
                self._adapter.delete(node_ids=(event.object_id,), edge_ids=())
                return "applied"
            label = event.schema_identifiers.get("node_label", "record")
            self._adapter.upsert_batch(
                GraphExportBatch(
                    batch_id=event.event_id,
                    schema=GraphSchema(node_labels=[label], relation_types=[]),
                    nodes=[
                        GraphExportNode(
                            node_id=event.object_id,
                            labels=[label],
                            namespace=event.namespace,
                            properties=dict(event.payload),
                            version_hash=_event_hash(event),
                        )
                    ],
                    source_cursor_start=event.cursor,
                    source_cursor_end=event.cursor,
                    source_event_ids=(event.event_id,),
                )
            )
            return "applied"
        if event.object_type not in {"relation", "link"}:
            return "skipped"
        if event.operation == "delete":
            self._adapter.delete(node_ids=(), edge_ids=(event.object_id,))
            return "applied"
        source = str(event.payload.get("source_record_id") or "")
        target = str(event.payload.get("target_record_id") or "")
        if not source or not target:
            return "skipped"
        relation_type = str(
            event.schema_identifiers.get("relation_type")
            or event.payload.get("relation_type")
            or event.object_type
        )
        self._adapter.upsert_batch(
            GraphExportBatch(
                batch_id=event.event_id,
                schema=GraphSchema(node_labels=[], relation_types=[relation_type]),
                edges=[
                    GraphExportEdge(
                        edge_id=event.object_id,
                        source_node_id=source,
                        target_node_id=target,
                        relation_type=relation_type,
                        namespace=event.namespace,
                        properties=dict(event.payload),
                        version_hash=_event_hash(event),
                    )
                ],
                source_cursor_start=event.cursor,
                source_cursor_end=event.cursor,
                source_event_ids=(event.event_id,),
            )
        )
        return "applied"

    def set_watermark(self, cursor: int) -> str | None:
        if not self._adapter.capabilities().supports("projection_watermark"):
            return None
        self._adapter.set_projection_watermark(cursor)
        return str(cursor)

    def get_watermark(self) -> str | None:
        if not self._adapter.capabilities().supports("projection_watermark"):
            return None
        value = self._adapter.get_projection_watermark()
        return str(value) if value is not None else None


class VectorChangeProjector:
    def __init__(
        self, store: ProjectionStateStore, adapter: StoredVectorBackend
    ) -> None:
        self._store = store
        self._adapter = adapter

    def apply(self, event: SophiaGraphChangeEvent) -> ProjectionApplyStatus:
        if event.object_type != "embedding":
            return "skipped"
        point_id = str(event.payload.get("point_id") or event.object_id)
        if event.operation == "delete":
            self._adapter.delete((point_id,))
            return "applied"
        record_id = str(event.payload.get("record_id") or "")
        vector_space = str(event.payload.get("vector_space") or "")
        embedding = self._store.get_embedding(record_id, vector_space)
        if embedding is None or embedding.vector is None:
            raise InvalidArgumentError("canonical embedding vector is unavailable")
        self._adapter.upsert(
            (
                VectorPoint(
                    point_id=point_id,
                    vector=tuple(float(value) for value in embedding.vector),
                    vector_space=embedding.vector_space,
                    namespace=embedding.namespace,
                    payload={"record_id": embedding.record_id},
                    version_hash=_event_hash(event),
                ),
            )
        )
        return "applied"

    def set_watermark(self, cursor: int) -> str | None:
        if not self._adapter.capabilities().projection_watermark:
            return None
        self._adapter.set_projection_watermark(cursor)
        return str(cursor)

    def get_watermark(self) -> str | None:
        if not self._adapter.capabilities().projection_watermark:
            return None
        value = self._adapter.get_projection_watermark()
        return str(value) if value is not None else None


def _retry_ready(failure: ProjectionFailure, now: str) -> bool:
    return (
        not failure.dead_letter
        and failure.retryable
        and (failure.next_retry_at is None or is_expired(failure.next_retry_at, now))
    )


def _validate_event_order(
    events: list[SophiaGraphChangeEvent], *, after_cursor: int
) -> None:
    previous = after_cursor
    for event in events:
        if event.cursor is None or event.cursor <= previous:
            raise InvalidArgumentError("projection event cursor is out of order")
        previous = event.cursor


def _record_failure(
    store: ProjectionStateStore,
    *,
    target: ProjectionTarget,
    event: SophiaGraphChangeEvent,
    attempt_number: int,
    reason: ProjectionFailureReason,
    error: Exception,
    now: str,
) -> ProjectionFailure:
    dead_letter = attempt_number >= target.max_attempts
    retry_seconds = min(300, 2 ** max(0, attempt_number - 1))
    failure = ProjectionFailure(
        target_id=target.target_id,
        event_id=event.event_id,
        cursor=int(event.cursor or 0),
        attempt_count=attempt_number,
        reason=reason,
        retryable=not dead_letter,
        dead_letter=dead_letter,
        updated_at=now,
        next_retry_at=None if dead_letter else iso_after(now, retry_seconds),
        error_message=bounded_error_message(type(error).__name__),
    )
    store.put_projection_failure(failure)
    store.record_projection_attempt(
        ProjectionAttempt(
            attempt_id=f"{target.target_id}:{event.event_id}:{attempt_number}",
            target_id=target.target_id,
            event_id=event.event_id,
            cursor=int(event.cursor or 0),
            attempt_number=attempt_number,
            status="failed",
            started_at=now,
            completed_at=now,
            next_retry_at=failure.next_retry_at,
            error_code=reason,
            error_message=failure.error_message,
        )
    )
    return failure


def _project_event(
    store: ProjectionStateStore,
    *,
    target: ProjectionTarget,
    projector: ChangeProjector,
    event: SophiaGraphChangeEvent,
    lease: ProjectionLease,
    attempt_number: int,
    now: str,
    current_watermark: str | None,
    sink: TelemetrySink,
) -> _EventProjectionResult:
    try:
        with trace_operation(
            sink,
            "sophiagraph.projection.apply",
            attributes={
                "backend": target.adapter_name,
                "object_type": event.object_type,
                "stage": "target_write",
            },
        ):
            status = projector.apply(event)
            target_watermark = projector.set_watermark(int(event.cursor))
    except Exception as exc:  # noqa: BLE001 - adapter boundary becomes durable state
        failure = _record_failure(
            store,
            target=target,
            event=event,
            attempt_number=attempt_number,
            reason="target_write_failed",
            error=exc,
            now=now,
        )
        return _EventProjectionResult(None, None, failure, current_watermark)

    checkpoint = ProjectionCheckpoint(
        target_id=target.target_id,
        cursor=int(event.cursor),
        event_id=event.event_id,
        updated_at=now,
        target_watermark=target_watermark,
    )
    try:
        store.advance_projection_checkpoint(
            checkpoint,
            fencing_token=lease.fencing_token,
            now=now,
        )
    except Exception as exc:  # noqa: BLE001 - checkpoint boundary becomes durable state
        failure = _record_failure(
            store,
            target=target,
            event=event,
            attempt_number=attempt_number,
            reason="checkpoint_write_failed",
            error=exc,
            now=now,
        )
        return _EventProjectionResult(None, None, failure, target_watermark)

    store.clear_projection_failure(
        target_id=target.target_id,
        event_id=event.event_id,
    )
    store.record_projection_attempt(
        ProjectionAttempt(
            attempt_id=f"{target.target_id}:{event.event_id}:{attempt_number}",
            target_id=target.target_id,
            event_id=event.event_id,
            cursor=int(event.cursor),
            attempt_number=attempt_number,
            status=status,
            started_at=now,
            completed_at=now,
        )
    )
    return _EventProjectionResult(checkpoint, status, None, target_watermark)


def run_projection_batch(
    store: ProjectionStateStore,
    *,
    target_id: str,
    projector: ChangeProjector,
    owner_id: str,
    now: str,
    max_events: int = 100,
    telemetry_sink: TelemetrySink | None = None,
) -> ProjectionBatchResult:
    target = store.get_projection_target(target_id)
    if target is None or not target.enabled:
        raise InvalidArgumentError("enabled projection target is required")
    if max_events <= 0:
        raise InvalidArgumentError("max_events must be positive")
    sink = telemetry_sink or NullTelemetrySink()
    namespaces = [target.namespace] if target.namespace is not None else None
    source_events = store.list_changes(namespaces=namespaces)
    source_head = int(source_events[-1].cursor or 0) if source_events else 0
    checkpoint = store.get_projection_checkpoint(target_id)
    events = store.list_changes(
        since_cursor=checkpoint.cursor,
        limit=max_events,
        namespaces=namespaces,
    )
    _validate_event_order(events, after_cursor=checkpoint.cursor)
    lease = store.acquire_projection_lease(
        target_id=target_id, owner_id=owner_id, now=now
    )
    applied = skipped = failed = dead_lettered = 0
    target_watermark = checkpoint.target_watermark
    failures = {
        failure.event_id: failure
        for failure in store.list_projection_failures(target_id=target_id)
    }
    try:
        for event in events:
            existing = failures.get(event.event_id)
            if existing is not None and not _retry_ready(existing, now):
                dead_lettered += int(existing.dead_letter)
                break
            attempt_number = (
                len(
                    store.list_projection_attempts(
                        target_id=target_id, event_id=event.event_id
                    )
                )
                + 1
            )
            result = _project_event(
                store,
                target=target,
                projector=projector,
                event=event,
                lease=lease,
                attempt_number=attempt_number,
                now=now,
                current_watermark=target_watermark,
                sink=sink,
            )
            target_watermark = result.target_watermark
            if result.failure is not None:
                failed += 1
                dead_lettered += int(result.failure.dead_letter)
                break
            if result.checkpoint is None or result.status is None:
                raise RuntimeError("projection event result is incomplete")
            checkpoint = result.checkpoint
            applied += int(result.status == "applied")
            skipped += int(result.status == "skipped")
    finally:
        try:
            store.release_projection_lease(
                target_id=target_id,
                owner_id=owner_id,
                fencing_token=lease.fencing_token,
            )
        except ProjectionFenceError:
            pass
    return ProjectionBatchResult(
        target_id=target_id,
        source_head_cursor=source_head,
        checkpoint_cursor=checkpoint.cursor,
        requested=len(events),
        applied=applied,
        skipped=skipped,
        failed=failed,
        dead_lettered=dead_lettered,
        target_watermark=target_watermark,
    )


def get_projection_health(
    store: ProjectionStateStore, *, target_id: str, now: str
) -> ProjectionHealth:
    checkpoint = store.get_projection_checkpoint(target_id)
    target = store.get_projection_target(target_id)
    if target is None:
        raise InvalidArgumentError("projection target is required")
    namespaces = [target.namespace] if target.namespace is not None else None
    events = store.list_changes(namespaces=namespaces)
    source_head = int(events[-1].cursor or 0) if events else 0
    failures = store.list_projection_failures(target_id=target_id)
    lease = store.get_projection_lease(target_id)
    active_lease = (
        lease if lease is not None and not is_expired(lease.expires_at, now) else None
    )
    return ProjectionHealth(
        target_id=target_id,
        source_head_cursor=source_head,
        checkpoint_cursor=checkpoint.cursor,
        lag=max(0, source_head - checkpoint.cursor),
        retry_count=sum(not item.dead_letter for item in failures),
        dead_letter_count=sum(item.dead_letter for item in failures),
        lease_owner=active_lease.owner_id if active_lease is not None else None,
        lease_expires_at=active_lease.expires_at if active_lease is not None else None,
        last_error_reason=failures[-1].reason if failures else None,
    )


def record_projection_health(
    health: ProjectionHealth,
    *,
    target: ProjectionTarget,
    sink: TelemetrySink,
) -> None:
    state = (
        "dead_lettered"
        if health.dead_letter_count
        else "retrying"
        if health.retry_count
        else "lagging"
        if health.lag
        else "healthy"
    )
    sink.record(
        TelemetryEvent(
            name="sophiagraph.projection.health",
            duration_ms=0.0,
            attributes=safe_telemetry_attributes(
                {
                    "backend": target.adapter_name,
                    "target_kind": target.kind,
                    "health_state": state,
                    "reason_code": health.last_error_reason or "none",
                    "cursor_lag": health.lag,
                    "retry_count": health.retry_count,
                    "dead_letter_count": health.dead_letter_count,
                    "lease_active": health.lease_owner is not None,
                }
            ),
        )
    )


__all__ = [
    "ChangeProjector",
    "GraphChangeProjector",
    "ProjectionApplyStatus",
    "ProjectionStateStore",
    "VectorChangeProjector",
    "get_projection_health",
    "record_projection_health",
    "run_projection_batch",
]
