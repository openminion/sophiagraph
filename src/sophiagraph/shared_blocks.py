"""Shared memory-block collaboration primitives."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from typing import Any, Literal
from uuid import NAMESPACE_URL, uuid5

from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.models import MemoryNamespace
from sophiagraph.models.namespace import sorted_namespace_key

SharedAttachmentStatus = Literal["active", "detached"]
SharedBlockAccessMode = Literal["read_only"]
SharedMirrorStatus = Literal["fresh", "stale"]
SharedBlockConflictStatus = Literal["open", "resolved"]
SharedBlockUsageAction = Literal[
    "attach",
    "read",
    "stale_detected",
    "edit_denied",
    "conflict",
]


def _stable_id(prefix: str, *parts: str) -> str:
    return f"{prefix}-{uuid5(NAMESPACE_URL, ':'.join(str(part) for part in parts))}"


@dataclass(frozen=True, slots=True)
class SharedBlockAttachment:
    attachment_id: str
    block_id: str
    namespace: MemoryNamespace
    attached_agent_id: str
    access_mode: SharedBlockAccessMode = "read_only"
    attached_at: str = ""
    status: SharedAttachmentStatus = "active"
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.attachment_id:
            raise InvalidArgumentError("attachment_id is required")
        if not self.block_id:
            raise InvalidArgumentError("block_id is required")
        if not isinstance(self.namespace, MemoryNamespace):
            raise TypeError("namespace must be MemoryNamespace")
        if not self.attached_agent_id:
            raise InvalidArgumentError("attached_agent_id is required")
        if self.access_mode != "read_only":
            raise InvalidArgumentError("v1 shared block access_mode must be read_only")
        if self.status not in {"active", "detached"}:
            raise InvalidArgumentError(f"invalid attachment status: {self.status!r}")

    @classmethod
    def create(
        cls,
        *,
        block_id: str,
        namespace: MemoryNamespace,
        attached_agent_id: str,
        attached_at: str = "",
    ) -> "SharedBlockAttachment":
        return cls(
            attachment_id=_stable_id(
                "shared-attach",
                block_id,
                sorted_namespace_key(namespace),
                attached_agent_id,
            ),
            block_id=block_id,
            namespace=namespace,
            attached_agent_id=attached_agent_id,
            attached_at=attached_at,
        )


@dataclass(frozen=True, slots=True)
class SharedBlockMirror:
    mirror_id: str
    block_id: str
    source_namespace: MemoryNamespace
    mirror_namespace: MemoryNamespace
    source_hash: str
    mirror_hash: str
    last_synced_at: str
    status: SharedMirrorStatus = "fresh"
    stale_after: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.mirror_id:
            raise InvalidArgumentError("mirror_id is required")
        if not self.block_id:
            raise InvalidArgumentError("block_id is required")
        if not isinstance(self.source_namespace, MemoryNamespace):
            raise TypeError("source_namespace must be MemoryNamespace")
        if not isinstance(self.mirror_namespace, MemoryNamespace):
            raise TypeError("mirror_namespace must be MemoryNamespace")
        if not self.source_hash or not self.mirror_hash:
            raise InvalidArgumentError("source_hash and mirror_hash are required")
        if self.status not in {"fresh", "stale"}:
            raise InvalidArgumentError(f"invalid mirror status: {self.status!r}")

    @property
    def is_stale(self) -> bool:
        return self.status == "stale" or self.source_hash != self.mirror_hash


@dataclass(frozen=True, slots=True)
class SharedBlockEditConflict:
    conflict_id: str
    block_id: str
    namespace: MemoryNamespace
    attempted_by: str
    reason: str
    base_hash: str
    proposed_hash: str
    created_at: str
    status: SharedBlockConflictStatus = "open"
    resolved_at: str | None = None

    def __post_init__(self) -> None:
        if not self.conflict_id:
            raise InvalidArgumentError("conflict_id is required")
        if not self.block_id:
            raise InvalidArgumentError("block_id is required")
        if not isinstance(self.namespace, MemoryNamespace):
            raise TypeError("namespace must be MemoryNamespace")
        if not self.attempted_by:
            raise InvalidArgumentError("attempted_by is required")
        if not self.reason:
            raise InvalidArgumentError("reason is required")
        if self.status not in {"open", "resolved"}:
            raise InvalidArgumentError(f"invalid conflict status: {self.status!r}")


@dataclass(frozen=True, slots=True)
class SharedBlockUsageEvent:
    event_id: str
    block_id: str
    namespace: MemoryNamespace
    agent_id: str
    action: SharedBlockUsageAction
    occurred_at: str
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.event_id:
            raise InvalidArgumentError("event_id is required")
        if not self.block_id:
            raise InvalidArgumentError("block_id is required")
        if not isinstance(self.namespace, MemoryNamespace):
            raise TypeError("namespace must be MemoryNamespace")
        if not self.agent_id:
            raise InvalidArgumentError("agent_id is required")
        if self.action not in {
            "attach",
            "read",
            "stale_detected",
            "edit_denied",
            "conflict",
        }:
            raise InvalidArgumentError(f"invalid usage action: {self.action!r}")
        if not self.occurred_at:
            raise InvalidArgumentError("occurred_at is required")


def mark_mirror_stale_if_needed(
    mirror: SharedBlockMirror,
    *,
    current_source_hash: str,
) -> SharedBlockMirror:
    if current_source_hash == mirror.mirror_hash:
        return replace(mirror, source_hash=current_source_hash, status="fresh")
    return replace(mirror, source_hash=current_source_hash, status="stale")


def create_shared_block_conflict(
    *,
    block_id: str,
    namespace: MemoryNamespace,
    attempted_by: str,
    reason: str,
    base_hash: str,
    proposed_hash: str,
    created_at: str,
) -> SharedBlockEditConflict:
    return SharedBlockEditConflict(
        conflict_id=_stable_id(
            "shared-conflict",
            block_id,
            sorted_namespace_key(namespace),
            attempted_by,
            base_hash,
            proposed_hash,
        ),
        block_id=block_id,
        namespace=namespace,
        attempted_by=attempted_by,
        reason=reason,
        base_hash=base_hash,
        proposed_hash=proposed_hash,
        created_at=created_at,
    )


def _namespace_from_payload(payload: dict[str, Any], key: str) -> None:
    if isinstance(payload.get(key), dict):
        payload[key] = MemoryNamespace.from_dict(payload[key])


def shared_attachment_to_dict(value: SharedBlockAttachment) -> dict[str, Any]:
    return asdict(value)


def shared_attachment_from_dict(data: dict[str, Any]) -> SharedBlockAttachment:
    payload = dict(data)
    _namespace_from_payload(payload, "namespace")
    return SharedBlockAttachment(**payload)


def shared_mirror_to_dict(value: SharedBlockMirror) -> dict[str, Any]:
    return asdict(value)


def shared_mirror_from_dict(data: dict[str, Any]) -> SharedBlockMirror:
    payload = dict(data)
    _namespace_from_payload(payload, "source_namespace")
    _namespace_from_payload(payload, "mirror_namespace")
    return SharedBlockMirror(**payload)


def shared_conflict_to_dict(value: SharedBlockEditConflict) -> dict[str, Any]:
    return asdict(value)


def shared_conflict_from_dict(data: dict[str, Any]) -> SharedBlockEditConflict:
    payload = dict(data)
    _namespace_from_payload(payload, "namespace")
    return SharedBlockEditConflict(**payload)


def shared_usage_to_dict(value: SharedBlockUsageEvent) -> dict[str, Any]:
    return asdict(value)


def shared_usage_from_dict(data: dict[str, Any]) -> SharedBlockUsageEvent:
    payload = dict(data)
    _namespace_from_payload(payload, "namespace")
    return SharedBlockUsageEvent(**payload)


__all__ = [
    "SharedAttachmentStatus",
    "SharedBlockAccessMode",
    "SharedBlockAttachment",
    "SharedBlockEditConflict",
    "SharedBlockUsageAction",
    "SharedBlockUsageEvent",
    "SharedMirrorStatus",
    "create_shared_block_conflict",
    "mark_mirror_stale_if_needed",
    "shared_attachment_from_dict",
    "shared_attachment_to_dict",
    "shared_conflict_from_dict",
    "shared_conflict_to_dict",
    "shared_mirror_from_dict",
    "shared_mirror_to_dict",
    "shared_usage_from_dict",
    "shared_usage_to_dict",
]
