from __future__ import annotations

import pytest

from sophiagraph.models import (
    MemoryCandidate,
    MemoryNamespace,
    MemoryRecord,
    MemoryRelation,
    MemoryTierTransition,
    StructuralLink,
)
from sophiagraph.portability.models import (
    MemoryBundleExportOptions,
    MemoryBundleImportOptions,
)
from sophiagraph.query import LinkQueryOptions, ListQueryOptions, SearchQueryOptions
from sophiagraph.storage import SophiaGraphMemoryStore, SophiaGraphSqliteStore


@pytest.fixture(params=["memory", "sqlite"])
def store(request, tmp_path):
    if request.param == "memory":
        return SophiaGraphMemoryStore()
    return SophiaGraphSqliteStore(tmp_path / "sophiagraph.sqlite3")


def _namespace(agent_id: str, *, tenant_id: str = "tenant") -> MemoryNamespace:
    return MemoryNamespace(
        tenant_id=tenant_id,
        user_id="user",
        agent_id=agent_id,
        session_id=f"session-{agent_id}",
        project_id="project",
        graph_id="main",
    )


def _record(record_id: str, namespace: MemoryNamespace) -> MemoryRecord:
    return MemoryRecord(
        id=record_id,
        scope=f"agent:{namespace.agent_id}",
        type="fact",
        key=f"fact:{record_id}",
        title=f"Title {record_id}",
        content={"text": f"{record_id} body"},
        tags=[f"tag-{namespace.agent_id}"],
        created_at="2026-05-25T00:00:00+00:00",
        updated_at="2026-05-25T00:00:00+00:00",
        event_time="2026-05-25T00:00:00+00:00",
        source="validated",
        namespace=namespace,
    )


def _link(source: str, target: str, namespace: MemoryNamespace) -> StructuralLink:
    return StructuralLink(
        link_id=f"link-{source}-{target}",
        source_record_id=source,
        target_record_id=target,
        raw_target=target,
        link_kind="wikilink",
        resolution_status="resolved",
        relation_type="supports",
        namespace=namespace,
        created_at="2026-05-25T00:00:00+00:00",
    )


def test_shared_store_contract_parity_for_crud_query_export_import(
    store, tmp_path
) -> None:
    alpha = _namespace("alpha")
    beta = _namespace("beta")
    rec_alpha = _record("rec-alpha", alpha)
    rec_beta = _record("rec-beta", beta)
    store.put_record(rec_alpha)
    store.put_record(rec_beta)
    store.put_relation(
        MemoryRelation(
            relation_id="rel-alpha-beta",
            source_record_id=rec_alpha.id,
            target_record_id=rec_beta.id,
            relation_type="supports",
            created_at="2026-05-25T00:00:00+00:00",
        )
    )
    store.put_link(_link(rec_alpha.id, rec_beta.id, alpha))

    assert store.get_record("rec-alpha") == rec_alpha
    assert {
        record.id
        for record in store.search_records(
            SearchQueryOptions(query="body", scopes=["agent:alpha", "agent:beta"])
        )
    } == {
        "rec-beta",
        "rec-alpha",
    }
    assert [
        relation.relation_id
        for relation in store.list_relations("rec-alpha", direction="both")
    ] == ["rel-alpha-beta"]
    assert [
        link.link_id
        for link in store.list_links(
            LinkQueryOptions(
                record_id="rec-alpha", namespaces=[MemoryNamespace(agent_id="alpha")]
            )
        )
    ] == ["link-rec-alpha-rec-beta"]

    snapshot = store.export_snapshot(
        MemoryBundleExportOptions(
            scopes=["agent:alpha", "agent:beta"],
            include_relations=True,
            namespaces=[MemoryNamespace(agent_id="alpha")],
        )
    )
    assert [record.id for record in snapshot.records] == ["rec-alpha"]
    assert snapshot.relations == []

    dest = (
        SophiaGraphMemoryStore()
        if isinstance(store, SophiaGraphMemoryStore)
        else SophiaGraphSqliteStore(tmp_path / "dest.sqlite3")
    )
    result = dest.import_snapshot(snapshot, MemoryBundleImportOptions())
    assert result.imported_records == 1
    assert [
        record.id
        for record in dest.list_records(ListQueryOptions(scopes=["agent:alpha"]))
    ] == ["rec-alpha"]


