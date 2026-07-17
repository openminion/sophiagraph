"""Deterministic in-memory stored-vector backend for conformance tests."""

from __future__ import annotations

from sophiagraph.models.projection import ProjectionInventoryItem
from sophiagraph.vectors import SimilarityMetric, compute_similarity

from .types import VectorBackendCapabilities, VectorHit, VectorPoint, VectorQuery


class FakeVectorBackend:
    def __init__(self) -> None:
        self._points: dict[str, VectorPoint] = {}
        self._watermark: int | None = None

    def capabilities(self) -> VectorBackendCapabilities:
        return VectorBackendCapabilities(
            backend_name="fake",
            metrics=tuple(SimilarityMetric),
            namespace_filtering=True,
            payload_filtering=True,
            wait_for_ack=True,
            write_ordering="atomic_memory",
            projection_watermark=True,
            inventory=True,
        )

    def upsert(self, points: tuple[VectorPoint, ...]) -> None:
        for point in points:
            self._points[point.point_id] = point

    def search(self, query: VectorQuery) -> tuple[VectorHit, ...]:
        hits: list[VectorHit] = []
        for point in self._points.values():
            if point.vector_space != query.vector_space:
                continue
            if query.namespaces and point.namespace not in query.namespaces:
                continue
            if any(
                point.payload.get(key) != value
                for key, value in query.payload_filters.items()
            ):
                continue
            hits.append(
                VectorHit(
                    point_id=point.point_id,
                    score=compute_similarity(query.metric, query.vector, point.vector),
                    payload=point.payload,
                )
            )
        hits.sort(key=lambda item: (-item.score, item.point_id))
        return tuple(hits[: query.limit])

    def delete(self, point_ids: tuple[str, ...]) -> None:
        for point_id in point_ids:
            self._points.pop(point_id, None)

    def healthcheck(self) -> bool:
        return True

    def set_projection_watermark(self, cursor: int) -> None:
        self._watermark = int(cursor)

    def get_projection_watermark(self) -> int | None:
        return self._watermark

    def inventory(self) -> tuple[ProjectionInventoryItem, ...]:
        return tuple(
            ProjectionInventoryItem(
                object_id=point.point_id,
                object_kind="embedding",
                version_hash=point.version_hash,
            )
            for point in sorted(self._points.values(), key=lambda item: item.point_id)
        )


__all__ = ["FakeVectorBackend"]
