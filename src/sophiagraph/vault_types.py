"""Typed vault import, export, and repair contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import PurePosixPath
from typing import Literal, Protocol

from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.models import (
    KnowledgeDocumentBlock,
    LinkResolutionCandidate,
    MemoryNamespace,
    MemoryRecord,
    StructuralLink,
)
from sophiagraph.query import LinkQueryOptions, ListQueryOptions

VaultFileKind = Literal["markdown", "canvas", "asset"]
VaultDiagnosticSeverity = Literal["info", "warning", "error"]


def _validate_path(path: str) -> str:
    normalized = str(PurePosixPath(str(path or "").replace("\\", "/")))
    if not normalized or normalized == ".":
        raise InvalidArgumentError("path is required")
    if normalized.startswith(("/", "../")):
        raise InvalidArgumentError("path must be relative and cannot traverse parents")
    if ".." in normalized.split("/"):
        raise InvalidArgumentError("path must be relative and cannot traverse parents")
    return normalized


def _infer_kind(path: str, explicit: VaultFileKind | None = None) -> VaultFileKind:
    if explicit is not None:
        return explicit
    lowered = path.lower()
    if lowered.endswith(".md"):
        return "markdown"
    if lowered.endswith(".canvas"):
        return "canvas"
    return "asset"


def _hash_text(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


class VaultStore(Protocol):
    """Store subset used by vault adapters.

    Methods overlapping ``SophiaGraphStore`` must keep matching signatures.
    """

    def put_record(self, record: MemoryRecord) -> str: ...

    def list_records(self, options: ListQueryOptions) -> list[MemoryRecord]: ...

    def put_document_blocks(
        self, record_id: str, blocks: list[KnowledgeDocumentBlock]
    ) -> None: ...

    def replace_record_links(
        self, record_id: str, links: list[StructuralLink]
    ) -> None: ...

    def list_links(self, options: LinkQueryOptions) -> list[StructuralLink]: ...


@dataclass(frozen=True, slots=True)
class VaultDiagnostic:
    code: str
    path: str
    message: str
    severity: VaultDiagnosticSeverity = "info"

    def __post_init__(self) -> None:
        if not self.code:
            raise InvalidArgumentError("diagnostic code is required")
        object.__setattr__(self, "path", _validate_path(self.path))
        if not self.message:
            raise InvalidArgumentError("diagnostic message is required")


@dataclass(frozen=True, slots=True)
class VaultFilePayload:
    path: str
    content: str = ""
    file_kind: VaultFileKind | None = None
    modified_at: str | None = None
    deleted: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", _validate_path(self.path))
        object.__setattr__(self, "file_kind", _infer_kind(self.path, self.file_kind))

    @property
    def content_hash(self) -> str:
        return _hash_text(self.content)


@dataclass(frozen=True, slots=True)
class VaultFileRecord:
    path: str
    file_kind: VaultFileKind
    record_id: str | None
    content_hash: str
    modified_at: str | None = None
    is_deleted: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", _validate_path(self.path))
        if not self.content_hash:
            raise InvalidArgumentError("content_hash is required")


@dataclass(frozen=True, slots=True)
class VaultImportOptions:
    vault_id: str
    namespace: MemoryNamespace
    scope: str
    root_label: str = "vault"
    imported_at: str | None = None
    tombstone_missing: bool = False
    resolver_candidates: list[LinkResolutionCandidate] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.vault_id:
            raise InvalidArgumentError("vault_id is required")
        if not self.scope:
            raise InvalidArgumentError("scope is required")


@dataclass(frozen=True, slots=True)
class VaultExportOptions:
    vault_id: str
    namespace: MemoryNamespace
    scope: str
    include_deleted: bool = False
    rewrite_markdown: bool = False

    def __post_init__(self) -> None:
        if not self.vault_id:
            raise InvalidArgumentError("vault_id is required")
        if not self.scope:
            raise InvalidArgumentError("scope is required")


@dataclass(frozen=True, slots=True)
class VaultManifest:
    vault_id: str
    root_label: str
    imported_at: str
    namespace: MemoryNamespace
    files: list[VaultFileRecord] = field(default_factory=list)
    options: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.vault_id:
            raise InvalidArgumentError("vault_id is required")
        if not self.imported_at:
            raise InvalidArgumentError("imported_at is required")


@dataclass(frozen=True, slots=True)
class VaultImportResult:
    manifest: VaultManifest
    created_count: int = 0
    updated_count: int = 0
    deleted_count: int = 0
    stale_count: int = 0
    repaired_count: int = 0
    diagnostics: list[VaultDiagnostic] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class VaultExportedFile:
    path: str
    content: str
    file_kind: VaultFileKind
    content_hash: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", _validate_path(self.path))
        if not self.content_hash:
            raise InvalidArgumentError("content_hash is required")


@dataclass(frozen=True, slots=True)
class VaultExportResult:
    files: list[VaultExportedFile] = field(default_factory=list)
    skipped_paths: list[str] = field(default_factory=list)
    diagnostics: list[VaultDiagnostic] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class VaultRenameOperation:
    old_path: str
    new_path: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "old_path", _validate_path(self.old_path))
        object.__setattr__(self, "new_path", _validate_path(self.new_path))
        if self.old_path == self.new_path:
            raise InvalidArgumentError("old_path and new_path must differ")


@dataclass(frozen=True, slots=True)
class VaultRepairPlan:
    vault_id: str
    namespace: MemoryNamespace
    operations: list[VaultRenameOperation] = field(default_factory=list)
    affected_link_ids: list[str] = field(default_factory=list)
    diagnostics: list[VaultDiagnostic] = field(default_factory=list)

    @property
    def changed_count(self) -> int:
        return len(self.affected_link_ids)
