"""Temporal context graph convergence coverage."""

from __future__ import annotations

from pathlib import Path

import pytest

from sophiagraph import SophiaGraphMemoryStore, SophiaGraphSqliteStore
from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.models import (
    Contradiction,
    Fact,
    FactConvergenceLink,
    MemoryNamespace,
    RAW_EPISODE_KINDS,
    RawEpisode,
)
from sophiagraph.models.entity_fact import EntityFactProvenance
from sophiagraph.storage.entity_episode_store import RawEpisodeListOptions


def _ns_a() -> MemoryNamespace:
    return MemoryNamespace(tenant_id="acme", agent_id="alpha")


def _ns_b() -> MemoryNamespace:
    return MemoryNamespace(tenant_id="acme", agent_id="beta")


def _prov() -> EntityFactProvenance:
    return EntityFactProvenance(
        source_kind="tool_observation", source_id="ingest-1", actor="agent"
    )


@pytest.fixture(params=["memory", "sqlite"])
def store(request, tmp_path: Path):
    if request.param == "memory":
        return SophiaGraphMemoryStore()
    return SophiaGraphSqliteStore(tmp_path / "sg.sqlite3")


def _raw_episode(
    episode_id: str = "ep-r1",
    *,
    kind: str = "user_input",
    occurred_at: str = "2026-05-29T10:00:00",
    namespace: MemoryNamespace | None = None,
    actor: str = "user",
) -> RawEpisode:
    return RawEpisode(
        episode_id=episode_id,
        kind=kind,
        source="chat",
        source_id=f"msg-{episode_id}",
        namespace=namespace or _ns_a(),
        occurred_at=occurred_at,
        ingested_at=occurred_at,
        payload={"text": "(opaque caller payload)"},
        provenance=_prov(),
        actor=actor,
    )


def _fact(
    fact_id: str = "f-1",
    *,
    observed_at: str = "2026-05-29T10:00:00",
    valid_from: str | None = None,
    valid_to: str | None = None,
    object_literal: str = "x",
    source_episode_ids: list[str] | None = None,
    namespace: MemoryNamespace | None = None,
) -> Fact:
    return Fact(
        fact_id=fact_id,
        namespace=namespace or _ns_a(),
        subject_entity_id="ent-1",
        predicate="claims",
        object_literal=object_literal,
        provenance=_prov(),
        observed_at=observed_at,
        valid_from=valid_from,
        valid_to=valid_to,
        source_episode_ids=source_episode_ids or [],
    )


def test_raw_episode_round_trip(store) -> None:
    ep = _raw_episode()
    store.put_raw_episode(ep)
    loaded = store.get_raw_episode("ep-r1")
    assert loaded is not None
    assert loaded.kind == "user_input"
    assert loaded.source == "chat"
    assert loaded.payload == {"text": "(opaque caller payload)"}


def test_raw_episode_namespace_isolation(store) -> None:
    store.put_raw_episode(_raw_episode("ep-a", namespace=_ns_a()))
    store.put_raw_episode(_raw_episode("ep-b", namespace=_ns_b()))
    only_a = store.list_raw_episodes(namespaces=[_ns_a()])
    only_b = store.list_raw_episodes(namespaces=[_ns_b()])
    assert {ep.episode_id for ep in only_a} == {"ep-a"}
    assert {ep.episode_id for ep in only_b} == {"ep-b"}


def test_raw_episode_filters_by_kind_and_source(store) -> None:
    store.put_raw_episode(
        _raw_episode("ep-1", kind="user_input", occurred_at="2026-05-29T10:00:00")
    )
    store.put_raw_episode(
        _raw_episode("ep-2", kind="tool_output", occurred_at="2026-05-29T10:05:00")
    )
    tool_only = store.list_raw_episodes(kind="tool_output")
    assert [ep.episode_id for ep in tool_only] == ["ep-2"]
    chat_only = store.list_raw_episodes(source="chat")
    assert {ep.episode_id for ep in chat_only} == {"ep-1", "ep-2"}


def test_raw_episode_rejects_unknown_kind() -> None:
    with pytest.raises(InvalidArgumentError):
        RawEpisode(
            episode_id="ep-x",
            kind="hallucinated_kind",  # type: ignore[arg-type]
            source="chat",
            source_id="x",
            namespace=_ns_a(),
            occurred_at="2026-05-29T10:00:00",
            ingested_at="2026-05-29T10:00:00",
            payload={},
            provenance=_prov(),
        )


