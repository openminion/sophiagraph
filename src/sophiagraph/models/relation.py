"""Memory graph relation DTOs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, get_args

from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.models.primitives import MemoryRelationType, _assert_literal

MEMORY_RELATION_TYPES = frozenset(get_args(MemoryRelationType))


def _require_meta_dict(meta: dict[str, Any] | Any) -> None:
    if not isinstance(meta, dict):
        raise TypeError(
            "meta must be a dict"
        )  # allow-bare-raise: defensive type guard in dataclass __post_init__


@dataclass(frozen=True)
class MemoryRelation:
    relation_id: str
    source_record_id: str
    target_record_id: str
    relation_type: MemoryRelationType
    created_at: str
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.relation_id:
            raise InvalidArgumentError("relation_id is required")
        if not self.source_record_id:
            raise InvalidArgumentError("source_record_id is required")
        if not self.target_record_id:
            raise InvalidArgumentError("target_record_id is required")
        if self.source_record_id == self.target_record_id:
            raise InvalidArgumentError("relation endpoints must differ")
        _assert_literal(
            self.relation_type,
            MEMORY_RELATION_TYPES,
            "relation_type",
        )
        if not self.created_at:
            raise InvalidArgumentError("created_at is required")
        _require_meta_dict(self.meta)


__all__ = ["MEMORY_RELATION_TYPES", "MemoryRelation"]
