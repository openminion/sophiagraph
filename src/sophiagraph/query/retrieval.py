"""Hybrid retrieval pipeline over typed stage contracts."""

from __future__ import annotations

from typing import Any

from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.models import MemoryRecord
from sophiagraph.query.retrieval_types import (
    GraphStageOptions,
    KeywordStageOptions,
    RecencyStageOptions,
    RerankAdapter,
    RerankStageOptions,
    RetrievalExplanation,
    RetrievalHit,
    RetrievalRequest,
    RetrievalResult,
    RETRIEVAL_STAGES,
    RetrievalStage,
    SCORE_COMPONENT_KINDS,
    ScoreComponent,
    ScoreComponentKind,
    STAGE_ORDER,
    TrustStageOptions,
    VectorAdapter,
    VectorStageOptions,
)


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
            (embedding.record_id, list(embedding.vector or []))
            for embedding in embeddings
            if embedding.vector is not None
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
        _expand_graph_stage(
            store,
            request=request,
            record_map=record_map,
            component_map=component_map,
            via_relations=via_relations,
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
        _apply_rerank_stage(
            request=request,
            record_map=record_map,
            component_map=component_map,
            rerank_adapter=rerank_adapter,
        )

    return _build_retrieval_result(
        request=request,
        record_map=record_map,
        component_map=component_map,
        via_relations=via_relations,
        active_stages=active,
    )


def _expand_graph_stage(
    store: Any,
    *,
    request: RetrievalRequest,
    record_map: dict[str, MemoryRecord],
    component_map: dict[str, list[ScoreComponent]],
    via_relations: dict[str, list[str]],
) -> None:
    for seed in list(record_map):
        try:
            relations = store.list_relations(
                seed,
                direction="both",
                relation_types=request.graph.relation_types if request.graph else None,
                limit=request.graph.max_expanded_records if request.graph else 0,
            )
        except Exception:
            continue
        for relation in relations:
            neighbor_id = (
                relation.target_record_id
                if relation.source_record_id == seed
                else relation.source_record_id
            )
            via_relations.setdefault(neighbor_id, []).append(relation.relation_id)
            component = ScoreComponent(
                kind="graph_proximity",
                raw_score=0.5,
                weight=1.0,
                detail={"via_record_id": seed, "depth": 1},
            )
            if neighbor_id in record_map:
                component.detail.pop("depth")
                component_map.setdefault(neighbor_id, []).append(component)
                continue
            neighbor = store.get_record(neighbor_id)
            if neighbor is None or neighbor.scope not in request.scopes:
                continue
            record_map[neighbor_id] = neighbor
            component_map.setdefault(neighbor_id, []).append(component)


def _apply_rerank_stage(
    *,
    request: RetrievalRequest,
    record_map: dict[str, MemoryRecord],
    component_map: dict[str, list[ScoreComponent]],
    rerank_adapter: RerankAdapter | None,
) -> None:
    if request.rerank is None:
        return
    if rerank_adapter is not None:
        limit = request.rerank.limit or request.limit
        ranked_records = [record_map[record_id] for record_id in sorted(record_map)]
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


def _build_retrieval_result(
    *,
    request: RetrievalRequest,
    record_map: dict[str, MemoryRecord],
    component_map: dict[str, list[ScoreComponent]],
    via_relations: dict[str, list[str]],
    active_stages: list[str],
) -> RetrievalResult:
    rrf_scores = _rrf_scores(component_map)
    explanations: list[RetrievalExplanation] = []
    for record_id, record in record_map.items():
        components = component_map.get(record_id, [])
        explanations.append(
            RetrievalExplanation(
                record_id=record_id,
                components=list(components),
                final_score=float(rrf_scores.get(record_id, 0.0)),
                source_record_ids=[record_id],
                via_relation_ids=list(via_relations.get(record_id, [])),
                provenance={
                    "scope": record.scope,
                    "source": str(record.source),
                    "fusion": "rrf",
                },
            )
        )
    explanations.sort(
        key=lambda explanation: (-explanation.final_score, explanation.record_id)
    )
    hits = [
        RetrievalHit(
            record=record_map[explanation.record_id],
            score=explanation.final_score,
            explanation=explanation,
        )
        for explanation in explanations
    ]
    truncated = len(hits) > request.limit
    if truncated:
        hits = hits[: request.limit]
    return RetrievalResult(
        hits=hits,
        request_stage_order=active_stages,
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
