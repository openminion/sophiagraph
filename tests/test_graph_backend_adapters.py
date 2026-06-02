from __future__ import annotations

from sophiagraph.graph_backends import (
    FakeGraphBackendAdapter,
    GraphBackendQuery,
    build_graph_export_batch,
)
from sophiagraph.models import (
    MemoryNamespace,
    MemoryRecord,
    MemoryRelation,
    StructuralLink,
)


def _ns() -> MemoryNamespace:
    return MemoryNamespace(tenant_id="tenant", agent_id="agent", graph_id="main")


def _record(record_id: str, title: str) -> MemoryRecord:
    return MemoryRecord(
        id=record_id,
        scope="agent:agent",
        type="fact",
        key=record_id,
        title=title,
        content={"text": title},
        created_at="2026-05-31T00:00:00+00:00",
        updated_at="2026-05-31T00:00:00+00:00",
        namespace=_ns(),
        meta={"properties": {"kind": "test"}},
    )


def test_graph_export_batch_contains_explicit_labels_relations_and_namespaces() -> None:
    records = [_record("rec-a", "A"), _record("rec-b", "B")]
    relation = MemoryRelation(
        relation_id="rel-a-b",
        source_record_id="rec-a",
        target_record_id="rec-b",
        relation_type="supports",
        created_at="2026-05-31T00:00:00+00:00",
    )
    link = StructuralLink(
        link_id="link-a-b",
        source_record_id="rec-a",
        target_record_id="rec-b",
        raw_target="B",
        link_kind="wikilink",
        resolution_status="resolved",
        relation_type="mentions",
        namespace=_ns(),
    )

    batch = build_graph_export_batch(
        batch_id="batch-1", records=records, relations=[relation], links=[link]
    )

    assert batch.schema.node_labels == ["fact"]
    assert batch.schema.relation_types == ["mentions", "supports"]
    assert {edge.relation_type for edge in batch.edges} == {"supports", "mentions"}
    assert all(node.namespace.agent_id == "agent" for node in batch.nodes)


def test_fake_backend_reports_unsupported_shortest_path_without_provider_sdk() -> None:
    batch = build_graph_export_batch(
        batch_id="batch-1",
        records=[_record("rec-a", "A"), _record("rec-b", "B")],
        relations=[
            MemoryRelation(
                relation_id="rel-a-b",
                source_record_id="rec-a",
                target_record_id="rec-b",
                relation_type="supports",
                created_at="2026-05-31T00:00:00+00:00",
            )
        ],
    )
    backend = FakeGraphBackendAdapter()
    backend.upsert_batch(batch)

    unsupported = backend.query(
        GraphBackendQuery(
            query_id="q-shortest",
            kind="shortest_path",
            start_node_id="rec-a",
            target_node_id="rec-b",
        )
    )
    neighbors = backend.query(
        GraphBackendQuery(
            query_id="q-neighbors",
            kind="neighbors",
            start_node_id="rec-a",
        )
    )

    assert unsupported.unsupported_reason == "shortest_path unsupported by backend"
    assert neighbors.rows[0].node_ids == ["rec-b"]
    assert backend.capabilities().supports("neighbors")


def test_fake_backend_negotiates_pattern_query_support() -> None:
    batch = build_graph_export_batch(
        batch_id="batch-1",
        records=[
            _record("rec-a", "A"),
            _record("rec-b", "B"),
            _record("rec-c", "C"),
        ],
        relations=[
            MemoryRelation(
                relation_id="rel-a-b",
                source_record_id="rec-a",
                target_record_id="rec-b",
                relation_type="supports",
                created_at="2026-05-31T00:00:00+00:00",
            ),
            MemoryRelation(
                relation_id="rel-b-c",
                source_record_id="rec-b",
                target_record_id="rec-c",
                relation_type="supports",
                created_at="2026-05-31T00:00:00+00:00",
            ),
        ],
    )
    unsupported = FakeGraphBackendAdapter()
    supported = FakeGraphBackendAdapter(support_pattern_query=True)
    unsupported.upsert_batch(batch)
    supported.upsert_batch(batch)
    query = GraphBackendQuery(
        query_id="q-pattern",
        kind="pattern",
        pattern_query={
            "seed_record_ids": ["rec-a"],
            "relation_types": ["supports"],
            "max_hops": 2,
        },
    )

    assert unsupported.query(query).unsupported_reason == (
        "pattern_query unsupported by backend"
    )
    assert supported.capabilities().supports("pattern_query")
    result = supported.query(query)
    assert result.unsupported_reason is None
    assert result.rows[0].node_ids == ["rec-a", "rec-b", "rec-c"]
    assert result.rows[0].edge_ids == ["rel-a-b", "rel-b-c"]
