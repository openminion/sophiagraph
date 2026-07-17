"""Shared helpers for durable projection state."""

from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import json
from typing import Any

from sophiagraph.models import MemoryEmbedding, MemoryNamespace, ProjectionTarget


def iso_after(value: str, seconds: int) -> str:
    return (datetime.fromisoformat(value) + timedelta(seconds=seconds)).isoformat()


def is_expired(expires_at: str, now: str) -> bool:
    return datetime.fromisoformat(expires_at) <= datetime.fromisoformat(now)


def structural_hash(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def target_matches_namespaces(
    target: ProjectionTarget,
    namespaces: list[MemoryNamespace] | None,
) -> bool:
    if not namespaces:
        return True
    if target.namespace is None:
        return False
    return any(target.namespace.matches(namespace) for namespace in namespaces)


def bounded_error_message(message: str | None) -> str | None:
    if message is None:
        return None
    return str(message)[:512]


def embedding_change_payload(embedding: MemoryEmbedding) -> dict[str, Any]:
    structural = {
        "record_id": embedding.record_id,
        "vector_space": embedding.vector_space,
        "dimension": embedding.dimension,
        "provider": embedding.provider,
        "model": embedding.model,
        "external_vector_id": embedding.external_vector_id,
        "updated_at": embedding.updated_at,
    }
    return {
        **structural,
        "point_id": embedding.external_vector_id or embedding.key,
        "version_hash": structural_hash(structural),
    }


__all__ = [
    "bounded_error_message",
    "embedding_change_payload",
    "is_expired",
    "iso_after",
    "structural_hash",
    "target_matches_namespaces",
]