def test_raw_episode_kinds_enum_is_closed() -> None:
    assert RAW_EPISODE_KINDS == {
        "message",
        "tool_output",
        "user_input",
        "system_event",
        "validation_result",
        "import_event",
    }


def test_raw_episode_list_options_validate_namespaces_limit_and_time_window() -> None:
    with pytest.raises(
        InvalidArgumentError, match="namespaces must contain MemoryNamespace values"
    ):
        RawEpisodeListOptions(namespaces=[_ns_a(), "bad"])  # type: ignore[list-item]

    with pytest.raises(InvalidArgumentError, match="limit must be positive"):
        RawEpisodeListOptions(limit=0)

    with pytest.raises(
        InvalidArgumentError,
        match="occurred_after must be less than or equal to occurred_before",
    ):
        RawEpisodeListOptions(
            occurred_after="2026-05-29T10:05:00",
            occurred_before="2026-05-29T10:00:00",
        )


def test_fact_source_episode_ids_round_trip(store) -> None:
    store.put_raw_episode(_raw_episode("ep-1"))
    store.put_fact(_fact("f-1", source_episode_ids=["ep-1"]))
    loaded = store.get_fact("f-1")
    assert loaded is not None
    assert loaded.source_episode_ids == ["ep-1"]


def test_list_facts_filters_by_source_episode(store) -> None:
    store.put_fact(
        _fact("f-a", source_episode_ids=["ep-1"], observed_at="2026-05-29T10:00:00")
    )
    store.put_fact(
        _fact("f-b", source_episode_ids=["ep-2"], observed_at="2026-05-29T10:05:00")
    )
    matched = store.list_facts(source_episode_id="ep-1")
    assert [f.fact_id for f in matched] == ["f-a"]


def test_fact_convergence_link_round_trip(store) -> None:
    store.put_fact(_fact("f-1", source_episode_ids=["ep-1"]))
    store.put_raw_episode(_raw_episode("ep-1"))
    link = FactConvergenceLink(
        link_id="lnk-1",
        fact_id="f-1",
        episode_id="ep-1",
        namespace=_ns_a(),
        role="primary",
        confidence=1.0,
        created_at="2026-05-29T10:00:00",
    )
    store.put_fact_convergence_link(link)
    by_fact = store.list_fact_convergence_links(fact_id="f-1")
    by_episode = store.list_fact_convergence_links(episode_id="ep-1")
    assert [link.link_id for link in by_fact] == ["lnk-1"]
    assert [link.link_id for link in by_episode] == ["lnk-1"]


def test_fact_convergence_link_namespace_isolation(store) -> None:
    store.put_fact_convergence_link(
        FactConvergenceLink(
            link_id="lnk-a",
            fact_id="f-x",
            episode_id="ep-x",
            namespace=_ns_a(),
            role="primary",
        )
    )
    store.put_fact_convergence_link(
        FactConvergenceLink(
            link_id="lnk-b",
            fact_id="f-x",
            episode_id="ep-x",
            namespace=_ns_b(),
            role="primary",
        )
    )
    only_a = store.list_fact_convergence_links(namespaces=[_ns_a()])
    assert {link.link_id for link in only_a} == {"lnk-a"}


def test_supersession_marks_target_historical(store) -> None:
    store.put_fact(_fact("f-old", object_literal="manager"))
    store.put_fact(
        _fact("f-new", object_literal="ic", observed_at="2026-06-01T00:00:00")
    )
    store.record_contradiction(
        Contradiction(
            contradiction_id="c-1",
            namespace=_ns_a(),
            target_fact_id="f-old",
            contradicting_fact_id="f-new",
            decision="supersedes",
            deciding_actor="user",
            decided_at="2026-06-01T00:00:00",
        )
    )
    active = store.list_facts(active_state="active")
    historical = store.list_facts(active_state="historical")
    # active excludes the superseded fact
    assert {f.fact_id for f in active} == {"f-new"}
    # historical returns it with invalidation evidence
    assert [f.fact_id for f in historical] == ["f-old"]
    assert historical[0].superseded_by_fact_id == "f-new"


