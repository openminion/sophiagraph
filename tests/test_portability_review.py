from __future__ import annotations

import json
import os
from dataclasses import replace

import pytest

from sophiagraph.models import MemoryBlock, MemoryNamespace, MemoryRecord
from sophiagraph.portability import (
    MEMORY_REVIEW_ARTIFACT_VERSION,
    MemoryBundleSnapshot,
    MemoryReviewError,
    MemoryReviewPlan,
    MemoryReviewSectionSummary,
    build_memory_review_artifact,
    read_review_artifact,
    read_review_plan,
    render_review_markdown,
    write_review_document,
    write_review_markdown,
)


def _snapshot() -> MemoryBundleSnapshot:
    return MemoryBundleSnapshot(
        manifest={
            "bundle_id": "bundle-1",
            "source_backend": "sqlite",
            "source_instance": "source.db",
        },
        records=[
            MemoryRecord(
                id="record-1",
                scope="agent:alpha",
                namespace=MemoryNamespace(agent_id="alpha"),
                type="fact",
                content={"text": "Remember this"},
                source="user_said",
                created_at="2026-07-20T00:00:00+00:00",
                updated_at="2026-07-20T00:00:00+00:00",
            )
        ],
    )


def test_artifact_round_trip_is_deterministic_and_owner_only(tmp_path) -> None:
    artifact = build_memory_review_artifact(_snapshot())
    path = write_review_document(artifact, tmp_path / "review.json")
    loaded = read_review_artifact(path)

    assert loaded == artifact
    assert loaded.version == MEMORY_REVIEW_ARTIFACT_VERSION
    assert (
        loaded.sections["records"][0]["review_origin"]["source_record_id"] == "record-1"
    )
    assert (
        write_review_document(loaded, tmp_path / "copy.json").read_bytes()
        == path.read_bytes()
    )
    if os.name != "nt":
        assert path.stat().st_mode & 0o777 == 0o600


def test_markdown_is_display_only_and_carries_digest(tmp_path) -> None:
    artifact = build_memory_review_artifact(_snapshot())
    markdown = render_review_markdown(artifact)
    path = write_review_markdown(artifact, tmp_path / "review.md")

    assert artifact.artifact_sha256 in markdown
    assert "display-only" in markdown
    with pytest.raises(MemoryReviewError) as exc_info:
        read_review_artifact(path)
    assert exc_info.value.reason_code == "invalid_review_document"


def test_reader_rejects_unknown_version_and_digest_drift(tmp_path) -> None:
    artifact = build_memory_review_artifact(_snapshot())
    path = write_review_document(artifact, tmp_path / "review.json")
    payload = json.loads(path.read_text())
    payload["version"] = "memory_review.v99"
    path.write_text(json.dumps(payload))
    with pytest.raises(MemoryReviewError) as exc_info:
        read_review_artifact(path)
    assert exc_info.value.reason_code == "invalid_review_document"

    path = write_review_document(artifact, tmp_path / "review.json")
    payload = json.loads(path.read_text())
    payload["sections"]["records"][0]["title"] = "tampered"
    path.write_text(json.dumps(payload))
    with pytest.raises(MemoryReviewError) as exc_info:
        read_review_artifact(path)
    assert exc_info.value.reason_code == "artifact_digest_mismatch"


def test_non_empty_unsupported_section_fails_closed() -> None:
    block = MemoryBlock(
        block_id="block-1",
        class_name="agent_identity",
        mode="pinned",
        content="Identity",
        owner_namespace=MemoryNamespace(agent_id="alpha"),
        token_estimate=1,
        source="operator",
        created_at="2026-07-20T00:00:00+00:00",
        last_updated_at="2026-07-20T00:00:00+00:00",
    )
    with pytest.raises(MemoryReviewError) as exc_info:
        build_memory_review_artifact(replace(_snapshot(), memory_blocks=[block]))
    assert exc_info.value.reason_code == "unsupported_section"


def test_missing_origin_provenance_fails_closed(tmp_path) -> None:
    artifact = build_memory_review_artifact(_snapshot())
    path = write_review_document(artifact, tmp_path / "review.json")
    payload = json.loads(path.read_text())
    payload["sections"]["records"][0]["review_origin"] = {}
    payload["artifact_sha256"] = ""
    from sophiagraph.portability.review import review_sha256

    payload["artifact_sha256"] = review_sha256(payload, digest_field="artifact_sha256")
    path.write_text(json.dumps(payload))
    with pytest.raises(MemoryReviewError) as exc_info:
        read_review_artifact(path)
    assert exc_info.value.reason_code == "origin_provenance_required"


def test_plan_reader_rejects_unknown_version_and_digest_drift(tmp_path) -> None:
    from sophiagraph.portability.review import review_sha256

    plan = MemoryReviewPlan(
        version="memory_review_plan.v1",
        plan_id="plan-1",
        created_at="2026-07-20T00:00:00+00:00",
        artifact_sha256="artifact",
        options={},
        options_sha256=review_sha256({}),
        target_backend="SQLiteMemoryStore",
        target_identity="target.db",
        target_fingerprint="target",
        operations=(),
        section_summaries=(MemoryReviewSectionSummary(name="records", count=0),),
    )
    plan = replace(plan, plan_sha256=review_sha256(plan, digest_field="plan_sha256"))
    path = write_review_document(plan, tmp_path / "plan.json")
    assert read_review_plan(path) == plan

    payload = json.loads(path.read_text())
    payload["version"] = "memory_review_plan.v99"
    path.write_text(json.dumps(payload))
    with pytest.raises(MemoryReviewError) as exc_info:
        read_review_plan(path)
    assert exc_info.value.reason_code == "invalid_review_document"

    path = write_review_document(plan, tmp_path / "plan.json")
    payload = json.loads(path.read_text())
    payload["target_fingerprint"] = "changed"
    path.write_text(json.dumps(payload))
    with pytest.raises(MemoryReviewError) as exc_info:
        read_review_plan(path)
    assert exc_info.value.reason_code == "plan_digest_mismatch"
