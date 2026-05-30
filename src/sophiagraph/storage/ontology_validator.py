"""Ontology validation helpers for records, entities, facts, and relations."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

from sophiagraph.contracts.errors import (
    OntologyNotFoundError,
    OntologyValidationError,
)
from sophiagraph.models import (
    Entity,
    Fact,
    MemoryRecord,
    MemoryRelation,
    OntologyDefinition,
    PropertySchema,
)


def _python_type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, datetime):
        return "datetime"
    if isinstance(value, str):
        # Accept ISO timestamps as the datetime value type for callers
        # that store dates as ISO strings.
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
            return "datetime_or_str"
        except (TypeError, ValueError):
            return "str"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "dict"
    return "unknown"


def _value_matches(prop: PropertySchema, value: Any) -> bool:
    observed = _python_type_name(value)
    if prop.value_type == "datetime":
        return observed in {"datetime", "datetime_or_str"}
    if observed == "datetime_or_str":
        observed = "str"
    return observed == prop.value_type


def _validate_properties(
    properties: Mapping[str, Any] | None,
    *,
    schema_properties: list[PropertySchema],
    where: str,
) -> None:
    seen_keys: set[str] = set()
    if properties is None:
        properties = {}
    if not isinstance(properties, Mapping):
        raise OntologyValidationError(
            f"{where}: properties must be a Mapping[str, Any]",
            details={"where": where, "got_type": type(properties).__name__},
        )
    for key, value in properties.items():
        prop = next((p for p in schema_properties if p.name == key), None)
        if prop is None:
            # Unknown properties are tolerated when no schema entry exists,
            # but a property that is declared must match the typed value.
            continue
        seen_keys.add(key)
        if not _value_matches(prop, value):
            raise OntologyValidationError(
                f"{where}: property {key!r} expected type {prop.value_type!r}, "
                f"got {_python_type_name(value)!r}",
                details={
                    "where": where,
                    "property": key,
                    "expected_type": prop.value_type,
                    "observed_type": _python_type_name(value),
                },
            )
    for prop in schema_properties:
        if prop.required and prop.name not in seen_keys:
            raise OntologyValidationError(
                f"{where}: required property {prop.name!r} is missing",
                details={
                    "where": where,
                    "missing_property": prop.name,
                    "expected_type": prop.value_type,
                },
            )


def validate_record_against_ontology(
    record: MemoryRecord,
    ontology: OntologyDefinition,
) -> None:
    """Validate that a ``MemoryRecord`` belongs to an ontology category."""

    declared_category = (
        record.meta.get("ontology_category") if isinstance(record.meta, dict) else None
    )
    category = str(declared_category or record.type)
    if not ontology.has_category(category) and not ontology.has_entity_type(category):
        raise OntologyValidationError(
            (
                f"record {record.id!r}: category {category!r} is not declared in "
                f"ontology {ontology.ontology_id!r}@{ontology.version!r}"
            ),
            details={
                "record_id": record.id,
                "category": category,
                "ontology_id": ontology.ontology_id,
                "ontology_version": ontology.version,
            },
        )
    entity_type = ontology.get_entity_type(category)
    if entity_type is not None:
        property_map = (
            record.meta.get("properties") if isinstance(record.meta, dict) else None
        )
        _validate_properties(
            property_map,
            schema_properties=list(entity_type.properties),
            where=f"record {record.id!r}",
        )


def validate_entity_against_ontology(
    entity: Entity,
    ontology: OntologyDefinition,
) -> None:
    """Validate an ``Entity`` against the ontology entity types."""

    if not ontology.has_entity_type(entity.entity_type):
        raise OntologyValidationError(
            (
                f"entity {entity.entity_id!r}: entity_type {entity.entity_type!r} is "
                f"not declared in ontology {ontology.ontology_id!r}@{ontology.version!r}"
            ),
            details={
                "entity_id": entity.entity_id,
                "entity_type": entity.entity_type,
                "ontology_id": ontology.ontology_id,
                "ontology_version": ontology.version,
            },
        )
    schema = ontology.get_entity_type(entity.entity_type)
    if schema is not None and schema.properties:
        property_map = entity.meta if isinstance(entity.meta, dict) else {}
        _validate_properties(
            property_map,
            schema_properties=list(schema.properties),
            where=f"entity {entity.entity_id!r}",
        )


def validate_fact_against_ontology(
    fact: Fact,
    ontology: OntologyDefinition,
) -> None:
    """Validate a ``Fact``'s predicate against the ontology edge types."""

    schema = ontology.get_edge_type(fact.predicate)
    if schema is None:
        raise OntologyValidationError(
            (
                f"fact {fact.fact_id!r}: predicate {fact.predicate!r} is not declared "
                f"in ontology {ontology.ontology_id!r}@{ontology.version!r}"
            ),
            details={
                "fact_id": fact.fact_id,
                "predicate": fact.predicate,
                "ontology_id": ontology.ontology_id,
                "ontology_version": ontology.version,
            },
        )
    # Fact-level property validation reuses the edge type's property list.
    property_map = fact.meta if isinstance(fact.meta, dict) else {}
    if schema.properties:
        _validate_properties(
            property_map,
            schema_properties=list(schema.properties),
            where=f"fact {fact.fact_id!r}",
        )


