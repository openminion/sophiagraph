from __future__ import annotations

from pathlib import Path

import pytest

from sophiagraph import (
    ActiveEmbeddingModelSet,
    KnowledgeDocumentBlock,
    MemoryEmbedding,
    MemoryNamespace,
    MemoryRecord,
    MemoryRelation,
    SophiaGraphMemoryStore,
    SophiaGraphSqliteStore,
    VectorSpaceModelDescriptor,
    build_store_capability_report,
)
from sophiagraph.embedding_lifecycle import list_orphan_external_vector_ids
from sophiagraph.portability.models import (
    MemoryBundleExportOptions,
    MemoryBundleImportOptions,
)
from sophiagraph.query import (
    GraphSnapshotOptions,
    ListQueryOptions,
    SearchQueryOptions,
)
from sophiagraph.storage.capabilities import StoreCapabilityReport


@pytest.fixture(params=["memory", "sqlite"])
def store(request, tmp_path: Path):
    if request.param == "memory":
        return SophiaGraphMemoryStore()
    return SophiaGraphSqliteStore(tmp_path / "sophiagraph.sqlite3")


def _namespace() -> MemoryNamespace:
    return MemoryNamespace(tenant_id="tenant", agent_id="storage", graph_id="main")


def _record(record_id: str, text: str) -> MemoryRecord:
    return MemoryRecord(
        id=record_id,
        scope="agent:storage",
        type="fact",
        key=f"fact:{record_id}",
        title=f"Storage {record_id}",
        content={"text": text},
        tags=["storage"],
        created_at="2026-07-02T00:00:00+00:00",
        updated_at="2026-07-02T00:00:00+00:00",
        event_time="2026-07-02T00:00:00+00:00",
        source="validated",
        namespace=_namespace(),
    )


def _embedding(record_id: str, external_vector_id: str) -> MemoryEmbedding:
    return MemoryEmbedding(
        record_id=record_id,
        vector_space="semantic",
        dimension=3,
        provider="builtin",
        model="fixture",
        namespace=_namespace(),
        created_at="2026-07-02T00:00:00+00:00",
        updated_at="2026-07-02T00:00:00+00:00",
        vector=[1.0, 0.0, 0.0],
        external_vector_id=external_vector_id,
    )


def _active_model_set() -> ActiveEmbeddingModelSet:
    return ActiveEmbeddingModelSet(
        namespace=_namespace(),
        vector_space="semantic",
        active_models=(
            VectorSpaceModelDescriptor(
                provider="builtin",
                model="fixture",
                dimension=3,
            ),
        ),
        updated_at="2026-07-02T00:00:00+00:00",
    )


def _populate(store) -> None:
    first = _record("rec-alpha", "alpha durable memory search")
    second = _record("rec-beta", "beta durable memory search")
    store.put_record(first)
    store.put_record(second)
    store.put_relation(
        MemoryRelation(
            relation_id="rel-alpha-beta",
            source_record_id=first.id,
            target_record_id=second.id,
            relation_type="supports",
            created_at="2026-07-02T00:00:00+00:00",
        )
    )
    store.put_document_blocks(
        "rec-alpha",
        [
            KnowledgeDocumentBlock(
                block_id="block-alpha",
                document_id="doc-alpha",
                record_id="rec-alpha",
                block_type="heading",
                anchor="storage",
                excerpt="SQLite and memory stores should agree.",
            )
        ],
    )
    store.put_embedding(_embedding("rec-alpha", "vec-alpha-v1"))
    store.put_embedding(_embedding("rec-alpha", "vec-alpha-v2"))
    store.put_active_model_set(_active_model_set())


def test_store_capability_report_surfaces_backend_posture(store) -> None:
    _populate(store)

    report = build_store_capability_report(store)
    payload = report.to_dict()

    assert isinstance(report, StoreCapabilityReport)
    assert payload["backend"] in {"memory", "sqlite"}
    assert payload["record_count"] == 2
    assert payload["embedding_count"] == 1
    assert payload["active_model_set_count"] == 1
    assert payload["external_vector_ids_supported"] is True
    assert payload["namespace_governance_supported"] is True
    assert "builtin" in payload["optional_vector_backends"]
    if payload["backend"] == "sqlite":
        assert payload["durable"] is True
        assert payload["backup_supported"] is True
        assert payload["sqlite_schema_version"] is not None
    else:
        assert payload["durable"] is False
        assert (
            "in_memory_store_uses_deterministic_python_search" in payload["diagnostics"]
        )


def test_memory_and_sqlite_stores_share_retrieval_and_graph_contract(
    store,
) -> None:
    _populate(store)

    listed = store.list_records(ListQueryOptions(scopes=["agent:storage"]))
    searched = store.search_records(
        SearchQueryOptions(query="durable", scopes=["agent:storage"])
    )
    relations = store.list_relations("rec-alpha")
    blocks = store.list_document_blocks(record_id="rec-alpha")
    graph = store.get_graph_snapshot(GraphSnapshotOptions(scopes=["agent:storage"]))

    assert {record.id for record in listed} == {"rec-alpha", "rec-beta"}
    assert {record.id for record in searched} == {"rec-alpha", "rec-beta"}
    assert [block.block_id for block in blocks] == ["block-alpha"]
    assert blocks[0].excerpt == "SQLite and memory stores should agree."
    assert [relation.relation_id for relation in relations] == ["rel-alpha-beta"]
    assert {node.record_id for node in graph.nodes} == {"rec-alpha", "rec-beta"}


def test_portability_preserves_governance_and_vector_lifecycle(store) -> None:
    _populate(store)

    snapshot = store.export_snapshot(
        MemoryBundleExportOptions(
            scopes=["agent:storage"],
            include_relations=True,
            include_embedding_lifecycle=True,
            namespaces=[_namespace()],
        )
    )
    dest = SophiaGraphMemoryStore()
    result = dest.import_snapshot(snapshot, MemoryBundleImportOptions())

    assert result.imported_records == 2
    assert result.imported_relations == 1
    assert result.imported_active_embedding_model_sets == 1
    assert dest.list_active_model_sets(namespaces=[_namespace()]) == [
        _active_model_set()
    ]


def test_vector_lifecycle_reports_orphan_external_ids(store) -> None:
    _populate(store)

    assert list_orphan_external_vector_ids(store, namespace=_namespace()) == [
        ("vec-alpha-v1", "2026-07-02T00:00:00+00:00")
    ]
    assert store.delete_embedding("rec-alpha", "semantic") is True
    assert list_orphan_external_vector_ids(store, namespace=_namespace()) == [
        ("vec-alpha-v1", "2026-07-02T00:00:00+00:00"),
        ("vec-alpha-v2", "2026-07-02T00:00:00+00:00"),
    ]
