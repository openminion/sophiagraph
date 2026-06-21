"""Open Knowledge Format profile helpers over the SophiaGraph document substrate."""

from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
from pathlib import Path, PurePosixPath
import re
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from sophiagraph.adapters.markdown import (
    MarkdownImport,
    extract_markdown,
)
from sophiagraph.contracts.errors import InvalidArgumentError, NotFoundError
from sophiagraph.models import (
    ExplicitLinkResolver,
    LinkResolutionCandidate,
    MemoryNamespace,
    StructuralLink,
    split_target_parts,
)
from sophiagraph.models.okf import (
    OKF_SPEC_BASELINE_COMMIT,
    OKF_SPEC_BASELINE_URL,
    OkfBundle,
    OkfBundleManifest,
    OkfCitation,
    OkfConceptDocument,
    OkfConceptProfile,
    OkfConformanceFinding,
    OkfIndexDocument,
    OkfIndexEntry,
    OkfLogDocument,
    OkfLogEntry,
    OkfNavigationPacket,
)
from sophiagraph.query import KnowledgeContextExcerpt, UnlinkedMentionCandidate
from sophiagraph.storage.record_lifecycle import utc_now_iso
from sophiagraph.vault import (
    VaultFilePayload,
    VaultImportOptions,
    VaultImportResult,
    VaultStore,
    import_vault_files,
)

_CITATIONS_HEADING_RE = re.compile(r"^(#{1,6})\s+Citations\s*$", re.IGNORECASE)
_LIST_ITEM_RE = re.compile(r"^\s*(?:[-*]|\d+\.)\s+(.*)$")
_MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_ROOT_LINK_RE = re.compile(r"(\]\()\/([^)/][^)]+)\)")
_WORD_CHARS = re.compile(r"[A-Za-z0-9_]")


def _stable_id(prefix: str, *parts: str) -> str:
    return f"{prefix}-{uuid5(NAMESPACE_URL, ':'.join(parts))}"


def _bundle_id(root: Path) -> str:
    return sha256(str(root.resolve()).encode("utf-8")).hexdigest()[:16]


def _bundle_relative(path: str) -> str:
    normalized = str(PurePosixPath(str(path or "").replace("\\", "/")))
    if not normalized or normalized == ".":
        raise InvalidArgumentError("path is required")
    if normalized.startswith("../") or ".." in normalized.split("/"):
        raise InvalidArgumentError("path cannot traverse parents")
    return normalized.lstrip("/")


def _read_markdown_files(bundle_root: Path) -> dict[str, str]:
    if not bundle_root.is_dir():
        raise NotFoundError(f"bundle root not found: {bundle_root}")
    payloads: dict[str, str] = {}
    for path in sorted(bundle_root.rglob("*.md")):
        relative = path.relative_to(bundle_root).as_posix()
        payloads[relative] = path.read_text(encoding="utf-8")
    if not payloads:
        raise InvalidArgumentError("bundle root does not contain markdown files")
    return payloads


def _frontmatter_dict(imported: MarkdownImport) -> dict[str, Any]:
    frontmatter: dict[str, Any] = {"title": imported.document.title}
    if imported.document.aliases:
        frontmatter["aliases"] = list(imported.document.aliases)
    if imported.tags:
        frontmatter["tags"] = list(imported.tags)
    for prop in imported.properties:
        frontmatter[prop.name] = prop.value
    return frontmatter


def _document_kind(path: str) -> str:
    if PurePosixPath(path).name == "index.md":
        return "index"
    if PurePosixPath(path).name == "log.md":
        return "log"
    if path.startswith("references/"):
        return "reference"
    return "concept"


def _profile_from_frontmatter(frontmatter: dict[str, Any]) -> OkfConceptProfile:
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


def _build_candidates(
    markdown_by_path: dict[str, str],
    *,
    namespace: MemoryNamespace,
    bundle_id: str,
) -> list[LinkResolutionCandidate]:
    candidates: list[LinkResolutionCandidate] = []
    for path, text in markdown_by_path.items():
        record_id = _stable_id("okf-rec", bundle_id, path)
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


