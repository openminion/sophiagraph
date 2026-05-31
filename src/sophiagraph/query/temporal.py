"""Bitemporal record query helpers."""

from __future__ import annotations

from datetime import datetime

from sophiagraph.models import MemoryRecord
from sophiagraph.query.options import ListQueryOptions, SearchQueryOptions
from sophiagraph.temporal import coerce_temporal_dt


def has_bitemporal_filter(options: ListQueryOptions | SearchQueryOptions) -> bool:
    return any(
        (
            options.as_of is not None,
            options.valid_at is not None,
            options.effective_during is not None,
            options.believed_at is not None,
        )
    )


def record_matches_bitemporal(
    record: MemoryRecord,
    options: ListQueryOptions | SearchQueryOptions,
) -> bool:
    if options.valid_at is not None and not _valid_at(record, options.valid_at):
        return False
    if options.as_of is not None and not _believed_at(record, options.as_of):
        return False
    if options.believed_at is not None and not _believed_at(
        record, options.believed_at
    ):
        return False
    if options.effective_during is not None and not _effective_during(
        record, options.effective_during
    ):
        return False
    return True


def _record_start(record: MemoryRecord) -> datetime:
    return coerce_temporal_dt(record.event_time or record.created_at)


def _record_end(record: MemoryRecord) -> datetime | None:
    return coerce_temporal_dt(record.valid_to) if record.valid_to else None


def _valid_at(record: MemoryRecord, when: str) -> bool:
    target = coerce_temporal_dt(when)
    start = _record_start(record)
    end = _record_end(record)
    return start <= target and (end is None or target < end)


def _believed_at(record: MemoryRecord, when: str) -> bool:
    target = coerce_temporal_dt(when)
    created = coerce_temporal_dt(record.created_at)
    end = _record_end(record)
    return created <= target and (end is None or target < end)


def _effective_during(record: MemoryRecord, window: tuple[str, str]) -> bool:
    start_at, end_at = window
    window_start = coerce_temporal_dt(start_at)
    window_end = coerce_temporal_dt(end_at)
    record_start = _record_start(record)
    record_end = _record_end(record)
    if window_end <= window_start:
        return False
    if record_end is not None and record_end <= window_start:
        return False
    return record_start < window_end


__all__ = [
    "has_bitemporal_filter",
    "record_matches_bitemporal",
]
