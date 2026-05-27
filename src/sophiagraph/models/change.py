"""Changefeed DTOs for structural Sophiagraph mutations."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.models.namespace import MemoryNamespace

ChangeObjectType = Literal[
    "record",
    "relation",
    "link",
    "candidate",
    "tier_transition",
    "block",
    "memory_block",
    "view",
    "canvas",
    "schema",
]
ChangeOperation = Literal["put", "delete", "import"]


def default_change_namespace() -> MemoryNamespace:
    return MemoryNamespace(graph_id="unscoped")


@dataclass(frozen=True, slots=True)
class SophiaGraphChangeEvent:
    event_id: str
    object_type: ChangeObjectType
    object_id: str
    operation: ChangeOperation
    changed_at: str
    payload: dict[str, Any]
    namespace: MemoryNamespace = field(default_factory=default_change_namespace)
    cursor: int | None = None
    idempotency_key: str | None = None
    source_operation_id: str | None = None
    schema_identifiers: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.event_id:
            raise InvalidArgumentError("event_id is required")
        if not self.object_id:
            raise InvalidArgumentError("object_id is required")
        if self.object_type not in {
            "record",
            "relation",
            "link",
            "candidate",
            "tier_transition",
            "block",
            "memory_block",
            "view",
            "canvas",
            "schema",
        }:
            raise InvalidArgumentError(f"invalid object_type: {self.object_type!r}")
        if self.operation not in {"put", "delete", "import"}:
            raise InvalidArgumentError(f"invalid operation: {self.operation!r}")
        if not self.changed_at:
            raise InvalidArgumentError("changed_at is required")
        if self.cursor is not None and self.cursor < 0:
            raise InvalidArgumentError("cursor must be non-negative")
        if not isinstance(self.namespace, MemoryNamespace):
            raise TypeError(
                "namespace must be MemoryNamespace"
            )  # allow-bare-raise: defensive dataclass guard


__all__ = [
    "ChangeObjectType",
    "ChangeOperation",
    "SophiaGraphChangeEvent",
    "default_change_namespace",
]
