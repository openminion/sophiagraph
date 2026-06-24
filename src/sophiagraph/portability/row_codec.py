"""Row hydration and JSON helpers for durable-knowledge portability."""

from __future__ import annotations

import json
from typing import Any

from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.models import (
    ArtifactRef,
    CandidateReview,
    MemoryBlock,
    MemoryCandidate,
    MemoryNamespace,
    MemoryRecord,
    MemoryRelation,
    MemoryTierTransition,
    SophiaGraphChangeEvent,
    coerce_candidate_status,
    coerce_memory_relation_type,
    coerce_memory_source,
    coerce_memory_tier,
    coerce_memory_tier_transition_reason,
    coerce_memory_type,
    default_change_namespace,
)


def json_dumps(value: Any, *, indent: int | None = None) -> str:
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, indent=indent, default=str
    )


_json_dumps = json_dumps


def _required(data: dict[str, Any], field_name: str) -> Any:
    if field_name not in data or data[field_name] is None:
        raise InvalidArgumentError(f"missing required field: {field_name}")
    return data[field_name]


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
    if isinstance(raw_review, CandidateReview):
        return raw_review
    if not isinstance(raw_review, dict):
        return None
    return CandidateReview(
        reviewer=str(raw_review.get("reviewer", "")),
        decided_at=str(raw_review.get("decided_at", "")),
        note=str(raw_review.get("note"))
        if raw_review.get("note") is not None
        else None,
    )


def record_from_dict(data: dict[str, Any]) -> MemoryRecord:
    scope = str(_required(data, "scope"))
    raw_namespace = data.get("namespace")
    if isinstance(raw_namespace, MemoryNamespace):
        namespace = raw_namespace
    elif isinstance(raw_namespace, dict) and raw_namespace:
        namespace = MemoryNamespace.from_dict(raw_namespace)
    else:
        namespace = MemoryNamespace.from_scope(scope)
    return MemoryRecord(
        id=str(_required(data, "id")),
        scope=scope,
        type=coerce_memory_type(str(_required(data, "type"))),
        content=_required(data, "content"),
        created_at=str(_required(data, "created_at")),
        updated_at=str(_required(data, "updated_at")),
        key=str(data.get("key")) if data.get("key") is not None else None,
        title=str(data.get("title")) if data.get("title") is not None else None,
        tags=[str(item) for item in data.get("tags", [])]
        if isinstance(data.get("tags"), list)
        else [],
        entities=[str(item) for item in data.get("entities", [])]
        if isinstance(data.get("entities"), list)
        else [],
        source=coerce_memory_source(str(data.get("source", "agent_inferred"))),
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
        deleted_at=str(data.get("deleted_at"))
        if data.get("deleted_at") is not None
        else None,
        deleted_reason=str(data.get("deleted_reason"))
        if data.get("deleted_reason") is not None
        else None,
        tier=coerce_memory_tier(str(data.get("tier", "working"))),
        access_count=max(0, int(data.get("access_count", 0) or 0)),
        integrity_hash=str(data.get("integrity_hash"))
        if data.get("integrity_hash") is not None
        else None,
    )


def candidate_from_dict(data: dict[str, Any]) -> MemoryCandidate:
    raw_namespace = data.get("namespace")
    namespace = None
    if isinstance(raw_namespace, MemoryNamespace):
        namespace = raw_namespace
    elif isinstance(raw_namespace, dict) and raw_namespace:
        namespace = MemoryNamespace.from_dict(raw_namespace)
    return MemoryCandidate(
        candidate_id=str(_required(data, "candidate_id")),
        session_id=str(_required(data, "session_id")),
        proposed_scope=str(_required(data, "proposed_scope")),
        type=coerce_memory_type(str(_required(data, "type"))),
        content=_required(data, "content"),
        tags=[str(item) for item in data.get("tags", [])]
        if isinstance(data.get("tags"), list)
        else [],
        entities=[str(item) for item in data.get("entities", [])]
        if isinstance(data.get("entities"), list)
        else [],
        source=coerce_memory_source(str(data.get("source", "agent_inferred"))),
        confidence=float(data.get("confidence", 0.5) or 0.5),
        evidence_refs=_artifact_refs_from_payload(data.get("evidence_refs")),
        status=coerce_candidate_status(str(data.get("status", "proposed"))),
        key=str(data.get("key")) if data.get("key") is not None else None,
        title=str(data.get("title")) if data.get("title") is not None else None,
        review=_review_from_payload(data.get("review")),
        meta=dict(data.get("meta", {})) if isinstance(data.get("meta"), dict) else {},
        namespace=namespace,
        claim_key=str(data.get("claim_key"))
        if data.get("claim_key") is not None
        else None,
        polarity=str(data.get("polarity", "asserts")),
        source_class=str(data.get("source_class"))
        if data.get("source_class") is not None
        else None,
        created_at=str(data.get("created_at"))
        if data.get("created_at") is not None
        else None,
        updated_at=str(data.get("updated_at"))
        if data.get("updated_at") is not None
        else None,
    )


