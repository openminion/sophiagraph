from __future__ import annotations

from pathlib import Path

import pytest

from sophiagraph import (
    ActiveEmbeddingModelSet,
    MemoryEmbedding,
    MemoryNamespace,
    MemoryRecord,
    ReembedCursor,
    ReembedPlan,
    SophiaGraphMemoryStore,
    SophiaGraphSqliteStore,
    VectorSpaceModelDescriptor,
    build_reembed_plan,
    detect_stale_embeddings,
    list_orphan_external_vector_ids,
)
from sophiagraph.contracts.errors import InvalidArgumentError


def _ns(agent_id: str = "alpha") -> MemoryNamespace:
    return MemoryNamespace(tenant_id="tenant", agent_id=agent_id, graph_id="main")


def _record(
    record_id: str,
    *,
    namespace: MemoryNamespace | None = None,
    updated_at: str = "2026-06-06T00:00:00+00:00",
) -> MemoryRecord:
    active_namespace = namespace or _ns()
    return MemoryRecord(
        id=record_id,
        scope=f"agent:{active_namespace.agent_id or 'alpha'}",
        type="fact",
        key=record_id,
        title=record_id,
        content={"text": record_id},
        created_at="2026-06-05T00:00:00+00:00",
        updated_at=updated_at,
        namespace=active_namespace,
        meta={},
    )


def _embedding(
    record_id: str,
    *,
    namespace: MemoryNamespace | None = None,
    vector_space: str = "semantic",
    provider: str = "provider-a",
    model: str = "model-v1",
    dimension: int = 3,
    updated_at: str = "2026-06-05T00:00:00+00:00",
    external_vector_id: str | None = None,
) -> MemoryEmbedding:
    return MemoryEmbedding(
        record_id=record_id,
        vector_space=vector_space,
        dimension=dimension,
        provider=provider,
        model=model,
        namespace=namespace or _ns(),
        created_at="2026-06-05T00:00:00+00:00",
        updated_at=updated_at,
        vector=[float(index + 1) for index in range(dimension)],
        external_vector_id=external_vector_id,
        metadata={"fixture": True},
    )


def _active_set(
    *,
    namespace: MemoryNamespace | None = None,
    vector_space: str = "semantic",
    provider: str = "provider-a",
    model: str = "model-v2",
    dimension: int = 4,
    updated_at: str = "2026-06-06T00:00:00+00:00",
) -> ActiveEmbeddingModelSet:
    return ActiveEmbeddingModelSet(
        namespace=namespace or _ns(),
        vector_space=vector_space,
        active_models=(
            VectorSpaceModelDescriptor(
                provider=provider,
                model=model,
                dimension=dimension,
            ),
        ),
        updated_at=updated_at,
    )


@pytest.fixture(params=["memory", "sqlite"])
def store(request, tmp_path):
    if request.param == "memory":
        return SophiaGraphMemoryStore()
    return SophiaGraphSqliteStore(tmp_path / "sophiagraph.sqlite3")


def test_embedding_lifecycle_dtos_validate_and_export_publicly() -> None:
    with pytest.raises(InvalidArgumentError, match="active_models must not be empty"):
        ActiveEmbeddingModelSet(
            namespace=_ns(),
            vector_space="semantic",
            active_models=(),
            updated_at="2026-06-06T00:00:00+00:00",
        )

    with pytest.raises(InvalidArgumentError, match="dimension must be positive"):
        VectorSpaceModelDescriptor(provider="provider-a", model="model-v2", dimension=0)

    descriptor = VectorSpaceModelDescriptor(
        provider="provider-a",
        model="model-v2",
        dimension=4,
    )
    model_set = _active_set()
    cursor = ReembedCursor(
        namespace=_ns(), vector_space="semantic", last_record_id="rec-1"
    )

    assert descriptor.to_dict()["model"] == "model-v2"
    assert model_set.to_dict()["vector_space"] == "semantic"
    assert cursor.encoded.endswith("|semantic|rec-1")

    import sophiagraph

    assert "ActiveEmbeddingModelSet" in sophiagraph.__all__
    assert "detect_stale_embeddings" in sophiagraph.__all__
    assert "build_reembed_plan" in sophiagraph.__all__


