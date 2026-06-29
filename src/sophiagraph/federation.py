"""Explicit workspace federation packets and query helpers."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.models import MemoryNamespace
from sophiagraph.query.explorer import explore_knowledge
from sophiagraph.query.explorer_types import (
    KnowledgeExplorerStore,
    KnowledgeExplorerRequest,
    KnowledgeExplorerResult,
    KnowledgeHit,
)
from sophiagraph.workspace_types import open_workspace_store


@dataclass(frozen=True, slots=True)
class FederatedWorkspaceRef:
    """One explicit workspace participating in a federated query."""

    workspace_id: str
    root: str | None = None
    store: KnowledgeExplorerStore | None = None
    label: str = ""
    namespace: MemoryNamespace | None = None
    scope: str | None = None

    def __post_init__(self) -> None:
        if not self.workspace_id:
            raise InvalidArgumentError("workspace_id is required")
        if self.root is None and self.store is None:
            raise InvalidArgumentError("workspace requires root or store")


@dataclass(frozen=True, slots=True)
class FederatedWorkspaceQuery:
    """Query over an explicit workspace set; hidden global queries are refused."""

    workspaces: tuple[FederatedWorkspaceRef, ...]
    request: KnowledgeExplorerRequest
    deduplicate: bool = True
    limit: int = 50

    def __post_init__(self) -> None:
        if not self.workspaces:
            raise InvalidArgumentError("federated query requires workspaces")
        if self.limit <= 0:
            raise InvalidArgumentError("limit must be positive")
        ids = [workspace.workspace_id for workspace in self.workspaces]
        if len(ids) != len(set(ids)):
            raise InvalidArgumentError("workspace_id values must be unique")


@dataclass(frozen=True, slots=True)
class FederatedCitation:
    """Structural source citation for one federated hit."""

    workspace_id: str
    record_id: str
    source_path: str | None = None
    namespace: MemoryNamespace | None = None
    scope: str | None = None
    excerpt: str | None = None

    def __post_init__(self) -> None:
        if not self.workspace_id:
            raise InvalidArgumentError("workspace_id is required")
        if not self.record_id:
            raise InvalidArgumentError("record_id is required")


@dataclass(frozen=True, slots=True)
class FederatedKnowledgeHit:
    """Explorer hit decorated with explicit workspace attribution."""

    workspace_id: str
    hit: KnowledgeHit
    citation: FederatedCitation


@dataclass(frozen=True, slots=True)
class FederatedOmission:
    """Why a workspace or hit was omitted from a federated result."""

    workspace_id: str
    reason: str
    detail: str = ""

    def __post_init__(self) -> None:
        if not self.workspace_id:
            raise InvalidArgumentError("workspace_id is required")
        if self.reason not in {"duplicate", "query_failed", "limit_exceeded"}:
            raise InvalidArgumentError(f"invalid omission reason: {self.reason!r}")


@dataclass(frozen=True, slots=True)
class FederatedWorkspaceResult:
    """Combined federated result with source packets preserved."""

    query: FederatedWorkspaceQuery
    workspace_results: dict[str, KnowledgeExplorerResult]
    hits: tuple[FederatedKnowledgeHit, ...]
    citations: tuple[FederatedCitation, ...]
    omissions: tuple[FederatedOmission, ...] = ()
    diagnostics: dict[str, Any] = field(default_factory=dict)


def run_federated_workspace_query(
    query: FederatedWorkspaceQuery,
) -> FederatedWorkspaceResult:
    """Run a structural explorer query over the caller-declared workspace set."""

    workspace_results: dict[str, KnowledgeExplorerResult] = {}
    hits: list[FederatedKnowledgeHit] = []
    citations: list[FederatedCitation] = []
    omissions: list[FederatedOmission] = []
    seen: set[str] = set()
    for workspace in query.workspaces:
        try:
            result = explore_knowledge(
                _workspace_store(workspace),
                _workspace_request(query.request, workspace),
            )
        except Exception as exc:  # allow-bare-raise: boundary records diagnostic
            omissions.append(
                FederatedOmission(
                    workspace_id=workspace.workspace_id,
                    reason="query_failed",
                    detail=type(exc).__name__,
                )
            )
            continue
        workspace_results[workspace.workspace_id] = result
        for hit in result.hits:
            if query.deduplicate and hit.record_id in seen:
                omissions.append(
                    FederatedOmission(
                        workspace_id=workspace.workspace_id,
                        reason="duplicate",
                        detail=hit.record_id,
                    )
                )
                continue
            seen.add(hit.record_id)
            citation = _citation_for(workspace, hit)
            hits.append(
                FederatedKnowledgeHit(
                    workspace_id=workspace.workspace_id,
                    hit=hit,
                    citation=citation,
                )
            )
            citations.append(citation)
            if len(hits) >= query.limit:
                break
        if len(hits) >= query.limit:
            omissions.extend(
                FederatedOmission(
                    workspace_id=item.workspace_id,
                    reason="limit_exceeded",
                    detail=str(query.limit),
                )
                for item in query.workspaces
                if item.workspace_id not in workspace_results
            )
            break
    return FederatedWorkspaceResult(
        query=query,
        workspace_results=workspace_results,
        hits=tuple(hits),
        citations=tuple(citations),
        omissions=tuple(omissions),
        diagnostics={
            "workspace_count": len(query.workspaces),
            "hit_count": len(hits),
        },
    )


def _workspace_store(workspace: FederatedWorkspaceRef) -> KnowledgeExplorerStore:
    if workspace.store is not None:
        return workspace.store
    return open_workspace_store(Path(str(workspace.root)))


def _workspace_request(
    request: KnowledgeExplorerRequest,
    workspace: FederatedWorkspaceRef,
) -> KnowledgeExplorerRequest:
    namespaces = list(request.namespaces or [])
    if workspace.namespace is not None:
        namespaces = [workspace.namespace]
    scopes = list(request.scopes)
    if workspace.scope is not None:
        scopes = [workspace.scope]
    return replace(request, scopes=scopes, namespaces=namespaces)


def _citation_for(
    workspace: FederatedWorkspaceRef,
    hit: KnowledgeHit,
) -> FederatedCitation:
    context = hit.context
    return FederatedCitation(
        workspace_id=workspace.workspace_id,
        record_id=hit.record_id,
        source_path=context.source_path if context else None,
        namespace=workspace.namespace,
        scope=workspace.scope,
        excerpt=context.text if context else None,
    )


__all__ = [
    "FederatedCitation",
    "FederatedKnowledgeHit",
    "FederatedOmission",
    "FederatedWorkspaceQuery",
    "FederatedWorkspaceRef",
    "FederatedWorkspaceResult",
    "run_federated_workspace_query",
]
