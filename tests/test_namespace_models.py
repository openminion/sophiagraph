from __future__ import annotations

import pytest

from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.models import MemoryNamespace, MemoryNamespaceComponent, MemoryRecord


def test_memory_namespace_validates_explicit_dimensions() -> None:
    namespace = MemoryNamespace(
        tenant_id="tenant-acme",
        org_id="org-research",
        user_id="user-j",
        agent_id="agent-codex",
        session_id="session-123",
        conversation_id="conversation-456",
        project_id="project-sophiagraph",
        graph_id="graph-main",
    )

    assert namespace.as_dict() == {
        "tenant_id": "tenant-acme",
        "org_id": "org-research",
        "user_id": "user-j",
        "agent_id": "agent-codex",
        "session_id": "session-123",
        "conversation_id": "conversation-456",
        "project_id": "project-sophiagraph",
        "graph_id": "graph-main",
    }
    assert [component.kind for component in namespace.components] == [
        "tenant",
        "org",
        "user",
        "agent",
        "session",
        "conversation",
        "project",
        "graph",
    ]


def test_memory_namespace_rejects_missing_or_invalid_ids() -> None:
    with pytest.raises(InvalidArgumentError, match="at least one namespace id"):
        MemoryNamespace()

    with pytest.raises(InvalidArgumentError, match="invalid user_id"):
        MemoryNamespace(user_id="bad id with spaces")


def test_memory_namespace_keeps_legacy_scope_compatibility() -> None:
    assert MemoryNamespace.from_scope("session:s1").to_scope("session") == "session:s1"
    assert MemoryNamespace.from_scope("agent:a1").to_scope("agent") == "agent:a1"
    assert MemoryNamespace.from_scope("project:p1").to_scope("project") == "project:p1"
    assert MemoryNamespace.from_scope("global:g1").to_scope("global") == "global:g1"


def test_memory_namespace_component_scope_bridge_is_explicit() -> None:
    assert (
        MemoryNamespaceComponent(kind="agent", id="codex").as_scope() == "agent:codex"
    )
    assert MemoryNamespaceComponent(kind="graph", id="main").as_scope() == "global:main"

    with pytest.raises(InvalidArgumentError, match="legacy scope"):
        MemoryNamespaceComponent(kind="tenant", id="acme").as_scope()


def test_existing_scope_records_still_load_without_namespace_fields() -> None:
    record = MemoryRecord(
        id="rec-legacy",
        scope="agent:legacy",
        type="fact",
        content={"text": "legacy scope remains valid"},
        created_at="2026-05-23T00:00:00+00:00",
        updated_at="2026-05-23T00:00:00+00:00",
    )

    assert record.scope == "agent:legacy"
    assert MemoryNamespace.from_scope(record.scope).agent_id == "legacy"
    assert record.effective_namespace == MemoryNamespace(agent_id="legacy")


def test_memory_record_accepts_explicit_namespace() -> None:
    namespace = MemoryNamespace(
        tenant_id="tenant-acme",
        user_id="user-j",
        agent_id="codex",
    )
    record = MemoryRecord(
        id="rec-namespace",
        scope="agent:codex",
        type="fact",
        content={"text": "namespace persists"},
        created_at="2026-05-23T00:00:00+00:00",
        updated_at="2026-05-23T00:00:00+00:00",
        namespace=namespace,
    )

    assert record.effective_namespace == namespace
