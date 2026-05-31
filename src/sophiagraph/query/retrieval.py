"""Hybrid retrieval stage DTOs, scoring, and explanations."""

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
    """Keyword retrieval — fallback substring + optional FTS5 hit-ranking."""

    query: str
    limit: int = 50

    def __post_init__(self) -> None:
        if not self.query:
            raise InvalidArgumentError("keyword query is required")
        if self.limit <= 0:
            raise InvalidArgumentError("keyword limit must be positive")


@dataclass(frozen=True)
class VectorStageOptions:
    """Vector retrieval via caller-supplied adapter + query embedding."""

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
    """Recency weighting — half-life in days for updated_at decay."""

    half_life_days: float = 30.0

    def __post_init__(self) -> None:
        if self.half_life_days <= 0:
            raise InvalidArgumentError("half_life_days must be positive")


@dataclass(frozen=True)
class TrustStageOptions:
    """Trust weighting per record source (caller-supplied multipliers)."""

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
    """Per-hit explanation: how a record reached its final score."""

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


def _rrf_scores(
    component_map: dict[str, list[ScoreComponent]],
    *,
    rank_constant: int = 60,
) -> dict[str, float]:
    scores = {record_id: 0.0 for record_id in component_map}
    kinds = sorted(
        {
            component.kind
            for components in component_map.values()
            for component in components
            if component.kind != "rerank"
        }
    )
    for kind in kinds:
        ranked = sorted(
            (
                (record_id, component.weighted_score)
                for record_id, components in component_map.items()
                for component in components
                if component.kind == kind
            ),
            key=lambda item: (-item[1], item[0]),
        )
        for rank, (record_id, _) in enumerate(ranked, start=1):
            scores[record_id] = scores.get(record_id, 0.0) + 1.0 / (
                rank_constant + rank
            )
    for record_id, components in component_map.items():
        rerank_scores = [c.weighted_score for c in components if c.kind == "rerank"]
        if rerank_scores:
            scores[record_id] = max(rerank_scores) + scores.get(record_id, 0.0)
    return scores


