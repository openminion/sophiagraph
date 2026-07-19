"""Store, request, and GraphFakos helpers for local UI preview flows."""

from __future__ import annotations

from typing import cast
from uuid import uuid4

from graphfakos import GraphFakosRequest, GraphFakosScreen
from graphfakos.ui import render_provider_path

from sophiagraph.models import (
    KnowledgeDocumentBlock,
    MemoryCandidate,
    MemoryNamespace,
    MemoryRecord,
    StructuralLink,
)
from sophiagraph.query import ListQueryOptions
from sophiagraph.storage import SophiaGraphMemoryStore
from sophiagraph.workspace import load_workspace_metadata, open_workspace_store

from .graphfakos_adapter import SophiagraphViewerProvider
from .preview_types import PreviewScreen, UiPreviewRequest


def render_server_preview_path(
    request: UiPreviewRequest,
    path: str,
    query: dict[str, list[str]],
) -> str:
    screen = screen_from_path(path) or request.screen
    next_request = request_from_query(request, screen=screen, query=query)
    store, namespace, scope = store_for_request(next_request)
    provider = SophiagraphViewerProvider(
        store=store,
        scope=scope,
        namespace=namespace,
        principal_id="local-operator",
        workspace_id=next_request.workspace or "workspace:preview",
        workspace_root=next_request.workspace or "",
        source_root=next_request.source_root or "",
    )
    graph_request = graphfakos_request(
        next_request,
        record_id=next_request.record_id or first_record_id(store, scope, namespace),
    )
    return server_html(render_provider_path(provider, graph_request, path, query))


def request_from_query(
    request: UiPreviewRequest,
    *,
    screen: PreviewScreen,
    query: dict[str, list[str]],
) -> UiPreviewRequest:
    return UiPreviewRequest(
        screen=screen,
        workspace=first_query_value(query, "workspace") or request.workspace,
        source_root=first_query_value(query, "source_root") or request.source_root,
        output_path=request.output_path,
        scope=first_query_value(query, "scope") or request.scope,
        query=first_query_value(query, "query") or request.query,
        record_id=first_query_value(query, "record_id") or request.record_id,
        tenant_id=first_query_value(query, "tenant_id") or request.tenant_id,
        agent_id=first_query_value(query, "agent_id") or request.agent_id,
        graph_id=first_query_value(query, "graph_id") or request.graph_id,
        open_browser=False,
    )


def first_query_value(query: dict[str, list[str]], key: str) -> str | None:
    values = query.get(key) or []
    return values[0] if values and values[0] else None


def screen_from_path(path: str) -> PreviewScreen | None:
    value = path.strip("/") or "explore"
    aliases = {
        "": "explore",
        "candidate_review": "candidates",
        "saved_views": "views",
        "record_detail": "record",
    }
    value = aliases.get(value, value)
    if value in {
        "explore",
        "record",
        "graph",
        "candidates",
        "views",
        "timeline",
        "schema",
    }:
        return cast(PreviewScreen, value)
    return None


def server_html(html: str) -> str:
    replacements = {
        "href='/provider_status'": "href='/schema'",
        "href='/provider_status?": "href='/schema?",
        "href='/context_preview'": "href='/candidates'",
        "href='/context_preview?": "href='/candidates?",
        "href='/neighborhood'": "href='/graph'",
        "href='/neighborhood?": "href='/graph?",
    }
    for source, target in replacements.items():
        html = html.replace(source, target)
    return html


def graphfakos_request(
    request: UiPreviewRequest,
    *,
    record_id: str | None,
) -> GraphFakosRequest:
    screen_map: dict[PreviewScreen, GraphFakosScreen] = {
        "explore": "explore",
        "record": "explore",
        "graph": "neighborhood",
        "candidates": "context_preview",
        "views": "provider_status",
        "timeline": "timeline",
        "schema": "provider_status",
    }
    return GraphFakosRequest(
        screen=screen_map[request.screen],
        query=request.query,
        focus_node_id=record_id,
        source_node_id=record_id,
        max_depth=1,
        limit=25,
    )


def store_for_request(
    request: UiPreviewRequest,
) -> tuple[object, MemoryNamespace, str]:
    if request.workspace:
        metadata = load_workspace_metadata(request.workspace)
        return (
            open_workspace_store(request.workspace),
            metadata.namespace,
            metadata.scope,
        )
    namespace = MemoryNamespace(
        tenant_id=request.tenant_id,
        agent_id=request.agent_id,
        graph_id=request.graph_id,
    )
    store = SophiaGraphMemoryStore()
    seed_demo_store(store, namespace=namespace, scope=request.scope)
    return store, namespace, request.scope


def first_record_id(
    store: object,
    scope: str,
    namespace: MemoryNamespace,
) -> str | None:
    records = store.list_records(
        ListQueryOptions(scopes=[scope], namespaces=[namespace])
    )
    return records[0].id if records else None


def seed_demo_store(
    store: SophiaGraphMemoryStore,
    *,
    namespace: MemoryNamespace,
    scope: str,
) -> None:
    auth = demo_record(
        "auth-decision",
        "Auth Decision",
        "Use JWT auth for the operator console.",
        namespace=namespace,
        scope=scope,
    )
    refresh = demo_record(
        "refresh-plan",
        "Refresh Plan",
        "Refresh graph previews after local workspace sync.",
        namespace=namespace,
        scope=scope,
    )
    store.put_record(auth)
    store.put_record(refresh)
    store.put_link(
        StructuralLink(
            link_id="link-auth-refresh",
            source_record_id=auth.id,
            target_record_id=refresh.id,
            raw_target=refresh.title or refresh.id,
            link_kind="wikilink",
            resolution_status="resolved",
            namespace=namespace,
            relation_type="supports",
            created_at="2026-06-21T00:00:00+00:00",
        )
    )
    store.put_document_blocks(
        auth.id,
        [
            KnowledgeDocumentBlock(
                block_id="block-auth",
                document_id="doc-auth",
                record_id=auth.id,
                block_type="heading",
                anchor="auth",
                excerpt="Use JWT auth",
            )
        ],
    )
    store.put_candidate(
        MemoryCandidate(
            candidate_id=f"candidate-{uuid4().hex[:8]}",
            session_id="preview",
            proposed_scope=scope,
            type="fact",
            title="Preview candidate",
            content={"text": "Promote explicit UI preview affordances."},
            source="agent_inferred",
            confidence=0.84,
            status="proposed",
            namespace=namespace,
            claim_key="ui.preview",
            polarity="asserts",
            source_class="user_input",
            created_at="2026-06-21T00:00:00+00:00",
            updated_at="2026-06-21T00:00:00+00:00",
        )
    )


def demo_record(
    record_id: str,
    title: str,
    text: str,
    *,
    namespace: MemoryNamespace,
    scope: str,
) -> MemoryRecord:
    return MemoryRecord(
        id=record_id,
        scope=scope,
        type="fact",
        key=record_id,
        title=title,
        content={"text": text},
        namespace=namespace,
        created_at="2026-06-21T00:00:00+00:00",
        updated_at="2026-06-21T00:00:00+00:00",
        meta={
            "document": {"path": f"{record_id}.md"},
            "properties": {"status": "preview"},
        },
    )


__all__ = [
    "first_record_id",
    "graphfakos_request",
    "render_server_preview_path",
    "store_for_request",
]
