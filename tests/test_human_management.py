from __future__ import annotations

from sophiagraph import (
    FreshnessLedgerEntry,
    HumanNoteInput,
    HumanNotePatch,
    MemoryNamespace,
    SophiaGraphMemoryStore,
    SourceRegistryEntry,
    VaultFilePayload,
    VaultImportOptions,
    archive_human_note,
    build_human_workbench_packet,
    build_source_management_console,
    create_human_note,
    import_vault_files,
    list_human_workspace,
    plan_human_vault_import,
    render_human_workbench_html,
    update_human_note,
)
from sophiagraph.freshness import freshness_id_for
from sophiagraph.sync import LocalSyncRequest, detect_sync_conflict


def _ns() -> MemoryNamespace:
    return MemoryNamespace(tenant_id="tenant", agent_id="human", graph_id="main")


def test_human_note_workspace_supports_create_update_archive_and_list() -> None:
    store = SophiaGraphMemoryStore()
    created = create_human_note(
        store,
        HumanNoteInput(
            scope="agent:notes",
            namespace=_ns(),
            note_key="alpha",
            title="Alpha note",
            body="Initial body",
            tags=("notes", "alpha"),
            created_at="2026-06-12T00:00:00+00:00",
        ),
    )

    updated = update_human_note(
        store,
        record_id=created.id,
        patch=HumanNotePatch(
            title="Alpha note updated",
            body="Updated body",
            updated_at="2026-06-12T01:00:00+00:00",
        ),
    )
    archived = archive_human_note(
        store,
        record_id=created.id,
        archived_at="2026-06-12T02:00:00+00:00",
        reason="archived for test",
    )

    active = list_human_workspace(
        store,
        scope="agent:notes",
        namespace=_ns(),
        include_archived=False,
    )
    all_notes = list_human_workspace(
        store,
        scope="agent:notes",
        namespace=_ns(),
        include_archived=True,
    )

    assert updated.title == "Alpha note updated"
    assert updated.content["text"] == "Updated body"
    assert archived.meta["human_note"]["archived"] is True
    assert active.active_count == 0
    assert all_notes.archived_count == 1
    assert all_notes.notes[0].archived is True


def test_vault_import_dry_run_reports_create_update_delete_and_stale() -> None:
    store = SophiaGraphMemoryStore()
    options = VaultImportOptions(
        vault_id="vault-main",
        namespace=_ns(),
        scope="agent:notes",
        tombstone_missing=True,
        imported_at="2026-06-12T00:00:00+00:00",
    )
    initial_files = [
        VaultFilePayload(path="notes/alpha.md", content="# Alpha\n\nBody\n"),
        VaultFilePayload(path="notes/beta.md", content="# Beta\n\nKeep me\n"),
    ]
    import_vault_files(store, initial_files, options)

    plan = plan_human_vault_import(
        store,
        [
            VaultFilePayload(path="notes/alpha.md", content="# Alpha\n\nChanged\n"),
            VaultFilePayload(path="notes/gamma.md", content="# Gamma\n\nNew\n"),
        ],
        options,
    )

    by_path = {item.path: item for item in plan.items}
    assert plan.updated_count == 1
    assert plan.created_count == 1
    assert plan.deleted_count == 1
    assert plan.stale_count == 1
    assert by_path["notes/alpha.md"].action == "update"
    assert by_path["notes/gamma.md"].action == "create"
    assert by_path["notes/beta.md"].action == "delete"


def test_source_management_console_merges_sources_freshness_and_conflicts() -> None:
    store = SophiaGraphMemoryStore()
    create_human_note(
        store,
        HumanNoteInput(
            scope="agent:notes",
            namespace=_ns(),
            note_key="with-source",
            title="Source-backed note",
            body="Body",
            meta={"source_id": "src-1"},
        ),
    )
    source = SourceRegistryEntry(
        source_id="src-1",
        source_type="manual",
        namespace=_ns(),
        display_name="Manual Source",
        permission_scope="read_write",
        updated_at="2026-06-12T00:00:00+00:00",
    )
    freshness = FreshnessLedgerEntry(
        ledger_id=freshness_id_for(_ns(), "connector", "src-1"),
        namespace=_ns(),
        source_kind="connector",
        source_id="src-1",
        status="failed",
        updated_at="2026-06-12T01:00:00+00:00",
        error_code="connector_failed",
    )
    conflict = detect_sync_conflict(
        LocalSyncRequest(
            mode="file_primary",
            namespace=_ns(),
            source_id="src-1",
            path="notes/with-source.md",
            previous_file_hash="h1",
            previous_record_hash="r1",
            current_file_hash="h2",
            current_record_hash="r2",
        ),
        observed_at="2026-06-12T02:00:00+00:00",
    ).conflict
    assert conflict is not None

    store.put_source_entry(source)
    store.put_freshness_entry(freshness)
    store.put_sync_conflict(conflict)

    console = build_source_management_console(
        store,
        scope="agent:notes",
        namespace=_ns(),
    )

    assert console.open_conflict_count == 1
    assert console.sources[0].freshness_status == "failed"
    assert console.sources[0].open_conflict_count == 1
    assert console.inspection_report is not None
    assert any(
        finding.kind == "open_conflict"
        for finding in console.inspection_report.findings
    )


def test_human_workbench_packet_and_html_render_surface_notes_imports_and_sources() -> (
    None
):
    store = SophiaGraphMemoryStore()
    create_human_note(
        store,
        HumanNoteInput(
            scope="agent:notes",
            namespace=_ns(),
            note_key="alpha",
            title="Alpha note",
            body="Alpha body",
        ),
    )
    packet = build_human_workbench_packet(
        store,
        scope="agent:notes",
        namespace=_ns(),
        import_files=[
            VaultFilePayload(path="notes/alpha.md", content="# Alpha\n\nAlpha body\n")
        ],
        import_options=VaultImportOptions(
            vault_id="vault-main",
            namespace=_ns(),
            scope="agent:notes",
        ),
    )

    html = render_human_workbench_html(packet)
    assert packet.workspace.active_count == 1
    assert packet.import_plan is not None
    assert "Human Workbench" in html
    assert "Alpha note" in html
    assert "Import Plan" in html
