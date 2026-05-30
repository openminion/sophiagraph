"""Multimodal artifact memory tests."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from sophiagraph import (
    SophiaGraphMemoryStore,
    SophiaGraphSqliteStore,
)
from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.models import (
    ARTIFACT_RETENTION_POLICIES,
    ARTIFACT_SOURCE_CLASSES,
    ArtifactRecord,
    MemoryNamespace,
)


_SHA = "a" * 64
_OTHER_SHA = "b" * 64


def _ns(agent_id: str = "alpha") -> MemoryNamespace:
    return MemoryNamespace(agent_id=agent_id, session_id="s")


def _artifact(
    *,
    artifact_id: str = "art-1",
    target_record_id: str | None = None,
    source_class: str = "tool_output",
    namespace: MemoryNamespace | None = None,
) -> ArtifactRecord:
    return ArtifactRecord(
        artifact_id=artifact_id,
        uri="vault:notes/screenshot.png",
        sha256=_SHA,
        mime="image/png",
        size_bytes=1234,
        namespace=namespace or _ns(),
        source_class=source_class,  # type: ignore[arg-type]
        source_owner="task-runner",
        created_at="2026-05-29T00:00:00+00:00",
        retention="default",
        target_record_id=target_record_id,
    )


@pytest.fixture(params=["memory", "sqlite"])
def store(request, tmp_path: Path):
    if request.param == "memory":
        return SophiaGraphMemoryStore()
    return SophiaGraphSqliteStore(tmp_path / "art.sqlite3")


def test_artifact_record_constructs_with_required_fields() -> None:
    art = _artifact()
    assert art.artifact_id == "art-1"
    assert art.source_class == "tool_output"
    assert art.retention == "default"


def test_artifact_record_requires_typed_namespace() -> None:
    with pytest.raises(InvalidArgumentError):
        ArtifactRecord(
            artifact_id="a",
            uri="vault:x",
            sha256=_SHA,
            mime="text/plain",
            size_bytes=1,
            namespace={"agent_id": "x"},  # type: ignore[arg-type]
            source_class="tool_output",
            source_owner="x",
            created_at="2026-05-29T00:00:00+00:00",
        )


def test_artifact_record_requires_uri_with_scheme() -> None:
    with pytest.raises(InvalidArgumentError):
        ArtifactRecord(
            artifact_id="a",
            uri="notes/foo.png",  # no scheme
            sha256=_SHA,
            mime="image/png",
            size_bytes=1,
            namespace=_ns(),
            source_class="tool_output",
            source_owner="x",
            created_at="2026-05-29T00:00:00+00:00",
        )


def test_artifact_record_validates_sha256_format() -> None:
    with pytest.raises(InvalidArgumentError):
        ArtifactRecord(
            artifact_id="a",
            uri="vault:x",
            sha256="not-a-digest",
            mime="text/plain",
            size_bytes=1,
            namespace=_ns(),
            source_class="tool_output",
            source_owner="x",
            created_at="2026-05-29T00:00:00+00:00",
        )


def test_artifact_record_validates_mime_shape() -> None:
    with pytest.raises(InvalidArgumentError):
        ArtifactRecord(
            artifact_id="a",
            uri="vault:x",
            sha256=_SHA,
            mime="not_a_mime",
            size_bytes=1,
            namespace=_ns(),
            source_class="tool_output",
            source_owner="x",
            created_at="2026-05-29T00:00:00+00:00",
        )


def test_artifact_record_validates_size_non_negative() -> None:
    with pytest.raises(InvalidArgumentError):
        ArtifactRecord(
            artifact_id="a",
            uri="vault:x",
            sha256=_SHA,
            mime="text/plain",
            size_bytes=-1,
            namespace=_ns(),
            source_class="tool_output",
            source_owner="x",
            created_at="2026-05-29T00:00:00+00:00",
        )


def test_artifact_record_rejects_unknown_source_class() -> None:
    with pytest.raises(InvalidArgumentError):
        _artifact(source_class="hallucinated")


def test_artifact_record_rejects_unknown_retention_policy() -> None:
    with pytest.raises(InvalidArgumentError):
        ArtifactRecord(
            artifact_id="a",
            uri="vault:x",
            sha256=_SHA,
            mime="text/plain",
            size_bytes=1,
            namespace=_ns(),
            source_class="tool_output",
            source_owner="x",
            created_at="2026-05-29T00:00:00+00:00",
            retention="forever",  # type: ignore[arg-type]
        )


def test_artifact_source_class_and_retention_enums_are_closed() -> None:
    assert ARTIFACT_SOURCE_CLASSES == {
        "user_upload",
        "tool_output",
        "edited_file",
        "screenshot",
        "command_evidence",
        "external_link",
        "imported_bundle",
    }
    assert ARTIFACT_RETENTION_POLICIES == {
        "default",
        "session_only",
        "until_replaced",
        "indefinite",
        "purge_on_export",
    }


def test_put_artifact_round_trips(store) -> None:
    art = _artifact(target_record_id="rec-1")
    returned = store.put_artifact(art)
    assert returned == "art-1"
    fetched = store.get_artifact("art-1")
    assert fetched is not None
    assert fetched.artifact_id == "art-1"
    assert fetched.target_record_id == "rec-1"
    assert fetched.mime == "image/png"
    assert fetched.namespace == _ns()


def test_list_artifacts_filters_by_namespace(store) -> None:
    store.put_artifact(_artifact(artifact_id="a-alpha", namespace=_ns("alpha")))
    store.put_artifact(
        ArtifactRecord(
            artifact_id="a-beta",
            uri="vault:x",
            sha256=_OTHER_SHA,
            mime="image/png",
            size_bytes=1,
            namespace=_ns("beta"),
            source_class="tool_output",
            source_owner="x",
            created_at="2026-05-29T00:00:00+00:00",
        )
    )
    only_alpha = store.list_artifacts(namespaces=[_ns("alpha")])
    assert [a.artifact_id for a in only_alpha] == ["a-alpha"]


def test_list_artifacts_filters_by_target_record_id_and_source_class(store) -> None:
    store.put_artifact(_artifact(artifact_id="a-1", target_record_id="rec-1"))
    store.put_artifact(
        ArtifactRecord(
            artifact_id="a-2",
            uri="vault:y",
            sha256=_OTHER_SHA,
            mime="image/png",
            size_bytes=2,
            namespace=_ns(),
            source_class="screenshot",
            source_owner="x",
            created_at="2026-05-29T00:00:00+00:00",
            target_record_id="rec-2",
        )
    )
    by_target = store.list_artifacts(target_record_id="rec-1")
    assert [a.artifact_id for a in by_target] == ["a-1"]
    by_class = store.list_artifacts(source_class="screenshot")
    assert [a.artifact_id for a in by_class] == ["a-2"]


def test_put_artifact_emits_changefeed_event(store) -> None:
    store.put_artifact(_artifact())
    events = [e for e in store.list_changes() if e.object_type == "artifact"]
    assert events
    assert events[-1].object_id == "art-1"
    assert events[-1].operation == "put"


def test_artifact_module_contains_no_llm_extraction_tokens() -> None:
    path = (
        Path(__file__).parent.parent / "src" / "sophiagraph" / "models" / "artifact.py"
    )
    source = path.read_text(encoding="utf-8")
    banned = [
        r"\bopenai\b",
        r"\banthropic\b",
        r"\bClaude\b",
        r"\bocr\(",
        r"\btranscribe\(",
        r"\bextract_claims\(",
        r"\bsummarize\(",
        r"\bclassify_image\(",
    ]
    for pattern in banned:
        assert re.search(pattern, source) is None, (
            f"banned extraction token {pattern!r} found in artifact.py"
        )


def test_artifact_dto_does_not_carry_inline_binary_content() -> None:
    """The dataclass has no field for raw bytes."""

    art = _artifact()
    field_names = {f.name for f in art.__dataclass_fields__.values()}
    assert "blob" not in field_names
    assert "raw_bytes" not in field_names
    assert "content" not in field_names
