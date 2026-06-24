from __future__ import annotations

import pytest

from sophiagraph.adapters.markdown import extract_markdown, export_markdown
from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.models import (
    ExplicitLinkResolver,
    KnowledgeDocument,
    KnowledgeDocumentBlock,
    LinkResolutionCandidate,
    MemoryNamespace,
    MemoryRecord,
    StructuralLink,
)


def _namespace() -> MemoryNamespace:
    return MemoryNamespace(tenant_id="tenant", agent_id="agent", graph_id="main")


def test_document_dto_wraps_record_metadata_without_converting_records() -> None:
    namespace = _namespace()
    document = KnowledgeDocument(
        document_id="doc-1",
        record_id="rec-1",
        path="folder/Roadmap.md",
        title="Roadmap",
        aliases=["Plan"],
        content_hash="abc123",
        namespace=namespace,
        created_at="2026-05-23T00:00:00+00:00",
        updated_at="2026-05-23T00:00:00+00:00",
    )
    record = MemoryRecord(
        id="rec-1",
        scope="agent:agent",
        type="artifact_digest",
        title="Roadmap",
        key="doc:roadmap",
        content={"text": "document body"},
        created_at="2026-05-23T00:00:00+00:00",
        updated_at="2026-05-23T00:00:00+00:00",
        namespace=namespace,
        meta={"document": document.as_record_meta()},
    )

    assert KnowledgeDocument.from_record(record) == document
    assert (
        MemoryRecord(
            id="rec-fact",
            scope="agent:agent",
            type="fact",
            content={"text": "not a document"},
            created_at="2026-05-23T00:00:00+00:00",
            updated_at="2026-05-23T00:00:00+00:00",
            namespace=namespace,
        ).type
        == "fact"
    )


def test_document_rejects_unsafe_path() -> None:
    with pytest.raises(InvalidArgumentError, match="non-absolute"):
        KnowledgeDocument(
            document_id="doc-1",
            record_id="rec-1",
            path="/abs.md",
            title="Abs",
            content_hash="abc123",
            namespace=_namespace(),
        )


def test_document_from_record_rejects_malformed_aliases_metadata() -> None:
    namespace = _namespace()
    record = MemoryRecord(
        id="rec-1",
        scope="agent:agent",
        type="artifact_digest",
        title="Roadmap",
        content={"text": "document body"},
        created_at="2026-05-23T00:00:00+00:00",
        updated_at="2026-05-23T00:00:00+00:00",
        namespace=namespace,
        meta={
            "document": {
                "document_id": "doc-1",
                "path": "Roadmap.md",
                "title": "Roadmap",
                "aliases": "Plan",
                "content_hash": "abc123",
            }
        },
    )

    with pytest.raises(InvalidArgumentError, match="document aliases must be a list"):
        KnowledgeDocument.from_record(record)


def test_document_block_rejects_invalid_block_type() -> None:
    with pytest.raises(InvalidArgumentError, match="invalid block_type"):
        KnowledgeDocumentBlock(
            block_id="block-1",
            document_id="doc-1",
            record_id="rec-1",
            block_type="unknown",  # type: ignore[arg-type]
            anchor="anchor",
        )


def test_markdown_adapter_extracts_explicit_structure_and_preserves_body() -> None:
    namespace = _namespace()
    text = """---
title: Roadmap
aliases: [Plan, Strategy]
tags: [project/core]
status: active
---
# Roadmap

See [[Decision Log|decisions]], ![[Diagram#^block-1]], and [site](https://example.com).
Inline #project/core tag is structural.
"""
    imported = extract_markdown(
        text,
        path="Roadmap.md",
        record_id="rec-roadmap",
        namespace=namespace,
        resolver_candidates=[
            LinkResolutionCandidate(
                record_id="rec-decision",
                path="Decision Log.md",
                title="Decision Log",
                aliases=["decisions"],
                namespace=namespace,
            )
        ],
    )

    assert imported.document.title == "Roadmap"
    assert imported.document.aliases == ["Plan", "Strategy"]
    assert imported.tags == ["project/core"]
    assert {link.link_kind for link in imported.links} == {
        "wikilink",
        "embed",
        "external",
    }
    assert {block.anchor for block in imported.blocks} >= {"roadmap", "block-1"}
    assert imported.links[0].resolution_status == "resolved"
    assert imported.links[1].target_block_id == "block-1"
    assert "Inline #project/core" in export_markdown(imported)


def test_explicit_resolver_reports_unresolved_and_ambiguous_without_guessing() -> None:
    namespace = _namespace()
    resolver = ExplicitLinkResolver(
        [
            LinkResolutionCandidate("rec-1", "A.md", "Topic", namespace=namespace),
            LinkResolutionCandidate("rec-2", "B.md", "Topic", namespace=namespace),
        ]
    )

    ambiguous = resolver.resolve("topic", namespace=namespace)
    unresolved = resolver.resolve("text merely mentioning Topic without link")

    assert ambiguous.status == "ambiguous"
    assert unresolved.status == "unresolved"


def test_structural_link_requires_explicit_target() -> None:
    with pytest.raises(InvalidArgumentError, match="raw_target"):
        StructuralLink(
            link_id="link-1",
            source_record_id="rec-1",
            raw_target="",
            link_kind="wikilink",
            resolution_status="unresolved",
            namespace=_namespace(),
        )
