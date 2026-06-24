"""Internal OKF bundle mechanics shared by import, export, and navigation."""

from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
from pathlib import Path, PurePosixPath
import re
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from sophiagraph.adapters.markdown import MarkdownImport, extract_markdown
from sophiagraph.contracts.errors import InvalidArgumentError, NotFoundError
from sophiagraph.models import (
    ExplicitLinkResolver,
    LinkResolutionCandidate,
    MemoryNamespace,
    StructuralLink,
    split_target_parts,
)
from sophiagraph.models.okf import (
    OkfCitation,
    OkfConceptDocument,
    OkfConceptProfile,
    OkfConformanceFinding,
    OkfIndexEntry,
    OkfLogEntry,
)

CITATIONS_HEADING_RE = re.compile(r"^(#{1,6})\s+Citations\s*$", re.IGNORECASE)
LIST_ITEM_RE = re.compile(r"^\s*(?:[-*]|\d+\.)\s+(.*)$")
MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
ROOT_LINK_RE = re.compile(r"(\]\()\/([^)/][^)]+)\)")


def stable_id(prefix: str, *parts: str) -> str:
    return f"{prefix}-{uuid5(NAMESPACE_URL, ':'.join(parts))}"


def bundle_id(root: Path) -> str:
    return sha256(str(root.resolve()).encode("utf-8")).hexdigest()[:16]


def bundle_relative(path: str) -> str:
    normalized = str(PurePosixPath(str(path or "").replace("\\", "/")))
    if not normalized or normalized == ".":
        raise InvalidArgumentError("path is required")
    if normalized.startswith("../") or ".." in normalized.split("/"):
        raise InvalidArgumentError("path cannot traverse parents")
    return normalized.lstrip("/")


def read_markdown_files(bundle_root: Path) -> dict[str, str]:
    if not bundle_root.is_dir():
        raise NotFoundError(f"bundle root not found: {bundle_root}")
    payloads: dict[str, str] = {}
    for path in sorted(bundle_root.rglob("*.md")):
        relative = path.relative_to(bundle_root).as_posix()
        payloads[relative] = path.read_text(encoding="utf-8")
    if not payloads:
        raise InvalidArgumentError("bundle root does not contain markdown files")
    return payloads


def frontmatter_dict(imported: MarkdownImport) -> dict[str, Any]:
    frontmatter: dict[str, Any] = {"title": imported.document.title}
    if imported.document.aliases:
        frontmatter["aliases"] = list(imported.document.aliases)
    if imported.tags:
        frontmatter["tags"] = list(imported.tags)
    for prop in imported.properties:
        frontmatter[prop.name] = prop.value
    return frontmatter


def document_kind(path: str) -> str:
    if PurePosixPath(path).name == "index.md":
        return "index"
    if PurePosixPath(path).name == "log.md":
        return "log"
    if path.startswith("references/"):
        return "reference"
    return "concept"


def profile_from_frontmatter(frontmatter: dict[str, Any]) -> OkfConceptProfile:
    extensions = {
        key: value
        for key, value in frontmatter.items()
        if key
        not in {
            "type",
            "title",
            "description",
            "resource",
            "tags",
            "timestamp",
            "okf_version",
        }
    }
    return OkfConceptProfile(
        concept_type=str(frontmatter.get("type") or ""),
        title=str(frontmatter["title"]) if frontmatter.get("title") else None,
        description=(
            str(frontmatter["description"]) if frontmatter.get("description") else None
        ),
        resource=str(frontmatter["resource"]) if frontmatter.get("resource") else None,
        tags=[str(item) for item in frontmatter.get("tags", [])]
        if isinstance(frontmatter.get("tags"), list)
        else ([str(frontmatter["tags"])] if frontmatter.get("tags") else []),
        timestamp=str(frontmatter["timestamp"])
        if frontmatter.get("timestamp")
        else None,
        okf_version=(
            str(frontmatter["okf_version"]) if frontmatter.get("okf_version") else None
        ),
        extensions=extensions,
    )


def build_candidates(
    markdown_by_path: dict[str, str],
    *,
    namespace: MemoryNamespace,
    bundle_root_id: str,
) -> list[LinkResolutionCandidate]:
    candidates: list[LinkResolutionCandidate] = []
    for path, text in markdown_by_path.items():
        record_id = stable_id("okf-rec", bundle_root_id, path)
        imported = extract_markdown(
            text,
            path=path,
            record_id=record_id,
            namespace=namespace,
        )
        candidates.append(
            LinkResolutionCandidate(
                record_id=record_id,
                path=path,
                title=imported.document.title,
                aliases=imported.document.aliases,
                namespace=namespace,
            )
        )
    return candidates


