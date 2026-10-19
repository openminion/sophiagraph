from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest

from sophiagraph import ArtifactRef, MemoryCandidate, MemoryNamespace, MemoryRecord
from sophiagraph.models import ProjectionTarget
from sophiagraph.server.__main__ import main
from sophiagraph.storage import SophiaGraphSqliteStore
from sophiagraph.workbench import WorkbenchActionKind, WorkbenchActionRequest
from sophiagraph.workbench_actions import execute_workbench_action
from sophiagraph.models import WorkbenchActionExecutionContext

NOW = "2026-07-17T10:00:00+00:00"


def _namespace() -> MemoryNamespace:
    return MemoryNamespace(agent_id="local", graph_id="main")


def _sqlite_path(tmp_path: Path) -> Path:
    return tmp_path / "operations.sqlite3"


def _record(record_id: str) -> MemoryRecord:
    return MemoryRecord(
        id=record_id,
        scope="agent:local",
        type="fact",
        content={"text": "operation CLI record"},
        created_at=NOW,
        updated_at=NOW,
        namespace=_namespace(),
    )


def _candidate(candidate_id: str) -> MemoryCandidate:
    return MemoryCandidate(
        candidate_id=candidate_id,
        session_id="session-cli",
        proposed_scope="agent:local",
        type="fact",
        title="CLI candidate",
        content={"text": "CLI action candidate"},
        evidence_refs=(
            ArtifactRef(
                ref="artifact://cli-source",
                mime="text/plain",
                sha256="a" * 64,
                size_bytes=12,
            ),
        ),
        status=cast(str, "proposed"),
        namespace=_namespace(),
        source_class="user_input",
        created_at=NOW,
        updated_at=NOW,
    )


def _read_stdout(capsys) -> dict:
    return json.loads(capsys.readouterr().out)


def test_projection_one_shot_cli_runs_and_reports_status(tmp_path, capsys) -> None:
    sqlite_path = _sqlite_path(tmp_path)
    store = SophiaGraphSqliteStore(sqlite_path)
    store.put_record(_record("rec-cli"))
    store.register_projection_target(
        ProjectionTarget("graph-cli", "graph", "fake", namespace=_namespace())
    )

    run_code = main(
        [
            "projection-run",
            "--sqlite-path",
            str(sqlite_path),
            "--target-id",
            "graph-cli",
            "--now",
            NOW,
        ]
    )
    run_payload = _read_stdout(capsys)
    status_code = main(
        [
            "projection-status",
            "--sqlite-path",
            str(sqlite_path),
            "--target-id",
            "graph-cli",
            "--now",
            NOW,
        ]
    )
    status_payload = _read_stdout(capsys)

    assert run_code == 0
    assert run_payload["ok"] is True
    assert run_payload["projection"]["applied"] == 1
    assert status_code == 0
    assert status_payload["health"]["lag"] == 0


def test_projection_failure_release_requires_explicit_authorization(
    tmp_path,
    capsys,
) -> None:
    sqlite_path = _sqlite_path(tmp_path)
    store = SophiaGraphSqliteStore(sqlite_path)
    store.register_projection_target(
        ProjectionTarget("graph-cli", "graph", "fake", namespace=_namespace())
    )

    code = main(
        [
            "projection-release-failure",
            "--sqlite-path",
            str(sqlite_path),
            "--target-id",
            "graph-cli",
            "--event-id",
            "event-1",
        ]
    )
    payload = _read_stdout(capsys)

    assert code == 2
    assert payload["ok"] is False
    assert payload["error"]["reason"] == (
        "projection failure release requires authorization"
    )


def test_journal_one_shot_cli_reports_and_prunes_scoped_entries(
    tmp_path,
    capsys,
) -> None:
    sqlite_path = _sqlite_path(tmp_path)
    store = SophiaGraphSqliteStore(sqlite_path)
    store.put_candidate(_candidate("cand-cli"))
    execute_workbench_action(
        store,
        WorkbenchActionRequest(
            action=cast(WorkbenchActionKind, "approve_candidate"),
            target_id="candidate:cand-cli",
            actor_id="local-operator",
            workspace_id="workspace:local",
            payload_kind="candidate",
            payload={},
        ),
        WorkbenchActionExecutionContext(
            action_id="action-cli",
            request_id="request-cli",
            principal_id="local-operator",
            workspace_id="workspace:local",
            scope="agent:local",
            namespace=_namespace(),
        ),
    )

    status_code = main(
        [
            "journal-status",
            "--sqlite-path",
            str(sqlite_path),
            "--scope",
            "agent:local",
            "--action-id",
            "action-cli",
        ]
    )
    status_payload = _read_stdout(capsys)
    prune_code = main(
        [
            "journal-prune",
            "--sqlite-path",
            str(sqlite_path),
            "--completed-before",
            "9999-12-31T00:00:00+00:00",
        ]
    )
    prune_payload = _read_stdout(capsys)
    missing_code = main(
        [
            "journal-status",
            "--sqlite-path",
            str(sqlite_path),
            "--scope",
            "agent:local",
            "--action-id",
            "action-cli",
        ]
    )
    missing_payload = _read_stdout(capsys)

    assert status_code == 0
    assert status_payload["entry"]["action_id"] == "action-cli"
    assert status_payload["entry"]["result"]["outcome"] == "applied"
    assert prune_code == 0
    assert prune_payload["pruned"] == 1
    assert missing_code == 1
    assert missing_payload["entry"] is None


@pytest.mark.parametrize(
    "command_args",
    (
        ("projection-run", "--target-id", "graph-cli"),
        ("projection-status", "--target-id", "graph-cli"),
        (
            "projection-release-failure",
            "--target-id",
            "graph-cli",
            "--event-id",
            "event-1",
            "--authorized",
        ),
        ("projection-reconcile", "--target-id", "graph-cli"),
        ("journal-status", "--action-id", "action-cli"),
        (
            "journal-prune",
            "--completed-before",
            "9999-12-31T00:00:00+00:00",
        ),
    ),
)
def test_one_shot_cli_reports_sqlite_path_failures_as_json(
    tmp_path,
    capsys,
    command_args,
) -> None:
    blocked_parent = tmp_path / "not-a-directory"
    blocked_parent.write_text("blocked", encoding="utf-8")
    sqlite_path = blocked_parent / "sophiagraph.sqlite3"

    code = main([*command_args, "--sqlite-path", str(sqlite_path)])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert code == 2
    assert payload == {
        "error": {"reason": f"unable to open sqlite backend at {str(sqlite_path)!r}"},
        "ok": False,
    }
    assert captured.err == ""


@pytest.mark.parametrize("command", ("serve-stdio", "serve-http"))
def test_server_startup_reports_sqlite_path_failures_without_tracebacks(
    tmp_path,
    capsys,
    command,
) -> None:
    blocked_parent = tmp_path / "not-a-directory"
    blocked_parent.write_text("blocked", encoding="utf-8")
    sqlite_path = blocked_parent / "sophiagraph.sqlite3"

    with pytest.raises(SystemExit) as excinfo:
        main([command, "--backend", "sqlite", "--sqlite-path", str(sqlite_path)])
    captured = capsys.readouterr()

    assert excinfo.value.code == 2
    assert "unable to open sqlite backend" in captured.err
    assert "Traceback" not in captured.err
    assert captured.out == ""
