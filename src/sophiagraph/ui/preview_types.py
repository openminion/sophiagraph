"""Typed request and result contracts for local UI preview helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

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


__all__ = [
    "PreviewScreen",
    "UiPreviewRender",
    "UiPreviewRequest",
    "UiPreviewResult",
]
