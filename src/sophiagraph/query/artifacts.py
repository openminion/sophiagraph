"""Artifact-backed text query DTOs and deterministic retrieval helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Protocol

from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.models import (
    ARTIFACT_PROJECTION_FRESHNESS_STATES,
    ArtifactCitation,
    ArtifactRecord,
    ArtifactTextProjection,
    MemoryNamespace,
    MemoryRecord,
)
from sophiagraph.models.privacy import RedactionTarget
from sophiagraph.portability.models import MemoryBundleSnapshot
from sophiagraph.privacy import (
    filter_records_for_retrieval,
    filter_snapshot_for_export,
    privacy_policy_from_record,
)


class ArtifactTextQueryStore(Protocol):
    def get_artifact(self, artifact_id: str) -> ArtifactRecord | None: ...

    def get_record(self, record_id: str) -> MemoryRecord | None: ...

    def list_artifact_projections(
        self,
        *,
        namespaces: list[MemoryNamespace] | None = None,
        artifact_id: str | None = None,
        derived_text_record_id: str | None = None,
        projection_kinds: list[str] | None = None,
        include_superseded: bool = True,
        limit: int | None = None,
    ) -> list[ArtifactTextProjection]: ...


@dataclass(frozen=True, slots=True)
class ArtifactTextQueryOptions:
    query: str
    namespaces: list[MemoryNamespace] | None = None
    artifact_ids: list[str] | None = None
    target_record_id: str | None = None
    source_classes: list[str] | None = None
    projection_kinds: list[str] | None = None
    freshness: list[str] | None = None
    limit: int | None = None

    def __post_init__(self) -> None:
        if not self.query.strip():
            raise InvalidArgumentError("query is required")
        for name, values in (
            ("artifact_ids", self.artifact_ids),
            ("source_classes", self.source_classes),
            ("projection_kinds", self.projection_kinds),
            ("freshness", self.freshness),
        ):
            if values is not None and any(not str(value).strip() for value in values):
                raise InvalidArgumentError(f"{name} cannot contain empty values")
        if self.freshness is not None:
            invalid = {
                str(value)
                for value in self.freshness
                if str(value) not in ARTIFACT_PROJECTION_FRESHNESS_STATES
            }
            if invalid:
                raise InvalidArgumentError(
                    f"invalid freshness filters: {sorted(invalid)}"
                )
        if self.limit is not None and self.limit <= 0:
            raise InvalidArgumentError("limit must be positive")


@dataclass(frozen=True, slots=True)
class ArtifactTextOmission:
    projection_id: str
    artifact_id: str
    derived_text_record_id: str
    reason: str
    detail: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.projection_id:
            raise InvalidArgumentError("projection_id is required")
        if not self.artifact_id:
            raise InvalidArgumentError("artifact_id is required")
        if not self.derived_text_record_id:
            raise InvalidArgumentError("derived_text_record_id is required")
        if not self.reason:
            raise InvalidArgumentError("reason is required")


@dataclass(frozen=True, slots=True)
class ArtifactTextHit:
    projection_id: str
    artifact_id: str
    derived_text_record_id: str
    projection_kind: str
    freshness: str
    snippet: str
    citations: tuple[ArtifactCitation, ...] = ()
    matched_segment_ids: tuple[str, ...] = ()
    target_record_id: str | None = None
    source_class: str | None = None
    redacted: bool = False

    def __post_init__(self) -> None:
        if not self.projection_id:
            raise InvalidArgumentError("projection_id is required")
        if not self.artifact_id:
            raise InvalidArgumentError("artifact_id is required")
        if not self.derived_text_record_id:
            raise InvalidArgumentError("derived_text_record_id is required")
        if not self.projection_kind:
            raise InvalidArgumentError("projection_kind is required")
        if self.freshness not in ARTIFACT_PROJECTION_FRESHNESS_STATES:
            raise InvalidArgumentError(f"invalid freshness: {self.freshness!r}")
        if not self.snippet:
            raise InvalidArgumentError("snippet is required")


@dataclass(frozen=True, slots=True)
class ArtifactTextQueryResult:
    query: str
    hits: tuple[ArtifactTextHit, ...]
    omitted: tuple[ArtifactTextOmission, ...] = ()

    def __post_init__(self) -> None:
        if not self.query.strip():
            raise InvalidArgumentError("query is required")


def projection_freshness(
    projection: ArtifactTextProjection,
    artifact: ArtifactRecord | None,
    derived_text_record: MemoryRecord | None,
) -> str:
    if projection.superseded_by_projection_id:
        return "superseded"
    if artifact is None or artifact.sha256 != projection.source_sha256:
        return "source_replaced"
    if derived_text_record is None:
        return "missing_derived_text"
    return "current"


def _policy_requires_artifact_redaction(
    record: MemoryRecord | None,
    artifact_id: str,
    *,
    surface: str,
) -> str | None:
    if record is None:
        return None
    policy = privacy_policy_from_record(record)
    if policy is None:
        return None
    visibility = (
        policy.retrieval_visibility
        if surface == "retrieval"
        else policy.export_visibility
    )
    if visibility != "redacted" or policy.redaction_plan is None:
        return None
    for target in policy.redaction_plan.targets:
        if (
            isinstance(target, RedactionTarget)
            and target.kind == "artifact_text"
            and target.artifact_ref == artifact_id
        ):
            return policy.redaction_plan.replace_with
    return None


def _normalize(value: str) -> str:
    return value.casefold()


def _build_hit(
    projection: ArtifactTextProjection,
    artifact: ArtifactRecord | None,
    derived_text_record: MemoryRecord | None,
    query: str,
) -> ArtifactTextHit | None:
    needle = _normalize(query.strip())
    matched_segments = [
        segment
        for segment in projection.segments
        if needle in _normalize(segment.text)
    ]
    if not matched_segments:
        return None
    citations: list[ArtifactCitation] = []
    seen: set[str] = set()
    for segment in matched_segments:
        for citation in segment.citations:
            if citation.citation_id in seen:
                continue
            seen.add(citation.citation_id)
            citations.append(citation)
    return ArtifactTextHit(
        projection_id=projection.projection_id,
        artifact_id=projection.artifact_id,
        derived_text_record_id=projection.derived_text_record_id,
        projection_kind=projection.projection_kind,
        freshness=projection_freshness(projection, artifact, derived_text_record),
        snippet=matched_segments[0].text,
        citations=tuple(citations),
        matched_segment_ids=tuple(segment.segment_id for segment in matched_segments),
        target_record_id=artifact.target_record_id if artifact is not None else None,
        source_class=artifact.source_class if artifact is not None else None,
    )


def _redact_hit(hit: ArtifactTextHit, replace_with: str) -> ArtifactTextHit:
    return ArtifactTextHit(
        projection_id=hit.projection_id,
        artifact_id=hit.artifact_id,
        derived_text_record_id=hit.derived_text_record_id,
        projection_kind=hit.projection_kind,
        freshness=hit.freshness,
        snippet=replace_with,
        citations=hit.citations,
        matched_segment_ids=hit.matched_segment_ids,
        target_record_id=hit.target_record_id,
        source_class=hit.source_class,
        redacted=True,
    )


def query_artifact_text(
    store: ArtifactTextQueryStore,
    options: ArtifactTextQueryOptions,
    *,
    source_owner: str,
    hooks: Iterable[Any] = (),
) -> ArtifactTextQueryResult:
    projections = store.list_artifact_projections(
        namespaces=options.namespaces,
        projection_kinds=options.projection_kinds,
        include_superseded=True,
        limit=None,
    )
    candidate_rows: list[
        tuple[ArtifactTextProjection, ArtifactRecord | None, MemoryRecord | None, ArtifactTextHit]
    ] = []
    for projection in projections:
        artifact = store.get_artifact(projection.artifact_id)
        if options.artifact_ids is not None and projection.artifact_id not in options.artifact_ids:
            continue
        if artifact is None:
            continue
        if (
            options.target_record_id is not None
            and artifact.target_record_id != options.target_record_id
        ):
            continue
        if (
            options.source_classes is not None
            and artifact.source_class not in options.source_classes
        ):
            continue
        record = store.get_record(projection.derived_text_record_id)
        hit = _build_hit(projection, artifact, record, options.query)
        if hit is None:
            continue
        if options.freshness is not None and hit.freshness not in options.freshness:
            continue
        candidate_rows.append((projection, artifact, record, hit))

    records = [record for _, _, record, _ in candidate_rows if record is not None]
    retrieval = filter_records_for_retrieval(
        records,
        source_owner=source_owner,
        hooks=hooks,
    )
    kept_by_id = {record.id: record for record in retrieval.records}
    omitted_by_id = {item.record_id: item for item in retrieval.omitted}
    hits: list[ArtifactTextHit] = []
    omitted: list[ArtifactTextOmission] = []
    for projection, _, record, hit in candidate_rows:
        if record is None:
            hits.append(hit)
            continue
        omitted_item = omitted_by_id.get(record.id)
        if omitted_item is not None:
            omitted.append(
                ArtifactTextOmission(
                    projection_id=projection.projection_id,
                    artifact_id=projection.artifact_id,
                    derived_text_record_id=record.id,
                    reason=omitted_item.reason,
                    detail=dict(omitted_item.detail),
                )
            )
            continue
        kept = kept_by_id.get(record.id)
        replace_with = _policy_requires_artifact_redaction(
            kept,
            projection.artifact_id,
            surface="retrieval",
        )
        hits.append(_redact_hit(hit, replace_with) if replace_with else hit)
    if options.limit is not None:
        hits = hits[: options.limit]
    return ArtifactTextQueryResult(
        query=options.query,
        hits=tuple(hits),
        omitted=tuple(omitted),
    )


def filter_artifact_query_result_for_export(
    store: ArtifactTextQueryStore,
    result: ArtifactTextQueryResult,
    *,
    source_owner: str,
    hooks: Iterable[Any] = (),
) -> ArtifactTextQueryResult:
    records = [
        record
        for hit in result.hits
        if (record := store.get_record(hit.derived_text_record_id)) is not None
    ]
    export = filter_snapshot_for_export(
        MemoryBundleSnapshot(manifest={}, records=records),
        source_owner=source_owner,
        hooks=hooks,
    )
    kept_by_id = {record.id: record for record in export.snapshot.records}
    omitted_by_id = {item.record_id: item for item in export.omitted}
    hits: list[ArtifactTextHit] = []
    omitted = list(result.omitted)
    for hit in result.hits:
        omitted_item = omitted_by_id.get(hit.derived_text_record_id)
        if omitted_item is not None:
            omitted.append(
                ArtifactTextOmission(
                    projection_id=hit.projection_id,
                    artifact_id=hit.artifact_id,
                    derived_text_record_id=hit.derived_text_record_id,
                    reason=omitted_item.reason,
                    detail=dict(omitted_item.detail),
                )
            )
            continue
        kept = kept_by_id.get(hit.derived_text_record_id)
        replace_with = _policy_requires_artifact_redaction(
            kept,
            hit.artifact_id,
            surface="export",
        )
        hits.append(_redact_hit(hit, replace_with) if replace_with else hit)
    return ArtifactTextQueryResult(
        query=result.query,
        hits=tuple(hits),
        omitted=tuple(omitted),
    )


__all__ = [
    "ArtifactTextHit",
    "ArtifactTextOmission",
    "ArtifactTextQueryOptions",
    "ArtifactTextQueryResult",
    "ArtifactTextQueryStore",
    "filter_artifact_query_result_for_export",
    "projection_freshness",
    "query_artifact_text",
]
