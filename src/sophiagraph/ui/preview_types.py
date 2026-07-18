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
    source_root: str | None = None
    output_path: str = "sophiagraph-ui-preview.html"
    artifact_path: str = ""
    embed_path: str = ""
    report_path: str = ""
    markdown_report_path: str = ""
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
    source_root: str | None
    record_count: int
    provider_id: str
    node_count: int
    edge_count: int
    route: str
    artifact: dict[str, object] | None = None
    embed: dict[str, object] | None = None
    report: dict[str, object] | None = None
    markdown_report: dict[str, object] | None = None
    opened: bool = False

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "output_path": self.output_path,
            "screen": self.screen,
            "workspace": self.workspace,
            "source_root": self.source_root,
            "record_count": self.record_count,
            "provider_id": self.provider_id,
            "node_count": self.node_count,
            "edge_count": self.edge_count,
            "route": self.route,
            "opened": self.opened,
        }
        if self.artifact is not None:
            payload["artifact"] = self.artifact
        if self.embed is not None:
            payload["embed"] = self.embed
        if self.report is not None:
            payload["report"] = self.report
        if self.markdown_report is not None:
            payload["markdown_report"] = self.markdown_report
        return payload


@dataclass(frozen=True, slots=True)
class UiPreviewRender:
    html: str
    screen: str
    workspace: str | None
    source_root: str | None
    record_count: int


__all__ = [
    "PreviewScreen",
    "UiPreviewRender",
    "UiPreviewRequest",
    "UiPreviewResult",
]
