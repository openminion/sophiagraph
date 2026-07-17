"""Optional stored-vector backend contracts and adapters."""

from .qdrant import QdrantRetrievalAdapter, QdrantVectorBackend
from .fake import FakeVectorBackend
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
    "FakeVectorBackend",
    "StoredVectorBackend",
    "VectorBackendCapabilities",
    "VectorHit",
    "VectorPoint",
    "VectorQuery",
]
