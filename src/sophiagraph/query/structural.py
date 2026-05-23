"""Obsidian-inspired structural search DTOs and parser."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Literal

from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.models import MemoryNamespace

StructuralSort = Literal["title", "path", "created", "updated", "degree"]


@dataclass(frozen=True, slots=True)
class StructuralSearchQuery:
    text_terms: list[str] = field(default_factory=list)
    exact_phrases: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    properties: dict[str, str] = field(default_factory=dict)
    path: str | None = None
    file: str | None = None
    content: str | None = None
    block: str | None = None
    section: str | None = None
    task: str | None = None
    link_to: str | None = None
    linked_from: str | None = None
    relation_type: str | None = None
    namespaces: list[MemoryNamespace] | None = None
    sort: StructuralSort | None = None
    limit: int | None = None

    def __post_init__(self) -> None:
        if self.limit is not None and self.limit <= 0:
            raise InvalidArgumentError("limit must be positive")


_TOKEN_RE = re.compile(r'"[^"]+"|\[[^\]]+:[^\]]+\]|\S+')
_KNOWN_PREFIXES = {
    "path",
    "file",
    "content",
    "block",
    "section",
    "task",
    "link_to",
    "linked_from",
    "relation_type",
    "sort",
    "tag",
}


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        return value[1:-1]
    return value


def _normalize_tag(value: str) -> str:
    return value.lstrip("#").strip().lower()


def parse_structural_query(query: str) -> StructuralSearchQuery:
    """Parse a deterministic structural query without semantic rewriting."""
    if not str(query or "").strip():
        raise InvalidArgumentError("query is required")
    text_terms: list[str] = []
    exact_phrases: list[str] = []
    tags: list[str] = []
    properties: dict[str, str] = {}
    fields: dict[str, str] = {}
    for token in _TOKEN_RE.findall(query):
        if token.startswith('"') and token.endswith('"'):
            exact_phrases.append(_strip_quotes(token))
            continue
        if token.startswith("[") and token.endswith("]") and ":" in token:
            key, value = token[1:-1].split(":", 1)
            if not key or not value:
                raise InvalidArgumentError(f"invalid property filter: {token!r}")
            properties[key.strip()] = value.strip()
            continue
        if token.startswith("#"):
            tags.append(_normalize_tag(token))
            continue
        if ":" in token:
            key, value = token.split(":", 1)
            if key not in _KNOWN_PREFIXES:
                raise InvalidArgumentError(f"unsupported structural operator: {key}")
            if not value:
                raise InvalidArgumentError(f"{key} value is required")
            if key == "tag":
                tags.append(_normalize_tag(value))
            else:
                fields[key] = value
            continue
        text_terms.append(token)
    sort = fields.get("sort")
    if sort is not None and sort not in {
        "title",
        "path",
        "created",
        "updated",
        "degree",
    }:
        raise InvalidArgumentError(f"invalid sort: {sort!r}")
    return StructuralSearchQuery(
        text_terms=text_terms,
        exact_phrases=exact_phrases,
        tags=tags,
        properties=properties,
        path=fields.get("path"),
        file=fields.get("file"),
        content=fields.get("content"),
        block=fields.get("block"),
        section=fields.get("section"),
        task=fields.get("task"),
        link_to=fields.get("link_to"),
        linked_from=fields.get("linked_from"),
        relation_type=fields.get("relation_type"),
        sort=sort,  # type: ignore[arg-type]
    )


__all__ = ["StructuralSearchQuery", "StructuralSort", "parse_structural_query"]
