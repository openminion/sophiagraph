"""Shared filter predicates for entity, fact, episode, and procedure rows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from sophiagraph.contracts.errors import InvalidSupersessionError
from sophiagraph.models import (
    Contradiction,
    Decision,
    Entity,
    EntityAlias,
    EntitySummary,
    Episode,
    EpisodeStep,
    Fact,
    FactConvergenceLink,
    MemoryNamespace,
    Outcome,
    Procedure,
    RawEpisode,
)
from sophiagraph.storage.graph_helpers import namespace_matches_filters


@dataclass(frozen=True, slots=True)
class RawEpisodeListOptions:
    namespaces: list[MemoryNamespace] | None = None
    kind: str | None = None
    source: str | None = None
    occurred_after: str | None = None
    occurred_before: str | None = None
    include_invalidated: bool = False
    limit: int | None = None


def entity_passes(
    entity: Entity,
    *,
    namespaces: list[MemoryNamespace] | None,
    canonical_name: str | None,
    entity_type: str | None,
    include_invalidated: bool,
) -> bool:
    if not namespace_matches_filters(entity.namespace, namespaces):
        return False
    if canonical_name and entity.canonical_name != canonical_name:
        return False
    if entity_type and entity.entity_type != entity_type:
        return False
    if not include_invalidated and entity.invalidated_at is not None:
        return False
    return True


def entity_alias_passes(
    alias: EntityAlias,
    *,
    namespaces: list[MemoryNamespace] | None,
    entity_id: str | None,
    alias_name: str | None,
) -> bool:
    if not namespace_matches_filters(alias.namespace, namespaces):
        return False
    if entity_id and alias.entity_id != entity_id:
        return False
    if alias_name and alias.alias_name != alias_name:
        return False
    return True


def fact_passes(
    fact: Fact,
    *,
    namespaces: list[MemoryNamespace] | None,
    subject_entity_id: str | None,
    object_entity_id: str | None,
    predicate: str | None,
    valid_at: str | None,
    learned_at: str | None = None,
    active_state: str = "active",
    source_episode_id: str | None = None,
    include_invalidated: bool,
) -> bool:
    if not namespace_matches_filters(fact.namespace, namespaces):
        return False
    if subject_entity_id and fact.subject_entity_id != subject_entity_id:
        return False
    if object_entity_id and fact.object_entity_id != object_entity_id:
        return False
    if predicate and fact.predicate != predicate:
        return False
    effective_state = "all" if include_invalidated else active_state
    if effective_state == "active" and fact.is_invalidated:
        return False
    if effective_state == "historical" and not fact.is_invalidated:
        return False
    if valid_at is not None:
        # valid_from <= valid_at < valid_to
        if fact.valid_from is not None and valid_at < fact.valid_from:
            return False
        if fact.valid_to is not None and valid_at >= fact.valid_to:
            return False
    if learned_at is not None and fact.observed_at:
        if fact.observed_at > learned_at:
            return False
    if source_episode_id and source_episode_id not in fact.source_episode_ids:
        return False
    return True


def contradiction_passes(
    contra: Contradiction,
    *,
    namespaces: list[MemoryNamespace] | None,
    target_fact_id: str | None,
    contradicting_fact_id: str | None,
) -> bool:
    if not namespace_matches_filters(contra.namespace, namespaces):
        return False
    if target_fact_id and contra.target_fact_id != target_fact_id:
        return False
    if contradicting_fact_id and contra.contradicting_fact_id != contradicting_fact_id:
        return False
    return True


def entity_summary_passes(
    summary: EntitySummary,
    *,
    namespaces: list[MemoryNamespace] | None,
    entity_id: str | None,
    include_invalidated: bool,
) -> bool:
    if not namespace_matches_filters(summary.namespace, namespaces):
        return False
    if entity_id and summary.entity_id != entity_id:
        return False
    if not include_invalidated and summary.invalidated_at is not None:
        return False
    return True


def episode_passes(
    episode: Episode,
    *,
    namespaces: list[MemoryNamespace] | None,
    status: str | None,
    task_id: str | None,
    artifact_id: str | None,
    tool_id: str | None,
    started_after: str | None,
    started_before: str | None,
) -> bool:
    if not namespace_matches_filters(episode.namespace, namespaces):
        return False
    if status and episode.status != status:
        return False
    if task_id and episode.task_id != task_id:
        return False
    if artifact_id and artifact_id not in episode.artifact_ids:
        return False
    if tool_id and tool_id not in episode.tool_ids:
        return False
    if started_after and episode.started_at < started_after:
        return False
    if started_before and episode.started_at > started_before:
        return False
    return True


def episode_step_passes(
    step: EpisodeStep, *, episode_id: str, kind: str | None
) -> bool:
    if step.episode_id != episode_id:
        return False
    if kind and step.kind != kind:
        return False
    return True


def outcome_passes(
    outcome: Outcome,
    *,
    episode_id: str | None,
    step_id: str | None,
    status: str | None,
    namespaces: list[MemoryNamespace] | None,
) -> bool:
    if not namespace_matches_filters(outcome.namespace, namespaces):
        return False
    if episode_id and outcome.episode_id != episode_id:
        return False
    if step_id and outcome.step_id != step_id:
        return False
    if status and outcome.status != status:
        return False
    return True


def decision_passes(
    decision: Decision,
    *,
    episode_id: str | None,
    namespaces: list[MemoryNamespace] | None,
) -> bool:
    if not namespace_matches_filters(decision.namespace, namespaces):
        return False
    if episode_id and decision.episode_id != episode_id:
        return False
    return True


def raw_episode_passes(
    episode: RawEpisode,
    *,
    options: RawEpisodeListOptions,
) -> bool:
    if not namespace_matches_filters(episode.namespace, options.namespaces):
        return False
    if options.kind and episode.kind != options.kind:
        return False
    if options.source and episode.source != options.source:
        return False
    if options.occurred_after and episode.occurred_at < options.occurred_after:
        return False
    if options.occurred_before and episode.occurred_at > options.occurred_before:
        return False
    if not options.include_invalidated and episode.invalidated_at is not None:
        return False
    return True


def fact_convergence_link_passes(
    link: FactConvergenceLink,
    *,
    fact_id: str | None,
    episode_id: str | None,
    namespaces: list[MemoryNamespace] | None,
) -> bool:
    if not namespace_matches_filters(link.namespace, namespaces):
        return False
    if fact_id and link.fact_id != fact_id:
        return False
    if episode_id and link.episode_id != episode_id:
        return False
    return True


def procedure_passes(
    procedure: Procedure,
    *,
    namespaces: list[MemoryNamespace] | None,
    promotion_tier: str | None,
    include_invalidated: bool,
) -> bool:
    if not namespace_matches_filters(procedure.namespace, namespaces):
        return False
    if promotion_tier and procedure.promotion_tier != promotion_tier:
        return False
    if not include_invalidated and procedure.invalidated_at is not None:
        return False
    return True


# SEFT-03 — contradiction validator (callers pre-validate fact references).


def validate_contradiction_references(
    contradiction: Contradiction,
    *,
    known_fact_ids: Iterable[str],
) -> None:
    """Raise ``InvalidSupersessionError`` if either fact ID is unknown."""

    known = set(known_fact_ids)
    if contradiction.target_fact_id not in known:
        raise InvalidSupersessionError(
            f"target_fact_id {contradiction.target_fact_id!r} not found",
            details={
                "contradiction_id": contradiction.contradiction_id,
                "missing": "target_fact_id",
            },
        )
    if contradiction.contradicting_fact_id not in known:
        raise InvalidSupersessionError(
            f"contradicting_fact_id {contradiction.contradicting_fact_id!r} not found",
            details={
                "contradiction_id": contradiction.contradiction_id,
                "missing": "contradicting_fact_id",
            },
        )


__all__ = [
    "RawEpisodeListOptions",
    "contradiction_passes",
    "decision_passes",
    "entity_alias_passes",
    "entity_passes",
    "entity_summary_passes",
    "episode_passes",
    "episode_step_passes",
    "fact_convergence_link_passes",
    "fact_passes",
    "outcome_passes",
    "procedure_passes",
    "raw_episode_passes",
    "validate_contradiction_references",
]
