"""Compatibility exports for GraphFakos local viewer server primitives."""

from __future__ import annotations

from graphfakos.server import (
    LocalViewerHttpServer as LocalVisualHttpServer,
    LocalViewerServerResult as LocalVisualServerResult,
    RenderPath,
    make_local_viewer_server as make_local_visual_server,
    serve_local_viewer as serve_local_visual_server,
)

__all__ = [
    "LocalVisualHttpServer",
    "LocalVisualServerResult",
    "RenderPath",
    "make_local_visual_server",
    "serve_local_visual_server",
]
