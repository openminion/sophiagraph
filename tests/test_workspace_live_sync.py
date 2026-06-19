from __future__ import annotations

import ast
import json
from dataclasses import replace
from pathlib import Path
import subprocess
import sys

from sophiagraph import (
    MemoryNamespace,
    WorkspaceFilePrimaryNoteOptions,
    apply_workspace_sync,
    initialize_workspace,
    materialize_workspace_note,
    open_workspace_store,
    poll_workspace_sync,
    scan_workspace_sync,
    workspace_file_primary_note_put,
    workspace_note_put,
    workspace_sync_status,
)


def _ns() -> MemoryNamespace:
    return MemoryNamespace(agent_id="workspace-sync", graph_id="main")


def _init_workspace(workspace_root: Path) -> None:
    initialize_workspace(
        workspace_root,
        scope="agent:workspace-sync",
        namespace=_ns(),
        label="workspace-sync",
        vault_id="vault-sync",
    )


def _write_markdown(root: Path, relative_path: str, content: str) -> Path:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_workspace_live_sync_create_apply_status_and_roundtrip(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    source_root = tmp_path / "notes"
    _init_workspace(workspace)
    _write_markdown(source_root, "notes/alpha.md", "# Alpha\n\nAlpha body\n")

    plan = scan_workspace_sync(workspace, source_root)
    assert plan.created_count == 1
    assert plan.modified_count == 0
    assert plan.deleted_count == 0
    assert plan.renamed_count == 0
    assert plan.conflict_count == 0

    apply_result = apply_workspace_sync(workspace, source_root, plan=plan)
    assert apply_result.imported_paths == ("notes/alpha.md",)
    assert apply_result.path_record_ids["notes/alpha.md"]
    assert apply_result.source_entry_id is not None

    repeat_plan = scan_workspace_sync(workspace, source_root)
    assert repeat_plan.deltas == ()
    assert repeat_plan.unchanged_count == 1

    status = workspace_sync_status(workspace, source_root, plan=repeat_plan)
    assert status.tracked_count == 1
    assert status.fresh_count == 1
    assert status.pending_delta_count == 0
    assert status.source_entry_id is not None

    assert plan == type(plan).from_dict(plan.to_dict())
    assert apply_result == type(apply_result).from_dict(apply_result.to_dict())
    assert status == type(status).from_dict(status.to_dict())


def test_workspace_live_sync_detects_modify_delete_and_rename(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    source_root = tmp_path / "notes"
    _init_workspace(workspace)
    alpha_path = _write_markdown(
        source_root, "notes/alpha.md", "# Alpha\n\nAlpha body\n"
    )

    apply_workspace_sync(workspace, source_root)

    alpha_path.write_text("# Alpha\n\nUpdated body\n", encoding="utf-8")
    modified_plan = scan_workspace_sync(workspace, source_root)
    assert [delta.kind for delta in modified_plan.deltas] == ["modified"]
    assert modified_plan.deltas[0].relative_path == "notes/alpha.md"

    apply_workspace_sync(workspace, source_root, plan=modified_plan)
    renamed_path = source_root / "notes" / "beta.md"
    alpha_path.rename(renamed_path)
    renamed_plan = scan_workspace_sync(workspace, source_root)
    assert [delta.kind for delta in renamed_plan.deltas] == ["renamed"]
    assert renamed_plan.deltas[0].previous_relative_path == "notes/alpha.md"
    assert renamed_plan.deltas[0].relative_path == "notes/beta.md"

    apply_workspace_sync(workspace, source_root, plan=renamed_plan)
    renamed_path.unlink()
    deleted_plan = scan_workspace_sync(workspace, source_root)
    assert [delta.kind for delta in deleted_plan.deltas] == ["deleted"]
    assert deleted_plan.deltas[0].relative_path == "notes/beta.md"

    _write_markdown(source_root, "notes/beta.md", "# Alpha\n\nUpdated body\n")
    restored_plan = scan_workspace_sync(workspace, source_root)
    assert restored_plan.deltas == ()


def test_workspace_live_sync_detects_db_only_conflict(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    source_root = tmp_path / "notes"
    _init_workspace(workspace)
    _write_markdown(source_root, "notes/alpha.md", "# Alpha\n\nAlpha body\n")

    applied = apply_workspace_sync(workspace, source_root)
    store = open_workspace_store(workspace)
    record = store.get_record(applied.path_record_ids["notes/alpha.md"])
    assert record is not None
    vault_meta = dict(record.meta.get("vault") or {})
    store.put_record(
        replace(
            record,
            updated_at="2026-06-19T00:00:00+00:00",
            meta={
                **dict(record.meta),
                "vault": {
                    **vault_meta,
                    "content_hash": "db-only-change",
                },
            },
        )
    )
    conflict_plan = scan_workspace_sync(workspace, source_root)
    assert [delta.kind for delta in conflict_plan.deltas] == ["conflict"]
    assert conflict_plan.deltas[0].conflict is not None
    assert conflict_plan.deltas[0].conflict.kind == "record_changed"


def test_workspace_file_primary_helpers_keep_disk_visible(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    source_root = tmp_path / "notes"
    _init_workspace(workspace)

    put_result = workspace_file_primary_note_put(
        workspace,
        source_root,
        options=WorkspaceFilePrimaryNoteOptions(
            note_key="welcome",
            title="Welcome",
            body="Hello from file-primary mode.",
            tags=("intro",),
        ),
    )
    note_path = source_root / put_result.relative_path
    assert note_path.exists()
    assert "Hello from file-primary mode." in note_path.read_text(encoding="utf-8")

    store = open_workspace_store(workspace)
    synced_record = store.get_record(put_result.record_id)
    assert synced_record is not None
    assert synced_record.meta["human_note"]["note_key"] == "welcome"
    assert synced_record.meta["human_note"]["archived"] is False

    legacy = workspace_note_put(
        workspace,
        note_key="legacy",
        title="Legacy",
        body="Legacy DB-only note",
        tags=("legacy",),
    )
    materialized = materialize_workspace_note(
        workspace,
        source_root,
        record_id=legacy.id,
    )
    legacy_path = source_root / materialized.relative_path
    assert legacy_path.exists()
    archived = store.get_record(legacy.id)
    assert archived is not None
    assert archived.meta["human_note"]["archived"] is True
    materialized_record = store.get_record(materialized.record_id)
    assert materialized_record is not None
    assert materialized_record.meta["human_note"]["archived"] is False
    assert scan_workspace_sync(workspace, source_root).deltas == ()


def test_workspace_poll_cycles_are_bounded_and_stdlib_only(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    source_root = tmp_path / "notes"
    _init_workspace(workspace)
    _write_markdown(source_root, "notes/alpha.md", "# Alpha\n\nAlpha body\n")

    cycles = poll_workspace_sync(
        workspace,
        source_root,
        cycles=2,
        interval_seconds=0.0,
        apply_changes=True,
    )
    assert len(cycles) == 2
    assert cycles[0].apply_result is not None
    assert cycles[1].plan.deltas == ()
    assert cycles[1].status.pending_delta_count == 0
    assert cycles[0] == type(cycles[0]).from_dict(cycles[0].to_dict())

    source = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "sophiagraph"
        / "workspace_sync.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name)
    forbidden = {"watchdog", "watchfiles", "threading", "subprocess", "asyncio"}
    leaked = imports & forbidden
    assert not leaked, (
        f"workspace sync pulled forbidden watcher/runtime imports: {sorted(leaked)}"
    )


def test_workspace_live_sync_cli_commands(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    source_root = tmp_path / "notes"
    _write_markdown(source_root, "notes/alpha.md", "# Alpha\n\nAlpha body\n")

    subprocess.run(
        [
            sys.executable,
            "-m",
            "sophiagraph",
            "workspace-init",
            str(workspace),
            "--scope",
            "agent:workspace-sync",
            "--agent-id",
            "workspace-sync",
            "--graph-id",
            "main",
            "--label",
            "workspace-sync",
            "--json",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    plan = subprocess.run(
        [
            sys.executable,
            "-m",
            "sophiagraph",
            "workspace-sync-plan",
            str(workspace),
            str(source_root),
            "--json",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(plan.stdout)["deltas"][0]["kind"] == "created"

    apply_result = subprocess.run(
        [
            sys.executable,
            "-m",
            "sophiagraph",
            "workspace-sync-apply",
            str(workspace),
            str(source_root),
            "--json",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(apply_result.stdout)["imported_paths"] == ["notes/alpha.md"]

    status = subprocess.run(
        [
            sys.executable,
            "-m",
            "sophiagraph",
            "workspace-sync-status",
            str(workspace),
            str(source_root),
            "--json",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(status.stdout)["fresh_count"] == 1

    file_note = subprocess.run(
        [
            sys.executable,
            "-m",
            "sophiagraph",
            "workspace-file-note-put",
            str(workspace),
            str(source_root),
            "welcome",
            "--title",
            "Welcome",
            "--body",
            "Hello from the CLI.",
            "--json",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(file_note.stdout)["relative_path"] == "notes/welcome.md"

    legacy = subprocess.run(
        [
            sys.executable,
            "-m",
            "sophiagraph",
            "workspace-note-put",
            str(workspace),
            "legacy",
            "--title",
            "Legacy",
            "--body",
            "Legacy DB note",
            "--json",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    legacy_record_id = json.loads(legacy.stdout)["record_id"]

    materialized = subprocess.run(
        [
            sys.executable,
            "-m",
            "sophiagraph",
            "workspace-note-materialize",
            str(workspace),
            str(source_root),
            legacy_record_id,
            "--json",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(materialized.stdout)["relative_path"] == "notes/legacy.md"

    polled = subprocess.run(
        [
            sys.executable,
            "-m",
            "sophiagraph",
            "workspace-sync-poll",
            str(workspace),
            str(source_root),
            "--cycles",
            "1",
            "--json",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert len(json.loads(polled.stdout)) == 1
