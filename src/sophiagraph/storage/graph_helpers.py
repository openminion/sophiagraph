"""Shared structural-link and graph helpers for package stores."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from sophiagraph.models import (
    CategorySchema,
    Contradiction,
    Decision,
    EdgeTypeSchema,
    Entity,
    EntityAlias,
    EntityFactProvenance,
    EntitySummary,
    EntityTypeSchema,
    Episode,
    EpisodeStep,
    Fact,
    FactConvergenceLink,
    KnowledgeDocumentBlock,
    MemoryBlock,
    MemoryNamespace,
    MemoryRecord,
    OntologyDefinition,
    Outcome,
    Procedure,
    ProcedureStep,
    PropertySchema,
    RawEpisode,
    StructuralLink,
)
from sophiagraph.query import GraphEdge, GraphNode, StructuralSearchQuery


def namespace_matches_filters(
    namespace: MemoryNamespace,
    filters: list[MemoryNamespace] | None,
) -> bool:
    if not filters:
        return True
    return any(namespace.matches(item) for item in filters)


def link_to_dict(link: StructuralLink) -> dict[str, Any]:
    return asdict(link)


def link_from_dict(data: dict[str, Any]) -> StructuralLink:
    payload = dict(data)
    raw_namespace = payload.get("namespace")
    if isinstance(raw_namespace, dict):
        payload["namespace"] = MemoryNamespace.from_dict(raw_namespace)
    return StructuralLink(**payload)


def block_to_dict(block: KnowledgeDocumentBlock) -> dict[str, Any]:
    return asdict(block)


def block_from_dict(data: dict[str, Any]) -> KnowledgeDocumentBlock:
    return KnowledgeDocumentBlock(**dict(data))


def _ns_dict_to_object(value: Any) -> MemoryNamespace:
    if isinstance(value, MemoryNamespace):
        return value
    if isinstance(value, dict):
        return MemoryNamespace.from_dict(value)
    raise TypeError("namespace payload must be MemoryNamespace or dict")


def _provenance_dict_to_object(value: Any) -> EntityFactProvenance:
    if isinstance(value, EntityFactProvenance):
        return value
    if isinstance(value, dict):
        return EntityFactProvenance(**dict(value))
    raise TypeError("provenance payload must be EntityFactProvenance or dict")


def entity_to_dict(entity: Entity) -> dict[str, Any]:
    payload = asdict(entity)
    if isinstance(entity.namespace, MemoryNamespace):
        payload["namespace"] = entity.namespace.as_dict()
    payload["meta"] = dict(entity.meta)
    return payload


def entity_from_dict(data: dict[str, Any]) -> Entity:
    payload = dict(data)
    payload["namespace"] = _ns_dict_to_object(payload.get("namespace"))
    payload["provenance"] = _provenance_dict_to_object(payload.get("provenance"))
    return Entity(**payload)


def entity_alias_to_dict(alias: EntityAlias) -> dict[str, Any]:
    payload = asdict(alias)
    if isinstance(alias.namespace, MemoryNamespace):
        payload["namespace"] = alias.namespace.as_dict()
    payload["meta"] = dict(alias.meta)
    return payload


def entity_alias_from_dict(data: dict[str, Any]) -> EntityAlias:
    payload = dict(data)
    payload["namespace"] = _ns_dict_to_object(payload.get("namespace"))
    payload["provenance"] = _provenance_dict_to_object(payload.get("provenance"))
    return EntityAlias(**payload)


def fact_to_dict(fact: Fact) -> dict[str, Any]:
    payload = asdict(fact)
    if isinstance(fact.namespace, MemoryNamespace):
        payload["namespace"] = fact.namespace.as_dict()
    payload["meta"] = dict(fact.meta)
    return payload


def fact_from_dict(data: dict[str, Any]) -> Fact:
    payload = dict(data)
    payload["namespace"] = _ns_dict_to_object(payload.get("namespace"))
    raw_prov = payload.get("provenance")
    if raw_prov is not None:
        payload["provenance"] = _provenance_dict_to_object(raw_prov)
    return Fact(**payload)


def contradiction_to_dict(contra: Contradiction) -> dict[str, Any]:
    payload = asdict(contra)
    if isinstance(contra.namespace, MemoryNamespace):
        payload["namespace"] = contra.namespace.as_dict()
    payload["meta"] = dict(contra.meta)
    return payload


def contradiction_from_dict(data: dict[str, Any]) -> Contradiction:
    payload = dict(data)
    payload["namespace"] = _ns_dict_to_object(payload.get("namespace"))
    return Contradiction(**payload)


def entity_summary_to_dict(summary: EntitySummary) -> dict[str, Any]:
    payload = asdict(summary)
    if isinstance(summary.namespace, MemoryNamespace):
        payload["namespace"] = summary.namespace.as_dict()
    payload["meta"] = dict(summary.meta)
    return payload


def entity_summary_from_dict(data: dict[str, Any]) -> EntitySummary:
    payload = dict(data)
    payload["namespace"] = _ns_dict_to_object(payload.get("namespace"))
    payload["provenance"] = _provenance_dict_to_object(payload.get("provenance"))
    return EntitySummary(**payload)


def episode_to_dict(episode: Episode) -> dict[str, Any]:
    payload = asdict(episode)
    if isinstance(episode.namespace, MemoryNamespace):
        payload["namespace"] = episode.namespace.as_dict()
    payload["meta"] = dict(episode.meta)
    return payload


def episode_from_dict(data: dict[str, Any]) -> Episode:
    payload = dict(data)
    payload["namespace"] = _ns_dict_to_object(payload.get("namespace"))
    return Episode(**payload)


def episode_step_to_dict(step: EpisodeStep) -> dict[str, Any]:
    payload = asdict(step)
    if isinstance(step.namespace, MemoryNamespace):
        payload["namespace"] = step.namespace.as_dict()
    payload["meta"] = dict(step.meta)
    return payload


def episode_step_from_dict(data: dict[str, Any]) -> EpisodeStep:
    payload = dict(data)
    payload["namespace"] = _ns_dict_to_object(payload.get("namespace"))
    return EpisodeStep(**payload)


def outcome_to_dict(outcome: Outcome) -> dict[str, Any]:
    payload = asdict(outcome)
    if isinstance(outcome.namespace, MemoryNamespace):
        payload["namespace"] = outcome.namespace.as_dict()
    payload["meta"] = dict(outcome.meta)
    return payload


def outcome_from_dict(data: dict[str, Any]) -> Outcome:
    payload = dict(data)
    payload["namespace"] = _ns_dict_to_object(payload.get("namespace"))
    return Outcome(**payload)


def decision_to_dict(decision: Decision) -> dict[str, Any]:
    payload = asdict(decision)
    if isinstance(decision.namespace, MemoryNamespace):
        payload["namespace"] = decision.namespace.as_dict()
    payload["meta"] = dict(decision.meta)
    return payload


def decision_from_dict(data: dict[str, Any]) -> Decision:
    payload = dict(data)
    payload["namespace"] = _ns_dict_to_object(payload.get("namespace"))
    return Decision(**payload)


def procedure_to_dict(procedure: Procedure) -> dict[str, Any]:
    payload = asdict(procedure)
    if isinstance(procedure.namespace, MemoryNamespace):
        payload["namespace"] = procedure.namespace.as_dict()
    payload["meta"] = dict(procedure.meta)
    payload["steps"] = [asdict(step) for step in procedure.steps]
    return payload


def procedure_from_dict(data: dict[str, Any]) -> Procedure:
    payload = dict(data)
    payload["namespace"] = _ns_dict_to_object(payload.get("namespace"))
    raw_steps = payload.get("steps", [])
    payload["steps"] = [
        s if isinstance(s, ProcedureStep) else ProcedureStep(**dict(s))
        for s in raw_steps
    ]
    return Procedure(**payload)


def ontology_to_dict(ontology: OntologyDefinition) -> dict[str, Any]:
    payload = asdict(ontology)
    if isinstance(ontology.namespace, MemoryNamespace):
        payload["namespace"] = ontology.namespace.as_dict()
    payload["meta"] = dict(ontology.meta)
    return payload


def ontology_from_dict(data: dict[str, Any]) -> OntologyDefinition:
    payload = dict(data)
    payload["namespace"] = _ns_dict_to_object(payload.get("namespace"))
    payload["categories"] = [
        c if isinstance(c, CategorySchema) else CategorySchema(**dict(c))
        for c in payload.get("categories", [])
    ]
    payload["entity_types"] = [
        e
        if isinstance(e, EntityTypeSchema)
        else EntityTypeSchema(
            name=e["name"],
            description=e.get("description", ""),
            properties=[
                p if isinstance(p, PropertySchema) else PropertySchema(**dict(p))
                for p in e.get("properties", [])
            ],
        )
        for e in payload.get("entity_types", [])
    ]
    payload["edge_types"] = [
        e
        if isinstance(e, EdgeTypeSchema)
        else EdgeTypeSchema(
            name=e["name"],
            source_entity_types=list(e.get("source_entity_types", [])),
            target_entity_types=list(e.get("target_entity_types", [])),
            description=e.get("description", ""),
            properties=[
                p if isinstance(p, PropertySchema) else PropertySchema(**dict(p))
                for p in e.get("properties", [])
            ],
        )
        for e in payload.get("edge_types", [])
    ]
    return OntologyDefinition(**payload)


def lifecycle_policy_to_dict(policy: Any) -> dict[str, Any]:
    """SLCE-02 — serialize a ``LifecyclePolicy`` to a portable dict."""

    from sophiagraph.storage.lifecycle_policy import (
        LifecyclePolicy,
        PromotionPredicate,
    )

    if not isinstance(policy, LifecyclePolicy):
        raise TypeError("lifecycle_policy_to_dict requires a LifecyclePolicy")
    return {
        "policy_id": policy.policy_id,
        "namespace_filter": policy.namespace_filter.as_dict(),
        "created_at_iso": policy.created_at_iso,
        "ttl_active_iso": policy.ttl_active_iso,
        "ttl_cooling_iso": policy.ttl_cooling_iso,
        "promotion_predicates": [
            {
                "kind": p.kind.value,
                "threshold": p.threshold,
                "window_iso": p.window_iso,
                "namespace_dimension": p.namespace_dimension,
                "namespace_dimension_value": p.namespace_dimension_value,
            }
            for p in policy.promotion_predicates
            if isinstance(p, PromotionPredicate)
        ],
    }


def lifecycle_policy_from_dict(data: dict[str, Any]) -> Any:
    """SLCE-02 — hydrate a ``LifecyclePolicy`` from a portable dict."""

    from sophiagraph.storage.lifecycle_policy import (
        LifecyclePolicy,
        PromotionPredicate,
        PromotionPredicateKind,
    )

    predicates = tuple(
        PromotionPredicate(
            kind=PromotionPredicateKind(p["kind"]),
            threshold=p.get("threshold"),
            window_iso=p.get("window_iso"),
            namespace_dimension=p.get("namespace_dimension"),
            namespace_dimension_value=p.get("namespace_dimension_value"),
        )
        for p in data.get("promotion_predicates", [])
    )
    return LifecyclePolicy(
        policy_id=data["policy_id"],
        namespace_filter=_ns_dict_to_object(data.get("namespace_filter")),
        created_at_iso=data["created_at_iso"],
        ttl_active_iso=data.get("ttl_active_iso"),
        ttl_cooling_iso=data.get("ttl_cooling_iso"),
        promotion_predicates=predicates,
    )


def raw_episode_to_dict(episode: RawEpisode) -> dict[str, Any]:
    payload = asdict(episode)
    if isinstance(episode.namespace, MemoryNamespace):
        payload["namespace"] = episode.namespace.as_dict()
    payload["payload"] = dict(episode.payload)
    payload["meta"] = dict(episode.meta)
    return payload


def raw_episode_from_dict(data: dict[str, Any]) -> RawEpisode:
    payload = dict(data)
    payload["namespace"] = _ns_dict_to_object(payload.get("namespace"))
    payload["provenance"] = _provenance_dict_to_object(payload.get("provenance"))
    return RawEpisode(**payload)


def fact_convergence_link_to_dict(link: FactConvergenceLink) -> dict[str, Any]:
    payload = asdict(link)
    if isinstance(link.namespace, MemoryNamespace):
        payload["namespace"] = link.namespace.as_dict()
    payload["meta"] = dict(link.meta)
    return payload


def fact_convergence_link_from_dict(data: dict[str, Any]) -> FactConvergenceLink:
    payload = dict(data)
    payload["namespace"] = _ns_dict_to_object(payload.get("namespace"))
    return FactConvergenceLink(**payload)


def memory_block_to_dict(block: MemoryBlock) -> dict[str, Any]:
    """Serialize a ``MemoryBlock`` to a portable dict."""
    payload = asdict(block)
    namespace = payload.get("owner_namespace")
    if isinstance(namespace, MemoryNamespace):
        payload["owner_namespace"] = namespace.as_dict()
    if isinstance(block.provenance, dict):
        payload["provenance"] = dict(block.provenance)
    else:
        payload["provenance"] = dict(block.provenance)
    return payload


def memory_block_from_dict(data: dict[str, Any]) -> MemoryBlock:
    """Hydrate a ``MemoryBlock`` from a portable dict."""
    payload = dict(data)
    raw_namespace = payload.get("owner_namespace")
    if isinstance(raw_namespace, dict):
        payload["owner_namespace"] = MemoryNamespace.from_dict(raw_namespace)
    return MemoryBlock(**payload)


def graph_node_from_record(
    record: MemoryRecord,
    *,
    degree_in: int = 0,
    degree_out: int = 0,
) -> GraphNode:
    document = record.meta.get("document")
    properties = record.meta.get("properties")
    document_meta = document if isinstance(document, dict) else {}
    property_meta = properties if isinstance(properties, dict) else {}
    return GraphNode(
        record_id=record.id,
        title=record.title,
        path=document_meta.get("path"),
        tags=list(record.tags),
        properties=dict(property_meta),
        degree_in=degree_in,
        degree_out=degree_out,
        orphan=(degree_in + degree_out) == 0,
        namespace=record.effective_namespace,
        provenance={"scope": record.scope},
    )


def graph_edge_from_link(link: StructuralLink, *, direction: str = "out") -> GraphEdge:
    return GraphEdge(
        edge_id=link.link_id,
        source_record_id=link.source_record_id,
        target_record_id=link.target_record_id,
        relation_type=link.relation_type,
        direction=direction,
        unresolved_target=None if link.target_record_id else link.raw_target,
        label=link.display_text,
        provenance={
            "link_kind": link.link_kind,
            "resolution_status": link.resolution_status,
            "source_path": link.source_path,
        },
    )


def record_matches_structural_query(
    record: MemoryRecord,
    query: StructuralSearchQuery,
    *,
    outgoing_targets: list[str] | None = None,
    incoming_sources: list[str] | None = None,
    blocks: list[KnowledgeDocumentBlock] | None = None,
) -> bool:
    if query.namespaces and not namespace_matches_filters(
        record.effective_namespace, query.namespaces
    ):
        return False
    document = record.meta.get("document")
    properties = record.meta.get("properties")
    document_meta = document if isinstance(document, dict) else {}
    property_meta = properties if isinstance(properties, dict) else {}
    haystack = " ".join(
        str(part)
        for part in [
            record.title,
            record.key,
            record.content,
            document_meta.get("path"),
            property_meta,
        ]
    ).lower()
    for phrase in query.exact_phrases:
        if phrase.lower() not in haystack:
            return False
    for term in query.text_terms:
        if term.lower() not in haystack:
            return False
    record_tags = {tag.lower().lstrip("#") for tag in record.tags}
    property_tags = property_meta.get("tags")
    if isinstance(property_tags, list):
        record_tags.update(str(tag).lower().lstrip("#") for tag in property_tags)
    for tag in query.tags:
        if tag.lower().lstrip("#") not in record_tags:
            return False
    for key, value in query.properties.items():
        if str(property_meta.get(key)) != value:
            return False
    path = str(document_meta.get("path") or "")
    if query.path and query.path.lower() not in path.lower():
        return False
    if query.file and query.file.lower() != path.rsplit("/", 1)[-1].lower():
        return False
    if query.content and query.content.lower() not in str(record.content).lower():
        return False
    if query.link_to and query.link_to not in set(outgoing_targets or []):
        return False
    if query.linked_from and query.linked_from not in set(incoming_sources or []):
        return False
    if query.block and query.block not in {block.block_id for block in blocks or []}:
        return False
    if query.section and query.section not in {block.anchor for block in blocks or []}:
        return False
    if query.task:
        task = query.task.lower()
        if not any(
            block.excerpt and task in block.excerpt.lower() for block in blocks or []
        ):
            return False
    return True


__all__ = [
    "contradiction_from_dict",
    "contradiction_to_dict",
    "decision_from_dict",
    "decision_to_dict",
    "entity_alias_from_dict",
    "entity_alias_to_dict",
    "entity_from_dict",
    "entity_summary_from_dict",
    "entity_summary_to_dict",
    "entity_to_dict",
    "episode_from_dict",
    "episode_step_from_dict",
    "episode_step_to_dict",
    "episode_to_dict",
    "fact_convergence_link_from_dict",
    "fact_convergence_link_to_dict",
    "fact_from_dict",
    "fact_to_dict",
    "raw_episode_from_dict",
    "raw_episode_to_dict",
    "graph_edge_from_link",
    "graph_node_from_record",
    "block_from_dict",
    "block_to_dict",
    "link_from_dict",
    "link_to_dict",
    "memory_block_from_dict",
    "memory_block_to_dict",
    "namespace_matches_filters",
    "lifecycle_policy_from_dict",
    "lifecycle_policy_to_dict",
    "ontology_from_dict",
    "ontology_to_dict",
    "outcome_from_dict",
    "outcome_to_dict",
    "procedure_from_dict",
    "procedure_to_dict",
    "record_matches_structural_query",
]