def test_active_state_all_returns_both(store) -> None:
    store.put_fact(_fact("f-old"))
    store.put_fact(_fact("f-new", observed_at="2026-06-01T00:00:00"))
    store.record_contradiction(
        Contradiction(
            contradiction_id="c-1",
            namespace=_ns_a(),
            target_fact_id="f-old",
            contradicting_fact_id="f-new",
            decision="supersedes",
            deciding_actor="user",
            decided_at="2026-06-01T00:00:00",
        )
    )
    all_facts = store.list_facts(active_state="all")
    assert {f.fact_id for f in all_facts} == {"f-old", "f-new"}


def test_valid_at_window(store) -> None:
    store.put_fact(
        _fact(
            "f-2021",
            valid_from="2021-01-01",
            valid_to="2022-12-31",
            object_literal="Berlin",
        )
    )
    store.put_fact(
        _fact(
            "f-2023",
            valid_from="2023-01-01",
            object_literal="Paris",
            observed_at="2023-01-01",
        )
    )
    in_2022 = store.list_facts(valid_at="2022-06-01")
    in_2024 = store.list_facts(valid_at="2024-06-01")
    assert [f.fact_id for f in in_2022] == ["f-2021"]
    assert [f.fact_id for f in in_2024] == ["f-2023"]


def test_learned_at_excludes_facts_observed_later(store) -> None:
    store.put_fact(_fact("f-early", observed_at="2026-05-01"))
    store.put_fact(_fact("f-late", observed_at="2026-06-01"))
    seen_by_may = store.list_facts(learned_at="2026-05-15")
    assert [f.fact_id for f in seen_by_may] == ["f-early"]


def test_namespace_isolation_on_fact_queries(store) -> None:
    store.put_fact(_fact("f-a", namespace=_ns_a()))
    store.put_fact(_fact("f-b", namespace=_ns_b()))
    only_a = store.list_facts(namespaces=[_ns_a()])
    only_b = store.list_facts(namespaces=[_ns_b()])
    assert {f.fact_id for f in only_a} == {"f-a"}
    assert {f.fact_id for f in only_b} == {"f-b"}


def test_delta_replay_preserves_convergence_state(tmp_path: Path) -> None:
    source = SophiaGraphSqliteStore(tmp_path / "src.sqlite3")
    source.put_raw_episode(_raw_episode("ep-1"))
    source.put_fact(_fact("f-1", source_episode_ids=["ep-1"]))
    source.put_fact_convergence_link(
        FactConvergenceLink(
            link_id="lnk-1",
            fact_id="f-1",
            episode_id="ep-1",
            namespace=_ns_a(),
            role="primary",
        )
    )
    delta = source.export_delta()
    target = SophiaGraphSqliteStore(tmp_path / "tgt.sqlite3")
    result = target.import_delta(delta)
    assert result.applied is True
    assert target.get_raw_episode("ep-1") is not None
    assert target.get_fact("f-1") is not None
    assert target.list_fact_convergence_links(fact_id="f-1")[0].link_id == "lnk-1"

    # Replay the same delta → idempotent: nothing new applied.
    result2 = target.import_delta(delta)
    assert result2.skipped_changes >= result.imported_changes


def test_memory_delta_replay_preserves_convergence_state() -> None:
    source = SophiaGraphMemoryStore()
    source.put_raw_episode(_raw_episode("ep-1"))
    source.put_fact(_fact("f-1", source_episode_ids=["ep-1"]))
    source.put_fact_convergence_link(
        FactConvergenceLink(
            link_id="lnk-1",
            fact_id="f-1",
            episode_id="ep-1",
            namespace=_ns_a(),
            role="primary",
        )
    )
    delta = source.export_delta()
    target = SophiaGraphMemoryStore()
    result = target.import_delta(delta)
    assert result.applied is True
    assert target.get_raw_episode("ep-1") is not None
    assert target.list_fact_convergence_links(fact_id="f-1")[0].link_id == "lnk-1"


# Anti-LLM boundary


def test_anti_llm_no_inference_helpers_in_convergence_module() -> None:
    from sophiagraph.models import convergence as mod

    forbidden = {
        "extract_facts_from_episode",
        "summarize_episode",
        "infer_invalidations_from_text",
        "auto_link_facts_to_episodes",
    }
    assert set(mod.__all__) & forbidden == set()
