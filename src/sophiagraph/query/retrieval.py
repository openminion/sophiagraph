"""Hybrid retrieval pipeline over typed stage contracts."""

from __future__ import annotations

from contextlib import suppress
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
    RetrievalEligibilityCallback,
    RetrievalEligibilityDecision,
    RetrievalHit,
    RetrievalOmission,
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


class _Eligibility:
    def __init__(self, callback: RetrievalEligibilityCallback | None) -> None:
        self.callback = callback
        self._decisions: dict[tuple[str, RetrievalStage], bool] = {}
        self._omissions: dict[tuple[str, RetrievalStage, str], RetrievalOmission] = {}

    def allows(self, record: MemoryRecord, stage: RetrievalStage) -> bool:
        if self.callback is None:
            return True
        key = (record.id, stage)
        cached = self._decisions.get(key)
        if cached is not None:
            return cached
        try:
            decision = self.callback(record, stage)
        except Exception:
            decision = RetrievalEligibilityDecision(
                eligible=False,
                reason_code="eligibility_callback_error",
            )
        self._decisions[key] = decision.eligible
        if not decision.eligible:
            omission = RetrievalOmission(
                item_id=record.id,
                stage=stage,
                reason_code=decision.reason_code,
            )
            self._omissions.setdefault(
                (omission.item_id, omission.stage, omission.reason_code), omission
            )
        return decision.eligible

    @property
    def omissions(self) -> list[RetrievalOmission]:
        return list(self._omissions.values())


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


def _apply_keyword_stage(
    store: Any,
    *,
    request: RetrievalRequest,
    record_map: dict[str, MemoryRecord],
    component_map: dict[str, list[ScoreComponent]],
    eligibility: _Eligibility,
) -> None:
    if request.keyword is None:
        return
    from sophiagraph.query import SearchQueryOptions

    eligible_index = 0
    offset = 0
    while eligible_index < request.keyword.limit:
        page = store.search_records(
            SearchQueryOptions(
                query=request.keyword.query,
                scopes=request.scopes,
                namespaces=request.namespaces,
                limit=request.keyword.limit,
                offset=(None if request.eligibility_callback is None else offset),
            )
        )
        for record in page:
            if not eligibility.allows(record, "keyword"):
                continue
            record_map[record.id] = record
            raw = max(
                0.0,
                1.0 - (eligible_index / max(1, request.keyword.limit)),
            )
            component_map.setdefault(record.id, []).append(
                ScoreComponent(
                    kind="keyword",
                    raw_score=raw,
                    weight=1.0,
                    detail={"rank": eligible_index},
                )
            )
            eligible_index += 1
            if eligible_index >= request.keyword.limit:
                break
        if request.eligibility_callback is None or len(page) < request.keyword.limit:
            break
        offset += len(page)


