from __future__ import annotations

import pytest

from sophiagraph import (
    KnowledgeDocumentBlock,
    KnowledgeExplorerFilters,
    KnowledgeExplorerRequest,
    LinkQueryOptions,
    MemoryNamespace,
    MemoryRecord,
    SavedExplorerView,
    StructuralLink,
    evaluate_saved_explorer_view,
    explore_knowledge,
)
from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.storage import SophiaGraphMemoryStore, SophiaGraphSqliteStore


@pytest.fixture(params=["memory", "sqlite"])
def store(request: pytest.FixtureRequest, tmp_path):
    if request.param == "memory":
        return SophiaGraphMemoryStore()
    return SophiaGraphSqliteStore(tmp_path / "sophiagraph.sqlite3")


def _namespace(agent: str = "agent-a") -> MemoryNamespace:
    return MemoryNamespace(tenant_id="tenant-a", agent_id=agent, graph_id="main")


def _record(
    record_id: str,
    title: str,
    text: str,
    *,
    namespace: MemoryNamespace | None = None,
    tags: list[str] | None = None,
    valid_to: str | None = None,
    source: str = "validated",
) -> MemoryRecord:
    return MemoryRecord(
        id=record_id,
        scope="agent:agent-a",
        type="fact",
        key=record_id,
        title=title,
        content={"text": text},
        tags=list(tags or []),
        created_at="2026-05-01T00:00:00+00:00",
        updated_at="2026-05-02T00:00:00+00:00",
        event_time="2026-05-01T00:00:00+00:00",
        valid_to=valid_to,
        source=source,  # type: ignore[arg-type]
        confidence=0.9,
        namespace=namespace or _namespace(),
        meta={
            "aliases": [f"{title} Alias"],
            "document": {
                "path": f"{record_id}.md",
                "title": title,
            },
            "properties": {
                "status": "accepted",
            },
        },
    )


def _link(
    link_id: str,
    source: str,
    target: str,
    raw_target: str,
    *,
    namespace: MemoryNamespace | None = None,
    before: str = "",
    after: str = "",
) -> StructuralLink:
    return StructuralLink(
        link_id=link_id,
        source_record_id=source,
        target_record_id=target,
        raw_target=raw_target,
        link_kind="wikilink",
        resolution_status="resolved",
        namespace=namespace or _namespace(),
        context_before=before,
        context_after=after,
        relation_type="supports",
        created_at="2026-05-03T00:00:00+00:00",
    )


def _seed_graph(store) -> None:
    ns = _namespace()
    for record in [
        _record(
            "auth",
            "Auth Decision",
            "We chose JWT auth.",
            namespace=ns,
            tags=["security"],
        ),
        _record(
            "refresh",
            "Refresh Token Plan",
            "Refresh tokens extend the JWT decision.",
            namespace=ns,
            tags=["security", "tokens"],
        ),
        _record(
            "notes",
            "Implementation Notes",
            "These notes reference Auth Decision directly.",
            namespace=ns,
            tags=["implementation"],
        ),
        _record(
            "onboarding",
            "Onboarding Guide",
            "Guide for new engineers.",
            namespace=ns,
            tags=["docs"],
        ),
    ]:
        store.put_record(record)
    store.put_link(
        _link(
            "link-auth-refresh",
            "auth",
            "refresh",
            "Refresh Token Plan",
            before="See ",
            after=" before launch.",
        )
    )
    store.put_link(
        _link(
            "link-notes-auth",
            "notes",
            "auth",
            "Auth Decision",
            before="Depends on ",
            after=" for security.",
        )
    )
    store.put_document_blocks(
        "onboarding",
        [
            KnowledgeDocumentBlock(
                block_id="block-onboarding-heading",
                document_id="onboarding",
                record_id="onboarding",
                block_type="heading",
                anchor="Onboarding Guide",
                excerpt="Onboarding Guide",
            )
        ],
    )


def test_explorer_packet_combines_search_graph_links_paths_and_facets(store) -> None:
    _seed_graph(store)

    result = explore_knowledge(
        store,
        KnowledgeExplorerRequest(
            scopes=["agent:agent-a"],
            namespaces=[_namespace()],
            query="Refresh",
            root_record_id="auth",
            include_query_plan=True,
            depth=1,
            limit=10,
        ),
    )

    assert [hit.record_id for hit in result.hits] == ["refresh"]
    assert result.graph is not None
    assert {node.record_id for node in result.graph.nodes} >= {
        "auth",
        "refresh",
        "notes",
    }
    assert [link.link_id for link in result.backlinks] == ["link-notes-auth"]
    assert [link.link_id for link in result.outgoing_links] == ["link-auth-refresh"]
    assert [path.record_ids for path in result.paths] == [["auth", "refresh"]]
    assert ("tag", "security") in {
        (facet.field, facet.value) for facet in result.facets
    }
    assert result.query_plan is not None
    assert {stage.stage for stage in result.query_plan.stages} >= {
        "search",
        "filters",
        "graph",
        "backlinks",
        "outgoing_links",
        "paths",
        "facets",
    }
    assert any(action.action == "inspect_path" for action in result.navigation)


