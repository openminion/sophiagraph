"""Typed artifact projection and citation DTOs."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Final, Literal

from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.models.namespace import MemoryNamespace


ArtifactProjectionKind = Literal[
    "ocr_text",
    "transcript",
    "caption",
    "document_text",
]
ARTIFACT_PROJECTION_KINDS: Final[frozenset[str]] = frozenset(
    {"ocr_text", "transcript", "caption", "document_text"}
)

ArtifactCitationKind = Literal["page", "region", "timestamp", "segment"]
ARTIFACT_CITATION_KINDS: Final[frozenset[str]] = frozenset(
    {"page", "region", "timestamp", "segment"}
)

ArtifactProjectionFreshness = Literal[
    "current",
    "source_replaced",
    "superseded",
    "missing_derived_text",
]
ARTIFACT_PROJECTION_FRESHNESS_STATES: Final[frozenset[str]] = frozenset(
    {"current", "source_replaced", "superseded", "missing_derived_text"}
)
_HEX64_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")


def _optional_int(data: dict[str, Any], key: str) -> int | None:
    return int(data[key]) if data.get(key) is not None else None


def _optional_str(data: dict[str, Any], key: str) -> str | None:
    return str(data[key]) if data.get(key) is not None else None


def _meta_dict(data: dict[str, Any]) -> dict[str, Any]:
    return dict(data.get("meta", {})) if isinstance(data.get("meta"), dict) else {}


@dataclass(frozen=True, slots=True)
class ArtifactCitation:
    citation_id: str
    artifact_id: str
    kind: ArtifactCitationKind
    page_index: int | None = None
    region_id: str | None = None
    segment_id: str | None = None
    start_ms: int | None = None
    end_ms: int | None = None
    start_char: int | None = None
    end_char: int | None = None
    label: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.citation_id:
            raise InvalidArgumentError("citation_id is required")
        if not self.artifact_id:
            raise InvalidArgumentError("artifact_id is required")
        if self.kind not in ARTIFACT_CITATION_KINDS:
            raise InvalidArgumentError(f"invalid citation kind: {self.kind!r}")
        if self.kind == "page" and self.page_index is None:
            raise InvalidArgumentError("page citations require page_index")
        if self.kind == "region":
            if self.region_id is None:
                raise InvalidArgumentError("region citations require region_id")
            if self.page_index is None:
                raise InvalidArgumentError("region citations require page_index")
        if self.kind == "timestamp" and (self.start_ms is None or self.end_ms is None):
            raise InvalidArgumentError(
                "timestamp citations require start_ms and end_ms"
            )
        if self.kind == "segment" and not self.segment_id:
            raise InvalidArgumentError("segment citations require segment_id")
        if self.page_index is not None and self.page_index < 0:
            raise InvalidArgumentError("page_index must be non-negative")
        if self.start_ms is not None and self.start_ms < 0:
            raise InvalidArgumentError("start_ms must be non-negative")
        if self.end_ms is not None and self.end_ms < 0:
            raise InvalidArgumentError("end_ms must be non-negative")
        if (
            self.start_ms is not None
            and self.end_ms is not None
            and self.end_ms < self.start_ms
        ):
            raise InvalidArgumentError("end_ms must be >= start_ms")
        if self.start_char is not None and self.start_char < 0:
            raise InvalidArgumentError("start_char must be non-negative")
        if self.end_char is not None and self.end_char < 0:
            raise InvalidArgumentError("end_char must be non-negative")
        if (
            self.start_char is not None
            and self.end_char is not None
            and self.end_char < self.start_char
        ):
            raise InvalidArgumentError("end_char must be >= start_char")
        if not isinstance(self.meta, dict):
            raise InvalidArgumentError("meta must be a dict")

    def to_dict(self) -> dict[str, Any]:
        return {
            "citation_id": self.citation_id,
            "artifact_id": self.artifact_id,
            "kind": self.kind,
            "page_index": self.page_index,
            "region_id": self.region_id,
            "segment_id": self.segment_id,
            "start_ms": self.start_ms,
            "end_ms": self.end_ms,
            "start_char": self.start_char,
            "end_char": self.end_char,
            "label": self.label,
            "meta": dict(self.meta),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ArtifactCitation":
        return cls(
            citation_id=str(data.get("citation_id", "")),
            artifact_id=str(data.get("artifact_id", "")),
            kind=str(data.get("kind", "")),  # type: ignore[arg-type]
            page_index=_optional_int(data, "page_index"),
            region_id=_optional_str(data, "region_id"),
            segment_id=_optional_str(data, "segment_id"),
            start_ms=_optional_int(data, "start_ms"),
            end_ms=_optional_int(data, "end_ms"),
            start_char=_optional_int(data, "start_char"),
            end_char=_optional_int(data, "end_char"),
            label=_optional_str(data, "label"),
            meta=_meta_dict(data),
        )


@dataclass(frozen=True, slots=True)
class ArtifactProjectionSegment:
    segment_id: str
    ordinal: int
    text: str
    citations: tuple[ArtifactCitation, ...] = ()
    label: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.segment_id:
            raise InvalidArgumentError("segment_id is required")
        if self.ordinal < 0:
            raise InvalidArgumentError("ordinal must be non-negative")
        if not self.text:
            raise InvalidArgumentError("text is required")
        for citation in self.citations:
            if not isinstance(citation, ArtifactCitation):
                raise InvalidArgumentError(
                    "citations must contain ArtifactCitation instances"
                )
        if not isinstance(self.meta, dict):
            raise InvalidArgumentError("meta must be a dict")

    def to_dict(self) -> dict[str, Any]:
        return {
            "segment_id": self.segment_id,
            "ordinal": self.ordinal,
            "text": self.text,
            "citations": [citation.to_dict() for citation in self.citations],
            "label": self.label,
            "meta": dict(self.meta),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ArtifactProjectionSegment":
        raw_citations = data.get("citations", [])
        return cls(
            segment_id=str(data.get("segment_id", "")),
            ordinal=int(data.get("ordinal", 0) or 0),
            text=str(data.get("text", "")),
            citations=tuple(
                ArtifactCitation.from_dict(item)
                for item in raw_citations
                if isinstance(item, dict)
            ),
            label=_optional_str(data, "label"),
            meta=_meta_dict(data),
        )


@dataclass(frozen=True, slots=True)
class ArtifactTextProjection:
    projection_id: str
    artifact_id: str
    derived_text_record_id: str
    namespace: MemoryNamespace
    projection_kind: ArtifactProjectionKind
    adapter_id: str
    source_sha256: str
    source_mime: str
    created_at: str
    segments: tuple[ArtifactProjectionSegment, ...]
    superseded_by_projection_id: str | None = None
    superseded_at: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.projection_id:
            raise InvalidArgumentError("projection_id is required")
        if not self.artifact_id:
            raise InvalidArgumentError("artifact_id is required")
        if not self.derived_text_record_id:
            raise InvalidArgumentError("derived_text_record_id is required")
        if not isinstance(self.namespace, MemoryNamespace):
            raise InvalidArgumentError("namespace must be MemoryNamespace")
        if self.projection_kind not in ARTIFACT_PROJECTION_KINDS:
            raise InvalidArgumentError(
                f"invalid projection_kind: {self.projection_kind!r}"
            )
        if not self.adapter_id:
            raise InvalidArgumentError("adapter_id is required")
        if not _HEX64_PATTERN.match(self.source_sha256):
            raise InvalidArgumentError("source_sha256 must be a 64-char hex digest")
        if not self.source_mime:
            raise InvalidArgumentError("source_mime is required")
        if not self.created_at:
            raise InvalidArgumentError("created_at is required")
        if not self.segments:
            raise InvalidArgumentError("segments must not be empty")
        if (
            self.superseded_by_projection_id is not None
            and not self.superseded_by_projection_id
        ):
            raise InvalidArgumentError(
                "superseded_by_projection_id must be non-empty or None"
            )
        if self.superseded_at is not None and not self.superseded_at:
            raise InvalidArgumentError("superseded_at must be non-empty or None")
        if not isinstance(self.meta, dict):
            raise InvalidArgumentError("meta must be a dict")
        seen_segment_ids: set[str] = set()
        for segment in self.segments:
            if not isinstance(segment, ArtifactProjectionSegment):
                raise InvalidArgumentError(
                    "segments must contain ArtifactProjectionSegment instances"
                )
            if segment.segment_id in seen_segment_ids:
                raise InvalidArgumentError(
                    f"duplicate segment_id in projection: {segment.segment_id!r}"
                )
            seen_segment_ids.add(segment.segment_id)
            for citation in segment.citations:
                if citation.artifact_id != self.artifact_id:
                    raise InvalidArgumentError(
                        "citation artifact_id must match projection artifact_id"
                    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "projection_id": self.projection_id,
            "artifact_id": self.artifact_id,
            "derived_text_record_id": self.derived_text_record_id,
            "namespace": self.namespace.as_dict(),
            "projection_kind": self.projection_kind,
            "adapter_id": self.adapter_id,
            "source_sha256": self.source_sha256,
            "source_mime": self.source_mime,
            "created_at": self.created_at,
            "segments": [segment.to_dict() for segment in self.segments],
            "superseded_by_projection_id": self.superseded_by_projection_id,
            "superseded_at": self.superseded_at,
            "meta": dict(self.meta),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ArtifactTextProjection":
        raw_namespace = data.get("namespace")
        if not isinstance(raw_namespace, dict):
            raise InvalidArgumentError("projection namespace payload is required")
        raw_segments = data.get("segments", [])
        return cls(
            projection_id=str(data.get("projection_id", "")),
            artifact_id=str(data.get("artifact_id", "")),
            derived_text_record_id=str(data.get("derived_text_record_id", "")),
            namespace=MemoryNamespace.from_dict(raw_namespace),
            projection_kind=str(data.get("projection_kind", "")),  # type: ignore[arg-type]
            adapter_id=str(data.get("adapter_id", "")),
            source_sha256=str(data.get("source_sha256", "")),
            source_mime=str(data.get("source_mime", "")),
            created_at=str(data.get("created_at", "")),
            segments=tuple(
                ArtifactProjectionSegment.from_dict(item)
                for item in raw_segments
                if isinstance(item, dict)
            ),
            superseded_by_projection_id=_optional_str(
                data,
                "superseded_by_projection_id",
            ),
            superseded_at=_optional_str(data, "superseded_at"),
            meta=_meta_dict(data),
        )


__all__ = [
    "ARTIFACT_CITATION_KINDS",
    "ARTIFACT_PROJECTION_FRESHNESS_STATES",
    "ARTIFACT_PROJECTION_KINDS",
    "ArtifactCitation",
    "ArtifactCitationKind",
    "ArtifactProjectionFreshness",
    "ArtifactProjectionKind",
    "ArtifactProjectionSegment",
    "ArtifactTextProjection",
]
