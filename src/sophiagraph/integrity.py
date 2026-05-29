"""Row-level integrity hash primitives for ``MemoryRecord``.

This module is the canonical owner of row-level integrity hashing for
durable memory records. It declares three public symbols:

1. ``compute_row_integrity_hash`` — pure deterministic SHA-256 over a
   record's typed serializable fields, sorted for field-order
   independence.
2. ``populate_integrity_hash`` — helper that returns a copy of the
   supplied record with ``integrity_hash`` populated, gated by an
   ``enabled`` operator flag (default off, backward-compat).
3. ``verify_row_integrity`` — pure verifier returning a closed-enum
   ``IntegrityOutcome`` (``VALID``, ``TAMPERED``, ``UNVERIFIED``).

Anti-LLM boundary:
    The hash input is mechanically derived from typed record fields;
    the hash itself is mechanical SHA-256; the outcome enum is closed.
    There is no LLM step in any of these primitives.

Operator-runtime concerns (audit-log emission, retention, export) are
explicitly out of scope here. See KPR-10 governance hooks for those.
"""

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


# Fields excluded from the canonical hash input. ``integrity_hash`` is
# self-excluded so verification can recompute against an empty slot;
# any future operator-only mutation fields would be listed here.
INTEGRITY_HASH_EXCLUDED_FIELDS: frozenset[str] = frozenset({"integrity_hash"})


class IntegrityOutcome(str, enum.Enum):
    """Closed enum for row-integrity verification outcomes."""

    VALID = "valid"
    TAMPERED = "tampered"
    UNVERIFIED = "unverified"


def _canonicalize(value: Any) -> Any:
    """Coerce a record field value into a canonical, hash-stable form.

    Rules:
        - ``None`` / ``bool`` / ``int`` / ``float`` / ``str`` pass through.
        - Lists/tuples are recursed element-wise into a list.
        - Dicts are recursed and emitted with sorted keys.
        - Dataclasses (e.g. ``ArtifactRef``) are converted via ``asdict``
          and then recursed (ensuring sorted-key emission).
        - Enums / Literals stringify via ``str``.
        - Anything else falls back to ``str(value)`` (last-resort
          stability guarantee).
    """
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (list, tuple)):
        return [_canonicalize(item) for item in value]
    if isinstance(value, dict):
        return {key: _canonicalize(value[key]) for key in sorted(value.keys())}
    # Dataclass instance fallback — replicate asdict + recurse pattern.
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
    """Compute a deterministic SHA-256 integrity hash for ``record``.

    Field-order independence is guaranteed because ``_canonical_payload``
    sorts dict keys at every nesting level. Type-coercion stability is
    guaranteed by ``_canonicalize`` which normalizes containers and
    dataclass instances into JSON-encodable shapes.

    Returns:
        Hex-encoded SHA-256 digest (64 lowercase hex chars).
    """
    payload = _canonical_payload(record)
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def populate_integrity_hash(
    record: MemoryRecord, *, enabled: bool = False
) -> MemoryRecord:
    """Return a copy of ``record`` with ``integrity_hash`` populated.

    When ``enabled`` is ``False`` (the default), the record is returned
    unchanged. This keeps every existing put-record call site
    backward-compatible until an operator opts in.

    When ``enabled`` is ``True``, the integrity hash is computed via
    ``compute_row_integrity_hash`` and attached via dataclass
    ``replace``. If the record already carries an ``integrity_hash``,
    it is overwritten (operator flag is authoritative at put time).
    """
    if not enabled:
        return record
    digest = compute_row_integrity_hash(record)
    return replace(record, integrity_hash=digest)


def verify_row_integrity(record: MemoryRecord) -> IntegrityOutcome:
    """Verify ``record.integrity_hash`` against a freshly computed hash.

    Outcomes:
        - ``UNVERIFIED`` when ``integrity_hash`` is unset (``None`` or
          empty string) — the record was stored before integrity
          extension was enabled, so we make no tampering claim.
        - ``VALID`` when the stored hash matches the recomputed hash.
        - ``TAMPERED`` when the stored hash differs from the recomputed
          hash.

    This function is purely structural: it never asks an LLM whether
    the divergence is "real" tampering or how severe it is.
    """
    stored = getattr(record, "integrity_hash", None)
    if stored is None or stored == "":
        return IntegrityOutcome.UNVERIFIED
    expected = compute_row_integrity_hash(record)
    if stored == expected:
        return IntegrityOutcome.VALID
    return IntegrityOutcome.TAMPERED