def resolve_bundle_target(source_path: str, raw_target: str) -> str | None:
    candidate = raw_target.split("|", 1)[0].split("#", 1)[0].strip()
    if not candidate or re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", candidate):
        return None
    pure = PurePosixPath(candidate)
    if candidate.startswith("/"):
        return bundle_relative(candidate)
    source_dir = PurePosixPath(source_path).parent
    return bundle_relative(str(source_dir / pure))


def normalize_okf_links(
    imported: MarkdownImport,
    *,
    source_path: str,
    candidates: list[LinkResolutionCandidate],
) -> list[StructuralLink]:
    resolver = ExplicitLinkResolver(candidates)
    normalized: list[StructuralLink] = []
    for link in imported.links:
        if link.link_kind == "external":
            normalized.append(link)
            continue
        bundle_target = resolve_bundle_target(source_path, link.raw_target)
        resolved = resolver.resolve(
            bundle_target or link.raw_target,
            namespace=imported.document.namespace,
        )
        _, heading, block_id = split_target_parts(
            (bundle_target or link.raw_target).split("|", 1)[0]
        )
        normalized.append(
            replace(
                link,
                raw_target=bundle_target or link.raw_target,
                resolution_status=resolved.status,
                target_record_id=resolved.target_record_id,
                target_path=resolved.target_path,
                target_heading=link.target_heading or heading,
                target_block_id=link.target_block_id or block_id,
                meta={
                    **dict(link.meta),
                    "ambiguous_record_ids": list(resolved.ambiguous_record_ids),
                },
            )
        )
    return normalized


def extract_citations(body: str, *, source_path: str) -> list[OkfCitation]:
    citations: list[OkfCitation] = []
    lines = body.splitlines()
    in_section = False
    current_section = "Citations"
    for index, line in enumerate(lines, start=1):
        if CITATIONS_HEADING_RE.match(line):
            in_section = True
            current_section = line.lstrip("#").strip()
            continue
        if in_section and line.startswith("#"):
            break
        if not in_section:
            continue
        item_match = LIST_ITEM_RE.match(line)
        if not item_match:
            continue
        item = item_match.group(1).strip()
        link_match = MARKDOWN_LINK_RE.search(item)
        if link_match:
            label = link_match.group(1).strip()
            target = link_match.group(2).strip()
        else:
            label = None
            target = item
        target_kind = (
            "external"
            if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", target)
            else "bundle_path"
        )
        if target_kind == "bundle_path":
            target = resolve_bundle_target(source_path, target) or bundle_relative(
                target
            )
        citations.append(
            OkfCitation(
                citation_id=stable_id("okf-citation", source_path, str(index), target),
                target=target,
                target_kind=target_kind,
                source_path=source_path,
                source_section=current_section,
                label=label,
                line_number=index,
            )
        )
    return citations


def extract_index_entries(body: str, *, source_path: str) -> list[OkfIndexEntry]:
    entries: list[OkfIndexEntry] = []
    for line in body.splitlines():
        item_match = LIST_ITEM_RE.match(line)
        if not item_match:
            continue
        item = item_match.group(1).strip()
        link_match = MARKDOWN_LINK_RE.search(item)
        if link_match:
            label = link_match.group(1).strip()
            target = resolve_bundle_target(source_path, link_match.group(2).strip())
            description = item[link_match.end() :].lstrip(" :-") or None
            entries.append(
                OkfIndexEntry(label=label, target_path=target, description=description)
            )
        else:
            entries.append(OkfIndexEntry(label=item))
    return entries


def extract_log_entries(body: str) -> list[OkfLogEntry]:
    entries: list[OkfLogEntry] = []
    for index, line in enumerate(body.splitlines(), start=1):
        item_match = LIST_ITEM_RE.match(line)
        if not item_match:
            continue
        entries.append(OkfLogEntry(text=item_match.group(1).strip(), line_number=index))
    return entries


