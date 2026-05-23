"""Document-profile DTOs for link-native knowledge graphs."""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any, Literal

from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.models.namespace import MemoryNamespace
from sophiagraph.models.record import MemoryRecord

DocumentSourceFormat = Literal["markdown", "text", "html", "json", "external"]
DocumentBlockType = Literal["heading", "block", "paragraph", "property"]


def content_hash(content: str) -> str:
    """Return a stable SHA-256 hash for document content."""
    return sha256(content.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class KnowledgeDocument:
    """Metadata wrapper for a document-profile ``MemoryRecord`` node."""

    document_id: str
    record_id: str
    path: str
    title: str
    namespace: MemoryNamespace
    content_hash: str
    source_format: DocumentSourceFormat = "markdown"
    aliases: list[str] = field(default_factory=list)
    created_at: str | None = None
    updated_at: str | None = None
    provenance: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.document_id:
            raise InvalidArgumentError("document_id is required")
        if not self.record_id:
            raise InvalidArgumentError("record_id is required")
        if not self.path or self.path.startswith("/"):
            raise InvalidArgumentError("path must be a non-absolute document path")
        if ".." in self.path.split("/"):
            raise InvalidArgumentError("path cannot contain parent traversal")
        if not self.title:
            raise InvalidArgumentError("title is required")
        if not self.content_hash:
            raise InvalidArgumentError("content_hash is required")
        if not isinstance(self.namespace, MemoryNamespace):
            raise TypeError(
                "namespace must be MemoryNamespace"
            )  # allow-bare-raise: defensive dataclass guard

    @classmethod
    def from_record(cls, record: MemoryRecord) -> "KnowledgeDocument":
        """Build document metadata from a document-profile record."""
        meta = record.meta.get("document")
        if not isinstance(meta, dict):
            raise InvalidArgumentError("record does not contain document metadata")
        return cls(
            document_id=str(meta.get("document_id") or record.id),
            record_id=record.id,
            path=str(meta.get("path") or ""),
            title=str(meta.get("title") or record.title or ""),
            aliases=[str(item) for item in meta.get("aliases", [])],
            content_hash=str(meta.get("content_hash") or ""),
            source_format=str(meta.get("source_format") or "markdown"),  # type: ignore[arg-type]
            namespace=record.effective_namespace,
            created_at=record.created_at,
            updated_at=record.updated_at,
            provenance=dict(meta.get("provenance") or {}),
        )

    def as_record_meta(self) -> dict[str, Any]:
        """Return the metadata payload stored on a document-profile record."""
        return {
            "document_id": self.document_id,
            "path": self.path,
            "title": self.title,
            "aliases": list(self.aliases),
            "content_hash": self.content_hash,
            "source_format": self.source_format,
            "provenance": dict(self.provenance),
        }


@dataclass(frozen=True)
class KnowledgeDocumentBlock:
    """Addressable heading/block target inside a document."""

    block_id: str
    document_id: str
    record_id: str
    block_type: DocumentBlockType
    anchor: str
    content_hash: str | None = None
    line_start: int | None = None
    line_end: int | None = None
    excerpt: str | None = None

    def __post_init__(self) -> None:
        if not self.block_id:
            raise InvalidArgumentError("block_id is required")
        if not self.document_id:
            raise InvalidArgumentError("document_id is required")
        if not self.record_id:
            raise InvalidArgumentError("record_id is required")
        if not self.anchor:
            raise InvalidArgumentError("anchor is required")
        if self.line_start is not None and self.line_start < 1:
            raise InvalidArgumentError("line_start must be positive")
        if self.line_end is not None and self.line_end < 1:
            raise InvalidArgumentError("line_end must be positive")
        if (
            self.line_start is not None
            and self.line_end is not None
            and self.line_end < self.line_start
        ):
            raise InvalidArgumentError("line_end must be >= line_start")


__all__ = [
    "DocumentBlockType",
    "DocumentSourceFormat",
    "KnowledgeDocument",
    "KnowledgeDocumentBlock",
    "content_hash",
]
