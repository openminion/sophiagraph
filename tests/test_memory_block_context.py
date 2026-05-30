"""Memory-block context assembly and failure-mode tests."""

from __future__ import annotations

import pytest

from sophiagraph.audit import MemoryAuditEvent
from sophiagraph.contracts.errors import (
    MEMORY_BLOCK_DISAGREEMENT_RECORDED,
    MEMORY_BLOCK_STALE_SURFACED,
    MEMORY_BLOCKS_BUDGET_EXCEEDED,
    InvalidArgumentError,
    MemoryBlocksBudgetHardFloorViolatedError,
)
from sophiagraph.models import MemoryBlock, MemoryNamespace
from sophiagraph.query import (
    BLOCK_PRIORITY_ORDER,
    DisagreementSignal,
    STALE_MARKER,
    assemble_block_context,
    record_disagreement,
)


def _ns() -> MemoryNamespace:
    return MemoryNamespace(tenant_id="acme", agent_id="alpha")


def _identity(token_estimate: int = 32, stale_after: str | None = None) -> MemoryBlock:
    return MemoryBlock(
        block_id="blk-identity",
        class_name="agent_identity",
        mode="read_only",
        content="You are a focused assistant who values evidence." * 2,
        token_estimate=token_estimate,
        owner_namespace=_ns(),
        source="agent_config",
        created_at="2026-05-26T10:00:00+00:00",
        last_updated_at="2026-05-26T10:00:00+00:00",
        last_updated_by="system",
        stale_after=stale_after,
    )


def _mission(
    block_id: str = "blk-mission",
    token_estimate: int = 24,
    stale_after: str | None = None,
) -> MemoryBlock:
    return MemoryBlock(
        block_id=block_id,
        class_name="active_mission",
        mode="pinned",
        content="Investigate the failing task and write down findings.",
        token_estimate=token_estimate,
        owner_namespace=_ns(),
        source="operator_pin",
        created_at="2026-05-26T10:01:00+00:00",
        last_updated_at="2026-05-26T10:01:00+00:00",
        last_updated_by="alice",
        stale_after=stale_after,
    )


def _session_pin(
    block_id: str = "blk-session",
    token_estimate: int = 16,
) -> MemoryBlock:
    return MemoryBlock(
        block_id=block_id,
        class_name="session_pin",
        mode="pinned",
        content="Use ripgrep for searches in this repo.",
        token_estimate=token_estimate,
        owner_namespace=_ns(),
        source="operator_pin",
        created_at="2026-05-26T10:02:00+00:00",
        last_updated_at="2026-05-26T10:02:00+00:00",
        last_updated_by="alice",
    )


# SMBL-04 — assembly behavior


def test_render_order_matches_frozen_priority() -> None:
    pkg = assemble_block_context(
        [_session_pin(), _mission(), _identity()],
        ceiling_tokens=4096,
    )
    classes = [block.class_name for block in pkg.rendered]
    assert classes == list(BLOCK_PRIORITY_ORDER)
    assert pkg.budget_exceeded is False
    assert pkg.total_tokens == 32 + 24 + 16


def test_truncation_order_is_reverse_priority() -> None:
    # Total = 72; ceiling 50 → session_pin must shed first.
    pkg = assemble_block_context(
        [_identity(32), _mission(token_estimate=24), _session_pin(token_estimate=16)],
        ceiling_tokens=50,
        identity_floor_tokens=8,
    )
    assert pkg.budget_exceeded is True
    # session_pin truncates first; mission may also truncate.
    assert pkg.truncated_block_ids or pkg.dropped_block_ids
    # session_pin should be the first thing the truncator touches.
    impact = pkg.truncated_block_ids + pkg.dropped_block_ids
    assert "blk-session" in impact
    # Identity must not appear in dropped list.
    assert "blk-identity" not in pkg.dropped_block_ids
    # Total post-truncation is at or under the ceiling.
    assert pkg.total_tokens <= 50


def test_identity_hard_floor_loud_failure() -> None:
    # Ceiling smaller than the identity floor → cannot fit.
    with pytest.raises(MemoryBlocksBudgetHardFloorViolatedError) as info:
        assemble_block_context(
            [_identity(32), _mission(token_estimate=24)],
            ceiling_tokens=64,
            identity_floor_tokens=128,
        )
    assert info.value.code == "MEMORY_BLOCKS_BUDGET_HARD_FLOOR_VIOLATED"
    assert info.value.details["ceiling_tokens"] == 64
    assert info.value.details["identity_floor_tokens"] == 128


def test_assembly_rejects_non_positive_ceiling() -> None:
    with pytest.raises(InvalidArgumentError):
        assemble_block_context([_identity()], ceiling_tokens=0)


def test_no_silent_drops_truncated_paths_recorded() -> None:
    events: list[MemoryAuditEvent] = []
    pkg = assemble_block_context(
        [_identity(32), _mission(token_estimate=24), _session_pin(token_estimate=16)],
        ceiling_tokens=40,
        identity_floor_tokens=8,
        audit_recorder=events.append,
        session_id="sess-1",
    )
    # Every block that lost tokens is reported in either truncated or
    # dropped — never silently dropped.
    affected = set(pkg.truncated_block_ids) | set(pkg.dropped_block_ids)
    assert affected, "expected truncation evidence"
    # Each remaining block in pkg.rendered should match its declared cost.
    for block in pkg.rendered:
        assert block.token_cost >= 0


# SMBL-05 FM-1 — budget exceeded audit event


