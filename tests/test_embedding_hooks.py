from __future__ import annotations

from pathlib import Path
import tomllib

import pytest

from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.models import (
    MemoryEmbedding,
    MemoryNamespace,
    memory_embedding_from_dict,
)
from sophiagraph.query import EmbeddingListOptions
from sophiagraph.storage import SophiaGraphMemoryStore, SophiaGraphSqliteStore
from sophiagraph.storage.sqlite.schema import SCHEMA_VERSION


def _namespace(agent_id: str = "agent") -> MemoryNamespace:
    return MemoryNamespace(tenant_id="tenant", agent_id=agent_id, graph_id="main")


def _embedding(
    record_id: str = "rec-1",
    *,
    vector_space: str = "openai:text-embedding-3-small",
    namespace: MemoryNamespace | None = None,
    dimension: int = 3,
    provider: str = "caller-supplied",
    model: str = "text-embedding-3-small",
    vector: list[float] | None = None,
    external_vector_id: str | None = None,
    updated_at: str = "2026-05-25T00:00:00+00:00",
) -> MemoryEmbedding:
    return MemoryEmbedding(
        record_id=record_id,
        vector_space=vector_space,
        dimension=dimension,
        provider=provider,
        model=model,
        namespace=namespace or _namespace(),
        created_at="2026-05-25T00:00:00+00:00",
        updated_at=updated_at,
        vector=vector if vector is not None else [0.1, 0.2, 0.3],
        external_vector_id=external_vector_id,
        metadata={"source": "test-fixture"},
    )


@pytest.fixture(params=["memory", "sqlite"])
def store(request, tmp_path):
    if request.param == "memory":
        return SophiaGraphMemoryStore()
    return SophiaGraphSqliteStore(tmp_path / "sophiagraph.sqlite3")


def test_embedding_dto_requires_explicit_metadata_and_consistent_dimension() -> None:
    with pytest.raises(InvalidArgumentError, match="provider is required"):
        _embedding(provider="")

    with pytest.raises(InvalidArgumentError, match="model is required"):
        _embedding(model="")

    with pytest.raises(InvalidArgumentError, match="dimension must be positive"):
        _embedding(dimension=0, vector=[])

    with pytest.raises(InvalidArgumentError, match="vector length"):
        _embedding(dimension=4, vector=[0.1, 0.2, 0.3])

    with pytest.raises(InvalidArgumentError, match="vector or external_vector_id"):
        MemoryEmbedding(
            record_id="rec-1",
            vector_space="space",
            dimension=3,
            provider="provider",
            model="model",
            namespace=_namespace(),
            created_at="2026-05-25T00:00:00+00:00",
            updated_at="2026-05-25T00:00:00+00:00",
        )

    with pytest.raises(TypeError, match="namespace"):
        _embedding(namespace="agent")  # type: ignore[arg-type]


def test_embedding_from_dict_rejects_malformed_metadata_and_missing_provider() -> None:
    with pytest.raises(InvalidArgumentError, match="provider is required"):
        memory_embedding_from_dict(
            {
                "record_id": "rec-1",
                "vector_space": "space",
                "dimension": 3,
                "provider": None,
                "model": "model",
                "namespace": _namespace().as_dict(),
                "created_at": "2026-05-25T00:00:00+00:00",
                "updated_at": "2026-05-25T00:00:00+00:00",
                "vector": [0.1, 0.2, 0.3],
            }
        )

    with pytest.raises(InvalidArgumentError, match="metadata must be a dict"):
        memory_embedding_from_dict(
            {
                "record_id": "rec-1",
                "vector_space": "space",
                "dimension": 3,
                "provider": "provider",
                "model": "model",
                "namespace": _namespace().as_dict(),
                "created_at": "2026-05-25T00:00:00+00:00",
                "updated_at": "2026-05-25T00:00:00+00:00",
                "vector": [0.1, 0.2, 0.3],
                "metadata": ["bad"],
            }
        )


