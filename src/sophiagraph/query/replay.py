"""Episode replay DTOs and deterministic assembler."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.models import (
    Decision,
    Episode,
    EpisodeStep,
    MemoryNamespace,
    Outcome,
)


@dataclass(frozen=True)
class EpisodeReplayOptions:
    """Caller-supplied options for ``assemble_episode_replay``."""

    episode_id: str
    namespaces: list[MemoryNamespace] | None = None
    step_kind: str | None = None
    occurred_after: str | None = None
    occurred_before: str | None = None
    step_limit: int | None = None
    outcome_limit: int | None = None
    decision_limit: int | None = None

    def __post_init__(self) -> None:
        if not self.episode_id:
            raise InvalidArgumentError("episode_id is required")
        for limit_name, limit_value in (
            ("step_limit", self.step_limit),
            ("outcome_limit", self.outcome_limit),
            ("decision_limit", self.decision_limit),
        ):
            if limit_value is not None and limit_value <= 0:
                raise InvalidArgumentError(f"{limit_name} must be positive")


@dataclass(frozen=True)
class EpisodeReplay:
    """Deterministic package returned by ``assemble_episode_replay``."""

    episode: Episode
    steps: list[EpisodeStep] = field(default_factory=list)
    outcomes: list[Outcome] = field(default_factory=list)
    decisions: list[Decision] = field(default_factory=list)
    linked_artifact_ids: list[str] = field(default_factory=list)
    linked_tool_ids: list[str] = field(default_factory=list)


def _within_time_window(
    occurred_at: str,
    *,
    after: str | None,
    before: str | None,
) -> bool:
    if after is not None and occurred_at < after:
        return False
    if before is not None and occurred_at > before:
        return False
    return True


def assemble_episode_replay(store: Any, options: EpisodeReplayOptions) -> EpisodeReplay:
    """Build a deterministic bounded episode replay package."""

    episode = store.get_episode(options.episode_id)
    if episode is None:
        raise InvalidArgumentError(
            f"episode {options.episode_id!r} not found",
        )
    # Namespace guard: refuse to return data for an episode the caller
    # explicitly filtered out.
    if options.namespaces is not None:
        from sophiagraph.storage.graph_helpers import namespace_matches_filters

        if not namespace_matches_filters(episode.namespace, options.namespaces):
            raise InvalidArgumentError(
                f"episode {options.episode_id!r} is outside the requested namespaces",
            )

    steps = list(
        store.list_episode_steps(
            episode_id=options.episode_id,
            kind=options.step_kind,
            limit=options.step_limit,
        )
    )
    if options.occurred_after or options.occurred_before:
        steps = [
            step
            for step in steps
            if _within_time_window(
                step.occurred_at,
                after=options.occurred_after,
                before=options.occurred_before,
            )
        ]

    outcomes = list(
        store.list_outcomes(
            episode_id=options.episode_id,
            namespaces=options.namespaces,
            limit=options.outcome_limit,
        )
    )
    if options.occurred_after or options.occurred_before:
        outcomes = [
            outcome
            for outcome in outcomes
            if _within_time_window(
                outcome.occurred_at,
                after=options.occurred_after,
                before=options.occurred_before,
            )
        ]
    outcomes.sort(key=lambda o: (o.occurred_at, o.outcome_id))

    decisions = list(
        store.list_decisions(
            episode_id=options.episode_id,
            namespaces=options.namespaces,
            limit=options.decision_limit,
        )
    )
    if options.occurred_after or options.occurred_before:
        decisions = [
            decision
            for decision in decisions
            if _within_time_window(
                decision.occurred_at,
                after=options.occurred_after,
                before=options.occurred_before,
            )
        ]
    decisions.sort(key=lambda d: (d.occurred_at, d.decision_id))

    artifact_ids = list(episode.artifact_ids)
    for step in steps:
        if step.artifact_id and step.artifact_id not in artifact_ids:
            artifact_ids.append(step.artifact_id)

    tool_ids = list(episode.tool_ids)
    for step in steps:
        if step.tool_id and step.tool_id not in tool_ids:
            tool_ids.append(step.tool_id)

    return EpisodeReplay(
        episode=episode,
        steps=steps,
        outcomes=outcomes,
        decisions=decisions,
        linked_artifact_ids=artifact_ids,
        linked_tool_ids=tool_ids,
    )


__all__ = [
    "EpisodeReplay",
    "EpisodeReplayOptions",
    "assemble_episode_replay",
]
