"""Optional Qdrant stored-vector backend."""

from __future__ import annotations

import importlib
from typing import Any, Mapping, Sequence
from uuid import NAMESPACE_URL, uuid5

from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.models import MemoryNamespace
from sophiagraph.models.projection import ProjectionInventoryItem
from sophiagraph.vectors import SimilarityMetric

from .types import VectorBackendCapabilities, VectorHit, VectorPoint, VectorQuery


_DISTANCE_NAMES = {
    SimilarityMetric.COSINE: "COSINE",
    SimilarityMetric.L2: "EUCLID",
    SimilarityMetric.DOT: "DOT",
}
_WATERMARK_POINT_ID = "sophiagraph:projection-watermark"


def _provider_point_id(point_id: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"sophiagraph:{point_id}"))


def _load_qdrant() -> tuple[Any, Any]:
    try:
        client_module = importlib.import_module("qdrant_client")
        models_module = importlib.import_module("qdrant_client.models")
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Qdrant support requires `pip install sophiagraph[qdrant]`"
        ) from exc
    return client_module, models_module


class QdrantVectorBackend:
    """Stored-vector adapter using caller-supplied embeddings and Qdrant."""

    def __init__(
        self,
        *,
        collection_name: str,
        vector_size: int,
        metric: SimilarityMetric = SimilarityMetric.COSINE,
        location: str | None = None,
        url: str | None = None,
        api_key: str | None = None,
        client: Any | None = None,
        models: Any | None = None,
        ensure_collection: bool = False,
        wait_for_ack: bool = True,
        write_ordering: str | None = None,
    ) -> None:
        if not collection_name or vector_size <= 0:
            raise InvalidArgumentError(
                "collection_name and positive vector_size required"
            )
        if client is None or models is None:
            client_module, models_module = _load_qdrant()
            client = client or client_module.QdrantClient(
                location=location,
                url=url,
                api_key=api_key,
            )
            models = models or models_module
        self.collection_name = collection_name
        self.vector_size = vector_size
        self.metric = metric
        self._client = client
        self._models = models
        self._wait_for_ack = wait_for_ack
        self._write_ordering = write_ordering
        if ensure_collection:
            self.ensure_collection()

    def capabilities(self) -> VectorBackendCapabilities:
        return VectorBackendCapabilities(
            backend_name="qdrant",
            metrics=tuple(SimilarityMetric),
            namespace_filtering=True,
            payload_filtering=True,
            wait_for_ack=self._wait_for_ack,
            write_ordering=self._write_ordering or "provider_default",
            projection_watermark=True,
            inventory=hasattr(self._client, "scroll"),
        )

    def ensure_collection(self) -> None:
        if self._collection_exists():
            return
        distance = getattr(self._models.Distance, _DISTANCE_NAMES[self.metric])
        self._client.create_collection(
            collection_name=self.collection_name,
            vectors_config=self._models.VectorParams(
                size=self.vector_size,
                distance=distance,
            ),
        )

    def _collection_exists(self) -> bool:
        probe = getattr(self._client, "collection_exists", None)
        if probe is not None:
            return bool(probe(self.collection_name))
        collections = self._client.get_collections().collections
        return any(item.name == self.collection_name for item in collections)

    def upsert(self, points: tuple[VectorPoint, ...]) -> None:
        if any(len(point.vector) != self.vector_size for point in points):
            raise InvalidArgumentError(
                "point vector dimension does not match collection"
            )
        payload = [
            self._models.PointStruct(
                id=_provider_point_id(point.point_id),
                vector=list(point.vector),
                payload={
                    **dict(point.payload),
                    "sophiagraph_point_id": point.point_id,
                    "vector_space": point.vector_space,
                    "namespace": point.namespace.as_dict(),
                    "sophiagraph_kind": "embedding",
                    "sophiagraph_version": point.version_hash,
                },
            )
            for point in points
        ]
        if payload:
            self._upsert_points(payload)

    def search(self, query: VectorQuery) -> tuple[VectorHit, ...]:
        if query.metric is not self.metric:
            raise InvalidArgumentError(
                "query metric must match the Qdrant collection metric"
            )
        query_filter = self._build_filter(query)
        if hasattr(self._client, "query_points"):
            response = self._client.query_points(
                collection_name=self.collection_name,
                query=list(query.vector),
                query_filter=query_filter,
                limit=query.limit,
                with_payload=True,
            )
            results = response.points
        else:
            results = self._client.search(
                collection_name=self.collection_name,
                query_vector=list(query.vector),
                query_filter=query_filter,
                limit=query.limit,
                with_payload=True,
            )
        return tuple(
            VectorHit(
                point_id=str(
                    (item.payload or {}).get("sophiagraph_point_id") or item.id
                ),
                score=float(item.score),
                payload=dict(item.payload or {}),
            )
            for item in results
        )

    def delete(self, point_ids: tuple[str, ...]) -> None:
        if not point_ids:
            return
        selector = self._models.PointIdsList(
            points=[_provider_point_id(point_id) for point_id in point_ids]
        )
        self._client.delete(
            collection_name=self.collection_name,
            points_selector=selector,
        )

    def healthcheck(self) -> bool:
        self._client.get_collection(self.collection_name)
        return True

    def _build_filter(self, query: VectorQuery) -> Any | None:
        conditions = [
            self._models.FieldCondition(
                key="sophiagraph_kind",
                match=self._models.MatchValue(value="embedding"),
            ),
            self._models.FieldCondition(
                key="vector_space",
                match=self._models.MatchValue(value=query.vector_space),
            ),
        ]
        for key, value in sorted(query.payload_filters.items()):
            conditions.append(
                self._models.FieldCondition(
                    key=str(key),
                    match=self._models.MatchValue(value=value),
                )
            )
        if query.namespaces:
            conditions.append(self._namespace_condition(query.namespaces))
        return self._models.Filter(must=conditions)

    def _namespace_condition(self, namespaces: tuple[MemoryNamespace, ...]) -> Any:
        alternatives = []
        for namespace in namespaces:
            clauses = [
                self._models.FieldCondition(
                    key=f"namespace.{key}",
                    match=self._models.MatchValue(value=value),
                )
                for key, value in sorted(namespace.as_dict().items())
            ]
            alternatives.append(self._models.Filter(must=clauses))
        return self._models.Filter(should=alternatives)

    def set_projection_watermark(self, cursor: int) -> None:
        point = self._models.PointStruct(
            id=_provider_point_id(_WATERMARK_POINT_ID),
            vector=[0.0] * self.vector_size,
            payload={
                "sophiagraph_kind": "projection_watermark",
                "cursor": int(cursor),
            },
        )
        self._upsert_points([point])

    def get_projection_watermark(self) -> int | None:
        retrieve = getattr(self._client, "retrieve", None)
        if retrieve is None:
            return None
        points = retrieve(
            collection_name=self.collection_name,
            ids=[_provider_point_id(_WATERMARK_POINT_ID)],
            with_payload=True,
        )
        if not points:
            return None
        payload = dict(points[0].payload or {})
        value = payload.get("cursor")
        return int(value) if value is not None else None

    def inventory(self) -> tuple[ProjectionInventoryItem, ...]:
        scroll = getattr(self._client, "scroll", None)
        if scroll is None:
            raise InvalidArgumentError(
                "Qdrant client does not support inventory scroll"
            )
        items: list[ProjectionInventoryItem] = []
        offset = None
        while True:
            points, offset = scroll(
                collection_name=self.collection_name,
                scroll_filter=self._models.Filter(
                    must=[
                        self._models.FieldCondition(
                            key="sophiagraph_kind",
                            match=self._models.MatchValue(value="embedding"),
                        )
                    ]
                ),
                limit=256,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            for point in points:
                payload = dict(point.payload or {})
                items.append(
                    ProjectionInventoryItem(
                        object_id=str(payload.get("sophiagraph_point_id") or point.id),
                        object_kind="embedding",
                        version_hash=payload.get("sophiagraph_version"),
                    )
                )
            if offset is None:
                break
        return tuple(sorted(items, key=lambda item: item.object_id))

    def _upsert_points(self, points: list[Any]) -> None:
        kwargs: dict[str, Any] = {
            "collection_name": self.collection_name,
            "points": points,
            "wait": self._wait_for_ack,
        }
        if self._write_ordering is not None:
            kwargs["ordering"] = self._write_ordering
        self._client.upsert(**kwargs)


class QdrantRetrievalAdapter:
    """Bridge a stored Qdrant backend into hybrid retrieval."""

    def __init__(
        self,
        backend: QdrantVectorBackend,
        *,
        namespaces: tuple[MemoryNamespace, ...] = (),
        payload_filters: Mapping[str, Any] | None = None,
    ) -> None:
        self._backend = backend
        self._namespaces = namespaces
        self._payload_filters = dict(payload_filters or {})

    def search(
        self,
        *,
        query_embedding: Sequence[float],
        vector_space: str,
        candidates: Sequence[tuple[str, Sequence[float]]],
        limit: int,
        metric: str,
    ) -> list[tuple[str, float]]:
        allowed_ids = {record_id for record_id, _ in candidates}
        query_limit = max(limit, len(allowed_ids)) if allowed_ids else limit
        hits = self._backend.search(
            VectorQuery(
                vector=tuple(float(value) for value in query_embedding),
                vector_space=vector_space,
                limit=query_limit,
                metric=SimilarityMetric(metric),
                namespaces=self._namespaces,
                payload_filters=self._payload_filters,
            )
        )
        ranked = []
        for hit in hits:
            record_id = str(hit.payload.get("record_id") or hit.point_id)
            if allowed_ids and record_id not in allowed_ids:
                continue
            ranked.append((record_id, hit.score))
            if len(ranked) >= limit:
                break
        return ranked


__all__ = ["QdrantRetrievalAdapter", "QdrantVectorBackend"]
