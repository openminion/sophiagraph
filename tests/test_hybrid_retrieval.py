"""Hybrid retrieval contract coverage."""

from __future__ import annotations

from pathlib import Path

import pytest

from sophiagraph import SophiaGraphMemoryStore, SophiaGraphSqliteStore
from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.models import MemoryNamespace, MemoryRecord
from sophiagraph.query import (
    GraphStageOptions,
    KeywordStageOptions,
    RETRIEVAL_STAGES,
    RecencyStageOptions,
    RerankStageOptions,
    RetrievalRequest,
    TrustStageOptions,
    VectorAdapter,
    VectorStageOptions,
    assemble_retrieval,
)


def _ns() -> MemoryNamespace:
    return MemoryNamespace(agent_id="alpha")


def _record(
    id: str,
    content: str,
    *,
    source: str = "user_said",
    updated_at: str = "2026-05-29T10:00:00+00:00",
) -> MemoryRecord:
    return MemoryRecord(
        id=id,
        scope="agent:alpha",
        type="fact",
        content=content,
        created_at=updated_at,
        updated_at=updated_at,
        namespace=_ns(),
        source=source,
    )


@pytest.fixture(params=["memory", "sqlite"])
def store(request, tmp_path: Path):
    s = (
        SophiaGraphMemoryStore()
        if request.param == "memory"
        else SophiaGraphSqliteStore(tmp_path / "sg.sqlite3")
    )
    for rid, txt in [
        ("rec-1", "Sophiagraph stores typed memory."),
        ("rec-2", "The agent ran make check."),
        ("rec-3", "Berlin has a population of 3.7 million."),
    ]:
        s.put_record(_record(rid, txt))
    return s


def test_keyword_options_validate() -> None:
    KeywordStageOptions(query="hello", limit=10)
    with pytest.raises(InvalidArgumentError):
        KeywordStageOptions(query="", limit=10)
    with pytest.raises(InvalidArgumentError):
        KeywordStageOptions(query="x", limit=0)


def test_vector_options_validate() -> None:
    VectorStageOptions(query_embedding=[0.1, 0.2], vector_space="default")
    with pytest.raises(InvalidArgumentError):
        VectorStageOptions(query_embedding=[], vector_space="default")
    with pytest.raises(InvalidArgumentError):
        VectorStageOptions(query_embedding=[0.1], vector_space="")
    with pytest.raises(InvalidArgumentError):
        VectorStageOptions(query_embedding=[0.1], vector_space="default", metric="zzz")


def test_recency_options_validate() -> None:
    RecencyStageOptions(half_life_days=7)
    with pytest.raises(InvalidArgumentError):
        RecencyStageOptions(half_life_days=0)


def test_trust_options_validate() -> None:
    TrustStageOptions(source_weights={"user_said": 2.0, "agent_inferred": 0.5})
    with pytest.raises(InvalidArgumentError):
        TrustStageOptions(source_weights={"user_said": -1.0})
    with pytest.raises(InvalidArgumentError):
        TrustStageOptions(default_weight=-0.1)


def test_graph_options_validate() -> None:
    GraphStageOptions(depth=2, max_expanded_records=10)
    with pytest.raises(InvalidArgumentError):
        GraphStageOptions(depth=-1)


# Active stages + stage ordering


def test_active_stages_reports_in_canonical_order() -> None:
    req = RetrievalRequest(
        scopes=["agent:alpha"],
        keyword=KeywordStageOptions(query="x"),
        recency=RecencyStageOptions(),
        trust=TrustStageOptions(),
    )
    assert req.active_stages == ["keyword", "recency", "trust"]


def test_retrieval_stages_constant_is_closed_order() -> None:
    assert RETRIEVAL_STAGES == (
        "keyword",
        "vector",
        "graph",
        "recency",
        "trust",
        "rerank",
    )


def test_keyword_only_returns_hits_with_explanation(store) -> None:
    result = assemble_retrieval(
        store,
        RetrievalRequest(
            scopes=["agent:alpha"],
            keyword=KeywordStageOptions(query="Berlin"),
        ),
    )
    assert result.request_stage_order == ["keyword"]
    ids = [h.record.id for h in result.hits]
    assert "rec-3" in ids
    for hit in result.hits:
        assert hit.explanation.components
        assert any(c.kind == "keyword" for c in hit.explanation.components)


