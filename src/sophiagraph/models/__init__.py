"""Canonical durable-knowledge models and helpers."""

from .block import (
    MEMORY_BLOCK_DEFERRED_MODES,
    MEMORY_BLOCK_V1_CLASS_ALLOWLIST,
    MEMORY_BLOCK_V1_MODES,
    MemoryBlock,
    MemoryBlockClass,
    MemoryBlockMode,
    validate_block_for_creation,
)
from .candidate import CandidateReview, MemoryCandidate
from .change import (
    ChangeObjectType,
    ChangeOperation,
    SophiaGraphChangeEvent,
    default_change_namespace,
)
from .document import (
    DocumentBlockType,
    DocumentSourceFormat,
    KnowledgeDocument,
    KnowledgeDocumentBlock,
    content_hash,
)
from .embedding import MemoryEmbedding, memory_embedding_from_dict
from .link import (
    ContextUnit,
    ExplicitLinkResolver,
    LinkKind,
    LinkResolution,
    LinkResolutionCandidate,
    LinkResolutionDiagnostic,
    LinkResolutionStatus,
    StructuralLink,
    normalize_link_target,
    split_target_parts,
)
from .namespace import MemoryNamespace, MemoryNamespaceComponent, MemoryScope
from . import primitives as _primitive_models
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
from . import record as _record_models
from .relation import MemoryRelation
from .tier import MemoryTierTransition

_SCOPE_PATTERN = _primitive_models._SCOPE_PATTERN
_as_candidate_status = _primitive_models._as_candidate_status
_as_claim_key_polarity = _primitive_models._as_claim_key_polarity
_as_memory_relation_type = _primitive_models._as_memory_relation_type
_as_memory_relation_type_list = _primitive_models._as_memory_relation_type_list
_as_memory_source = _primitive_models._as_memory_source
_as_memory_source_class = _primitive_models._as_memory_source_class
_as_memory_tier = _primitive_models._as_memory_tier
_as_memory_tier_transition_reason = _primitive_models._as_memory_tier_transition_reason
_as_memory_type = _primitive_models._as_memory_type
_as_memory_type_list = _primitive_models._as_memory_type_list
_coerce_temporal_dt = _record_models._coerce_temporal_dt

__all__ = [
    "ArtifactRef",
    "CandidateReview",
    "CandidateStatus",
    "MEMORY_BLOCK_DEFERRED_MODES",
    "MEMORY_BLOCK_V1_CLASS_ALLOWLIST",
    "MEMORY_BLOCK_V1_MODES",
    "MemoryBlock",
    "MemoryBlockClass",
    "MemoryBlockMode",
    "validate_block_for_creation",
    "ChangeObjectType",
    "ChangeOperation",
    "ContextUnit",
    "DocumentBlockType",
    "DocumentSourceFormat",
    "ExplicitLinkResolver",
    "KnowledgeDocument",
    "KnowledgeDocumentBlock",
    "LinkKind",
    "LinkResolution",
    "LinkResolutionCandidate",
    "LinkResolutionDiagnostic",
    "LinkResolutionStatus",
    "MemoryCandidate",
    "MemoryEmbedding",
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
    "StructuralLink",
    "SophiaGraphChangeEvent",
    "default_change_namespace",
    "memory_embedding_from_dict",
    "coerce_candidate_status",
    "coerce_memory_relation_type",
    "coerce_memory_source",
    "coerce_memory_tier",
    "coerce_memory_tier_transition_reason",
    "coerce_memory_type",
    "content_hash",
    "normalize_link_target",
    "split_target_parts",
]
