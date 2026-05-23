"""Reusable query DTOs for durable wisdom graph surfaces."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any, TypeAlias

if TYPE_CHECKING:
    from sophiagraph.models import MemoryNamespace

MemoryType: TypeAlias = str
MemoryTier: TypeAlias = str
CandidateStatus: TypeAlias = str
RetrievalFilters: TypeAlias = Any


class RecordOrder(str, Enum):
    """Ordering options for record listings."""

    UPDATED_AT_DESC = "updated_at_desc"
    UPDATED_AT_ASC = "updated_at_asc"


@dataclass(slots=True)
class ListQueryOptions:
    scopes: list[str]
    types: list[MemoryType] | None = None
    tiers: list[MemoryTier] | None = None
    include_invalidated: bool = False
    limit: int | None = None
    offset: int | None = None
    order_by: RecordOrder | None = None
    namespaces: list["MemoryNamespace"] | None = None


@dataclass(slots=True)
class SearchQueryOptions:
    query: str
    scopes: list[str]
    types: list[MemoryType] | None = None
    tiers: list[MemoryTier] | None = None
    filters: RetrievalFilters | None = None
    include_invalidated: bool = False
    limit: int | None = None
    namespaces: list["MemoryNamespace"] | None = None


@dataclass(slots=True)
class CandidateListOptions:
    session_id: str | None = None
    proposed_scope: str | None = None
    status: CandidateStatus | None = None
    limit: int | None = None


__all__ = [
    "CandidateListOptions",
    "ListQueryOptions",
    "RecordOrder",
    "SearchQueryOptions",
]
