"""Resumable structural ingestion over connector envelopes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Literal

from sophiagraph.connectors import SourceIngestEnvelope, SourceIngestResult
from sophiagraph.contracts.errors import InvalidArgumentError, MemctlError

BatchItemStatus = Literal["accepted", "skipped", "failed"]
IngestHandler = Callable[[SourceIngestEnvelope], SourceIngestResult]


@dataclass(frozen=True, slots=True)
class IngestBatchPlan:
    batch_id: str
    envelopes: tuple[SourceIngestEnvelope, ...]
    continue_on_error: bool = False

    def __post_init__(self) -> None:
        if not self.batch_id or not self.envelopes:
            raise InvalidArgumentError("batch_id and envelopes are required")
        ids = [envelope.ingest_id for envelope in self.envelopes]
        if len(ids) != len(set(ids)):
            raise InvalidArgumentError("batch envelopes require unique ingest ids")


@dataclass(frozen=True, slots=True)
class IngestBatchCheckpoint:
    batch_id: str
    completed_ingest_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class IngestBatchItemResult:
    ingest_id: str
    status: BatchItemStatus
    record_ids: tuple[str, ...] = ()
    error: str | None = None


@dataclass(frozen=True, slots=True)
class IngestBatchResult:
    batch_id: str
    items: tuple[IngestBatchItemResult, ...]
    checkpoint: IngestBatchCheckpoint
    complete: bool


def execute_ingest_batch(
    plan: IngestBatchPlan,
    handler: IngestHandler,
    *,
    checkpoint: IngestBatchCheckpoint | None = None,
    max_items: int | None = None,
) -> IngestBatchResult:
    if checkpoint is not None and checkpoint.batch_id != plan.batch_id:
        raise InvalidArgumentError("checkpoint batch_id does not match plan")
    if max_items is not None and max_items <= 0:
        raise InvalidArgumentError("max_items must be positive")
    completed = set(checkpoint.completed_ingest_ids if checkpoint else ())
    items: list[IngestBatchItemResult] = []
    processed = 0
    for envelope in plan.envelopes:
        if envelope.ingest_id in completed:
            continue
        if max_items is not None and processed >= max_items:
            break
        processed += 1
        try:
            observed = handler(envelope)
            status: BatchItemStatus = "accepted" if observed.accepted else "skipped"
            items.append(
                IngestBatchItemResult(
                    ingest_id=envelope.ingest_id,
                    status=status,
                    record_ids=tuple(observed.record_ids),
                )
            )
            completed.add(envelope.ingest_id)
        except MemctlError as exc:
            items.append(
                IngestBatchItemResult(
                    ingest_id=envelope.ingest_id,
                    status="failed",
                    error=f"{exc.code}: {exc.message}",
                )
            )
            if not plan.continue_on_error:
                break
    ordered_completed = tuple(
        envelope.ingest_id
        for envelope in plan.envelopes
        if envelope.ingest_id in completed
    )
    next_checkpoint = IngestBatchCheckpoint(
        batch_id=plan.batch_id,
        completed_ingest_ids=ordered_completed,
    )
    return IngestBatchResult(
        batch_id=plan.batch_id,
        items=tuple(items),
        checkpoint=next_checkpoint,
        complete=len(ordered_completed) == len(plan.envelopes),
    )


__all__ = [
    "BatchItemStatus",
    "IngestBatchCheckpoint",
    "IngestBatchItemResult",
    "IngestBatchPlan",
    "IngestBatchResult",
    "IngestHandler",
    "execute_ingest_batch",
]