def test_detect_stale_embeddings_covers_all_structural_reasons_and_namespace_isolation(
    store,
) -> None:
    alpha = _ns("alpha")
    beta = _ns("beta")
    for record in (
        _record("rec-dim", namespace=alpha, updated_at="2026-06-05T00:00:00+00:00"),
        _record("rec-model", namespace=alpha, updated_at="2026-06-05T00:00:00+00:00"),
        _record(
            "rec-provider", namespace=alpha, updated_at="2026-06-05T00:00:00+00:00"
        ),
        _record("rec-updated", namespace=alpha, updated_at="2026-06-06T00:00:00+00:00"),
        _record("rec-beta", namespace=beta, updated_at="2026-06-06T00:00:00+00:00"),
    ):
        store.put_record(record)

    store.put_embedding(
        _embedding(
            "rec-updated",
            namespace=alpha,
            provider="provider-a",
            model="model-v2",
            dimension=4,
            updated_at="2026-06-05T00:00:00+00:00",
        )
    )
    store.put_embedding(
        _embedding(
            "rec-provider",
            namespace=alpha,
            provider="provider-b",
            model="model-v2",
            dimension=4,
        )
    )
    store.put_embedding(
        _embedding(
            "rec-model",
            namespace=alpha,
            provider="provider-a",
            model="model-v1",
            dimension=4,
        )
    )
    store.put_embedding(
        _embedding(
            "rec-dim",
            namespace=alpha,
            provider="provider-a",
            model="model-v2",
            dimension=3,
        )
    )
    store.put_embedding(
        _embedding(
            "rec-beta",
            namespace=beta,
            provider="provider-a",
            model="model-v1",
            dimension=4,
        )
    )

    findings = detect_stale_embeddings(
        store,
        namespace=alpha,
        vector_space="semantic",
        active_models=_active_set(namespace=alpha),
    )

    assert [(finding.record_id, finding.reasons) for finding in findings] == [
        ("rec-dim", ("DIMENSION_MISMATCH",)),
        ("rec-model", ("MODEL_NOT_IN_ACTIVE_SET",)),
        ("rec-provider", ("PROVIDER_NOT_IN_ACTIVE_SET",)),
        ("rec-updated", ("RECORD_UPDATED_AFTER_EMBEDDING",)),
    ]


def test_reembed_plan_is_deterministic_resumable_and_serializable(store) -> None:
    namespace = _ns()
    for record_id in ("rec-1", "rec-2", "rec-3"):
        store.put_record(_record(record_id, namespace=namespace))
        store.put_embedding(
            _embedding(
                record_id,
                namespace=namespace,
                provider="provider-a",
                model="model-v1",
                dimension=4,
            )
        )
    active_models = _active_set(namespace=namespace)
    target_model = active_models.active_models[0]

    plan = build_reembed_plan(
        store,
        namespace=namespace,
        vector_space="semantic",
        target_model=target_model,
        batch_size=2,
        active_models=active_models,
    )

    assert [finding.record_id for finding in plan.stale_findings] == [
        "rec-1",
        "rec-2",
        "rec-3",
    ]
    assert [len(batch.items) for batch in plan.batches] == [2, 1]
    assert plan.batches[0].cursor is not None
    resumed = build_reembed_plan(
        store,
        namespace=namespace,
        vector_space="semantic",
        target_model=target_model,
        batch_size=2,
        active_models=active_models,
        since_cursor=plan.batches[0].cursor,
    )
    assert [finding.record_id for finding in resumed.stale_findings] == ["rec-3"]

    round_trip = ReembedPlan.from_dict(plan.to_dict())
    assert round_trip.total_findings == 3
    assert [batch.cursor.encoded for batch in round_trip.batches if batch.cursor] == [
        batch.cursor.encoded for batch in plan.batches if batch.cursor
    ]


def test_active_model_set_storage_round_trips_and_emits_changefeed(store) -> None:
    namespace = _ns()
    model_set = _active_set(namespace=namespace)

    key = store.put_active_model_set(model_set)

    assert key.endswith(":semantic")
    assert (
        store.get_active_model_set(namespace=namespace, vector_space="semantic")
        == model_set
    )
    assert store.list_active_model_sets(namespaces=[namespace]) == [model_set]
    changes = [
        change
        for change in store.list_changes()
        if change.object_type == "active_embedding_model_set"
    ]
    assert len(changes) == 1
    assert changes[0].object_id == key


def test_orphan_external_vector_ids_follow_delete_and_reuse(store) -> None:
    namespace = _ns()
    store.put_record(_record("rec-orphan", namespace=namespace))
    store.put_embedding(
        _embedding(
            "rec-orphan",
            namespace=namespace,
            dimension=4,
            external_vector_id="vec-1",
        )
    )

    store.tombstone_record(
        "rec-orphan",
        deleted_at="2026-06-06T01:00:00+00:00",
        reason="cleanup",
    )
    assert store.delete_embedding("rec-orphan", "semantic") is True
    assert list_orphan_external_vector_ids(store, namespace=namespace) == [
        ("vec-1", "2026-06-05T00:00:00+00:00")
    ]

    store.put_embedding(
        _embedding(
            "rec-orphan",
            namespace=namespace,
            dimension=4,
            external_vector_id="vec-1",
            updated_at="2026-06-06T02:00:00+00:00",
        )
    )
    assert list_orphan_external_vector_ids(store, namespace=namespace) == []


def test_embedding_lifecycle_source_files_stay_provider_free() -> None:
    forbidden = {
        "openai",
        "anthropic",
        "voyageai",
        "cohere",
        "llm_complete",
        "claude",
        "embed_call",
        "auto_reembed",
        "generate_embedding",
    }
    root = Path(__file__).resolve().parents[1] / "src" / "sophiagraph"
    for relative_path in ("embedding_lifecycle.py", "models/embedding_lifecycle.py"):
        text = (root / relative_path).read_text(encoding="utf-8").lower()
        leaked = [token for token in forbidden if token in text]
        assert not leaked, (
            f"{relative_path} contains forbidden provider tokens: {leaked}"
        )
