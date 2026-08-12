"""Typed Open Knowledge Format bundle/profile models."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any, Literal

from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.models.document import KnowledgeDocument, KnowledgeDocumentBlock
from sophiagraph.models.link import StructuralLink
from sophiagraph.models.namespace import MemoryNamespace

if TYPE_CHECKING:
    from sophiagraph.query.explorer import UnlinkedMentionCandidate

OkfDocumentKind = Literal["concept", "index", "log", "reference"]
OkfFindingSeverity = Literal["error", "warning", "info"]

OKF_SPEC_BASELINE_COMMIT = "ba17dd5dfd72d357418966318466d345bf63dcfb"
OKF_SPEC_BASELINE_URL = (
    "https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/"
    f"{OKF_SPEC_BASELINE_COMMIT}/okf/SPEC.md"
)


def _validate_relative_path(path: str) -> str:
    normalized = str(PurePosixPath(str(path or "").replace("\\", "/")))
    if not normalized or normalized == ".":
        raise InvalidArgumentError("path is required")
    if normalized.startswith(("/", "../")):
        raise InvalidArgumentError("path must be relative and cannot traverse parents")
    if ".." in normalized.split("/"):
        raise InvalidArgumentError("path must be relative and cannot traverse parents")
    return normalized


@dataclass(frozen=True, slots=True)
class OkfCitation:
    """Structural citation from a concept body to an external or bundle target."""

    citation_id: str
    target: str
    target_kind: Literal["external", "bundle_path"]
    source_path: str
    source_section: str | None = None
    label: str | None = None
    line_number: int | None = None

    def __post_init__(self) -> None:
        if not self.citation_id:
            raise InvalidArgumentError("citation_id is required")
        if not self.target:
            raise InvalidArgumentError("target is required")
        object.__setattr__(
            self, "source_path", _validate_relative_path(self.source_path)
        )
        if self.line_number is not None and self.line_number < 1:
            raise InvalidArgumentError("line_number must be positive")


@dataclass(frozen=True, slots=True)
class OkfConceptProfile:
    """Shared OKF frontmatter shape for concept-like documents."""

    concept_type: str | None = None
    title: str | None = None
    description: str | None = None
    resource: str | None = None
    tags: list[str] = field(default_factory=list)
    timestamp: str | None = None
    okf_version: str | None = None
    extensions: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.extensions, dict):
            raise TypeError(
                "extensions must be a dict"
            )  # allow-bare-raise: defensive dataclass guard


@dataclass(frozen=True, slots=True)
class OkfIndexEntry:
    """One explicit item extracted from an OKF index body."""

    label: str
    target_path: str | None = None
    description: str | None = None

    def __post_init__(self) -> None:
        if not self.label:
            raise InvalidArgumentError("label is required")
        if self.target_path is not None:
            object.__setattr__(
                self, "target_path", _validate_relative_path(self.target_path)
            )


@dataclass(frozen=True, slots=True)
class OkfLogEntry:
    """One raw chronological entry from `log.md`."""

    text: str
    line_number: int

    def __post_init__(self) -> None:
        if not self.text:
            raise InvalidArgumentError("text is required")
        if self.line_number < 1:
            raise InvalidArgumentError("line_number must be positive")


@dataclass(frozen=True, slots=True)
class OkfConceptDocument:
    """A concept or reference document inside one OKF bundle."""

    document: KnowledgeDocument
    profile: OkfConceptProfile
    body: str
    frontmatter: dict[str, Any] = field(default_factory=dict)
    links: list[StructuralLink] = field(default_factory=list)
    blocks: list[KnowledgeDocumentBlock] = field(default_factory=list)
    citations: list[OkfCitation] = field(default_factory=list)
    document_kind: Literal["concept", "reference"] = "concept"

    def __post_init__(self) -> None:
        if self.document_kind not in {"concept", "reference"}:
            raise InvalidArgumentError(f"invalid document_kind: {self.document_kind!r}")


@dataclass(frozen=True, slots=True)
class OkfIndexDocument:
    """Reserved `index.md` document for progressive disclosure."""

    document: KnowledgeDocument
    body: str
    entries: list[OkfIndexEntry] = field(default_factory=list)
    frontmatter: dict[str, Any] = field(default_factory=dict)
    links: list[StructuralLink] = field(default_factory=list)
    blocks: list[KnowledgeDocumentBlock] = field(default_factory=list)
    citations: list[OkfCitation] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class OkfLogDocument:
    """Reserved `log.md` document for chronological history."""

    document: KnowledgeDocument
    body: str
    entries: list[OkfLogEntry] = field(default_factory=list)
    frontmatter: dict[str, Any] = field(default_factory=dict)
    links: list[StructuralLink] = field(default_factory=list)
    blocks: list[KnowledgeDocumentBlock] = field(default_factory=list)
    citations: list[OkfCitation] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class OkfConformanceFinding:
    """Deterministic finding from OKF bundle validation."""

    code: str
    severity: OkfFindingSeverity
    path: str
    message: str
    line_number: int | None = None

    def __post_init__(self) -> None:
        if not self.code:
            raise InvalidArgumentError("code is required")
        object.__setattr__(self, "path", _validate_relative_path(self.path))
        if not self.message:
            raise InvalidArgumentError("message is required")
        if self.line_number is not None and self.line_number < 1:
            raise InvalidArgumentError("line_number must be positive")


@dataclass(frozen=True, slots=True)
class OkfBundleManifest:
    """Pinned bundle manifest for one OKF import/export operation."""

    bundle_id: str
    root_path: str
    namespace: MemoryNamespace
    spec_commit: str = OKF_SPEC_BASELINE_COMMIT
    spec_url: str = OKF_SPEC_BASELINE_URL
    okf_version: str | None = None
    concept_count: int = 0
    index_count: int = 0
    log_count: int = 0
    reference_count: int = 0

    def __post_init__(self) -> None:
        if not self.bundle_id:
            raise InvalidArgumentError("bundle_id is required")
        if not self.root_path:
            raise InvalidArgumentError("root_path is required")
        if not self.spec_commit:
            raise InvalidArgumentError("spec_commit is required")
        if not isinstance(self.namespace, MemoryNamespace):
            raise TypeError(
                "namespace must be MemoryNamespace"
            )  # allow-bare-raise: defensive dataclass guard


@dataclass(frozen=True, slots=True)
class OkfBundle:
    """Whole imported OKF bundle in package-owned typed form."""

    manifest: OkfBundleManifest
    concepts: list[OkfConceptDocument] = field(default_factory=list)
    indices: list[OkfIndexDocument] = field(default_factory=list)
    logs: list[OkfLogDocument] = field(default_factory=list)
    references: list[OkfConceptDocument] = field(default_factory=list)
    findings: list[OkfConformanceFinding] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class OkfNavigationPacket:
    """Bundle-level navigation packet for explorer and workbench surfaces."""

    manifest: OkfBundleManifest
    current_path: str
    document_kind: OkfDocumentKind
    title: str | None
    outgoing_links: list[StructuralLink] = field(default_factory=list)
    backlinks: list[StructuralLink] = field(default_factory=list)
    unresolved_links: list[StructuralLink] = field(default_factory=list)
    citations: list[OkfCitation] = field(default_factory=list)
    references: list[OkfConceptDocument] = field(default_factory=list)
    unlinked_mentions: list[UnlinkedMentionCandidate] = field(default_factory=list)
    index_entries: list[OkfIndexEntry] = field(default_factory=list)
    log_entries: list[OkfLogEntry] = field(default_factory=list)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "current_path", _validate_relative_path(self.current_path)
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
    "OkfDocumentKind",
    "OkfFindingSeverity",
    "OkfIndexDocument",
    "OkfIndexEntry",
    "OkfLogDocument",
    "OkfLogEntry",
    "OkfNavigationPacket",
]
