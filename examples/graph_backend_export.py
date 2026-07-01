"""Graph backend export example using the provider-free fake backend."""

from __future__ import annotations

import json

from sophiagraph import (
    FakeGraphBackendAdapter,
    GraphBackendQuery,
    MemoryNamespace,
    MemoryRecord,
    MemoryRelation,
    build_graph_export_batch,
)


def _record(record_id: str, title: str) -> MemoryRecord:
    namespace = MemoryNamespace(agent_id="example", graph_id="main")
    return MemoryRecord(
        id=record_id,
        scope="agent:example",
        type="fact",
        key=record_id,
        title=title,
        content={"text": title},
        created_at="2026-06-30T00:00:00+00:00",
        updated_at="2026-06-30T00:00:00+00:00",
        namespace=namespace,
        meta={"properties": {"kind": "example", "title": title}},
    )


def run_example() -> dict[str, object]:
    records = [_record("rec-a", "A"), _record("rec-b", "B")]
    relations = [
        MemoryRelation(
            relation_id="rel-a-b",
            source_record_id="rec-a",
            target_record_id="rec-b",
            relation_type="supports",
            created_at="2026-06-30T00:00:00+00:00",
        )
    ]
    batch = build_graph_export_batch(
        batch_id="example-batch",
        records=records,
        relations=relations,
    )
    backend = FakeGraphBackendAdapter(support_shortest_path=True)
    backend.upsert_batch(batch)
    result = backend.query(
        GraphBackendQuery(
            query_id="path",
            kind="shortest_path",
            start_node_id="rec-a",
            target_node_id="rec-b",
        )
    )

    return {
        "backend": backend.capabilities().backend_name,
        "node_count": len(batch.nodes),
        "edge_count": len(batch.edges),
        "path": result.rows[0].node_ids if result.rows else [],
    }


def main() -> int:
    print(json.dumps(run_example(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
