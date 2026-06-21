from __future__ import annotations

import pytest

import sophiagraph
from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.models import (
    MemoryAttributionUpdate,
    MemoryCandidate,
    MemoryContradictionLink,
    MemoryEvidenceLink,
    MemoryNamespace,
    SelfImprovingMemoryLifecycle,
    apply_attribution_update,
    attach_contradiction,
    build_memory_retrieval_packet,
    lifecycle_from_candidate,
    transition_lifecycle,
)


def _candidate() -> MemoryCandidate:
    return MemoryCandidate(
        candidate_id="cand-1",
        session_id="session-1",
        proposed_scope="agent:self-improve",
        type="strategy_outcome",
        content={"text": "Prefer evidence-backed cleanup plans."},
        source="validated",
        confidence=0.55,
        namespace=MemoryNamespace(agent_id="self-improve", session_id="session-1"),
    )


def _pragma_ref(state: str = "fresh") -> MemoryEvidenceLink:
    return MemoryEvidenceLink(
        ref_uri="pragma://repo/memory-evidence/snapshot/node",
        freshness_state=state,
        reason_codes=("source_fact",),
    )


def test_lifecycle_models_validate_enum_safety_and_round_trip() -> None:
    lifecycle = lifecycle_from_candidate(
        _candidate(),
        memory_id="mem-1",
        kind="strategy_outcome",
        evidence_refs=(_pragma_ref(),),
    )
    restored = SelfImprovingMemoryLifecycle.from_dict(lifecycle.to_dict())

    assert restored == lifecycle
    assert lifecycle.trust_state == "candidate"
    assert lifecycle.pragma_refs == ("pragma://repo/memory-evidence/snapshot/node",)
    assert "SelfImprovingMemoryLifecycle" in sophiagraph.__all__
    assert sophiagraph.SelfImprovingMemoryLifecycle is SelfImprovingMemoryLifecycle

    with pytest.raises(InvalidArgumentError, match="invalid kind"):
        lifecycle_from_candidate(_candidate(), memory_id="bad", kind="fact")
    with pytest.raises(InvalidArgumentError, match="invalid freshness_state"):
        _pragma_ref("speculative")


def test_candidate_provisional_trusted_pinned_suppressed_and_superseded_transitions() -> (
    None
):
    lifecycle = lifecycle_from_candidate(
        _candidate(),
        memory_id="mem-1",
        kind="strategy_outcome",
        evidence_refs=(_pragma_ref(),),
    )
    provisional = transition_lifecycle(
        lifecycle,
        to_state="provisional",
        reason_code="reviewed_supporting_evidence",
        actor="reviewer",
        observed_at="2026-06-20T00:00:00+00:00",
    )
    trusted = transition_lifecycle(
        provisional,
        to_state="trusted",
        reason_code="positive_attribution_repeated",
        actor="reviewer",
        observed_at="2026-06-20T00:01:00+00:00",
    )
    pinned = transition_lifecycle(
        trusted,
        to_state="pinned",
        reason_code="operator_pin",
        actor="operator",
        observed_at="2026-06-20T00:02:00+00:00",
    )
    unpinned = transition_lifecycle(
        pinned,
        to_state="trusted",
        reason_code="operator_unpin",
        actor="operator",
        observed_at="2026-06-20T00:03:00+00:00",
    )
    suppressed = transition_lifecycle(
        unpinned,
        to_state="suppressed",
        reason_code="harmful_outcome",
        actor="reviewer",
        observed_at="2026-06-20T00:04:00+00:00",
        suppression_reason="harmful_outcome",
    )

    assert [event.to_state for event in suppressed.history] == [
        "provisional",
        "trusted",
        "pinned",
        "trusted",
        "suppressed",
    ]
    assert suppressed.trust_score == 0.0
    with pytest.raises(InvalidArgumentError, match="invalid lifecycle transition"):
        transition_lifecycle(
            suppressed,
            to_state="trusted",
            reason_code="terminal_reopen_not_allowed",
            actor="reviewer",
            observed_at="2026-06-20T00:05:00+00:00",
        )

    superseded = transition_lifecycle(
        trusted,
        to_state="superseded",
        reason_code="newer_canonical_memory",
        actor="reviewer",
        observed_at="2026-06-20T00:06:00+00:00",
        superseded_by_memory_id="mem-2",
    )
    assert superseded.superseded_by_memory_id == "mem-2"


