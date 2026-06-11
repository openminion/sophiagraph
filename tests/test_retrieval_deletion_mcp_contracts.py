"""Cross-surface tests for retrieval, deletion, and MCP adapter contracts."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

import pytest

from sophiagraph import SophiaGraphMemoryStore, SophiaGraphSqliteStore
from sophiagraph.adapters import McpMemoryRequest, SophiaGraphMcpAdapter
from sophiagraph.models import (
    MemoryEmbedding,
    MemoryNamespace,
    MemoryRecord,
    MemoryRelation,
)
from sophiagraph.query import (
    KeywordStageOptions,
    ListQueryOptions,
    RerankAdapter,
    RerankStageOptions,
    RetrievalRequest,
    SearchQueryOptions,
    VectorAdapter,
    VectorStageOptions,
    assemble_retrieval,
)


def _ns() -> MemoryNamespace:
    return MemoryNamespace(agent_id="contract")


def _record(
    record_id: str,
    content: str,
    *,
    event_time: str = "2026-01-01T00:00:00+00:00",
    valid_to: str | None = None,
    created_at: str = "2026-01-01T00:00:00+00:00",
) -> MemoryRecord:
    return MemoryRecord(
        id=record_id,
        scope="agent:contract",
        type="fact",
        content=content,
        created_at=created_at,
        updated_at=created_at,
        event_time=event_time,
        valid_to=valid_to,
        namespace=_ns(),
        source="user_said",
    )


@pytest.fixture(params=["memory", "sqlite"])
def store(request, tmp_path: Path):
    if request.param == "memory":
        return SophiaGraphMemoryStore()
    return SophiaGraphSqliteStore(tmp_path / "sg.sqlite3")


def test_bitemporal_valid_at_and_believed_at(store) -> None:
    old = _record(
        "belief-old",
        "Paris trip is in June",
        event_time="2026-01-01T00:00:00+00:00",
        valid_to="2026-03-01T00:00:00+00:00",
        created_at="2026-01-02T00:00:00+00:00",
    )
    new = _record(
        "belief-new",
        "Paris trip is in July",
        event_time="2026-03-01T00:00:00+00:00",
        created_at="2026-03-02T00:00:00+00:00",
    )
    store.put_record(old)
    store.put_record(new)

    january = store.list_records(
        ListQueryOptions(
            scopes=["agent:contract"],
            valid_at="2026-02-01T00:00:00+00:00",
        )
    )
    april = store.list_records(
        ListQueryOptions(
            scopes=["agent:contract"],
            believed_at="2026-04-01T00:00:00+00:00",
        )
    )

    assert [record.id for record in january] == ["belief-old"]
    assert [record.id for record in april] == ["belief-new"]


def test_bitemporal_search_includes_superseded_record(store) -> None:
    store.put_record(
        _record(
            "past",
            "The launch date is May",
            valid_to="2026-05-15T00:00:00+00:00",
        )
    )
    store.put_record(
        _record(
            "current",
            "The launch date is June",
            event_time="2026-05-15T00:00:00+00:00",
        )
    )
    result = store.search_records(
        SearchQueryOptions(
            query="May",
            scopes=["agent:contract"],
            as_of="2026-04-01T00:00:00+00:00",
        )
    )
    assert [record.id for record in result] == ["past"]


class _VectorAdapter(VectorAdapter):
    def search(self, **kwargs):
        return [("vec-only", 0.99), ("kw-hit", 0.5)]


class _Reranker(RerankAdapter):
    def rerank(self, *, records, request, limit):
        return [("vec-only", 10.0)]


def test_hybrid_retrieval_uses_rrf_and_rerank_adapter(store) -> None:
    store.put_record(_record("kw-hit", "alpha keyword"))
    store.put_record(_record("vec-only", "semantic neighbor"))
    store.put_embedding(
        MemoryEmbedding(
            record_id="vec-only",
            vector_space="test",
            dimension=2,
            provider="fake",
            model="fake",
            namespace=_ns(),
            created_at="2026-01-01T00:00:00+00:00",
            updated_at="2026-01-01T00:00:00+00:00",
            vector=[0.1, 0.2],
        )
    )
    result = assemble_retrieval(
        store,
        RetrievalRequest(
            scopes=["agent:contract"],
            keyword=KeywordStageOptions(query="alpha"),
            vector=VectorStageOptions(query_embedding=[0.1, 0.2], vector_space="test"),
            rerank=RerankStageOptions(),
        ),
        vector_adapter=_VectorAdapter(),
        rerank_adapter=_Reranker(),
    )
    assert result.hits[0].record.id == "vec-only"
    assert result.hits[0].explanation.provenance["fusion"] == "rrf"


def test_provable_deletion_cascades_and_exports_audit(store) -> None:
    store.put_record(_record("root", "delete me"))
    store.put_record(_record("other", "neighbor"))
    store.put_relation(
        MemoryRelation(
            relation_id="rel-1",
            source_record_id="root",
            target_record_id="other",
            relation_type="related_to",
            created_at="2026-01-01T00:00:00+00:00",
        )
    )
    store.put_embedding(
        MemoryEmbedding(
            record_id="root",
            vector_space="test",
            dimension=1,
            provider="fake",
            model="fake",
            namespace=_ns(),
            created_at="2026-01-01T00:00:00+00:00",
            updated_at="2026-01-01T00:00:00+00:00",
            vector=[0.1],
        )
    )
    result = store.cascade_tombstones(
        "root",
        deleted_at="2026-05-30T00:00:00+00:00",
        reason="user_request",
    )
    audit = store.erasure_audit_export(record_id="root")

    assert result.tombstoned_record_ids == ["root"]
    assert result.removed_relation_ids == ["rel-1"]
    assert result.removed_embedding_keys == ["root:test"]
    assert audit.entries[0].reason == "user_request"
    assert store.get_record("root").is_deleted is True


def test_mcp_adapter_crud_search_without_openminion_import(store) -> None:
    adapter = SophiaGraphMcpAdapter(store)
    record = _record("mcp-1", "MCP searchable memory")
    create = adapter.handle(
        McpMemoryRequest(operation="create", payload={"record": asdict(record)})
    )
    search = adapter.handle(
        McpMemoryRequest(
            operation="search",
            payload={"query": "searchable", "scopes": ["agent:contract"]},
        )
    )
    delete = adapter.handle(
        McpMemoryRequest(
            operation="delete",
            payload={
                "record_id": "mcp-1",
                "deleted_at": "2026-05-30T00:00:00+00:00",
                "reason": "test",
            },
        )
    )

    assert create.ok is True
    assert search.ok is True
    assert search.payload["records"][0]["id"] == "mcp-1"
    assert delete.ok is True
    assert delete.payload["record"]["is_deleted"] is True
