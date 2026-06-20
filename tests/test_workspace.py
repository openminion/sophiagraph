from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from sophiagraph import (
    MemoryNamespace,
    apply_workspace_import,
    build_workspace_workbench,
    initialize_workspace,
    load_workspace_status,
    plan_workspace_import,
    render_workspace_workbench,
    workspace_note_put,
)


def _ns() -> MemoryNamespace:
    return MemoryNamespace(agent_id="workspace", graph_id="main")


def _source_tree(root: Path) -> Path:
    notes = root / "notes"
    notes.mkdir(parents=True)
    (notes / "alpha.md").write_text("# Alpha\n\nAlpha body\n", encoding="utf-8")
    return root


def test_workspace_init_persists_metadata_and_status(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    status = initialize_workspace(
        workspace,
        scope="agent:workspace",
        namespace=_ns(),
        label="local-wisdom",
        vault_id="vault-main",
    )

    assert status.metadata.label == "local-wisdom"
    assert status.import_profile.vault_id == "vault-main"
    assert status.record_count == 0
    assert status.db_path.endswith("sophiagraph.sqlite3")
    assert "." not in status.metadata.created_at

    reloaded = load_workspace_status(workspace)
    assert reloaded.metadata.namespace == _ns()
    assert reloaded.workspace_root == str(workspace.resolve())


def test_workspace_note_put_import_and_workbench_flow(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    initialize_workspace(
        workspace,
        scope="agent:workspace",
        namespace=_ns(),
        label="local-wisdom",
        vault_id="vault-main",
    )
    workspace_note_put(
        workspace,
        note_key="welcome",
        title="Welcome",
        body="Hello from the workspace",
        tags=("intro",),
    )

    source_root = _source_tree(tmp_path / "vault")
    plan = plan_workspace_import(workspace, source_root)
    assert plan.created_count == 1
    assert [item.path for item in plan.items] == ["notes/alpha.md"]

    result = apply_workspace_import(workspace, source_root)
    assert result.created_count == 1
    status = load_workspace_status(workspace)
    assert status.record_count == 2
    assert status.note_count == 1

    packet = build_workspace_workbench(workspace, source_root=source_root)
    html = render_workspace_workbench(workspace, source_root=source_root)
    assert packet.workspace.active_count == 1
    assert packet.import_plan is not None
    assert "Human Workbench" in html
    assert "Welcome" in html
    assert "Import Plan" in html


def test_workspace_cli_commands(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    source_root = _source_tree(tmp_path / "vault")

    init = subprocess.run(
        [
            sys.executable,
            "-m",
            "sophiagraph",
            "workspace-init",
            str(workspace),
            "--scope",
            "agent:workspace",
            "--agent-id",
            "workspace",
            "--graph-id",
            "main",
            "--label",
            "local-wisdom",
            "--json",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    init_payload = json.loads(init.stdout)
    assert init_payload["metadata"]["label"] == "local-wisdom"

    put = subprocess.run(
        [
            sys.executable,
            "-m",
            "sophiagraph",
            "workspace-note-put",
            str(workspace),
            "welcome",
            "--title",
            "Welcome",
            "--body",
            "Hello from cli",
            "--json",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(put.stdout)["title"] == "Welcome"

    plan = subprocess.run(
        [
            sys.executable,
            "-m",
            "sophiagraph",
            "workspace-import-plan",
            str(workspace),
            str(source_root),
            "--json",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(plan.stdout)["created_count"] == 1

    apply = subprocess.run(
        [
            sys.executable,
            "-m",
            "sophiagraph",
            "workspace-import-apply",
            str(workspace),
            str(source_root),
            "--json",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(apply.stdout)["manifest_file_count"] == 1

    status = subprocess.run(
        [
            sys.executable,
            "-m",
            "sophiagraph",
            "workspace-status",
            str(workspace),
            "--json",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(status.stdout)["record_count"] == 2

    workbench = subprocess.run(
        [
            sys.executable,
            "-m",
            "sophiagraph",
            "workspace-workbench",
            str(workspace),
            "--source-root",
            str(source_root),
            "--json",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(workbench.stdout)["workspace"]["active_count"] == 1