def test_contradiction_and_supersession_links_are_explicit_not_inferred() -> None:
    trusted = transition_lifecycle(
        transition_lifecycle(
            lifecycle_from_candidate(
                _candidate(),
                memory_id="mem-1",
                kind="strategy_outcome",
            ),
            to_state="provisional",
            reason_code="reviewed",
            actor="reviewer",
            observed_at="2026-06-20T01:00:00+00:00",
        ),
        to_state="trusted",
        reason_code="repeated_positive",
        actor="reviewer",
        observed_at="2026-06-20T01:01:00+00:00",
    )
    review_link = MemoryContradictionLink(
        link_id="contra-1",
        target_memory_id="mem-1",
        contradicting_memory_id="mem-2",
        decision="mark_for_review",
        reason_code="fresh_evidence_conflict",
        observed_at="2026-06-20T01:02:00+00:00",
        evidence_refs=(_pragma_ref("changed"),),
    )
    demoted = attach_contradiction(trusted, review_link)

    assert demoted.trust_state == "provisional"
    assert demoted.contradiction_links == (review_link,)
    assert demoted.evidence_refs[-1].freshness_state == "changed"

    supersede_link = MemoryContradictionLink(
        link_id="contra-2",
        target_memory_id="mem-1",
        contradicting_memory_id="mem-3",
        decision="supersede_target",
        reason_code="newer_canonical_memory",
        observed_at="2026-06-20T01:03:00+00:00",
    )
    superseded = attach_contradiction(demoted, supersede_link)

    assert superseded.trust_state == "superseded"
    assert superseded.superseded_by_memory_id == "mem-3"
    with pytest.raises(InvalidArgumentError, match="cannot target itself"):
        MemoryContradictionLink(
            link_id="bad",
            target_memory_id="same",
            contradicting_memory_id="same",
            decision="keep_both",
            reason_code="bad",
            observed_at="2026-06-20T01:04:00+00:00",
        )


def test_retrieval_packet_is_compact_trust_bearing_and_evidence_backed() -> None:
    lifecycle = SelfImprovingMemoryLifecycle(
        memory_id="mem-1",
        namespace_ref="agent:self-improve",
        kind="lesson",
        trust_state="trusted",
        trust_score=0.9,
        memory_refs=("mem-1",),
        evidence_refs=(_pragma_ref(),),
        summary_block_ids=("summary-1",),
    )
    trusted_packet = build_memory_retrieval_packet(
        lifecycle,
        packet_id="packet-1",
    )
    candidate_packet = build_memory_retrieval_packet(
        SelfImprovingMemoryLifecycle(
            memory_id="mem-2",
            namespace_ref="agent:self-improve",
            kind="lesson",
            trust_state="candidate",
            trust_score=0.2,
            memory_refs=("mem-2",),
            evidence_refs=(_pragma_ref(),),
        ),
        packet_id="packet-2",
    )

    assert trusted_packet.to_dict() == {
        "packet_id": "packet-1",
        "namespace_ref": "agent:self-improve",
        "kind": "lesson",
        "trust_state": "trusted",
        "trust_score": 0.9,
        "retrieval_reason_codes": ["trusted_retrieval"],
        "memory_refs": ["mem-1"],
        "pragma_refs": ["pragma://repo/memory-evidence/snapshot/node"],
        "summary_block_ids": ["summary-1"],
        "omitted_reason": None,
    }
    assert candidate_packet.omitted_reason == "trust_state_candidate"
    assert candidate_packet.memory_refs == ()
    assert candidate_packet.pragma_refs == ()


def test_attribution_updates_raise_lower_suppress_and_re_review_explicitly() -> None:
    lifecycle = lifecycle_from_candidate(
        _candidate(),
        memory_id="mem-1",
        kind="strategy_outcome",
    )
    provisional = apply_attribution_update(
        lifecycle,
        MemoryAttributionUpdate(
            update_id="u1",
            memory_id="mem-1",
            outcome="positive",
            weight=0.1,
            observed_at="2026-06-20T02:00:00+00:00",
            reason_codes=("positive_reuse",),
        ),
    )
    trusted = apply_attribution_update(
        provisional,
        MemoryAttributionUpdate(
            update_id="u2",
            memory_id="mem-1",
            outcome="positive",
            weight=0.3,
            observed_at="2026-06-20T02:01:00+00:00",
            reason_codes=("positive_reuse",),
        ),
    )
    re_review = apply_attribution_update(
        trusted,
        MemoryAttributionUpdate(
            update_id="u3",
            memory_id="mem-1",
            outcome="evidence_changed",
            weight=0.2,
            observed_at="2026-06-20T02:02:00+00:00",
            reason_codes=("pragma_changed",),
            evidence_refs=(_pragma_ref("changed"),),
        ),
    )
    suppressed = apply_attribution_update(
        re_review,
        MemoryAttributionUpdate(
            update_id="u4",
            memory_id="mem-1",
            outcome="suppress",
            weight=1.0,
            observed_at="2026-06-20T02:03:00+00:00",
            reason_codes=("harmful_retrieval",),
        ),
    )

    assert provisional.trust_state == "provisional"
    assert trusted.trust_state == "trusted"
    assert re_review.trust_state == "provisional"
    assert re_review.evidence_refs[-1].freshness_state == "changed"
    assert suppressed.trust_state == "suppressed"
    assert suppressed.suppression_reason == "harmful_retrieval"