def relation_from_dict(data: dict[str, Any]) -> MemoryRelation:
    return MemoryRelation(
        relation_id=str(_required(data, "relation_id")),
        source_record_id=str(_required(data, "source_record_id")),
        target_record_id=str(_required(data, "target_record_id")),
        relation_type=coerce_memory_relation_type(
            str(_required(data, "relation_type"))
        ),
        created_at=str(_required(data, "created_at")),
        meta=dict(data.get("meta", {})) if isinstance(data.get("meta"), dict) else {},
    )


def tier_transition_from_dict(data: dict[str, Any]) -> MemoryTierTransition:
    return MemoryTierTransition(
        transition_id=str(_required(data, "transition_id")),
        record_id=str(_required(data, "record_id")),
        scope=str(_required(data, "scope")),
        record_type=coerce_memory_type(str(_required(data, "record_type"))),
        from_tier=coerce_memory_tier(str(_required(data, "from_tier"))),
        to_tier=coerce_memory_tier(str(_required(data, "to_tier"))),
        transition_reason=coerce_memory_tier_transition_reason(
            str(_required(data, "transition_reason"))
        ),
        transition_at=str(_required(data, "transition_at")),
        access_count=max(0, int(data.get("access_count", 0) or 0)),
        meta=dict(data.get("meta", {})) if isinstance(data.get("meta"), dict) else {},
    )


def change_event_from_dict(data: dict[str, Any]) -> SophiaGraphChangeEvent:
    raw_namespace = data.get("namespace")
    if isinstance(raw_namespace, MemoryNamespace):
        namespace = raw_namespace
    elif isinstance(raw_namespace, dict) and raw_namespace:
        namespace = MemoryNamespace.from_dict(raw_namespace)
    else:
        namespace = default_change_namespace()
    return SophiaGraphChangeEvent(
        event_id=str(_required(data, "event_id")),
        object_type=str(_required(data, "object_type")),  # type: ignore[arg-type]
        object_id=str(_required(data, "object_id")),
        operation=str(_required(data, "operation")),  # type: ignore[arg-type]
        changed_at=str(_required(data, "changed_at")),
        payload=dict(data.get("payload", {}))
        if isinstance(data.get("payload"), dict)
        else {},
        namespace=namespace,
        cursor=int(data["cursor"]) if data.get("cursor") is not None else None,
        idempotency_key=str(data.get("idempotency_key"))
        if data.get("idempotency_key") is not None
        else None,
        source_operation_id=str(data.get("source_operation_id"))
        if data.get("source_operation_id") is not None
        else None,
        schema_identifiers={
            str(key): str(value)
            for key, value in dict(data.get("schema_identifiers", {})).items()
        }
        if isinstance(data.get("schema_identifiers"), dict)
        else {},
    )


def memory_block_from_dict(data: dict[str, Any]) -> MemoryBlock:
    """Hydrate a portable ``MemoryBlock`` row from a dict."""

    payload = dict(data)
    raw_namespace = payload.get("owner_namespace")
    if isinstance(raw_namespace, dict):
        payload["owner_namespace"] = MemoryNamespace.from_dict(raw_namespace)
    return MemoryBlock(**payload)


_record_from_dict = record_from_dict
_candidate_from_dict = candidate_from_dict
_relation_from_dict = relation_from_dict
_tier_transition_from_dict = tier_transition_from_dict


__all__ = [
    "_candidate_from_dict",
    "_json_dumps",
    "_record_from_dict",
    "_relation_from_dict",
    "_tier_transition_from_dict",
    "candidate_from_dict",
    "change_event_from_dict",
    "json_dumps",
    "memory_block_from_dict",
    "record_from_dict",
    "relation_from_dict",
    "tier_transition_from_dict",
]
