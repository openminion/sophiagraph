from __future__ import annotations

from dataclasses import replace
import io
import json
import tarfile

import pytest

from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.models import MemoryNamespace, MemoryRecord
from sophiagraph.portability.codec import (
    MEMORY_BUNDLE_VERSION,
    json_dumps,
    read_bundle_snapshot,
    write_bundle_snapshot,
)
from sophiagraph.portability.models import (
    MemoryBundleExportOptions,
    MemoryBundleImportOptions,
    MemoryBundleSnapshot,
)
from sophiagraph.query import ListQueryOptions
from sophiagraph.storage import SophiaGraphMemoryStore


def _record(
    record_id: str,
    *,
    scope: str = "agent:portable",
    namespace: MemoryNamespace | None = None,
) -> MemoryRecord:
    return MemoryRecord(
        id=record_id,
        scope=scope,
        type="fact",
        key=f"fact:{record_id}",
        title=f"Portable {record_id}",
        content={"text": f"{record_id} content"},
        created_at="2026-05-25T00:00:00+00:00",
        updated_at="2026-05-25T00:00:00+00:00",
        source="imported",
        namespace=namespace,
    )


def _rewrite_bundle(source, dest, transform) -> None:
    with tarfile.open(source, "r:gz") as archive:
        members = {
            member.name: archive.extractfile(member).read()
            for member in archive.getmembers()
            if member.isfile()
        }
    members = transform(members)
    with tarfile.open(dest, "w:gz") as archive:
        for name, payload in members.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))


def test_bundle_reader_rejects_missing_manifest_checksum_and_versions(tmp_path) -> None:
    snapshot = MemoryBundleSnapshot(manifest={}, records=[_record("rec-bundle")])
    valid_path = write_bundle_snapshot(snapshot, tmp_path / "valid.tar.gz")

    missing_manifest = tmp_path / "missing-manifest.tar.gz"
    _rewrite_bundle(
        valid_path,
        missing_manifest,
        lambda members: {
            name: payload
            for name, payload in members.items()
            if not name.endswith("manifest.json")
        },
    )
    with pytest.raises(InvalidArgumentError, match="missing manifest"):
        read_bundle_snapshot(missing_manifest)

    checksum_mismatch = tmp_path / "checksum-mismatch.tar.gz"
    _rewrite_bundle(
        valid_path,
        checksum_mismatch,
        lambda members: {
            name: (b"corrupt\n" if name.endswith("records.jsonl") else payload)
            for name, payload in members.items()
        },
    )
    with pytest.raises(InvalidArgumentError, match="checksum mismatch"):
        read_bundle_snapshot(checksum_mismatch)

    unsupported_version = tmp_path / "unsupported-version.tar.gz"

    def mutate_version(members: dict[str, bytes]) -> dict[str, bytes]:
        manifest_name = "memory-bundle/manifest.json"
        manifest = json.loads(members[manifest_name].decode("utf-8"))
        manifest["bundle_version"] = "memory_bundle.v0"
        return {**members, manifest_name: json_dumps(manifest).encode("utf-8")}

    _rewrite_bundle(valid_path, unsupported_version, mutate_version)
    with pytest.raises(InvalidArgumentError, match="unsupported bundle_version"):
        read_bundle_snapshot(unsupported_version)


def test_bundle_reader_allows_absent_optional_sections(tmp_path) -> None:
    path = write_bundle_snapshot(
        MemoryBundleSnapshot(manifest={}, records=[_record("rec-partial")]),
        tmp_path / "partial.tar.gz",
    )

    snapshot = read_bundle_snapshot(path)

    assert snapshot.manifest["bundle_version"] == MEMORY_BUNDLE_VERSION
    assert [record.id for record in snapshot.records] == ["rec-partial"]
    assert snapshot.candidates == []
    assert snapshot.relations == []
    assert snapshot.tier_transitions == []


def test_import_snapshot_dry_run_conflicts_scope_rewrites_and_namespace_allowlist() -> (
    None
):
    alpha = MemoryNamespace(tenant_id="tenant", agent_id="alpha")
    beta = MemoryNamespace(tenant_id="tenant", agent_id="beta")
    source = SophiaGraphMemoryStore()
    source.put_record(_record("rec-alpha", namespace=alpha))
    source.put_record(
        _record("rec-beta", scope="agent:beta", namespace=beta),
    )
    snapshot = source.export_snapshot(
        MemoryBundleExportOptions(scopes=["agent:portable", "agent:beta"])
    )
    dest = SophiaGraphMemoryStore()

    dry_run = dest.import_snapshot(
        snapshot,
        MemoryBundleImportOptions(
            dry_run=True,
            namespace_allowlist=[MemoryNamespace(agent_id="alpha")],
            scope_rewrites={"agent:portable": "agent:rewritten"},
        ),
    )

    assert dry_run.applied is False
    assert dry_run.imported_records == 1
    assert dry_run.skipped_records == 1
    assert dry_run.rewrites == {"agent:portable": "agent:rewritten"}
    assert dest.list_records(ListQueryOptions(scopes=["agent:rewritten"])) == []

    applied = dest.import_snapshot(
        snapshot,
        MemoryBundleImportOptions(
            namespace_allowlist=[MemoryNamespace(agent_id="alpha")],
            scope_rewrites={"agent:portable": "agent:rewritten"},
        ),
    )
    assert applied.applied is True
    assert applied.imported_records == 1
    assert [
        record.scope
        for record in dest.list_records(ListQueryOptions(scopes=["agent:rewritten"]))
    ] == ["agent:rewritten"]

    with pytest.raises(InvalidArgumentError, match="record already exists"):
        dest.import_snapshot(
            replace(snapshot, records=[snapshot.records[0]]),
            MemoryBundleImportOptions(conflict_mode="error"),
        )
