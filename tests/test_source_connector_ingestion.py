from __future__ import annotations

import pytest

from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.connectors import (
    SourceIngestEnvelope,
    SourceRegistryEntry,
    decide_source_ingest,
    update_source_after_ingest,
)
from sophiagraph.freshness import FreshnessLedgerEntry
from sophiagraph.models import MemoryNamespace
from sophiagraph.storage import SophiaGraphMemoryStore, SophiaGraphSqliteStore


def _ns(agent_id: str = "agent") -> MemoryNamespace:
    return MemoryNamespace(tenant_id="tenant", agent_id=agent_id, graph_id="main")


@pytest.fixture(params=["memory", "sqlite"])
def store(request, tmp_path):
    if request.param == "memory":
        return SophiaGraphMemoryStore()
    return SophiaGraphSqliteStore(tmp_path / "source.sqlite3")


def _source(permission_scope: str = "read_only") -> SourceRegistryEntry:
    return SourceRegistryEntry(
        source_id="source:fake",
        source_type="test_fake",
        namespace=_ns(),
        display_name="Fake source",
        permission_scope=permission_scope,  # type: ignore[arg-type]
        created_at="2026-05-31T00:00:00+00:00",
        updated_at="2026-05-31T00:00:00+00:00",
    )


def test_source_registry_and_ingest_envelope_round_trip(store) -> None:
    source = _source()
    envelope = SourceIngestEnvelope.create(
        source_id=source.source_id,
        namespace=source.namespace,
        payload_kind="document",
        payload={"id": "doc-1", "title": "Doc"},
        cursor="cursor-1",
        content_hash="hash-1",
        permission_scope="read_only",
    )

    store.put_source_entry(source)
    store.put_source_ingest(envelope)

    assert store.get_source_entry(source.source_id) == source
    assert store.get_source_ingest(envelope.ingest_id) == envelope
    assert store.list_source_entries(
        namespaces=[MemoryNamespace(agent_id="agent")]
    ) == [source]


def test_connector_replay_decision_consumes_freshness() -> None:
    source = _source()
    envelope = SourceIngestEnvelope.create(
        source_id=source.source_id,
        namespace=source.namespace,
        payload_kind="record",
        payload={"id": "rec-1"},
        cursor="cursor-1",
        content_hash="hash-1",
    )
    existing = FreshnessLedgerEntry.create(
        namespace=source.namespace,
        source_kind="connector",
        source_id=source.source_id,
        status="fresh",
        cursor="cursor-1",
        content_hash="hash-1",
    )

    replay = decide_source_ingest(source, envelope, existing)
    updated = update_source_after_ingest(source, envelope, updated_at="now")

    assert replay.accepted is False
    assert replay.replay_decision.decision == "skip_unchanged"
    assert updated.cursor == "cursor-1"
    assert updated.content_hash == "hash-1"


def test_connector_ingest_rejects_namespace_mismatch() -> None:
    source = _source()
    envelope = SourceIngestEnvelope.create(
        source_id=source.source_id,
        namespace=_ns("other"),
        payload_kind="record",
        payload={"id": "rec-1"},
        cursor="cursor-1",
        content_hash="hash-1",
    )

    with pytest.raises(InvalidArgumentError, match="namespace"):
        decide_source_ingest(source, envelope)


def test_metadata_only_source_rejects_payload_body() -> None:
    source = _source("metadata_only")
    envelope = SourceIngestEnvelope.create(
        source_id=source.source_id,
        namespace=source.namespace,
        payload_kind="document",
        payload={"body": "not allowed"},
        cursor="c",
        content_hash="h",
        permission_scope="metadata_only",
    )

    with pytest.raises(InvalidArgumentError, match="metadata_only"):
        decide_source_ingest(source, envelope)


def test_source_namespace_isolation(store) -> None:
    store.put_source_entry(_source())
    store.put_source_entry(
        SourceRegistryEntry(
            source_id="source:other",
            source_type="test_fake",
            namespace=_ns("other"),
            display_name="Other source",
            permission_scope="read_only",
        )
    )

    listed = store.list_source_entries(namespaces=[MemoryNamespace(agent_id="agent")])

    assert [source.source_id for source in listed] == ["source:fake"]
