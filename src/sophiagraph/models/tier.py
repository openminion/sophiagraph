"""Memory tier transition DTOs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, get_args

from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.models.primitives import (
    MemoryTier,
    MemoryTierTransitionReason,
    MemoryType,
    Scope,
    _assert_literal,
    _assert_scope,
)


@dataclass(frozen=True)
class MemoryTierTransition:
    transition_id: str
    record_id: str
    scope: Scope
    record_type: MemoryType
    from_tier: MemoryTier
    to_tier: MemoryTier
    transition_reason: MemoryTierTransitionReason
    transition_at: str
    access_count: int = 0
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.transition_id:
            raise InvalidArgumentError("transition_id is required")
        if not self.record_id:
            raise InvalidArgumentError("record_id is required")
        _assert_scope(self.scope)
        _assert_literal(self.record_type, get_args(MemoryType), "record_type")
        _assert_literal(self.from_tier, get_args(MemoryTier), "from_tier")
        _assert_literal(self.to_tier, get_args(MemoryTier), "to_tier")
        _assert_literal(
            self.transition_reason,
            get_args(MemoryTierTransitionReason),
            "transition_reason",
        )
        if self.from_tier == self.to_tier:
            raise InvalidArgumentError("from_tier and to_tier must differ")
        if int(self.access_count) < 0:
            raise InvalidArgumentError("access_count must be non-negative")
        if not isinstance(self.meta, dict):
            raise TypeError(
                "meta must be a dict"
            )  # allow-bare-raise: defensive type guard in dataclass __post_init__


__all__ = ["MemoryTierTransition"]
