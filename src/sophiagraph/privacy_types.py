"""Typed privacy result contracts and constants."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.models import MemoryRecord, RedactionResult
from sophiagraph.portability.models import MemoryBundleSnapshot

PRIVACY_META_KEY = "privacy_policy"

PrivacyOmissionReason = str
PRIVACY_OMISSION_REASONS = frozenset(
    {
        "hidden_by_visibility",
        "audit_only",
        "denied_by_policy_hook",
    }
)


@dataclass(frozen=True)
class PrivacyOmittedRecord:
    """Typed explanation for one omitted record."""

    record_id: str
    reason: PrivacyOmissionReason
    detail: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.record_id:
            raise InvalidArgumentError("record_id is required")
        if self.reason not in PRIVACY_OMISSION_REASONS:
            raise InvalidArgumentError(f"invalid omission reason: {self.reason!r}")
        if not isinstance(self.detail, dict):
            raise InvalidArgumentError("detail must be a dict")


@dataclass(frozen=True)
class PrivacyRetrievalResult:
    records: list[MemoryRecord]
    omitted: list[PrivacyOmittedRecord] = field(default_factory=list)
    denial_events: list[Any] = field(default_factory=list)
    redactions: list[RedactionResult] = field(default_factory=list)


@dataclass(frozen=True)
class PrivacyExportResult:
    snapshot: MemoryBundleSnapshot
    omitted: list[PrivacyOmittedRecord] = field(default_factory=list)
    denial_events: list[Any] = field(default_factory=list)
    redactions: list[RedactionResult] = field(default_factory=list)


__all__ = [
    "PRIVACY_META_KEY",
    "PRIVACY_OMISSION_REASONS",
    "PrivacyExportResult",
    "PrivacyOmissionReason",
    "PrivacyOmittedRecord",
    "PrivacyRetrievalResult",
]
