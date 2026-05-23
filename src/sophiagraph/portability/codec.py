"""Durable-knowledge bundle codec."""

from __future__ import annotations

from dataclasses import asdict
from hashlib import sha256
import io
import json
from pathlib import Path
import tarfile
from typing import Any

from sophiagraph.contracts.provenance import TurnProvenanceTrace
from sophiagraph.contracts.types import MEMORY_CONTRACT_VERSION
from sophiagraph.models import (
    ArtifactRef,
    CandidateReview,
    MemoryCandidate,
    MemoryNamespace,
    MemoryRecord,
    MemoryRelation,
    MemoryTierTransition,
    _as_candidate_status,
    _as_memory_relation_type,
    _as_memory_source,
    _as_memory_tier,
    _as_memory_tier_transition_reason,
    _as_memory_type,
)

from sophiagraph.portability.models import MemoryBundleSnapshot
from sophiagraph.contracts.errors import InvalidArgumentError


MEMORY_BUNDLE_VERSION = "memory_bundle.v1"
_BUNDLE_ROOT = "memory-bundle"
_MANIFEST_NAME = "manifest.json"


def _json_dumps(value: Any, *, indent: int | None = None) -> str:
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, indent=indent, default=str
    )


def _sha256_bytes(data: bytes) -> str:
    return sha256(data).hexdigest()


def _artifact_refs_from_payload(raw_refs: Any) -> list[ArtifactRef]:
    refs: list[ArtifactRef] = []
    if not isinstance(raw_refs, list):
        return refs
    for item in raw_refs:
        if not isinstance(item, dict):
            continue
        refs.append(
            ArtifactRef(
                ref=str(item.get("ref", "")),
                mime=str(item.get("mime", "application/octet-stream")),
                sha256=str(item.get("sha256", "")),
                size_bytes=max(0, int(item.get("size_bytes", 0) or 0)),
                label=str(item.get("label")) if item.get("label") is not None else None,
            )
        )
    return refs


def _review_from_payload(raw_review: Any) -> CandidateReview | None:
    if not isinstance(raw_review, dict):
        return None
    return CandidateReview(
        reviewer=str(raw_review.get("reviewer", "")),
        decided_at=str(raw_review.get("decided_at", "")),
        note=str(raw_review.get("note"))
        if raw_review.get("note") is not None
        else None,
    )


def _record_from_dict(data: dict[str, Any]) -> MemoryRecord:
    raw_namespace = data.get("namespace")
    if isinstance(raw_namespace, MemoryNamespace):
        namespace = raw_namespace
    elif isinstance(raw_namespace, dict) and raw_namespace:
        namespace = MemoryNamespace.from_dict(raw_namespace)
    else:
        namespace = MemoryNamespace.from_scope(str(data.get("scope", "")))
    return MemoryRecord(
        id=str(data.get("id", "")),
        scope=str(data.get("scope", "")),
        type=_as_memory_type(str(data.get("type", ""))),
        content=data.get("content", ""),
        created_at=str(data.get("created_at", "")),
        updated_at=str(data.get("updated_at", "")),
        key=str(data.get("key")) if data.get("key") is not None else None,
        title=str(data.get("title")) if data.get("title") is not None else None,
        tags=[str(item) for item in data.get("tags", [])]
        if isinstance(data.get("tags"), list)
        else [],
        entities=[str(item) for item in data.get("entities", [])]
        if isinstance(data.get("entities"), list)
        else [],
        source=_as_memory_source(str(data.get("source", "agent_inferred"))),
        confidence=float(data.get("confidence", 0.5) or 0.5),
        evidence_refs=_artifact_refs_from_payload(data.get("evidence_refs")),
        expires_at=str(data.get("expires_at"))
        if data.get("expires_at") is not None
        else None,
        visibility=str(data.get("visibility"))
        if data.get("visibility") is not None
        else None,
        meta=dict(data.get("meta", {})) if isinstance(data.get("meta"), dict) else {},
        last_hit_at=str(data.get("last_hit_at"))
        if data.get("last_hit_at") is not None
        else None,
        event_time=str(data.get("event_time"))
        if data.get("event_time") is not None
        else str(data.get("created_at", "")),
        valid_to=str(data.get("valid_to"))
        if data.get("valid_to") is not None
        else None,
        supersedes_id=str(data.get("supersedes_id"))
        if data.get("supersedes_id") is not None
        else None,
        superseded_by_id=str(data.get("superseded_by_id"))
        if data.get("superseded_by_id") is not None
        else None,
        supersession_reason=str(data.get("supersession_reason"))
        if data.get("supersession_reason") is not None
        else None,
        is_deleted=bool(data.get("is_deleted", False)),
        namespace=namespace,
        # Preserve optional deletion audit fields across bundle round-trips.
        deleted_at=str(data.get("deleted_at"))
        if data.get("deleted_at") is not None
        else None,
        deleted_reason=str(data.get("deleted_reason"))
        if data.get("deleted_reason") is not None
        else None,
        tier=_as_memory_tier(str(data.get("tier", "working"))),
        access_count=max(0, int(data.get("access_count", 0) or 0)),
    )


