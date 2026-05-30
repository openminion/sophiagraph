"""Episodic/procedural memory and replay coverage."""

from __future__ import annotations

from pathlib import Path

import pytest

from sophiagraph import SophiaGraphMemoryStore, SophiaGraphSqliteStore
from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.models import (
    Decision,
    Episode,
    EpisodeStep,
    MemoryNamespace,
    Outcome,
    Procedure,
    ProcedureStep,
)
from sophiagraph.query import EpisodeReplayOptions, assemble_episode_replay


def _ns_a() -> MemoryNamespace:
    return MemoryNamespace(tenant_id="acme", agent_id="alpha")


def _ns_b() -> MemoryNamespace:
    return MemoryNamespace(tenant_id="acme", agent_id="beta")


@pytest.fixture(params=["memory", "sqlite"])
def store(request, tmp_path: Path):
    if request.param == "memory":
        return SophiaGraphMemoryStore()
    return SophiaGraphSqliteStore(tmp_path / "sg.sqlite3")


def _episode(
    episode_id: str = "ep-1",
    started_at: str = "2026-05-29T10:00:00",
    status: str = "in_progress",
    namespace: MemoryNamespace | None = None,
    artifact_ids: list[str] | None = None,
) -> Episode:
    return Episode(
        episode_id=episode_id,
        namespace=namespace or _ns_a(),
        title="Task A",
        status=status,
        started_at=started_at,
        artifact_ids=artifact_ids or [],
    )


def _step(
    step_id: str,
    seq: int,
    occurred_at: str,
    *,
    episode_id: str = "ep-1",
    kind: str = "thought",
    artifact_id: str | None = None,
    namespace: MemoryNamespace | None = None,
) -> EpisodeStep:
    return EpisodeStep(
        step_id=step_id,
        episode_id=episode_id,
        namespace=namespace or _ns_a(),
        kind=kind,
        sequence=seq,
        occurred_at=occurred_at,
        artifact_id=artifact_id,
    )


# SEPM-01 — DTO validation


def test_episode_requires_title() -> None:
    with pytest.raises(InvalidArgumentError):
        Episode(
            episode_id="ep-1",
            namespace=_ns_a(),
            title="",
            status="in_progress",
            started_at="2026-05-29T10:00:00",
        )


def test_episode_rejects_invalid_status() -> None:
    with pytest.raises(InvalidArgumentError):
        Episode(
            episode_id="ep-1",
            namespace=_ns_a(),
            title="X",
            status="cosmic",  # type: ignore[arg-type]
            started_at="2026-05-29T10:00:00",
        )


def test_episode_ended_at_must_be_after_started_at() -> None:
    with pytest.raises(InvalidArgumentError):
        Episode(
            episode_id="ep-1",
            namespace=_ns_a(),
            title="X",
            status="succeeded",
            started_at="2026-05-29T10:00:00",
            ended_at="2026-05-28T00:00:00",
        )


def test_step_rejects_invalid_kind() -> None:
    with pytest.raises(InvalidArgumentError):
        EpisodeStep(
            step_id="s-1",
            episode_id="ep-1",
            namespace=_ns_a(),
            kind="invent_a_kind",  # type: ignore[arg-type]
            sequence=0,
            occurred_at="2026-05-29T10:00:00",
        )


def test_outcome_requires_episode_or_step() -> None:
    with pytest.raises(InvalidArgumentError):
        Outcome(
            outcome_id="o-1",
            namespace=_ns_a(),
            status="succeeded",
            occurred_at="2026-05-29T10:05:00",
        )


def test_procedure_promotion_tier_enum() -> None:
    with pytest.raises(InvalidArgumentError):
        Procedure(
            procedure_id="p-1",
            namespace=_ns_a(),
            title="X",
            promotion_tier="cosmic",  # type: ignore[arg-type]
            created_at="2026-05-29T10:00:00",
        )


def test_decision_requires_chosen() -> None:
    with pytest.raises(InvalidArgumentError):
        Decision(
            decision_id="d-1",
            namespace=_ns_a(),
            title="Pick stack",
            chosen="",
            occurred_at="2026-05-29T10:00:00",
        )


def test_anti_llm_no_inference_on_episode_module() -> None:
    from sophiagraph.models import episode_procedure as mod

    forbidden = {
        "infer_outcome_from_text",
        "summarize_episode",
        "extract_procedure_from_prose",
        "auto_promote_procedure",
    }
    assert set(mod.__all__) & forbidden == set()


# SEPM-02 — persistence + namespace isolation


def test_episode_round_trip(store) -> None:
    ep = _episode(artifact_ids=["art-1", "art-2"])
    store.put_episode(ep)
    loaded = store.get_episode("ep-1")
    assert loaded is not None
    assert loaded.title == "Task A"
    assert loaded.artifact_ids == ["art-1", "art-2"]


def test_list_episodes_namespace_isolation(store) -> None:
    store.put_episode(_episode(episode_id="ep-a", namespace=_ns_a()))
    store.put_episode(_episode(episode_id="ep-b", namespace=_ns_b()))
    only_a = store.list_episodes(namespaces=[_ns_a()])
    only_b = store.list_episodes(namespaces=[_ns_b()])
    assert {ep.episode_id for ep in only_a} == {"ep-a"}
    assert {ep.episode_id for ep in only_b} == {"ep-b"}