def test_explorer_packet_can_include_structural_communities(store) -> None:
    _seed_graph(store)

    result = explore_knowledge(
        store,
        KnowledgeExplorerRequest(
            scopes=["agent:agent-a"],
            namespaces=[_namespace()],
            query="Refresh",
            root_record_id="auth",
            include_communities=True,
            include_query_plan=True,
            limit=10,
        ),
    )

    assert result.communities
    assert result.source_sets
    assert result.layout_hints
    assert any(facet.field == "community" for facet in result.facets)
    assert any(action.action == "open_community" for action in result.navigation)
    assert any(action.action == "filter_community" for action in result.navigation)
    assert result.query_plan is not None
    assert "communities" in {stage.stage for stage in result.query_plan.stages}


def test_explorer_filters_facets_and_namespace_isolation(store) -> None:
    _seed_graph(store)
    other_ns = _namespace("agent-b")
    store.put_record(
        _record(
            "other",
            "Refresh Token Outside",
            "Refresh belongs to another namespace.",
            namespace=other_ns,
        )
    )

    result = explore_knowledge(
        store,
        KnowledgeExplorerRequest(
            scopes=["agent:agent-a"],
            namespaces=[_namespace()],
            query="Refresh",
            filters=KnowledgeExplorerFilters(tags=["tokens"]),
        ),
    )

    assert [hit.record_id for hit in result.hits] == ["refresh"]
    assert "other" not in {hit.record_id for hit in result.hits}
    assert any(
        facet.field == "source" and facet.value == "validated"
        for facet in result.facets
    )


def test_explorer_can_filter_orphan_records(store) -> None:
    _seed_graph(store)

    result = explore_knowledge(
        store,
        KnowledgeExplorerRequest(
            scopes=["agent:agent-a"],
            namespaces=[_namespace()],
            filters=KnowledgeExplorerFilters(include_orphans=False),
            include_graph=False,
            limit=10,
        ),
    )

    assert "onboarding" not in {hit.record_id for hit in result.hits}
    assert {"auth", "refresh", "notes"}.issubset({hit.record_id for hit in result.hits})


def test_unlinked_mentions_are_candidates_not_persisted_edges(store) -> None:
    _seed_graph(store)
    store.put_record(
        _record(
            "daily",
            "Daily Note",
            "Discuss Onboarding Guide before tomorrow.",
            tags=["daily"],
        )
    )
    before = store.list_links(
        LinkQueryOptions(
            record_id="daily",
            direction="out",
            namespaces=[_namespace()],
        )
    )

    result = explore_knowledge(
        store,
        KnowledgeExplorerRequest(
            scopes=["agent:agent-a"],
            namespaces=[_namespace()],
            root_record_id="daily",
            include_unlinked_mentions=True,
            include_graph=False,
            limit=10,
        ),
    )
    after = store.list_links(
        LinkQueryOptions(
            record_id="daily",
            direction="out",
            namespaces=[_namespace()],
        )
    )

    assert before == after == []
    candidate = next(
        mention
        for mention in result.unlinked_mentions
        if mention.target_record_id == "onboarding"
    )
    assert candidate.match_kind in {"title", "heading"}
    assert any(
        action.action == "apply_repair_candidate"
        and action.candidate_id == candidate.candidate_id
        for action in result.navigation
    )


def test_saved_explorer_view_replays_request(store) -> None:
    _seed_graph(store)
    view = SavedExplorerView(
        view_id="view-security",
        name="Security graph",
        request=KnowledgeExplorerRequest(
            scopes=["agent:agent-a"],
            namespaces=[_namespace()],
            query="Refresh",
            filters=KnowledgeExplorerFilters(tags=["security"]),
            root_record_id="auth",
        ),
    )

    result = evaluate_saved_explorer_view(store, view)

    assert [hit.record_id for hit in result.hits] == ["refresh"]
    assert result.graph is not None


def test_temporal_explorer_filters_records(store) -> None:
    ns = _namespace()
    store.put_record(
        _record(
            "old",
            "Old Fact",
            "Temporal fact",
            namespace=ns,
            valid_to="2026-05-10T00:00:00+00:00",
        )
    )

    before = explore_knowledge(
        store,
        KnowledgeExplorerRequest(
            scopes=["agent:agent-a"],
            namespaces=[ns],
            valid_at="2026-05-05T00:00:00+00:00",
            include_graph=False,
        ),
    )
    after = explore_knowledge(
        store,
        KnowledgeExplorerRequest(
            scopes=["agent:agent-a"],
            namespaces=[ns],
            valid_at="2026-05-11T00:00:00+00:00",
            include_graph=False,
        ),
    )

    assert [hit.record_id for hit in before.hits] == ["old"]
    assert after.hits == []


def test_explorer_dtos_reject_invalid_values() -> None:
    with pytest.raises(InvalidArgumentError, match="at least one scope"):
        KnowledgeExplorerRequest(scopes=[])
    with pytest.raises(InvalidArgumentError, match="cursor"):
        KnowledgeExplorerRequest(scopes=["agent:agent-a"], cursor="next")
    with pytest.raises(InvalidArgumentError, match="types"):
        KnowledgeExplorerFilters(types=[""])
