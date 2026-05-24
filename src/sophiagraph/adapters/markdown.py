"""Structural Markdown/frontmatter adapter for knowledge documents."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any
from uuid import uuid5, NAMESPACE_URL

from sophiagraph.models import MemoryNamespace
from sophiagraph.models.document import (
    KnowledgeDocument,
    KnowledgeDocumentBlock,
    content_hash,
)
from sophiagraph.models.link import (
    ExplicitLinkResolver,
    LinkResolutionCandidate,
    StructuralLink,
    split_target_parts,
)


@dataclass(frozen=True)
class MarkdownProperty:
    name: str
    value: str | int | float | bool | list[str]


@dataclass(frozen=True)
class MarkdownImport:
    document: KnowledgeDocument
    body: str
    properties: list[MarkdownProperty] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    links: list[StructuralLink] = field(default_factory=list)
    blocks: list[KnowledgeDocumentBlock] = field(default_factory=list)


_FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n?", re.DOTALL)
_WIKILINK_RE = re.compile(r"(!)?\[\[([^\]]+)\]\]")
_MARKDOWN_LINK_RE = re.compile(r"(?<!!)\[([^\]]+)\]\(([^)]+)\)")
_TAG_RE = re.compile(r"(?<![\w/])#([A-Za-z0-9_/-]+)")
_URL_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*://")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_BLOCK_ID_RE = re.compile(r"\^([A-Za-z0-9_-]+)")


def _stable_id(prefix: str, value: str) -> str:
    return f"{prefix}-{uuid5(NAMESPACE_URL, value)}"


def _parse_scalar(value: str) -> str | int | float | bool | list[str]:
    stripped = value.strip()
    if stripped.lower() in {"true", "false"}:
        return stripped.lower() == "true"
    if stripped.startswith("[") and stripped.endswith("]"):
        inner = stripped[1:-1].strip()
        if not inner:
            return []
        return [part.strip().strip('"').strip("'") for part in inner.split(",")]
    try:
        return int(stripped)
    except ValueError:
        pass
    try:
        return float(stripped)
    except ValueError:
        return stripped.strip('"').strip("'")


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    frontmatter: dict[str, Any] = {}
    for raw_line in match.group(1).splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        frontmatter[key.strip()] = _parse_scalar(value)
    return frontmatter, text[match.end() :]


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    return [str(value)] if str(value) else []


def _bounded_context(text: str, start: int, end: int, size: int) -> tuple[str, str]:
    before = text[max(0, start - size) : start]
    after = text[end : min(len(text), end + size)]
    return before, after


def parse_markdown_links(
    body: str,
    *,
    source_record_id: str,
    namespace: MemoryNamespace,
    source_path: str | None = None,
    resolver: ExplicitLinkResolver | None = None,
    context_chars: int = 80,
) -> list[StructuralLink]:
    """Parse explicit Markdown links only; unlinked mentions are ignored."""
    links: list[StructuralLink] = []
    for match in _WIKILINK_RE.finditer(body):
        raw = match.group(2).strip()
        target_part, heading, block_id = split_target_parts(raw.split("|", 1)[0])
        display = raw.split("|", 1)[1].strip() if "|" in raw else None
        resolution = (
            resolver.resolve(target_part, namespace=namespace)
            if resolver is not None
            else None
        )
        before, after = _bounded_context(
            body, match.start(), match.end(), context_chars
        )
        status = resolution.status if resolution is not None else "unresolved"
        links.append(
            StructuralLink(
                link_id=_stable_id("link", f"{source_record_id}:{match.start()}"),
                source_record_id=source_record_id,
                source_path=source_path,
                raw_target=raw,
                link_kind="embed" if match.group(1) else "wikilink",
                resolution_status=status,
                target_record_id=resolution.target_record_id
                if resolution is not None
                else None,
                target_path=resolution.target_path if resolution is not None else None,
                target_heading=heading,
                target_block_id=block_id,
                display_text=display,
                original=match.group(0),
                start=match.start(),
                end=match.end(),
                context_before=before,
                context_after=after,
                namespace=namespace,
            )
        )
    for match in _MARKDOWN_LINK_RE.finditer(body):
        label = match.group(1).strip()
        raw = match.group(2).strip()
        is_external = bool(_URL_RE.match(raw))
        resolution = (
            None
            if is_external or resolver is None
            else resolver.resolve(raw, namespace=namespace)
        )
        before, after = _bounded_context(
            body, match.start(), match.end(), context_chars
        )
        links.append(
            StructuralLink(
                link_id=_stable_id("link", f"{source_record_id}:{match.start()}"),
                source_record_id=source_record_id,
                source_path=source_path,
                raw_target=raw,
                link_kind="external" if is_external else "markdown",
                resolution_status="external"
                if is_external
                else (resolution.status if resolution is not None else "unresolved"),
                target_record_id=resolution.target_record_id
                if resolution is not None
                else None,
                target_path=resolution.target_path if resolution is not None else None,
                display_text=label,
                original=match.group(0),
                start=match.start(),
                end=match.end(),
                context_before=before,
                context_after=after,
                namespace=namespace,
            )
        )
    return sorted(links, key=lambda link: link.start or 0)


def parse_markdown_blocks(
    body: str,
    *,
    document_id: str,
    record_id: str,
) -> list[KnowledgeDocumentBlock]:
    """Parse explicit headings and block IDs into addressable block rows."""
    blocks: list[KnowledgeDocumentBlock] = []
    for line_number, line in enumerate(body.splitlines(), start=1):
        heading = _HEADING_RE.match(line)
        if heading:
            text = heading.group(2).strip()
            anchor = re.sub(r"[^a-z0-9 -]", "", text.lower())
            anchor = re.sub(r"\s+", "-", anchor.strip())
            blocks.append(
                KnowledgeDocumentBlock(
                    block_id=_stable_id("block", f"{document_id}:heading:{anchor}"),
                    document_id=document_id,
                    record_id=record_id,
                    block_type="heading",
                    anchor=anchor,
                    content_hash=content_hash(line),
                    line_start=line_number,
                    line_end=line_number,
                    excerpt=line,
                )
            )
        for block_match in _BLOCK_ID_RE.finditer(line):
            block_id = block_match.group(1)
            blocks.append(
                KnowledgeDocumentBlock(
                    block_id=block_id,
                    document_id=document_id,
                    record_id=record_id,
                    block_type="block",
                    anchor=block_id,
                    content_hash=content_hash(line),
                    line_start=line_number,
                    line_end=line_number,
                    excerpt=line,
                )
            )
    return blocks


def extract_markdown(
    text: str,
    *,
    path: str,
    record_id: str,
    namespace: MemoryNamespace,
    resolver_candidates: list[LinkResolutionCandidate] | None = None,
) -> MarkdownImport:
    """Extract explicit frontmatter, tags, aliases, and links without prose edits."""
    frontmatter, body = _parse_frontmatter(text)
    title = str(frontmatter.get("title") or path.rsplit("/", 1)[-1].removesuffix(".md"))
    aliases = _string_list(frontmatter.get("aliases") or frontmatter.get("alias"))
    frontmatter_tags = [
        _tag.strip("#").lower() for _tag in _string_list(frontmatter.get("tags"))
    ]
    inline_tags = [match.group(1).lower() for match in _TAG_RE.finditer(body)]
    tags = sorted(set(frontmatter_tags + inline_tags))
    document = KnowledgeDocument(
        document_id=_stable_id("doc", path),
        record_id=record_id,
        path=path,
        title=title,
        aliases=aliases,
        content_hash=content_hash(body),
        source_format="markdown",
        namespace=namespace,
        provenance={"adapter": "markdown"},
    )
    properties = [
        MarkdownProperty(name=str(key), value=value)
        for key, value in frontmatter.items()
        if key not in {"title", "alias", "aliases", "tags"}
    ]
    resolver = (
        ExplicitLinkResolver(resolver_candidates)
        if resolver_candidates is not None
        else None
    )
    links = parse_markdown_links(
        body,
        source_record_id=record_id,
        namespace=namespace,
        source_path=path,
        resolver=resolver,
    )
    blocks = parse_markdown_blocks(
        body,
        document_id=document.document_id,
        record_id=record_id,
    )
    return MarkdownImport(
        document=document,
        body=body,
        properties=properties,
        tags=tags,
        links=links,
        blocks=blocks,
    )


def export_markdown(imported: MarkdownImport) -> str:
    """Export supported frontmatter and original body without changing prose."""
    frontmatter: dict[str, Any] = {
        "title": imported.document.title,
    }
    if imported.document.aliases:
        frontmatter["aliases"] = imported.document.aliases
    if imported.tags:
        frontmatter["tags"] = imported.tags
    for prop in imported.properties:
        frontmatter[prop.name] = prop.value
    lines = ["---"]
    for key, value in frontmatter.items():
        if isinstance(value, list):
            rendered = "[" + ", ".join(str(item) for item in value) + "]"
        elif isinstance(value, bool):
            rendered = "true" if value else "false"
        else:
            rendered = str(value)
        lines.append(f"{key}: {rendered}")
    lines.append("---")
    return "\n".join(lines) + "\n" + imported.body


__all__ = [
    "MarkdownImport",
    "MarkdownProperty",
    "extract_markdown",
    "export_markdown",
    "parse_markdown_blocks",
    "parse_markdown_links",
]
