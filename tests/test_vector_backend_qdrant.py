from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from uuid import UUID

import pytest

from sophiagraph.models import MemoryNamespace
from sophiagraph.vector_backends import (
    QdrantRetrievalAdapter,
    QdrantVectorBackend,
    VectorPoint,
    VectorQuery,
)


class _Model:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class _Models:
    PointStruct = PointIdsList = FieldCondition = MatchValue = Filter = VectorParams = (
        _Model
    )
    Distance = SimpleNamespace(COSINE="cosine", EUCLID="euclid", DOT="dot")


@dataclass
class _Hit:
    id: str
    score: float
    payload: dict[str, object]


class _Client:
    def __init__(self) -> None:
        self.exists = False
        self._points = {}
        self.deleted = None
        self.query_filter = None

    def collection_exists(self, name: str) -> bool:
        return self.exists

    def create_collection(self, **kwargs) -> None:
        self.exists = True

    def upsert(self, *, collection_name: str, points, **kwargs) -> None:
        for point in points:
            self._points[point.id] = point

    @property
    def points(self):
        return list(self._points.values())

    def search(self, **kwargs):
        self.query_filter = kwargs["query_filter"]
        return [_Hit("point-1", 0.9, {"record_id": "rec-1"})]

    def delete(self, *, collection_name: str, points_selector) -> None:
        self.deleted = points_selector.points
        for point_id in points_selector.points:
            self._points.pop(point_id, None)

    def retrieve(self, *, collection_name: str, ids, with_payload: bool):
        return [self._points[point_id] for point_id in ids if point_id in self._points]

    def scroll(self, **kwargs):
        points = [
            point
            for point in self._points.values()
            if point.payload.get("sophiagraph_kind") == "embedding"
        ]
        return points, None

    def get_collection(self, name: str):
        return {"name": name}


class _LegacyClient(_Client):
    collection_exists = None

    def get_collections(self):
        names = ["memory"] if self.exists else []
        return SimpleNamespace(
            collections=[SimpleNamespace(name=name) for name in names]
        )


def test_qdrant_adapter_upsert_search_delete_and_health() -> None:
    client = _Client()
    backend = QdrantVectorBackend(
        collection_name="memory",
        vector_size=2,
        client=client,
        models=_Models,
        ensure_collection=True,
    )
    namespace = MemoryNamespace(agent_id="agent-1", graph_id="main")
    backend.upsert(
        (
            VectorPoint(
                point_id="point-1",
                vector=(1.0, 0.0),
                vector_space="default",
                namespace=namespace,
                payload={"record_id": "rec-1"},
            ),
        )
    )
    hits = backend.search(
        VectorQuery(
            vector=(1.0, 0.0),
            vector_space="default",
            namespaces=(namespace,),
            payload_filters={"record_id": "rec-1"},
        )
    )
    assert client.points[0].payload["namespace"]["agent_id"] == "agent-1"
    backend.set_projection_watermark(9)
    assert backend.get_projection_watermark() == 9
    assert backend.inventory()[0].object_id == "point-1"
    backend.delete(("point-1",))
    assert hits[0].point_id == "point-1"
    assert client.query_filter is not None
    assert client.deleted is not None
    assert len(client.deleted) == 1
    UUID(client.deleted[0])
    assert backend.healthcheck() is True

    retrieval = QdrantRetrievalAdapter(backend, namespaces=(namespace,))
    assert retrieval.search(
        query_embedding=(1.0, 0.0),
        vector_space="default",
        candidates=(("rec-1", (1.0, 0.0)),),
        limit=1,
        metric="cosine",
    ) == [("rec-1", 0.9)]


def test_qdrant_collection_probe_supports_legacy_client() -> None:
    client = _LegacyClient()
    QdrantVectorBackend(
        collection_name="memory",
        vector_size=2,
        client=client,
        models=_Models,
        ensure_collection=True,
    )
    assert client.exists is True


def test_qdrant_installed_client_projection_contract() -> None:
    qdrant_client = pytest.importorskip(
        "qdrant_client", reason="optional Qdrant compatibility extra is not installed"
    )
    backend = QdrantVectorBackend(
        collection_name="projection-compatibility",
        vector_size=2,
        client=qdrant_client.QdrantClient(":memory:"),
        models=pytest.importorskip("qdrant_client.models"),
        ensure_collection=True,
    )
    point = VectorPoint(
        point_id="point-1",
        vector=(1.0, 0.0),
        vector_space="default",
        namespace=MemoryNamespace(graph_id="main"),
        version_hash="v1",
    )

    backend.upsert((point,))
    backend.set_projection_watermark(5)

    assert backend.get_projection_watermark() == 5
    assert backend.inventory()[0].object_id == "point-1"
    backend.delete((point.point_id,))
    assert backend.inventory() == ()
