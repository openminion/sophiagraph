"""Shared memory-block edit gates for storage layers."""

from __future__ import annotations

from sophiagraph.contracts.errors import (
    MEMORY_BLOCK_EDIT_DENIED,
    MemoryBlockEditDeniedError,
)
from sophiagraph.models import MemoryBlock


def enforce_block_edit_gate(
    block: MemoryBlock,
    *,
    operator_action: bool,
    actor: str,
    operation: str,
) -> None:
    """Reject memory-block mutations that are not explicitly operator-owned."""

    if block.mode == "read_only":
        raise MemoryBlockEditDeniedError(
            (
                f"memory block {block.block_id!r} is read_only; "
                f"runtime/operator mutations are denied in v1"
            ),
            details={
                "event_type": MEMORY_BLOCK_EDIT_DENIED,
                "block_id": block.block_id,
                "class_name": block.class_name,
                "mode": block.mode,
                "operation": operation,
                "actor": actor,
                "operator_action": operator_action,
                "reason": "read_only_block",
            },
        )
    if block.mode == "pinned" and not operator_action:
        raise MemoryBlockEditDeniedError(
            (
                f"memory block {block.block_id!r} is pinned; "
                f"mutation requires an explicit operator action"
            ),
            details={
                "event_type": MEMORY_BLOCK_EDIT_DENIED,
                "block_id": block.block_id,
                "class_name": block.class_name,
                "mode": block.mode,
                "operation": operation,
                "actor": actor,
                "operator_action": operator_action,
                "reason": "operator_action_required",
            },
        )


__all__ = ["enforce_block_edit_gate"]