def _recency_score(updated_at: str, *, now_iso: str, half_life_days: float) -> float:
    """Exponential recency decay using caller-supplied timestamps."""
    from datetime import datetime

    try:
        updated = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
        now = datetime.fromisoformat(now_iso.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return 0.0
    delta_days = max(0.0, (now - updated).total_seconds() / 86400.0)
    return 0.5 ** (delta_days / float(half_life_days))


def assemble_retrieval(
    store: Any,
    request: RetrievalRequest,
    *,
    vector_adapter: VectorAdapter | None = None,
    rerank_adapter: RerankAdapter | None = None,
    now_iso: str = "",
) -> RetrievalResult:
    """Execute the hybrid retrieval pipeline in canonical stage order."""

    active = request.active_stages
    for prev, curr in zip(active, active[1:]):
        if STAGE_ORDER[prev] >= STAGE_ORDER[curr]:
            raise InvalidArgumentError(
                f"retrieval stages out of order: {prev!r} before {curr!r}"
            )

    if request.vector is not None and vector_adapter is None:
        raise InvalidArgumentError(
            "vector stage requested but no VectorAdapter was supplied"
        )

    component_map: dict[str, list[ScoreComponent]] = {}
    record_map: dict[str, MemoryRecord] = {}
    via_relations: dict[str, list[str]] = {}

    if request.keyword is not None:
        from sophiagraph.query import SearchQueryOptions

        options = SearchQueryOptions(
            query=request.keyword.query,
            scopes=request.scopes,
            namespaces=request.namespaces,
            limit=request.keyword.limit,
        )
        for index, record in enumerate(store.search_records(options)):
            record_map[record.id] = record
            raw = max(0.0, 1.0 - (index / max(1, request.keyword.limit)))
            component_map.setdefault(record.id, []).append(
                ScoreComponent(
                    kind="keyword",
                    raw_score=raw,
                    weight=1.0,
                    detail={"rank": index},
                )
            )

    if request.vector is not None:
        from sophiagraph.query import EmbeddingListOptions

        embeddings = store.list_embeddings(
            EmbeddingListOptions(
                vector_space=request.vector.vector_space,
                namespaces=request.namespaces,
            )
        )
        candidates = [
            (e.record_id, list(e.vector or []))
            for e in embeddings
            if e.vector is not None
        ]
        if candidates and vector_adapter is not None:
            results = vector_adapter.search(
                query_embedding=list(request.vector.query_embedding),
                vector_space=request.vector.vector_space,
                candidates=candidates,
                limit=request.vector.limit,
                metric=request.vector.metric,
            )
            for record_id, score in results:
                record = record_map.get(record_id) or store.get_record(record_id)
                if record is None:
                    continue
                record_map[record_id] = record
                component_map.setdefault(record_id, []).append(
                    ScoreComponent(
                        kind="vector",
                        raw_score=float(score),
                        weight=1.0,
                        detail={"vector_space": request.vector.vector_space},
                    )
                )

    if request.graph is not None and request.graph.depth > 0:
        seeds = list(record_map.keys())
        for seed in seeds:
            try:
                relations = store.list_relations(
                    seed,
                    direction="both",
                    relation_types=request.graph.relation_types,
                    limit=request.graph.max_expanded_records,
                )
            except Exception:
                continue
            for relation in relations:
                neighbor_id = (
                    relation.target_record_id
                    if relation.source_record_id == seed
                    else relation.source_record_id
                )
                if neighbor_id in record_map:
                    via_relations.setdefault(neighbor_id, []).append(
                        relation.relation_id
                    )
                    component_map.setdefault(neighbor_id, []).append(
                        ScoreComponent(
                            kind="graph_proximity",
                            raw_score=0.5,
                            weight=1.0,
                            detail={"via_record_id": seed},
                        )
                    )
                    continue
                neighbor = store.get_record(neighbor_id)
                if neighbor is None:
                    continue
                record_map[neighbor_id] = neighbor
                via_relations.setdefault(neighbor_id, []).append(relation.relation_id)
                component_map.setdefault(neighbor_id, []).append(
                    ScoreComponent(
                        kind="graph_proximity",
                        raw_score=0.5,
                        weight=1.0,
                        detail={"via_record_id": seed, "depth": 1},
                    )
                )

    if request.recency is not None and now_iso:
        for record_id, record in record_map.items():
            score = _recency_score(
                record.updated_at,
                now_iso=now_iso,
                half_life_days=request.recency.half_life_days,
            )
            component_map.setdefault(record_id, []).append(
                ScoreComponent(
                    kind="recency",
                    raw_score=score,
                    weight=1.0,
                    detail={"half_life_days": request.recency.half_life_days},
                )
            )

    if request.trust is not None:
        for record_id, record in record_map.items():
            weight = request.trust.source_weights.get(
                str(record.source), request.trust.default_weight
            )
            component_map.setdefault(record_id, []).append(
                ScoreComponent(
                    kind="trust",
                    raw_score=1.0,
                    weight=float(weight),
                    detail={"source": str(record.source)},
                )
            )

    if request.rerank is not None:
        if rerank_adapter is not None:
            limit = request.rerank.limit or request.limit
            ranked_records = [
                record_map[record_id]
                for record_id in sorted(record_map)
                if record_id in record_map
            ]
            for record_id, score in rerank_adapter.rerank(
                records=ranked_records,
                request=request,
                limit=limit,
            ):
                if record_id not in record_map:
                    continue
                component_map.setdefault(record_id, []).append(
                    ScoreComponent(
                        kind="rerank",
                        raw_score=float(score),
                        weight=1.0,
                        detail={"source": "adapter"},
                    )
                )
        for record_id, override_score in request.rerank.score_override.items():
            if record_id not in record_map:
                continue
            component_map.setdefault(record_id, []).append(
                ScoreComponent(
                    kind="rerank",
                    raw_score=float(override_score),
                    weight=1.0,
                    detail={"source": "caller_supplied"},
                )
            )
    rrf_scores = _rrf_scores(component_map)
    explanations: list[RetrievalExplanation] = []
    for record_id, record in record_map.items():
        components = component_map.get(record_id, [])
        final = rrf_scores.get(record_id, 0.0)
        explanations.append(
            RetrievalExplanation(
                record_id=record_id,
                components=list(components),
                final_score=float(final),
                source_record_ids=[record_id],
                via_relation_ids=list(via_relations.get(record_id, [])),
                provenance={
                    "scope": record.scope,
                    "source": str(record.source),
                    "fusion": "rrf",
                },
            )
        )
    explanations.sort(key=lambda e: (-e.final_score, e.record_id))
    hits = [
        RetrievalHit(
            record=record_map[e.record_id],
            score=e.final_score,
            explanation=e,
        )
        for e in explanations
    ]
    truncated = len(hits) > request.limit
    if truncated:
        hits = hits[: request.limit]
    return RetrievalResult(
        hits=hits,
        request_stage_order=active,
        namespaces_applied=request.namespaces,
        truncated=truncated,
    )


__all__ = [
    "GraphStageOptions",
    "KeywordStageOptions",
    "RecencyStageOptions",
    "RerankAdapter",
    "RerankStageOptions",
    "RetrievalExplanation",
    "RetrievalHit",
    "RetrievalRequest",
    "RetrievalResult",
    "RETRIEVAL_STAGES",
    "RetrievalStage",
    "SCORE_COMPONENT_KINDS",
    "STAGE_ORDER",
    "ScoreComponent",
    "ScoreComponentKind",
    "TrustStageOptions",
    "VectorAdapter",
    "VectorStageOptions",
    "assemble_retrieval",
]
