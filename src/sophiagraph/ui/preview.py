"""Local HTML preview helpers for the package-owned SophiaGraph UI."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from uuid import uuid4
import webbrowser

from sophiagraph.models import (
    KnowledgeDocumentBlock,
    MemoryCandidate,
    MemoryNamespace,
    MemoryRecord,
    StructuralLink,
)
from sophiagraph.query import (
    CandidateListOptions,
    KnowledgeExplorerRequest,
    LinkQueryOptions,
    ListQueryOptions,
)
from sophiagraph.storage import SophiaGraphMemoryStore
from sophiagraph.views import SavedViewDefinition, SavedViewSummary
from sophiagraph.workspace import load_workspace_metadata, open_workspace_store

from .local_server import (
    LocalVisualHttpServer,
    LocalVisualServerResult,
    make_local_visual_server,
    serve_local_visual_server,
)
from .render import render_screen_html
from .screens import (
    GraphViewRequest,
    SavedViewWorkbenchRequest,
    build_candidate_review_screen,
    build_explorer_screen,
    build_graph_view_screen,
    build_record_detail_screen,
    build_saved_view_workbench_screen,
    build_schema_developer_screen,
    build_timeline_screen,
)

PreviewScreen = Literal[
    "explore",
    "record",
    "graph",
    "candidates",
    "views",
    "timeline",
    "schema",
]


@dataclass(frozen=True, slots=True)
class UiPreviewRequest:
    screen: PreviewScreen = "explore"
    workspace: str | None = None
    output_path: str = "sophiagraph-ui-preview.html"
    scope: str = "agent:demo"
    query: str = ""
    record_id: str | None = None
    tenant_id: str | None = None
    agent_id: str | None = "demo"
    graph_id: str | None = "main"
    open_browser: bool = False


@dataclass(frozen=True, slots=True)
class UiPreviewResult:
    output_path: str
    screen: str
    workspace: str | None
    record_count: int
    opened: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "output_path": self.output_path,
            "screen": self.screen,
            "workspace": self.workspace,
            "record_count": self.record_count,
            "opened": self.opened,
        }


@dataclass(frozen=True, slots=True)
class UiPreviewRender:
    html: str
    screen: str
    workspace: str | None
    record_count: int


def write_ui_preview(request: UiPreviewRequest) -> UiPreviewResult:
    rendered = render_ui_preview(request)
    output_path = Path(request.output_path).expanduser().resolve(strict=False)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered.html, encoding="utf-8")
    opened = False
    if request.open_browser:
        opened = webbrowser.open(output_path.as_uri())
    return UiPreviewResult(
        output_path=str(output_path),
        screen=rendered.screen,
        workspace=rendered.workspace,
        record_count=rendered.record_count,
        opened=opened,
    )


def render_ui_preview(request: UiPreviewRequest) -> UiPreviewRender:
    store, namespace, scope = _store_for_request(request)
    record_id = request.record_id or _first_record_id(store, scope, namespace)
    screen = _build_preview_screen(
        store,
        request=request,
        namespace=namespace,
        scope=scope,
        record_id=record_id,
    )
    return UiPreviewRender(
        html=render_screen_html(screen),
        screen=request.screen,
        workspace=request.workspace,
        record_count=store.record_count(),
    )


def make_ui_preview_server(
    request: UiPreviewRequest,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
) -> LocalVisualHttpServer:
    return make_local_visual_server(
        render_path=lambda path, query: _render_server_path(request, path, query),
        default_path=f"/{request.screen}",
        host=host,
        port=port,
    )


def serve_ui_preview(
    request: UiPreviewRequest,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
) -> LocalVisualServerResult:
    return serve_local_visual_server(
        render_path=lambda path, query: _render_server_path(request, path, query),
        default_path=f"/{request.screen}",
        host=host,
        port=port,
        open_browser=request.open_browser,
    )


def _render_server_path(
    request: UiPreviewRequest,
    path: str,
    query: dict[str, list[str]],
) -> str:
    screen = _screen_from_path(path) or request.screen
    next_request = _request_from_query(request, screen=screen, query=query)
    return _server_html(render_ui_preview(next_request).html)


def _request_from_query(
    request: UiPreviewRequest,
    *,
    screen: PreviewScreen,
    query: dict[str, list[str]],
) -> UiPreviewRequest:
    return UiPreviewRequest(
        screen=screen,
        workspace=_first_query_value(query, "workspace") or request.workspace,
        output_path=request.output_path,
        scope=_first_query_value(query, "scope") or request.scope,
        query=_first_query_value(query, "query") or request.query,
        record_id=_first_query_value(query, "record_id") or request.record_id,
        tenant_id=_first_query_value(query, "tenant_id") or request.tenant_id,
        agent_id=_first_query_value(query, "agent_id") or request.agent_id,
        graph_id=_first_query_value(query, "graph_id") or request.graph_id,
        open_browser=False,
    )


def _first_query_value(query: dict[str, list[str]], key: str) -> str | None:
    values = query.get(key) or []
    return values[0] if values and values[0] else None


def _screen_from_path(path: str) -> PreviewScreen | None:
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
        return value  # type: ignore[return-value]
    return None


def _server_html(html: str) -> str:
    replacements = {
        "href='#explore'": "href='/explore'",
        "href='#record_detail'": "href='/record'",
        "href='#graph'": "href='/graph'",
        "href='#candidate_review'": "href='/candidates'",
        "href='#saved_views'": "href='/views'",
        "href='#timeline'": "href='/timeline'",
        "href='#schema'": "href='/schema'",
    }
    for source, target in replacements.items():
        html = html.replace(source, target)
    return html


def _store_for_request(
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
    _seed_demo_store(store, namespace=namespace, scope=request.scope)
    return store, namespace, request.scope


def _build_preview_screen(
    store: object,
    *,
    request: UiPreviewRequest,
    namespace: MemoryNamespace,
    scope: str,
    record_id: str | None,
) -> object:
    namespaces = [namespace]
    if request.screen == "record":
        return build_record_detail_screen(store, record_id=record_id or "")
    if request.screen == "graph":
        return build_graph_view_screen(
            store,
            GraphViewRequest(
                root_record_id=record_id or "",
                scopes=[scope],
                namespaces=namespaces,
                target_record_id=_second_record_id(store, scope, namespace),
            ),
        )
    if request.screen == "candidates":
        return build_candidate_review_screen(
            store,
            CandidateListOptions(status="proposed", limit=25),
        )
    if request.screen == "views":
        return build_saved_view_workbench_screen(
            store,
            SavedViewWorkbenchRequest(
                scopes=[scope],
                namespaces=namespaces,
                definitions=[
                    SavedViewDefinition(
                        view_id="preview-records",
                        name="Preview Records",
                        summaries=[SavedViewSummary("count")],
                    )
                ],
            ),
        )
    if request.screen == "timeline":
        return build_timeline_screen(
            store,
            ListQueryOptions(
                scopes=[scope],
                namespaces=namespaces,
                include_invalidated=True,
            ),
        )
    if request.screen == "schema":
        records = store.list_records(ListQueryOptions(scopes=[scope], namespaces=namespaces))
        return build_schema_developer_screen(
            records=records,
            links=store.list_links(LinkQueryOptions(namespaces=namespaces)),
            blocks=store.list_document_blocks(record_id=record_id),
            backend_capabilities={"preview": True},
            structural_result=None,
        )
    return build_explorer_screen(
        store,
        KnowledgeExplorerRequest(
            scopes=[scope],
            namespaces=namespaces,
            query=request.query,
            root_record_id=record_id,
        ),
    )


def _first_record_id(
    store: object,
    scope: str,
    namespace: MemoryNamespace,
) -> str | None:
    records = store.list_records(ListQueryOptions(scopes=[scope], namespaces=[namespace]))
    return records[0].id if records else None


def _second_record_id(
    store: object,
    scope: str,
    namespace: MemoryNamespace,
) -> str | None:
    records = store.list_records(ListQueryOptions(scopes=[scope], namespaces=[namespace]))
    return records[1].id if len(records) > 1 else None


def _seed_demo_store(
    store: SophiaGraphMemoryStore,
    *,
    namespace: MemoryNamespace,
    scope: str,
) -> None:
    auth = _demo_record(
        "auth-decision",
        "Auth Decision",
        "Use JWT auth for the operator console.",
        namespace=namespace,
        scope=scope,
    )
    refresh = _demo_record(
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


def _demo_record(
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
    "PreviewScreen",
    "UiPreviewRender",
    "UiPreviewRequest",
    "UiPreviewResult",
    "make_ui_preview_server",
    "render_ui_preview",
    "serve_ui_preview",
    "write_ui_preview",
]