def _candidate_from_dict(data: dict[str, Any]) -> MemoryCandidate:
    return MemoryCandidate(
        candidate_id=str(data.get("candidate_id", "")),
        session_id=str(data.get("session_id", "")),
        proposed_scope=str(data.get("proposed_scope", "")),
        type=_as_memory_type(str(data.get("type", ""))),
        content=data.get("content", ""),
        tags=[str(item) for item in data.get("tags", [])]
        if isinstance(data.get("tags"), list)
        else [],
        entities=[str(item) for item in data.get("entities", [])]
        if isinstance(data.get("entities"), list)
        else [],
        source=_as_memory_source(str(data.get("source", "agent_inferred"))),
        confidence=float(data.get("confidence", 0.5) or 0.5),
        evidence_refs=_artifact_refs_from_payload(data.get("evidence_refs")),
        status=_as_candidate_status(str(data.get("status", "proposed"))),
        key=str(data.get("key")) if data.get("key") is not None else None,
        title=str(data.get("title")) if data.get("title") is not None else None,
        review=_review_from_payload(data.get("review")),
        meta=dict(data.get("meta", {})) if isinstance(data.get("meta"), dict) else {},
        created_at=str(data.get("created_at"))
        if data.get("created_at") is not None
        else None,
        updated_at=str(data.get("updated_at"))
        if data.get("updated_at") is not None
        else None,
    )


def _relation_from_dict(data: dict[str, Any]) -> MemoryRelation:
    return MemoryRelation(
        relation_id=str(data.get("relation_id", "")),
        source_record_id=str(data.get("source_record_id", "")),
        target_record_id=str(data.get("target_record_id", "")),
        relation_type=_as_memory_relation_type(
            str(data.get("relation_type", "related_to"))
        ),
        created_at=str(data.get("created_at", "")),
        meta=dict(data.get("meta", {})) if isinstance(data.get("meta"), dict) else {},
    )


def _tier_transition_from_dict(data: dict[str, Any]) -> MemoryTierTransition:
    return MemoryTierTransition(
        transition_id=str(data.get("transition_id", "")),
        record_id=str(data.get("record_id", "")),
        scope=str(data.get("scope", "")),
        record_type=_as_memory_type(str(data.get("record_type", ""))),
        from_tier=_as_memory_tier(str(data.get("from_tier", ""))),
        to_tier=_as_memory_tier(str(data.get("to_tier", ""))),
        transition_reason=_as_memory_tier_transition_reason(
            str(data.get("transition_reason", ""))
        ),
        transition_at=str(data.get("transition_at", "")),
        access_count=max(0, int(data.get("access_count", 0) or 0)),
        meta=dict(data.get("meta", {})) if isinstance(data.get("meta"), dict) else {},
    )


def _serialize_rows(rows: list[Any]) -> bytes:
    payload = "\n".join(_json_dumps(asdict(row)) for row in rows)
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
    }
    manifest["sections"] = {
        "records": True,
        "candidates": bool(snapshot.candidates),
        "relations": bool(snapshot.relations),
        "tier_transitions": bool(snapshot.tier_transitions),
        "provenance_traces": bool(snapshot.provenance_traces),
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


def _serialize_provenance_traces(traces: list[TurnProvenanceTrace]) -> bytes:
    """Serialize provenance traces as JSONL via the contract `to_dict()` helper."""

    payload = "\n".join(_json_dumps(trace.to_dict()) for trace in traces)
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

    files: dict[str, bytes] = {
        "records.jsonl": _serialize_rows(snapshot.records),
    }
    if snapshot.candidates:
        files["candidates.jsonl"] = _serialize_rows(snapshot.candidates)
    if snapshot.relations:
        files["relations.jsonl"] = _serialize_rows(snapshot.relations)
    if snapshot.tier_transitions:
        files["tier_transitions.jsonl"] = _serialize_rows(snapshot.tier_transitions)
    # Write provenance only when the snapshot actually includes traces.
    if snapshot.provenance_traces:
        files["provenance.jsonl"] = _serialize_provenance_traces(
            snapshot.provenance_traces
        )

    manifest = build_manifest(snapshot=snapshot, files=files)
    manifest_bytes = _json_dumps(manifest, indent=2).encode("utf-8")

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

    records = _hydrate_jsonl(members.get("records.jsonl", b""), _record_from_dict)
    candidates = _hydrate_jsonl(
        members.get("candidates.jsonl", b""),
        _candidate_from_dict,
    )
    relations = _hydrate_jsonl(
        members.get("relations.jsonl", b""),
        _relation_from_dict,
    )
    tier_transitions = _hydrate_jsonl(
        members.get("tier_transitions.jsonl", b""),
        _tier_transition_from_dict,
    )
    provenance_traces = _hydrate_provenance_traces(members.get("provenance.jsonl", b""))
    return MemoryBundleSnapshot(
        manifest=manifest,
        records=records,
        candidates=candidates,
        relations=relations,
        tier_transitions=tier_transitions,
        provenance_traces=provenance_traces,
    )


__all__ = [
    "MEMORY_BUNDLE_VERSION",
    "build_manifest",
    "read_bundle_snapshot",
    "write_bundle_snapshot",
]
