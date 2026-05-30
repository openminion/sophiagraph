"""Evidence-bearing context package assembly for retrieval modes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Final, Literal, Mapping, Sequence

from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.models import MemoryNamespace


RetrievalMode = Literal[
    "local_graph",
    "structural_search",
    "temporal_fact",
    "hybrid",
    "global",
    "drift",
]


RETRIEVAL_MODES: Final[frozenset[str]] = frozenset(
    {
        "local_graph",
        "structural_search",
        "temporal_fact",
        "hybrid",
        "global",
        "drift",
    }
)


ContextItemKind = Literal[
    "record",
    "memory_block",
    "fact",
    "raw_episode",
    "graph_path",
    "summary_reference",
    "drift_step",
]


CONTEXT_ITEM_KINDS: Final[frozenset[str]] = frozenset(
    {
        "record",
        "memory_block",
        "fact",
        "raw_episode",
        "graph_path",
        "summary_reference",
        "drift_step",
    }
)


OmissionReason = Literal[
    "budget_exceeded",
    "duplicate",
    "namespace_excluded",
    "filter_excluded",
    "below_threshold",
    "adapter_omitted",
]


OMISSION_REASONS: Final[frozenset[str]] = frozenset(
    {
        "budget_exceeded",
        "duplicate",
        "namespace_excluded",
        "filter_excluded",
        "below_threshold",
        "adapter_omitted",
    }
)


@dataclass(frozen=True)
class LocalGraphMode:
    """Start from seed records, traverse bounded neighborhood."""

    seed_record_ids: list[str]
    depth: int = 1
    relation_types: list[str] | None = None
    max_paths: int = 20

    def __post_init__(self) -> None:
        if not self.seed_record_ids:
            raise InvalidArgumentError("local_graph requires seed_record_ids")
        if self.depth < 0:
            raise InvalidArgumentError("local_graph depth must be >= 0")
        if self.max_paths <= 0:
            raise InvalidArgumentError("local_graph max_paths must be positive")


@dataclass(frozen=True)
class StructuralSearchMode:
    """Query explicit text/property/path filters via upstream search."""

    query: str
    limit: int = 50

    def __post_init__(self) -> None:
        if not self.query:
            raise InvalidArgumentError("structural_search query is required")
        if self.limit <= 0:
            raise InvalidArgumentError("structural_search limit must be positive")


@dataclass(frozen=True)
class TemporalFactMode:
    """Query active/historical facts with validity filters."""

    subject_entity_id: str | None = None
    predicate: str | None = None
    valid_at: str | None = None
    learned_at: str | None = None
    active_state: str = "active"
    source_episode_id: str | None = None
    limit: int = 50

    def __post_init__(self) -> None:
        if self.limit <= 0:
            raise InvalidArgumentError("temporal_fact limit must be positive")
        if self.active_state not in {"active", "historical", "all"}:
            raise InvalidArgumentError(
                f"temporal_fact active_state {self.active_state!r} not in "
                "{'active', 'historical', 'all'}"
            )


@dataclass(frozen=True)
class HybridMode:
    """Combine structural, optional vector, and graph candidates."""

    seed_query: str
    hybrid_options: Mapping[str, Any] = field(default_factory=dict)
    limit: int = 30

    def __post_init__(self) -> None:
        if not self.seed_query:
            raise InvalidArgumentError("hybrid seed_query is required")
        if self.limit <= 0:
            raise InvalidArgumentError("hybrid limit must be positive")


@dataclass(frozen=True)
class GlobalMode:
    """Consume caller-supplied summary references; never generates them."""

    summary_record_ids: list[str]
    related_filter: Mapping[str, Any] = field(default_factory=dict)
    limit: int = 20

    def __post_init__(self) -> None:
        if not self.summary_record_ids:
            raise InvalidArgumentError(
                "global mode requires caller-supplied summary_record_ids"
            )
        if self.limit <= 0:
            raise InvalidArgumentError("global limit must be positive")


@dataclass(frozen=True)
class DriftStepInput:
    """One caller-supplied refinement step in a drift retrieval loop."""

    step_id: str
    seed_record_id: str
    note: str = ""

    def __post_init__(self) -> None:
        if not self.step_id:
            raise InvalidArgumentError("drift step_id is required")
        if not self.seed_record_id:
            raise InvalidArgumentError("drift seed_record_id is required")


@dataclass(frozen=True)
class DriftMode:
    """Caller-supplied refinement loop over local searches."""

    initial_summary_record_ids: list[str]
    refinement_steps: list[DriftStepInput] = field(default_factory=list)
    limit: int = 30

    def __post_init__(self) -> None:
        if not self.initial_summary_record_ids:
            raise InvalidArgumentError(
                "drift mode requires caller-supplied initial_summary_record_ids"
            )
        if self.limit <= 0:
            raise InvalidArgumentError("drift limit must be positive")


@dataclass(frozen=True)
class ContextBudget:
    """Per-package budget controls."""

    max_items: int = 50
    max_record_chars: int | None = None

    def __post_init__(self) -> None:
        if self.max_items <= 0:
            raise InvalidArgumentError("max_items must be positive")
        if self.max_record_chars is not None and self.max_record_chars <= 0:
            raise InvalidArgumentError("max_record_chars must be positive")


@dataclass(frozen=True)
class ContextRequest:
    """One typed retrieval+assembly request."""

    scopes: list[str]
    mode: str
    namespaces: list[MemoryNamespace] | None = None
    local_graph: LocalGraphMode | None = None
    structural_search: StructuralSearchMode | None = None
    temporal_fact: TemporalFactMode | None = None
    hybrid: HybridMode | None = None
    global_mode: GlobalMode | None = None
    drift: DriftMode | None = None
    budget: ContextBudget = field(default_factory=ContextBudget)

    def __post_init__(self) -> None:
        if not self.scopes:
            raise InvalidArgumentError("context request requires scopes")
        if self.mode not in RETRIEVAL_MODES:
            raise InvalidArgumentError(f"unsupported retrieval mode: {self.mode!r}")
        # Each mode requires its matching options object.
        attr = "global_mode" if self.mode == "global" else self.mode
        if getattr(self, attr) is None:
            raise InvalidArgumentError(
                f"mode {self.mode!r} requires {attr!r} options to be set"
            )


@dataclass(frozen=True)
class ItemScore:
    """One score component per upstream stage that ranked this item."""

    source: str
    value: float
    detail: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GraphPathEvidence:
    """A structural path tying items together (record-id endpoints)."""

    nodes: list[str]
    edges: list[str]
    relation_types: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ContextItem:
    """One evidence-bearing item in the context package."""

    item_id: str
    kind: ContextItemKind
    payload: Mapping[str, Any]
    scores: list[ItemScore] = field(default_factory=list)
    snippet: str = ""
    excerpt_bounds: tuple[int, int] | None = None
    provenance: Mapping[str, Any] = field(default_factory=dict)
    via_paths: list[GraphPathEvidence] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.item_id:
            raise InvalidArgumentError("ContextItem.item_id is required")
        if self.kind not in CONTEXT_ITEM_KINDS:
            raise InvalidArgumentError(f"unknown context item kind: {self.kind!r}")
        if not isinstance(self.payload, Mapping):
            raise InvalidArgumentError("payload must be Mapping[str, Any]")

    @property
    def final_score(self) -> float:
        return sum(component.value for component in self.scores)


@dataclass(frozen=True)
class OmittedDiagnostic:
    """One omitted candidate explanation."""

    item_id: str
    kind: ContextItemKind
    reason: OmissionReason
    detail: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.reason not in OMISSION_REASONS:
            raise InvalidArgumentError(f"unknown omission reason: {self.reason!r}")


@dataclass(frozen=True)
class ContextPackage:
    """The public evidence-bearing context package."""

    mode: RetrievalMode
    items: list[ContextItem]
    omitted: list[OmittedDiagnostic] = field(default_factory=list)
    namespaces_applied: list[MemoryNamespace] | None = None
    request_provenance: Mapping[str, Any] = field(default_factory=dict)
    drift_steps_recorded: list[Mapping[str, Any]] = field(default_factory=list)


VectorScoreLookup = Callable[[Sequence[str]], Mapping[str, float]]
"""Caller-supplied lookup mapping record ID to vector score."""


FactLookup = Callable[[Sequence[str]], Mapping[str, Sequence[Mapping[str, Any]]]]
"""Caller-supplied lookup mapping record ID to related fact rows."""


SummaryReferenceProvider = Callable[[Sequence[str]], Sequence[Mapping[str, Any]]]
"""Caller-supplied global summary reference fetcher."""


def _record_to_item(
    record,
    *,
    scope: str,
    score_source: str,
    raw_score: float,
    snippet_bounds: int | None = None,
) -> ContextItem:
    content_str = (
        record.content if isinstance(record.content, str) else str(record.content)
    )
    if snippet_bounds is not None and len(content_str) > snippet_bounds:
        snippet = content_str[:snippet_bounds]
        bounds = (0, snippet_bounds)
    else:
        snippet = content_str
        bounds = (0, len(content_str))
    return ContextItem(
        item_id=record.id,
        kind="record",
        payload={
            "id": record.id,
            "scope": record.scope,
            "type": str(record.type),
            "title": record.title,
            "tags": list(record.tags),
            "source": str(record.source),
            "updated_at": record.updated_at,
        },
        scores=[
            ItemScore(
                source=score_source,
                value=float(raw_score),
                detail={"scope": scope},
            )
        ],
        snippet=snippet,
        excerpt_bounds=bounds,
        provenance={
            "record_id": record.id,
            "scope": record.scope,
            "namespace": record.effective_namespace.as_dict(),
            "source": str(record.source),
        },
    )


def _apply_budget(
    items: list[ContextItem],
    *,
    max_items: int,
) -> tuple[list[ContextItem], list[OmittedDiagnostic]]:
    if len(items) <= max_items:
        return items, []
    kept = items[:max_items]
    overflow = items[max_items:]
    omitted = [
        OmittedDiagnostic(
            item_id=item.item_id,
            kind=item.kind,
            reason="budget_exceeded",
            detail={"final_score": item.final_score},
        )
        for item in overflow
    ]
    return kept, omitted


def _assemble_local_graph(store, request: ContextRequest) -> ContextPackage:
    mode = request.local_graph
    assert mode is not None
    items: list[ContextItem] = []
    paths_by_seed: dict[str, list[GraphPathEvidence]] = {}
    record_ids_seen: set[str] = set()

    # Seeds.
    for seed_id in mode.seed_record_ids:
        seed = store.get_record(seed_id)
        if seed is None:
            continue
        items.append(
            _record_to_item(
                seed,
                scope="seed",
                score_source="local_graph_seed",
                raw_score=1.0,
                snippet_bounds=request.budget.max_record_chars,
            )
        )
        record_ids_seen.add(seed.id)

    # Neighborhood.
    for seed_id in mode.seed_record_ids:
        try:
            relations = store.list_relations(
                seed_id,
                direction="both",
                relation_types=mode.relation_types,
                limit=mode.max_paths,
            )
        except Exception:
            continue
        for relation in relations:
            neighbor_id = (
                relation.target_record_id
                if relation.source_record_id == seed_id
                else relation.source_record_id
            )
            if not neighbor_id or neighbor_id in record_ids_seen:
                paths_by_seed.setdefault(neighbor_id or "", []).append(
                    GraphPathEvidence(
                        nodes=[seed_id, neighbor_id or ""],
                        edges=[relation.relation_id],
                        relation_types=[str(relation.relation_type)],
                    )
                )
                continue
            neighbor = store.get_record(neighbor_id)
            if neighbor is None:
                continue
            item = _record_to_item(
                neighbor,
                scope="neighbor",
                score_source="local_graph_neighbor",
                raw_score=0.5,
                snippet_bounds=request.budget.max_record_chars,
            )
            # Attach the path that brought us here.
            item = ContextItem(
                item_id=item.item_id,
                kind=item.kind,
                payload=item.payload,
                scores=item.scores,
                snippet=item.snippet,
                excerpt_bounds=item.excerpt_bounds,
                provenance=item.provenance,
                via_paths=[
                    GraphPathEvidence(
                        nodes=[seed_id, neighbor_id],
                        edges=[relation.relation_id],
                        relation_types=[str(relation.relation_type)],
                    )
                ],
            )
            items.append(item)
            record_ids_seen.add(neighbor_id)

    items, omitted = _apply_budget(items, max_items=request.budget.max_items)
    return ContextPackage(
        mode="local_graph",
        items=items,
        omitted=omitted,
        namespaces_applied=request.namespaces,
        request_provenance={
            "mode": "local_graph",
            "seeds": list(mode.seed_record_ids),
            "depth": mode.depth,
        },
    )


def _assemble_structural_search(store, request: ContextRequest) -> ContextPackage:
    mode = request.structural_search
    assert mode is not None
    from sophiagraph.query import SearchQueryOptions

    records = store.search_records(
        SearchQueryOptions(
            query=mode.query,
            scopes=request.scopes,
            namespaces=request.namespaces,
            limit=mode.limit,
        )
    )
    items: list[ContextItem] = []
    for index, record in enumerate(records):
        raw_score = max(0.0, 1.0 - (index / max(1, mode.limit)))
        items.append(
            _record_to_item(
                record,
                scope="keyword_hit",
                score_source="structural_search",
                raw_score=raw_score,
                snippet_bounds=request.budget.max_record_chars,
            )
        )
    items, omitted = _apply_budget(items, max_items=request.budget.max_items)
    return ContextPackage(
        mode="structural_search",
        items=items,
        omitted=omitted,
        namespaces_applied=request.namespaces,
        request_provenance={
            "mode": "structural_search",
            "query": mode.query,
        },
    )


def _assemble_temporal_fact(store, request: ContextRequest) -> ContextPackage:
    mode = request.temporal_fact
    assert mode is not None
    facts = store.list_facts(
        namespaces=request.namespaces,
        subject_entity_id=mode.subject_entity_id,
        predicate=mode.predicate,
        valid_at=mode.valid_at,
        learned_at=mode.learned_at,
        active_state=mode.active_state,
        source_episode_id=mode.source_episode_id,
        limit=mode.limit,
    )
    items: list[ContextItem] = []
    for fact in facts:
        items.append(
            ContextItem(
                item_id=fact.fact_id,
                kind="fact",
                payload={
                    "fact_id": fact.fact_id,
                    "predicate": fact.predicate,
                    "subject_entity_id": fact.subject_entity_id,
                    "object_entity_id": fact.object_entity_id,
                    "object_literal": fact.object_literal,
                    "valid_from": fact.valid_from,
                    "valid_to": fact.valid_to,
                    "observed_at": fact.observed_at,
                    "invalidated_at": fact.invalidated_at,
                    "superseded_by_fact_id": fact.superseded_by_fact_id,
                    "source_episode_ids": list(fact.source_episode_ids),
                },
                scores=[
                    ItemScore(
                        source="temporal_fact",
                        value=float(fact.confidence),
                        detail={"active_state": mode.active_state},
                    )
                ],
                provenance={
                    "fact_id": fact.fact_id,
                    "namespace": fact.namespace.as_dict(),
                    "source_episode_ids": list(fact.source_episode_ids),
                },
            )
        )
    items, omitted = _apply_budget(items, max_items=request.budget.max_items)
    return ContextPackage(
        mode="temporal_fact",
        items=items,
        omitted=omitted,
        namespaces_applied=request.namespaces,
        request_provenance={
            "mode": "temporal_fact",
            "active_state": mode.active_state,
            "valid_at": mode.valid_at,
            "learned_at": mode.learned_at,
        },
    )


def _assemble_hybrid(
    store,
    request: ContextRequest,
    *,
    vector_score_lookup: VectorScoreLookup | None,
    fact_lookup: FactLookup | None,
) -> ContextPackage:
    mode = request.hybrid
    assert mode is not None
    from sophiagraph.query import SearchQueryOptions

    records = store.search_records(
        SearchQueryOptions(
            query=mode.seed_query,
            scopes=request.scopes,
            namespaces=request.namespaces,
            limit=mode.limit,
        )
    )
    items: list[ContextItem] = []
    record_ids = [record.id for record in records]
    vector_scores = vector_score_lookup(record_ids) if vector_score_lookup else {}
    for index, record in enumerate(records):
        keyword_score = max(0.0, 1.0 - (index / max(1, mode.limit)))
        scores = [
            ItemScore(
                source="structural_search",
                value=keyword_score,
                detail={"rank": index},
            )
        ]
        vec = vector_scores.get(record.id)
        if vec is not None:
            scores.append(
                ItemScore(
                    source="vector_adapter",
                    value=float(vec),
                    detail={"caller_supplied": True},
                )
            )
        item = _record_to_item(
            record,
            scope="hybrid_hit",
            score_source="structural_search",
            raw_score=keyword_score,
            snippet_bounds=request.budget.max_record_chars,
        )
        item = ContextItem(
            item_id=item.item_id,
            kind=item.kind,
            payload=item.payload,
            scores=scores,
            snippet=item.snippet,
            excerpt_bounds=item.excerpt_bounds,
            provenance=item.provenance,
        )
        items.append(item)

    if fact_lookup is not None:
        fact_lookups = fact_lookup(record_ids)
        for record_id, facts in fact_lookups.items():
            for fact_payload in facts:
                fact_id = str(
                    fact_payload.get("fact_id") or fact_payload.get("id") or ""
                )
                if not fact_id:
                    continue
                items.append(
                    ContextItem(
                        item_id=fact_id,
                        kind="fact",
                        payload=dict(fact_payload),
                        scores=[
                            ItemScore(
                                source="temporal_adapter",
                                value=float(fact_payload.get("confidence", 0.5)),
                                detail={"caller_supplied": True},
                            )
                        ],
                        provenance={"fact_id": fact_id, "via_record_id": record_id},
                    )
                )

    # Sort by aggregated score before truncation.
    items.sort(key=lambda i: -i.final_score)
    items, omitted = _apply_budget(items, max_items=request.budget.max_items)
    return ContextPackage(
        mode="hybrid",
        items=items,
        omitted=omitted,
        namespaces_applied=request.namespaces,
        request_provenance={
            "mode": "hybrid",
            "seed_query": mode.seed_query,
            "vector_adapter_attached": vector_score_lookup is not None,
            "fact_adapter_attached": fact_lookup is not None,
        },
    )


def _assemble_global(
    store,
    request: ContextRequest,
    *,
    summary_provider: SummaryReferenceProvider | None,
) -> ContextPackage:
    mode = request.global_mode
    assert mode is not None
    items: list[ContextItem] = []
    summary_payloads: Sequence[Mapping[str, Any]] = []
    if summary_provider is not None:
        summary_payloads = summary_provider(mode.summary_record_ids)
    else:
        # Default: fetch records by id from the store.
        summary_payloads = [
            {
                "summary_id": sid,
                "record_id": sid,
                "title": (
                    store.get_record(sid).title
                    if store.get_record(sid) is not None
                    else None
                ),
            }
            for sid in mode.summary_record_ids
        ]
    for entry in summary_payloads:
        summary_id = str(entry.get("summary_id") or entry.get("record_id") or "")
        if not summary_id:
            continue
        items.append(
            ContextItem(
                item_id=summary_id,
                kind="summary_reference",
                payload=dict(entry),
                scores=[
                    ItemScore(
                        source="global_summary",
                        value=1.0,
                        detail={"caller_supplied": True},
                    )
                ],
                provenance={
                    "summary_id": summary_id,
                    "caller_supplied": True,
                },
            )
        )
    items, omitted = _apply_budget(items, max_items=request.budget.max_items)
    return ContextPackage(
        mode="global",
        items=items,
        omitted=omitted,
        namespaces_applied=request.namespaces,
        request_provenance={
            "mode": "global",
            "summary_record_ids": list(mode.summary_record_ids),
            "summary_provider_attached": summary_provider is not None,
        },
    )


def _assemble_drift(
    store,
    request: ContextRequest,
    *,
    summary_provider: SummaryReferenceProvider | None,
) -> ContextPackage:
    mode = request.drift
    assert mode is not None
    items: list[ContextItem] = []
    drift_steps: list[Mapping[str, Any]] = []
    # Seed with caller-supplied initial summaries.
    summary_payloads: Sequence[Mapping[str, Any]] = []
    if summary_provider is not None:
        summary_payloads = summary_provider(mode.initial_summary_record_ids)
    else:
        summary_payloads = [
            {
                "summary_id": sid,
                "record_id": sid,
                "title": (
                    store.get_record(sid).title
                    if store.get_record(sid) is not None
                    else None
                ),
            }
            for sid in mode.initial_summary_record_ids
        ]
    for entry in summary_payloads:
        summary_id = str(entry.get("summary_id") or entry.get("record_id") or "")
        if not summary_id:
            continue
        items.append(
            ContextItem(
                item_id=summary_id,
                kind="summary_reference",
                payload=dict(entry),
                scores=[
                    ItemScore(
                        source="drift_initial_summary",
                        value=1.0,
                        detail={"caller_supplied": True},
                    )
                ],
                provenance={"summary_id": summary_id, "caller_supplied": True},
            )
        )
    # Record each drift step.
    for step in mode.refinement_steps:
        record = store.get_record(step.seed_record_id)
        record_provenance: Mapping[str, Any] = {
            "step_id": step.step_id,
            "seed_record_id": step.seed_record_id,
            "note": step.note,
        }
        drift_steps.append(record_provenance)
        if record is not None:
            items.append(
                ContextItem(
                    item_id=f"drift-{step.step_id}",
                    kind="drift_step",
                    payload={
                        "step_id": step.step_id,
                        "record_id": record.id,
                        "title": record.title,
                        "scope": record.scope,
                    },
                    scores=[
                        ItemScore(
                            source="drift_refinement",
                            value=0.5,
                            detail={"caller_supplied": True},
                        )
                    ],
                    provenance=record_provenance,
                )
            )
    items, omitted = _apply_budget(items, max_items=request.budget.max_items)
    return ContextPackage(
        mode="drift",
        items=items,
        omitted=omitted,
        namespaces_applied=request.namespaces,
        request_provenance={
            "mode": "drift",
            "initial_summary_record_ids": list(mode.initial_summary_record_ids),
            "summary_provider_attached": summary_provider is not None,
        },
        drift_steps_recorded=drift_steps,
    )


def assemble_context(
    store,
    request: ContextRequest,
    *,
    vector_score_lookup: VectorScoreLookup | None = None,
    fact_lookup: FactLookup | None = None,
    summary_provider: SummaryReferenceProvider | None = None,
) -> ContextPackage:
    """Build the public context package for ``request``."""

    if request.mode == "local_graph":
        return _assemble_local_graph(store, request)
    if request.mode == "structural_search":
        return _assemble_structural_search(store, request)
    if request.mode == "temporal_fact":
        return _assemble_temporal_fact(store, request)
    if request.mode == "hybrid":
        return _assemble_hybrid(
            store,
            request,
            vector_score_lookup=vector_score_lookup,
            fact_lookup=fact_lookup,
        )
    if request.mode == "global":
        return _assemble_global(
            store,
            request,
            summary_provider=summary_provider,
        )
    if request.mode == "drift":
        return _assemble_drift(
            store,
            request,
            summary_provider=summary_provider,
        )
    raise InvalidArgumentError(f"mode {request.mode!r} not handled by assembler")


__all__ = [
    "CONTEXT_ITEM_KINDS",
    "ContextBudget",
    "ContextItem",
    "ContextItemKind",
    "ContextPackage",
    "ContextRequest",
    "DriftMode",
    "DriftStepInput",
    "FactLookup",
    "GlobalMode",
    "GraphPathEvidence",
    "HybridMode",
    "ItemScore",
    "LocalGraphMode",
    "OMISSION_REASONS",
    "OmissionReason",
    "OmittedDiagnostic",
    "RETRIEVAL_MODES",
    "RetrievalMode",
    "StructuralSearchMode",
    "SummaryReferenceProvider",
    "TemporalFactMode",
    "VectorScoreLookup",
    "assemble_context",
]
