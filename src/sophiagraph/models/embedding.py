"""Caller-supplied embedding sidecar DTOs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.models.namespace import MemoryNamespace
from sophiagraph.models.primitives import _assert_namespace_id


def _string_field(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _optional_string_field(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _metadata_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise InvalidArgumentError("metadata must be a dict")
    return dict(value)


def _vector_list(value: Any) -> list[float] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        raise InvalidArgumentError("vector must be a list")
    return [float(item) for item in value]


@dataclass(frozen=True, slots=True)
class MemoryEmbedding:
    record_id: str
    vector_space: str
    dimension: int
    provider: str
    model: str
    namespace: MemoryNamespace
    created_at: str
    updated_at: str
    vector: list[float] | None = None
    external_vector_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.record_id:
            raise InvalidArgumentError("record_id is required")
        _assert_namespace_id(self.vector_space, "vector_space")
        if int(self.dimension) <= 0:
            raise InvalidArgumentError("dimension must be positive")
        if not self.provider:
            raise InvalidArgumentError("provider is required")
        if not self.model:
            raise InvalidArgumentError("model is required")
        if not isinstance(self.namespace, MemoryNamespace):
            raise TypeError(
                "namespace must be MemoryNamespace"
            )  # allow-bare-raise: defensive dataclass guard
        if not self.created_at:
            raise InvalidArgumentError("created_at is required")
        if not self.updated_at:
            raise InvalidArgumentError("updated_at is required")
        if not isinstance(self.metadata, dict):
            raise TypeError(
                "metadata must be a dict"
            )  # allow-bare-raise: defensive dataclass guard
        if (
            self.vector is None
            and not self.external_vector_id
            and not bool(self.metadata.get("vector_omitted"))
        ):
            raise InvalidArgumentError("vector or external_vector_id is required")
        if self.vector is not None:
            if len(self.vector) != int(self.dimension):
                raise InvalidArgumentError("vector length must match dimension")
            for value in self.vector:
                if not isinstance(value, int | float):
                    raise TypeError(
                        "vector must contain numeric values"
                    )  # allow-bare-raise: defensive dataclass guard
        if (
            self.external_vector_id is not None
            and not str(self.external_vector_id).strip()
        ):
            raise InvalidArgumentError("external_vector_id must be non-empty when set")

    @property
    def key(self) -> str:
        return f"{self.record_id}:{self.vector_space}"

    @property
    def has_vector(self) -> bool:
        return self.vector is not None

    def without_vector(self) -> "MemoryEmbedding":
        return MemoryEmbedding(
            record_id=self.record_id,
            vector_space=self.vector_space,
            dimension=self.dimension,
            provider=self.provider,
            model=self.model,
            namespace=self.namespace,
            created_at=self.created_at,
            updated_at=self.updated_at,
            vector=None,
            external_vector_id=self.external_vector_id,
            metadata={**self.metadata, "vector_omitted": True},
        )


def memory_embedding_from_dict(data: dict[str, Any]) -> MemoryEmbedding:
    raw_namespace = data.get("namespace")
    if isinstance(raw_namespace, MemoryNamespace):
        namespace = raw_namespace
    elif isinstance(raw_namespace, dict) and raw_namespace:
        namespace = MemoryNamespace.from_dict(raw_namespace)
    else:
        raise InvalidArgumentError("namespace is required")
    return MemoryEmbedding(
        record_id=_string_field(data.get("record_id")),
        vector_space=_string_field(data.get("vector_space")),
        dimension=int(data.get("dimension", 0) or 0),
        provider=_string_field(data.get("provider")),
        model=_string_field(data.get("model")),
        namespace=namespace,
        created_at=_string_field(data.get("created_at")),
        updated_at=_string_field(data.get("updated_at")),
        vector=_vector_list(data.get("vector")),
        external_vector_id=_optional_string_field(data.get("external_vector_id")),
        metadata=_metadata_dict(data.get("metadata")),
    )


__all__ = ["MemoryEmbedding", "memory_embedding_from_dict"]
