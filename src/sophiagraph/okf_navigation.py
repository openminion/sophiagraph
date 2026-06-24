"""OKF navigation packet assembly behind the stable `sophiagraph.okf` facade."""

from __future__ import annotations

import re
from typing import Any

from sophiagraph.contracts.errors import NotFoundError
from sophiagraph.models import StructuralLink
from sophiagraph.models.okf import (
    OkfBundle,
    OkfIndexDocument,
    OkfLogDocument,
    OkfNavigationPacket,
)
from sophiagraph.query import KnowledgeContextExcerpt, UnlinkedMentionCandidate

from .okf_support import bundle_relative, stable_id


def build_okf_navigation_packet(
    bundle: OkfBundle,
    *,
    current_path: str,
) -> OkfNavigationPacket:
    path = bundle_relative(current_path)
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
    ranged_links = [
        item
        for item in getattr(document, "links", [])
        if item.start is not None and item.end is not None
    ]
    for link in sorted(ranged_links, key=lambda item: item.start or 0, reverse=True):
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
                candidate_id=stable_id(
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
