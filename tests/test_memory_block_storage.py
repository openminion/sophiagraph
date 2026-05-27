"""SMBL-02 + SMBL-03 storage and portability coverage for ``MemoryBlock``.

Proves both backends (memory + SQLite) round-trip blocks, persist all four
mode literals (including the deferred ``shared`` / ``writable`` modes),
keep namespace isolation, support bundle export/import, and honor the
SMBL-03 edit-semantics gate (``read_only`` rejected always; ``pinned``
rejected unless ``operator_action=True``).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sophiagraph import (
    SophiaGraphMemoryStore,
    SophiaGraphSqliteStore,
)
from sophiagraph.contracts.errors import (
    MEMORY_BLOCK_EDIT_DENIED,
    MemoryBlockEditDeniedError,
    NotFoundError,
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


def _ns_a() -> MemoryNamespace:
    return MemoryNamespace(tenant_id="acme", agent_id="alpha")


def _ns_b() -> MemoryNamespace:
    return MemoryNamespace(tenant_id="acme", agent_id="beta")


def _identity_block(block_id: str = "blk-identity-1") -> MemoryBlock:
    return MemoryBlock(
        block_id=block_id,
        class_name="agent_identity",
        mode="read_only",
        content="You are a focused assistant.",
        token_estimate=32,
        owner_namespace=_ns_a(),
        source="agent_config",
        created_at="2026-05-26T10:00:00+00:00",
        last_updated_at="2026-05-26T10:00:00+00:00",
        last_updated_by="system",
    )


def _mission_block(block_id: str = "blk-mission-1") -> MemoryBlock:
    return MemoryBlock(
        block_id=block_id,
        class_name="active_mission",
        mode="pinned",
        content="Investigate the failing tracker.",
        token_estimate=20,
        owner_namespace=_ns_a(),
        source="operator_pin",
        created_at="2026-05-26T10:01:00+00:00",
        last_updated_at="2026-05-26T10:01:00+00:00",
        last_updated_by="alice",
    )


def _deferred_block() -> MemoryBlock:
    """A bundle-only block carrying a deferred mode (round-trips OK)."""
    return MemoryBlock(
        block_id="blk-shared-1",
        class_name="active_mission",
        mode="shared",
        content="(deferred-mode payload — DTO round-trips)",
        token_estimate=12,
        owner_namespace=_ns_a(),
        source="bundle_import",
        created_at="2026-05-26T10:02:00+00:00",
        last_updated_at="2026-05-26T10:02:00+00:00",
        last_updated_by="system",
    )


@pytest.fixture(params=["memory", "sqlite"])
def store(request, tmp_path: Path):
    """Cross-backend parametrization: every test runs on both stores."""
    if request.param == "memory":
        return SophiaGraphMemoryStore()
    return SophiaGraphSqliteStore(tmp_path / "sg.sqlite3")


# ---------------------------------------------------------------------------
# SMBL-02 — persistence + portability + namespace isolation
# ---------------------------------------------------------------------------


def test_put_get_round_trip(store) -> None:
    block = _identity_block()
    block_id = store.put_memory_block(block)
    assert block_id == block.block_id
    loaded = store.get_memory_block(block.block_id)
    assert loaded is not None
    assert loaded.block_id == block.block_id
    assert loaded.class_name == "agent_identity"
    assert loaded.mode == "read_only"
    assert loaded.content == "You are a focused assistant."
    assert loaded.token_estimate == 32
    assert loaded.owner_namespace == _ns_a()
    assert loaded.source == "agent_config"
    assert loaded.last_updated_by == "system"


def test_list_returns_deterministic_order(store) -> None:
    store.put_memory_block(_mission_block("blk-mission-1"))
    store.put_memory_block(_identity_block("blk-identity-1"))
    store.put_memory_block(_mission_block("blk-mission-2"))
    listed = store.list_memory_blocks()
    # Deterministic sort: class_name asc, created_at asc, block_id asc.
    classes = [block.class_name for block in listed]
    assert classes == ["active_mission", "active_mission", "agent_identity"]
    mission_ids = [
        block.block_id for block in listed if block.class_name == "active_mission"
    ]
    assert mission_ids == ["blk-mission-1", "blk-mission-2"]


def test_namespace_isolation(store) -> None:
    a_block = _identity_block("blk-a")  # ns_a
    b_block = MemoryBlock(
        block_id="blk-b",
        class_name="agent_identity",
        mode="read_only",
        content="Different agent.",
        token_estimate=10,
        owner_namespace=_ns_b(),
        source="agent_config",
        created_at="2026-05-26T10:03:00+00:00",
        last_updated_at="2026-05-26T10:03:00+00:00",
        last_updated_by="system",
    )
    store.put_memory_block(a_block)
    store.put_memory_block(b_block)
    only_a = store.list_memory_blocks(namespaces=[_ns_a()])
    only_b = store.list_memory_blocks(namespaces=[_ns_b()])
    assert {block.block_id for block in only_a} == {"blk-a"}
    assert {block.block_id for block in only_b} == {"blk-b"}


def test_stored_dto_round_trips_deferred_modes(store) -> None:
    """A ``shared``/``writable`` block must round-trip without crashing.

    The stored/portable contract is intentionally permissive; the v1 active
    gate runs at ``validate_block_for_creation``, not at the store layer.
    """
    deferred = _deferred_block()
    store.put_memory_block(deferred)
    loaded = store.get_memory_block(deferred.block_id)
    assert loaded is not None
    assert loaded.mode == "shared"
    assert loaded.content == "(deferred-mode payload — DTO round-trips)"
    # ...but the activation gate must still reject it:
    from sophiagraph.contracts.errors import MemoryBlockModeNotYetSupportedError

    with pytest.raises(MemoryBlockModeNotYetSupportedError):
        validate_block_for_creation(loaded)


def test_bundle_round_trips_blocks_including_deferred_modes(
    store, tmp_path: Path
) -> None:
    """Bundle export/import preserves blocks across both mode classes."""
    store.put_memory_block(_identity_block())
    store.put_memory_block(_mission_block())
    store.put_memory_block(_deferred_block())

    snapshot = store.export_snapshot(
        MemoryBundleExportOptions(
            scopes=[],
            include_memory_blocks=True,
        )
    )
    assert {block.block_id for block in snapshot.memory_blocks} == {
        "blk-identity-1",
        "blk-mission-1",
        "blk-shared-1",
    }
    bundle_path = write_bundle_snapshot(snapshot, tmp_path / "bundle.tar.gz")
    hydrated = read_bundle_snapshot(bundle_path)
    assert {block.block_id for block in hydrated.memory_blocks} == {
        "blk-identity-1",
        "blk-mission-1",
        "blk-shared-1",
    }
    deferred = next(
        block for block in hydrated.memory_blocks if block.block_id == "blk-shared-1"
    )
    assert deferred.mode == "shared"  # deferred mode preserved exactly

    # Re-import into a fresh store and confirm counts.
    fresh = SophiaGraphMemoryStore()
    result = fresh.import_snapshot(
        hydrated,
        MemoryBundleImportOptions(),
    )
    assert result.imported_memory_blocks == 3
    assert {block.block_id for block in fresh.list_memory_blocks()} == {
        "blk-identity-1",
        "blk-mission-1",
        "blk-shared-1",
    }


def test_bundle_default_does_not_include_blocks(store) -> None:
    """Off-by-default: existing callers don't get surprise block sections."""
    store.put_memory_block(_identity_block())
    snapshot = store.export_snapshot(MemoryBundleExportOptions(scopes=[]))
    assert snapshot.memory_blocks == []


