from __future__ import annotations

from dataclasses import dataclass

from sophiagraph.collaboration import ConservativeThreeWayMergeAdapter
from sophiagraph.materialized_views import (
    InMemoryMaterializedViewCache,
    refresh_materialized_view,
    view_requires_refresh,
)
from sophiagraph.models import MemoryNamespace, MemoryRecord, SophiaGraphChangeEvent
from sophiagraph.security import (
    MappingKeyProvider,
    decrypt_json_payload,
    encrypt_json_payload,
)
from sophiagraph.views import SavedViewDefinition


@dataclass
class _TestCipher:
    algorithm: str = "test-authenticated"

    def encrypt(self, key: bytes, plaintext: bytes, associated_data: bytes):
        return b"nonce", bytes(value ^ key[0] for value in plaintext)

    def decrypt(
        self, key: bytes, nonce: bytes, ciphertext: bytes, associated_data: bytes
    ):
        assert nonce == b"nonce"
        return bytes(value ^ key[0] for value in ciphertext)


def test_encrypted_payload_roundtrip_uses_caller_key_and_aad() -> None:
    provider = MappingKeyProvider({"key-1": b"k" * 32})
    cipher = _TestCipher()
    encrypted = encrypt_json_payload(
        {"content": "private"},
        key_id="key-1",
        key_provider=provider,
        cipher=cipher,
        associated_data=b"namespace:agent-1",
    )
    assert decrypt_json_payload(
        encrypted,
        key_provider=provider,
        cipher=cipher,
        associated_data=b"namespace:agent-1",
    ) == {"content": "private"}


def test_three_way_merge_preserves_concurrent_conflict() -> None:
    result = ConservativeThreeWayMergeAdapter().merge(
        base={"title": "A", "body": "base"},
        local={"title": "Local", "body": "local"},
        remote={"title": "Remote", "body": "base"},
    )
    assert result.values["body"] == "local"
    assert result.values["title"] == "A"
    assert result.conflicts[0].field == "title"


def test_materialized_view_refreshes_only_for_new_relevant_changes() -> None:
    cache = InMemoryMaterializedViewCache()
    definition = SavedViewDefinition(view_id="view-1", name="Records")
    record = MemoryRecord(
        id="rec-1",
        scope="agent:agent-1",
        namespace=MemoryNamespace(agent_id="agent-1", graph_id="main"),
        type="fact",
        content="Stored fact",
        source="user_said",
        created_at="2026-07-15T00:00:00+00:00",
        updated_at="2026-07-15T00:00:00+00:00",
    )
    entry = refresh_materialized_view(
        definition,
        [record],
        source_cursor=3,
        cache=cache,
    )
    old_event = SophiaGraphChangeEvent(
        event_id="event-1",
        object_type="record",
        object_id="rec-1",
        operation="put",
        changed_at="2026-07-15T00:00:00+00:00",
        payload={},
        cursor=3,
    )
    new_event = SophiaGraphChangeEvent(
        event_id="event-2",
        object_type="record",
        object_id="rec-1",
        operation="put",
        changed_at="2026-07-15T00:00:01+00:00",
        payload={},
        cursor=4,
    )
    assert cache.get("view-1") == entry
    assert view_requires_refresh(entry, [old_event]) is False
    assert view_requires_refresh(entry, [new_event]) is True
