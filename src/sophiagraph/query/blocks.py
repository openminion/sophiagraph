"""Budget-aware memory-block rendering and disagreement recordkeeping."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from sophiagraph.audit import (
    MemoryAuditEvent,
    MemoryAuditRecorder,
    memory_block_audit_event,
    noop_audit_recorder,
)
from sophiagraph.contracts.errors import (
    MEMORY_BLOCK_DISAGREEMENT_RECORDED,
    MEMORY_BLOCK_STALE_SURFACED,
    MEMORY_BLOCKS_BUDGET_CEILING_DEFAULT_TOKENS,
    MEMORY_BLOCKS_BUDGET_EXCEEDED,
    MEMORY_IDENTITY_BLOCK_HARD_FLOOR_TOKENS,
    InvalidArgumentError,
    MemoryBlocksBudgetHardFloorViolatedError,
)
from sophiagraph.models import MemoryBlock


# Render in this order; truncate in reverse.
BLOCK_PRIORITY_ORDER: tuple[str, ...] = (
    "agent_identity",
    "active_mission",
    "session_pin",
)
TRUNCATE_ORDER: tuple[str, ...] = tuple(reversed(BLOCK_PRIORITY_ORDER))

STALE_MARKER: str = "[stale] "
STALE_MARKER_TOKEN_COST: int = max(1, len(STALE_MARKER.split()))


@dataclass(frozen=True)
class RenderedBlock:
    """One block as it appears in the assembled context package."""

    block_id: str
    class_name: str
    mode: str
    content: str
    token_cost: int
    is_stale: bool = False
    truncated: bool = False
    original_token_estimate: int = 0


@dataclass(frozen=True)
class MemoryBlockContextPackage:
    """Deterministic output of ``assemble_block_context``."""

    rendered: list[RenderedBlock]
    total_tokens: int
    ceiling_tokens: int
    identity_floor_tokens: int
    budget_exceeded: bool = False
    truncated_block_ids: list[str] = field(default_factory=list)
    dropped_block_ids: list[str] = field(default_factory=list)
    stale_block_ids: list[str] = field(default_factory=list)


def _is_stale(block: MemoryBlock, now_iso: str | None) -> bool:
    if not block.stale_after:
        return False
    if now_iso is None:
        return False
    return block.stale_after <= now_iso


def _sorted_for_render(blocks: list[MemoryBlock]) -> list[MemoryBlock]:
    def key(block: MemoryBlock) -> tuple[int, str, str, str]:
        try:
            class_rank = BLOCK_PRIORITY_ORDER.index(block.class_name)
        except ValueError:
            class_rank = len(BLOCK_PRIORITY_ORDER)
        return (class_rank, block.class_name, block.created_at, block.block_id)

    return sorted(blocks, key=key)


def assemble_block_context(
    blocks: list[MemoryBlock],
    *,
    ceiling_tokens: int = MEMORY_BLOCKS_BUDGET_CEILING_DEFAULT_TOKENS,
    identity_floor_tokens: int = MEMORY_IDENTITY_BLOCK_HARD_FLOOR_TOKENS,
    now_iso: str | None = None,
    session_id: str | None = None,
    audit_recorder: MemoryAuditRecorder | None = None,
    already_marked_stale: set[str] | None = None,
) -> MemoryBlockContextPackage:
    """Render blocks into a deterministic, budget-aware context package."""

    if ceiling_tokens <= 0:
        raise InvalidArgumentError("ceiling_tokens must be positive")
    if identity_floor_tokens < 0:
        raise InvalidArgumentError("identity_floor_tokens must be non-negative")
    # Fail before rendering when the identity floor cannot fit.
    if identity_floor_tokens > ceiling_tokens:
        raise MemoryBlocksBudgetHardFloorViolatedError(
            (
                f"identity block hard floor {identity_floor_tokens} exceeds "
                f"ceiling {ceiling_tokens}; no block package can fit"
            ),
            details={
                "ceiling_tokens": ceiling_tokens,
                "identity_floor_tokens": identity_floor_tokens,
                "post_truncation_total": None,
            },
        )

    recorder = audit_recorder or noop_audit_recorder
    stale_marker_record = (
        already_marked_stale if already_marked_stale is not None else set()
    )

    ordered = _sorted_for_render(blocks)
    rendered: list[RenderedBlock] = []
    stale_ids: list[str] = []

    for block in ordered:
        is_stale = _is_stale(block, now_iso)
        if is_stale:
            stale_ids.append(block.block_id)
            content = STALE_MARKER + block.content
            token_cost = int(block.token_estimate) + STALE_MARKER_TOKEN_COST
        else:
            content = block.content
            token_cost = int(block.token_estimate)
        rendered.append(
            RenderedBlock(
                block_id=block.block_id,
                class_name=block.class_name,
                mode=block.mode,
                content=content,
                token_cost=token_cost,
                is_stale=is_stale,
                truncated=False,
                original_token_estimate=int(block.token_estimate),
            )
        )

    total = sum(block.token_cost for block in rendered)
    truncated_ids: list[str] = []
    dropped_ids: list[str] = []

    if total > ceiling_tokens:
        # Truncate in reverse-priority order, preserving identity floor.
        rendered, truncated_ids, dropped_ids = _truncate_in_reverse_priority(
            rendered,
            ceiling_tokens=ceiling_tokens,
            identity_floor_tokens=identity_floor_tokens,
        )
        total = sum(block.token_cost for block in rendered)
        # Post-truncation overflow means the identity floor cannot fit.
        if total > ceiling_tokens:
            raise MemoryBlocksBudgetHardFloorViolatedError(
                (
                    f"identity block hard floor {identity_floor_tokens} cannot fit "
                    f"under ceiling {ceiling_tokens} (post-truncation total = {total})"
                ),
                details={
                    "ceiling_tokens": ceiling_tokens,
                    "identity_floor_tokens": identity_floor_tokens,
                    "post_truncation_total": total,
                },
            )
        recorder(
            memory_block_audit_event(
                event_type=MEMORY_BLOCKS_BUDGET_EXCEEDED,
                block_id="(package)",
                session_id=session_id,
                details={
                    "ceiling_tokens": ceiling_tokens,
                    "identity_floor_tokens": identity_floor_tokens,
                    "truncated_block_ids": list(truncated_ids),
                    "dropped_block_ids": list(dropped_ids),
                    "post_truncation_total": total,
                },
            )
        )

    # Stale events are caller-scoped by the ``already_marked_stale`` set.
    for block in rendered:
        if block.is_stale and block.block_id not in stale_marker_record:
            recorder(
                memory_block_audit_event(
                    event_type=MEMORY_BLOCK_STALE_SURFACED,
                    block_id=block.block_id,
                    class_name=block.class_name,
                    mode=block.mode,
                    session_id=session_id,
                    details={
                        "token_cost": block.token_cost,
                        "rendered_with_marker": True,
                    },
                )
            )
            stale_marker_record.add(block.block_id)

    return MemoryBlockContextPackage(
        rendered=rendered,
        total_tokens=total,
        ceiling_tokens=ceiling_tokens,
        identity_floor_tokens=identity_floor_tokens,
        budget_exceeded=bool(truncated_ids or dropped_ids),
        truncated_block_ids=truncated_ids,
        dropped_block_ids=dropped_ids,
        stale_block_ids=stale_ids,
    )


def _truncate_in_reverse_priority(
    rendered: list[RenderedBlock],
    *,
    ceiling_tokens: int,
    identity_floor_tokens: int,
) -> tuple[list[RenderedBlock], list[str], list[str]]:
    truncated_ids: list[str] = []
    dropped_ids: list[str] = []
    by_class: dict[str, list[RenderedBlock]] = {
        name: [] for name in BLOCK_PRIORITY_ORDER
    }
    extras: list[RenderedBlock] = []
    for block in rendered:
        if block.class_name in by_class:
            by_class[block.class_name].append(block)
        else:
            extras.append(block)

    def total() -> int:
        return sum(
            block.token_cost
            for class_blocks in by_class.values()
            for block in class_blocks
        ) + sum(block.token_cost for block in extras)

    for class_name in TRUNCATE_ORDER:
        if total() <= ceiling_tokens:
            break
        class_blocks = by_class[class_name]
        if class_name == "agent_identity":
            i = 0
            while total() > ceiling_tokens and i < len(class_blocks):
                block = class_blocks[i]
                excess = total() - ceiling_tokens
                new_cost = max(identity_floor_tokens, block.token_cost - excess)
                if new_cost != block.token_cost:
                    class_blocks[i] = _truncate_block(block, new_cost)
                    if block.block_id not in truncated_ids:
                        truncated_ids.append(block.block_id)
                i += 1
        else:
            while class_blocks and total() > ceiling_tokens:
                excess = total() - ceiling_tokens
                last = class_blocks[-1]
                if excess >= last.token_cost:
                    dropped_ids.append(last.block_id)
                    class_blocks.pop()
                else:
                    new_cost = last.token_cost - excess
                    class_blocks[-1] = _truncate_block(last, new_cost)
                    if last.block_id not in truncated_ids:
                        truncated_ids.append(last.block_id)
                    break

    out: list[RenderedBlock] = []
    for class_name in BLOCK_PRIORITY_ORDER:
        out.extend(by_class[class_name])
    out.extend(extras)
    return out, truncated_ids, dropped_ids


def _truncate_block(block: RenderedBlock, new_token_cost: int) -> RenderedBlock:
    """Shrink content structurally to match the reduced token budget."""
    if new_token_cost >= block.token_cost:
        return block
    ratio = new_token_cost / max(1, block.token_cost)
    new_length = max(1, int(len(block.content) * ratio))
    new_content = block.content[:new_length].rstrip() + "..."
    return RenderedBlock(
        block_id=block.block_id,
        class_name=block.class_name,
        mode=block.mode,
        content=new_content,
        token_cost=new_token_cost,
        is_stale=block.is_stale,
        truncated=True,
        original_token_estimate=block.original_token_estimate,
    )


DisagreementKind = Literal[
    "claim_key_polarity",
    "explicit_upstream_metadata",
    "exact_key_contradiction_fact",
]


@dataclass(frozen=True)
class DisagreementSignal:
    """Caller-supplied structural disagreement signal."""

    kind: DisagreementKind
    block_id: str
    retrieval_record_id: str
    claim_key: str | None = None
    block_polarity: str | None = None
    retrieval_polarity: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DisagreementOutcome:
    """Result of recording one disagreement signal."""

    signal: DisagreementSignal
    audit_event: MemoryAuditEvent
    block_preferred: bool = True


def record_disagreement(
    signal: DisagreementSignal,
    *,
    session_id: str | None = None,
    audit_recorder: MemoryAuditRecorder | None = None,
) -> DisagreementOutcome:
    """Record a structural retrieval/block disagreement."""

    if signal.kind == "claim_key_polarity":
        if not signal.claim_key:
            raise InvalidArgumentError(
                "claim_key is required for kind='claim_key_polarity'"
            )
        if signal.block_polarity is None or signal.retrieval_polarity is None:
            raise InvalidArgumentError(
                "polarity values are required for kind='claim_key_polarity'"
            )
        if signal.block_polarity == signal.retrieval_polarity:
            raise InvalidArgumentError(
                "claim_key polarity disagreement requires distinct polarities"
            )

    recorder = audit_recorder or noop_audit_recorder
    event = memory_block_audit_event(
        event_type=MEMORY_BLOCK_DISAGREEMENT_RECORDED,
        block_id=signal.block_id,
        session_id=session_id,
        details={
            "kind": signal.kind,
            "retrieval_record_id": signal.retrieval_record_id,
            "claim_key": signal.claim_key,
            "block_polarity": signal.block_polarity,
            "retrieval_polarity": signal.retrieval_polarity,
            "extra": dict(signal.details),
            "block_preferred": True,
        },
    )
    recorder(event)
    return DisagreementOutcome(signal=signal, audit_event=event, block_preferred=True)


__all__ = [
    "BLOCK_PRIORITY_ORDER",
    "DisagreementKind",
    "DisagreementOutcome",
    "DisagreementSignal",
    "MemoryBlockContextPackage",
    "RenderedBlock",
    "STALE_MARKER",
    "TRUNCATE_ORDER",
    "assemble_block_context",
    "record_disagreement",
]
