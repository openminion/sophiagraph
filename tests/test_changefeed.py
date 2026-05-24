from __future__ import annotations

import pytest

from sophiagraph.models import (
    MemoryNamespace,
    MemoryRecord,
    MemoryRelation,
    StructuralLink,
)
from sophiagraph.storage import SophiaGraphMemoryStore, SophiaGraphSqliteStore


def _namespace(agent_id: str = "agent") -> MemoryNamespace:
    return MemoryNamespace(tenant_id="tenant", agent_id=agent_id, graph_id="main")


def _record(record_id: str, namespace: MemoryNamespace) -> MemoryRecord:
    return MemoryRecord(
        id=record_id,
        scope=f"agent:{namespace.agent_id}",
        type="fact",
        key=f"fact:{record_id}",
        title=f"Record {record_id}",
        content={"text": f"{record_id} content"},
        created_at="2026-05-24T00:00:00+00:00",
        updated_at="2026-05-24T00:00:00+00:00",
        namespace=namespace,
    )


def _relation(source: str, target: str) -> MemoryRelation:
    return MemoryRelation(
        relation_id=f"rel-{source}-{target}",
        source_record_id=source,
        target_record_id=target,
        relation_type="supports",
        created_at="2026-05-24T00:00:00+00:00",
    )


def _link(source: str, target: str, namespace: MemoryNamespace) -> StructuralLink:
    return StructuralLink(
        link_id=f"link-{source}-{target}",
        source_record_id=source,
        target_record_id=target,
        raw_target=target,
        link_kind="wikilink",
        resolution_status="resolved",
        relation_type="supports",
        namespace=namespace,
        created_at="2026-05-24T00:00:00+00:00",
    )


@pytest.fixture(params=["memory", "sqlite"])
def store(request, tmp_path):
    if request.param == "memory":
        return SophiaGraphMemoryStore()
    return SophiaGraphSqliteStore(tmp_path / "sophiagraph.sqlite3")


def test_changefeed_orders_and_filters_by_namespace(store) -> None:
    namespace = _namespace()
    other_namespace = _namespace("other")
    store.put_record(_record("rec-a", namespace))
    store.put_record(_record("rec-b", namespace))
    store.put_record(_record("rec-other", other_namespace))
    store.put_relation(_relation("rec-a", "rec-b"))
    store.put_link(_link("rec-a", "rec-b", namespace))

    all_changes = store.list_changes()
    filtered = store.list_changes(namespaces=[MemoryNamespace(agent_id="agent")])
    after_first = store.list_changes(since_cursor=all_changes[0].cursor)

    assert [event.cursor for event in all_changes] == sorted(
        event.cursor for event in all_changes
    )
    assert {event.object_type for event in filtered} == {"record", "relation", "link"}
    assert all(event.namespace.agent_id == "agent" for event in filtered)
    assert all(
        (event.cursor or 0) > (all_changes[0].cursor or 0) for event in after_first
    )
    relation_event = next(
        event for event in all_changes if event.object_type == "relation"
    )
    record_event = next(event for event in all_changes if event.object_id == "rec-a")
    assert relation_event.schema_identifiers == {"relation_type": "supports"}
    assert record_event.schema_identifiers == {"node_label": "fact"}


def test_delta_export_import_is_replay_safe(store, tmp_path) -> None:
    namespace = _namespace()
    store.put_record(_record("rec-a", namespace))
    store.put_record(_record("rec-b", namespace))
    store.put_relation(_relation("rec-a", "rec-b"))
    store.put_link(_link("rec-a", "rec-b", namespace))
    delta = store.export_delta(namespaces=[MemoryNamespace(agent_id="agent")])

    target = (
        SophiaGraphMemoryStore()
        if isinstance(store, SophiaGraphMemoryStore)
        else SophiaGraphSqliteStore(tmp_path / "target.sqlite3")
    )
    first = target.import_delta(delta)
    second = target.import_delta(delta)

    assert first.imported_changes == len(delta.changes)
    assert first.skipped_changes == 0
    assert second.imported_changes == 0
    assert second.skipped_changes == len(delta.changes)
    assert target.get_record("rec-a") is not None
    assert target.list_relations("rec-a")[0].relation_id == "rel-rec-a-rec-b"
    assert target.get_outgoing_links("rec-a")[0].link_id == "link-rec-a-rec-b"


def test_changefeed_keeps_orphan_relation_writes_compatible(store) -> None:
    store.put_relation(_relation("missing-source", "missing-target"))

    event = store.list_changes()[0]

    assert event.object_type == "relation"
    assert event.namespace.graph_id == "unscoped"
