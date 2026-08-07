from __future__ import annotations

from dataclasses import asdict

import pytest

from sophiagraph import (
    ArtifactRef,
    CandidateReviewDecision,
    MemoryCandidate,
    MemoryNamespace,
)
from sophiagraph.access import (
    AccessConstraint,
    AuthorizedSophiaGraphGateway,
    DelegationMemoryGrant,
    MemoryAccessContext,
    MemoryAccessRequest,
)
from sophiagraph.models import DelegatedCandidateProvenance
from sophiagraph.portability import candidate_from_dict
from sophiagraph.storage import SophiaGraphMemoryStore, SophiaGraphSqliteStore


@pytest.fixture(params=["memory", "sqlite"])
def store(request, tmp_path):
    if request.param == "memory":
        return SophiaGraphMemoryStore()
    return SophiaGraphSqliteStore(tmp_path / "delegated-candidate.sqlite3")


def _candidate() -> MemoryCandidate:
    namespace = MemoryNamespace(agent_id="parent", project_id="project")
    return MemoryCandidate(
        candidate_id="candidate-handback",
        session_id="parent-run",
        proposed_scope="project:project",
        type="fact",
        content={"text": "structured child proposal"},
        evidence_refs=[
            ArtifactRef(
                ref="artifact://child-result",
                mime="application/json",
                sha256="a" * 64,
                size_bytes=24,
            )
        ],
        namespace=namespace,
        delegation_provenance=DelegatedCandidateProvenance(
            parent_agent_id="parent",
            child_agent_id="child",
            parent_run_id="parent-run",
            child_run_id="child-run",
            trace_parent_id="trace",
            grant_id="grant-1",
            workspace_id="workspace",
            namespace=namespace,
            source_record_ids=("source-1",),
        ),
    )


def test_delegated_candidate_provenance_round_trips_across_stores(store) -> None:
    candidate = _candidate()
    store.put_candidate(candidate)
    loaded = store.get_candidate(candidate.candidate_id)
    assert loaded == candidate
    assert loaded.delegation_provenance.source_record_ids == ("source-1",)


def test_delegated_candidate_codec_rejects_namespace_disagreement() -> None:
    candidate = _candidate()
    payload = asdict(candidate)
    payload["namespace"] = MemoryNamespace(agent_id="other").as_dict()
    payload["delegation_provenance"] = {
        **asdict(candidate.delegation_provenance),
        "namespace": candidate.delegation_provenance.namespace.as_dict(),
    }
    with pytest.raises(Exception, match="namespace must match"):
        candidate_from_dict(payload)


class _Resolver:
    def __init__(self, grant: DelegationMemoryGrant) -> None:
        self.grant = grant

    def resolve_grant(self, grant_id, *, context, operation):
        return self.grant if grant_id == self.grant.grant_id else None


def test_gateway_routes_review_and_promotion_through_canonical_owner(store) -> None:
    candidate = _candidate()
    store.put_candidate(candidate)
    namespace = candidate.namespace
    grant = DelegationMemoryGrant(
        grant_id="grant-review",
        issuer_authority="openminion-policy",
        audience="sophiagraph",
        delegator_agent_id="parent",
        subject_agent_id="reviewer",
        parent_run_id="parent-run",
        child_run_id="review-run",
        trace_parent_id="trace",
        namespaces=(namespace,),
        workspace_ids=("workspace",),
        operations=("promote",),
        record_types=("fact",),
        issued_at="2026-08-06T00:00:00+00:00",
        expires_at="2099-08-07T00:00:00+00:00",
        max_results=1,
        max_context_tokens=100,
    )
    context = MemoryAccessContext(
        principal_id="reviewer-principal",
        audience="sophiagraph",
        subject_agent_id="reviewer",
        parent_run_id="parent-run",
        child_run_id="review-run",
        trace_parent_id="trace",
        constraints=(
            AccessConstraint(
                mode="allowlist",
                namespaces=(namespace,),
                workspace_ids=("workspace",),
                operations=("promote",),
                record_types=("fact",),
            ),
        ),
        delegated=True,
    )
    request = MemoryAccessRequest(
        operation="promote",
        grant_id=grant.grant_id,
        namespaces=(namespace,),
        workspace_ids=("workspace",),
        record_types=("fact",),
    )
    gateway = AuthorizedSophiaGraphGateway(store, resolver=_Resolver(grant))

    gateway.review_candidate(
        CandidateReviewDecision(
            candidate_id=candidate.candidate_id,
            action="approve",
            reviewer="parent-reviewer",
        ),
        context=context,
        request=request,
    )
    record = gateway.promote_candidate(
        candidate.candidate_id,
        "project:project",
        reviewer="parent-reviewer",
        context=context,
        request=request,
    )

    assert record.content == candidate.content
    assert store.get_candidate(candidate.candidate_id).status == "promoted"
    assert store.list_relations(record.id) == []
