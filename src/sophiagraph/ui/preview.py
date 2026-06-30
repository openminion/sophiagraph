"""Public local UI preview entrypoints for the package-owned SophiaGraph UI."""

from __future__ import annotations

from graphfakos import GraphPreviewOutputPaths, write_provider_preview_outputs
from graphfakos.server import (
    LocalViewerHttpServer as LocalVisualHttpServer,
    LocalViewerServerResult as LocalVisualServerResult,
    make_local_viewer_server,
    serve_local_viewer,
)
from graphfakos.static import render_static_html

from .graphfakos_adapter import SophiagraphViewerProvider
from .preview_support import (
    first_record_id,
    graphfakos_request,
    render_server_preview_path,
    store_for_request,
)
from .preview_types import (
    PreviewScreen,
    UiPreviewRender,
    UiPreviewRequest,
    UiPreviewResult,
)


def write_ui_preview(request: UiPreviewRequest) -> UiPreviewResult:
    store, namespace, scope = store_for_request(request)
    record_id = request.record_id or first_record_id(store, scope, namespace)
    provider = SophiagraphViewerProvider(
        store=store,
        scope=scope,
        namespace=namespace,
    )
    graph_request = graphfakos_request(request, record_id=record_id)
    payload = write_provider_preview_outputs(
        provider,
        graph_request,
        GraphPreviewOutputPaths(
            html_path=request.output_path,
            artifact_path=request.artifact_path,
            embed_path=request.embed_path,
            report_path=request.report_path,
            markdown_report_path=request.markdown_report_path,
        ),
        open_browser=request.open_browser,
    )
    return UiPreviewResult(
        output_path=str(payload["output_path"]),
        screen=str(payload["screen"]),
        workspace=request.workspace,
        record_count=store.record_count(),
        provider_id=str(payload["provider_id"]),
        node_count=int(payload["node_count"]),
        edge_count=int(payload["edge_count"]),
        route=str(payload["route"]),
        artifact=payload.get("artifact"),
        embed=payload.get("embed"),
        report=payload.get("report"),
        markdown_report=payload.get("markdown_report"),
        opened=bool(payload["opened"]),
    )


def render_ui_preview(request: UiPreviewRequest) -> UiPreviewRender:
    store, namespace, scope = store_for_request(request)
    record_id = request.record_id or first_record_id(store, scope, namespace)
    provider = SophiagraphViewerProvider(
        store=store,
        scope=scope,
        namespace=namespace,
    )
    graph_request = graphfakos_request(request, record_id=record_id)
    return UiPreviewRender(
        html=render_static_html(provider, graph_request),
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
    return make_local_viewer_server(
        render_path=lambda path, query: render_server_preview_path(
            request, path, query
        ),
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
    return serve_local_viewer(
        render_path=lambda path, query: render_server_preview_path(
            request, path, query
        ),
        default_path=f"/{request.screen}",
        host=host,
        port=port,
        open_browser=request.open_browser,
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
