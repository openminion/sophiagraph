"""Bundle manifest, JSONL, and tarball helpers for durable-knowledge portability."""

from __future__ import annotations

from dataclasses import asdict
from hashlib import sha256
import io
import json
from pathlib import Path
import tarfile
from typing import Any

from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.contracts.provenance import TurnProvenanceTrace
from sophiagraph.contracts.types import MEMORY_CONTRACT_VERSION
from sophiagraph.models import (
    ActiveEmbeddingModelSet,
    MemoryBlock,
    MemoryNamespace,
    RetentionSnapshot,
)
from sophiagraph.portability.models import MemoryBundleSnapshot
from sophiagraph.portability.row_codec import (
    candidate_from_dict,
    json_dumps,
    memory_block_from_dict,
    record_from_dict,
    relation_from_dict,
    tier_transition_from_dict,
)

MEMORY_BUNDLE_VERSION = "memory_bundle.v1"
_BUNDLE_ROOT = "memory-bundle"
_MANIFEST_NAME = "manifest.json"


def _sha256_bytes(data: bytes) -> str:
    return sha256(data).hexdigest()


def _serialize_rows(rows: list[Any]) -> bytes:
    payload = "\n".join(json_dumps(asdict(row)) for row in rows)
    if payload:
        payload += "\n"
    return payload.encode("utf-8")


def _hydrate_jsonl(data: bytes, factory) -> list[Any]:
    lines = [line.strip() for line in data.decode("utf-8").splitlines() if line.strip()]
    result: list[Any] = []
    for line in lines:
        payload = json.loads(line)
        if not isinstance(payload, dict):
            raise InvalidArgumentError("bundle row must decode to an object")
        result.append(factory(payload))
    return result


def build_manifest(
    *,
    snapshot: MemoryBundleSnapshot,
    files: dict[str, bytes] | None = None,
) -> dict[str, Any]:
    manifest = dict(snapshot.manifest or {})
    manifest["bundle_version"] = MEMORY_BUNDLE_VERSION
    manifest["memory_contract_version"] = MEMORY_CONTRACT_VERSION
    manifest.setdefault(
        "bundle_id", manifest.get("bundle_id") or snapshot.manifest.get("bundle_id", "")
    )
    manifest["counts"] = {
        "records": len(snapshot.records),
        "candidates": len(snapshot.candidates),
        "relations": len(snapshot.relations),
        "tier_transitions": len(snapshot.tier_transitions),
        "provenance_traces": len(snapshot.provenance_traces),
        "memory_blocks": len(snapshot.memory_blocks),
        "ontologies": len(snapshot.ontologies),
        "active_embedding_model_sets": len(snapshot.active_embedding_model_sets),
        "retention_snapshots": len(snapshot.retention_snapshots),
    }
    manifest["sections"] = {
        "records": True,
        "candidates": bool(snapshot.candidates),
        "relations": bool(snapshot.relations),
        "tier_transitions": bool(snapshot.tier_transitions),
        "provenance_traces": bool(snapshot.provenance_traces),
        "memory_blocks": bool(snapshot.memory_blocks),
        "ontologies": bool(snapshot.ontologies),
        "active_embedding_model_sets": bool(snapshot.active_embedding_model_sets),
        "retention_snapshots": bool(snapshot.retention_snapshots),
    }
    manifest["artifacts_included"] = False
    manifest.setdefault("files", {})
    if files is not None:
        manifest["files"] = {
            name: {
                "sha256": _sha256_bytes(payload),
                "byte_count": len(payload),
            }
            for name, payload in files.items()
        }
    return manifest


def _memory_block_to_payload(block: MemoryBlock) -> dict[str, Any]:
    payload = asdict(block)
    namespace = block.owner_namespace
    if isinstance(namespace, MemoryNamespace):
        payload["owner_namespace"] = namespace.as_dict()
    payload["provenance"] = dict(block.provenance)
    return payload


def _serialize_memory_blocks(blocks: list[MemoryBlock]) -> bytes:
    payload = "\n".join(json_dumps(_memory_block_to_payload(block)) for block in blocks)
    if payload:
        payload += "\n"
    return payload.encode("utf-8")


