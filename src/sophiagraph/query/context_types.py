"""Public context assembly packet and retrieval-mode types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Final, Literal, Mapping, Sequence

from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.models import MemoryNamespace
from sophiagraph.query.community import CommunityQueryResult

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
    "community",
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
        "community",
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
FactLookup = Callable[[Sequence[str]], Mapping[str, Sequence[Mapping[str, Any]]]]
SummaryReferenceProvider = Callable[[Sequence[str]], Sequence[Mapping[str, Any]]]
CommunityQueryProvider = Callable[[ContextRequest], CommunityQueryResult]


__all__ = [
    "CONTEXT_ITEM_KINDS",
    "ContextBudget",
    "ContextItem",
    "ContextItemKind",
    "ContextPackage",
    "CommunityQueryProvider",
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
]
