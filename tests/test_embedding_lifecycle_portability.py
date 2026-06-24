from __future__ import annotations

import io
import json
import tarfile

from sophiagraph import (
    ActiveEmbeddingModelSet,
    MemoryNamespace,
    SophiaGraphMemoryStore,
    VectorSpaceModelDescriptor,
)
from sophiagraph.portability.codec import read_bundle_snapshot, write_bundle_snapshot
from sophiagraph.portability.models import (
    MemoryBundleExportOptions,
    MemoryBundleImportOptions,
)


def _ns() -> MemoryNamespace:
    return MemoryNamespace(tenant_id="tenant", agent_id="portable", graph_id="main")


def _active_set() -> ActiveEmbeddingModelSet:
    return ActiveEmbeddingModelSet(
        namespace=_ns(),
        vector_space="semantic",
        active_models=(
            VectorSpaceModelDescriptor(
                provider="provider-a",
                model="model-v2",
                dimension=4,
            ),
        ),
        updated_at="2026-06-06T00:00:00+00:00",
    )


def _rewrite_bundle_without_embedding_lifecycle(source, dest) -> None:
    with tarfile.open(source, "r:gz") as archive:
        members = {
            member.name: archive.extractfile(member).read()
            for member in archive.getmembers()
            if member.isfile()
        }
    manifest_name = "memory-bundle/manifest.json"
    manifest = json.loads(members[manifest_name].decode("utf-8"))
    members = {
        name: payload
        for name, payload in members.items()
        if not name.endswith("embedding_lifecycle.jsonl")
    }
    manifest["files"].pop("embedding_lifecycle.jsonl", None)
    manifest["counts"]["active_embedding_model_sets"] = 0
    manifest["sections"]["active_embedding_model_sets"] = False
    members[manifest_name] = json.dumps(manifest, sort_keys=True, indent=2).encode(
        "utf-8"
    )
    with tarfile.open(dest, "w:gz") as archive:
        for name, payload in members.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))


def test_embedding_lifecycle_bundle_round_trip_and_backward_compat(tmp_path) -> None:
    source = SophiaGraphMemoryStore()
    source.put_active_model_set(_active_set())

    snapshot = source.export_snapshot(
        MemoryBundleExportOptions(
            scopes=["agent:portable"],
            include_embedding_lifecycle=True,
            namespaces=[_ns()],
        )
    )
    bundle_path = write_bundle_snapshot(
        snapshot, tmp_path / "embedding-lifecycle.tar.gz"
    )
    restored = read_bundle_snapshot(bundle_path)

    assert restored.manifest["counts"]["active_embedding_model_sets"] == 1
    assert len(restored.active_embedding_model_sets) == 1

    dest = SophiaGraphMemoryStore()
    result = dest.import_snapshot(
        restored,
        MemoryBundleImportOptions(),
    )
    assert result.imported_active_embedding_model_sets == 1
    assert dest.list_active_model_sets(namespaces=[_ns()]) == [_active_set()]

    downgraded_bundle = tmp_path / "embedding-lifecycle-old.tar.gz"
    _rewrite_bundle_without_embedding_lifecycle(bundle_path, downgraded_bundle)
    downgraded = read_bundle_snapshot(downgraded_bundle)
    assert downgraded.active_embedding_model_sets == []
