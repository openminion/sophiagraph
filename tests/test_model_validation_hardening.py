from __future__ import annotations

from dataclasses import replace

import pytest

from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.models import (
    ArtifactRef,
    CandidateReview,
    MemoryCandidate,
    MemoryNamespace,
    MemoryRecord,
    MemoryRelation,
    MemoryTierTransition,
)
from sophiagraph.temporal import coerce_temporal_dt


def _record(**overrides) -> MemoryRecord:
    payload = {
        "id": "rec-validated",
        "scope": "agent:validation",
        "type": "fact",
        "content": {"text": "validated"},
        "created_at": "2026-05-25T00:00:00+00:00",
        "updated_at": "2026-05-25T00:00:00+00:00",
        "source": "validated",
        "confidence": 0.9,
        "namespace": MemoryNamespace(agent_id="validation"),
    }
    payload.update(overrides)
    return MemoryRecord(**payload)


def _candidate(**overrides) -> MemoryCandidate:
    payload = {
        "candidate_id": "cand-validated",
        "session_id": "session-1",
        "proposed_scope": "agent:validation",
        "type": "fact",
        "content": {"text": "candidate"},
        "namespace": MemoryNamespace(agent_id="validation"),
    }
    payload.update(overrides)
    return MemoryCandidate(**payload)


@pytest.mark.parametrize(
    ("field", "value", "error_type"),
    [
        ("id", "", InvalidArgumentError),
        ("scope", "bad scope", InvalidArgumentError),
        ("type", "note", InvalidArgumentError),
        ("source", "crawler", InvalidArgumentError),
        ("tier", "hot", InvalidArgumentError),
        ("visibility", "public", InvalidArgumentError),
        ("confidence", 1.1, InvalidArgumentError),
        ("content", "", InvalidArgumentError),
        ("tags", ["valid", 123], TypeError),
        ("entities", ["valid", object()], TypeError),
        ("evidence_refs", [object()], TypeError),
        ("namespace", "agent:validation", TypeError),
        ("meta", [], TypeError),
        ("access_count", -1, InvalidArgumentError),
    ],
)
def test_memory_record_rejects_invalid_structured_values(
    field: str,
    value,
    error_type: type[Exception],
) -> None:
    with pytest.raises(error_type):
        _record(**{field: value})


def test_memory_record_temporal_helpers_fail_on_malformed_timestamps() -> None:
    record = _record(valid_to="not-a-timestamp")

    with pytest.raises(ValueError):
        record.is_invalidated_at("2026-05-25T00:00:00+00:00")

    with pytest.raises(InvalidArgumentError, match="temporal timestamp"):
        coerce_temporal_dt("")


@pytest.mark.parametrize(
    ("field", "value", "error_type"),
    [
        ("candidate_id", "", InvalidArgumentError),
        ("session_id", "", InvalidArgumentError),
        ("proposed_scope", "tenant:acme", InvalidArgumentError),
        ("type", "note", InvalidArgumentError),
        ("status", "accepted", InvalidArgumentError),
        ("source", "crawler", InvalidArgumentError),
        ("confidence", -0.1, InvalidArgumentError),
        ("content", "", InvalidArgumentError),
        ("tags", ["valid", 1], TypeError),
        ("review", object(), TypeError),
        ("meta", "bad", TypeError),
        ("namespace", "agent:validation", TypeError),
        ("polarity", "maybe", InvalidArgumentError),
    ],
)
def test_memory_candidate_rejects_invalid_structured_values(
    field: str,
    value,
    error_type: type[Exception],
) -> None:
    with pytest.raises(error_type):
        _candidate(**{field: value})


def test_memory_candidate_rejects_conflicting_claim_metadata() -> None:
    with pytest.raises(InvalidArgumentError, match="source_class conflicts"):
        _candidate(
            source_class="observed",
            meta={"source_class": "derived"},
        )

    with pytest.raises(InvalidArgumentError, match="polarity conflicts"):
        _candidate(
            polarity="negates",
            meta={"polarity": "asserts"},
        )

    with pytest.raises(InvalidArgumentError, match="claim_key must be non-empty"):
        _candidate(claim_key=" ")


def test_candidate_review_and_artifact_refs_validate_required_fields() -> None:
    with pytest.raises(InvalidArgumentError, match="reviewer is required"):
        CandidateReview(reviewer="", decided_at="2026-05-25T00:00:00+00:00")

    with pytest.raises(InvalidArgumentError, match="size_bytes"):
        ArtifactRef(ref="artifact", mime="text/plain", sha256="abc", size_bytes=-1)

    with pytest.raises(InvalidArgumentError, match="ref is required"):
        ArtifactRef(ref="", mime="text/plain", sha256="abc", size_bytes=0)


def test_relation_and_tier_transition_reject_invalid_values() -> None:
    with pytest.raises(InvalidArgumentError, match="endpoints must differ"):
        MemoryRelation(
            relation_id="rel-self",
            source_record_id="rec-1",
            target_record_id="rec-1",
            relation_type="supports",
            created_at="2026-05-25T00:00:00+00:00",
        )

    with pytest.raises(InvalidArgumentError, match="invalid relation_type"):
        MemoryRelation(
            relation_id="rel-bad",
            source_record_id="rec-1",
            target_record_id="rec-2",
            relation_type="links_to",
            created_at="2026-05-25T00:00:00+00:00",
        )

    with pytest.raises(TypeError, match="meta must be a dict"):
        MemoryRelation(
            relation_id="rel-bad-meta",
            source_record_id="rec-1",
            target_record_id="rec-2",
            relation_type="supports",
            created_at="2026-05-25T00:00:00+00:00",
            meta=[],  # type: ignore[arg-type]
        )

    transition = MemoryTierTransition(
        transition_id="tier-1",
        record_id="rec-1",
        scope="agent:validation",
        record_type="fact",
        from_tier="working",
        to_tier="archival",
        transition_reason="manual_override",
        transition_at="2026-05-25T00:00:00+00:00",
    )
    with pytest.raises(InvalidArgumentError, match="must differ"):
        replace(transition, to_tier="working")

    with pytest.raises(InvalidArgumentError, match="access_count"):
        replace(transition, access_count=-1)

    with pytest.raises(TypeError, match="meta must be a dict"):
        replace(transition, meta=[])  # type: ignore[arg-type]
