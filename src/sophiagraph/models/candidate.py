"""Memory candidate and review DTOs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, get_args

from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.models.namespace import MemoryNamespace
from sophiagraph.models.primitives import (
    CandidateStatus,
    MemorySource,
    MemoryType,
    Scope,
    _as_claim_key_polarity,
    _as_memory_source_class,
    _assert_confidence,
    _assert_iterable,
    _assert_literal,
    _assert_scope,
)
from sophiagraph.models.record import ArtifactRef
from sophiagraph.trust.types import ClaimKeyPolarity, MemorySourceClass

MEMORY_CANDIDATE_STATUS_PROPOSED = "proposed"


@dataclass(frozen=True)
class CandidateReview:
    reviewer: str
    decided_at: str
    note: str | None = None

    def __post_init__(self) -> None:
        if not self.reviewer:
            raise InvalidArgumentError("reviewer is required")
        if not self.decided_at:
            raise InvalidArgumentError("decided_at is required")


@dataclass(frozen=True, slots=True)
class DelegatedCandidateProvenance:
    """Explicit lineage for a child proposal submitted by its parent host."""

    parent_agent_id: str
    child_agent_id: str
    parent_run_id: str
    child_run_id: str
    trace_parent_id: str
    grant_id: str
    workspace_id: str
    namespace: MemoryNamespace
    source_record_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        required = (
            self.parent_agent_id,
            self.child_agent_id,
            self.parent_run_id,
            self.child_run_id,
            self.trace_parent_id,
            self.grant_id,
            self.workspace_id,
        )
        if any(not value for value in required):
            raise InvalidArgumentError("delegated candidate provenance is incomplete")
        if not isinstance(self.namespace, MemoryNamespace):
            raise TypeError("provenance namespace must be MemoryNamespace")
        if any(not value for value in self.source_record_ids):
            raise InvalidArgumentError("source_record_ids cannot contain empty values")


def _assert_delegation_provenance(
    namespace: MemoryNamespace | None,
    provenance: DelegatedCandidateProvenance | None,
) -> None:
    if provenance is None:
        return
    if not isinstance(provenance, DelegatedCandidateProvenance):
        raise TypeError("delegation_provenance must be DelegatedCandidateProvenance")
    if namespace != provenance.namespace:
        raise InvalidArgumentError(
            "candidate namespace must match delegated provenance namespace"
        )


@dataclass(frozen=True)
class MemoryCandidate:
    candidate_id: str
    session_id: str
    proposed_scope: Scope
    type: MemoryType
    content: dict[str, Any] | str
    tags: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    source: MemorySource = "agent_inferred"
    confidence: float = 0.5
    evidence_refs: list[ArtifactRef] = field(default_factory=list)
    status: CandidateStatus = MEMORY_CANDIDATE_STATUS_PROPOSED
    key: str | None = None
    title: str | None = None
    review: CandidateReview | None = None
    meta: dict[str, Any] = field(default_factory=dict)
    namespace: MemoryNamespace | None = None
    claim_key: str | None = None
    polarity: ClaimKeyPolarity = "asserts"
    source_class: MemorySourceClass | None = None
    created_at: str | None = None
    updated_at: str | None = None
    delegation_provenance: DelegatedCandidateProvenance | None = None

    def __post_init__(self) -> None:
        if not self.candidate_id:
            raise InvalidArgumentError("candidate_id is required")
        if not self.session_id:
            raise InvalidArgumentError("session_id is required")
        _assert_scope(self.proposed_scope)
        _assert_literal(self.type, get_args(MemoryType), "type")
        _assert_literal(self.source, get_args(MemorySource), "source")
        _assert_literal(self.status, get_args(CandidateStatus), "status")
        _assert_confidence(self.confidence)
        if isinstance(self.content, str) and not self.content:
            raise InvalidArgumentError("content string must be non-empty")
        _assert_iterable(self.tags, "tags", str)
        _assert_iterable(self.entities, "entities", str)
        for ref in self.evidence_refs:
            if not isinstance(ref, ArtifactRef):
                raise TypeError(
                    "evidence_refs must contain ArtifactRef instances"
                )  # allow-bare-raise: defensive type guard in dataclass __post_init__
        if self.review and not isinstance(self.review, CandidateReview):
            raise TypeError(
                "review must be CandidateReview"
            )  # allow-bare-raise: defensive type guard in dataclass __post_init__
        if not isinstance(self.meta, dict):
            raise TypeError(
                "meta must be a dict"
            )  # allow-bare-raise: defensive type guard in dataclass __post_init__
        if self.namespace is not None and not isinstance(
            self.namespace, MemoryNamespace
        ):
            raise TypeError(
                "namespace must be MemoryNamespace"
            )  # allow-bare-raise: defensive type guard in dataclass __post_init__
        _assert_delegation_provenance(self.namespace, self.delegation_provenance)
        _assert_literal(self.polarity, get_args(ClaimKeyPolarity), "polarity")
        resolved_meta = dict(self.meta)
        resolved_claim_key = self.claim_key
        meta_claim_key = resolved_meta.get("claim_key")
        if meta_claim_key is not None:
            meta_claim_key = str(meta_claim_key).strip()
            if resolved_claim_key is None:
                resolved_claim_key = str(meta_claim_key)
            elif str(resolved_claim_key).strip() != meta_claim_key:
                raise InvalidArgumentError("claim_key conflicts with meta claim_key")
        if resolved_claim_key is not None:
            resolved_claim_key = str(resolved_claim_key).strip()
            if not resolved_claim_key:
                raise InvalidArgumentError("claim_key must be non-empty when set")
            resolved_meta["claim_key"] = resolved_claim_key

        resolved_polarity = self.polarity
        meta_polarity = resolved_meta.get("polarity")
        if meta_polarity is not None:
            meta_polarity = _as_claim_key_polarity(str(meta_polarity))
            if self.polarity != "asserts" and self.polarity != meta_polarity:
                raise InvalidArgumentError("polarity conflicts with meta polarity")
            if self.polarity == "asserts":
                resolved_polarity = meta_polarity
        _assert_literal(
            resolved_polarity,
            get_args(ClaimKeyPolarity),
            "polarity",
        )
        resolved_meta["polarity"] = resolved_polarity

        resolved_source_class = self.source_class
        meta_source_class = resolved_meta.get("source_class")
        if meta_source_class is not None:
            meta_source_class = _as_memory_source_class(str(meta_source_class))
            if (
                resolved_source_class is not None
                and resolved_source_class != meta_source_class
            ):
                raise InvalidArgumentError(
                    "source_class conflicts with meta source_class"
                )
            if resolved_source_class is None:
                resolved_source_class = meta_source_class
        if resolved_source_class is not None:
            _assert_literal(
                resolved_source_class,
                get_args(MemorySourceClass),
                "source_class",
            )
            resolved_meta["source_class"] = resolved_source_class

        object.__setattr__(self, "claim_key", resolved_claim_key)
        object.__setattr__(self, "polarity", resolved_polarity)
        object.__setattr__(self, "source_class", resolved_source_class)
        object.__setattr__(self, "meta", resolved_meta)


__all__ = ["CandidateReview", "DelegatedCandidateProvenance", "MemoryCandidate"]