def findings_for_document(
    *,
    path: str,
    kind: str,
    frontmatter: dict[str, Any],
    body: str,
    bundle_paths: set[str],
    links: list[StructuralLink],
) -> list[OkfConformanceFinding]:
    findings: list[OkfConformanceFinding] = []
    if kind in {"concept", "reference"} and not frontmatter.get("type"):
        findings.append(
            OkfConformanceFinding(
                code="missing_type",
                severity="error",
                path=path,
                message="concept documents require frontmatter field `type`",
            )
        )
    if kind in {"index", "log"} and frontmatter.get("type"):
        findings.append(
            OkfConformanceFinding(
                code="reserved_frontmatter_type",
                severity="warning",
                path=path,
                message="reserved index/log files should not be treated as concept documents",
            )
        )
    if not body.strip():
        findings.append(
            OkfConformanceFinding(
                code="empty_body",
                severity="warning",
                path=path,
                message="document body is empty",
            )
        )
    for link in links:
        if link.link_kind == "external":
            continue
        raw_target = link.raw_target.split("#", 1)[0]
        if (
            raw_target
            and raw_target not in bundle_paths
            and link.resolution_status == "unresolved"
        ):
            findings.append(
                OkfConformanceFinding(
                    code="unresolved_link",
                    severity="warning",
                    path=path,
                    message=f"unresolved bundle link: {link.raw_target}",
                    line_number=(link.start or 0) + 1
                    if link.start is not None
                    else None,
                )
            )
    return findings


def render_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return "[" + ", ".join(str(item) for item in value) + "]"
    return str(value)


def frontmatter_lines(frontmatter: dict[str, Any]) -> list[str]:
    lines = ["---"]
    for key, value in frontmatter.items():
        lines.append(f"{key}: {render_scalar(value)}")
    lines.append("---")
    return lines


def bundle_relative_markdown_target(link: StructuralLink) -> str | None:
    path = link.target_path
    if not path:
        return None
    target = "/" + bundle_relative(path)
    if link.target_heading:
        target += f"#{link.target_heading}"
    elif link.target_block_id:
        target += f"#^{link.target_block_id}"
    return target


def obsidian_target(link: StructuralLink) -> str | None:
    if not link.target_path:
        return None
    target = link.target_path
    if link.target_heading:
        target += f"#{link.target_heading}"
    elif link.target_block_id:
        target += f"#^{link.target_block_id}"
    return target


def render_link(link: StructuralLink, *, obsidian_compatible: bool) -> str:
    if link.link_kind == "external":
        label = link.display_text or link.raw_target
        return f"[{label}]({link.raw_target})"
    target = (
        obsidian_target(link)
        if obsidian_compatible
        else bundle_relative_markdown_target(link)
    )
    if target is None:
        return link.original or (
            f"[[{link.raw_target}]]"
            if obsidian_compatible
            else f"[{link.display_text or link.raw_target}]({link.raw_target})"
        )
    if obsidian_compatible:
        display = f"|{link.display_text}" if link.display_text else ""
        prefix = "!" if link.link_kind == "embed" else ""
        return f"{prefix}[[{target}{display}]]"
    label = link.display_text or link.raw_target.split("#", 1)[0].rsplit("/", 1)[
        -1
    ].removesuffix(".md")
    if link.link_kind == "embed":
        return f"![{label}]({target})"
    return f"[{label}]({target})"


def rewrite_body(
    body: str,
    links: list[StructuralLink],
    *,
    obsidian_compatible: bool,
) -> str:
    rewritten = body
    ranged_links = [
        item for item in links if item.start is not None and item.end is not None
    ]
    for link in sorted(ranged_links, key=lambda item: item.start or 0, reverse=True):
        replacement = render_link(link, obsidian_compatible=obsidian_compatible)
        rewritten = rewritten[: link.start] + replacement + rewritten[link.end :]
    return rewritten


def frontmatter_for_concept(document: OkfConceptDocument) -> dict[str, Any]:
    frontmatter: dict[str, Any] = {}
    if document.profile.concept_type:
        frontmatter["type"] = document.profile.concept_type
    if document.profile.title:
        frontmatter["title"] = document.profile.title
    if document.document.aliases:
        frontmatter["aliases"] = list(document.document.aliases)
    if document.profile.description:
        frontmatter["description"] = document.profile.description
    if document.profile.resource:
        frontmatter["resource"] = document.profile.resource
    if document.profile.tags:
        frontmatter["tags"] = list(document.profile.tags)
    if document.profile.timestamp:
        frontmatter["timestamp"] = document.profile.timestamp
    if document.profile.okf_version:
        frontmatter["okf_version"] = document.profile.okf_version
    for key, value in document.profile.extensions.items():
        frontmatter[key] = value
    return frontmatter


def render_document(*, frontmatter: dict[str, Any], body: str) -> str:
    return "\n".join(frontmatter_lines(frontmatter)) + "\n" + body