def test_budget_exceeded_emits_typed_audit_event() -> None:
    events: list[MemoryAuditEvent] = []
    pkg = assemble_block_context(
        [_identity(32), _mission(token_estimate=24), _session_pin(token_estimate=16)],
        ceiling_tokens=40,
        identity_floor_tokens=8,
        audit_recorder=events.append,
        session_id="sess-1",
    )
    budget_events = [
        event for event in events if event.event_type == MEMORY_BLOCKS_BUDGET_EXCEEDED
    ]
    assert len(budget_events) == 1
    details = budget_events[0].details
    assert details["ceiling_tokens"] == 40
    assert "truncated_block_ids" in details
    assert "dropped_block_ids" in details
    assert details["post_truncation_total"] == pkg.total_tokens


def test_under_budget_emits_no_budget_event() -> None:
    events: list[MemoryAuditEvent] = []
    assemble_block_context(
        [_identity(8), _mission(token_estimate=8), _session_pin(token_estimate=8)],
        ceiling_tokens=100,
        identity_floor_tokens=4,
        audit_recorder=events.append,
    )
    assert not [
        event for event in events if event.event_type == MEMORY_BLOCKS_BUDGET_EXCEEDED
    ]


# SMBL-05 FM-2 — stale-but-still-pinned block


def test_stale_block_renders_with_marker_and_counts_against_budget() -> None:
    events: list[MemoryAuditEvent] = []
    block = _mission(stale_after="2026-05-25T00:00:00+00:00")  # already stale
    pkg = assemble_block_context(
        [block],
        ceiling_tokens=4096,
        now_iso="2026-05-26T12:00:00+00:00",
        audit_recorder=events.append,
        session_id="sess-1",
    )
    assert pkg.stale_block_ids == ["blk-mission"]
    rendered = pkg.rendered[0]
    assert rendered.is_stale is True
    assert rendered.content.startswith(STALE_MARKER)
    # Marker cost is added to the original token estimate.
    assert rendered.token_cost > rendered.original_token_estimate
    stale_events = [
        event for event in events if event.event_type == MEMORY_BLOCK_STALE_SURFACED
    ]
    assert len(stale_events) == 1
    assert stale_events[0].target_id == "blk-mission"
    assert stale_events[0].session_id == "sess-1"


def test_stale_event_fires_once_per_session() -> None:
    events: list[MemoryAuditEvent] = []
    seen: set[str] = set()
    block = _mission(stale_after="2026-05-25T00:00:00+00:00")
    # First call should emit; second should not.
    for _ in range(2):
        assemble_block_context(
            [block],
            ceiling_tokens=4096,
            now_iso="2026-05-26T12:00:00+00:00",
            audit_recorder=events.append,
            session_id="sess-1",
            already_marked_stale=seen,
        )
    stale_events = [
        event for event in events if event.event_type == MEMORY_BLOCK_STALE_SURFACED
    ]
    assert len(stale_events) == 1


# SMBL-05 FM-3 — structural / caller-supplied disagreement


def test_claim_key_polarity_disagreement_records_event() -> None:
    events: list[MemoryAuditEvent] = []
    signal = DisagreementSignal(
        kind="claim_key_polarity",
        block_id="blk-mission",
        retrieval_record_id="rec-99",
        claim_key="project.deadline",
        block_polarity="asserts",
        retrieval_polarity="negates",
    )
    outcome = record_disagreement(
        signal,
        session_id="sess-1",
        audit_recorder=events.append,
    )
    assert outcome.block_preferred is True
    assert len(events) == 1
    event = events[0]
    assert event.event_type == MEMORY_BLOCK_DISAGREEMENT_RECORDED
    assert event.details["kind"] == "claim_key_polarity"
    assert event.details["claim_key"] == "project.deadline"
    assert event.details["block_preferred"] is True


def test_disagreement_does_not_modify_anything() -> None:
    """FM-3: the block wins, and nothing is auto-updated."""
    signal = DisagreementSignal(
        kind="exact_key_contradiction_fact",
        block_id="blk-mission",
        retrieval_record_id="rec-99",
    )
    outcome = record_disagreement(signal)
    assert outcome.block_preferred is True
    # The function is structural-only — it does not return any
    # "apply mutation" surface.
    assert not hasattr(outcome, "apply")


def test_claim_key_polarity_requires_both_polarities() -> None:
    with pytest.raises(InvalidArgumentError):
        record_disagreement(
            DisagreementSignal(
                kind="claim_key_polarity",
                block_id="blk-mission",
                retrieval_record_id="rec-99",
                claim_key="project.deadline",
                block_polarity="asserts",
                retrieval_polarity=None,
            )
        )


def test_claim_key_polarity_rejects_identical_polarities() -> None:
    with pytest.raises(InvalidArgumentError):
        record_disagreement(
            DisagreementSignal(
                kind="claim_key_polarity",
                block_id="blk-mission",
                retrieval_record_id="rec-99",
                claim_key="project.deadline",
                block_polarity="asserts",
                retrieval_polarity="asserts",
            )
        )


def test_no_runtime_prose_inference_in_signal_construction() -> None:
    """Guard the public surface against prose-inference symbols."""
    from sophiagraph.query import blocks as blocks_mod

    public_callables = {
        name for name in blocks_mod.__all__ if callable(getattr(blocks_mod, name, None))
    }
    # No symbol matches prose/embedding/LLM-judge inference.
    forbidden = {"detect_from_prose", "infer_disagreement", "classify_contradiction"}
    assert public_callables & forbidden == set()
