"""Row-level integrity hash primitives for ``MemoryRecord``."""

from __future__ import annotations

import enum
import hashlib
import json
from dataclasses import asdict, replace
from typing import Any

from sophiagraph.models.record import MemoryRecord

__all__ = [
    "INTEGRITY_HASH_EXCLUDED_FIELDS",
    "IntegrityOutcome",
    "compute_row_integrity_hash",
    "populate_integrity_hash",
    "verify_row_integrity",
]


# ``integrity_hash`` self-excludes so verification recomputes a stable digest.
INTEGRITY_HASH_EXCLUDED_FIELDS: frozenset[str] = frozenset({"integrity_hash"})


class IntegrityOutcome(str, enum.Enum):
    """Closed enum for row-integrity verification outcomes."""

    VALID = "valid"
    TAMPERED = "tampered"
    UNVERIFIED = "unverified"


def _canonicalize(value: Any) -> Any:
    """Coerce record fields into hash-stable JSON-like values."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (list, tuple)):
        return [_canonicalize(item) for item in value]
    if isinstance(value, dict):
        return {key: _canonicalize(value[key]) for key in sorted(value.keys())}
    if hasattr(value, "__dataclass_fields__"):
        return _canonicalize(asdict(value))
    return str(value)


def _canonical_payload(record: MemoryRecord) -> dict[str, Any]:
    """Return the canonical (sorted, excluded-fields-removed) payload."""
    raw = asdict(record)
    filtered = {
        key: value
        for key, value in raw.items()
        if key not in INTEGRITY_HASH_EXCLUDED_FIELDS
    }
    return _canonicalize(filtered)


def compute_row_integrity_hash(record: MemoryRecord) -> str:
    """Compute a deterministic SHA-256 integrity hash for ``record``."""
    payload = _canonical_payload(record)
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def populate_integrity_hash(
    record: MemoryRecord, *, enabled: bool = False
) -> MemoryRecord:
    """Optionally return a copy with ``integrity_hash`` populated."""
    if not enabled:
        return record
    digest = compute_row_integrity_hash(record)
    return replace(record, integrity_hash=digest)


def verify_row_integrity(record: MemoryRecord) -> IntegrityOutcome:
    """Verify ``record.integrity_hash`` against a freshly computed hash."""
    stored = getattr(record, "integrity_hash", None)
    if stored is None or stored == "":
        return IntegrityOutcome.UNVERIFIED
    expected = compute_row_integrity_hash(record)
    if stored == expected:
        return IntegrityOutcome.VALID
    return IntegrityOutcome.TAMPERED
