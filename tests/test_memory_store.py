from __future__ import annotations

from sophiagraph.models import MemoryNamespace, MemoryRecord
from sophiagraph.portability.models import (
    MemoryBundleExportOptions,
    MemoryBundleImportOptions,
)
from sophiagraph.query import ListQueryOptions, SearchQueryOptions
from sophiagraph.storage import SophiaGraphMemoryStore


def _record(
    record_id: str = "mem-1",
    *,
    scope: str = "agent:memory",
    namespace: MemoryNamespace | None = None,
) -> MemoryRecord:
    return MemoryRecord(
        id=record_id,
        scope=scope,
        type="fact",
        key="topic:alpha",
        title="Alpha memory",
        content={"text": "memory backend works"},
        created_at="2026-05-22T00:00:00+00:00",
        updated_at="2026-05-22T00:00:00+00:00",
        source="validated",
        confidence=1.0,
        event_time="2026-05-22T00:00:00+00:00",
        namespace=namespace,
    )


def test_memory_store_round_trip_and_search() -> None:
    store = SophiaGraphMemoryStore()
    record = _record()
    store.put_record(record)
    assert store.get_record(record.id) is not None
    assert len(store.list_records(ListQueryOptions(scopes=["agent:memory"]))) == 1
    assert (
        len(
            store.search_records(
                SearchQueryOptions(query="works", scopes=["agent:memory"])
            )
        )
        == 1
    )


def test_memory_store_portability_round_trip() -> None:
    source = SophiaGraphMemoryStore()
    source.put_record(_record())
    snapshot = source.export_snapshot(
        MemoryBundleExportOptions(scopes=["agent:memory"])
    )
    dest = SophiaGraphMemoryStore()
    result = dest.import_snapshot(snapshot, MemoryBundleImportOptions())
    assert result.applied is True
    assert len(dest.list_records(ListQueryOptions(scopes=["agent:memory"]))) == 1


def test_memory_store_namespace_filters_and_export_boundaries() -> None:
    source = SophiaGraphMemoryStore()
    alpha_namespace = MemoryNamespace(
        tenant_id="tenant-acme",
        user_id="user-j",
        agent_id="alpha",
        graph_id="main",
    )
    beta_namespace = MemoryNamespace(
        tenant_id="tenant-acme",
        user_id="user-j",
        agent_id="beta",
        graph_id="main",
    )
    source.put_record(
        _record("mem-alpha", scope="agent:alpha", namespace=alpha_namespace)
    )
    source.put_record(_record("mem-beta", scope="agent:beta", namespace=beta_namespace))

    listed = source.list_records(
        ListQueryOptions(
            scopes=["agent:alpha", "agent:beta"],
            namespaces=[MemoryNamespace(agent_id="alpha")],
        )
    )
    assert [record.id for record in listed] == ["mem-alpha"]

    snapshot = source.export_snapshot(
        MemoryBundleExportOptions(
            scopes=["agent:alpha", "agent:beta"],
            namespaces=[MemoryNamespace(agent_id="alpha")],
        )
    )
    assert [record.id for record in snapshot.records] == ["mem-alpha"]

    dest = SophiaGraphMemoryStore()
    result = dest.import_snapshot(
        source.export_snapshot(
            MemoryBundleExportOptions(scopes=["agent:alpha", "agent:beta"])
        ),
        MemoryBundleImportOptions(
            namespace_allowlist=[MemoryNamespace(agent_id="alpha")]
        ),
    )
    assert result.imported_records == 1
    assert result.skipped_records == 1
    assert [
        record.id
        for record in dest.list_records(ListQueryOptions(scopes=["agent:alpha"]))
    ] == ["mem-alpha"]
