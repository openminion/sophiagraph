from __future__ import annotations

from pathlib import Path

import pytest

from sophiagraph import MemoryCandidate
from sophiagraph.query import CandidateListOptions, RecordOrder
from sophiagraph.storage import SophiaGraphMemoryStore, SophiaGraphSqliteStore


@pytest.fixture(params=("memory", "sqlite"))
def store(request: pytest.FixtureRequest, tmp_path: Path):
    if request.param == "memory":
        return SophiaGraphMemoryStore()
    return SophiaGraphSqliteStore(tmp_path / "candidate-ordering.sqlite3")


def test_candidate_list_supports_explicit_oldest_updated_order(store) -> None:
    older = MemoryCandidate(
        candidate_id="candidate-a",
        session_id="session-1",
        proposed_scope="agent:test",
        type="fact",
        content={"text": "older"},
        created_at="2026-09-29T00:00:00+00:00",
        updated_at="2026-09-29T00:00:00+00:00",
    )
    newer = MemoryCandidate(
        candidate_id="candidate-b",
        session_id="session-1",
        proposed_scope="agent:test",
        type="fact",
        content={"text": "newer"},
        created_at="2026-09-29T00:01:00+00:00",
        updated_at="2026-09-29T00:01:00+00:00",
    )
    newest_tie = MemoryCandidate(
        candidate_id="candidate-c",
        session_id="session-1",
        proposed_scope="agent:test",
        type="fact",
        content={"text": "newest tie"},
        created_at="2026-09-29T00:01:00+00:00",
        updated_at="2026-09-29T00:01:00+00:00",
    )
    store.put_candidate(older)
    store.put_candidate(newer)
    store.put_candidate(newest_tie)

    default_order = store.list_candidates(CandidateListOptions(status="proposed"))
    explicit_descending = store.list_candidates(
        CandidateListOptions(
            status="proposed",
            order_by=RecordOrder.UPDATED_AT_DESC,
        )
    )
    assert [item.candidate_id for item in default_order] == [
        "candidate-b",
        "candidate-c",
        "candidate-a",
    ]
    assert explicit_descending == default_order

    selected = store.list_candidates(
        CandidateListOptions(
            status="proposed",
            limit=1,
            order_by=RecordOrder.UPDATED_AT_ASC,
        )
    )
    assert [item.candidate_id for item in selected] == ["candidate-a"]

    store.update_candidate(
        "candidate-a",
        {"updated_at": "2026-09-29T00:02:00+00:00"},
    )
    selected = store.list_candidates(
        CandidateListOptions(
            status="proposed",
            limit=1,
            order_by=RecordOrder.UPDATED_AT_ASC,
        )
    )
    assert [item.candidate_id for item in selected] == ["candidate-b"]
