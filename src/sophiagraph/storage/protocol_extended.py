"""Extended store protocol slices for semantic, temporal, and deletion owners."""

from __future__ import annotations

from typing import Protocol

from sophiagraph.deletion import DeletionCascadeResult, ErasureAuditExport
from sophiagraph.models import (
    ArtifactRecord,
    ArtifactTextProjection,
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
    MemoryRecord,
    MemoryType,
    OntologyDefinition,
    Outcome,
    Procedure,
    RawEpisode,
)


class ExtendedSophiaGraphStore(Protocol):
    """Additional protocol surface for higher-level graph knowledge owners."""

    def put_entity(self, entity: Entity) -> str: ...

    def get_entity(self, entity_id: str) -> Entity | None: ...

    def list_entities(
        self,
        *,
        namespaces: list[MemoryNamespace] | None = None,
        canonical_name: str | None = None,
        entity_type: str | None = None,
        include_invalidated: bool = False,
        limit: int | None = None,
    ) -> list[Entity]: ...

    def put_entity_alias(self, alias: EntityAlias) -> str: ...

    def list_entity_aliases(
        self,
        *,
        entity_id: str | None = None,
        alias_name: str | None = None,
        namespaces: list[MemoryNamespace] | None = None,
        limit: int | None = None,
    ) -> list[EntityAlias]: ...

    def put_fact(self, fact: Fact) -> str: ...

    def get_fact(self, fact_id: str) -> Fact | None: ...

    def list_facts(
        self,
        *,
        namespaces: list[MemoryNamespace] | None = None,
        subject_entity_id: str | None = None,
        object_entity_id: str | None = None,
        predicate: str | None = None,
        valid_at: str | None = None,
        learned_at: str | None = None,
        active_state: str = "active",
        source_episode_id: str | None = None,
        include_invalidated: bool = False,
        limit: int | None = None,
    ) -> list[Fact]: ...

    def put_raw_episode(self, episode: RawEpisode) -> str: ...

    def get_raw_episode(self, episode_id: str) -> RawEpisode | None: ...

    def list_raw_episodes(
        self,
        *,
        namespaces: list[MemoryNamespace] | None = None,
        kind: str | None = None,
        source: str | None = None,
        occurred_after: str | None = None,
        occurred_before: str | None = None,
        include_invalidated: bool = False,
        limit: int | None = None,
    ) -> list[RawEpisode]: ...

    def put_fact_convergence_link(self, link: FactConvergenceLink) -> str: ...

    def list_fact_convergence_links(
        self,
        *,
        fact_id: str | None = None,
        episode_id: str | None = None,
        namespaces: list[MemoryNamespace] | None = None,
        limit: int | None = None,
    ) -> list[FactConvergenceLink]: ...

    def put_ontology(self, ontology: OntologyDefinition) -> tuple[str, str]: ...

    def get_ontology(
        self,
        *,
        ontology_id: str,
        version: str,
    ) -> OntologyDefinition | None: ...

    def list_ontologies(
        self,
        *,
        ontology_id: str | None = None,
        owner: str | None = None,
        namespaces: list[MemoryNamespace] | None = None,
        limit: int | None = None,
    ) -> list[OntologyDefinition]: ...

    def record_contradiction(self, contradiction: Contradiction) -> Contradiction: ...

    def list_contradictions(
        self,
        *,
        target_fact_id: str | None = None,
        contradicting_fact_id: str | None = None,
        namespaces: list[MemoryNamespace] | None = None,
        limit: int | None = None,
    ) -> list[Contradiction]: ...

    def put_entity_summary(self, summary: EntitySummary) -> str: ...

    def get_entity_summary(self, summary_id: str) -> EntitySummary | None: ...

    def list_entity_summaries(
        self,
        *,
        entity_id: str | None = None,
        namespaces: list[MemoryNamespace] | None = None,
        include_invalidated: bool = False,
        limit: int | None = None,
    ) -> list[EntitySummary]: ...

    def put_episode(self, episode: Episode) -> str: ...

    def get_episode(self, episode_id: str) -> Episode | None: ...

    def list_episodes(
        self,
        *,
        namespaces: list[MemoryNamespace] | None = None,
        status: str | None = None,
        task_id: str | None = None,
        artifact_id: str | None = None,
        tool_id: str | None = None,
        started_after: str | None = None,
        started_before: str | None = None,
        limit: int | None = None,
    ) -> list[Episode]: ...

    def put_episode_step(self, step: EpisodeStep) -> str: ...

    def list_episode_steps(
        self,
        *,
        episode_id: str,
        kind: str | None = None,
        limit: int | None = None,
    ) -> list[EpisodeStep]: ...

    def put_outcome(self, outcome: Outcome) -> str: ...

    def list_outcomes(
        self,
        *,
        episode_id: str | None = None,
        step_id: str | None = None,
        status: str | None = None,
        namespaces: list[MemoryNamespace] | None = None,
        limit: int | None = None,
    ) -> list[Outcome]: ...

    def put_decision(self, decision: Decision) -> str: ...

    def list_decisions(
        self,
        *,
        episode_id: str | None = None,
        namespaces: list[MemoryNamespace] | None = None,
        limit: int | None = None,
    ) -> list[Decision]: ...

    def put_procedure(self, procedure: Procedure) -> str: ...

    def get_procedure(self, procedure_id: str) -> Procedure | None: ...

    def list_procedures(
        self,
        *,
        namespaces: list[MemoryNamespace] | None = None,
        promotion_tier: str | None = None,
        include_invalidated: bool = False,
        limit: int | None = None,
    ) -> list[Procedure]: ...

    def put_artifact(self, artifact: ArtifactRecord) -> str: ...

    def get_artifact(self, artifact_id: str) -> ArtifactRecord | None: ...

    def list_artifacts(
        self,
        *,
        namespaces: list[MemoryNamespace] | None = None,
        target_record_id: str | None = None,
        source_class: str | None = None,
        limit: int | None = None,
    ) -> list[ArtifactRecord]: ...

    def put_artifact_projection(self, projection: ArtifactTextProjection) -> str: ...

    def get_artifact_projection(
        self, projection_id: str
    ) -> ArtifactTextProjection | None: ...

    def list_artifact_projections(
        self,
        *,
        namespaces: list[MemoryNamespace] | None = None,
        artifact_id: str | None = None,
        derived_text_record_id: str | None = None,
        projection_kinds: list[str] | None = None,
        include_superseded: bool = True,
        limit: int | None = None,
    ) -> list[ArtifactTextProjection]: ...

    def mark_artifact_projection_superseded(
        self,
        projection_id: str,
        *,
        superseded_by_projection_id: str,
        superseded_at: str,
    ) -> ArtifactTextProjection: ...

    def tombstone_record(
        self,
        record_id: str,
        *,
        deleted_at: str,
        reason: str,
    ) -> MemoryRecord: ...

    def cascade_tombstones(
        self,
        record_id: str,
        *,
        deleted_at: str,
        reason: str,
    ) -> DeletionCascadeResult: ...

    def erasure_audit_export(
        self,
        *,
        record_id: str | None = None,
        namespaces: list[MemoryNamespace] | None = None,
    ) -> ErasureAuditExport: ...

    def history(
        self,
        scope: str,
        type: MemoryType,
        key: str,
    ) -> list[MemoryRecord]: ...
