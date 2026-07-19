"""In-memory workbench action journal support."""

from __future__ import annotations

from dataclasses import replace

from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.models import (
    MemoryNamespace,
    WorkbenchActionJournalEntry,
    WorkbenchActionResult,
)


class MemoryWorkbenchActionMixin:
    @property
    def _workbench_actions(self) -> dict[str, WorkbenchActionJournalEntry]:
        return self.__dict__.setdefault("_workbench_actions_state", {})

    def reserve_workbench_action(
        self,
        entry: WorkbenchActionJournalEntry,
    ) -> WorkbenchActionJournalEntry:
        existing = self._workbench_actions.get(entry.action_id)
        if existing is not None:
            return existing
        self._workbench_actions[entry.action_id] = entry
        return entry

    def get_workbench_action(
        self,
        action_id: str,
        *,
        scope: str,
        namespace: MemoryNamespace,
    ) -> WorkbenchActionJournalEntry | None:
        entry = self._workbench_actions.get(action_id)
        if entry is None or entry.scope != scope or entry.namespace != namespace:
            return None
        return entry

    def mark_workbench_action_in_progress(
        self,
        action_id: str,
        *,
        fencing_token: int,
        started_at: str,
    ) -> WorkbenchActionJournalEntry:
        entry = self._workbench_actions.get(action_id)
        if entry is None:
            raise InvalidArgumentError(f"unknown action_id: {action_id}")
        if entry.fencing_token != fencing_token:
            raise InvalidArgumentError("action fencing token mismatch")
        if entry.lifecycle == "terminal":
            return entry
        updated = replace(
            entry,
            lifecycle="in_progress",
            started_at=started_at,
            updated_at=started_at,
        )
        self._workbench_actions[action_id] = updated
        return updated

    def finalize_workbench_action(
        self,
        action_id: str,
        *,
        fencing_token: int,
        result: WorkbenchActionResult,
        completed_at: str,
    ) -> WorkbenchActionJournalEntry:
        entry = self._workbench_actions.get(action_id)
        if entry is None:
            raise InvalidArgumentError(f"unknown action_id: {action_id}")
        if entry.fencing_token != fencing_token:
            raise InvalidArgumentError("action fencing token mismatch")
        updated = replace(
            entry,
            lifecycle="terminal",
            completed_at=completed_at,
            updated_at=completed_at,
            result=result,
            recovery_required=result.recovery_required,
        )
        self._workbench_actions[action_id] = updated
        return updated

    def list_workbench_actions(
        self,
        *,
        scope: str | None = None,
        namespace: MemoryNamespace | None = None,
        lifecycle: str | None = None,
        limit: int | None = None,
    ) -> list[WorkbenchActionJournalEntry]:
        entries = list(self._workbench_actions.values())
        if scope is not None:
            entries = [entry for entry in entries if entry.scope == scope]
        if namespace is not None:
            entries = [entry for entry in entries if entry.namespace == namespace]
        if lifecycle is not None:
            entries = [entry for entry in entries if entry.lifecycle == lifecycle]
        entries.sort(
            key=lambda entry: (entry.updated_at, entry.action_id), reverse=True
        )
        return entries[: int(limit)] if limit is not None else entries

    def prune_workbench_actions(
        self,
        *,
        completed_before: str,
    ) -> int:
        removable = [
            action_id
            for action_id, entry in self._workbench_actions.items()
            if (
                entry.lifecycle == "terminal"
                and not entry.recovery_required
                and entry.completed_at
                and entry.completed_at < completed_before
            )
        ]
        for action_id in removable:
            del self._workbench_actions[action_id]
        return len(removable)


__all__ = ["MemoryWorkbenchActionMixin"]
