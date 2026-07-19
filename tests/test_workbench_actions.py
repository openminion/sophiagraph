from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest

from sophiagraph import (
    ArtifactRef,
    MemoryCandidate,
    MemoryNamespace,
    SophiaGraphMemoryStore,
    SophiaGraphSqliteStore,
)
from sophiagraph.workbench import WorkbenchActionRequest
from sophiagraph.workbench import WorkbenchActionKind
from sophiagraph.workbench_actions import (
    WorkbenchActionCrash,
    execute_workbench_action,
    preview_workbench_execution,
    prune_workbench_action_journal,
    workbench_action_status,
)
from sophiagraph.models import WorkbenchActionExecutionContext
from sophiagraph.workspace import initialize_workspace


@pytest.fixture(params=["memory", "sqlite"])
def store(request, tmp_path: Path):
    if request.param == "memory":
        return SophiaGraphMemoryStore()
    return SophiaGraphSqliteStore(tmp_path / "actions.sqlite3")


def _namespace() -> MemoryNamespace:
    return MemoryNamespace(agent_id="codex", graph_id="main")


def _context(
    action_id: str = "action-1",
    *,
    expected_updated_at: str | None = None,
    workspace_root: Path | None = None,
    source_root: Path | None = None,
) -> WorkbenchActionExecutionContext:
    return WorkbenchActionExecutionContext(
        action_id=action_id,
        request_id=f"request:{action_id}",
        principal_id="local-operator",
        workspace_id="workspace:local",
        scope="agent:codex",
        namespace=_namespace(),
        expected_updated_at=expected_updated_at,
        workspace_root=str(workspace_root or ""),
        source_root=str(source_root or ""),
    )


def _request(
    action: str,
    target_id: str,
    *,
    payload: dict[str, object] | None = None,
) -> WorkbenchActionRequest:
    return WorkbenchActionRequest(
        action=cast(WorkbenchActionKind, action),
        target_id=target_id,
        actor_id="local-operator",
        workspace_id="workspace:local",
        payload_kind="candidate",
        payload=dict(payload or {}),
    )


def _artifact(ref: str = "artifact://source-1") -> ArtifactRef:
    return ArtifactRef(ref=ref, mime="text/plain", sha256="a" * 64, size_bytes=12)


def _candidate(candidate_id: str, *, status: str = "proposed") -> MemoryCandidate:
    return MemoryCandidate(
        candidate_id=candidate_id,
        session_id="session-1",
        proposed_scope="agent:codex",
        type="fact",
        title="Candidate Fact",
        content={"text": "explicit fact candidate"},
        evidence_refs=[_artifact()],
        status=cast(str, status),
        namespace=_namespace(),
        source_class="user_input",
        created_at="2026-07-17T10:00:00+00:00",
        updated_at="2026-07-17T10:00:00+00:00",
    )


class _TelemetrySink:
    def __init__(self) -> None:
        self.events = []

    def record(self, event) -> None:
        self.events.append(event)


def test_candidate_review_action_applies_once_and_replays(store) -> None:
    store.put_candidate(_candidate("cand-1"))
    request = _request(
        "approve_candidate",
        "candidate:cand-1",
        payload={"expected_updated_at": "2026-07-17T10:00:00+00:00"},
    )
    context = _context("approve-cand-1")

    first = execute_workbench_action(store, request, context)
    second = execute_workbench_action(store, request, context)

    assert first.outcome == "applied"
    assert first.audit_refs[0] == "action_journal:approve-cand-1"
    assert second.to_dict() == first.to_dict()
    assert store.get_candidate("cand-1").status == "approved"
    entries = store.list_workbench_actions(scope="agent:codex", namespace=_namespace())
    assert entries[0].lifecycle == "terminal"
    assert entries[0].result is not None


def test_action_telemetry_uses_bounded_labels(store) -> None:
    store.put_candidate(_candidate("cand-telemetry"))
    sink = _TelemetrySink()

    execute_workbench_action(
        store,
        _request("approve_candidate", "candidate:cand-telemetry"),
        _context("telemetry-action"),
        telemetry_sink=sink,
    )

    attributes = sink.events[0].attributes
    assert attributes == {
        "operation": "workbench_action",
        "action_kind": "approve_candidate",
        "outcome": "applied",
        "reason_code": "applied",
        "target_kind": "approve_candidate",
    }
    assert "action_id" not in attributes
    assert "principal_id" not in attributes
    assert "target_id" not in attributes


def test_candidate_action_rejects_payload_impersonation(store) -> None:
    store.put_candidate(_candidate("cand-identity"))
    result = execute_workbench_action(
        store,
        _request(
            "approve_candidate",
            "candidate:cand-identity",
            payload={"principal_id": "mallory"},
        ),
        _context("identity-denied"),
    )

    assert result.outcome == "blocked"
    assert result.reason_code == "impersonation_denied"
    assert store.get_candidate("cand-identity").status == "proposed"


def test_candidate_action_rejects_stale_and_cross_scope(store) -> None:
    store.put_candidate(_candidate("cand-stale"))
    stale = execute_workbench_action(
        store,
        _request(
            "approve_candidate",
            "candidate:cand-stale",
            payload={"expected_updated_at": "2026-07-17T09:00:00+00:00"},
        ),
        _context("stale-cand"),
    )
    other_scope_context = WorkbenchActionExecutionContext(
        action_id="scope-denied",
        request_id="request:scope-denied",
        principal_id="local-operator",
        workspace_id="workspace:local",
        scope="agent:other",
        namespace=MemoryNamespace(agent_id="other", graph_id="main"),
    )
    denied = execute_workbench_action(
        store,
        _request("approve_candidate", "candidate:cand-stale"),
        other_scope_context,
    )

    assert stale.outcome == "conflict"
    assert stale.reason_code == "stale_precondition"
    assert denied.outcome == "blocked"
    assert denied.reason_code == "scope_denied"