def test_list_episodes_filters_by_status_and_artifact(store) -> None:
    store.put_episode(_episode(episode_id="ep-1", status="succeeded"))
    store.put_episode(
        _episode(episode_id="ep-2", status="failed", artifact_ids=["art-1"])
    )
    succeeded = store.list_episodes(status="succeeded")
    assert [ep.episode_id for ep in succeeded] == ["ep-1"]
    with_art = store.list_episodes(artifact_id="art-1")
    assert [ep.episode_id for ep in with_art] == ["ep-2"]


def test_outcome_and_decision_persist(store) -> None:
    store.put_episode(_episode())
    store.put_outcome(
        Outcome(
            outcome_id="o-1",
            namespace=_ns_a(),
            status="succeeded",
            occurred_at="2026-05-29T10:05:00",
            episode_id="ep-1",
        )
    )
    store.put_decision(
        Decision(
            decision_id="d-1",
            namespace=_ns_a(),
            title="Pick stack",
            chosen="python",
            occurred_at="2026-05-29T10:02:00",
            episode_id="ep-1",
            alternatives=["go", "rust"],
        )
    )
    assert store.list_outcomes(episode_id="ep-1")[0].outcome_id == "o-1"
    assert store.list_decisions(episode_id="ep-1")[0].decision_id == "d-1"


def test_procedure_round_trip_with_steps(store) -> None:
    store.put_procedure(
        Procedure(
            procedure_id="p-1",
            namespace=_ns_a(),
            title="Run focused tests",
            promotion_tier="experimental",
            created_at="2026-05-29T10:00:00",
            updated_at="2026-05-29T10:00:00",
            steps=[
                ProcedureStep(sequence=0, title="cd module"),
                ProcedureStep(sequence=1, title="run pytest", tool_id="bash"),
            ],
        )
    )
    loaded = store.get_procedure("p-1")
    assert loaded is not None
    assert len(loaded.steps) == 2
    assert loaded.steps[1].tool_id == "bash"


# SEPM-03 — replay


def _seed_replay_data(store) -> None:
    store.put_episode(_episode(artifact_ids=["art-seed"]))
    store.put_episode_step(_step("s-2", 1, "2026-05-29T10:02:00"))
    store.put_episode_step(_step("s-1", 0, "2026-05-29T10:01:00"))
    store.put_episode_step(
        _step(
            "s-3", 2, "2026-05-29T10:03:00", kind="tool_call", artifact_id="art-extra"
        )
    )
    store.put_outcome(
        Outcome(
            outcome_id="o-2",
            namespace=_ns_a(),
            status="succeeded",
            occurred_at="2026-05-29T10:05:00",
            episode_id="ep-1",
        )
    )
    store.put_outcome(
        Outcome(
            outcome_id="o-1",
            namespace=_ns_a(),
            status="partial",
            occurred_at="2026-05-29T10:04:00",
            episode_id="ep-1",
        )
    )
    store.put_decision(
        Decision(
            decision_id="d-1",
            namespace=_ns_a(),
            title="Choose tool",
            chosen="bash",
            occurred_at="2026-05-29T10:02:30",
            episode_id="ep-1",
        )
    )


def test_replay_deterministic_order(store) -> None:
    _seed_replay_data(store)
    replay = assemble_episode_replay(store, EpisodeReplayOptions(episode_id="ep-1"))
    # Steps in sequence order.
    assert [s.step_id for s in replay.steps] == ["s-1", "s-2", "s-3"]
    # Outcomes in occurred_at order.
    assert [o.outcome_id for o in replay.outcomes] == ["o-1", "o-2"]
    assert [d.decision_id for d in replay.decisions] == ["d-1"]
    # Artifact collection: seeded + step.artifact_id.
    assert set(replay.linked_artifact_ids) == {"art-seed", "art-extra"}


def test_replay_namespace_isolation(store) -> None:
    _seed_replay_data(store)
    with pytest.raises(InvalidArgumentError):
        assemble_episode_replay(
            store,
            EpisodeReplayOptions(episode_id="ep-1", namespaces=[_ns_b()]),
        )


def test_replay_time_window(store) -> None:
    _seed_replay_data(store)
    replay = assemble_episode_replay(
        store,
        EpisodeReplayOptions(
            episode_id="ep-1",
            occurred_after="2026-05-29T10:02:00",
            occurred_before="2026-05-29T10:04:30",
        ),
    )
    # s-1 (10:01) excluded; s-2 (10:02) and s-3 (10:03) included.
    assert [s.step_id for s in replay.steps] == ["s-2", "s-3"]
    # o-2 (10:05) excluded; o-1 (10:04) included.
    assert [o.outcome_id for o in replay.outcomes] == ["o-1"]


def test_replay_step_limit_respected(store) -> None:
    _seed_replay_data(store)
    replay = assemble_episode_replay(
        store, EpisodeReplayOptions(episode_id="ep-1", step_limit=2)
    )
    assert len(replay.steps) == 2


def test_replay_rejects_unknown_episode(store) -> None:
    with pytest.raises(InvalidArgumentError):
        assemble_episode_replay(store, EpisodeReplayOptions(episode_id="ep-missing"))


def test_replay_options_rejects_non_positive_limit() -> None:
    with pytest.raises(InvalidArgumentError):
        EpisodeReplayOptions(episode_id="ep-1", step_limit=0)