def _hydrate_memory_blocks(data: bytes) -> list[MemoryBlock]:
    lines = [line.strip() for line in data.decode("utf-8").splitlines() if line.strip()]
    result: list[MemoryBlock] = []
    for line in lines:
        payload = json.loads(line)
        if not isinstance(payload, dict):
            raise InvalidArgumentError(
                "bundle memory_block row must decode to an object"
            )
        result.append(memory_block_from_dict(payload))
    return result


def _serialize_ontologies(ontologies) -> bytes:
    from sophiagraph.storage.graph_helpers import ontology_to_dict

    payload = "\n".join(json_dumps(ontology_to_dict(o)) for o in ontologies)
    if payload:
        payload += "\n"
    return payload.encode("utf-8")


def _hydrate_ontologies(data: bytes):
    from sophiagraph.storage.graph_helpers import ontology_from_dict

    lines = [line.strip() for line in data.decode("utf-8").splitlines() if line.strip()]
    result = []
    for line in lines:
        payload = json.loads(line)
        if not isinstance(payload, dict):
            raise InvalidArgumentError("bundle ontology row must decode to an object")
        result.append(ontology_from_dict(payload))
    return result


def _serialize_active_embedding_model_sets(
    model_sets: list[ActiveEmbeddingModelSet],
) -> bytes:
    payload = "\n".join(json_dumps(model_set.to_dict()) for model_set in model_sets)
    if payload:
        payload += "\n"
    return payload.encode("utf-8")


def _hydrate_active_embedding_model_sets(data: bytes) -> list[ActiveEmbeddingModelSet]:
    lines = [line.strip() for line in data.decode("utf-8").splitlines() if line.strip()]
    result: list[ActiveEmbeddingModelSet] = []
    for line in lines:
        payload = json.loads(line)
        if not isinstance(payload, dict):
            raise InvalidArgumentError(
                "bundle active_embedding_model_set row must decode to an object"
            )
        result.append(ActiveEmbeddingModelSet.from_dict(payload))
    return result


def _serialize_retention_snapshots(snapshots: list[RetentionSnapshot]) -> bytes:
    payload = "\n".join(json_dumps(snapshot.to_dict()) for snapshot in snapshots)
    if payload:
        payload += "\n"
    return payload.encode("utf-8")


def _hydrate_retention_snapshots(data: bytes) -> list[RetentionSnapshot]:
    lines = [line.strip() for line in data.decode("utf-8").splitlines() if line.strip()]
    result: list[RetentionSnapshot] = []
    for line in lines:
        payload = json.loads(line)
        if not isinstance(payload, dict):
            raise InvalidArgumentError(
                "bundle retention_snapshot row must decode to an object"
            )
        result.append(RetentionSnapshot.from_dict(payload))
    return result


def _serialize_provenance_traces(traces: list[TurnProvenanceTrace]) -> bytes:
    payload = "\n".join(json_dumps(trace.to_dict()) for trace in traces)
    if payload:
        payload += "\n"
    return payload.encode("utf-8")


def _hydrate_provenance_traces(data: bytes) -> list[TurnProvenanceTrace]:
    lines = [line.strip() for line in data.decode("utf-8").splitlines() if line.strip()]
    result: list[TurnProvenanceTrace] = []
    for line in lines:
        payload = json.loads(line)
        if not isinstance(payload, dict):
            raise InvalidArgumentError("bundle provenance row must decode to an object")
        result.append(TurnProvenanceTrace.from_dict(payload))
    return result


