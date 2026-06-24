"""Public local UI preview entrypoints for the package-owned SophiaGraph UI."""

from __future__ import annotations

from pathlib import Path
import webbrowser

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