def test_changefeed_emits_memory_block_events(store) -> None:
    store.put_memory_block(_identity_block())
    store.put_memory_block(_mission_block())
    events = store.list_changes()
    block_events = [event for event in events if event.object_type == "memory_block"]
    assert len(block_events) == 2
    # Schema identifiers carry the canonical names that SGNPOG-06 returns
    # from ``describe_schema()`` — required by the SGNPOG-01 contract.
    assert all(
        event.schema_identifiers.get("node_label") == "memory_block"
        for event in block_events
    )
    assert {event.schema_identifiers.get("class_name") for event in block_events} == {
        "agent_identity",
        "active_mission",
    }


# ---------------------------------------------------------------------------
# SMBL-03 — edit semantics + denial via typed error
# ---------------------------------------------------------------------------


def test_read_only_update_denied_with_typed_error(store) -> None:
    store.put_memory_block(_identity_block())
    with pytest.raises(MemoryBlockEditDeniedError) as info:
        store.update_memory_block_content(
            "blk-identity-1",
            new_content="hacked",
            actor="bob",
        )
    err = info.value
    assert err.code == MEMORY_BLOCK_EDIT_DENIED
    assert err.details["event_type"] == MEMORY_BLOCK_EDIT_DENIED
    assert err.details["reason"] == "read_only_block"
    assert err.details["block_id"] == "blk-identity-1"
    # Content unchanged after denied edit.
    still = store.get_memory_block("blk-identity-1")
    assert still is not None
    assert still.content == "You are a focused assistant."


