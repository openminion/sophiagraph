from __future__ import annotations

import inspect
import re
from collections.abc import Callable
from pathlib import Path

import pytest

import sophiagraph
from sophiagraph import (
    CommunityDetectionOptions,
    CommunityQueryOptions,
    GraphCommunity,
    GraphPatternNodePredicate,
    GraphPatternQuery,
    MemoryNamespace,
    MemoryRecord,
    MemoryRelation,
    SophiaGraphMemoryStore,
    SophiaGraphSqliteStore,
    StructuralLink,
    build_community_snapshot,
    community_snapshot_status,
    detect_communities,
    execute_graph_pattern_query,
    layout_hints_for_snapshot,
    pattern_query_to_backend_payload,
    query_communities,
)
from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.query.graph import GraphSnapshotOptions


StoreFactory = Callable[[Path], SophiaGraphMemoryStore | SophiaGraphSqliteStore]


def _ns(agent_id: str = "agent") -> MemoryNamespace:
    return MemoryNamespace(tenant_id="tenant", agent_id=agent_id, graph_id="main")


def _record(
    record_id: str,
    title: str,
    *,
    namespace: MemoryNamespace | None = None,
    tags: list[str] | None = None,
    source_id: str | None = None,
) -> MemoryRecord:
    meta = {
        "properties": {
            "status": "active",
            "kind": "project",
            "priority": 5 if record_id.endswith("a") else 2,
        }
    }
    if source_id:
        meta["source_id"] = source_id
    return MemoryRecord(
        id=record_id,
        scope="agent:agent",
        type="fact",
        key=record_id,
        title=title,
        content={"text": title},
        tags=list(tags or []),
        created_at="2026-06-01T00:00:00+00:00",
        updated_at="2026-06-01T00:00:00+00:00",
        source="validated",
        namespace=namespace or _ns(),
        meta=meta,
    )


def _relation(
    relation_id: str,
    source: str,
    target: str,
    relation_type: str = "supports",
) -> MemoryRelation:
    return MemoryRelation(
        relation_id=relation_id,
        source_record_id=source,
        target_record_id=target,
        relation_type=relation_type,
        created_at="2026-06-01T00:00:00+00:00",
    )


def _link(
    link_id: str,
    source: str,
    target: str,
    relation_type: str = "supports",
    *,
    namespace: MemoryNamespace | None = None,
) -> StructuralLink:
    return StructuralLink(
        link_id=link_id,
        source_record_id=source,
        target_record_id=target,
        raw_target=target,
        link_kind="wikilink",
        resolution_status="resolved",
        relation_type=relation_type,
        namespace=namespace or _ns(),
        created_at="2026-06-01T00:00:00+00:00",
    )


@pytest.fixture(params=["memory", "sqlite"])
def store(request: pytest.FixtureRequest, tmp_path: Path):
    if request.param == "memory":
        s = SophiaGraphMemoryStore()
    else:
        s = SophiaGraphSqliteStore(tmp_path / "sg.sqlite3")
    namespace = _ns()
    other_namespace = _ns("other")
    for record in [
        _record(
            "rec-a",
            "Alpha decision",
            namespace=namespace,
            tags=["alpha"],
            source_id="src-1",
        ),
        _record("rec-b", "Beta implementation", namespace=namespace, tags=["alpha"]),
        _record("rec-c", "Gamma followup", namespace=namespace, tags=["alpha"]),
        _record("rec-d", "Delta isolated", namespace=namespace, tags=["delta"]),
        _record("rec-other", "Other namespace", namespace=other_namespace),
    ]:
        s.put_record(record)
    for relation in [
        _relation("rel-a-b", "rec-a", "rec-b", "supports"),
        _relation("rel-b-c", "rec-b", "rec-c", "supports"),
        _relation("rel-a-c", "rec-a", "rec-c", "related_to"),
        _relation("rel-other", "rec-other", "rec-a", "supports"),
    ]:
        s.put_relation(relation)
    for link in [
        _link("link-a-b", "rec-a", "rec-b", "supports", namespace=namespace),
        _link("link-b-c", "rec-b", "rec-c", "supports", namespace=namespace),
        _link("link-a-c", "rec-a", "rec-c", "related_to", namespace=namespace),
        _link(
            "link-other", "rec-other", "rec-a", "supports", namespace=other_namespace
        ),
    ]:
        s.put_link(link)
    return s


def test_community_dtos_validate_and_are_public() -> None:
    namespace = _ns()
    community = GraphCommunity(
        community_id="community-1",
        namespace=namespace,
        record_ids=["rec-a"],
        seed_record_id="rec-a",
    )

    assert community.namespace == namespace
    assert sophiagraph.GraphCommunity is GraphCommunity
    assert sophiagraph.CommunityDetectionOptions is CommunityDetectionOptions
    with pytest.raises(InvalidArgumentError):
        CommunityDetectionOptions(scopes=[], namespaces=[namespace])
    with pytest.raises(InvalidArgumentError):
        GraphCommunity(
            community_id="bad",
            namespace=namespace,
            record_ids=["rec-a"],
            seed_record_id="missing",
        )


