"""Optional stored-vector backend contracts and adapters."""

from .qdrant import QdrantRetrievalAdapter, QdrantVectorBackend
from .types import (
    StoredVectorBackend,
    VectorBackendCapabilities,
    VectorHit,
    VectorPoint,
    VectorQuery,
)

__all__ = [
    "QdrantVectorBackend",
    "QdrantRetrievalAdapter",
    "StoredVectorBackend",
    "VectorBackendCapabilities",
    "VectorHit",
    "VectorPoint",
    "VectorQuery",
]