def test_candidate_promotion_requires_approval_and_promotes_with_evidence(
    store,
) -> None:
    store.put_candidate(_candidate("cand-promote"))
    blocked = execute_workbench_action(
        store,
        _request("promote_candidate", "candidate:cand-promote"),
        _context("promote-blocked"),
    )
    execute_workbench_action(
        store,
        _request("approve_candidate", "candidate:cand-promote"),
        _context("approve-before-promote"),
    )
    promoted = execute_workbench_action(
        store,
        _request(
            "promote_candidate",
            "candidate:cand-promote",
            payload={"evidence_refs": ["artifact://source-1"]},
        ),
        _context("promote-applied"),
    )

    assert blocked.outcome == "blocked"
    assert blocked.reason_code == "candidate_not_approved"
    assert promoted.outcome == "applied"
    assert promoted.provider_payload["record_id"]
    assert store.get_candidate("cand-promote").status == "promoted"


def test_preview_and_host_required_actions_are_truthful(store) -> None:
    preview = preview_workbench_execution(
        _request("apply_repair", "repair-1"),
        _context("preview-repair"),
    )
    restore = execute_workbench_action(
        store,
        _request("restore_workspace", "snapshot-1"),
        _context("restore-blocked"),
    )
    review_only = execute_workbench_action(
        store,
        _request("propose_note_edit", "note-1"),
        _context("review-only"),
    )

    assert preview.outcome == "preview_only"
    assert restore.outcome == "blocked"
    assert restore.reason_code == "host_required"
    assert review_only.outcome == "unsupported"
    assert review_only.reason_code == "review_not_persisted"


def test_active_reservation_blocks_replay_without_double_apply(store) -> None:
    store.put_candidate(_candidate("cand-crash"))
    request = _request("approve_candidate", "candidate:cand-crash")
    context = _context("crash-action")

    with pytest.raises(WorkbenchActionCrash):
        execute_workbench_action(
            store,
            request,
            context,
            fault_after_side_effect=True,
        )
    retry = execute_workbench_action(store, request, context)

    assert store.get_candidate("cand-crash").status == "approved"
    assert retry.outcome == "blocked"
    assert retry.reason_code == "reservation_in_progress"


def test_journal_status_is_scoped_and_prune_preserves_recovery(store) -> None:
    store.put_candidate(_candidate("cand-journal"))
    context = _context("journal-action")
    result = execute_workbench_action(
        store,
        _request("reject_candidate", "candidate:cand-journal"),
        context,
    )
    entry = workbench_action_status(
        store,
        action_id="journal-action",
        scope="agent:codex",
        namespace=_namespace(),
    )
    denied = workbench_action_status(
        store,
        action_id="journal-action",
        scope="agent:other",
        namespace=MemoryNamespace(agent_id="other", graph_id="main"),
    )

    assert result.outcome == "applied"
    assert entry is not None
    assert denied is None
    assert (
        prune_workbench_action_journal(
            store,
            completed_before="2999-01-01T00:00:00+00:00",
        )
        == 1
    )


def test_sqlite_journal_survives_restart(tmp_path: Path) -> None:
    db_path = tmp_path / "persistent.sqlite3"
    store = SophiaGraphSqliteStore(db_path)
    store.put_candidate(_candidate("cand-sqlite"))
    result = execute_workbench_action(
        store,
        _request("approve_candidate", "candidate:cand-sqlite"),
        _context("sqlite-action"),
    )
    reopened = SophiaGraphSqliteStore(db_path)
    entry = workbench_action_status(
        reopened,
        action_id="sqlite-action",
        scope="agent:codex",
        namespace=_namespace(),
    )

    assert result.audit_durability == "durable"
    assert entry is not None
    assert entry.result is not None
    assert entry.result.outcome == "applied"


def test_save_note_action_writes_file_primary_workspace(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    source_root = tmp_path / "source"
    initialize_workspace(
        workspace_root,
        scope="agent:codex",
        namespace=_namespace(),
        overwrite=True,
    )
    request = _request(
        "save_note",
        "daily-note",
        payload={
            "note_key": "daily-note",
            "title": "Daily Note",
            "body": "Saved from the visual workbench.",
            "relative_path": "notes/daily-note.md",
            "tags": ["workbench"],
        },
    )

    result = execute_workbench_action(
        SophiaGraphSqliteStore(workspace_root / "store" / "sophiagraph.sqlite3"),
        request,
        _context(
            "save-note",
            workspace_root=workspace_root,
            source_root=source_root,
        ),
    )
    conflict = execute_workbench_action(
        SophiaGraphSqliteStore(workspace_root / "store" / "sophiagraph.sqlite3"),
        _request(
            "save_note",
            "daily-note-2",
            payload={
                "note_key": "daily-note-2",
                "title": "Daily Note",
                "body": "Overwrite without hash.",
                "relative_path": "notes/daily-note.md",
            },
        ),
        _context(
            "save-note-conflict",
            workspace_root=workspace_root,
            source_root=source_root,
        ),
    )

    assert result.outcome == "applied"
    assert (source_root / "notes" / "daily-note.md").exists()
    assert conflict.outcome == "conflict"
    assert conflict.reason_code == "stale_precondition"
