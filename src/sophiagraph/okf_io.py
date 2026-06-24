"""OKF bundle import/export helpers behind the stable `sophiagraph.okf` facade."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

from sophiagraph.adapters.markdown import MarkdownImport, extract_markdown
from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.models import MemoryNamespace, StructuralLink
from sophiagraph.models.okf import (
    OKF_SPEC_BASELINE_COMMIT,
    OKF_SPEC_BASELINE_URL,
    OkfBundle,
    OkfBundleManifest,
    OkfCitation,
    OkfConceptDocument,
    OkfConformanceFinding,
    OkfIndexDocument,
    OkfLogDocument,
)
from sophiagraph.storage.record_lifecycle import utc_now_iso
from sophiagraph.vault import (
    VaultFilePayload,
    VaultImportOptions,
    VaultImportResult,
    VaultStore,
    import_vault_files,
)

from .okf_support import (
    ROOT_LINK_RE,
    build_candidates,
    bundle_id,
    document_kind,
    extract_citations,
    extract_index_entries,
    extract_log_entries,
    findings_for_document,
    frontmatter_dict,
    frontmatter_for_concept,
    normalize_okf_links,
    profile_from_frontmatter,
    read_markdown_files,
    render_document,
    rewrite_body,
    stable_id,
)


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
    markdown_by_path = read_markdown_files(root)
    root_bundle_id = bundle_id(root)
    candidates = build_candidates(
        markdown_by_path,
        namespace=namespace,
        bundle_root_id=root_bundle_id,
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
        record_id = stable_id("okf-rec", root_bundle_id, path)
        imported = extract_markdown(
            text,
            path=path,
            record_id=record_id,
            namespace=namespace,
        )
        frontmatter = frontmatter_dict(imported)
        normalized_links = normalize_okf_links(
            imported,
            source_path=path,
            candidates=candidates,
        )
        citations = extract_citations(imported.body, source_path=path)
        provisional.append(
            (
                path,
                document_kind(path),
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
            findings_for_document(
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
                    entries=extract_index_entries(imported.body, source_path=path),
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
                    entries=extract_log_entries(imported.body),
                    frontmatter=frontmatter,
                    links=normalized_links,
                    blocks=list(imported.blocks),
                    citations=citations,
                )
            )
            continue
        profile = profile_from_frontmatter(frontmatter)
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
        bundle_id=root_bundle_id,
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


def export_okf_bundle(
    bundle: OkfBundle,
    *,
    obsidian_compatible: bool = False,
) -> list[VaultFilePayload]:
    files: list[VaultFilePayload] = []
    concept_like_documents = bundle.concepts + bundle.references
    for document in concept_like_documents:
        body = rewrite_body(
            document.body,
            document.links,
            obsidian_compatible=obsidian_compatible,
        )
        files.append(
            VaultFilePayload(
                path=document.document.path,
                content=render_document(
                    frontmatter=frontmatter_for_concept(document),
                    body=body,
                ),
                file_kind="markdown",
            )
        )
    for document in bundle.indices:
        body = rewrite_body(
            document.body,
            document.links,
            obsidian_compatible=obsidian_compatible,
        )
        files.append(
            VaultFilePayload(
                path=document.document.path,
                content=render_document(
                    frontmatter=dict(document.frontmatter),
                    body=body,
                ),
                file_kind="markdown",
            )
        )
    for document in bundle.logs:
        body = rewrite_body(
            document.body,
            document.links,
            obsidian_compatible=obsidian_compatible,
        )
        files.append(
            VaultFilePayload(
                path=document.document.path,
                content=render_document(
                    frontmatter=dict(document.frontmatter),
                    body=body,
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
        content=ROOT_LINK_RE.sub(r"\1\2)", payload.content),
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
    if not vault_id:
        raise InvalidArgumentError("vault_id is required")
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
