"""Conflict-preserving collaborative merge contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol


@dataclass(frozen=True, slots=True)
class MergeConflict:
    field: str
    base_value: str | None
    local_value: str | None
    remote_value: str | None
    reason: str = "concurrent_edit"


@dataclass(frozen=True, slots=True)
class MergeResult:
    values: Mapping[str, str]
    conflicts: tuple[MergeConflict, ...]

    @property
    def clean(self) -> bool:
        return not self.conflicts


class CollaborativeMergeAdapter(Protocol):
    def merge(
        self,
        *,
        base: Mapping[str, str],
        local: Mapping[str, str],
        remote: Mapping[str, str],
    ) -> MergeResult: ...


class ConservativeThreeWayMergeAdapter:
    """Merge independent field edits and preserve concurrent edits as conflicts."""

    def merge(
        self,
        *,
        base: Mapping[str, str],
        local: Mapping[str, str],
        remote: Mapping[str, str],
    ) -> MergeResult:
        values: dict[str, str] = {}
        conflicts: list[MergeConflict] = []
        for field in sorted(set(base) | set(local) | set(remote)):
            base_value = base.get(field)
            local_value = local.get(field)
            remote_value = remote.get(field)
            if local_value == remote_value:
                selected = local_value
            elif local_value == base_value:
                selected = remote_value
            elif remote_value == base_value:
                selected = local_value
            else:
                selected = base_value
                conflicts.append(
                    MergeConflict(
                        field=field,
                        base_value=base_value,
                        local_value=local_value,
                        remote_value=remote_value,
                    )
                )
            if selected is not None:
                values[field] = selected
        return MergeResult(values=values, conflicts=tuple(conflicts))


__all__ = [
    "CollaborativeMergeAdapter",
    "ConservativeThreeWayMergeAdapter",
    "MergeConflict",
    "MergeResult",
]
