"""Reusable temporal truth helpers for durable knowledge records."""

from __future__ import annotations

from datetime import datetime, timezone

from sophiagraph.contracts.errors import InvalidArgumentError


def utc_now_iso() -> str:
    """Return the current UTC timestamp in ISO-8601 form."""

    return datetime.now(timezone.utc).isoformat()


def coerce_temporal_dt(value: datetime | str) -> datetime:
    """Normalize a temporal timestamp into a timezone-aware datetime."""
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    text = str(value or "").strip()
    if not text:
        raise InvalidArgumentError("temporal timestamp must be non-empty")
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


__all__ = ["coerce_temporal_dt", "utc_now_iso"]