def test_read_only_update_denied_even_with_operator_action(store) -> None:
    """Read-only is the strict tier — operator_action does not unlock it."""
    store.put_memory_block(_identity_block())
    with pytest.raises(MemoryBlockEditDeniedError):
        store.update_memory_block_content(
            "blk-identity-1",
            new_content="should not apply",
            actor="alice",
            operator_action=True,
        )


def test_pinned_update_requires_operator_action(store) -> None:
    store.put_memory_block(_mission_block())
    with pytest.raises(MemoryBlockEditDeniedError) as info:
        store.update_memory_block_content(
            "blk-mission-1",
            new_content="background-update attempt",
            actor="retrieval-runtime",
        )
    assert info.value.details["reason"] == "operator_action_required"


def test_pinned_update_succeeds_with_operator_action(store) -> None:
    store.put_memory_block(_mission_block())
    updated = store.update_memory_block_content(
        "blk-mission-1",
        new_content="Investigate flake in test_x.",
        actor="alice",
        operator_action=True,
    )
    assert updated.content == "Investigate flake in test_x."
    assert updated.last_updated_by == "alice"
    loaded = store.get_memory_block("blk-mission-1")
    assert loaded is not None
    assert loaded.content == "Investigate flake in test_x."


def test_pinned_delete_requires_operator_action(store) -> None:
    store.put_memory_block(_mission_block())
    with pytest.raises(MemoryBlockEditDeniedError):
        store.delete_memory_block(
            "blk-mission-1",
            actor="retrieval-runtime",
        )
    # And the operator-action-true path actually deletes.
    assert store.delete_memory_block(
        "blk-mission-1", actor="alice", operator_action=True
    )
    assert store.get_memory_block("blk-mission-1") is None


def test_delete_missing_block_returns_false(store) -> None:
    assert (
        store.delete_memory_block("blk-not-here", actor="alice", operator_action=True)
        is False
    )


def test_update_missing_block_raises_not_found(store) -> None:
    with pytest.raises(NotFoundError):
        store.update_memory_block_content(
            "blk-not-here",
            new_content="nope",
            actor="alice",
            operator_action=True,
        )


def test_mark_stale_after_persists(store) -> None:
    store.put_memory_block(_mission_block())
    updated = store.mark_memory_block_stale_after(
        "blk-mission-1",
        stale_after="2026-06-01T00:00:00+00:00",
    )
    assert updated.stale_after == "2026-06-01T00:00:00+00:00"
    loaded = store.get_memory_block("blk-mission-1")
    assert loaded is not None
    assert loaded.stale_after == "2026-06-01T00:00:00+00:00"


def test_list_memory_blocks_excludes_stale_when_requested(store) -> None:
    store.put_memory_block(_identity_block())
    store.put_memory_block(_mission_block())
    store.mark_memory_block_stale_after(
        "blk-mission-1",
        stale_after="1970-01-01T00:00:00+00:00",  # already stale
    )
    fresh_only = store.list_memory_blocks(include_stale=False)
    assert {block.block_id for block in fresh_only} == {"blk-identity-1"}
    with_stale = store.list_memory_blocks(include_stale=True)
    assert {block.block_id for block in with_stale} == {
        "blk-identity-1",
        "blk-mission-1",
    }
