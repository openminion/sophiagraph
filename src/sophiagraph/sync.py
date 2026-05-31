"""Local-first sync and conflict primitives."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from typing import Any, Literal
from uuid import NAMESPACE_URL, uuid5

from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.models import MemoryNamespace

LocalSyncMode = Literal["file_primary", "db_as_index"]
SyncConflictKind = Literal[
    "file_changed",
    "record_changed",
    "both_changed",
    "missing_file",
    "missing_record",
]
SyncResultStatus = Literal[
    "unchanged",
    "file_changed",
    "record_changed",
    "conflict",
    "missing_file",
    "missing_record",
]
SyncConflictStatus = Literal["open", "resolved"]
SyncResolutionAction = Literal[
    "use_file", "use_record", "caller_patch", "mark_resolved"
]


def _namespace_key(namespace: MemoryNamespace) -> str:
    return "|".join(
        f"{key}={value}" for key, value in sorted(namespace.as_dict().items())
    )


def _stable_id(prefix: str, *parts: str) -> str:
    return f"{prefix}-{uuid5(NAMESPACE_URL, ':'.join(str(part) for part in parts))}"


def _require_hash(value: str | None, field_name: str) -> None:
    if value is not None and not str(value):
        raise InvalidArgumentError(f"{field_name} cannot be empty")


@dataclass(frozen=True, slots=True)
class LocalSyncRequest:
    mode: LocalSyncMode
    namespace: MemoryNamespace
    source_id: str
    path: str
    record_id: str | None = None
    previous_file_hash: str | None = None
    previous_record_hash: str | None = None
    current_file_hash: str | None = None
    current_record_hash: str | None = None
    file_modified_at: str | None = None
    record_updated_at: str | None = None
    file_exists: bool = True
    record_exists: bool = True

    def __post_init__(self) -> None:
        if self.mode not in {"file_primary", "db_as_index"}:
            raise InvalidArgumentError(f"invalid sync mode: {self.mode!r}")
        if not isinstance(self.namespace, MemoryNamespace):
            raise TypeError("namespace must be MemoryNamespace")
        if not self.source_id:
            raise InvalidArgumentError("source_id is required")
        if not self.path:
            raise InvalidArgumentError("path is required")
        for field_name in (
            "previous_file_hash",
            "previous_record_hash",
            "current_file_hash",
            "current_record_hash",
        ):
            _require_hash(getattr(self, field_name), field_name)


@dataclass(frozen=True, slots=True)
class SyncConflictRecord:
    conflict_id: str
    kind: SyncConflictKind
    namespace: MemoryNamespace
    source_id: str
    path: str
    mode: LocalSyncMode
    record_id: str | None = None
    file_hash: str | None = None
    record_hash: str | None = None
    file_modified_at: str | None = None
    record_updated_at: str | None = None
    status: SyncConflictStatus = "open"
    created_at: str = ""
    resolved_at: str | None = None
    resolution_action: SyncResolutionAction | None = None
    resolution_patch: dict[str, Any] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.conflict_id:
            raise InvalidArgumentError("conflict_id is required")
        if self.kind not in {
            "file_changed",
            "record_changed",
            "both_changed",
            "missing_file",
            "missing_record",
        }:
            raise InvalidArgumentError(f"invalid conflict kind: {self.kind!r}")
        if self.status not in {"open", "resolved"}:
            raise InvalidArgumentError(f"invalid conflict status: {self.status!r}")
        if not isinstance(self.namespace, MemoryNamespace):
            raise TypeError("namespace must be MemoryNamespace")
        if not self.source_id:
            raise InvalidArgumentError("source_id is required")
        if not self.path:
            raise InvalidArgumentError("path is required")
        if self.mode not in {"file_primary", "db_as_index"}:
            raise InvalidArgumentError(f"invalid sync mode: {self.mode!r}")
        if self.resolution_action is not None and self.resolution_action not in {
            "use_file",
            "use_record",
            "caller_patch",
            "mark_resolved",
        }:
            raise InvalidArgumentError(
                f"invalid resolution action: {self.resolution_action!r}"
            )

    @property
    def is_open(self) -> bool:
        return self.status == "open"


@dataclass(frozen=True, slots=True)
class LocalSyncResult:
    status: SyncResultStatus
    namespace: MemoryNamespace
    source_id: str
    path: str
    conflict: SyncConflictRecord | None = None

    def __post_init__(self) -> None:
        if self.status not in {
            "unchanged",
            "file_changed",
            "record_changed",
            "conflict",
            "missing_file",
            "missing_record",
        }:
            raise InvalidArgumentError(f"invalid sync result status: {self.status!r}")
        if self.status == "conflict" and self.conflict is None:
            raise InvalidArgumentError("conflict status requires a conflict record")
        if not self.source_id:
            raise InvalidArgumentError("source_id is required")
        if not self.path:
            raise InvalidArgumentError("path is required")


@dataclass(frozen=True, slots=True)
class SyncResolution:
    conflict_id: str
    action: SyncResolutionAction
    resolved_by: str
    resolved_at: str
    patch: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.conflict_id:
            raise InvalidArgumentError("conflict_id is required")
        if self.action not in {
            "use_file",
            "use_record",
            "caller_patch",
            "mark_resolved",
        }:
            raise InvalidArgumentError(f"invalid resolution action: {self.action!r}")
        if self.action == "caller_patch" and not self.patch:
            raise InvalidArgumentError("caller_patch resolution requires patch")
        if not self.resolved_by:
            raise InvalidArgumentError("resolved_by is required")
        if not self.resolved_at:
            raise InvalidArgumentError("resolved_at is required")


def conflict_id_for(request: LocalSyncRequest, kind: SyncConflictKind) -> str:
    return _stable_id(
        "sync-conflict",
        request.mode,
        _namespace_key(request.namespace),
        request.source_id,
        request.path,
        kind,
        request.current_file_hash or "",
        request.current_record_hash or "",
    )


def detect_sync_conflict(
    request: LocalSyncRequest,
    *,
    observed_at: str = "",
) -> LocalSyncResult:
    if not request.file_exists:
        kind: SyncConflictKind = "missing_file"
        conflict = _conflict_from_request(request, kind, observed_at)
        return LocalSyncResult(
            status="missing_file",
            namespace=request.namespace,
            source_id=request.source_id,
            path=request.path,
            conflict=conflict,
        )
    if not request.record_exists:
        kind = "missing_record"
        conflict = _conflict_from_request(request, kind, observed_at)
        return LocalSyncResult(
            status="missing_record",
            namespace=request.namespace,
            source_id=request.source_id,
            path=request.path,
            conflict=conflict,
        )
    file_changed = request.current_file_hash != request.previous_file_hash
    record_changed = request.current_record_hash != request.previous_record_hash
    if not file_changed and not record_changed:
        return LocalSyncResult(
            status="unchanged",
            namespace=request.namespace,
            source_id=request.source_id,
            path=request.path,
        )
    if file_changed and record_changed:
        kind = "both_changed"
        status: SyncResultStatus = "conflict"
    elif file_changed:
        kind = "file_changed"
        status = "file_changed"
    else:
        kind = "record_changed"
        status = "record_changed"
    conflict = _conflict_from_request(request, kind, observed_at)
    return LocalSyncResult(
        status=status,
        namespace=request.namespace,
        source_id=request.source_id,
        path=request.path,
        conflict=conflict,
    )


def _conflict_from_request(
    request: LocalSyncRequest,
    kind: SyncConflictKind,
    observed_at: str,
) -> SyncConflictRecord:
    return SyncConflictRecord(
        conflict_id=conflict_id_for(request, kind),
        kind=kind,
        namespace=request.namespace,
        source_id=request.source_id,
        path=request.path,
        mode=request.mode,
        record_id=request.record_id,
        file_hash=request.current_file_hash,
        record_hash=request.current_record_hash,
        file_modified_at=request.file_modified_at,
        record_updated_at=request.record_updated_at,
        created_at=observed_at,
    )


def resolve_sync_conflict(
    conflict: SyncConflictRecord,
    resolution: SyncResolution,
) -> SyncConflictRecord:
    if conflict.conflict_id != resolution.conflict_id:
        raise InvalidArgumentError("resolution conflict_id does not match conflict")
    if conflict.status == "resolved":
        return conflict
    return replace(
        conflict,
        status="resolved",
        resolved_at=resolution.resolved_at,
        resolution_action=resolution.action,
        resolution_patch=dict(resolution.patch),
        meta={**conflict.meta, "resolved_by": resolution.resolved_by},
    )


def sync_conflict_to_dict(conflict: SyncConflictRecord) -> dict[str, Any]:
    return asdict(conflict)


def sync_conflict_from_dict(data: dict[str, Any]) -> SyncConflictRecord:
    payload = dict(data)
    if isinstance(payload.get("namespace"), dict):
        payload["namespace"] = MemoryNamespace.from_dict(payload["namespace"])
    return SyncConflictRecord(**payload)


__all__ = [
    "LocalSyncMode",
    "LocalSyncRequest",
    "LocalSyncResult",
    "SyncConflictKind",
    "SyncConflictRecord",
    "SyncConflictStatus",
    "SyncResolution",
    "SyncResolutionAction",
    "conflict_id_for",
    "detect_sync_conflict",
    "resolve_sync_conflict",
    "sync_conflict_from_dict",
    "sync_conflict_to_dict",
]