def _apply_vector_stage(
    store: Any,
    *,
    request: RetrievalRequest,
    record_map: dict[str, MemoryRecord],
    component_map: dict[str, list[ScoreComponent]],
    via_relations: dict[str, list[str]],
    eligibility: _Eligibility,
    vector_adapter: VectorAdapter | None,
) -> None:
    if request.vector is None:
        return
    from sophiagraph.query import EmbeddingListOptions

    embeddings = store.list_embeddings(
        EmbeddingListOptions(
            vector_space=request.vector.vector_space,
            namespaces=request.namespaces,
        )
    )
    candidates: list[tuple[str, list[float]]] = []
    vector_records: dict[str, MemoryRecord] = {}
    for embedding in embeddings:
        if embedding.vector is None:
            continue
        if request.eligibility_callback is not None:
            record = record_map.get(embedding.record_id) or store.get_record(
                embedding.record_id
            )
            if record is None:
                continue
            if not eligibility.allows(record, "vector"):
                _remove_record(
                    record.id,
                    record_map,
                    component_map,
                    via_relations,
                )
                continue
            vector_records[record.id] = record
        candidates.append((embedding.record_id, list(embedding.vector)))
    if not candidates or vector_adapter is None:
        return
    results = vector_adapter.search(
        query_embedding=list(request.vector.query_embedding),
        vector_space=request.vector.vector_space,
        candidates=candidates,
        limit=request.vector.limit,
        metric=request.vector.metric,
    )
    for record_id, score in results:
        if request.eligibility_callback is not None and record_id not in vector_records:
            continue
        record = (
            vector_records.get(record_id)
            or record_map.get(record_id)
            or store.get_record(record_id)
        )
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
    eligibility = _Eligibility(request.eligibility_callback)

    _apply_keyword_stage(
        store,
        request=request,
        record_map=record_map,
        component_map=component_map,
        eligibility=eligibility,
    )
    _apply_vector_stage(
        store,
        request=request,
        record_map=record_map,
        component_map=component_map,
        via_relations=via_relations,
        eligibility=eligibility,
        vector_adapter=vector_adapter,
    )

    if request.graph is not None and request.graph.depth > 0:
        _expand_graph_stage(
            store,
            request=request,
            record_map=record_map,
            component_map=component_map,
            via_relations=via_relations,
            eligibility=eligibility,
        )

    if request.recency is not None and now_iso:
        for record_id, record in list(record_map.items()):
            if not eligibility.allows(record, "recency"):
                _remove_record(record_id, record_map, component_map, via_relations)
                continue
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
        for record_id, record in list(record_map.items()):
            if not eligibility.allows(record, "trust"):
                _remove_record(record_id, record_map, component_map, via_relations)
                continue
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
            eligibility=eligibility,
            via_relations=via_relations,
        )

    return _build_retrieval_result(
        request=request,
        record_map=record_map,
        component_map=component_map,
        via_relations=via_relations,
        active_stages=active,
        omissions=eligibility.omissions,
    )


def _remove_record(
    record_id: str,
    record_map: dict[str, MemoryRecord],
    component_map: dict[str, list[ScoreComponent]],
    via_relations: dict[str, list[str]],
) -> None:
    record_map.pop(record_id, None)
    component_map.pop(record_id, None)
    via_relations.pop(record_id, None)


def _expand_graph_stage(
    store: Any,
    *,
    request: RetrievalRequest,
    record_map: dict[str, MemoryRecord],
    component_map: dict[str, list[ScoreComponent]],
    via_relations: dict[str, list[str]],
    eligibility: _Eligibility,
) -> None:
    for seed in list(record_map):
        seed_record = record_map[seed]
        if not eligibility.allows(seed_record, "graph"):
            _remove_record(seed, record_map, component_map, via_relations)
            continue
        relations = []
        with suppress(Exception):
            relations = store.list_relations(
                seed,
                direction="both",
                relation_types=request.graph.relation_types if request.graph else None,
                limit=(
                    request.graph.max_expanded_records
                    if request.graph and request.eligibility_callback is None
                    else None
                ),
            )
        expanded = 0
        for relation in relations:
            neighbor_id = (
                relation.target_record_id
                if relation.source_record_id == seed
                else relation.source_record_id
            )
            neighbor = record_map.get(neighbor_id) or store.get_record(neighbor_id)
            if neighbor is None or neighbor.scope not in request.scopes:
                continue
            if not eligibility.allows(neighbor, "graph"):
                continue
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
            else:
                record_map[neighbor_id] = neighbor
                component_map.setdefault(neighbor_id, []).append(component)
            expanded += 1
            if request.graph and expanded >= request.graph.max_expanded_records:
                break


def _apply_rerank_stage(
    *,
    request: RetrievalRequest,
    record_map: dict[str, MemoryRecord],
    component_map: dict[str, list[ScoreComponent]],
    rerank_adapter: RerankAdapter | None,
    eligibility: _Eligibility,
    via_relations: dict[str, list[str]],
) -> None:
    if request.rerank is None:
        return
    for record_id, record in list(record_map.items()):
        if not eligibility.allows(record, "rerank"):
            _remove_record(record_id, record_map, component_map, via_relations)
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
    omissions: list[RetrievalOmission],
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
        omissions=omissions,
    )


__all__ = [
    "GraphStageOptions",
    "KeywordStageOptions",
    "RecencyStageOptions",
    "RerankAdapter",
    "RerankStageOptions",
    "RetrievalExplanation",
    "RetrievalEligibilityCallback",
    "RetrievalEligibilityDecision",
    "RetrievalHit",
    "RetrievalOmission",
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
