"""Freshness ledger primitives for incremental ingestion."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal
from uuid import NAMESPACE_URL, uuid5

from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.models import MemoryNamespace

FreshnessStatus = Literal["fresh", "stale", "pending", "failed", "unknown"]
FreshnessSourceKind = Literal[
    "file",
    "connector",
    "openminion_submission",
    "bundle_import",
    "schema_migration",
    "index_rebuild",
]
ReplayDecisionKind = Literal[
    "skip_unchanged",
    "ingest_changed",
    "retry_failed",
    "rebuild_required",
]


def freshness_id_for(
    namespace: MemoryNamespace,
    source_kind: FreshnessSourceKind,
    source_id: str,
) -> str:
    ns_key = "|".join(
        f"{key}={value}" for key, value in sorted(namespace.as_dict().items())
    )
    return f"fresh-{uuid5(NAMESPACE_URL, ':'.join([ns_key, source_kind, source_id]))}"


@dataclass(frozen=True, slots=True)
class FreshnessCursor:
    source_id: str
    cursor: str
    content_hash: str | None = None
    observed_at: str | None = None

    def __post_init__(self) -> None:
        if not self.source_id:
            raise InvalidArgumentError("source_id is required")
        if not self.cursor:
            raise InvalidArgumentError("cursor is required")
        if self.content_hash is not None and not self.content_hash:
            raise InvalidArgumentError("content_hash cannot be empty")


@dataclass(frozen=True, slots=True)
class FreshnessLedgerEntry:
    ledger_id: str
    namespace: MemoryNamespace
    source_kind: FreshnessSourceKind
    source_id: str
    status: FreshnessStatus
    cursor: str | None = None
    content_hash: str | None = None
    updated_at: str = ""
    record_ids: list[str] = field(default_factory=list)
    error_code: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.ledger_id:
            raise InvalidArgumentError("ledger_id is required")
        if not isinstance(self.namespace, MemoryNamespace):
            raise TypeError("namespace must be MemoryNamespace")
        if self.source_kind not in {
            "file",
            "connector",
            "openminion_submission",
            "bundle_import",
            "schema_migration",
            "index_rebuild",
        }:
            raise InvalidArgumentError(f"invalid source_kind: {self.source_kind!r}")
        if self.status not in {"fresh", "stale", "pending", "failed", "unknown"}:
            raise InvalidArgumentError(f"invalid freshness status: {self.status!r}")
        if not self.source_id:
            raise InvalidArgumentError("source_id is required")
        if self.status == "failed" and not self.error_code:
            raise InvalidArgumentError("failed freshness entries require error_code")

    @classmethod
    def create(
        cls,
        *,
        namespace: MemoryNamespace,
        source_kind: FreshnessSourceKind,
        source_id: str,
        status: FreshnessStatus,
        cursor: str | None = None,
        content_hash: str | None = None,
        updated_at: str = "",
        record_ids: list[str] | None = None,
        error_code: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> "FreshnessLedgerEntry":
        return cls(
            ledger_id=freshness_id_for(namespace, source_kind, source_id),
            namespace=namespace,
            source_kind=source_kind,
            source_id=source_id,
            status=status,
            cursor=cursor,
            content_hash=content_hash,
            updated_at=updated_at,
            record_ids=list(record_ids or []),
            error_code=error_code,
            meta=dict(meta or {}),
        )


@dataclass(frozen=True, slots=True)
class ReplayDecision:
    decision: ReplayDecisionKind
    reason: str
    previous_ledger_id: str | None = None

    def __post_init__(self) -> None:
        if self.decision not in {
            "skip_unchanged",
            "ingest_changed",
            "retry_failed",
            "rebuild_required",
        }:
            raise InvalidArgumentError(f"invalid replay decision: {self.decision!r}")
        if not self.reason:
            raise InvalidArgumentError("reason is required")


def decide_replay(
    existing: FreshnessLedgerEntry | None,
    *,
    incoming_cursor: str | None,
    incoming_hash: str | None,
    force_rebuild: bool = False,
) -> ReplayDecision:
    if force_rebuild:
        return ReplayDecision("rebuild_required", "caller requested rebuild")
    if existing is None:
        return ReplayDecision("ingest_changed", "no prior freshness entry")
    if existing.status == "failed":
        return ReplayDecision(
            "retry_failed",
            "previous ingest failed",
            previous_ledger_id=existing.ledger_id,
        )
    same_cursor = incoming_cursor is not None and incoming_cursor == existing.cursor
    same_hash = incoming_hash is not None and incoming_hash == existing.content_hash
    if same_cursor or same_hash:
        return ReplayDecision(
            "skip_unchanged",
            "cursor or content hash matches prior entry",
            previous_ledger_id=existing.ledger_id,
        )
    return ReplayDecision(
        "ingest_changed",
        "cursor and content hash changed",
        previous_ledger_id=existing.ledger_id,
    )


def freshness_entry_to_dict(entry: FreshnessLedgerEntry) -> dict[str, Any]:
    return asdict(entry)


def freshness_entry_from_dict(data: dict[str, Any]) -> FreshnessLedgerEntry:
    payload = dict(data)
    if isinstance(payload.get("namespace"), dict):
        payload["namespace"] = MemoryNamespace.from_dict(payload["namespace"])
    return FreshnessLedgerEntry(**payload)


__all__ = [
    "FreshnessCursor",
    "FreshnessLedgerEntry",
    "FreshnessSourceKind",
    "FreshnessStatus",
    "ReplayDecision",
    "ReplayDecisionKind",
    "decide_replay",
    "freshness_entry_from_dict",
    "freshness_entry_to_dict",
    "freshness_id_for",
]
