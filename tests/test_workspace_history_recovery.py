from __future__ import annotations

from sophiagraph import (
    MemoryNamespace,
    MemoryRecord,
    SophiaGraphMemoryStore,
    WorkspaceFileDelta,
    WorkspaceSyncPlan,
    apply_workspace_restore_plan,
    build_workspace_restore_plan,
    capture_workspace_revision,
    diff_workspace_revisions,
    list_workspace_history,
)
from sophiagraph.models import BackupDescriptor, BackupManifestEntry, RetentionSnapshot
from sophiagraph.workspace_history import WorkspaceHistoryOptions


def _namespace() -> MemoryNamespace:
    return MemoryNamespace(agent_id="history", graph_id="main")


def _record(record_id: str, title: str) -> MemoryRecord:
    return MemoryRecord(
        id=record_id,
        scope="agent:history",
        type="fact",
        content={"title": title},
        created_at="2026-06-23T10:00:00+00:00",
        updated_at="2026-06-23T10:00:00+00:00",
        title=title,
        namespace=_namespace(),
    )


def test_workspace_history_lists_changefeed_revisions() -> None:
    store = SophiaGraphMemoryStore()
    store.put_record(_record("rec-1", "First"))
    store.put_record(_record("rec-2", "Second"))

    history = list_workspace_history(
        store,
        WorkspaceHistoryOptions(
            workspace_root="/workspace",
            namespace=_namespace(),
        ),
    )

    assert [revision.change_count for revision in history] == [1, 1]
    assert [revision.object_ids for revision in history] == [("rec-1",), ("rec-2",)]
    assert history[0].latest_cursor == 1
    assert history[1].latest_cursor == 2


def test_workspace_revision_diff_is_structural() -> None:
    ns = _namespace()
    before = capture_workspace_revision(
        workspace_root="/workspace",
        namespace=ns,
        changes=[],
        sync_plan=WorkspaceSyncPlan(
            workspace_root="/workspace",
            source_root="/source",
            namespace=ns,
            observed_at="2026-06-23T10:00:00+00:00",
            deltas=(
                WorkspaceFileDelta(
                    kind="modified",
                    relative_path="notes/a.md",
                    source_id="workspace-file:notes/a.md",
                    content_hash="a",
                ),
            ),
        ),
    )
    after = capture_workspace_revision(
        workspace_root="/workspace",
        namespace=ns,
        changes=[],
        sync_plan=WorkspaceSyncPlan(
            workspace_root="/workspace",
            source_root="/source",
            namespace=ns,
            observed_at="2026-06-23T10:01:00+00:00",
            deltas=(
                WorkspaceFileDelta(
                    kind="created",
                    relative_path="notes/b.md",
                    source_id="workspace-file:notes/b.md",
                    content_hash="b",
                ),
            ),
        ),
    )

    diff = diff_workspace_revisions(before, after)

    assert diff.before_revision_id == before.revision_id
    assert diff.after_revision_id == after.revision_id
    assert [delta.relative_path for delta in diff.file_deltas] == ["notes/b.md"]


def test_restore_plan_surfaces_backend_operator_requirements() -> None:
    target = capture_workspace_revision(
        workspace_root="/workspace",
        namespace=_namespace(),
        changes=[],
        label="known-good",
    )

    plan = build_workspace_restore_plan(
        workspace_root="/workspace",
        target_revision=target,
        reason="operator requested rollback",
        backend_limitations=("neo4j restore delegated to host",),
    )
    result = apply_workspace_restore_plan(
        SophiaGraphMemoryStore(),
        plan,
        operator_confirmed=False,
    )

    assert result.applied is False
    assert result.operator_action_required is not None
    assert result.operator_action_required.backend_name == "workspace"


def test_restore_apply_reuses_retention_snapshot_owner() -> None:
    store = SophiaGraphMemoryStore()
    ns = _namespace()
    target = capture_workspace_revision(
        workspace_root="/workspace",
        namespace=ns,
        changes=[],
    )
    descriptor = BackupDescriptor(
        backup_id="backup-1",
        kind="physical_memory",
        backend_name="memory",
        created_at="2026-06-23T10:00:00+00:00",
        target_path="memory://snapshot",
        manifest_entries=[
            BackupManifestEntry(
                table_group="records",
                row_count=1,
                sha256="b" * 64,
                byte_size=10,
            )
        ],
    )
    store.put_retention_snapshot(
        RetentionSnapshot(
            snapshot_id="snapshot-1",
            name=target.revision_id,
            namespace=ns,
            created_at="2026-06-23T10:00:00+00:00",
            as_of_cursor=target.latest_cursor,
            backup_descriptor=descriptor,
        )
    )
    plan = build_workspace_restore_plan(
        workspace_root="/workspace",
        target_revision=target,
        reason="restore tested snapshot",
    )

    result = apply_workspace_restore_plan(store, plan)

    assert result.applied is True
    assert result.restored_revision_id == target.revision_id
    assert result.details["snapshot_id"] == "snapshot-1"
