from __future__ import annotations

from sophiagraph.graph_backends import (
    FakeGraphBackendAdapter,
    GraphExportBatch,
    GraphExportEdge,
    GraphExportNode,
)
from sophiagraph.models import MemoryNamespace
from sophiagraph.schema import GraphSchema
from sophiagraph.vector_backends import FakeVectorBackend, VectorPoint, VectorQuery


def test_fake_graph_backend_replays_upserts_deletes_and_watermarks() -> None:
    namespace = MemoryNamespace(graph_id="main")
    backend = FakeGraphBackendAdapter()
    batch = GraphExportBatch(
        batch_id="batch-1",
        schema=GraphSchema(node_labels=["fact"], relation_types=["supports"]),
        nodes=[
            GraphExportNode("a", ["fact"], namespace, version_hash="v1"),
            GraphExportNode("b", ["fact"], namespace, version_hash="v1"),
        ],
        edges=[
            GraphExportEdge("edge", "a", "b", "supports", namespace, version_hash="v1")
        ],
    )
    backend.upsert_batch(batch)
    backend.upsert_batch(batch)
    backend.set_projection_watermark(7)
    assert backend.get_projection_watermark() == 7
    assert [(item.object_kind, item.object_id) for item in backend.inventory()] == [
        ("edge", "edge"),
        ("node", "a"),
        ("node", "b"),
    ]
    backend.delete(node_ids=("a",), edge_ids=())
    backend.delete(node_ids=("a",), edge_ids=("edge",))
    assert [item.object_id for item in backend.inventory()] == ["b"]


def test_fake_vector_backend_is_idempotent_and_inventory_aware() -> None:
    namespace = MemoryNamespace(graph_id="main")
    backend = FakeVectorBackend()
    point = VectorPoint(
        point_id="point",
        vector=(1.0, 0.0),
        vector_space="space",
        namespace=namespace,
        version_hash="v1",
    )
    backend.upsert((point,))
    backend.upsert((point,))
    backend.set_projection_watermark(8)
    assert backend.search(VectorQuery((1.0, 0.0), "space"))[0].point_id == "point"
    assert backend.get_projection_watermark() == 8
    assert backend.inventory()[0].version_hash == "v1"
    backend.delete(("point",))
    backend.delete(("point",))
    assert backend.inventory() == ()
