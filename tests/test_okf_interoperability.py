from __future__ import annotations

from pathlib import Path

import pytest

from sophiagraph import (
    MemoryNamespace,
    OkfIndexDocument,
    OkfLogDocument,
    SophiaGraphMemoryStore,
    SophiaGraphSqliteStore,
    build_okf_navigation_packet,
    export_okf_bundle,
    import_okf_bundle,
    import_okf_bundle_into_store,
    validate_okf_bundle,
)
from sophiagraph.models import (
    OKF_SPEC_BASELINE_COMMIT,
    OKF_SPEC_BASELINE_URL,
    OkfConceptDocument,
)
from sophiagraph.query import LinkQueryOptions, ListQueryOptions
from sophiagraph.vault import VaultExportOptions, export_vault_files


def _namespace() -> MemoryNamespace:
    return MemoryNamespace(tenant_id="tenant", agent_id="agent", graph_id="main")


def _fixture_root(name: str) -> Path:
    return Path(__file__).parent / "fixtures" / "okf" / name


@pytest.fixture(params=["memory", "sqlite"])
def store(request: pytest.FixtureRequest, tmp_path: Path):
    if request.param == "memory":
        return SophiaGraphMemoryStore()
    return SophiaGraphSqliteStore(tmp_path / "okf.sqlite3")


def test_okf_import_preserves_reserved_docs_extensions_and_spec_pin() -> None:
    bundle = import_okf_bundle(_fixture_root("valid"), namespace=_namespace())

    assert bundle.manifest.spec_commit == OKF_SPEC_BASELINE_COMMIT
    assert bundle.manifest.spec_url == OKF_SPEC_BASELINE_URL
    assert bundle.manifest.okf_version == "0.1-draft"
    assert bundle.manifest.concept_count == 2
    assert bundle.manifest.index_count == 1
    assert bundle.manifest.log_count == 1
    assert bundle.manifest.reference_count == 1
    assert isinstance(bundle.indices[0], OkfIndexDocument)
    assert isinstance(bundle.logs[0], OkfLogDocument)

    roadmap = next(
        document
        for document in bundle.concepts
        if document.document.path == "Roadmap.md"
    )
    reference = bundle.references[0]

    assert isinstance(roadmap, OkfConceptDocument)
    assert roadmap.profile.extensions["custom_field"] == "keep-me"
    assert roadmap.profile.concept_type == "concept"
    assert roadmap.document.aliases == ["Plan"]
    assert reference.document_kind == "reference"
    assert reference.profile.concept_type == "reference"


def test_okf_validation_reports_missing_type_reserved_file_and_unresolved_link() -> (
    None
):
    findings = validate_okf_bundle(_fixture_root("invalid"))

    assert [(finding.code, finding.path) for finding in findings] == [
        ("missing_type", "Broken.md"),
        ("unresolved_link", "Broken.md"),
        ("reserved_frontmatter_type", "index.md"),
    ]


def test_okf_export_defaults_to_portable_markdown_and_opt_in_obsidian_mode() -> None:
    bundle = import_okf_bundle(_fixture_root("valid"), namespace=_namespace())

    portable = {payload.path: payload.content for payload in export_okf_bundle(bundle)}
    obsidian = {
        payload.path: payload.content
        for payload in export_okf_bundle(bundle, obsidian_compatible=True)
    }

    roadmap_portable = portable["Roadmap.md"]
    roadmap_obsidian = obsidian["Roadmap.md"]

    assert "[decisions](/Decision Log.md)" in roadmap_portable
    assert "[Reference Mirror](/references/Reference Mirror.md)" in roadmap_portable
    assert "[Missing](Missing.md)" in roadmap_portable
    assert "custom_field: keep-me" in roadmap_portable

    assert "[[Decision Log.md|decisions]]" in roadmap_obsidian
    assert "[[references/Reference Mirror.md|Reference Mirror]]" in roadmap_obsidian
    assert "[Missing](Missing.md)" in roadmap_obsidian


def test_okf_navigation_packet_exposes_structural_backlinks_citations_and_suggestions() -> (
    None
):
    bundle = import_okf_bundle(_fixture_root("valid"), namespace=_namespace())
    packet = build_okf_navigation_packet(bundle, current_path="Roadmap.md")

    assert packet.document_kind == "concept"
    assert {link.target_path for link in packet.outgoing_links if link.target_path} == {
        "Decision Log.md",
        "references/Reference Mirror.md",
    }
    assert {link.source_path for link in packet.backlinks} == {
        "Decision Log.md",
        "index.md",
    }
    assert [link.raw_target for link in packet.unresolved_links] == ["Missing.md"]
    assert [citation.target for citation in packet.citations] == [
        "https://example.com/docs",
        "references/Reference Mirror.md",
    ]
    assert [reference.document.path for reference in packet.references] == [
        "references/Reference Mirror.md"
    ]
    assert [candidate.target_record_id for candidate in packet.unlinked_mentions] == [
        next(
            document.document.record_id
            for document in bundle.concepts
            if document.document.path == "Decision Log.md"
        )
    ]


def test_okf_import_into_store_round_trips_through_vault_owner(store) -> None:
    namespace = _namespace()
    result = import_okf_bundle_into_store(
        store,
        _fixture_root("valid"),
        namespace=namespace,
        scope="agent:agent",
        vault_id="okf-bundle",
    )

    records = store.list_records(
        ListQueryOptions(scopes=["agent:agent"], namespaces=[namespace])
    )
    roadmap = next(record for record in records if record.title == "Roadmap")
    links = store.list_links(
        LinkQueryOptions(record_id=roadmap.id, direction="out", namespaces=[namespace])
    )
    exported = export_vault_files(
        store,
        VaultExportOptions(
            vault_id="okf-bundle",
            namespace=namespace,
            scope="agent:agent",
        ),
    )

    assert result.created_count == 5
    assert {record.title for record in records} == {
        "Bundle Index",
        "Decision Log",
        "Log",
        "Reference Mirror",
        "Roadmap",
    }
    assert any(link.resolution_status == "resolved" for link in links)
    assert any(link.resolution_status == "unresolved" for link in links)
    assert {item.path for item in exported.files} == {
        "Decision Log.md",
        "Roadmap.md",
        "index.md",
        "log.md",
        "references/Reference Mirror.md",
    }
