from __future__ import annotations

from dataclasses import replace

from sophiagraph.connectors import (
    SourceIngestEnvelope,
    SourceIngestResult,
    SourceRegistryEntry,
    decide_source_ingest,
)
from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.ingestion import IngestBatchPlan, execute_ingest_batch
from sophiagraph.models import MemoryNamespace
from sophiagraph.telemetry import (
    TelemetryEvent,
    safe_telemetry_attributes,
    trace_operation,
)


def _source() -> SourceRegistryEntry:
    return SourceRegistryEntry(
        source_id="source-1",
        source_type="api",
        namespace=MemoryNamespace(agent_id="agent-1", graph_id="main"),
        display_name="Source",
        permission_scope="read_only",
    )


def _envelope(cursor: str) -> SourceIngestEnvelope:
    source = _source()
    return SourceIngestEnvelope.create(
        source_id=source.source_id,
        namespace=source.namespace,
        payload_kind="record",
        payload={"id": cursor},
        cursor=cursor,
        content_hash=f"sha256:{cursor}",
    )


def test_resumable_ingest_preserves_checkpoint_order() -> None:
    plan = IngestBatchPlan(
        batch_id="batch-1", envelopes=(_envelope("1"), _envelope("2"))
    )

    def handler(envelope: SourceIngestEnvelope) -> SourceIngestResult:
        result = decide_source_ingest(_source(), envelope)
        return replace(result, record_ids=[f"rec:{envelope.cursor}"])

    first = execute_ingest_batch(plan, handler, max_items=1)
    assert first.complete is False
    second = execute_ingest_batch(plan, handler, checkpoint=first.checkpoint)
    assert second.complete is True
    assert second.checkpoint.completed_ingest_ids == tuple(
        envelope.ingest_id for envelope in plan.envelopes
    )


def test_ingest_batch_records_typed_item_failures() -> None:
    plan = IngestBatchPlan(batch_id="batch-1", envelopes=(_envelope("1"),))

    def handler(envelope: SourceIngestEnvelope) -> SourceIngestResult:
        del envelope
        raise InvalidArgumentError("invalid source payload")

    result = execute_ingest_batch(plan, handler)

    assert result.complete is False
    assert result.items[0].status == "failed"
    assert result.items[0].error == "INVALID_ARGUMENT: invalid source payload"


def test_telemetry_drops_sensitive_and_high_cardinality_fields() -> None:
    safe = safe_telemetry_attributes(
        {"backend": "sqlite", "query_text": "secret", "record_id": "rec-1"}
    )
    assert safe == {"backend": "sqlite"}

    events: list[TelemetryEvent] = []

    class Sink:
        def record(self, event: TelemetryEvent) -> None:
            events.append(event)

    with trace_operation(Sink(), "sophiagraph.query", attributes={"stage": "fts"}):
        pass
    assert events[0].attributes == {"stage": "fts", "outcome": "ok"}
