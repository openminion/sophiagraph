"""Workspace revision history, diff, and restore preview helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol
from uuid import uuid4

from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.models import MemoryNamespace, OperatorActionRequired
from sophiagraph.models.change import SophiaGraphChangeEvent
from sophiagraph.storage.base import SophiaGraphStore
from sophiagraph.temporal import utc_now_iso
from sophiagraph.workspace_sync import WorkspaceFileDelta, WorkspaceSyncPlan

WorkspaceDiffKind = Literal["added", "modified", "removed", "unchanged"]


class WorkspaceHistoryStore(Protocol):
    """Store subset used to build workspace history from the changefeed."""

    def list_changes(
        self,
        *,
        since_cursor: int | None = None,
        limit: int | None = None,
        namespaces: list[MemoryNamespace] | None = None,
    ) -> list[SophiaGraphChangeEvent]: ...


@dataclass(frozen=True, slots=True)
class WorkspaceRevision:
    """One structural workspace revision derived from sync/changefeed data."""

    revision_id: str
    workspace_root: str
    namespace: MemoryNamespace
    created_at: str
    latest_cursor: int | None
    change_count: int
    file_deltas: tuple[WorkspaceFileDelta, ...] = ()
    object_ids: tuple[str, ...] = ()
    source: str = "changefeed"
    label: str = ""

    def __post_init__(self) -> None:
        if not self.revision_id:
            raise InvalidArgumentError("revision_id is required")
        if not self.workspace_root:
            raise InvalidArgumentError("workspace_root is required")
        if not isinstance(self.namespace, MemoryNamespace):
            raise InvalidArgumentError("namespace must be a MemoryNamespace")
        if not self.created_at:
            raise InvalidArgumentError("created_at is required")
        if self.change_count < 0:
            raise InvalidArgumentError("change_count must be non-negative")


@dataclass(frozen=True, slots=True)
class WorkspaceHistoryOptions:
    """Options for listing workspace revision history."""

    workspace_root: str
    namespace: MemoryNamespace
    since_cursor: int | None = None
    limit: int | None = None

    def __post_init__(self) -> None:
        if not self.workspace_root:
            raise InvalidArgumentError("workspace_root is required")
        if self.since_cursor is not None and self.since_cursor < 0:
            raise InvalidArgumentError("since_cursor must be non-negative")
        if self.limit is not None and self.limit <= 0:
            raise InvalidArgumentError("limit must be positive")


@dataclass(frozen=True, slots=True)
class WorkspaceDiffEntry:
    """One structural difference between two workspace revisions."""

    kind: WorkspaceDiffKind
    object_id: str
    object_type: str
    before_cursor: int | None = None
    after_cursor: int | None = None

    def __post_init__(self) -> None:
        if self.kind not in {"added", "modified", "removed", "unchanged"}:
            raise InvalidArgumentError(f"invalid diff kind: {self.kind!r}")
        if not self.object_id:
            raise InvalidArgumentError("object_id is required")
        if not self.object_type:
            raise InvalidArgumentError("object_type is required")


@dataclass(frozen=True, slots=True)
class WorkspaceDiffSummary:
    """Typed diff summary for revision preview surfaces."""

    before_revision_id: str
    after_revision_id: str
    entries: tuple[WorkspaceDiffEntry, ...]
    file_deltas: tuple[WorkspaceFileDelta, ...] = ()

    @property
    def changed_count(self) -> int:
        return sum(1 for entry in self.entries if entry.kind != "unchanged")


@dataclass(frozen=True, slots=True)
class WorkspaceRestorePlan:
    """Previewable restore plan for a workspace revision."""

    plan_id: str
    workspace_root: str
    target_revision_id: str
    namespace: MemoryNamespace
    created_at: str
    reason: str
    preview: WorkspaceDiffSummary | None = None
    operator_action_required: OperatorActionRequired | None = None
    backend_limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.plan_id:
            raise InvalidArgumentError("plan_id is required")
        if not self.workspace_root:
            raise InvalidArgumentError("workspace_root is required")
        if not self.target_revision_id:
            raise InvalidArgumentError("target_revision_id is required")
        if not self.reason:
            raise InvalidArgumentError("reason is required")


@dataclass(frozen=True, slots=True)
class WorkspaceRestoreResult:
    """Result of an explicit workspace restore attempt."""

    plan_id: str
    applied: bool
    restored_revision_id: str | None = None
    operator_action_required: OperatorActionRequired | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.plan_id:
            raise InvalidArgumentError("plan_id is required")


def capture_workspace_revision(
    *,
    workspace_root: str,
    namespace: MemoryNamespace,
    changes: list[SophiaGraphChangeEvent],
    sync_plan: WorkspaceSyncPlan | None = None,
    label: str = "",
) -> WorkspaceRevision:
    """Capture one revision summary from explicit change and sync inputs."""

    cursors = [event.cursor for event in changes if event.cursor is not None]
    object_ids = tuple(sorted({event.object_id for event in changes}))
    created_at = max((event.changed_at for event in changes), default=utc_now_iso())
    file_deltas = tuple(sync_plan.deltas) if sync_plan is not None else ()
    return WorkspaceRevision(
        revision_id=f"workspace-revision-{uuid4().hex}",
        workspace_root=workspace_root,
        namespace=namespace,
        created_at=created_at,
        latest_cursor=max(cursors) if cursors else None,
        change_count=len(changes),
        file_deltas=file_deltas,
        object_ids=object_ids,
        source="sync_plan+changefeed" if sync_plan is not None else "changefeed",
        label=label,
    )


def list_workspace_history(
    store: WorkspaceHistoryStore,
    options: WorkspaceHistoryOptions,
) -> list[WorkspaceRevision]:
    """Build deterministic one-change revisions from the existing changefeed."""

    changes = store.list_changes(
        since_cursor=options.since_cursor,
        limit=options.limit,
        namespaces=[options.namespace],
    )
    revisions = [
        capture_workspace_revision(
            workspace_root=options.workspace_root,
            namespace=options.namespace,
            changes=[event],
        )
        for event in changes
    ]
    return sorted(
        revisions,
        key=lambda revision: (revision.latest_cursor or 0, revision.revision_id),
    )


def diff_workspace_revisions(
    before: WorkspaceRevision,
    after: WorkspaceRevision,
) -> WorkspaceDiffSummary:
    """Compare two revisions by structural object and file-delta identity."""

    before_ids = set(before.object_ids)
    after_ids = set(after.object_ids)
    entries: list[WorkspaceDiffEntry] = []
    for object_id in sorted(before_ids | after_ids):
        if object_id in before_ids and object_id in after_ids:
            kind: WorkspaceDiffKind = "unchanged"
        elif object_id in after_ids:
            kind = "added"
        else:
            kind = "removed"
        entries.append(
            WorkspaceDiffEntry(
                kind=kind,
                object_id=object_id,
                object_type="changefeed_object",
                before_cursor=before.latest_cursor,
                after_cursor=after.latest_cursor,
            )
        )
    return WorkspaceDiffSummary(
        before_revision_id=before.revision_id,
        after_revision_id=after.revision_id,
        entries=tuple(entries),
        file_deltas=after.file_deltas,
    )


def build_workspace_restore_plan(
    *,
    workspace_root: str,
    target_revision: WorkspaceRevision,
    current_revision: WorkspaceRevision | None = None,
    reason: str,
    backend_limitations: tuple[str, ...] = (),
) -> WorkspaceRestorePlan:
    """Build a preview-only restore plan; callers own actual mutation."""

    preview = (
        None
        if current_revision is None
        else diff_workspace_revisions(current_revision, target_revision)
    )
    action = None
    if backend_limitations:
        action = OperatorActionRequired(
            backend_name="workspace",
            action="restore_backend_state",
            command="use host-managed backup restore for listed backends",
            reason="some backends cannot be restored by the package-level preview",
        )
    return WorkspaceRestorePlan(
        plan_id=f"workspace-restore-{uuid4().hex}",
        workspace_root=workspace_root,
        target_revision_id=target_revision.revision_id,
        namespace=target_revision.namespace,
        created_at=utc_now_iso(),
        reason=reason,
        preview=preview,
        operator_action_required=action,
        backend_limitations=backend_limitations,
    )


def apply_workspace_restore_plan(
    store: SophiaGraphStore,
    plan: WorkspaceRestorePlan,
    *,
    operator_confirmed: bool = False,
) -> WorkspaceRestoreResult:
    """Apply package-safe restore bookkeeping without inventing backup logic."""

    if plan.operator_action_required is not None and not operator_confirmed:
        return WorkspaceRestoreResult(
            plan_id=plan.plan_id,
            applied=False,
            operator_action_required=plan.operator_action_required,
            details={"backend_limitations": list(plan.backend_limitations)},
        )
    snapshot = store.get_retention_snapshot(
        name=plan.target_revision_id,
        namespace=plan.namespace,
    )
    if snapshot is None:
        return WorkspaceRestoreResult(
            plan_id=plan.plan_id,
            applied=False,
            restored_revision_id=None,
            details={"reason": "no matching retention snapshot; host restore required"},
        )
    return WorkspaceRestoreResult(
        plan_id=plan.plan_id,
        applied=True,
        restored_revision_id=plan.target_revision_id,
        details={"snapshot_id": snapshot.snapshot_id},
    )


__all__ = [
    "WorkspaceDiffEntry",
    "WorkspaceDiffKind",
    "WorkspaceDiffSummary",
    "WorkspaceHistoryOptions",
    "WorkspaceHistoryStore",
    "WorkspaceRestorePlan",
    "WorkspaceRestoreResult",
    "WorkspaceRevision",
    "apply_workspace_restore_plan",
    "build_workspace_restore_plan",
    "capture_workspace_revision",
    "diff_workspace_revisions",
    "list_workspace_history",
]
