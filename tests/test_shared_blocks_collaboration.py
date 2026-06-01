from __future__ import annotations

import pytest

from sophiagraph.models import MemoryBlock, MemoryNamespace
from sophiagraph.shared_blocks import (
    SharedBlockMirror,
    SharedBlockUsageEvent,
    create_shared_block_conflict,
    mark_mirror_stale_if_needed,
)
from sophiagraph.shared_blocks import SharedBlockAttachment
from sophiagraph.storage import SophiaGraphMemoryStore, SophiaGraphSqliteStore


def _ns(agent_id: str = "agent") -> MemoryNamespace:
    return MemoryNamespace(tenant_id="tenant", agent_id=agent_id, graph_id="main")


@pytest.fixture(params=["memory", "sqlite"])
def store(request, tmp_path):
    if request.param == "memory":
        return SophiaGraphMemoryStore()
    return SophiaGraphSqliteStore(tmp_path / "shared.sqlite3")


def _block() -> MemoryBlock:
    return MemoryBlock(
        block_id="block-policy",
        class_name="agent_identity",
        mode="read_only",
        content="Policy block",
        token_estimate=2,
        owner_namespace=_ns("owner"),
        source="operator",
        created_at="2026-05-31T00:00:00+00:00",
        last_updated_at="2026-05-31T00:00:00+00:00",
    )


def test_shared_read_only_attachments_and_usage_round_trip(store) -> None:
    store.put_memory_block(_block())
    first = SharedBlockAttachment.create(
        block_id="block-policy",
        namespace=_ns("a"),
        attached_agent_id="a",
        attached_at="2026-05-31T00:01:00+00:00",
    )
    second = SharedBlockAttachment.create(
        block_id="block-policy",
        namespace=_ns("b"),
        attached_agent_id="b",
        attached_at="2026-05-31T00:02:00+00:00",
    )
    event = SharedBlockUsageEvent(
        event_id="usage-1",
        block_id="block-policy",
        namespace=_ns("a"),
        agent_id="a",
        action="read",
        occurred_at="2026-05-31T00:03:00+00:00",
    )

    store.put_shared_block_attachment(first)
    store.put_shared_block_attachment(second)
    store.put_shared_block_usage_event(event)

    assert {
        attachment.attachment_id
        for attachment in store.list_shared_block_attachments(block_id="block-policy")
    } == {first.attachment_id, second.attachment_id}
    assert store.list_shared_block_usage_events(action="read") == [event]


def test_shared_block_access_mode_is_default_deny() -> None:
    with pytest.raises(Exception, match="read_only"):
        SharedBlockAttachment(
            attachment_id="bad",
            block_id="block-policy",
            namespace=_ns(),
            attached_agent_id="agent",
            access_mode="writable",  # type: ignore[arg-type]
        )


def test_shared_mirror_stale_detection_and_storage(store) -> None:
    mirror = SharedBlockMirror(
        mirror_id="mirror-1",
        block_id="block-policy",
        source_namespace=_ns("owner"),
        mirror_namespace=_ns("agent"),
        source_hash="hash-1",
        mirror_hash="hash-1",
        last_synced_at="2026-05-31T00:00:00+00:00",
    )
    stale = mark_mirror_stale_if_needed(mirror, current_source_hash="hash-2")

    store.put_shared_block_mirror(stale)

    assert stale.status == "stale"
    assert stale.is_stale
    assert store.get_shared_block_mirror("mirror-1") == stale
    assert store.list_shared_block_mirrors(status="stale") == [stale]


def test_shared_edit_conflict_is_structural(store) -> None:
    conflict = create_shared_block_conflict(
        block_id="block-policy",
        namespace=_ns("agent"),
        attempted_by="agent",
        reason="read_only_shared_block",
        base_hash="hash-1",
        proposed_hash="hash-2",
        created_at="2026-05-31T00:10:00+00:00",
    )

    store.put_shared_block_conflict(conflict)

    assert conflict.status == "open"
    assert store.list_shared_block_conflicts(block_id="block-policy") == [conflict]
