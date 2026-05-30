"""Versioned ontology and category schema DTOs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Final, Literal, Mapping

from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.models.namespace import MemoryNamespace


OntologyCompatibility = Literal["fresh", "additive", "breaking"]


ONTOLOGY_COMPATIBILITIES: Final[frozenset[str]] = frozenset(
    {"fresh", "additive", "breaking"}
)


PropertyValueType = Literal[
    "str",
    "int",
    "float",
    "bool",
    "list",
    "dict",
    "datetime",
]


PROPERTY_VALUE_TYPES: Final[frozenset[str]] = frozenset(
    {"str", "int", "float", "bool", "list", "dict", "datetime"}
)


@dataclass(frozen=True)
class CategorySchema:
    """One named category inside an ontology."""

    name: str
    description: str = ""
    parent: str | None = None

    def __post_init__(self) -> None:
        if not self.name:
            raise InvalidArgumentError("CategorySchema.name is required")


@dataclass(frozen=True)
class PropertySchema:
    """One named property with a typed value."""

    name: str
    value_type: PropertyValueType
    required: bool = False
    description: str = ""

    def __post_init__(self) -> None:
        if not self.name:
            raise InvalidArgumentError("PropertySchema.name is required")
        if self.value_type not in PROPERTY_VALUE_TYPES:
            raise InvalidArgumentError(
                f"PropertySchema.value_type {self.value_type!r} not in "
                f"{sorted(PROPERTY_VALUE_TYPES)}"
            )


@dataclass(frozen=True)
class EntityTypeSchema:
    """One named entity type with optional property keys."""

    name: str
    description: str = ""
    properties: list[PropertySchema] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.name:
            raise InvalidArgumentError("EntityTypeSchema.name is required")
        seen: set[str] = set()
        for prop in self.properties:
            if prop.name in seen:
                raise InvalidArgumentError(
                    f"EntityTypeSchema.properties has duplicate name: {prop.name!r}"
                )
            seen.add(prop.name)


@dataclass(frozen=True)
class EdgeTypeSchema:
    """One named edge/relation type with allowed endpoint types."""

    name: str
    source_entity_types: list[str] = field(default_factory=list)
    target_entity_types: list[str] = field(default_factory=list)
    description: str = ""
    properties: list[PropertySchema] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.name:
            raise InvalidArgumentError("EdgeTypeSchema.name is required")
        seen: set[str] = set()
        for prop in self.properties:
            if prop.name in seen:
                raise InvalidArgumentError(
                    f"EdgeTypeSchema.properties has duplicate name: {prop.name!r}"
                )
            seen.add(prop.name)


@dataclass(frozen=True)
class OntologyDefinition:
    """One versioned domain ontology."""

    ontology_id: str
    version: str
    owner: str
    namespace: MemoryNamespace
    compatibility: OntologyCompatibility = "fresh"
    description: str = ""
    categories: list[CategorySchema] = field(default_factory=list)
    entity_types: list[EntityTypeSchema] = field(default_factory=list)
    edge_types: list[EdgeTypeSchema] = field(default_factory=list)
    created_at: str = ""
    meta: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.ontology_id:
            raise InvalidArgumentError("ontology_id is required")
        if not self.version:
            raise InvalidArgumentError("version is required")
        if not self.owner:
            raise InvalidArgumentError("owner is required")
        if not isinstance(self.namespace, MemoryNamespace):
            raise InvalidArgumentError("namespace must be MemoryNamespace")
        if self.compatibility not in ONTOLOGY_COMPATIBILITIES:
            raise InvalidArgumentError(
                f"compatibility {self.compatibility!r} not in "
                f"{sorted(ONTOLOGY_COMPATIBILITIES)}"
            )
        for collection, label, name_attr in (
            (self.categories, "categories", "name"),
            (self.entity_types, "entity_types", "name"),
            (self.edge_types, "edge_types", "name"),
        ):
            seen: set[str] = set()
            for entry in collection:
                key = getattr(entry, name_attr)
                if key in seen:
                    raise InvalidArgumentError(
                        f"OntologyDefinition.{label} has duplicate name: {key!r}"
                    )
                seen.add(key)
        if not isinstance(self.meta, Mapping):
            raise InvalidArgumentError("meta must be a Mapping[str, Any]")

    @property
    def schema_key(self) -> tuple[str, str]:
        return (self.ontology_id, self.version)

    def has_category(self, name: str) -> bool:
        return any(c.name == name for c in self.categories)

    def has_entity_type(self, name: str) -> bool:
        return any(e.name == name for e in self.entity_types)

    def has_edge_type(self, name: str) -> bool:
        return any(e.name == name for e in self.edge_types)

    def get_entity_type(self, name: str) -> EntityTypeSchema | None:
        return next((e for e in self.entity_types if e.name == name), None)

    def get_edge_type(self, name: str) -> EdgeTypeSchema | None:
        return next((e for e in self.edge_types if e.name == name), None)


__all__ = [
    "CategorySchema",
    "EdgeTypeSchema",
    "EntityTypeSchema",
    "ONTOLOGY_COMPATIBILITIES",
    "OntologyCompatibility",
    "OntologyDefinition",
    "PROPERTY_VALUE_TYPES",
    "PropertySchema",
    "PropertyValueType",
]
