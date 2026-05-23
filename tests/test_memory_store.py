from __future__ import annotations

import pytest

from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.models import MemoryCandidate, MemoryNamespace, MemoryRecord
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


def test_memory_store_candidate_promotion_preserves_candidate_namespace() -> None:
    store = SophiaGraphMemoryStore()
    namespace = MemoryNamespace(
        tenant_id="tenant-acme",
        user_id="user-j",
        agent_id="agent-candidate",
        session_id="session-1",
    )
    candidate = MemoryCandidate(
        candidate_id="cand-ns",
        session_id="session-1",
        proposed_scope="agent:agent-candidate",
        type="fact",
        content={"text": "candidate namespace persists"},
        namespace=namespace,
    )
    store.put_candidate(candidate)

    promoted = store.promote_candidate("cand-ns", "agent:agent-candidate")

    assert promoted.namespace == namespace
    assert promoted.effective_namespace == namespace


def test_memory_candidate_rejects_conflicting_meta_fields() -> None:
    with pytest.raises(InvalidArgumentError, match="claim_key conflicts"):
        MemoryCandidate(
            candidate_id="cand-conflict",
            session_id="session-1",
            proposed_scope="agent:agent-candidate",
            type="fact",
            content={"text": "conflict"},
            claim_key="project:a",
            meta={"claim_key": "project:b"},
        )
