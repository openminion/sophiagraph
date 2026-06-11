from __future__ import annotations

from dataclasses import asdict

import pytest

from sophiagraph.models import (
    MemoryNamespace,
    MemoryRecord,
    MemoryRelation,
    StructuralLink,
)
from sophiagraph.query import (
    GraphPatternNodePredicate,
    StructuralGraphQueryRequest,
    execute_structural_graph_query,
    structural_graph_query_request_from_dict,
    structural_graph_query_request_to_dict,
    structural_graph_query_result_from_dict,
    structural_graph_query_result_to_dict,
    structural_graph_query_to_backend_query,
    structural_result_to_knowledge_plan,
)
from sophiagraph.storage import SophiaGraphMemoryStore, SophiaGraphSqliteStore


def _ns(agent_id: str = "agent") -> MemoryNamespace:
    return MemoryNamespace(tenant_id="tenant", agent_id=agent_id, graph_id="main")


def _record(record_id: str, title: str, *, kind: str = "task") -> MemoryRecord:
    return MemoryRecord(
        id=record_id,
        scope="agent:agent",
        type="fact",
        key=record_id,
        title=title,
        content={"text": title},
        tags=["task"],
        created_at="2026-06-04T00:00:00+00:00",
        updated_at="2026-06-04T00:00:00+00:00",
        source="validated",
        namespace=_ns(),
        meta={"properties": {"kind": kind}},
    )


@pytest.fixture(params=["memory", "sqlite"])
def store(request, tmp_path):
    if request.param == "memory":
        store = SophiaGraphMemoryStore()
    else:
        store = SophiaGraphSqliteStore(tmp_path / "structural-query.sqlite3")
    for record in [
        _record("task-draft", "Draft the rollout plan"),
        _record("task-review", "Review the rollout plan"),
        _record("task-publish", "Publish the rollout plan"),
    ]:
        store.put_record(record)
    store.put_relation(
        MemoryRelation(
            relation_id="rel-draft-review",
            source_record_id="task-draft",
            target_record_id="task-review",
            relation_type="supports",
            created_at="2026-06-04T00:01:00+00:00",
        )
    )
    store.put_relation(
        MemoryRelation(
            relation_id="rel-review-publish",
            source_record_id="task-review",
            target_record_id="task-publish",
            relation_type="supports",
            created_at="2026-06-04T00:02:00+00:00",
        )
    )
    store.put_link(
        StructuralLink(
            link_id="link-draft-review",
            source_record_id="task-draft",
            target_record_id="task-review",
            raw_target="task-review",
            link_kind="wikilink",
            resolution_status="resolved",
            relation_type="supports",
            namespace=_ns(),
            created_at="2026-06-04T00:01:00+00:00",
        )
    )
    store.put_link(
        StructuralLink(
            link_id="link-review-publish",
            source_record_id="task-review",
            target_record_id="task-publish",
            raw_target="task-publish",
            link_kind="wikilink",
            resolution_status="resolved",
            relation_type="supports",
            namespace=_ns(),
            created_at="2026-06-04T00:02:00+00:00",
        )
    )
    return store


def test_request_round_trip_keeps_namespaces_and_predicates() -> None:
    request = StructuralGraphQueryRequest(
        query_id="q-pattern",
        mode="pattern",
        scopes=["agent:agent"],
        namespaces=[_ns()],
        seed_record_ids=["task-draft"],
        node_predicates=[GraphPatternNodePredicate("kind", "eq", "task")],
        relation_types=["supports"],
        limit=5,
    )

    payload = structural_graph_query_request_to_dict(request)
    restored = structural_graph_query_request_from_dict(payload)

    assert restored == request
    assert payload["namespaces"] == [request.namespaces[0].as_dict()]
    assert payload["node_predicates"] == [asdict(request.node_predicates[0])]


def test_pattern_mode_returns_rows_and_deterministic_planner(store) -> None:
    result = execute_structural_graph_query(
        store,
        StructuralGraphQueryRequest(
            query_id="q-pattern",
            mode="pattern",
            scopes=["agent:agent"],
            namespaces=[_ns()],
            seed_record_ids=["task-draft"],
            node_predicates=[GraphPatternNodePredicate("kind", "eq", "task")],
            relation_types=["supports"],
            max_hops=2,
            limit=5,
        ),
    )

    assert [row.node_ids for row in result.rows] == [
        ["task-draft", "task-review"],
        ["task-draft", "task-review", "task-publish"],
    ]
    assert [stage.stage for stage in result.planner] == [
        "mode",
        "seed_filter",
        "pattern_execute",
    ]
    assert result.rows[1].path is not None
    assert result.rows[1].path.edge_ids == ["link-draft-review", "link-review-publish"]


def test_global_mode_returns_communities_source_sets_and_plan(store) -> None:
    result = execute_structural_graph_query(
        store,
        StructuralGraphQueryRequest(
            query_id="q-global",
            mode="global",
            scopes=["agent:agent"],
            namespaces=[_ns()],
            relation_types=["supports"],
            limit=10,
        ),
    )

    assert len(result.communities) == 1
    assert result.rows[0].community_ids == [result.communities[0].community_id]
    assert result.rows[0].properties["record_count"] == 3
    assert [stage.stage for stage in result.planner[:2]] == [
        "mode",
        "community_detect",
    ]


def test_backend_mapping_reuses_existing_backend_query_contract() -> None:
    request = StructuralGraphQueryRequest(
        query_id="q-backend",
        mode="pattern",
        scopes=["agent:agent"],
        namespaces=[_ns()],
        seed_record_ids=["task-draft"],
        node_predicates=[GraphPatternNodePredicate("kind", "eq", "task")],
        relation_types=["supports"],
        node_labels=["fact"],
        property_filters={"kind": "task"},
        max_hops=2,
    )

    backend_query = structural_graph_query_to_backend_query(request)

    assert backend_query.kind == "pattern"
    assert backend_query.node_labels == ["fact"]
    assert backend_query.property_filters == {"kind": "task"}
    assert backend_query.pattern_query is not None
    assert backend_query.pattern_query["query_id"] == "q-backend"


def test_global_mode_does_not_map_to_backend_query() -> None:
    request = StructuralGraphQueryRequest(
        query_id="q-global-backend",
        mode="global",
        scopes=["agent:agent"],
    )

    with pytest.raises(Exception, match="only pattern-mode"):
        structural_graph_query_to_backend_query(request)


def test_result_round_trip_and_knowledge_plan_conversion(store) -> None:
    result = execute_structural_graph_query(
        store,
        StructuralGraphQueryRequest(
            query_id="q-plan",
            mode="pattern",
            scopes=["agent:agent"],
            namespaces=[_ns()],
            seed_record_ids=["task-draft"],
            node_predicates=[GraphPatternNodePredicate("kind", "eq", "task")],
            relation_types=["supports"],
            max_hops=2,
            limit=5,
        ),
    )

    payload = structural_graph_query_result_to_dict(result)
    restored = structural_graph_query_result_from_dict(payload)
    plan = structural_result_to_knowledge_plan(restored)

    assert restored == result
    assert [stage.stage for stage in plan.stages] == [
        "filters",
        "filters",
        "graph",
    ]
