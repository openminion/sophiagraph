from __future__ import annotations

from dataclasses import replace

import pytest

from sophiagraph.models import MemoryNamespace
from sophiagraph.query import LinkQueryOptions, ListQueryOptions, StructuralSearchQuery
from sophiagraph.storage import SophiaGraphMemoryStore, SophiaGraphSqliteStore
from sophiagraph.vault import (
    VaultExportOptions,
    VaultFilePayload,
    VaultImportOptions,
    VaultRenameOperation,
    apply_vault_repair_plan,
    build_vault_manifest,
    export_vault_files,
    import_vault_files,
    plan_vault_repairs,
)


def _namespace(agent_id: str = "agent") -> MemoryNamespace:
    return MemoryNamespace(tenant_id="tenant", agent_id=agent_id, graph_id="main")


@pytest.fixture(params=["memory", "sqlite"])
def store(request, tmp_path):
    if request.param == "memory":
        return SophiaGraphMemoryStore()
    return SophiaGraphSqliteStore(tmp_path / "vault.sqlite3")


def _options(namespace: MemoryNamespace) -> VaultImportOptions:
    return VaultImportOptions(
        vault_id="vault-main",
        namespace=namespace,
        scope=f"agent:{namespace.agent_id}",
        root_label="fixture-vault",
        imported_at="2026-05-25T00:00:00+00:00",
    )


def _roadmap_text(target: str = "Decision Log") -> str:
    return f"""---
title: Roadmap
aliases: [Plan]
tags: [project/core]
status: active
---
# Roadmap

See [[{target}|decisions]] and ![[Diagram#^block-1]].
- [ ] Ship vault sync ^todo-1
"""


def _decision_text() -> str:
    return """---
title: Decision Log
aliases: [decisions]
tags: [project/core]
---
# Decision Log

Decision content.
"""


def test_vault_manifest_rejects_traversal_and_reports_duplicates() -> None:
    namespace = _namespace()
    options = _options(namespace)

    with pytest.raises(Exception, match="relative"):
        VaultFilePayload(path="../secret.md", content="nope")

    result = import_vault_files(
        SophiaGraphMemoryStore(),
        [
            VaultFilePayload(path="Roadmap.md", content=_roadmap_text()),
            VaultFilePayload(path="Roadmap.md", content=_roadmap_text()),
        ],
        options,
    )
    manifest = build_vault_manifest(
        [VaultFilePayload(path="Roadmap.md", content=_roadmap_text())], options
    )

    assert [file.path for file in manifest.files] == ["Roadmap.md"]
    assert result.created_count == 1
    assert [diagnostic.code for diagnostic in result.diagnostics] == ["duplicate_path"]


def test_vault_import_export_round_trip_blocks_links_and_changefeed(store) -> None:
    namespace = _namespace()
    options = _options(namespace)
    result = import_vault_files(
        store,
        [
            VaultFilePayload(path="Roadmap.md", content=_roadmap_text()),
            VaultFilePayload(path="Decision Log.md", content=_decision_text()),
            VaultFilePayload(
                path="Boards/Main.canvas",
                content='{"nodes":[{"id":"n1","type":"text","x":0,"y":0,"width":200,"height":100,"text":"hello"}],"edges":[]}',
            ),
        ],
        options,
    )

    records = store.list_records(
        ListQueryOptions(scopes=["agent:agent"], namespaces=[namespace])
    )
    roadmap = next(record for record in records if record.title == "Roadmap")
    links = store.list_links(
        LinkQueryOptions(
            record_id=roadmap.id,
            direction="out",
            namespaces=[namespace],
        )
    )
    blocks = store.list_document_blocks(record_id=roadmap.id)
    exported = export_vault_files(
        store,
        VaultExportOptions(
            vault_id="vault-main", namespace=namespace, scope="agent:agent"
        ),
    )

    assert result.created_count == 3
    assert {file.path for file in result.manifest.files} == {
        "Boards/Main.canvas",
        "Decision Log.md",
        "Roadmap.md",
    }
    assert any(link.resolution_status == "resolved" for link in links)
    assert any(link.resolution_status == "unresolved" for link in links)
    assert {block.anchor for block in blocks} >= {"roadmap", "todo-1"}
    assert any(event.object_type == "link" for event in store.list_changes())
    assert any(event.object_type == "block" for event in store.list_changes())
    assert {
        (file.path, file.content)
        for file in exported.files
        if file.path == "Roadmap.md"
    } == {("Roadmap.md", _roadmap_text())}


def test_reimport_removes_stale_links_and_blocks(store) -> None:
    namespace = _namespace()
    options = _options(namespace)
    import_vault_files(
        store,
        [
            VaultFilePayload(path="Roadmap.md", content=_roadmap_text()),
            VaultFilePayload(path="Decision Log.md", content=_decision_text()),
        ],
        options,
    )
    second = import_vault_files(
        store,
        [VaultFilePayload(path="Roadmap.md", content="# Roadmap\n\nNo links now.\n")],
        options,
    )
    roadmap = next(
        record
        for record in store.list_records(ListQueryOptions(scopes=["agent:agent"]))
        if record.title == "Roadmap"
    )

    assert second.updated_count == 1
    assert (
        store.list_links(LinkQueryOptions(record_id=roadmap.id, direction="out")) == []
    )
    assert [
        block.anchor for block in store.list_document_blocks(record_id=roadmap.id)
    ] == ["roadmap"]
    assert (
        store.structural_search_records(
            StructuralSearchQuery(block="todo-1"), scopes=["agent:agent"]
        )
        == []
    )


