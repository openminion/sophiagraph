"""Memory-block DTOs and creation-time activation validation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Final, Literal, Mapping, get_args

from sophiagraph.contracts.errors import (
    InvalidArgumentError,
    MemoryBlockClassNotEligibleError,
    MemoryBlockModeInvalidError,
    MemoryBlockModeNotYetSupportedError,
)
from sophiagraph.models.namespace import MemoryNamespace

MemoryBlockMode = Literal["read_only", "pinned", "shared", "writable"]

# Only these modes may be created or activated as live blocks.
MEMORY_BLOCK_V1_MODES: Final[frozenset[str]] = frozenset({"read_only", "pinned"})

# Deferred-but-schema-valid modes round-trip through stored DTOs.
MEMORY_BLOCK_DEFERRED_MODES: Final[frozenset[str]] = frozenset({"shared", "writable"})


MemoryBlockClass = Literal["agent_identity", "active_mission", "session_pin"]

# Default-deny class allowlist for live block creation.
MEMORY_BLOCK_V1_CLASS_ALLOWLIST: Final[frozenset[str]] = frozenset(
    {"agent_identity", "active_mission", "session_pin"}
)


@dataclass(frozen=True)
class MemoryBlock:
    """Stored memory-block DTO that preserves all schema-valid modes."""

    block_id: str
    class_name: str
    mode: MemoryBlockMode
    content: str
    token_estimate: int
    owner_namespace: MemoryNamespace
    source: str
    provenance: Mapping[str, Any] = field(default_factory=dict)
    created_at: str = ""
    last_updated_at: str = ""
    last_updated_by: str = "system"
    stale_after: str | None = None

    def __post_init__(self) -> None:
        # Structural validation only; activation constraints live in
        # ``validate_block_for_creation`` so portable data can hydrate.
        if not self.block_id:
            raise InvalidArgumentError("block_id is required")
        if not isinstance(self.class_name, str) or not self.class_name:
            raise InvalidArgumentError("class_name is required")
        if not isinstance(self.mode, str) or not self.mode:
            raise InvalidArgumentError("mode is required")
        # Unknown modes are malformed data; deferred known modes remain valid.
        if self.mode not in get_args(MemoryBlockMode):
            raise MemoryBlockModeInvalidError(
                f"unknown memory-block mode: {self.mode!r}",
                details={"mode": self.mode},
            )
        if not isinstance(self.content, str):
            raise InvalidArgumentError("content must be a string")
        if not isinstance(self.token_estimate, int) or self.token_estimate < 0:
            raise InvalidArgumentError("token_estimate must be a non-negative integer")
        if not isinstance(self.owner_namespace, MemoryNamespace):
            raise InvalidArgumentError(
                "owner_namespace must be sophiagraph.models.namespace.MemoryNamespace"
            )
        if not isinstance(self.source, str) or not self.source:
            raise InvalidArgumentError("source is required")
        if not isinstance(self.provenance, Mapping):
            raise InvalidArgumentError("provenance must be a Mapping[str, Any]")
        if not isinstance(self.last_updated_by, str) or not self.last_updated_by:
            raise InvalidArgumentError("last_updated_by is required")
        if self.stale_after is not None and not isinstance(self.stale_after, str):
            raise InvalidArgumentError("stale_after must be an ISO string or None")


def validate_block_for_creation(block: MemoryBlock) -> None:
    """Enforce the live-block class and mode allowlists."""

    if block.class_name not in MEMORY_BLOCK_V1_CLASS_ALLOWLIST:
        raise MemoryBlockClassNotEligibleError(
            f"memory-block class {block.class_name!r} is not on the v1 allowlist; "
            f"eligible classes: {sorted(MEMORY_BLOCK_V1_CLASS_ALLOWLIST)}",
            details={
                "class_name": block.class_name,
                "eligible": sorted(MEMORY_BLOCK_V1_CLASS_ALLOWLIST),
            },
        )
    if block.mode in MEMORY_BLOCK_DEFERRED_MODES:
        raise MemoryBlockModeNotYetSupportedError(
            f"memory-block mode {block.mode!r} is schema-valid but deferred in v1; "
            f"active modes: {sorted(MEMORY_BLOCK_V1_MODES)}",
            details={
                "mode": block.mode,
                "active": sorted(MEMORY_BLOCK_V1_MODES),
                "deferred": sorted(MEMORY_BLOCK_DEFERRED_MODES),
            },
        )
    # Defense in depth for callers that bypass the DTO constructor.
    if block.mode not in MEMORY_BLOCK_V1_MODES:
        raise MemoryBlockModeInvalidError(
            f"memory-block mode {block.mode!r} is not a recognized literal",
            details={"mode": block.mode},
        )


__all__ = [
    "MEMORY_BLOCK_DEFERRED_MODES",
    "MEMORY_BLOCK_V1_CLASS_ALLOWLIST",
    "MEMORY_BLOCK_V1_MODES",
    "MemoryBlock",
    "MemoryBlockClass",
    "MemoryBlockMode",
    "validate_block_for_creation",
]
