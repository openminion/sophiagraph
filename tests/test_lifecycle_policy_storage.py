"""Cross-backend lifecycle policy storage and idempotency tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from sophiagraph import (
    LifecyclePolicy,
    PromotionPredicate,
    PromotionPredicateKind,
    SophiaGraphMemoryStore,
    SophiaGraphSqliteStore,
    apply_decision_to_record_meta,
    evaluate_policy,
)
from sophiagraph.models import MemoryNamespace
from sophiagraph.models.record import MemoryRecord


@pytest.fixture(params=["memory", "sqlite"])
def store(request, tmp_path: Path):
    if request.param == "memory":
        return SophiaGraphMemoryStore()
    return SophiaGraphSqliteStore(tmp_path / "sg.sqlite3")


def _ns() -> MemoryNamespace:
    return MemoryNamespace(agent_id="alpha", session_id="sess-1")


def _policy(*, policy_id: str = "p-1") -> LifecyclePolicy:
    return LifecyclePolicy(
        policy_id=policy_id,
        namespace_filter=_ns(),
        created_at_iso="2026-05-29T00:00:00+00:00",
        ttl_active_iso="P30D",
        ttl_cooling_iso="P7D",
        promotion_predicates=(
            PromotionPredicate(
                kind=PromotionPredicateKind.ACCESS_COUNT_ABOVE_THRESHOLD,
                threshold=5,
            ),
        ),
    )


# put / get / list.


def test_put_then_get_lifecycle_policy_round_trips(store) -> None:
    policy = _policy()
    returned_id = store.put_lifecycle_policy(policy)
    assert returned_id == "p-1"
    fetched = store.get_lifecycle_policy("p-1")
    assert fetched is not None
    assert fetched.policy_id == "p-1"
    assert fetched.ttl_active_iso == "P30D"
    assert fetched.ttl_cooling_iso == "P7D"
    assert len(fetched.promotion_predicates) == 1
    assert (
        fetched.promotion_predicates[0].kind
        == PromotionPredicateKind.ACCESS_COUNT_ABOVE_THRESHOLD
    )
    assert fetched.promotion_predicates[0].threshold == 5
    assert fetched.namespace_filter == _ns()


def test_get_lifecycle_policy_unknown_id_returns_none(store) -> None:
    assert store.get_lifecycle_policy("does-not-exist") is None


def test_list_lifecycle_policies_filters_by_namespace(store) -> None:
    p1 = _policy(policy_id="p-1")
    p2 = LifecyclePolicy(
        policy_id="p-2",
        namespace_filter=MemoryNamespace(agent_id="beta"),
        created_at_iso="2026-05-29T00:00:00+00:00",
        ttl_active_iso="P14D",
    )
    store.put_lifecycle_policy(p1)
    store.put_lifecycle_policy(p2)
    all_rows = store.list_lifecycle_policies()
    assert {p.policy_id for p in all_rows} == {"p-1", "p-2"}
    filtered = store.list_lifecycle_policies(namespaces=[_ns()])
    assert [p.policy_id for p in filtered] == ["p-1"]


def test_list_lifecycle_policies_limit_respected(store) -> None:
    for i in range(3):
        store.put_lifecycle_policy(
            LifecyclePolicy(
                policy_id=f"p-{i}",
                namespace_filter=_ns(),
                created_at_iso="2026-05-29T00:00:00+00:00",
                ttl_active_iso="P30D",
            )
        )
    rows = store.list_lifecycle_policies(limit=2)
    assert len(rows) == 2


def test_put_lifecycle_policy_overwrites_same_id(store) -> None:
    store.put_lifecycle_policy(_policy())
    updated = LifecyclePolicy(
        policy_id="p-1",
        namespace_filter=_ns(),
        created_at_iso="2026-05-29T00:00:00+00:00",
        ttl_active_iso="P60D",  # changed
    )
    store.put_lifecycle_policy(updated)
    fetched = store.get_lifecycle_policy("p-1")
    assert fetched is not None
    assert fetched.ttl_active_iso == "P60D"


NOW = datetime(2026, 5, 28, 12, 0, 0, tzinfo=timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def test_apply_decision_to_record_meta_is_pure_and_idempotent() -> None:
    record = MemoryRecord(
        id="rec-1",
        scope="session:s",
        type="fact",
        content="x",
        created_at=_iso(NOW - timedelta(days=40)),
        updated_at=_iso(NOW - timedelta(days=40)),
        access_count=0,
        meta={"unrelated": "preserved"},
    )
    policy = _policy()
    decision = evaluate_policy(record, policy, _iso(NOW))
    # Re-applying the same decision twice produces the same meta dict.
    new_meta = apply_decision_to_record_meta(record.meta, decision)
    new_meta_again = apply_decision_to_record_meta(new_meta, decision)
    assert new_meta == new_meta_again
    # Original record.meta is untouched (purity).
    assert record.meta == {"unrelated": "preserved"}
    # Unrelated meta is preserved through transitions.
    assert new_meta["unrelated"] == "preserved"
    # The transition is recorded as the next phase string.
    assert new_meta["lifecycle_phase"] == decision.next_phase.value
    assert new_meta["lifecycle_transition_reason"] == "ttl_active_elapsed"


def test_apply_decision_no_transition_does_not_record_reason() -> None:
    record = MemoryRecord(
        id="rec-1",
        scope="session:s",
        type="fact",
        content="x",
        created_at=_iso(NOW),
        updated_at=_iso(NOW),
    )
    policy = LifecyclePolicy(
        policy_id="p",
        namespace_filter=_ns(),
        created_at_iso=_iso(NOW),
    )
    decision = evaluate_policy(record, policy, _iso(NOW))
    new_meta = apply_decision_to_record_meta(record.meta, decision)
    assert new_meta["lifecycle_phase"] == "active"
    assert "lifecycle_transition_reason" not in new_meta


def test_apply_decision_rejects_non_decision() -> None:
    from sophiagraph.contracts.errors import InvalidArgumentError

    with pytest.raises(InvalidArgumentError):
        apply_decision_to_record_meta({}, "not_a_decision")  # type: ignore[arg-type]


# Anti-LLM source-token regression.


def test_lifecycle_storage_helpers_contain_no_llm_call_tokens() -> None:
    import re

    paths = [
        Path(__file__).parent.parent
        / "src"
        / "sophiagraph"
        / "storage"
        / "lifecycle_policy.py",
    ]
    banned = [
        r"\bopenai\b",
        r"\banthropic\b",
        r"\bClaude\b",
        r"\bllm_complete\b",
    ]
    for path in paths:
        source = path.read_text(encoding="utf-8")
        for pattern in banned:
            assert re.search(pattern, source) is None, (
                f"banned LLM token {pattern!r} found in {path.name}"
            )