def test_namespace_isolation_with_isolated_store(tmp_path: Path) -> None:
    s = SophiaGraphSqliteStore(tmp_path / "sg.sqlite3")
    s.put_record(_record("only-a", "agent A note"))
    s.put_record(
        MemoryRecord(
            id="only-b",
            scope="agent:alpha",
            type="fact",
            content="agent B note",
            created_at="2026-05-29T10:00:00+00:00",
            updated_at="2026-05-29T10:00:00+00:00",
            namespace=MemoryNamespace(agent_id="beta"),
            source="user_said",
        )
    )
    res = assemble_retrieval(
        s,
        RetrievalRequest(
            scopes=["agent:alpha"],
            namespaces=[MemoryNamespace(agent_id="alpha")],
            keyword=KeywordStageOptions(query="note"),
        ),
    )
    assert [h.record.id for h in res.hits] == ["only-a"]


def test_vector_stage_without_adapter_raises(store) -> None:
    with pytest.raises(InvalidArgumentError):
        assemble_retrieval(
            store,
            RetrievalRequest(
                scopes=["agent:alpha"],
                vector=VectorStageOptions(
                    query_embedding=[0.1, 0.2, 0.3], vector_space="default"
                ),
            ),
        )


class _StubVectorAdapter(VectorAdapter):
    def __init__(self) -> None:
        self.calls = 0

    def search(self, **kwargs) -> list[tuple[str, float]]:
        self.calls += 1
        candidates = kwargs["candidates"]
        # Deterministic stub: rank candidates by id.
        return [(rid, 1.0 - i * 0.1) for i, (rid, _vec) in enumerate(candidates)]


def test_vector_stage_invokes_adapter_when_supplied(store) -> None:
    # No embeddings exist → adapter is harmless (returns []).
    adapter = _StubVectorAdapter()
    result = assemble_retrieval(
        store,
        RetrievalRequest(
            scopes=["agent:alpha"],
            keyword=KeywordStageOptions(query="agent"),
            vector=VectorStageOptions(
                query_embedding=[0.1, 0.2], vector_space="default"
            ),
        ),
        vector_adapter=adapter,
    )
    # Adapter is invoked but does not invent records — keyword hits remain.
    assert result.request_stage_order == ["keyword", "vector"]
    assert all(h.record.id.startswith("rec-") for h in result.hits)


def test_keyword_only_pipeline_runs_without_adapter(store) -> None:
    """Adapter absence does not break other stages."""
    result = assemble_retrieval(
        store,
        RetrievalRequest(
            scopes=["agent:alpha"],
            keyword=KeywordStageOptions(query="agent"),
            recency=RecencyStageOptions(half_life_days=7),
            trust=TrustStageOptions(source_weights={"user_said": 2.0}),
        ),
        now_iso="2026-05-29T10:00:00+00:00",
    )
    assert result.hits
    # Every hit explanation carries components from each active stage.
    for hit in result.hits:
        kinds = {c.kind for c in hit.explanation.components}
        assert {"keyword", "recency", "trust"}.issubset(kinds)


def test_rerank_overrides_final_ordering(store) -> None:
    # Without rerank.
    base = assemble_retrieval(
        store,
        RetrievalRequest(
            scopes=["agent:alpha"],
            keyword=KeywordStageOptions(query="agent"),
        ),
    )
    natural_top = base.hits[0].record.id
    # With rerank: push an arbitrary record to the top.
    target_record = next(
        (h.record.id for h in base.hits if h.record.id != natural_top), natural_top
    )
    result = assemble_retrieval(
        store,
        RetrievalRequest(
            scopes=["agent:alpha"],
            keyword=KeywordStageOptions(query="agent"),
            rerank=RerankStageOptions(score_override={target_record: 100.0}),
        ),
    )
    assert result.hits[0].record.id == target_record
    rerank_components = [
        c for h in result.hits for c in h.explanation.components if c.kind == "rerank"
    ]
    assert rerank_components


def test_explanation_carries_source_and_via_relations(store) -> None:
    result = assemble_retrieval(
        store,
        RetrievalRequest(
            scopes=["agent:alpha"],
            keyword=KeywordStageOptions(query="agent"),
            trust=TrustStageOptions(source_weights={"user_said": 1.5}),
        ),
    )
    for hit in result.hits:
        assert hit.explanation.record_id == hit.record.id
        assert hit.explanation.source_record_ids == [hit.record.id]
        assert hit.explanation.provenance["source"] == "user_said"


def test_deterministic_ordering(store) -> None:
    # Same request twice → identical output.
    req = RetrievalRequest(
        scopes=["agent:alpha"],
        keyword=KeywordStageOptions(query="agent"),
    )
    a = assemble_retrieval(store, req)
    b = assemble_retrieval(store, req)
    assert [h.record.id for h in a.hits] == [h.record.id for h in b.hits]


# Anti-LLM


def test_anti_llm_no_inference_helpers_on_retrieval_module() -> None:
    from sophiagraph.query import retrieval as mod

    forbidden = {
        "rewrite_user_query",
        "summarize_relevance",
        "explain_in_prose",
        "auto_pick_stages",
    }
    assert set(mod.__all__) & forbidden == set()
