from __future__ import annotations

from pathlib import Path

import pytest

from sophiagraph import (
    ArtifactRef,
    CandidatePromotionPlan,
    CandidateQueueOptions,
    CandidateReviewDecision,
    MemoryCandidate,
    MemoryNamespace,
    SophiaGraphMemoryStore,
    SophiaGraphSqliteStore,
    apply_candidate_promotion_plan,
    apply_candidate_review,
    build_candidate_promotion_plan,
    list_candidate_queue,
)
from sophiagraph.contracts.errors import InvalidArgumentError


@pytest.fixture(params=["memory", "sqlite"])
def store(request, tmp_path: Path):
    if request.param == "memory":
        return SophiaGraphMemoryStore()
    return SophiaGraphSqliteStore(tmp_path / "review.sqlite3")


def _namespace() -> MemoryNamespace:
    return MemoryNamespace(agent_id="review", graph_id="main")


def _artifact(ref: str = "artifact://source-1") -> ArtifactRef:
    return ArtifactRef(ref=ref, mime="text/plain", sha256="a" * 64, size_bytes=12)


def _candidate(candidate_id: str, *, confidence: float = 0.8) -> MemoryCandidate:
    return MemoryCandidate(
        candidate_id=candidate_id,
        session_id="session-1",
        proposed_scope="agent:review",
        type="fact",
        content={"text": "explicitly supplied fact"},
        confidence=confidence,
        evidence_refs=[_artifact()],
        source_class="user_input",
        namespace=_namespace(),
        created_at="2026-06-23T10:00:00+00:00",
        updated_at="2026-06-23T10:00:00+00:00",
    )


def test_candidate_queue_filters_structurally(store) -> None:
    store.put_candidate(_candidate("cand-1", confidence=0.9))
    store.put_candidate(_candidate("cand-2", confidence=0.2))

    queue = list_candidate_queue(
        store,
        CandidateQueueOptions(
            status="proposed",
            min_confidence=0.5,
            source_class="user_input",
            require_evidence=True,
        ),
    )

    assert [item.candidate.candidate_id for item in queue] == ["cand-1"]
    assert queue[0].evidence_count == 1
    assert queue[0].namespace_key == "agent_id=review|graph_id=main"
    assert queue[0].reviewable is True


def test_candidate_review_records_decision_and_audit_event(store) -> None:
    events = []
    store.put_candidate(_candidate("cand-review"))

    updated = apply_candidate_review(
        store,
        CandidateReviewDecision(
            candidate_id="cand-review",
            action="approve",
            reviewer="alice",
            decided_at="2026-06-23T10:05:00+00:00",
            note="source checked",
        ),
        audit_recorder=events.append,
    )

    assert updated.status == "approved"
    assert updated.review is not None
    assert updated.review.reviewer == "alice"
    assert events[0].event_type == "memory.candidate_review.approve"
    assert events[0].details["candidate_id"] == "cand-review"


def test_candidate_promotion_requires_approval_and_evidence(store) -> None:
    store.put_candidate(_candidate("cand-promote"))
    with pytest.raises(InvalidArgumentError, match="approved"):
        build_candidate_promotion_plan(
            store,
            candidate_id="cand-promote",
            target_scope="agent:review",
            reviewer="alice",
        )

    apply_candidate_review(
        store,
        CandidateReviewDecision(
            candidate_id="cand-promote",
            action="approve",
            reviewer="alice",
        ),
    )
    plan = build_candidate_promotion_plan(
        store,
        candidate_id="cand-promote",
        target_scope="agent:review",
        reviewer="alice",
    )

    assert plan.evidence_refs == ("artifact://source-1",)


def test_apply_promotion_plan_reuses_store_promote_candidate(store) -> None:
    events = []
    store.put_candidate(_candidate("cand-apply"))
    apply_candidate_review(
        store,
        CandidateReviewDecision(
            candidate_id="cand-apply",
            action="approve",
            reviewer="alice",
        ),
    )
    plan = build_candidate_promotion_plan(
        store,
        candidate_id="cand-apply",
        target_scope="agent:review",
        reviewer="alice",
    )

    result = apply_candidate_promotion_plan(store, plan, audit_recorder=events.append)

    assert result.record_id
    assert store.get_record(result.record_id) is not None
    assert store.get_candidate("cand-apply").status == "promoted"  # type: ignore[union-attr]
    assert result.audit_events[0].event_type == "memory.candidate_review.promote"
    assert events[0].details["plan_id"] == plan.plan_id


def test_promotion_plan_rejects_evidence_not_on_candidate(store) -> None:
    store.put_candidate(_candidate("cand-bad-evidence"))
    apply_candidate_review(
        store,
        CandidateReviewDecision(
            candidate_id="cand-bad-evidence",
            action="approve",
            reviewer="alice",
        ),
    )
    plan = CandidatePromotionPlan(
        candidate_id="cand-bad-evidence",
        target_scope="agent:review",
        reviewer="alice",
        evidence_refs=("artifact://other",),
    )

    with pytest.raises(InvalidArgumentError, match="evidence_refs"):
        apply_candidate_promotion_plan(store, plan)
