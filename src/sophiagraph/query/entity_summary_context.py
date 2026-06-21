"""Deterministic context-block assembly over typed entity summaries."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Final, Literal, Mapping, Sequence

from sophiagraph.audit.policy import (
    PolicyDenialEvent,
    PolicyHookCallable,
    PolicyRequest,
    build_policy_denial_event,
    evaluate_policy_hooks,
)
from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.models import EntitySummary, MemoryNamespace
from sophiagraph.query.context_assembly import ContextBudget


SummaryContextOmissionReason = Literal[
    "not_found",
    "duplicate",
    "namespace_excluded",
    "invalidated",
    "hidden_by_visibility",
    "audit_only",
    "redacted_by_policy",
    "denied_by_policy_hook",
    "budget_exceeded",
]


SUMMARY_CONTEXT_OMISSION_REASONS: Final[frozenset[str]] = frozenset(
    {
        "not_found",
        "duplicate",
        "namespace_excluded",
        "invalidated",
        "hidden_by_visibility",
        "audit_only",
        "redacted_by_policy",
        "denied_by_policy_hook",
        "budget_exceeded",
    }
)


@dataclass(frozen=True)
class SummaryContextRequest:
    """One deterministic summary-context retrieval request."""

    summary_ids: list[str] = field(default_factory=list)
    entity_ids: list[str] = field(default_factory=list)
    namespaces: list[MemoryNamespace] | None = None
    include_invalidated: bool = False
    budget: ContextBudget = field(default_factory=ContextBudget)

    def __post_init__(self) -> None:
        if not self.summary_ids and not self.entity_ids:
            raise InvalidArgumentError(
                "summary context requires summary_ids or entity_ids"
            )
        if not isinstance(self.budget, ContextBudget):
            raise InvalidArgumentError("budget must be a ContextBudget")


@dataclass(frozen=True)
class SummaryContextItem:
    """One included summary block with evidence-bearing metadata."""

    summary_id: str
    entity_id: str
    namespace: MemoryNamespace
    summary_text: str
    authorship: str
    created_at: str
    updated_at: str
    source_record_ids: tuple[str, ...] = ()
    provenance: Mapping[str, Any] = field(default_factory=dict)
    detail: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.summary_id:
            raise InvalidArgumentError("summary_id is required")
        if not self.entity_id:
            raise InvalidArgumentError("entity_id is required")
        if not isinstance(self.namespace, MemoryNamespace):
            raise InvalidArgumentError("namespace must be a MemoryNamespace")
        if not isinstance(self.summary_text, str) or not self.summary_text:
            raise InvalidArgumentError("summary_text is required")


@dataclass(frozen=True)
class SummaryContextOmission:
    """One typed omission explanation for a skipped summary candidate."""

    summary_id: str
    entity_id: str | None
    reason: SummaryContextOmissionReason
    detail: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.summary_id:
            raise InvalidArgumentError("summary_id is required")
        if self.reason not in SUMMARY_CONTEXT_OMISSION_REASONS:
            raise InvalidArgumentError(f"invalid omission reason: {self.reason!r}")


@dataclass(frozen=True)
class SummaryContextResult:
    """The public summary-context packet."""

    items: list[SummaryContextItem]
    omitted: list[SummaryContextOmission] = field(default_factory=list)
    namespaces_applied: list[MemoryNamespace] | None = None
    denial_events: list[PolicyDenialEvent] = field(default_factory=list)
    request_provenance: Mapping[str, Any] = field(default_factory=dict)


def _matches_namespace(
    namespace: MemoryNamespace,
    filters: Sequence[MemoryNamespace] | None,
) -> bool:
    if not filters:
        return True
    return any(namespace.matches(item) for item in filters)


def _ordered_entity_summaries(
    rows: Sequence[EntitySummary],
) -> list[EntitySummary]:
    by_id = sorted(rows, key=lambda row: row.summary_id)
    by_created = sorted(by_id, key=lambda row: row.created_at or "", reverse=True)
    return sorted(
        by_created,
        key=lambda row: row.updated_at or row.created_at or "",
        reverse=True,
    )


def _policy_omission_reason(
    summary: EntitySummary,
) -> SummaryContextOmissionReason | None:
    policy = summary.privacy_policy
    if policy is None:
        return None
    if policy.retrieval_visibility == "hidden":
        return "hidden_by_visibility"
    if policy.retrieval_visibility == "audit_only":
        return "audit_only"
    if policy.retrieval_visibility == "redacted":
        return "redacted_by_policy"
    return None


def _build_item(
    summary: EntitySummary,
    *,
    max_chars: int | None,
) -> SummaryContextItem:
    text = summary.summary_text
    truncated = False
    if max_chars is not None and len(text) > max_chars:
        text = text[:max_chars]
        truncated = True
    return SummaryContextItem(
        summary_id=summary.summary_id,
        entity_id=summary.entity_id,
        namespace=summary.namespace,
        summary_text=text,
        authorship=summary.authorship,
        created_at=summary.created_at,
        updated_at=summary.updated_at,
        source_record_ids=tuple(summary.source_record_ids),
        provenance={
            "summary_id": summary.summary_id,
            "entity_id": summary.entity_id,
            "namespace": summary.namespace.as_dict(),
            "source_record_ids": list(summary.source_record_ids),
        },
        detail={
            "authorship": summary.authorship,
            "invalidated_at": summary.invalidated_at,
            "invalidation_reason": summary.invalidation_reason,
            "superseded_by_summary_id": summary.superseded_by_summary_id,
            "truncated": truncated,
        },
    )


def _evaluate_hooks(
    summary: EntitySummary,
    *,
    source_owner: str,
    hooks: Sequence[PolicyHookCallable],
) -> tuple[SummaryContextOmission | None, PolicyDenialEvent | None]:
    if not hooks:
        return None, None
    request = PolicyRequest(
        namespace=summary.namespace,
        surface="retrieval",
        source_owner=source_owner,
        target_kind="entity_summary",
        target_id=summary.summary_id,
        payload_kind="entity_summary",
        payload_meta={
            "entity_id": summary.entity_id,
            "authorship": summary.authorship,
            "source_record_ids": list(summary.source_record_ids),
            "privacy_policy": (
                summary.privacy_policy.to_dict()
                if summary.privacy_policy is not None
                else None
            ),
            "summary_meta": dict(summary.meta),
        },
    )
    decision = evaluate_policy_hooks(request, list(hooks))
    if decision.allowed:
        return None, None
    denial = build_policy_denial_event(request, decision)
    return (
        SummaryContextOmission(
            summary_id=summary.summary_id,
            entity_id=summary.entity_id,
            reason="denied_by_policy_hook",
            detail={
                "policy_id": decision.policy_id,
                "reason_code": decision.reason_code,
                "details": dict(decision.details),
            },
        ),
        denial,
    )


def assemble_entity_summary_context(
    store,
    request: SummaryContextRequest,
    *,
    source_owner: str = "sophiagraph",
    hooks: Sequence[PolicyHookCallable] = (),
) -> SummaryContextResult:
    """Build a deterministic context packet from caller-supplied summaries."""

    if not isinstance(request, SummaryContextRequest):
        raise InvalidArgumentError("request must be a SummaryContextRequest")

    items: list[SummaryContextItem] = []
    omitted: list[SummaryContextOmission] = []
    denial_events: list[PolicyDenialEvent] = []
    seen_summary_ids: set[str] = set()

    def process(
        summary: EntitySummary | None, *, requested_id: str | None = None
    ) -> None:
        summary_id = requested_id or (summary.summary_id if summary is not None else "")
        if summary is None:
            omitted.append(
                SummaryContextOmission(
                    summary_id=summary_id,
                    entity_id=None,
                    reason="not_found",
                )
            )
            return
        if summary.summary_id in seen_summary_ids:
            omitted.append(
                SummaryContextOmission(
                    summary_id=summary.summary_id,
                    entity_id=summary.entity_id,
                    reason="duplicate",
                )
            )
            return
        if not _matches_namespace(summary.namespace, request.namespaces):
            omitted.append(
                SummaryContextOmission(
                    summary_id=summary.summary_id,
                    entity_id=summary.entity_id,
                    reason="namespace_excluded",
                )
            )
            return
        if summary.is_invalidated and not request.include_invalidated:
            omitted.append(
                SummaryContextOmission(
                    summary_id=summary.summary_id,
                    entity_id=summary.entity_id,
                    reason="invalidated",
                    detail={
                        "invalidated_at": summary.invalidated_at,
                        "invalidation_reason": summary.invalidation_reason,
                        "superseded_by_summary_id": summary.superseded_by_summary_id,
                    },
                )
            )
            return
        policy_reason = _policy_omission_reason(summary)
        if policy_reason is not None:
            omitted.append(
                SummaryContextOmission(
                    summary_id=summary.summary_id,
                    entity_id=summary.entity_id,
                    reason=policy_reason,
                    detail={
                        "policy_id": (
                            summary.privacy_policy.policy_id
                            if summary.privacy_policy is not None
                            else None
                        ),
                        "decision_reason": (
                            summary.privacy_policy.decision_reason
                            if summary.privacy_policy is not None
                            else None
                        ),
                    },
                )
            )
            return
        hook_omission, denial = _evaluate_hooks(
            summary,
            source_owner=source_owner,
            hooks=hooks,
        )
        if hook_omission is not None:
            omitted.append(hook_omission)
            if denial is not None:
                denial_events.append(denial)
            return
        seen_summary_ids.add(summary.summary_id)
        items.append(
            _build_item(
                summary,
                max_chars=request.budget.max_record_chars,
            )
        )

    for summary_id in request.summary_ids:
        process(store.get_entity_summary(summary_id), requested_id=summary_id)

    for entity_id in request.entity_ids:
        rows = store.list_entity_summaries(
            entity_id=entity_id,
            namespaces=request.namespaces,
            include_invalidated=True,
        )
        for summary in _ordered_entity_summaries(rows):
            process(summary)

    if len(items) > request.budget.max_items:
        overflow = items[request.budget.max_items :]
        items = items[: request.budget.max_items]
        omitted.extend(
            SummaryContextOmission(
                summary_id=item.summary_id,
                entity_id=item.entity_id,
                reason="budget_exceeded",
                detail={"updated_at": item.updated_at},
            )
            for item in overflow
        )

    return SummaryContextResult(
        items=items,
        omitted=omitted,
        namespaces_applied=list(request.namespaces) if request.namespaces else None,
        denial_events=denial_events,
        request_provenance={
            "summary_ids": list(request.summary_ids),
            "entity_ids": list(request.entity_ids),
            "source_owner": source_owner,
            "include_invalidated": request.include_invalidated,
        },
    )


__all__ = [
    "SUMMARY_CONTEXT_OMISSION_REASONS",
    "SummaryContextItem",
    "SummaryContextOmission",
    "SummaryContextOmissionReason",
    "SummaryContextRequest",
    "SummaryContextResult",
    "assemble_entity_summary_context",
]