def write_bundle_snapshot(snapshot: MemoryBundleSnapshot, out_path: str | Path) -> Path:
    out = Path(out_path).expanduser().resolve(strict=False)
    out.parent.mkdir(parents=True, exist_ok=True)
    files: dict[str, bytes] = {"records.jsonl": _serialize_rows(snapshot.records)}
    if snapshot.candidates:
        files["candidates.jsonl"] = _serialize_rows(snapshot.candidates)
    if snapshot.relations:
        files["relations.jsonl"] = _serialize_rows(snapshot.relations)
    if snapshot.tier_transitions:
        files["tier_transitions.jsonl"] = _serialize_rows(snapshot.tier_transitions)
    if snapshot.provenance_traces:
        files["provenance.jsonl"] = _serialize_provenance_traces(
            snapshot.provenance_traces
        )
    if snapshot.memory_blocks:
        files["memory_blocks.jsonl"] = _serialize_memory_blocks(snapshot.memory_blocks)
    if snapshot.ontologies:
        files["ontologies.jsonl"] = _serialize_ontologies(snapshot.ontologies)
    if snapshot.active_embedding_model_sets:
        files["embedding_lifecycle.jsonl"] = _serialize_active_embedding_model_sets(
            snapshot.active_embedding_model_sets
        )
    if snapshot.retention_snapshots:
        files["retention_snapshots.jsonl"] = _serialize_retention_snapshots(
            snapshot.retention_snapshots
        )
    manifest = build_manifest(snapshot=snapshot, files=files)
    manifest_bytes = json_dumps(manifest, indent=2).encode("utf-8")
    with tarfile.open(out, "w:gz") as archive:
        for name, payload in {**files, _MANIFEST_NAME: manifest_bytes}.items():
            info = tarfile.TarInfo(name=f"{_BUNDLE_ROOT}/{name}")
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))
    return out


def read_bundle_snapshot(bundle_path: str | Path) -> MemoryBundleSnapshot:
    path = Path(bundle_path).expanduser().resolve(strict=False)
    with tarfile.open(path, "r:gz") as archive:
        members = {
            Path(member.name).name: archive.extractfile(member).read()
            for member in archive.getmembers()
            if member.isfile() and Path(member.name).name
        }
    if _MANIFEST_NAME not in members:
        raise InvalidArgumentError("bundle is missing manifest.json")
    manifest = json.loads(members[_MANIFEST_NAME].decode("utf-8"))
    if not isinstance(manifest, dict):
        raise InvalidArgumentError("bundle manifest must be an object")
    if str(manifest.get("bundle_version", "")) != MEMORY_BUNDLE_VERSION:
        raise InvalidArgumentError("unsupported bundle_version")
    if str(manifest.get("memory_contract_version", "")) != MEMORY_CONTRACT_VERSION:
        raise InvalidArgumentError("unsupported memory_contract_version")
    file_meta = manifest.get("files", {})
    if not isinstance(file_meta, dict):
        raise InvalidArgumentError("manifest files metadata must be an object")
    for name, meta in file_meta.items():
        if name not in members:
            raise InvalidArgumentError(f"bundle is missing {name}")
        if not isinstance(meta, dict):
            raise InvalidArgumentError(f"manifest entry for {name} must be an object")
        expected_sha = str(meta.get("sha256", ""))
        if expected_sha != _sha256_bytes(members[name]):
            raise InvalidArgumentError(f"checksum mismatch for {name}")
    return MemoryBundleSnapshot(
        manifest=manifest,
        records=_hydrate_jsonl(members.get("records.jsonl", b""), record_from_dict),
        candidates=_hydrate_jsonl(
            members.get("candidates.jsonl", b""), candidate_from_dict
        ),
        relations=_hydrate_jsonl(
            members.get("relations.jsonl", b""), relation_from_dict
        ),
        tier_transitions=_hydrate_jsonl(
            members.get("tier_transitions.jsonl", b""), tier_transition_from_dict
        ),
        provenance_traces=_hydrate_provenance_traces(
            members.get("provenance.jsonl", b"")
        ),
        memory_blocks=_hydrate_memory_blocks(members.get("memory_blocks.jsonl", b"")),
        ontologies=_hydrate_ontologies(members.get("ontologies.jsonl", b"")),
        active_embedding_model_sets=_hydrate_active_embedding_model_sets(
            members.get("embedding_lifecycle.jsonl", b"")
        ),
        retention_snapshots=_hydrate_retention_snapshots(
            members.get("retention_snapshots.jsonl", b"")
        ),
    )


__all__ = [
    "MEMORY_BUNDLE_VERSION",
    "build_manifest",
    "read_bundle_snapshot",
    "write_bundle_snapshot",
]
