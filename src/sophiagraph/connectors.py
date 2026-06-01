"""Provider-neutral source connector ingestion contracts."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from typing import Any, Literal
from uuid import NAMESPACE_URL, uuid5

from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.freshness import FreshnessLedgerEntry, ReplayDecision, decide_replay
from sophiagraph.models import MemoryNamespace

SourceType = Literal["file", "api", "webhook", "manual", "test_fake"]
SourcePermissionScope = Literal["read_only", "read_write", "metadata_only"]
ConnectorPayloadKind = Literal["document", "record", "link", "artifact", "batch"]


def ingest_key_for(source_id: str, cursor: str | None, content_hash: str | None) -> str:
    if not source_id:
        raise InvalidArgumentError("source_id is required")
    return f"ingest-{uuid5(NAMESPACE_URL, ':'.join([source_id, cursor or '', content_hash or '']))}"


@dataclass(frozen=True, slots=True)
class SourceRegistryEntry:
    source_id: str
    source_type: SourceType
    namespace: MemoryNamespace
    display_name: str
    permission_scope: SourcePermissionScope
    cursor: str | None = None
    content_hash: str | None = None
    provenance: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self) -> None:
        if not self.source_id:
            raise InvalidArgumentError("source_id is required")
        if self.source_type not in {"file", "api", "webhook", "manual", "test_fake"}:
            raise InvalidArgumentError(f"invalid source_type: {self.source_type!r}")
        if not isinstance(self.namespace, MemoryNamespace):
            raise TypeError("namespace must be MemoryNamespace")
        if not self.display_name:
            raise InvalidArgumentError("display_name is required")
        if self.permission_scope not in {
            "read_only",
            "read_write",
            "metadata_only",
        }:
            raise InvalidArgumentError(
                f"invalid permission_scope: {self.permission_scope!r}"
            )


@dataclass(frozen=True, slots=True)
class SourceIngestEnvelope:
    ingest_id: str
    source_id: str
    namespace: MemoryNamespace
    payload_kind: ConnectorPayloadKind
    payload: dict[str, Any]
    cursor: str | None = None
    content_hash: str | None = None
    permission_scope: SourcePermissionScope = "read_only"
    provenance: dict[str, Any] = field(default_factory=dict)
    idempotency_key: str | None = None

    def __post_init__(self) -> None:
        if not self.ingest_id:
            raise InvalidArgumentError("ingest_id is required")
        if not self.source_id:
            raise InvalidArgumentError("source_id is required")
        if not isinstance(self.namespace, MemoryNamespace):
            raise TypeError("namespace must be MemoryNamespace")
        if self.payload_kind not in {"document", "record", "link", "artifact", "batch"}:
            raise InvalidArgumentError(f"invalid payload_kind: {self.payload_kind!r}")
        if not isinstance(self.payload, dict):
            raise TypeError("payload must be a dict")
        if self.permission_scope not in {
            "read_only",
            "read_write",
            "metadata_only",
        }:
            raise InvalidArgumentError(
                f"invalid permission_scope: {self.permission_scope!r}"
            )

    @classmethod
    def create(
        cls,
        *,
        source_id: str,
        namespace: MemoryNamespace,
        payload_kind: ConnectorPayloadKind,
        payload: dict[str, Any],
        cursor: str | None = None,
        content_hash: str | None = None,
        permission_scope: SourcePermissionScope = "read_only",
        provenance: dict[str, Any] | None = None,
    ) -> "SourceIngestEnvelope":
        ingest_id = ingest_key_for(source_id, cursor, content_hash)
        return cls(
            ingest_id=ingest_id,
            source_id=source_id,
            namespace=namespace,
            payload_kind=payload_kind,
            payload=dict(payload),
            cursor=cursor,
            content_hash=content_hash,
            permission_scope=permission_scope,
            provenance=dict(provenance or {}),
            idempotency_key=ingest_id,
        )


@dataclass(frozen=True, slots=True)
class SourceIngestResult:
    ingest_id: str
    source_id: str
    accepted: bool
    replay_decision: ReplayDecision
    record_ids: list[str] = field(default_factory=list)
    freshness_entry: FreshnessLedgerEntry | None = None

    def __post_init__(self) -> None:
        if not self.ingest_id:
            raise InvalidArgumentError("ingest_id is required")
        if not self.source_id:
            raise InvalidArgumentError("source_id is required")


def update_source_after_ingest(
    source: SourceRegistryEntry,
    envelope: SourceIngestEnvelope,
    *,
    updated_at: str = "",
) -> SourceRegistryEntry:
    if source.source_id != envelope.source_id:
        raise InvalidArgumentError("envelope source_id does not match source")
    if not source.namespace.matches(envelope.namespace):
        raise InvalidArgumentError("envelope namespace does not match source")
    return replace(
        source,
        cursor=envelope.cursor or source.cursor,
        content_hash=envelope.content_hash or source.content_hash,
        permission_scope=envelope.permission_scope,
        updated_at=updated_at or source.updated_at,
    )


def decide_source_ingest(
    source: SourceRegistryEntry,
    envelope: SourceIngestEnvelope,
    existing_freshness: FreshnessLedgerEntry | None = None,
) -> SourceIngestResult:
    if source.source_id != envelope.source_id:
        raise InvalidArgumentError("envelope source_id does not match source")
    if not source.namespace.matches(envelope.namespace):
        raise InvalidArgumentError("envelope namespace does not match source")
    if source.permission_scope == "metadata_only" and envelope.payload:
        raise InvalidArgumentError("metadata_only sources cannot submit payload body")
    decision = decide_replay(
        existing_freshness,
        incoming_cursor=envelope.cursor,
        incoming_hash=envelope.content_hash,
    )
    accepted = decision.decision != "skip_unchanged"
    return SourceIngestResult(
        ingest_id=envelope.ingest_id,
        source_id=envelope.source_id,
        accepted=accepted,
        replay_decision=decision,
    )


def source_entry_to_dict(source: SourceRegistryEntry) -> dict[str, Any]:
    return asdict(source)


def source_entry_from_dict(data: dict[str, Any]) -> SourceRegistryEntry:
    payload = dict(data)
    if isinstance(payload.get("namespace"), dict):
        payload["namespace"] = MemoryNamespace.from_dict(payload["namespace"])
    return SourceRegistryEntry(**payload)


def source_ingest_to_dict(envelope: SourceIngestEnvelope) -> dict[str, Any]:
    return asdict(envelope)


def source_ingest_from_dict(data: dict[str, Any]) -> SourceIngestEnvelope:
    payload = dict(data)
    if isinstance(payload.get("namespace"), dict):
        payload["namespace"] = MemoryNamespace.from_dict(payload["namespace"])
    return SourceIngestEnvelope(**payload)


__all__ = [
    "ConnectorPayloadKind",
    "SourceIngestEnvelope",
    "SourceIngestResult",
    "SourcePermissionScope",
    "SourceRegistryEntry",
    "SourceType",
    "decide_source_ingest",
    "ingest_key_for",
    "source_entry_from_dict",
    "source_entry_to_dict",
    "source_ingest_from_dict",
    "source_ingest_to_dict",
    "update_source_after_ingest",
]
