"""Typed hybrid-retrieval stage contracts and result packets."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Final, Literal, Sequence

from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.models import MemoryNamespace, MemoryRecord

RetrievalStage = Literal[
    "keyword",
    "vector",
    "graph",
    "recency",
    "trust",
    "rerank",
]

RETRIEVAL_STAGES: Final[tuple[str, ...]] = (
    "keyword",
    "vector",
    "graph",
    "recency",
    "trust",
    "rerank",
)

STAGE_ORDER: Final[dict[str, int]] = {
    name: i for i, name in enumerate(RETRIEVAL_STAGES)
}

ScoreComponentKind = Literal[
    "keyword",
    "vector",
    "graph_proximity",
    "recency",
    "trust",
    "rerank",
]

SCORE_COMPONENT_KINDS: Final[frozenset[str]] = frozenset(
    {
        "keyword",
        "vector",
        "graph_proximity",
        "recency",
        "trust",
        "rerank",
    }
)


@dataclass(frozen=True)
class KeywordStageOptions:
    """Keyword retrieval with fallback substring and optional FTS5 ranking."""

    query: str
    limit: int = 50

    def __post_init__(self) -> None:
        if not self.query:
            raise InvalidArgumentError("keyword query is required")
        if self.limit <= 0:
            raise InvalidArgumentError("keyword limit must be positive")


@dataclass(frozen=True)
class VectorStageOptions:
    """Vector retrieval via caller-supplied adapter and query embedding."""

    query_embedding: Sequence[float]
    vector_space: str
    limit: int = 20
    metric: str = "cosine"

    def __post_init__(self) -> None:
        if not self.query_embedding:
            raise InvalidArgumentError("query_embedding is required")
        if not self.vector_space:
            raise InvalidArgumentError("vector_space is required")
        if self.limit <= 0:
            raise InvalidArgumentError("vector limit must be positive")
        if self.metric not in {"cosine", "l2", "dot"}:
            raise InvalidArgumentError(f"unknown vector metric: {self.metric!r}")


@dataclass(frozen=True)
class GraphStageOptions:
    """Graph-neighborhood expansion around prior-stage hits."""

    depth: int = 1
    relation_types: list[str] | None = None
    max_expanded_records: int = 50

    def __post_init__(self) -> None:
        if self.depth < 0:
            raise InvalidArgumentError("graph depth must be >= 0")
        if self.max_expanded_records <= 0:
            raise InvalidArgumentError("max_expanded_records must be positive")


@dataclass(frozen=True)
class RecencyStageOptions:
    """Recency weighting with a half-life in days for updated_at decay."""

    half_life_days: float = 30.0

    def __post_init__(self) -> None:
        if self.half_life_days <= 0:
            raise InvalidArgumentError("half_life_days must be positive")


@dataclass(frozen=True)
class TrustStageOptions:
    """Trust weighting per record source with caller-supplied multipliers."""

    source_weights: dict[str, float] = field(default_factory=dict)
    default_weight: float = 1.0

    def __post_init__(self) -> None:
        for source, weight in self.source_weights.items():
            if not source:
                raise InvalidArgumentError("source name cannot be empty")
            if weight < 0:
                raise InvalidArgumentError(f"trust weight for {source!r} must be >= 0")
        if self.default_weight < 0:
            raise InvalidArgumentError("default_weight must be >= 0")


@dataclass(frozen=True)
class RerankStageOptions:
    """Rerank stage with deterministic fallback score overrides."""

    score_override: dict[str, float] = field(default_factory=dict)
    limit: int | None = None


@dataclass(frozen=True)
class RetrievalRequest:
    """One typed hybrid retrieval request."""

    scopes: list[str]
    namespaces: list[MemoryNamespace] | None = None
    keyword: KeywordStageOptions | None = None
    vector: VectorStageOptions | None = None
    graph: GraphStageOptions | None = None
    recency: RecencyStageOptions | None = None
    trust: TrustStageOptions | None = None
    rerank: RerankStageOptions | None = None
    limit: int = 20

    def __post_init__(self) -> None:
        if not self.scopes:
            raise InvalidArgumentError("retrieval requires at least one scope")
        if self.limit <= 0:
            raise InvalidArgumentError("retrieval limit must be positive")

    @property
    def active_stages(self) -> list[str]:
        stages: list[str] = []
        if self.keyword is not None:
            stages.append("keyword")
        if self.vector is not None:
            stages.append("vector")
        if self.graph is not None:
            stages.append("graph")
        if self.recency is not None:
            stages.append("recency")
        if self.trust is not None:
            stages.append("trust")
        if self.rerank is not None:
            stages.append("rerank")
        return stages


@dataclass(frozen=True)
class ScoreComponent:
    """One per-stage score contribution for a retrieved record."""

    kind: ScoreComponentKind
    raw_score: float
    weight: float = 1.0
    detail: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.kind not in SCORE_COMPONENT_KINDS:
            raise InvalidArgumentError(f"unknown score component kind: {self.kind!r}")

    @property
    def weighted_score(self) -> float:
        return float(self.raw_score) * float(self.weight)


@dataclass(frozen=True)
class RetrievalExplanation:
    """Per-hit explanation for how a record reached its final score."""

    record_id: str
    components: list[ScoreComponent]
    final_score: float
    source_record_ids: list[str] = field(default_factory=list)
    via_relation_ids: list[str] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RetrievalHit:
    """One ranked retrieval hit."""

    record: MemoryRecord
    score: float
    explanation: RetrievalExplanation


@dataclass(frozen=True)
class RetrievalResult:
    """Typed result of one hybrid retrieval call."""

    hits: list[RetrievalHit]
    request_stage_order: list[str]
    namespaces_applied: list[MemoryNamespace] | None
    truncated: bool = False


class RerankAdapter:
    """Optional rerank adapter protocol over already-fused candidates."""

    def rerank(
        self,
        *,
        records: Sequence[MemoryRecord],
        request: RetrievalRequest,
        limit: int,
    ) -> list[tuple[str, float]]:
        raise NotImplementedError


class VectorAdapter:
    """Optional vector adapter protocol."""

    def search(
        self,
        *,
        query_embedding: Sequence[float],
        vector_space: str,
        candidates: Sequence[tuple[str, Sequence[float]]],
        limit: int,
        metric: str,
    ) -> list[tuple[str, float]]:
        raise NotImplementedError
