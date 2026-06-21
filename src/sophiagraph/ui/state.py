"""Shared app-state DTOs for the package-local visual explorer boundary."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sophiagraph.models import MemoryNamespace
from sophiagraph.query import KnowledgeExplorerRequest


@dataclass(frozen=True, slots=True)
class UiAppState:
    """Visible cross-screen UI state for the first SophiaGraph explorer shell."""

    active_namespace: MemoryNamespace | None = None
    comparison_namespace: MemoryNamespace | None = None
    explorer_request: KnowledgeExplorerRequest | None = None
    selected_record_id: str | None = None
    graph_depth: int = 1
    edge_filters: tuple[str, ...] = ()
    graph_mode: str = "neighborhood"
    as_of: str | None = None
    valid_at: str | None = None
    believed_at: str | None = None
    active_source_id: str | None = None
    active_connector_id: str | None = None
    selected_candidate_id: str | None = None
    candidate_status_filter: str | None = None
    active_saved_view_id: str | None = None
    saved_view_live: bool = True
    backend_capability_snapshot: dict[str, Any] = field(default_factory=dict)
    last_request_payload: dict[str, Any] = field(default_factory=dict)
    last_response_payload: dict[str, Any] = field(default_factory=dict)


__all__ = ["UiAppState"]
