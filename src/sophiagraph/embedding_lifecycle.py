"""Pure embedding lifecycle helpers over the public SophiaGraph store protocol."""

from __future__ import annotations

from typing import Protocol

from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.models import (
    ActiveEmbeddingModelSet,
    EmbeddingStalenessReason,
    MemoryNamespace,
    ReembedBatch,
    ReembedCursor,
    ReembedPlan,
    StaleEmbeddingFinding,
    VectorSpaceModelDescriptor,
    namespace_key,
)
from sophiagraph.query import EmbeddingListOptions


class _EmbeddingLifecycleStore(Protocol):
    def get_record(self, record_id: str): ...

    def list_embeddings(self, options: EmbeddingListOptions): ...

    def list_orphan_external_vector_ids(
        self,
        *,
        namespace: MemoryNamespace,
        since: str | None = None,
    ) -> list[tuple[str, str]]: ...


def _reasons_for_embedding(
    embedding,
    record,
    *,
    active_models: ActiveEmbeddingModelSet,
) -> tuple[EmbeddingStalenessReason, ...]:
    reasons: list[EmbeddingStalenessReason] = []
    if record is not None and record.updated_at > embedding.updated_at:
        reasons.append("RECORD_UPDATED_AFTER_EMBEDDING")
    provider_allowed = {
        descriptor.provider for descriptor in active_models.active_models
    }
    same_provider = [
        descriptor
        for descriptor in active_models.active_models
        if descriptor.provider == embedding.provider
    ]
    exact_model = [
        descriptor
        for descriptor in same_provider
        if descriptor.model == embedding.model
    ]
    if embedding.provider not in provider_allowed:
        reasons.append("PROVIDER_NOT_IN_ACTIVE_SET")
    elif not exact_model:
        reasons.append("MODEL_NOT_IN_ACTIVE_SET")
    elif all(descriptor.dimension != embedding.dimension for descriptor in exact_model):
        reasons.append("DIMENSION_MISMATCH")
    return tuple(reasons)


def detect_stale_embeddings(
    store: _EmbeddingLifecycleStore,
    *,
    namespace: MemoryNamespace,
    vector_space: str,
    active_models: ActiveEmbeddingModelSet,
) -> list[StaleEmbeddingFinding]:
    """Return deterministic stale-embedding findings for one namespace/vector space."""

    if active_models.namespace != namespace:
        raise InvalidArgumentError("active_models.namespace must match namespace")
    if active_models.vector_space != vector_space:
        raise InvalidArgumentError("active_models.vector_space must match vector_space")
    findings: list[StaleEmbeddingFinding] = []
    embeddings = store.list_embeddings(
        EmbeddingListOptions(
            namespaces=[namespace],
            vector_space=vector_space,
            include_vectors=False,
        )
    )
    embeddings.sort(key=lambda embedding: (embedding.record_id, embedding.vector_space))
    for embedding in embeddings:
        record = store.get_record(embedding.record_id)
        reasons = _reasons_for_embedding(
            embedding,
            record,
            active_models=active_models,
        )
        if reasons:
            findings.append(
                StaleEmbeddingFinding.from_embedding(
                    embedding,
                    reasons=reasons,
                    record_updated_at=record.updated_at if record is not None else None,
                )
            )
    return findings


def build_reembed_plan(
    store: _EmbeddingLifecycleStore,
    *,
    namespace: MemoryNamespace,
    vector_space: str,
    target_model: VectorSpaceModelDescriptor,
    batch_size: int,
    active_models: ActiveEmbeddingModelSet,
    since_cursor: ReembedCursor | None = None,
) -> ReembedPlan:
    """Build a deterministic, cursor-resumable re-embed plan."""

    if batch_size < 1:
        raise InvalidArgumentError("batch_size must be >= 1")
    if since_cursor is not None:
        if since_cursor.namespace != namespace:
            raise InvalidArgumentError("since_cursor.namespace must match namespace")
        if since_cursor.vector_space != vector_space:
            raise InvalidArgumentError(
                "since_cursor.vector_space must match vector_space"
            )
    findings = detect_stale_embeddings(
        store,
        namespace=namespace,
        vector_space=vector_space,
        active_models=active_models,
    )
    if since_cursor is not None:
        findings = [
            finding
            for finding in findings
            if (finding.record_id, finding.vector_space)
            > (since_cursor.last_record_id, since_cursor.vector_space)
        ]
    findings.sort(key=lambda finding: (finding.record_id, finding.vector_space))
    batches: list[ReembedBatch] = []
    for batch_index, offset in enumerate(range(0, len(findings), batch_size)):
        items = tuple(findings[offset : offset + batch_size])
        cursor = ReembedCursor(
            namespace=namespace,
            vector_space=vector_space,
            last_record_id=items[-1].record_id,
        )
        batches.append(
            ReembedBatch(
                batch_index=batch_index,
                target_model=target_model,
                items=items,
                cursor=cursor,
            )
        )
    return ReembedPlan(
        namespace=namespace,
        vector_space=vector_space,
        target_model=target_model,
        stale_findings=tuple(findings),
        batches=tuple(batches),
        resumed_from=since_cursor,
    )


def list_orphan_external_vector_ids(
    store: _EmbeddingLifecycleStore,
    *,
    namespace: MemoryNamespace,
    since: str | None = None,
) -> list[tuple[str, str]]:
    """Return namespace-scoped orphan external vector IDs from the store."""

    return store.list_orphan_external_vector_ids(namespace=namespace, since=since)


__all__ = [
    "build_reembed_plan",
    "detect_stale_embeddings",
    "list_orphan_external_vector_ids",
    "namespace_key",
]
