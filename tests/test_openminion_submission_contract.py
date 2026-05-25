from __future__ import annotations

import pytest

from sophiagraph.contracts.types import MemoryCandidateRequest
from sophiagraph.models import MemoryCandidate, MemoryNamespace
from sophiagraph.query import CandidateListOptions
from sophiagraph.storage import SophiaGraphMemoryStore, SophiaGraphSqliteStore


@pytest.fixture(params=["memory", "sqlite"])
def store(request, tmp_path):
    if request.param == "memory":
        return SophiaGraphMemoryStore()
    return SophiaGraphSqliteStore(tmp_path / "openminion-submit.sqlite3")


def test_openminion_candidate_request_can_stage_and_promote(store) -> None:
    request = MemoryCandidateRequest(
        scope="agent:openminion",
        record_type="fact",
        title="OpenMinion submitted fact",
        content={"text": "caller supplied durable fact"},
        tags=["openminion/e2e"],
        evidence_refs=[],
    )
    namespace = MemoryNamespace(
        tenant_id="tenant",
        agent_id="openminion",
        session_id="session-1",
        graph_id="main",
    )
    candidate = MemoryCandidate(
        candidate_id="cand-openminion-1",
        session_id="session-1",
        proposed_scope=request.scope,
        type=request.record_type,
        title=request.title,
        content=request.content,
        tags=list(request.tags),
        evidence_refs=list(request.evidence_refs),
        namespace=namespace,
        meta={"source_adapter": "openminion"},
    )

    candidate_id = store.put_candidate(candidate)
    staged = store.list_candidates(CandidateListOptions(session_id="session-1"))
    promoted = store.promote_candidate(candidate_id, request.scope)

    assert [item.candidate_id for item in staged] == ["cand-openminion-1"]
    assert promoted.scope == "agent:openminion"
    assert promoted.namespace == namespace
    assert promoted.content == {"text": "caller supplied durable fact"}
    assert promoted.meta["source_adapter"] == "openminion"