def test_namespace_boundaries_cover_list_search_export_import_candidates_and_history(
    store,
    tmp_path,
) -> None:
    alpha = _namespace("alpha")
    beta = _namespace("beta")
    store.put_record(_record("rec-alpha", alpha))
    store.put_record(_record("rec-beta", beta))
    store.put_tier_transition(
        MemoryTierTransition(
            transition_id="tier-alpha",
            record_id="rec-alpha",
            scope="agent:alpha",
            record_type="fact",
            from_tier="working",
            to_tier="archival",
            transition_reason="manual_override",
            transition_at="2026-05-25T00:00:00+00:00",
        )
    )
    store.put_tier_transition(
        MemoryTierTransition(
            transition_id="tier-beta",
            record_id="rec-beta",
            scope="agent:beta",
            record_type="fact",
            from_tier="working",
            to_tier="archival",
            transition_reason="manual_override",
            transition_at="2026-05-25T00:00:00+00:00",
        )
    )
    candidate = MemoryCandidate(
        candidate_id="cand-alpha",
        session_id="session-alpha",
        proposed_scope="agent:alpha",
        type="fact",
        content={"text": "candidate"},
        namespace=alpha,
    )
    store.put_candidate(candidate)

    assert [
        record.id
        for record in store.list_records(
            ListQueryOptions(
                scopes=["agent:alpha", "agent:beta"],
                namespaces=[MemoryNamespace(agent_id="alpha")],
            )
        )
    ] == ["rec-alpha"]
    assert [
        record.id
        for record in store.search_records(
            SearchQueryOptions(
                query="body",
                scopes=["agent:alpha", "agent:beta"],
                namespaces=[MemoryNamespace(agent_id="beta")],
            )
        )
    ] == ["rec-beta"]
    assert [
        transition.transition_id
        for transition in store.list_tier_transitions(scopes=["agent:alpha"])
    ] == ["tier-alpha"]
    promoted = store.promote_candidate("cand-alpha", "agent:alpha")
    assert promoted.effective_namespace == alpha

    source_snapshot = store.export_snapshot(
        MemoryBundleExportOptions(scopes=["agent:alpha", "agent:beta"])
    )
    dest = (
        SophiaGraphMemoryStore()
        if isinstance(store, SophiaGraphMemoryStore)
        else SophiaGraphSqliteStore(tmp_path / "allowlist.sqlite3")
    )
    import_result = dest.import_snapshot(
        source_snapshot,
        MemoryBundleImportOptions(
            namespace_allowlist=[MemoryNamespace(agent_id="beta")]
        ),
    )
    assert import_result.imported_records == 1
    assert import_result.skipped_records >= 1
    assert [
        record.id
        for record in dest.list_records(ListQueryOptions(scopes=["agent:beta"]))
    ] == ["rec-beta"]


def test_namespace_is_never_inferred_from_title_content_tags_or_meta(store) -> None:
    explicit_namespace = MemoryNamespace(tenant_id="tenant-real", agent_id="alpha")
    prose_namespace = MemoryNamespace(tenant_id="tenant-prose", agent_id="beta")
    record = MemoryRecord(
        id="rec-prose",
        scope="agent:alpha",
        type="fact",
        key="fact:prose",
        title="tenant-prose beta namespace words",
        content={"text": "please do not infer tenant-prose or agent beta"},
        tags=["tenant-prose", "beta"],
        meta={"tenant_id": "tenant-prose", "agent_id": "beta"},
        created_at="2026-05-25T00:00:00+00:00",
        updated_at="2026-05-25T00:00:00+00:00",
        namespace=explicit_namespace,
    )
    store.put_record(record)
    candidate = MemoryCandidate(
        candidate_id="cand-prose",
        session_id="session-prose",
        proposed_scope="agent:alpha",
        type="fact",
        title="tenant-prose beta words",
        content="mentions tenant-prose and beta",
        tags=["tenant-prose", "beta"],
        meta={"tenant_id": "tenant-prose", "agent_id": "beta"},
        namespace=explicit_namespace,
    )
    store.put_candidate(candidate)

    assert (
        store.list_records(
            ListQueryOptions(scopes=["agent:alpha"], namespaces=[prose_namespace])
        )
        == []
    )
    assert [
        item.id
        for item in store.list_records(
            ListQueryOptions(
                scopes=["agent:alpha"],
                namespaces=[MemoryNamespace(tenant_id="tenant-real", agent_id="alpha")],
            )
        )
    ] == ["rec-prose"]
    assert store.get_candidate("cand-prose").namespace == explicit_namespace
    promoted = store.promote_candidate("cand-prose", "agent:alpha")
    assert promoted.effective_namespace == explicit_namespace
    assert promoted.meta["tenant_id"] == "tenant-prose"
    assert promoted.effective_namespace.tenant_id == "tenant-real"


def test_upsert_and_reopen_keep_single_durable_row(store, tmp_path) -> None:
    created = store.upsert_record(
        "agent:upsert",
        "fact",
        "fact:stable",
        {"title": "First", "content": {"text": "first"}},
    )
    updated = store.upsert_record(
        "agent:upsert",
        "fact",
        "fact:stable",
        {"title": "Second", "content": {"text": "second"}},
    )

    assert updated.id == created.id
    assert updated.title == "Second"
    assert [
        record.id for record in store.history("agent:upsert", "fact", "fact:stable")
    ] == [created.id]

    if isinstance(store, SophiaGraphSqliteStore):
        reopened = SophiaGraphSqliteStore(store.db_path)
        assert reopened.get_record(created.id).title == "Second"
    else:
        snapshot = store.export_snapshot(
            MemoryBundleExportOptions(scopes=["agent:upsert"])
        )
        reopened = SophiaGraphMemoryStore()
        reopened.import_snapshot(snapshot, MemoryBundleImportOptions())
        assert reopened.get_record(created.id).title == "Second"
