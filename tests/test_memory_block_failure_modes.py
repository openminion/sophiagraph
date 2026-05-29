"""Memory-block failure modes and cross-package smoke coverage."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from sophiagraph import (
    SophiaGraphMemoryStore,
    SophiaGraphSqliteStore,
)
from sophiagraph.contracts.errors import (
    MEMORY_BLOCK_DISAGREEMENT_RECORDED,
    MEMORY_BLOCK_EDIT_DENIED,
    MEMORY_BLOCK_STALE_SURFACED,
    MEMORY_BLOCKS_BUDGET_EXCEEDED,
    MemoryBlockClassNotEligibleError,
    MemoryBlockEditDeniedError,
    MemoryBlockModeInvalidError,
    MemoryBlockModeNotYetSupportedError,
    MemoryBlocksBudgetHardFloorViolatedError,
)
from sophiagraph.models import (
    MemoryBlock,
    MemoryNamespace,
    validate_block_for_creation,
)
from sophiagraph.portability.codec import (
    read_bundle_snapshot,
    write_bundle_snapshot,
)
from sophiagraph.portability.models import (
    MemoryBundleExportOptions,
    MemoryBundleImportOptions,
)
from sophiagraph.query import (
    DisagreementSignal,
    assemble_block_context,
    record_disagreement,
)


def _ns() -> MemoryNamespace:
    return MemoryNamespace(tenant_id="acme", agent_id="alpha")


def _build(
    block_id: str,
    class_name: str,
    mode: str,
    *,
    content: str = "x",
    token_estimate: int = 8,
    stale_after: str | None = None,
) -> MemoryBlock:
    now = datetime.now(timezone.utc).isoformat()
    return MemoryBlock(
        block_id=block_id,
        class_name=class_name,
        mode=mode,
        content=content,
        token_estimate=token_estimate,
        owner_namespace=_ns(),
        source="test",
        created_at=now,
        last_updated_at=now,
        last_updated_by="system",
        stale_after=stale_after,
    )


# ---------------------------------------------------------------------------
# Allowlist + mode denials at creation
# ---------------------------------------------------------------------------


def test_class_allowlist_denial() -> None:
    block = _build("blk-1", "project_config", "read_only")  # NOT eligible
    with pytest.raises(MemoryBlockClassNotEligibleError) as info:
        validate_block_for_creation(block)
    assert info.value.code == "MEMORY_BLOCK_CLASS_NOT_ELIGIBLE"


def test_deferred_mode_denial() -> None:
    for mode in ("shared", "writable"):
        block = _build("blk-x", "active_mission", mode)
        with pytest.raises(MemoryBlockModeNotYetSupportedError) as info:
            validate_block_for_creation(block)
        assert info.value.code == "MEMORY_BLOCK_MODE_NOT_YET_SUPPORTED"


def test_unknown_mode_rejected_at_dto_construction() -> None:
    with pytest.raises(MemoryBlockModeInvalidError):
        MemoryBlock(
            block_id="blk-bad",
            class_name="active_mission",
            mode="cosmic",  # not in the 4-value Literal
            content="x",
            token_estimate=1,
            owner_namespace=_ns(),
            source="test",
            created_at="2026-05-26T00:00:00+00:00",
            last_updated_at="2026-05-26T00:00:00+00:00",
            last_updated_by="system",
        )


# ---------------------------------------------------------------------------
# Portability compatibility — all four modes round-trip; activation gate
# still rejects deferred modes on the importing side.
# ---------------------------------------------------------------------------


def test_bundle_round_trips_all_four_modes(tmp_path: Path) -> None:
    source = SophiaGraphSqliteStore(tmp_path / "src.sqlite3")
    blocks = [
        _build("blk-ro", "agent_identity", "read_only"),
        _build("blk-pin", "active_mission", "pinned"),
        _build("blk-sh", "active_mission", "shared"),
        _build("blk-wr", "active_mission", "writable"),
    ]
    for block in blocks:
        source.put_memory_block(block)

    snap = source.export_snapshot(
        MemoryBundleExportOptions(scopes=[], include_memory_blocks=True)
    )
    bundle = write_bundle_snapshot(snap, tmp_path / "bundle.tar.gz")
    rehydrated = read_bundle_snapshot(bundle)
    modes = {block.block_id: block.mode for block in rehydrated.memory_blocks}
    assert modes == {
        "blk-ro": "read_only",
        "blk-pin": "pinned",
        "blk-sh": "shared",
        "blk-wr": "writable",
    }

    target = SophiaGraphMemoryStore()
    result = target.import_snapshot(rehydrated, MemoryBundleImportOptions())
    assert result.imported_memory_blocks == 4

    # ...but the activation gate still rejects the deferred-mode blocks
    # if a caller tries to treat an imported block as active.
    shared = target.get_memory_block("blk-sh")
    assert shared is not None
    with pytest.raises(MemoryBlockModeNotYetSupportedError):
        validate_block_for_creation(shared)


# ---------------------------------------------------------------------------
# Reverse-priority truncation + hard-floor loud failure
# ---------------------------------------------------------------------------


def test_reverse_priority_truncation_and_hard_floor() -> None:
    pkg = assemble_block_context(
        [
            _build("blk-id", "agent_identity", "read_only", token_estimate=32),
            _build("blk-mi", "active_mission", "pinned", token_estimate=24),
            _build("blk-se", "session_pin", "pinned", token_estimate=16),
        ],
        ceiling_tokens=50,
        identity_floor_tokens=8,
    )
    # session truncates first, never identity-only-drop.
    impact = pkg.truncated_block_ids + pkg.dropped_block_ids
    assert "blk-se" in impact
    assert "blk-id" not in pkg.dropped_block_ids
    assert pkg.total_tokens <= 50

    # Hard floor loud failure when the floor can't fit under the ceiling.
    with pytest.raises(MemoryBlocksBudgetHardFloorViolatedError):
        assemble_block_context(
            [_build("blk-id", "agent_identity", "read_only", token_estimate=32)],
            ceiling_tokens=10,
            identity_floor_tokens=128,
        )


# ---------------------------------------------------------------------------
# FM-1 + FM-2 audit-event emissions wired through the recorder
# ---------------------------------------------------------------------------


def test_failure_mode_audit_emissions() -> None:
    events = []
    seen_stale: set[str] = set()

    pkg = assemble_block_context(
        [
            _build("blk-id", "agent_identity", "read_only", token_estimate=32),
            _build(
                "blk-mi",
                "active_mission",
                "pinned",
                token_estimate=24,
                stale_after="2026-01-01T00:00:00+00:00",  # stale
            ),
            _build("blk-se", "session_pin", "pinned", token_estimate=16),
        ],
        ceiling_tokens=40,
        identity_floor_tokens=8,
        now_iso="2026-05-26T12:00:00+00:00",
        session_id="sess-1",
        audit_recorder=events.append,
        already_marked_stale=seen_stale,
    )
    assert pkg.budget_exceeded is True
    event_types = [event.event_type for event in events]
    assert MEMORY_BLOCKS_BUDGET_EXCEEDED in event_types
    assert MEMORY_BLOCK_STALE_SURFACED in event_types
    # Stale emission is idempotent across calls.
    assemble_block_context(
        [
            _build("blk-id", "agent_identity", "read_only", token_estimate=32),
            _build(
                "blk-mi",
                "active_mission",
                "pinned",
                token_estimate=24,
                stale_after="2026-01-01T00:00:00+00:00",
            ),
        ],
        ceiling_tokens=4096,
        identity_floor_tokens=8,
        now_iso="2026-05-26T12:00:00+00:00",
        session_id="sess-1",
        audit_recorder=events.append,
        already_marked_stale=seen_stale,
    )
    stale_events = [e for e in events if e.event_type == MEMORY_BLOCK_STALE_SURFACED]
    assert len(stale_events) == 1  # once per session per stale block


# ---------------------------------------------------------------------------
# FM-3 structural disagreement + block preference
# ---------------------------------------------------------------------------


def test_structural_disagreement_records_and_prefers_block() -> None:
    events = []
    outcome = record_disagreement(
        DisagreementSignal(
            kind="exact_key_contradiction_fact",
            block_id="blk-mi",
            retrieval_record_id="rec-99",
        ),
        session_id="sess-1",
        audit_recorder=events.append,
    )
    assert outcome.block_preferred is True
    assert events and events[0].event_type == MEMORY_BLOCK_DISAGREEMENT_RECORDED


# ---------------------------------------------------------------------------
# Read-only denial + audit code
# ---------------------------------------------------------------------------


def test_read_only_denial_carries_canonical_audit_code(tmp_path: Path) -> None:
    store = SophiaGraphSqliteStore(tmp_path / "denial.sqlite3")
    block = _build("blk-id", "agent_identity", "read_only")
    store.put_memory_block(block)
    with pytest.raises(MemoryBlockEditDeniedError) as info:
        store.update_memory_block_content(
            "blk-id",
            new_content="hacked",
            actor="bob",
        )
    assert info.value.code == MEMORY_BLOCK_EDIT_DENIED
    assert info.value.details["event_type"] == MEMORY_BLOCK_EDIT_DENIED
    # Durable storage unchanged.
    assert store.get_memory_block("blk-id").content == "x"


# ---------------------------------------------------------------------------
# OpenMinion command-surface smoke (cross-package wiring)
# ---------------------------------------------------------------------------


def test_openminion_cli_module_importable_with_factory_swap() -> None:
    """Smoke: the OpenMinion CLI module imports cleanly against sophiagraph.

    Full CLI behavior is covered in
    ``openminion/tests/memory/test_memory_blocks_cli.py``; this test
    just confirms the cross-package import path is healthy from the
    sophiagraph side, so a fresh-wheel install can wire the CLI.
    """
    pytest.importorskip("openminion.cli.commands.memory")
    from openminion.cli.commands import memory as memory_cmd

    assert callable(memory_cmd.register)
    assert callable(memory_cmd.run_memory_cli_bridge)
    assert callable(memory_cmd.set_store_factory)
    assert callable(memory_cmd.reset_store_factory)