def _resolve_bundle_target(source_path: str, raw_target: str) -> str | None:
    candidate = raw_target.split("|", 1)[0].split("#", 1)[0].strip()
    if not candidate or re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", candidate):
        return None
    pure = PurePosixPath(candidate)
    if candidate.startswith("/"):
        return _bundle_relative(candidate)
    source_dir = PurePosixPath(source_path).parent
    return _bundle_relative(str(source_dir / pure))


def _normalize_okf_links(
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
        bundle_target = _resolve_bundle_target(source_path, link.raw_target)
        resolved = resolver.resolve(
            bundle_target or link.raw_target,
            namespace=imported.document.namespace,
        )
        target_part, heading, block_id = split_target_parts(
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


def _extract_citations(body: str, *, source_path: str) -> list[OkfCitation]:
    citations: list[OkfCitation] = []
    lines = body.splitlines()
    in_section = False
    current_section = "Citations"
    for index, line in enumerate(lines, start=1):
        if _CITATIONS_HEADING_RE.match(line):
            in_section = True
            current_section = line.lstrip("#").strip()
            continue
        if in_section and line.startswith("#"):
            break
        if not in_section:
            continue
        item_match = _LIST_ITEM_RE.match(line)
        if not item_match:
            continue
        item = item_match.group(1).strip()
        link_match = _MARKDOWN_LINK_RE.search(item)
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
            target = _resolve_bundle_target(source_path, target) or _bundle_relative(
                target
            )
        citations.append(
            OkfCitation(
                citation_id=_stable_id("okf-citation", source_path, str(index), target),
                target=target,
                target_kind=target_kind,
                source_path=source_path,
                source_section=current_section,
                label=label,
                line_number=index,
            )
        )
    return citations


def _extract_index_entries(body: str, *, source_path: str) -> list[OkfIndexEntry]:
    entries: list[OkfIndexEntry] = []
    for line in body.splitlines():
        item_match = _LIST_ITEM_RE.match(line)
        if not item_match:
            continue
        item = item_match.group(1).strip()
        link_match = _MARKDOWN_LINK_RE.search(item)
        if link_match:
            label = link_match.group(1).strip()
            target = _resolve_bundle_target(source_path, link_match.group(2).strip())
            description = item[link_match.end() :].lstrip(" :-") or None
            entries.append(
                OkfIndexEntry(label=label, target_path=target, description=description)
            )
        else:
            entries.append(OkfIndexEntry(label=item))
    return entries


def _extract_log_entries(body: str) -> list[OkfLogEntry]:
    entries: list[OkfLogEntry] = []
    for index, line in enumerate(body.splitlines(), start=1):
        item_match = _LIST_ITEM_RE.match(line)
        if not item_match:
            continue
        entries.append(OkfLogEntry(text=item_match.group(1).strip(), line_number=index))
    return entries


def _findings_for_document(
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


def validate_okf_bundle(
    bundle_root: str | Path,
    *,
    namespace: MemoryNamespace | None = None,
    spec_commit: str = OKF_SPEC_BASELINE_COMMIT,
) -> list[OkfConformanceFinding]:
    bundle = import_okf_bundle(
        bundle_root,
        namespace=namespace or MemoryNamespace(graph_id="okf"),
        spec_commit=spec_commit,
    )
    return list(bundle.findings)


def import_okf_bundle(
    bundle_root: str | Path,
    *,
    namespace: MemoryNamespace,
    spec_commit: str = OKF_SPEC_BASELINE_COMMIT,
) -> OkfBundle:
    root = Path(bundle_root).expanduser().resolve()
    markdown_by_path = _read_markdown_files(root)
    bundle_id = _bundle_id(root)
    candidates = _build_candidates(
        markdown_by_path, namespace=namespace, bundle_id=bundle_id
    )
    concepts: list[OkfConceptDocument] = []
    indices: list[OkfIndexDocument] = []
    logs: list[OkfLogDocument] = []
    references: list[OkfConceptDocument] = []
    findings: list[OkfConformanceFinding] = []
    provisional: list[
        tuple[
            str,
            str,
            MarkdownImport,
            dict[str, Any],
            list[StructuralLink],
            list[OkfCitation],
        ]
    ] = []
    bundle_version: str | None = None
    for path, text in markdown_by_path.items():
        record_id = _stable_id("okf-rec", bundle_id, path)
        imported = extract_markdown(
            text,
            path=path,
            record_id=record_id,
            namespace=namespace,
        )
        frontmatter = _frontmatter_dict(imported)
        normalized_links = _normalize_okf_links(
            imported,
            source_path=path,
            candidates=candidates,
        )
        citations = _extract_citations(imported.body, source_path=path)
        provisional.append(
            (
                path,
                _document_kind(path),
                imported,
                frontmatter,
                normalized_links,
                citations,
            )
        )
        if bundle_version is None and frontmatter.get("okf_version"):
            bundle_version = str(frontmatter["okf_version"])
    bundle_paths = {path for path, *_ in provisional}
    for path, kind, imported, frontmatter, normalized_links, citations in provisional:
        findings.extend(
            _findings_for_document(
                path=path,
                kind=kind,
                frontmatter=frontmatter,
                body=imported.body,
                bundle_paths=bundle_paths,
                links=normalized_links,
            )
        )
        if kind == "index":
            indices.append(
                OkfIndexDocument(
                    document=imported.document,
                    body=imported.body,
                    entries=_extract_index_entries(imported.body, source_path=path),
                    frontmatter=frontmatter,
                    links=normalized_links,
                    blocks=list(imported.blocks),
                    citations=citations,
                )
            )
            continue
        if kind == "log":
            logs.append(
                OkfLogDocument(
                    document=imported.document,
                    body=imported.body,
                    entries=_extract_log_entries(imported.body),
                    frontmatter=frontmatter,
                    links=normalized_links,
                    blocks=list(imported.blocks),
                    citations=citations,
                )
            )
            continue
        profile = _profile_from_frontmatter(frontmatter)
        concept = OkfConceptDocument(
            document=imported.document,
            profile=profile,
            body=imported.body,
            frontmatter=frontmatter,
            links=normalized_links,
            blocks=list(imported.blocks),
            citations=citations,
            document_kind="reference" if kind == "reference" else "concept",
        )
        if kind == "reference":
            references.append(concept)
        else:
            concepts.append(concept)
    manifest = OkfBundleManifest(
        bundle_id=bundle_id,
        root_path=str(root),
        namespace=namespace,
        spec_commit=spec_commit,
        spec_url=OKF_SPEC_BASELINE_URL.replace(OKF_SPEC_BASELINE_COMMIT, spec_commit),
        okf_version=bundle_version,
        concept_count=len(concepts),
        index_count=len(indices),
        log_count=len(logs),
        reference_count=len(references),
    )
    return OkfBundle(
        manifest=manifest,
        concepts=sorted(concepts, key=lambda item: item.document.path),
        indices=sorted(indices, key=lambda item: item.document.path),
        logs=sorted(logs, key=lambda item: item.document.path),
        references=sorted(references, key=lambda item: item.document.path),
        findings=sorted(
            findings, key=lambda item: (item.path, item.code, item.line_number or 0)
        ),
    )


def _render_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return "[" + ", ".join(str(item) for item in value) + "]"
    return str(value)


def _frontmatter_lines(frontmatter: dict[str, Any]) -> list[str]:
    lines = ["---"]
    for key, value in frontmatter.items():
        lines.append(f"{key}: {_render_scalar(value)}")
    lines.append("---")
    return lines


def _bundle_relative_markdown_target(link: StructuralLink) -> str | None:
    path = link.target_path
    if not path:
        return None
    target = "/" + _bundle_relative(path)
    if link.target_heading:
        target += f"#{link.target_heading}"
    elif link.target_block_id:
        target += f"#^{link.target_block_id}"
    return target


def _obsidian_target(link: StructuralLink) -> str | None:
    if link.target_path:
        target = link.target_path
        if link.target_heading:
            target += f"#{link.target_heading}"
        elif link.target_block_id:
            target += f"#^{link.target_block_id}"
        return target
    return None


def _render_link(link: StructuralLink, *, obsidian_compatible: bool) -> str:
    if link.link_kind == "external":
        label = link.display_text or link.raw_target
        return f"[{label}]({link.raw_target})"
    target = (
        _obsidian_target(link)
        if obsidian_compatible
        else _bundle_relative_markdown_target(link)
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


def _rewrite_body(
    body: str, links: list[StructuralLink], *, obsidian_compatible: bool
) -> str:
    rewritten = body
    for link in sorted(
        [item for item in links if item.start is not None and item.end is not None],
        key=lambda item: item.start or 0,
        reverse=True,
    ):
        replacement = _render_link(link, obsidian_compatible=obsidian_compatible)
        rewritten = rewritten[: link.start] + replacement + rewritten[link.end :]
    return rewritten


def _frontmatter_for_concept(document: OkfConceptDocument) -> dict[str, Any]:
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


def _render_document(
    *,
    frontmatter: dict[str, Any],
    body: str,
) -> str:
    return "\n".join(_frontmatter_lines(frontmatter)) + "\n" + body


def export_okf_bundle(
    bundle: OkfBundle,
    *,
    obsidian_compatible: bool = False,
) -> list[VaultFilePayload]:
    files: list[VaultFilePayload] = []
    for document in bundle.concepts + bundle.references:
        body = _rewrite_body(
            document.body,
            document.links,
            obsidian_compatible=obsidian_compatible,
        )
        files.append(
            VaultFilePayload(
                path=document.document.path,
                content=_render_document(
                    frontmatter=_frontmatter_for_concept(document),
                    body=body,
                ),
                file_kind="markdown",
            )
        )
    for document in bundle.indices:
        body = _rewrite_body(
            document.body,
            document.links,
            obsidian_compatible=obsidian_compatible,
        )
        files.append(
            VaultFilePayload(
                path=document.document.path,
                content=_render_document(
                    frontmatter=dict(document.frontmatter), body=body
                ),
                file_kind="markdown",
            )
        )
    for document in bundle.logs:
        body = _rewrite_body(
            document.body,
            document.links,
            obsidian_compatible=obsidian_compatible,
        )
        files.append(
            VaultFilePayload(
                path=document.document.path,
                content=_render_document(
                    frontmatter=dict(document.frontmatter), body=body
                ),
                file_kind="markdown",
            )
        )
    return sorted(files, key=lambda item: item.path)


def write_okf_bundle(
    bundle: OkfBundle,
    out_root: str | Path,
    *,
    obsidian_compatible: bool = False,
) -> Path:
    root = Path(out_root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    for payload in export_okf_bundle(bundle, obsidian_compatible=obsidian_compatible):
        destination = root / payload.path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(payload.content, encoding="utf-8")
    return root


def _store_compatible_payload(payload: VaultFilePayload) -> VaultFilePayload:
    if payload.file_kind != "markdown":
        return payload
    return replace(
        payload,
        content=_ROOT_LINK_RE.sub(r"\1\2)", payload.content),
    )


def import_okf_bundle_into_store(
    store: VaultStore,
    bundle_root: str | Path,
    *,
    namespace: MemoryNamespace,
    scope: str,
    vault_id: str,
    root_label: str = "okf",
    imported_at: str | None = None,
    tombstone_missing: bool = False,
    spec_commit: str = OKF_SPEC_BASELINE_COMMIT,
) -> VaultImportResult:
    bundle = import_okf_bundle(
        bundle_root,
        namespace=namespace,
        spec_commit=spec_commit,
    )
    files = [
        _store_compatible_payload(payload) for payload in export_okf_bundle(bundle)
    ]
    return import_vault_files(
        store,
        files,
        VaultImportOptions(
            vault_id=vault_id,
            namespace=namespace,
            scope=scope,
            root_label=root_label,
            imported_at=imported_at or utc_now_iso(),
            tombstone_missing=tombstone_missing,
        ),
    )


def build_okf_navigation_packet(
    bundle: OkfBundle,
    *,
    current_path: str,
) -> OkfNavigationPacket:
    path = _bundle_relative(current_path)
    document_map: dict[str, Any] = {}
    for document in bundle.concepts + bundle.references + bundle.indices + bundle.logs:
        document_map[document.document.path] = document
    if path not in document_map:
        raise NotFoundError(f"bundle document not found: {path}")
    document = document_map[path]
    all_links: list[StructuralLink] = []
    for item in bundle.concepts + bundle.references + bundle.indices + bundle.logs:
        all_links.extend(item.links)
    backlinks = [
        link
        for link in all_links
        if link.target_path == path
        and link.source_record_id != document.document.record_id
    ]
    unresolved = [
        link
        for link in getattr(document, "links", [])
        if link.resolution_status == "unresolved"
    ]
    title_map: dict[str, tuple[str, str]] = {}
    for item in bundle.concepts + bundle.references:
        title_map[item.document.title.lower()] = (
            item.document.record_id,
            item.document.title,
        )
        for alias in item.document.aliases:
            title_map[alias.lower()] = (item.document.record_id, alias)
    masked_body = document.body
    for link in sorted(
        [
            item
            for item in getattr(document, "links", [])
            if item.start is not None and item.end is not None
        ],
        key=lambda item: item.start or 0,
        reverse=True,
    ):
        masked_body = (
            masked_body[: link.start]
            + (" " * (link.end - link.start))
            + masked_body[link.end :]
        )
    suggestions: list[UnlinkedMentionCandidate] = []
    self_record_id = document.document.record_id
    for lowered, (target_record_id, matched_text) in title_map.items():
        if target_record_id == self_record_id:
            continue
        pattern = re.compile(
            rf"(?<![A-Za-z0-9_]){re.escape(matched_text)}(?![A-Za-z0-9_])",
            re.IGNORECASE,
        )
        match = pattern.search(masked_body)
        if match is None:
            continue
        suggestions.append(
            UnlinkedMentionCandidate(
                candidate_id=_stable_id(
                    "okf-mention", path, target_record_id, str(match.start())
                ),
                source_record_id=self_record_id,
                target_record_id=target_record_id,
                matched_text=match.group(0),
                match_kind="title" if lowered == matched_text.lower() else "alias",
                context=KnowledgeContextExcerpt(
                    record_id=self_record_id,
                    text=masked_body[
                        max(0, match.start() - 40) : match.end() + 40
                    ].strip(),
                    source_path=path,
                    char_budget=160,
                ),
            )
        )
    references = [
        reference
        for reference in bundle.references
        if any(
            citation.target_kind == "bundle_path"
            and citation.target == reference.document.path
            for citation in getattr(document, "citations", [])
        )
    ]
    document_kind = getattr(document, "document_kind", None) or (
        "index"
        if isinstance(document, OkfIndexDocument)
        else "log"
        if isinstance(document, OkfLogDocument)
        else "concept"
    )
    return OkfNavigationPacket(
        manifest=bundle.manifest,
        current_path=path,
        document_kind=document_kind,
        title=document.document.title,
        outgoing_links=list(getattr(document, "links", [])),
        backlinks=backlinks,
        unresolved_links=unresolved,
        citations=list(getattr(document, "citations", [])),
        references=references,
        unlinked_mentions=suggestions,
        index_entries=list(getattr(document, "entries", []))
        if isinstance(document, OkfIndexDocument)
        else [],
        log_entries=list(getattr(document, "entries", []))
        if isinstance(document, OkfLogDocument)
        else [],
    )


__all__ = [
    "OKF_SPEC_BASELINE_COMMIT",
    "OKF_SPEC_BASELINE_URL",
    "OkfBundle",
    "OkfBundleManifest",
    "OkfCitation",
    "OkfConceptDocument",
    "OkfConceptProfile",
    "OkfConformanceFinding",
    "OkfIndexDocument",
    "OkfIndexEntry",
    "OkfLogDocument",
    "OkfLogEntry",
    "OkfNavigationPacket",
    "build_okf_navigation_packet",
    "export_okf_bundle",
    "import_okf_bundle",
    "import_okf_bundle_into_store",
    "validate_okf_bundle",
    "write_okf_bundle",
]
