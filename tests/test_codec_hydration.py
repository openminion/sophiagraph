from __future__ import annotations

import pytest

from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.portability.codec import (
    candidate_from_dict,
    record_from_dict,
    relation_from_dict,
)


def test_record_hydration_reports_missing_required_fields() -> None:
    with pytest.raises(InvalidArgumentError, match="missing required field: type"):
        record_from_dict(
            {
                "id": "rec-1",
                "scope": "agent:test",
                "content": {"text": "missing type"},
                "created_at": "2026-05-23T00:00:00+00:00",
                "updated_at": "2026-05-23T00:00:00+00:00",
            }
        )


def test_candidate_hydration_reports_missing_required_fields() -> None:
    with pytest.raises(InvalidArgumentError, match="missing required field: content"):
        candidate_from_dict(
            {
                "candidate_id": "cand-1",
                "session_id": "session-1",
                "proposed_scope": "agent:test",
                "type": "fact",
            }
        )


def test_relation_hydration_reports_missing_required_fields() -> None:
    with pytest.raises(
        InvalidArgumentError,
        match="missing required field: relation_type",
    ):
        relation_from_dict(
            {
                "relation_id": "rel-1",
                "source_record_id": "rec-1",
                "target_record_id": "rec-2",
                "created_at": "2026-05-23T00:00:00+00:00",
            }
        )
