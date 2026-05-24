"""Property-graph schema discovery helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sophiagraph.models import (
    KnowledgeDocumentBlock,
    MemoryRecord,
    MemoryRelation,
    StructuralLink,
)


@dataclass(frozen=True, slots=True)
class GraphSchema:
    node_labels: list[str]
    relation_types: list[str]
    property_keys: dict[str, list[str]] = field(default_factory=dict)
    namespace_dimensions: list[str] = field(default_factory=list)
    edge_constraints: list[dict[str, str]] = field(default_factory=list)
    conflicts: list[dict[str, Any]] = field(default_factory=list)


def _type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "dict"
    return "str"


def describe_schema(
    *,
    records: list[MemoryRecord],
    relations: list[MemoryRelation] | None = None,
    links: list[StructuralLink] | None = None,
    blocks: list[KnowledgeDocumentBlock] | None = None,
) -> GraphSchema:
    property_types: dict[str, set[str]] = {}
    namespace_dimensions: set[str] = set()
    node_labels = {str(record.type) for record in records}
    if blocks:
        node_labels.add("block")
    for record in records:
        namespace_dimensions.update(record.effective_namespace.as_dict())
        properties = record.meta.get("properties")
        if isinstance(properties, dict):
            for key, value in properties.items():
                property_types.setdefault(str(key), set()).add(_type_name(value))
    relation_types = {str(relation.relation_type) for relation in relations or []}
    relation_types.update(
        str(link.relation_type) for link in links or [] if link.relation_type
    )
    conflicts = [
        {"property_key": key, "types": sorted(types)}
        for key, types in sorted(property_types.items())
        if len(types) > 1
    ]
    constraints = [
        {"relation_type": relation_type, "source": "*", "target": "*"}
        for relation_type in sorted(relation_types)
    ]
    return GraphSchema(
        node_labels=sorted(node_labels),
        relation_types=sorted(relation_types),
        property_keys={
            key: sorted(types) for key, types in sorted(property_types.items())
        },
        namespace_dimensions=sorted(namespace_dimensions),
        edge_constraints=constraints,
        conflicts=conflicts,
    )


__all__ = ["GraphSchema", "describe_schema"]