def validate_relation_against_ontology(
    relation: MemoryRelation,
    ontology: OntologyDefinition,
) -> None:
    """Validate a ``MemoryRelation`` against the ontology edge types."""

    schema = ontology.get_edge_type(str(relation.relation_type))
    if schema is None:
        raise OntologyValidationError(
            (
                f"relation {relation.relation_id!r}: relation_type "
                f"{relation.relation_type!r} is not declared in "
                f"ontology {ontology.ontology_id!r}@{ontology.version!r}"
            ),
            details={
                "relation_id": relation.relation_id,
                "relation_type": str(relation.relation_type),
                "ontology_id": ontology.ontology_id,
                "ontology_version": ontology.version,
            },
        )
    property_map = relation.meta if isinstance(relation.meta, dict) else {}
    if schema.properties:
        _validate_properties(
            property_map,
            schema_properties=list(schema.properties),
            where=f"relation {relation.relation_id!r}",
        )


# Cross-cutting "validate object against a stored ontology" surface.


def _resolve_ontology(
    store: Any,
    *,
    ontology_id: str,
    version: str,
) -> OntologyDefinition:
    ontology = store.get_ontology(ontology_id=ontology_id, version=version)
    if ontology is None:
        raise OntologyNotFoundError(
            f"ontology {ontology_id!r}@{version!r} is not registered",
            details={"ontology_id": ontology_id, "version": version},
        )
    return ontology


def validate_record_for_ontology(
    store: Any,
    record: MemoryRecord,
    *,
    ontology_id: str,
    version: str,
) -> None:
    """Look up the ontology then validate a record against it."""
    ontology = _resolve_ontology(store, ontology_id=ontology_id, version=version)
    validate_record_against_ontology(record, ontology)


def validate_entity_for_ontology(
    store: Any,
    entity: Entity,
    *,
    ontology_id: str,
    version: str,
) -> None:
    ontology = _resolve_ontology(store, ontology_id=ontology_id, version=version)
    validate_entity_against_ontology(entity, ontology)


def validate_fact_for_ontology(
    store: Any,
    fact: Fact,
    *,
    ontology_id: str,
    version: str,
) -> None:
    ontology = _resolve_ontology(store, ontology_id=ontology_id, version=version)
    validate_fact_against_ontology(fact, ontology)


def validate_relation_for_ontology(
    store: Any,
    relation: MemoryRelation,
    *,
    ontology_id: str,
    version: str,
) -> None:
    ontology = _resolve_ontology(store, ontology_id=ontology_id, version=version)
    validate_relation_against_ontology(relation, ontology)


__all__ = [
    "validate_entity_against_ontology",
    "validate_entity_for_ontology",
    "validate_fact_against_ontology",
    "validate_fact_for_ontology",
    "validate_record_against_ontology",
    "validate_record_for_ontology",
    "validate_relation_against_ontology",
    "validate_relation_for_ontology",
]
