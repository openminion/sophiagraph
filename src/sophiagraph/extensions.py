"""Dependency-light extension hooks for import/export/query adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from sophiagraph.contracts.errors import InvalidArgumentError


class Importer(Protocol):
    def __call__(self, payload: str, **kwargs: Any) -> Any: ...


class Exporter(Protocol):
    def __call__(self, payload: Any, **kwargs: Any) -> str: ...


class ViewEvaluator(Protocol):
    def __call__(self, records: list[Any], definition: Any) -> Any: ...


class RelationCodec(Protocol):
    def __call__(self, payload: Any) -> Any: ...


@dataclass(slots=True)
class SophiaGraphExtensionRegistry:
    importers: dict[str, Importer] = field(default_factory=dict)
    exporters: dict[str, Exporter] = field(default_factory=dict)
    view_evaluators: dict[str, ViewEvaluator] = field(default_factory=dict)
    relation_codecs: dict[str, RelationCodec] = field(default_factory=dict)

    def register_importer(self, name: str, importer: Importer) -> None:
        self.importers[_name(name)] = importer

    def register_exporter(self, name: str, exporter: Exporter) -> None:
        self.exporters[_name(name)] = exporter

    def register_view_evaluator(self, name: str, evaluator: ViewEvaluator) -> None:
        self.view_evaluators[_name(name)] = evaluator

    def register_relation_codec(self, name: str, codec: RelationCodec) -> None:
        self.relation_codecs[_name(name)] = codec


def _name(value: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise InvalidArgumentError("extension name is required")
    return normalized


__all__ = [
    "Exporter",
    "Importer",
    "RelationCodec",
    "SophiaGraphExtensionRegistry",
    "ViewEvaluator",
]
