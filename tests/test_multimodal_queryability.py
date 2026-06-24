"""Artifact projection and multimodal queryability tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from sophiagraph import (
    ARTIFACT_CITATION_KINDS,
    ARTIFACT_PROJECTION_FRESHNESS_STATES,
    ARTIFACT_PROJECTION_KINDS,
    ArtifactCitation,
    ArtifactProjectionSegment,
    ArtifactRecord,
    ArtifactTextProjection,
    ArtifactTextQueryOptions,
    ConsentState,
    MemoryNamespace,
    MemoryRecord,
    PrivacyPolicyState,
    RedactionPlan,
    RedactionTarget,
    SophiaGraphMemoryStore,
    SophiaGraphSqliteStore,
    filter_artifact_query_result_for_export,
    query_artifact_text,
    record_with_privacy_policy,
)
from sophiagraph.contracts.errors import InvalidArgumentError


_SHA = "a" * 64
_OTHER_SHA = "b" * 64


@pytest.fixture(params=["memory", "sqlite"])
def store(request, tmp_path: Path):
    if request.param == "memory":
        return SophiaGraphMemoryStore()
    return SophiaGraphSqliteStore(tmp_path / "multimodal-query.sqlite3")


def _ns(agent_id: str = "alpha") -> MemoryNamespace:
    return MemoryNamespace(agent_id=agent_id, session_id="sess-1")


def _record(
    record_id: str,
    content: str,
    *,
    namespace: MemoryNamespace | None = None,
) -> MemoryRecord:
    return MemoryRecord(
        id=record_id,
        scope="agent:alpha",
        type="fact",
        key=record_id,
        title=record_id,
        content=content,
        created_at="2026-06-17T00:00:00+00:00",
        updated_at="2026-06-17T00:00:00+00:00",
        namespace=namespace or _ns(),
        meta={},
    )


def _artifact(
    *,
    artifact_id: str = "art-1",
    sha256: str = _SHA,
    source_class: str = "edited_file",
    derived_text_record_id: str = "rec-1",
) -> ArtifactRecord:
    return ArtifactRecord(
        artifact_id=artifact_id,
        uri="vault:docs/contract.pdf",
        sha256=sha256,
        mime="application/pdf",
        size_bytes=2048,
        namespace=_ns(),
        source_class=source_class,  # type: ignore[arg-type]
        source_owner="adapter",
        created_at="2026-06-17T00:00:00+00:00",
        derived_text_record_id=derived_text_record_id,
        target_record_id="root-note",
    )


def _projection(
    *,
    projection_id: str = "proj-1",
    artifact_id: str = "art-1",
    derived_text_record_id: str = "rec-1",
    source_sha256: str = _SHA,
    text: str = "Contract terms and payment schedule.",
) -> ArtifactTextProjection:
    return ArtifactTextProjection(
        projection_id=projection_id,
        artifact_id=artifact_id,
        derived_text_record_id=derived_text_record_id,
        namespace=_ns(),
        projection_kind="document_text",
        adapter_id="adapter:test",
        source_sha256=source_sha256,
        source_mime="application/pdf",
        created_at="2026-06-17T00:00:00+00:00",
        segments=(
            ArtifactProjectionSegment(
                segment_id="seg-1",
                ordinal=0,
                text=text,
                citations=(
                    ArtifactCitation(
                        citation_id="cit-1",
                        artifact_id=artifact_id,
                        kind="page",
                        page_index=2,
                    ),
                    ArtifactCitation(
                        citation_id="cit-2",
                        artifact_id=artifact_id,
                        kind="segment",
                        segment_id="seg-1",
                    ),
                ),
            ),
        ),
    )


def _policy(
    *,
    retrieval_visibility: str = "visible",
    export_visibility: str = "visible",
    artifact_id: str = "art-1",
) -> PrivacyPolicyState:
    return PrivacyPolicyState(
        policy_id=f"privacy-{artifact_id}",
        consent=ConsentState(
            status="granted",
            granted_at="2026-06-17T00:00:00+00:00",
            source_owner="openminion",
        ),
        retrieval_visibility=retrieval_visibility,  # type: ignore[arg-type]
        export_visibility=export_visibility,  # type: ignore[arg-type]
        retention_class="retain",
        erase_intent="none",
        decision_reason="explicit_allow",
        source_owner="openminion",
        applied_at="2026-06-17T00:00:00+00:00",
        redaction_plan=RedactionPlan(
            plan_id=f"plan-{artifact_id}",
            reason="operator_policy",
            targets=(RedactionTarget(kind="artifact_text", artifact_ref=artifact_id),),
        )
        if "redacted" in {retrieval_visibility, export_visibility}
        else None,
    )


def test_projection_enums_and_citation_union_are_closed() -> None:
    assert ARTIFACT_PROJECTION_KINDS == {
        "ocr_text",
        "transcript",
        "caption",
        "document_text",
    }
    assert ARTIFACT_CITATION_KINDS == {"page", "region", "timestamp", "segment"}
    assert ARTIFACT_PROJECTION_FRESHNESS_STATES == {
        "current",
        "source_replaced",
        "superseded",
        "missing_derived_text",
    }
    with pytest.raises(InvalidArgumentError):
        ArtifactCitation(citation_id="bad", artifact_id="art-1", kind="page")  # type: ignore[arg-type]
    with pytest.raises(InvalidArgumentError):
        ArtifactCitation(
            citation_id="bad-ts",
            artifact_id="art-1",
            kind="timestamp",
            start_ms=50,
        )


def test_projection_segment_from_dict_preserves_invalid_negative_ordinal() -> None:
    with pytest.raises(InvalidArgumentError, match="ordinal must be non-negative"):
        ArtifactProjectionSegment.from_dict(
            {
                "segment_id": "seg-1",
                "ordinal": -1,
                "text": "bad",
                "citations": [],
            }
        )


def test_projection_rejects_non_hex_source_sha256() -> None:
    with pytest.raises(InvalidArgumentError, match="source_sha256"):
        _projection(source_sha256="z" * 64)


def test_artifact_projection_round_trips_and_marks_superseded(store) -> None:
    store.put_record(_record("rec-1", "Contract terms and payment schedule."))
    store.put_artifact(_artifact())
    store.put_artifact_projection(_projection())

    fetched = store.get_artifact_projection("proj-1")
    assert fetched is not None
    assert fetched.artifact_id == "art-1"
    assert fetched.segments[0].citations[0].page_index == 2

    updated = store.mark_artifact_projection_superseded(
        "proj-1",
        superseded_by_projection_id="proj-2",
        superseded_at="2026-06-17T01:00:00+00:00",
    )
    assert updated.superseded_by_projection_id == "proj-2"
    active_only = store.list_artifact_projections(include_superseded=False)
    assert active_only == []


def test_query_artifact_text_returns_citations_and_current_freshness(store) -> None:
    store.put_record(_record("rec-1", "Contract terms and payment schedule."))
    store.put_artifact(_artifact())
    store.put_artifact_projection(_projection())

    result = query_artifact_text(
        store,
        ArtifactTextQueryOptions(query="payment"),
        source_owner="openminion",
    )

    assert len(result.hits) == 1
    hit = result.hits[0]
    assert hit.freshness == "current"
    assert hit.matched_segment_ids == ("seg-1",)
    assert [citation.kind for citation in hit.citations] == ["page", "segment"]
    assert hit.snippet == "Contract terms and payment schedule."


def test_query_artifact_text_reports_source_replaced(store) -> None:
    store.put_record(_record("rec-1", "Contract terms and payment schedule."))
    store.put_artifact(_artifact(sha256=_SHA))
    store.put_artifact_projection(_projection(source_sha256=_SHA))
    store.put_artifact(_artifact(sha256=_OTHER_SHA))

    result = query_artifact_text(
        store,
        ArtifactTextQueryOptions(query="payment"),
        source_owner="openminion",
    )

    assert result.hits[0].freshness == "source_replaced"


def test_query_artifact_text_omits_hidden_records_via_privacy_owner(store) -> None:
    record = record_with_privacy_policy(
        _record("rec-1", "Contract terms and payment schedule."),
        _policy(retrieval_visibility="hidden"),
    )
    store.put_record(record)
    store.put_artifact(_artifact())
    store.put_artifact_projection(_projection())

    result = query_artifact_text(
        store,
        ArtifactTextQueryOptions(query="payment"),
        source_owner="openminion",
    )

    assert result.hits == ()
    assert len(result.omitted) == 1
    assert result.omitted[0].reason == "hidden_by_visibility"


def test_query_artifact_text_redacts_artifact_text_without_second_policy_path(
    store,
) -> None:
    record = record_with_privacy_policy(
        _record("rec-1", "Contract terms and payment schedule."),
        _policy(retrieval_visibility="redacted"),
    )
    store.put_record(record)
    store.put_artifact(_artifact())
    store.put_artifact_projection(_projection())

    result = query_artifact_text(
        store,
        ArtifactTextQueryOptions(query="payment"),
        source_owner="openminion",
    )

    assert len(result.hits) == 1
    assert result.hits[0].redacted is True
    assert result.hits[0].snippet == "[redacted]"
    assert len(result.hits[0].citations) == 2


def test_export_filter_reuses_privacy_owner_for_artifact_hits(store) -> None:
    record = record_with_privacy_policy(
        _record("rec-1", "Contract terms and payment schedule."),
        _policy(export_visibility="redacted"),
    )
    store.put_record(record)
    store.put_artifact(_artifact())
    store.put_artifact_projection(_projection())

    result = query_artifact_text(
        store,
        ArtifactTextQueryOptions(query="payment"),
        source_owner="openminion",
    )
    exported = filter_artifact_query_result_for_export(
        store,
        result,
        source_owner="openminion",
    )

    assert len(exported.hits) == 1
    assert exported.hits[0].redacted is True
    assert exported.hits[0].snippet == "[redacted]"
