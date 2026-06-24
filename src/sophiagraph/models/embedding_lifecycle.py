"""Typed DTOs for embedding lifecycle management."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Final, Literal

from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.models.embedding import MemoryEmbedding
from sophiagraph.models.namespace import MemoryNamespace
from sophiagraph.models.primitives import _assert_namespace_id


EmbeddingStalenessReason = Literal[
    "RECORD_UPDATED_AFTER_EMBEDDING",
    "MODEL_NOT_IN_ACTIVE_SET",
    "DIMENSION_MISMATCH",
    "PROVIDER_NOT_IN_ACTIVE_SET",
]


EMBEDDING_STALENESS_REASONS: Final[frozenset[str]] = frozenset(
    {
        "RECORD_UPDATED_AFTER_EMBEDDING",
        "MODEL_NOT_IN_ACTIVE_SET",
        "DIMENSION_MISMATCH",
        "PROVIDER_NOT_IN_ACTIVE_SET",
    }
)


def _string_field(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _optional_string_field(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def namespace_key(namespace: MemoryNamespace) -> str:
    """Return a deterministic namespace key for cursor and storage use."""

    return "|".join(
        f"{key}={value}"
        for key, value in namespace.as_dict().items()
        if value is not None
    )


@dataclass(frozen=True)
class VectorSpaceModelDescriptor:
    """One active embedding model descriptor for a vector space."""

    provider: str
    model: str
    dimension: int

    def __post_init__(self) -> None:
        if not self.provider:
            raise InvalidArgumentError("provider is required")
        if not self.model:
            raise InvalidArgumentError("model is required")
        if int(self.dimension) <= 0:
            raise InvalidArgumentError("dimension must be positive")

    def to_dict(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "model": self.model,
            "dimension": self.dimension,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "VectorSpaceModelDescriptor":
        return cls(
            provider=_string_field(data.get("provider")),
            model=_string_field(data.get("model")),
            dimension=int(data.get("dimension", 0) or 0),
        )


@dataclass(frozen=True)
class ActiveEmbeddingModelSet:
    """Namespace-scoped active embedding model set for one vector space."""

    namespace: MemoryNamespace
    vector_space: str
    active_models: tuple[VectorSpaceModelDescriptor, ...]
    updated_at: str

    def __post_init__(self) -> None:
        if not isinstance(self.namespace, MemoryNamespace):
            raise InvalidArgumentError("namespace must be MemoryNamespace")
        _assert_namespace_id(self.vector_space, "vector_space")
        if not self.updated_at:
            raise InvalidArgumentError("updated_at is required")
        if not self.active_models:
            raise InvalidArgumentError("active_models must not be empty")
        seen: set[tuple[str, str]] = set()
        for descriptor in self.active_models:
            if not isinstance(descriptor, VectorSpaceModelDescriptor):
                raise InvalidArgumentError(
                    "active_models must contain VectorSpaceModelDescriptor entries"
                )
            key = (descriptor.provider, descriptor.model)
            if key in seen:
                raise InvalidArgumentError(
                    "active_models must not contain duplicate provider/model pairs"
                )
            seen.add(key)

    @property
    def key(self) -> tuple[str, str]:
        return (namespace_key(self.namespace), self.vector_space)

    def to_dict(self) -> dict[str, object]:
        return {
            "namespace": self.namespace.as_dict(),
            "vector_space": self.vector_space,
            "active_models": [
                descriptor.to_dict() for descriptor in self.active_models
            ],
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ActiveEmbeddingModelSet":
        raw_namespace = data.get("namespace")
        if not isinstance(raw_namespace, dict):
            raise InvalidArgumentError("namespace is required")
        raw_models = data.get("active_models")
        return cls(
            namespace=MemoryNamespace.from_dict(raw_namespace),
            vector_space=_string_field(data.get("vector_space")),
            active_models=tuple(
                VectorSpaceModelDescriptor.from_dict(item)
                for item in raw_models
                if isinstance(item, dict)
            )
            if isinstance(raw_models, list)
            else (),
            updated_at=_string_field(data.get("updated_at")),
        )


@dataclass(frozen=True)
class StaleEmbeddingFinding:
    """Typed evidence that one embedding should be reconsidered by the host."""

    record_id: str
    vector_space: str
    namespace: MemoryNamespace
    embedding_provider: str
    embedding_model: str
    embedding_dimension: int
    embedding_updated_at: str
    reasons: tuple[EmbeddingStalenessReason, ...]
    record_updated_at: str | None = None
    external_vector_id: str | None = None

    def __post_init__(self) -> None:
        if not self.record_id:
            raise InvalidArgumentError("record_id is required")
        _assert_namespace_id(self.vector_space, "vector_space")
        if not isinstance(self.namespace, MemoryNamespace):
            raise InvalidArgumentError("namespace must be MemoryNamespace")
        if not self.embedding_provider:
            raise InvalidArgumentError("embedding_provider is required")
        if not self.embedding_model:
            raise InvalidArgumentError("embedding_model is required")
        if int(self.embedding_dimension) <= 0:
            raise InvalidArgumentError("embedding_dimension must be positive")
        if not self.embedding_updated_at:
            raise InvalidArgumentError("embedding_updated_at is required")
        if not self.reasons:
            raise InvalidArgumentError("reasons must not be empty")
        for reason in self.reasons:
            if reason not in EMBEDDING_STALENESS_REASONS:
                raise InvalidArgumentError(f"invalid staleness reason: {reason!r}")

    @classmethod
    def from_embedding(
        cls,
        embedding: MemoryEmbedding,
        *,
        reasons: tuple[EmbeddingStalenessReason, ...],
        record_updated_at: str | None,
    ) -> "StaleEmbeddingFinding":
        return cls(
            record_id=embedding.record_id,
            vector_space=embedding.vector_space,
            namespace=embedding.namespace,
            embedding_provider=embedding.provider,
            embedding_model=embedding.model,
            embedding_dimension=embedding.dimension,
            embedding_updated_at=embedding.updated_at,
            reasons=reasons,
            record_updated_at=record_updated_at,
            external_vector_id=embedding.external_vector_id,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "record_id": self.record_id,
            "vector_space": self.vector_space,
            "namespace": self.namespace.as_dict(),
            "embedding_provider": self.embedding_provider,
            "embedding_model": self.embedding_model,
            "embedding_dimension": self.embedding_dimension,
            "embedding_updated_at": self.embedding_updated_at,
            "reasons": list(self.reasons),
            "record_updated_at": self.record_updated_at,
            "external_vector_id": self.external_vector_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "StaleEmbeddingFinding":
        raw_namespace = data.get("namespace")
        if not isinstance(raw_namespace, dict):
            raise InvalidArgumentError("namespace is required")
        raw_reasons = data.get("reasons")
        return cls(
            record_id=_string_field(data.get("record_id")),
            vector_space=_string_field(data.get("vector_space")),
            namespace=MemoryNamespace.from_dict(raw_namespace),
            embedding_provider=_string_field(data.get("embedding_provider")),
            embedding_model=_string_field(data.get("embedding_model")),
            embedding_dimension=int(data.get("embedding_dimension", 0) or 0),
            embedding_updated_at=_string_field(data.get("embedding_updated_at")),
            reasons=tuple(str(item) for item in raw_reasons)
            if isinstance(raw_reasons, list)
            else (),
            record_updated_at=_optional_string_field(data.get("record_updated_at")),
            external_vector_id=_optional_string_field(data.get("external_vector_id")),
        )


@dataclass(frozen=True)
class ReembedCursor:
    """Deterministic resume cursor for re-embed planning."""

    namespace: MemoryNamespace
    vector_space: str
    last_record_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.namespace, MemoryNamespace):
            raise InvalidArgumentError("namespace must be MemoryNamespace")
        _assert_namespace_id(self.vector_space, "vector_space")
        if not self.last_record_id:
            raise InvalidArgumentError("last_record_id is required")

    @property
    def encoded(self) -> str:
        return (
            f"{namespace_key(self.namespace)}|{self.vector_space}|{self.last_record_id}"
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "namespace": self.namespace.as_dict(),
            "vector_space": self.vector_space,
            "last_record_id": self.last_record_id,
            "encoded": self.encoded,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ReembedCursor":
        raw_namespace = data.get("namespace")
        if not isinstance(raw_namespace, dict):
            raise InvalidArgumentError("namespace is required")
        return cls(
            namespace=MemoryNamespace.from_dict(raw_namespace),
            vector_space=_string_field(data.get("vector_space")),
            last_record_id=_string_field(data.get("last_record_id")),
        )


@dataclass(frozen=True)
class ReembedBatch:
    """One deterministic unit of stale embeddings for the host to process."""

    batch_index: int
    target_model: VectorSpaceModelDescriptor
    items: tuple[StaleEmbeddingFinding, ...]
    cursor: ReembedCursor | None = None

    def __post_init__(self) -> None:
        if self.batch_index < 0:
            raise InvalidArgumentError("batch_index must be non-negative")
        if not isinstance(self.target_model, VectorSpaceModelDescriptor):
            raise InvalidArgumentError(
                "target_model must be VectorSpaceModelDescriptor"
            )
        if not self.items:
            raise InvalidArgumentError("items must not be empty")
        for item in self.items:
            if not isinstance(item, StaleEmbeddingFinding):
                raise InvalidArgumentError(
                    "items must contain StaleEmbeddingFinding entries"
                )
        if self.cursor is not None and not isinstance(self.cursor, ReembedCursor):
            raise InvalidArgumentError("cursor must be ReembedCursor when set")

    def to_dict(self) -> dict[str, object]:
        return {
            "batch_index": self.batch_index,
            "target_model": self.target_model.to_dict(),
            "items": [item.to_dict() for item in self.items],
            "cursor": self.cursor.to_dict() if self.cursor is not None else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ReembedBatch":
        raw_items = data.get("items")
        raw_target_model = data.get("target_model")
        raw_cursor = data.get("cursor")
        if not isinstance(raw_target_model, dict):
            raise InvalidArgumentError("target_model is required")
        return cls(
            batch_index=int(data.get("batch_index", -1)),
            target_model=VectorSpaceModelDescriptor.from_dict(raw_target_model),
            items=tuple(
                StaleEmbeddingFinding.from_dict(item)
                for item in raw_items
                if isinstance(item, dict)
            )
            if isinstance(raw_items, list)
            else (),
            cursor=ReembedCursor.from_dict(raw_cursor)
            if isinstance(raw_cursor, dict)
            else None,
        )


@dataclass(frozen=True)
class ReembedPlan:
    """Deterministic stale-embedding plan emitted by SophiaGraph."""

    namespace: MemoryNamespace
    vector_space: str
    target_model: VectorSpaceModelDescriptor
    stale_findings: tuple[StaleEmbeddingFinding, ...] = field(default_factory=tuple)
    batches: tuple[ReembedBatch, ...] = field(default_factory=tuple)
    resumed_from: ReembedCursor | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.namespace, MemoryNamespace):
            raise InvalidArgumentError("namespace must be MemoryNamespace")
        _assert_namespace_id(self.vector_space, "vector_space")
        if not isinstance(self.target_model, VectorSpaceModelDescriptor):
            raise InvalidArgumentError(
                "target_model must be VectorSpaceModelDescriptor"
            )
        for finding in self.stale_findings:
            if not isinstance(finding, StaleEmbeddingFinding):
                raise InvalidArgumentError(
                    "stale_findings must contain StaleEmbeddingFinding entries"
                )
        for batch in self.batches:
            if not isinstance(batch, ReembedBatch):
                raise InvalidArgumentError("batches must contain ReembedBatch entries")
        if self.resumed_from is not None and not isinstance(
            self.resumed_from, ReembedCursor
        ):
            raise InvalidArgumentError("resumed_from must be ReembedCursor when set")

    @property
    def total_findings(self) -> int:
        return len(self.stale_findings)

    def to_dict(self) -> dict[str, object]:
        return {
            "namespace": self.namespace.as_dict(),
            "vector_space": self.vector_space,
            "target_model": self.target_model.to_dict(),
            "stale_findings": [finding.to_dict() for finding in self.stale_findings],
            "batches": [batch.to_dict() for batch in self.batches],
            "resumed_from": (
                self.resumed_from.to_dict() if self.resumed_from is not None else None
            ),
            "total_findings": self.total_findings,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ReembedPlan":
        raw_namespace = data.get("namespace")
        raw_target_model = data.get("target_model")
        raw_findings = data.get("stale_findings")
        raw_batches = data.get("batches")
        raw_resumed_from = data.get("resumed_from")
        if not isinstance(raw_namespace, dict):
            raise InvalidArgumentError("namespace is required")
        if not isinstance(raw_target_model, dict):
            raise InvalidArgumentError("target_model is required")
        return cls(
            namespace=MemoryNamespace.from_dict(raw_namespace),
            vector_space=_string_field(data.get("vector_space")),
            target_model=VectorSpaceModelDescriptor.from_dict(raw_target_model),
            stale_findings=tuple(
                StaleEmbeddingFinding.from_dict(item)
                for item in raw_findings
                if isinstance(item, dict)
            )
            if isinstance(raw_findings, list)
            else (),
            batches=tuple(
                ReembedBatch.from_dict(item)
                for item in raw_batches
                if isinstance(item, dict)
            )
            if isinstance(raw_batches, list)
            else (),
            resumed_from=ReembedCursor.from_dict(raw_resumed_from)
            if isinstance(raw_resumed_from, dict)
            else None,
        )


__all__ = [
    "ActiveEmbeddingModelSet",
    "EMBEDDING_STALENESS_REASONS",
    "EmbeddingStalenessReason",
    "ReembedBatch",
    "ReembedCursor",
    "ReembedPlan",
    "StaleEmbeddingFinding",
    "VectorSpaceModelDescriptor",
    "namespace_key",
]
