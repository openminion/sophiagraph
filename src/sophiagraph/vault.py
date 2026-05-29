"""Vault import/export adapters over explicit file payloads."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from hashlib import sha256
from pathlib import PurePosixPath
from typing import Literal, Protocol
from uuid import NAMESPACE_URL, uuid5

from sophiagraph.adapters.markdown import extract_markdown
from sophiagraph.canvas import CanvasBoard
from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.models import (
    KnowledgeDocumentBlock,
    LinkResolutionCandidate,
    MemoryNamespace,
    MemoryRecord,
    StructuralLink,
    split_target_parts,
)
from sophiagraph.query import LinkQueryOptions, ListQueryOptions
from sophiagraph.storage.record_lifecycle import utc_now_iso

VaultFileKind = Literal["markdown", "canvas", "asset"]
VaultDiagnosticSeverity = Literal["info", "warning", "error"]


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


def _hash_text(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _namespace_key(namespace: MemoryNamespace) -> str:
    return "|".join(
        f"{key}={value}" for key, value in sorted(namespace.as_dict().items())
    )


def _stable_id(prefix: str, *parts: str) -> str:
    return f"{prefix}-{uuid5(NAMESPACE_URL, ':'.join(parts))}"


def _validate_path(path: str) -> str:
    normalized = str(PurePosixPath(str(path or "").replace("\\", "/")))
    if not normalized or normalized == ".":
        raise InvalidArgumentError("path is required")
    if normalized.startswith("/") or normalized.startswith("../"):
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


@dataclass(frozen=True, slots=True)
class VaultDiagnostic:
    code: str
    path: str
    message: str
    severity: VaultDiagnosticSeverity = "info"

    def __post_init__(self) -> None:
        if not self.code:
            raise InvalidArgumentError("diagnostic code is required")
        _validate_path(self.path)
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


def _record_id_for(options: VaultImportOptions | VaultExportOptions, path: str) -> str:
    return _stable_id(
        "vault-rec", options.vault_id, _namespace_key(options.namespace), path
    )


def _record_vault_meta(record: MemoryRecord) -> dict[str, object]:
    vault_meta = record.meta.get("vault")
    return vault_meta if isinstance(vault_meta, dict) else {}


def _records_for_vault(
    store: VaultStore,
    *,
    vault_id: str,
    namespace: MemoryNamespace,
    scope: str,
    include_deleted: bool = True,
) -> list[MemoryRecord]:
    records = store.list_records(
        ListQueryOptions(
            scopes=[scope],
            namespaces=[namespace],
            include_invalidated=True,
            limit=None,
        )
    )
    return [
        record
        for record in records
        if _record_vault_meta(record).get("vault_id") == vault_id
        if include_deleted or not record.is_deleted
    ]


def _candidate_from_payload(
    payload: VaultFilePayload,
    options: VaultImportOptions,
) -> LinkResolutionCandidate | None:
    if payload.deleted or payload.file_kind != "markdown":
        return None
    record_id = _record_id_for(options, payload.path)
    imported = extract_markdown(
        payload.content,
        path=payload.path,
        record_id=record_id,
        namespace=options.namespace,
    )
    return LinkResolutionCandidate(
        record_id=record_id,
        path=payload.path,
        title=imported.document.title,
        aliases=imported.document.aliases,
        namespace=options.namespace,
    )


def _dedupe_payloads(
    files: list[VaultFilePayload],
) -> tuple[list[VaultFilePayload], list[VaultDiagnostic]]:
    seen: set[str] = set()
    accepted: list[VaultFilePayload] = []
    diagnostics: list[VaultDiagnostic] = []
    for payload in files:
        if payload.path in seen:
            diagnostics.append(
                VaultDiagnostic(
                    code="duplicate_path",
                    path=payload.path,
                    message=f"duplicate vault path skipped: {payload.path}",
                    severity="warning",
                )
            )
            continue
        seen.add(payload.path)
        accepted.append(payload)
    return accepted, diagnostics


def _manifest_file(
    payload: VaultFilePayload,
    *,
    record_id: str | None,
) -> VaultFileRecord:
    return VaultFileRecord(
        path=payload.path,
        file_kind=payload.file_kind or _infer_kind(payload.path),
        record_id=record_id,
        content_hash=payload.content_hash,
        modified_at=payload.modified_at,
        is_deleted=payload.deleted,
    )


def build_vault_manifest(
    files: list[VaultFilePayload],
    options: VaultImportOptions,
) -> VaultManifest:
    imported_at = options.imported_at or utc_now_iso()
    accepted, _ = _dedupe_payloads(files)
    return VaultManifest(
        vault_id=options.vault_id,
        root_label=options.root_label,
        imported_at=imported_at,
        namespace=options.namespace,
        files=[
            _manifest_file(
                payload,
                record_id=None
                if payload.deleted
                else _record_id_for(options, payload.path),
            )
            for payload in accepted
        ],
        options={"tombstone_missing": options.tombstone_missing},
    )


def _record_for_payload(
    payload: VaultFilePayload,
    *,
    options: VaultImportOptions,
    imported_at: str,
    existing: MemoryRecord | None,
    resolver_candidates: list[LinkResolutionCandidate],
) -> tuple[MemoryRecord, list[StructuralLink], list[KnowledgeDocumentBlock]]:
    record_id = _record_id_for(options, payload.path)
    if payload.file_kind == "markdown":
        imported = extract_markdown(
            payload.content,
            path=payload.path,
            record_id=record_id,
            namespace=options.namespace,
            resolver_candidates=resolver_candidates,
        )
        properties = {prop.name: prop.value for prop in imported.properties}
        document_meta = imported.document.as_record_meta()
        content = {
            "text": imported.body,
            "source_text": payload.content,
        }
        title = imported.document.title
        tags = imported.tags
        links = imported.links
        blocks = list(imported.blocks)
    elif payload.file_kind == "canvas":
        CanvasBoard.from_json(
            payload.content,
            board_id=_stable_id("canvas", options.vault_id, payload.path),
            namespace=options.namespace,
        )
        properties = {}
        document_meta = {
            "document_id": _stable_id("doc", options.vault_id, payload.path),
            "path": payload.path,
            "title": payload.path.rsplit("/", 1)[-1],
            "aliases": [],
            "content_hash": payload.content_hash,
            "source_format": "json",
            "provenance": {"adapter": "vault", "file_kind": "canvas"},
        }
        content = {"text": payload.content, "source_text": payload.content}
        title = payload.path.rsplit("/", 1)[-1]
        tags = []
        links = []
        blocks: list[KnowledgeDocumentBlock] = []
    else:
        properties = {}
        document_meta = {
            "document_id": _stable_id("doc", options.vault_id, payload.path),
            "path": payload.path,
            "title": payload.path.rsplit("/", 1)[-1],
            "aliases": [],
            "content_hash": payload.content_hash,
            "source_format": "external",
            "provenance": {"adapter": "vault", "file_kind": "asset"},
        }
        content = {"text": payload.content, "source_text": payload.content}
        title = payload.path.rsplit("/", 1)[-1]
        tags = []
        links = []
        blocks = []
    existing_meta = dict(existing.meta) if existing is not None else {}
    meta = {
        **existing_meta,
        "document": document_meta,
        "properties": properties,
        "vault": {
            "vault_id": options.vault_id,
            "root_label": options.root_label,
            "path": payload.path,
            "file_kind": payload.file_kind,
            "content_hash": payload.content_hash,
            "source_text": payload.content,
            "modified_at": payload.modified_at,
            "imported_at": imported_at,
        },
    }
    record = MemoryRecord(
        id=record_id,
        scope=options.scope,
        type="artifact_digest",
        key=f"vault:{options.vault_id}:{payload.path}",
        title=title,
        content=content,
        tags=tags,
        source="imported",
        confidence=1.0,
        created_at=existing.created_at if existing is not None else imported_at,
        updated_at=imported_at,
        namespace=options.namespace,
        meta=meta,
        event_time=imported_at,
        is_deleted=False,
        deleted_at=None,
        deleted_reason=None,
    )
    return record, links, blocks


def _tombstone_record(record: MemoryRecord, *, when: str, reason: str) -> MemoryRecord:
    return replace(
        record,
        updated_at=when,
        is_deleted=True,
        deleted_at=when,
        deleted_reason=reason,
    )


def import_vault_files(
    store: VaultStore,
    files: list[VaultFilePayload],
    options: VaultImportOptions,
) -> VaultImportResult:
    imported_at = options.imported_at or utc_now_iso()
    accepted, diagnostics = _dedupe_payloads(files)
    existing_records = _records_for_vault(
        store,
        vault_id=options.vault_id,
        namespace=options.namespace,
        scope=options.scope,
    )
    existing_by_path = {
        str(_record_vault_meta(record).get("path")): record
        for record in existing_records
        if _record_vault_meta(record).get("path")
    }
    candidates = [
        candidate
        for candidate in (
            _candidate_from_payload(payload, options) for payload in accepted
        )
        if candidate is not None
    ]
    candidates.extend(options.resolver_candidates)
    created = updated = deleted = stale = 0
    manifest_files: list[VaultFileRecord] = []
    seen_paths: set[str] = set()
    for payload in accepted:
        seen_paths.add(payload.path)
        existing = existing_by_path.get(payload.path)
        if payload.deleted:
            if existing is not None:
                tombstone = _tombstone_record(
                    existing, when=imported_at, reason="vault import deletion"
                )
                store.put_record(tombstone)
                store.put_document_blocks(tombstone.id, [])
                store.replace_record_links(tombstone.id, [])
                deleted += 1
            manifest_files.append(_manifest_file(payload, record_id=None))
            continue
        record, links, blocks = _record_for_payload(
            payload,
            options=options,
            imported_at=imported_at,
            existing=existing,
            resolver_candidates=candidates,
        )
        previous_hash = (
            str(_record_vault_meta(existing).get("content_hash"))
            if existing is not None
            else None
        )
        store.put_record(record)
        store.put_document_blocks(record.id, blocks)
        store.replace_record_links(record.id, links)
        if existing is None or existing.is_deleted:
            created += 1
        elif previous_hash != payload.content_hash:
            updated += 1
        manifest_files.append(_manifest_file(payload, record_id=record.id))
    if options.tombstone_missing:
        for path, record in existing_by_path.items():
            if path in seen_paths or record.is_deleted:
                continue
            tombstone = _tombstone_record(
                record, when=imported_at, reason="vault import missing file"
            )
            store.put_record(tombstone)
            store.put_document_blocks(tombstone.id, [])
            store.replace_record_links(tombstone.id, [])
            deleted += 1
            stale += 1
            manifest_files.append(
                VaultFileRecord(
                    path=path,
                    file_kind=str(
                        _record_vault_meta(record).get("file_kind") or "asset"
                    ),  # type: ignore[arg-type]
                    record_id=record.id,
                    content_hash=str(_record_vault_meta(record).get("content_hash")),
                    is_deleted=True,
                )
            )
    return VaultImportResult(
        manifest=VaultManifest(
            vault_id=options.vault_id,
            root_label=options.root_label,
            imported_at=imported_at,
            namespace=options.namespace,
            files=sorted(manifest_files, key=lambda item: item.path),
            options={"tombstone_missing": options.tombstone_missing},
        ),
        created_count=created,
        updated_count=updated,
        deleted_count=deleted,
        stale_count=stale,
        diagnostics=diagnostics,
    )


def export_vault_files(
    store: VaultStore,
    options: VaultExportOptions,
) -> VaultExportResult:
    records = _records_for_vault(
        store,
        vault_id=options.vault_id,
        namespace=options.namespace,
        scope=options.scope,
        include_deleted=options.include_deleted,
    )
    files: list[VaultExportedFile] = []
    skipped: list[str] = []
    diagnostics: list[VaultDiagnostic] = []
    seen_paths: set[str] = set()
    for record in sorted(
        records, key=lambda item: str(_record_vault_meta(item).get("path"))
    ):
        meta = _record_vault_meta(record)
        path = str(meta.get("path") or "")
        if not path:
            continue
        if path in seen_paths:
            skipped.append(path)
            diagnostics.append(
                VaultDiagnostic(
                    code="export_collision",
                    path=path,
                    message=f"duplicate export path skipped: {path}",
                    severity="warning",
                )
            )
            continue
        seen_paths.add(path)
        if record.is_deleted and not options.include_deleted:
            skipped.append(path)
            continue
        if options.rewrite_markdown:
            diagnostics.append(
                VaultDiagnostic(
                    code="rewrite_not_supported",
                    path=path,
                    message="rewritten export is intentionally not implemented; source text emitted",
                    severity="warning",
                )
            )
        content = str(meta.get("source_text") or "")
        if not content and isinstance(record.content, dict):
            content = str(
                record.content.get("source_text") or record.content.get("text") or ""
            )
        kind = str(meta.get("file_kind") or _infer_kind(path))
        files.append(
            VaultExportedFile(
                path=path,
                content=content,
                file_kind=kind,  # type: ignore[arg-type]
                content_hash=_hash_text(content),
            )
        )
    return VaultExportResult(
        files=files,
        skipped_paths=skipped,
        diagnostics=diagnostics,
    )


def _rewrite_link_target(
    raw_target: str, operation: VaultRenameOperation
) -> str | None:
    target_with_anchor, alias_separator, alias = raw_target.partition("|")
    target_part, heading, block_id = split_target_parts(target_with_anchor)
    old_path = operation.old_path
    old_stem = old_path.removesuffix(".md")
    matches = {old_path.lower(), old_stem.lower()}
    if target_part.lower() not in matches:
        return None
    suffix = ""
    if block_id:
        suffix = f"#^{block_id}"
    elif heading:
        suffix = f"#{heading}"
    alias_suffix = f"{alias_separator}{alias}" if alias_separator else ""
    return f"{operation.new_path}{suffix}{alias_suffix}"


def plan_vault_repairs(
    store: VaultStore,
    operations: list[VaultRenameOperation],
    options: VaultExportOptions,
) -> VaultRepairPlan:
    records = _records_for_vault(
        store,
        vault_id=options.vault_id,
        namespace=options.namespace,
        scope=options.scope,
        include_deleted=True,
    )
    affected: list[str] = []
    diagnostics: list[VaultDiagnostic] = []
    existing_paths = {
        str(_record_vault_meta(record).get("path"))
        for record in records
        if _record_vault_meta(record).get("path")
    }
    for operation in operations:
        if operation.new_path in existing_paths:
            diagnostics.append(
                VaultDiagnostic(
                    code="repair_target_conflict",
                    path=operation.new_path,
                    message=f"repair target already exists: {operation.new_path}",
                    severity="warning",
                )
            )
        for record in records:
            for link in store.list_links(
                LinkQueryOptions(
                    record_id=record.id,
                    direction="out",
                    namespaces=[options.namespace],
                )
            ):
                if link.target_path == operation.old_path or _rewrite_link_target(
                    link.raw_target, operation
                ):
                    affected.append(link.link_id)
    return VaultRepairPlan(
        vault_id=options.vault_id,
        namespace=options.namespace,
        operations=list(operations),
        affected_link_ids=sorted(set(affected)),
        diagnostics=diagnostics,
    )


def apply_vault_repair_plan(
    store: VaultStore,
    plan: VaultRepairPlan,
    options: VaultExportOptions,
) -> VaultRepairPlan:
    records = _records_for_vault(
        store,
        vault_id=options.vault_id,
        namespace=options.namespace,
        scope=options.scope,
        include_deleted=True,
    )
    changed: list[str] = []
    for record in records:
        outgoing = store.list_links(
            LinkQueryOptions(
                record_id=record.id,
                direction="out",
                namespaces=[options.namespace],
            )
        )
        rewritten: list[StructuralLink] = []
        touched = False
        for link in outgoing:
            updated = link
            for operation in plan.operations:
                new_raw = _rewrite_link_target(link.raw_target, operation)
                if new_raw is None and link.target_path != operation.old_path:
                    continue
                updated = replace(
                    updated,
                    raw_target=new_raw or updated.raw_target,
                    target_path=operation.new_path
                    if updated.target_path == operation.old_path
                    else updated.target_path,
                    meta={
                        **dict(updated.meta),
                        "vault_repair": {
                            "old_path": operation.old_path,
                            "new_path": operation.new_path,
                        },
                    },
                )
                touched = True
                changed.append(updated.link_id)
            rewritten.append(updated)
        if touched:
            store.replace_record_links(record.id, rewritten)
    return VaultRepairPlan(
        vault_id=plan.vault_id,
        namespace=plan.namespace,
        operations=list(plan.operations),
        affected_link_ids=sorted(set(changed)),
        diagnostics=list(plan.diagnostics),
    )


__all__ = [
    "VaultDiagnostic",
    "VaultExportOptions",
    "VaultExportResult",
    "VaultExportedFile",
    "VaultFileKind",
    "VaultFilePayload",
    "VaultFileRecord",
    "VaultImportOptions",
    "VaultImportResult",
    "VaultManifest",
    "VaultRenameOperation",
    "VaultRepairPlan",
    "apply_vault_repair_plan",
    "build_vault_manifest",
    "export_vault_files",
    "import_vault_files",
    "plan_vault_repairs",
]
