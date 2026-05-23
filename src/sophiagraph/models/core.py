"""Compatibility re-export surface for durable-knowledge models."""

from __future__ import annotations

from sophiagraph.temporal import coerce_temporal_dt

from .candidate import CandidateReview, MemoryCandidate
from .namespace import MemoryNamespace, MemoryNamespaceComponent, MemoryScope
from .primitives import (
    CandidateStatus,
    MemoryRelationType,
    MemorySource,
    MemoryTier,
    MemoryTierTransitionReason,
    MemoryType,
    NamespaceKind,
    RecordVisibility,
    RelationDirection,
    Scope,
    ScopeKind,
    SessionSummaryOutcome,
    SessionSummaryThreadStatus,
    _SCOPE_PATTERN,
    _as_candidate_status,
    _as_claim_key_polarity,
    _as_memory_relation_type,
    _as_memory_relation_type_list,
    _as_memory_source,
    _as_memory_source_class,
    _as_memory_tier,
    _as_memory_tier_transition_reason,
    _as_memory_type,
    _as_memory_type_list,
    coerce_candidate_status,
    coerce_memory_relation_type,
    coerce_memory_source,
    coerce_memory_tier,
    coerce_memory_tier_transition_reason,
    coerce_memory_type,
)
from .record import (
    ArtifactRef,
    MemoryPatchResult,
    MemoryRecord,
    RetrievalFilters,
    SessionSummaryActiveThread,
    SessionSummaryContent,
)
from .relation import MemoryRelation
from .tier import MemoryTierTransition

_coerce_temporal_dt = coerce_temporal_dt

__all__ = [
    "ArtifactRef",
    "CandidateReview",
    "CandidateStatus",
    "MemoryCandidate",
    "MemoryNamespace",
    "MemoryNamespaceComponent",
    "MemoryPatchResult",
    "MemoryRecord",
    "MemoryRelation",
    "MemoryRelationType",
    "MemoryScope",
    "MemorySource",
    "MemoryTier",
    "MemoryTierTransition",
    "MemoryTierTransitionReason",
    "MemoryType",
    "NamespaceKind",
    "RecordVisibility",
    "RelationDirection",
    "RetrievalFilters",
    "Scope",
    "ScopeKind",
    "SessionSummaryActiveThread",
    "SessionSummaryContent",
    "SessionSummaryOutcome",
    "SessionSummaryThreadStatus",
    "_SCOPE_PATTERN",
    "_as_candidate_status",
    "_as_claim_key_polarity",
    "_as_memory_relation_type",
    "_as_memory_relation_type_list",
    "_as_memory_source",
    "_as_memory_source_class",
    "_as_memory_tier",
    "_as_memory_tier_transition_reason",
    "_as_memory_type",
    "_as_memory_type_list",
    "_coerce_temporal_dt",
    "coerce_candidate_status",
    "coerce_memory_relation_type",
    "coerce_memory_source",
    "coerce_memory_tier",
    "coerce_memory_tier_transition_reason",
    "coerce_memory_type",
]