def test_vault_repair_plan_updates_structural_targets_without_rewriting_source(
    store,
) -> None:
    namespace = _namespace()
    options = _options(namespace)
    import_vault_files(
        store,
        [
            VaultFilePayload(
                path="Projects/Roadmap.md",
                content=_roadmap_text("Projects/Decision Log.md"),
            ),
            VaultFilePayload(path="Projects/Decision Log.md", content=_decision_text()),
        ],
        options,
    )
    export_options = VaultExportOptions(
        vault_id="vault-main", namespace=namespace, scope="agent:agent"
    )
    plan = plan_vault_repairs(
        store,
        [
            VaultRenameOperation(
                old_path="Projects/Decision Log.md",
                new_path="Decision Log.md",
            )
        ],
        export_options,
    )
    applied = apply_vault_repair_plan(store, plan, export_options)
    roadmap = next(
        record
        for record in store.list_records(ListQueryOptions(scopes=["agent:agent"]))
        if record.title == "Roadmap"
    )
    links = store.list_links(LinkQueryOptions(record_id=roadmap.id, direction="out"))
    link = next(link for link in links if link.target_path == "Decision Log.md")
    exported = export_vault_files(store, export_options)

    assert plan.changed_count == 1
    assert applied.changed_count == 1
    assert link.raw_target == "Decision Log.md|decisions"
    assert link.target_path == "Decision Log.md"
    roadmap_export = next(
        file for file in exported.files if file.path == "Projects/Roadmap.md"
    )
    assert roadmap_export.content == _roadmap_text("Projects/Decision Log.md")


def test_vault_repair_plan_reports_conflicts_and_preserves_namespaces(store) -> None:
    first_namespace = _namespace("agent-a")
    second_namespace = _namespace("agent-b")
    first_options = _options(first_namespace)
    second_options = _options(second_namespace)
    import_vault_files(
        store,
        [
            VaultFilePayload(
                path="Projects/Roadmap.md",
                content=_roadmap_text("Projects/Decision Log.md"),
            ),
            VaultFilePayload(path="Projects/Decision Log.md", content=_decision_text()),
            VaultFilePayload(path="Decision Log.md", content=_decision_text()),
        ],
        first_options,
    )
    import_vault_files(
        store,
        [
            VaultFilePayload(
                path="Projects/Roadmap.md",
                content=_roadmap_text("Projects/Decision Log.md"),
            ),
            VaultFilePayload(path="Projects/Decision Log.md", content=_decision_text()),
        ],
        second_options,
    )

    operation = VaultRenameOperation(
        old_path="Projects/Decision Log.md",
        new_path="Decision Log.md",
    )
    first_export = VaultExportOptions(
        vault_id="vault-main", namespace=first_namespace, scope="agent:agent-a"
    )
    second_export = VaultExportOptions(
        vault_id="vault-main", namespace=second_namespace, scope="agent:agent-b"
    )
    plan = plan_vault_repairs(store, [operation], first_export)
    applied = apply_vault_repair_plan(store, plan, first_export)
    second_roadmap = next(
        record
        for record in store.list_records(
            ListQueryOptions(scopes=["agent:agent-b"], namespaces=[second_namespace])
        )
        if record.title == "Roadmap"
    )
    second_link = next(
        link
        for link in store.list_links(
            LinkQueryOptions(record_id=second_roadmap.id, direction="out")
        )
        if link.target_path == "Projects/Decision Log.md"
    )

    assert [diagnostic.code for diagnostic in plan.diagnostics] == [
        "repair_target_conflict"
    ]
    assert applied.changed_count == 1
    assert second_link.raw_target == "Projects/Decision Log.md|decisions"
    assert export_vault_files(store, second_export).diagnostics == []


def test_vault_deleted_and_missing_files_become_tombstones(store) -> None:
    namespace = _namespace()
    options = _options(namespace)
    import_vault_files(
        store,
        [
            VaultFilePayload(path="Roadmap.md", content=_roadmap_text()),
            VaultFilePayload(path="Decision Log.md", content=_decision_text()),
        ],
        options,
    )
    deleted = import_vault_files(
        store,
        [VaultFilePayload(path="Roadmap.md", deleted=True)],
        replace(options, tombstone_missing=True),
    )
    records = store.list_records(
        ListQueryOptions(scopes=["agent:agent"], namespaces=[namespace])
    )

    assert deleted.deleted_count == 2
    assert deleted.stale_count == 1
    assert all(record.is_deleted for record in records)
    assert (
        export_vault_files(
            store,
            VaultExportOptions(
                vault_id="vault-main", namespace=namespace, scope="agent:agent"
            ),
        ).files
        == []
    )