def test_connected_components_and_label_propagation_are_deterministic(store) -> None:
    snapshot = store.get_graph_snapshot(
        GraphSnapshotOptions(scopes=["agent:agent"], namespaces=[_ns()])
    )
    connected_options = CommunityDetectionOptions(
        scopes=["agent:agent"],
        namespaces=[_ns()],
        relation_types=["supports"],
    )
    label_options = CommunityDetectionOptions(
        scopes=["agent:agent"],
        namespaces=[_ns()],
        algorithm="label_propagation",
        relation_types=["supports"],
    )

    communities, memberships = detect_communities(snapshot, connected_options)
    repeat, repeat_memberships = detect_communities(snapshot, connected_options)
    labels, _label_memberships = detect_communities(snapshot, label_options)

    assert [(item.record_ids, item.edge_ids) for item in communities] == [
        (item.record_ids, item.edge_ids) for item in repeat
    ]
    assert [(item.record_id, item.rank) for item in memberships] == [
        (item.record_id, item.rank) for item in repeat_memberships
    ]
    assert communities[0].record_ids == ["rec-a", "rec-b", "rec-c"]
    assert communities[0].seed_record_id == "rec-b"
    assert "rec-other" not in communities[0].record_ids
    assert labels[0].record_ids == ["rec-a", "rec-b", "rec-c"]


def test_community_snapshot_staleness_uses_changefeed_cursor(store) -> None:
    snapshot = build_community_snapshot(
        store,
        CommunityDetectionOptions(scopes=["agent:agent"], namespaces=[_ns()]),
    )
    unchanged = community_snapshot_status(store, snapshot)

    store.put_record(_record("rec-new", "New structural record", namespace=_ns()))
    changed = community_snapshot_status(store, snapshot)

    assert unchanged.stale is False
    assert changed.stale is True
    assert "record" in changed.stale_reasons


def test_query_communities_returns_source_sets_paths_and_summary_refs(store) -> None:
    result = query_communities(
        store,
        CommunityQueryOptions(
            detection=CommunityDetectionOptions(
                scopes=["agent:agent"],
                namespaces=[_ns()],
                relation_types=["supports"],
            ),
            query="decision",
            include_summary_refs=True,
            summary_reference_ids=["sum-caller-authored"],
            limit=10,
        ),
    )

    assert result.summary_reference_ids == ["sum-caller-authored"]
    assert [hit.record_id for hit in result.hits] == ["rec-a"]
    assert result.source_sets
    assert result.paths
    assert all("summary" not in community.meta for community in result.communities)
    assert result.query_plan is not None
    assert [stage.stage for stage in result.query_plan.stages] == [
        "communities",
        "records",
        "paths",
    ]


def test_pattern_query_executes_with_projection_and_backend_payload(store) -> None:
    query = GraphPatternQuery(
        query_id="pattern-1",
        scopes=["agent:agent"],
        namespaces=[_ns()],
        seed_record_ids=["rec-a"],
        node_predicates=[GraphPatternNodePredicate("tags", "contains", "alpha")],
        relation_types=["supports"],
        max_hops=2,
    )
    result = execute_graph_pattern_query(store, query)
    payload = pattern_query_to_backend_payload(query)

    assert payload["seed_record_ids"] == ["rec-a"]
    assert payload["relation_types"] == ["supports"]
    assert [match.record_ids for match in result.matches] == [
        ["rec-a", "rec-b"],
        ["rec-a", "rec-b", "rec-c"],
    ]
    assert result.matches[0].edge_ids == ["link-a-b"]
    assert result.matches[0].community_ids
    assert result.matches[0].properties["kind"] == "project"


def test_layout_hints_and_antillm_boundary_are_structural(store) -> None:
    snapshot = store.get_graph_snapshot(
        GraphSnapshotOptions(scopes=["agent:agent"], namespaces=[_ns()])
    )
    communities, _memberships = detect_communities(
        snapshot,
        CommunityDetectionOptions(scopes=["agent:agent"], namespaces=[_ns()]),
    )
    hints = layout_hints_for_snapshot(snapshot, communities)
    source = inspect.getsource(
        __import__("sophiagraph.query.community").query.community
    )

    assert {hint.record_id for hint in hints} >= {"rec-a", "rec-b", "rec-c"}
    for token in (
        "generate_community_summary",
        "text_to_cypher",
        "infer_topic",
        "summarize_community",
    ):
        assert re.search(token, source) is None
