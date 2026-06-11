"""Context assembly and retrieval mode coverage."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

import pytest

from sophiagraph import SophiaGraphMemoryStore, SophiaGraphSqliteStore
from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.models import (
    Fact,
    MemoryNamespace,
    MemoryRecord,
    MemoryRelation,
    StructuralLink,
)
from sophiagraph.models.entity_fact import EntityFactProvenance
from sophiagraph.query import (
    CONTEXT_ITEM_KINDS,
    CommunityDetectionOptions,
    CommunityQueryOptions,
    ContextBudget,
    ContextItem,
    ContextRequest,
    DriftMode,
    DriftStepInput,
    GlobalMode,
    HybridMode,
    LocalGraphMode,
    OmittedDiagnostic,
    RETRIEVAL_MODES,
    StructuralSearchMode,
    TemporalFactMode,
    assemble_context,
    query_communities,
)


def _ns() -> MemoryNamespace:
    return MemoryNamespace(agent_id="alpha")


def _record(rid: str, content: str = "x", source: str = "user_said") -> MemoryRecord:
    return MemoryRecord(
        id=rid,
        scope="agent:alpha",
        type="fact",
        content=content,
        created_at="2026-05-29T10:00:00+00:00",
        updated_at="2026-05-29T10:00:00+00:00",
        namespace=_ns(),
        source=source,
        title=f"Title for {rid}",
    )


@pytest.fixture(params=["memory", "sqlite"])
def store(request, tmp_path: Path):
    s = (
        SophiaGraphMemoryStore()
        if request.param == "memory"
        else SophiaGraphSqliteStore(tmp_path / "sg.sqlite3")
    )
    for rid, content in [
        ("rec-1", "Sophiagraph stores typed memory."),
        ("rec-2", "The agent ran make check."),
        ("rec-3", "Berlin has 3.7 million people."),
    ]:
        s.put_record(_record(rid, content))
    return s


def test_retrieval_modes_constant_is_closed_set() -> None:
    assert RETRIEVAL_MODES == {
        "local_graph",
        "structural_search",
        "temporal_fact",
        "hybrid",
        "global",
        "drift",
    }


def test_local_graph_mode_validates() -> None:
    LocalGraphMode(seed_record_ids=["rec-1"], depth=2)
    with pytest.raises(InvalidArgumentError):
        LocalGraphMode(seed_record_ids=[])
    with pytest.raises(InvalidArgumentError):
        LocalGraphMode(seed_record_ids=["rec-1"], depth=-1)
    with pytest.raises(InvalidArgumentError):
        LocalGraphMode(seed_record_ids=["rec-1"], max_paths=0)


def test_structural_mode_validates() -> None:
    StructuralSearchMode(query="hello", limit=10)
    with pytest.raises(InvalidArgumentError):
        StructuralSearchMode(query="", limit=10)
    with pytest.raises(InvalidArgumentError):
        StructuralSearchMode(query="hello", limit=0)


def test_temporal_fact_mode_validates_active_state() -> None:
    TemporalFactMode(active_state="active")
    TemporalFactMode(active_state="historical")
    TemporalFactMode(active_state="all")
    with pytest.raises(InvalidArgumentError):
        TemporalFactMode(active_state="future")  # type: ignore[arg-type]
    with pytest.raises(InvalidArgumentError):
        TemporalFactMode(limit=0)


def test_hybrid_mode_validates() -> None:
    HybridMode(seed_query="x")
    with pytest.raises(InvalidArgumentError):
        HybridMode(seed_query="")


def test_global_mode_requires_summary_ids() -> None:
    GlobalMode(summary_record_ids=["sum-1"])
    with pytest.raises(InvalidArgumentError):
        GlobalMode(summary_record_ids=[])


def test_drift_mode_requires_initial_summary_ids() -> None:
    DriftMode(initial_summary_record_ids=["sum-1"])
    with pytest.raises(InvalidArgumentError):
        DriftMode(initial_summary_record_ids=[])


def test_drift_step_input_validates() -> None:
    DriftStepInput(step_id="s-1", seed_record_id="rec-1")
    with pytest.raises(InvalidArgumentError):
        DriftStepInput(step_id="", seed_record_id="rec-1")
    with pytest.raises(InvalidArgumentError):
        DriftStepInput(step_id="s-1", seed_record_id="")


def test_context_request_rejects_mode_options_mismatch() -> None:
    # Hybrid mode without hybrid options.
    with pytest.raises(InvalidArgumentError):
        ContextRequest(scopes=["agent:alpha"], mode="hybrid")
    # Global mode looks for global_mode attribute.
    with pytest.raises(InvalidArgumentError):
        ContextRequest(scopes=["agent:alpha"], mode="global")
    # Unsupported mode entirely.
    with pytest.raises(InvalidArgumentError):
        ContextRequest(scopes=["agent:alpha"], mode="cosmic")  # type: ignore[arg-type]


def test_context_request_requires_scopes() -> None:
    with pytest.raises(InvalidArgumentError):
        ContextRequest(
            scopes=[],
            mode="structural_search",
            structural_search=StructuralSearchMode(query="x"),
        )


def test_context_budget_rejects_non_positive_values() -> None:
    with pytest.raises(InvalidArgumentError):
        ContextBudget(max_items=0)
    with pytest.raises(InvalidArgumentError):
        ContextBudget(max_record_chars=0)


def test_context_item_kinds_enum_is_closed() -> None:
    assert CONTEXT_ITEM_KINDS == {
        "record",
        "memory_block",
        "fact",
        "community",
        "raw_episode",
        "graph_path",
        "summary_reference",
        "drift_step",
    }


def test_context_item_rejects_unknown_kind() -> None:
    with pytest.raises(InvalidArgumentError):
        ContextItem(item_id="x", kind="invent", payload={})  # type: ignore[arg-type]


def test_omitted_diagnostic_rejects_unknown_reason() -> None:
    with pytest.raises(InvalidArgumentError):
        OmittedDiagnostic(
            item_id="x",
            kind="record",
            reason="hallucinated",  # type: ignore[arg-type]
        )


def test_structural_search_assembly(store) -> None:
    package = assemble_context(
        store,
        ContextRequest(
            scopes=["agent:alpha"],
            mode="structural_search",
            structural_search=StructuralSearchMode(query="Berlin"),
        ),
    )
    assert package.mode == "structural_search"
    ids = [item.item_id for item in package.items]
    assert "rec-3" in ids
    for item in package.items:
        assert item.kind == "record"
        assert item.scores
        assert item.scores[0].source == "structural_search"
        # Snippet bounds present.
        assert item.excerpt_bounds is not None
        # Provenance carries record id + namespace.
        assert item.provenance["record_id"] == item.item_id


def test_local_graph_assembly_seed_only(store) -> None:
    package = assemble_context(
        store,
        ContextRequest(
            scopes=["agent:alpha"],
            mode="local_graph",
            local_graph=LocalGraphMode(seed_record_ids=["rec-1"], depth=1),
        ),
    )
    assert package.mode == "local_graph"
    assert [item.item_id for item in package.items] == ["rec-1"]
    assert package.items[0].scores[0].source == "local_graph_seed"


def test_local_graph_assembly_with_neighbor(store) -> None:
    # Add a relation between rec-1 and rec-2.
    store.put_relation(
        MemoryRelation(
            relation_id="rel-1",
            source_record_id="rec-1",
            target_record_id="rec-2",
            relation_type="related_to",
            created_at="2026-05-29T10:00:00+00:00",
        )
    )
    package = assemble_context(
        store,
        ContextRequest(
            scopes=["agent:alpha"],
            mode="local_graph",
            local_graph=LocalGraphMode(seed_record_ids=["rec-1"], depth=1),
        ),
    )
    ids = [item.item_id for item in package.items]
    assert "rec-1" in ids
    assert "rec-2" in ids
    neighbor = next(i for i in package.items if i.item_id == "rec-2")
    assert neighbor.via_paths
    assert neighbor.via_paths[0].nodes == ["rec-1", "rec-2"]


def test_global_context_can_include_structural_community_evidence(store) -> None:
    store.put_relation(
        MemoryRelation(
            relation_id="rel-1",
            source_record_id="rec-1",
            target_record_id="rec-2",
            relation_type="related_to",
            created_at="2026-05-29T10:00:00+00:00",
        )
    )
    store.put_link(
        StructuralLink(
            link_id="link-1",
            source_record_id="rec-1",
            target_record_id="rec-2",
            raw_target="rec-2",
            link_kind="wikilink",
            resolution_status="resolved",
            relation_type="related_to",
            namespace=_ns(),
            created_at="2026-05-29T10:00:00+00:00",
        )
    )

    def community_provider(_request: ContextRequest):
        return query_communities(
            store,
            CommunityQueryOptions(
                detection=CommunityDetectionOptions(
                    scopes=["agent:alpha"],
                    namespaces=[_ns()],
                ),
                include_summary_refs=True,
                summary_reference_ids=["caller-summary"],
            ),
        )

    package = assemble_context(
        store,
        ContextRequest(
            scopes=["agent:alpha"],
            mode="global",
            global_mode=GlobalMode(summary_record_ids=["rec-1"]),
            budget=ContextBudget(max_items=10),
        ),
        community_query_provider=community_provider,
    )

    community_items = [item for item in package.items if item.kind == "community"]
    assert community_items
    assert package.request_provenance["community_query_attached"] is True
    assert community_items[0].payload["summary_reference_ids"] == ["caller-summary"]
    assert community_items[0].provenance["source_set_ids"]


def test_budget_truncation_emits_diagnostics(store) -> None:
    # Force budget below available results.
    package = assemble_context(
        store,
        ContextRequest(
            scopes=["agent:alpha"],
            mode="structural_search",
            structural_search=StructuralSearchMode(query="the"),
            budget=ContextBudget(max_items=1),
        ),
    )
    if len(package.items) + len(package.omitted) >= 2:
        # At least one item was omitted with the budget_exceeded reason.
        assert package.omitted
        assert all(d.reason == "budget_exceeded" for d in package.omitted)


def test_namespace_isolation_in_structural_assembly(tmp_path: Path) -> None:
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
    package = assemble_context(
        s,
        ContextRequest(
            scopes=["agent:alpha"],
            mode="structural_search",
            structural_search=StructuralSearchMode(query="note"),
            namespaces=[MemoryNamespace(agent_id="alpha")],
        ),
    )
    assert [item.item_id for item in package.items] == ["only-a"]


def test_temporal_fact_assembly(store) -> None:
    store.put_fact(
        Fact(
            fact_id="f-1",
            namespace=_ns(),
            subject_entity_id="ent-1",
            predicate="role",
            object_literal="manager",
            provenance=EntityFactProvenance(
                source_kind="user_input", source_id="t-1", actor="user"
            ),
            observed_at="2026-05-29T10:00:00+00:00",
        )
    )
    package = assemble_context(
        store,
        ContextRequest(
            scopes=["agent:alpha"],
            mode="temporal_fact",
            temporal_fact=TemporalFactMode(
                subject_entity_id="ent-1", active_state="active"
            ),
        ),
    )
    assert package.mode == "temporal_fact"
    assert [item.item_id for item in package.items] == ["f-1"]
    assert package.items[0].kind == "fact"
    assert package.items[0].payload["predicate"] == "role"


def test_hybrid_assembly_with_vector_scores_and_fact_lookup(store) -> None:
    def vector_scores(record_ids: Sequence[str]) -> Mapping[str, float]:
        # Stub: boost rec-2 to top.
        return {rid: (0.9 if rid == "rec-2" else 0.1) for rid in record_ids}

    def fact_lookup(
        record_ids: Sequence[str],
    ) -> Mapping[str, Sequence[Mapping[str, Any]]]:
        return {
            "rec-2": [
                {"fact_id": "f-derived", "predicate": "summary", "confidence": 0.7}
            ]
        }

    package = assemble_context(
        store,
        ContextRequest(
            scopes=["agent:alpha"],
            mode="hybrid",
            hybrid=HybridMode(seed_query="agent"),
        ),
        vector_score_lookup=vector_scores,
        fact_lookup=fact_lookup,
    )
    assert package.mode == "hybrid"
    assert package.request_provenance["vector_adapter_attached"] is True
    assert package.request_provenance["fact_adapter_attached"] is True
    # Score components include both structural and vector_adapter sources.
    sources = {
        comp.source
        for item in package.items
        if item.kind == "record"
        for comp in item.scores
    }
    assert {"structural_search", "vector_adapter"}.issubset(sources)
    # Fact lookup hit appears.
    fact_items = [i for i in package.items if i.kind == "fact"]
    assert fact_items
    assert fact_items[0].item_id == "f-derived"


def test_hybrid_assembly_without_adapters_still_works(store) -> None:
    """Adapter absence does not break hybrid mode."""
    package = assemble_context(
        store,
        ContextRequest(
            scopes=["agent:alpha"],
            mode="hybrid",
            hybrid=HybridMode(seed_query="agent"),
        ),
    )
    assert package.items
    for item in package.items:
        if item.kind == "record":
            # Only structural_search source — vector_adapter omitted.
            assert all(c.source == "structural_search" for c in item.scores)


def test_global_mode_records_caller_supplied_summaries(store) -> None:
    captured: list[str] = []

    def summary_provider(ids: Sequence[str]) -> Sequence[Mapping[str, Any]]:
        captured.extend(ids)
        return [
            {"summary_id": sid, "title": f"Summary for {sid}", "caller_supplied": True}
            for sid in ids
        ]

    package = assemble_context(
        store,
        ContextRequest(
            scopes=["agent:alpha"],
            mode="global",
            global_mode=GlobalMode(summary_record_ids=["sum-1", "sum-2"]),
        ),
        summary_provider=summary_provider,
    )
    assert captured == ["sum-1", "sum-2"]
    assert {item.item_id for item in package.items} == {"sum-1", "sum-2"}
    for item in package.items:
        assert item.kind == "summary_reference"
        assert item.payload.get("caller_supplied") is True


def test_drift_mode_records_each_step(store) -> None:
    package = assemble_context(
        store,
        ContextRequest(
            scopes=["agent:alpha"],
            mode="drift",
            drift=DriftMode(
                initial_summary_record_ids=["sum-1"],
                refinement_steps=[
                    DriftStepInput(step_id="step-1", seed_record_id="rec-1"),
                    DriftStepInput(
                        step_id="step-2", seed_record_id="rec-2", note="follow up"
                    ),
                ],
            ),
        ),
    )
    # Initial summary surfaces first, followed by drift_step rows.
    kinds = [item.kind for item in package.items]
    assert kinds[0] == "summary_reference"
    assert "drift_step" in kinds
    # Both step records show up in drift_steps_recorded.
    assert len(package.drift_steps_recorded) == 2
    assert {step["step_id"] for step in package.drift_steps_recorded} == {
        "step-1",
        "step-2",
    }


# Anti-LLM boundary


def test_anti_llm_no_inference_helpers_on_module() -> None:
    from sophiagraph.query import context_assembly as mod

    forbidden = {
        "summarize_records",
        "rewrite_query",
        "generate_follow_up_questions",
        "auto_pick_mode",
        "infer_global_summary",
    }
    assert set(mod.__all__) & forbidden == set()
