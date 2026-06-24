"""Vault import, export, and manifest flows over explicit file payloads."""

from __future__ import annotations

from sophiagraph.adapters.markdown import extract_markdown
from sophiagraph.canvas import CanvasBoard
from sophiagraph.models import KnowledgeDocumentBlock, MemoryRecord, StructuralLink
from sophiagraph.vault_support import (
    candidate_from_payload,
    dedupe_payloads,
    hash_text,
    imported_at_or_now,
    infer_kind,
    manifest_file,
    normalize_file_record,
    normalize_payload,
    record_id_for,
    record_vault_meta,
    records_for_vault,
    stable_id,
    tombstone_record,
)
from sophiagraph.vault_types import (
    VaultDiagnostic,
    VaultExportOptions,
    VaultExportResult,
    VaultExportedFile,
    VaultFilePayload,
    VaultImportOptions,
    VaultImportResult,
    VaultManifest,
    VaultStore,
)


def build_vault_manifest(
    files: list[VaultFilePayload],
    options: VaultImportOptions,
) -> VaultManifest:
    imported_at = imported_at_or_now(options.imported_at)
    accepted, _ = dedupe_payloads([normalize_payload(payload) for payload in files])
    return VaultManifest(
        vault_id=options.vault_id,
        root_label=options.root_label,
        imported_at=imported_at,
        namespace=options.namespace,
        files=[
            normalize_file_record(
                manifest_file(
                    payload,
                    record_id=None
                    if payload.deleted
                    else record_id_for(options, payload.path),
                )
            )
            for payload in accepted
        ],
        options={"tombstone_missing": options.tombstone_missing},
    )


def import_vault_files(
    store: VaultStore,
    files: list[VaultFilePayload],
    options: VaultImportOptions,
) -> VaultImportResult:
    imported_at = imported_at_or_now(options.imported_at)
    normalized = [normalize_payload(payload) for payload in files]
    accepted, diagnostics = dedupe_payloads(normalized)
    existing_records = records_for_vault(
        store,
        vault_id=options.vault_id,
        namespace=options.namespace,
        scope=options.scope,
    )
    existing_by_path = {
        str(record_vault_meta(record).get("path")): record
        for record in existing_records
        if record_vault_meta(record).get("path")
    }
    candidates = [
        candidate
        for candidate in (
            candidate_from_payload(payload, options) for payload in accepted
        )
        if candidate is not None
    ]
    candidates.extend(options.resolver_candidates)
    created = updated = deleted = stale = 0
    manifest_files = []
    seen_paths: set[str] = set()
    for payload in accepted:
        seen_paths.add(payload.path)
        existing = existing_by_path.get(payload.path)
        if payload.deleted:
            if existing is not None:
                tombstone = tombstone_record(
                    existing, when=imported_at, reason="vault import deletion"
                )
                store.put_record(tombstone)
                store.put_document_blocks(tombstone.id, [])
                store.replace_record_links(tombstone.id, [])
                deleted += 1
            manifest_files.append(
                normalize_file_record(manifest_file(payload, record_id=None))
            )
            continue
        record, links, blocks = _record_for_payload(
            payload,
            options=options,
            imported_at=imported_at,
            existing=existing,
            resolver_candidates=candidates,
        )
        previous_hash = (
            str(record_vault_meta(existing).get("content_hash"))
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
        manifest_files.append(
            normalize_file_record(manifest_file(payload, record_id=record.id))
        )
    if options.tombstone_missing:
        for path, record in existing_by_path.items():
            if path in seen_paths or record.is_deleted:
                continue
            tombstone = tombstone_record(
                record, when=imported_at, reason="vault import missing file"
            )
            store.put_record(tombstone)
            store.put_document_blocks(tombstone.id, [])
            store.replace_record_links(tombstone.id, [])
            deleted += 1
            stale += 1
            manifest_files.append(
                normalize_file_record(
                    manifest_file(
                        VaultFilePayload(
                            path=path,
                            content="",
                            file_kind=str(
                                record_vault_meta(record).get("file_kind") or "asset"
                            ),  # type: ignore[arg-type]
                            deleted=True,
                        ),
                        record_id=record.id,
                    )
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
    records = records_for_vault(
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
        records, key=lambda item: str(record_vault_meta(item).get("path"))
    ):
        meta = record_vault_meta(record)
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
        files.append(
            VaultExportedFile(
                path=path,
                content=content,
                file_kind=str(meta.get("file_kind") or infer_kind(path)),  # type: ignore[arg-type]
                content_hash=hash_text(content),
            )
        )
    return VaultExportResult(
        files=files,
        skipped_paths=skipped,
        diagnostics=diagnostics,
    )


def _record_for_payload(
    payload: VaultFilePayload,
    *,
    options: VaultImportOptions,
    imported_at: str,
    existing: MemoryRecord | None,
    resolver_candidates: list,
) -> tuple[MemoryRecord, list[StructuralLink], list[KnowledgeDocumentBlock]]:
    record_id = record_id_for(options, payload.path)
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
            board_id=stable_id("canvas", options.vault_id, payload.path),
            namespace=options.namespace,
        )
        properties = {}
        document_meta = {
            "document_id": stable_id("doc", options.vault_id, payload.path),
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
        blocks = []
    else:
        properties = {}
        document_meta = {
            "document_id": stable_id("doc", options.vault_id, payload.path),
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
