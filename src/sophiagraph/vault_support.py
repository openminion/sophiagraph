"""Private helpers shared across vault import, export, and repair flows."""

from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
from pathlib import PurePosixPath
from uuid import NAMESPACE_URL, uuid5

from sophiagraph.adapters.markdown import extract_markdown
from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.models import MemoryNamespace, MemoryRecord, split_target_parts
from sophiagraph.models.namespace import sorted_namespace_key
from sophiagraph.query import ListQueryOptions
from sophiagraph.storage.record_lifecycle import utc_now_iso
from sophiagraph.vault_types import (
    VaultDiagnostic,
    VaultFileKind,
    VaultFilePayload,
    VaultFileRecord,
    VaultImportOptions,
    VaultRenameOperation,
    VaultStore,
)


def hash_text(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def stable_id(prefix: str, *parts: str) -> str:
    return f"{prefix}-{uuid5(NAMESPACE_URL, ':'.join(parts))}"


def validate_path(path: str) -> str:
    normalized = str(PurePosixPath(str(path or "").replace("\\", "/")))
    if not normalized or normalized == ".":
        raise InvalidArgumentError("path is required")
    if normalized.startswith("/") or normalized.startswith("../"):
        raise InvalidArgumentError("path must be relative and cannot traverse parents")
    if ".." in normalized.split("/"):
        raise InvalidArgumentError("path must be relative and cannot traverse parents")
    return normalized


def infer_kind(path: str, explicit: VaultFileKind | None = None) -> VaultFileKind:
    if explicit is not None:
        return explicit
    lowered = path.lower()
    if lowered.endswith(".md"):
        return "markdown"
    if lowered.endswith(".canvas"):
        return "canvas"
    return "asset"


def record_id_for(options: VaultImportOptions, path: str) -> str:
    return stable_id(
        "vault-rec",
        options.vault_id,
        sorted_namespace_key(options.namespace),
        path,
    )


def record_vault_meta(record: MemoryRecord) -> dict[str, object]:
    vault_meta = record.meta.get("vault")
    return vault_meta if isinstance(vault_meta, dict) else {}


def records_for_vault(
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
        if record_vault_meta(record).get("vault_id") == vault_id
        if include_deleted or not record.is_deleted
    ]


def candidate_from_payload(
    payload: VaultFilePayload,
    options: VaultImportOptions,
):
    if payload.deleted or payload.file_kind != "markdown":
        return None
    record_id = record_id_for(options, payload.path)
    imported = extract_markdown(
        payload.content,
        path=payload.path,
        record_id=record_id,
        namespace=options.namespace,
    )
    from sophiagraph.models import LinkResolutionCandidate

    return LinkResolutionCandidate(
        record_id=record_id,
        path=payload.path,
        title=imported.document.title,
        aliases=imported.document.aliases,
        namespace=options.namespace,
    )


def dedupe_payloads(
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


def manifest_file(
    payload: VaultFilePayload,
    *,
    record_id: str | None,
) -> VaultFileRecord:
    return VaultFileRecord(
        path=payload.path,
        file_kind=payload.file_kind or infer_kind(payload.path),
        record_id=record_id,
        content_hash=payload.content_hash,
        modified_at=payload.modified_at,
        is_deleted=payload.deleted,
    )


def rewrite_link_target(raw_target: str, operation: VaultRenameOperation) -> str | None:
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


def tombstone_record(record: MemoryRecord, *, when: str, reason: str) -> MemoryRecord:
    return replace(
        record,
        updated_at=when,
        is_deleted=True,
        deleted_at=when,
        deleted_reason=reason,
    )


def normalize_payload(payload: VaultFilePayload) -> VaultFilePayload:
    path = validate_path(payload.path)
    return replace(payload, path=path, file_kind=infer_kind(path, payload.file_kind))


def normalize_diagnostic(diagnostic: VaultDiagnostic) -> VaultDiagnostic:
    return replace(diagnostic, path=validate_path(diagnostic.path))


def normalize_file_record(file_record: VaultFileRecord) -> VaultFileRecord:
    return replace(file_record, path=validate_path(file_record.path))


def imported_at_or_now(imported_at: str | None) -> str:
    return imported_at or utc_now_iso()