def test_memory_and_sqlite_store_embedding_roundtrip_and_namespace_filters(
    store,
) -> None:
    alpha = _namespace("alpha")
    beta = _namespace("beta")
    store.put_embedding(_embedding("rec-alpha", namespace=alpha))
    store.put_embedding(_embedding("rec-beta", namespace=beta))

    fetched = store.get_embedding("rec-alpha", "openai:text-embedding-3-small")
    assert fetched is not None
    assert fetched.vector == [0.1, 0.2, 0.3]
    assert fetched.namespace == alpha

    metadata_only = store.get_embedding(
        "rec-alpha",
        "openai:text-embedding-3-small",
        include_vector=False,
    )
    assert metadata_only is not None
    assert metadata_only.vector is None
    assert metadata_only.external_vector_id is None
    assert metadata_only.metadata["vector_omitted"] is True
    assert metadata_only.provider == "caller-supplied"

    filtered = store.list_embeddings(
        EmbeddingListOptions(
            namespaces=[MemoryNamespace(agent_id="alpha")],
            include_vectors=False,
        )
    )
    assert [embedding.record_id for embedding in filtered] == ["rec-alpha"]
    assert filtered[0].vector is None

    assert store.delete_embedding("rec-alpha", "openai:text-embedding-3-small") is True
    assert store.get_embedding("rec-alpha", "openai:text-embedding-3-small") is None
    assert store.delete_embedding("rec-alpha", "openai:text-embedding-3-small") is False


def test_embedding_storage_rejects_dimension_changes_for_existing_key(store) -> None:
    store.put_embedding(_embedding("rec-dim", dimension=3, vector=[0.1, 0.2, 0.3]))

    with pytest.raises(InvalidArgumentError, match="dimension cannot change"):
        store.put_embedding(
            _embedding(
                "rec-dim",
                dimension=2,
                vector=[0.1, 0.2],
                updated_at="2026-05-25T00:01:00+00:00",
            )
        )

    updated = _embedding(
        "rec-dim",
        dimension=3,
        vector=[0.4, 0.5, 0.6],
        updated_at="2026-05-25T00:02:00+00:00",
    )
    store.put_embedding(updated)
    assert store.get_embedding("rec-dim", "openai:text-embedding-3-small") == updated


def test_sqlite_embedding_table_persists_replay_safe_updates(tmp_path) -> None:
    db_path = tmp_path / "sophiagraph.sqlite3"
    store = SophiaGraphSqliteStore(db_path)
    first = _embedding("rec-sqlite", external_vector_id="vec-1")
    second = _embedding(
        "rec-sqlite",
        external_vector_id="vec-2",
        updated_at="2026-05-25T00:05:00+00:00",
    )
    store.put_embedding(first)
    store.put_embedding(second)

    reopened = SophiaGraphSqliteStore(db_path)

    fetched = reopened.get_embedding("rec-sqlite", "openai:text-embedding-3-small")
    assert fetched == second
    assert [
        embedding.external_vector_id
        for embedding in reopened.list_embeddings(
            EmbeddingListOptions(record_id="rec-sqlite")
        )
    ] == ["vec-2"]

    with reopened._connect() as conn:
        schema_version = conn.execute("PRAGMA user_version").fetchone()[0]
        row_count = conn.execute(
            "SELECT COUNT(*) FROM sophiagraph_embeddings"
        ).fetchone()[0]
    assert schema_version == SCHEMA_VERSION
    assert row_count == 1


def test_embedding_hooks_do_not_add_provider_dependencies() -> None:
    import sophiagraph

    pyproject = tomllib.loads(
        (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text()
    )

    assert pyproject["project"]["dependencies"] == ["graphfakos>=0.0.1,<1"]
    assert not any(
        dependency.startswith(("openai", "cohere", "sentence-transformers"))
        for dependency in pyproject["project"]["dependencies"]
    )
    assert "MemoryEmbedding" in sophiagraph.__all__
    assert "EmbeddingListOptions" in sophiagraph.__all__
