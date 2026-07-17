"""Provider-neutral stored-vector backend contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol

from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.models import MemoryNamespace
from sophiagraph.models.projection import ProjectionInventoryItem
from sophiagraph.vectors import SimilarityMetric


@dataclass(frozen=True, slots=True)
class VectorBackendCapabilities:
    backend_name: str
    metrics: tuple[SimilarityMetric, ...]
    namespace_filtering: bool
    payload_filtering: bool
    healthcheck: bool = True
    idempotent_writes: bool = True
    wait_for_ack: bool = False
    write_ordering: str = "provider_default"
    projection_watermark: bool = False
    inventory: bool = False


@dataclass(frozen=True, slots=True)
class VectorPoint:
    point_id: str
    vector: tuple[float, ...]
    vector_space: str
    namespace: MemoryNamespace
    payload: Mapping[str, Any] = field(default_factory=dict)
    version_hash: str | None = None

    def __post_init__(self) -> None:
        if not self.point_id or not self.vector_space:
            raise InvalidArgumentError("point_id and vector_space are required")
        if not self.vector:
            raise InvalidArgumentError("vector must be non-empty")
        if not isinstance(self.namespace, MemoryNamespace):
            raise TypeError("namespace must be MemoryNamespace")


@dataclass(frozen=True, slots=True)
class VectorQuery:
    vector: tuple[float, ...]
    vector_space: str
    limit: int = 20
    metric: SimilarityMetric = SimilarityMetric.COSINE
    namespaces: tuple[MemoryNamespace, ...] = ()
    payload_filters: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.vector or not self.vector_space:
            raise InvalidArgumentError("vector and vector_space are required")
        if self.limit <= 0:
            raise InvalidArgumentError("limit must be positive")


@dataclass(frozen=True, slots=True)
class VectorHit:
    point_id: str
    score: float
    payload: Mapping[str, Any] = field(default_factory=dict)


class StoredVectorBackend(Protocol):
    def capabilities(self) -> VectorBackendCapabilities: ...

    def upsert(self, points: tuple[VectorPoint, ...]) -> None: ...

    def search(self, query: VectorQuery) -> tuple[VectorHit, ...]: ...

    def delete(self, point_ids: tuple[str, ...]) -> None: ...

    def healthcheck(self) -> bool: ...

    def set_projection_watermark(self, cursor: int) -> None: ...

    def get_projection_watermark(self) -> int | None: ...

    def inventory(self) -> tuple[ProjectionInventoryItem, ...]: ...


__all__ = [
    "StoredVectorBackend",
    "VectorBackendCapabilities",
    "VectorHit",
    "VectorPoint",
    "VectorQuery",
]
