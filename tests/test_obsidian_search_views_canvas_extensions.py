from __future__ import annotations

import pytest

from sophiagraph.canvas import (
    CanvasBoard,
    CanvasEdge,
    CanvasNode,
    canvas_edges_to_relations,
)
from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.extensions import SophiaGraphExtensionRegistry
from sophiagraph.models import MemoryNamespace, MemoryRecord
from sophiagraph.query import parse_structural_query
from sophiagraph.views import SavedViewDefinition, evaluate_saved_view


def _namespace() -> MemoryNamespace:
    return MemoryNamespace(agent_id="agent", graph_id="main")


def test_structural_query_parser_accepts_supported_operators() -> None:
    query = parse_structural_query(
        'tag:#project [status:active] path:Roadmap link_to:Target "exact phrase"'
    )

    assert query.tags == ["project"]
    assert query.properties == {"status": "active"}
    assert query.path == "Roadmap"
    assert query.link_to == "Target"
    assert query.exact_phrases == ["exact phrase"]


def test_structural_query_parser_rejects_unsupported_operator() -> None:
    with pytest.raises(InvalidArgumentError, match="unsupported"):
        parse_structural_query("near:Roadmap")


def test_saved_view_evaluation_returns_deterministic_projected_rows() -> None:
    record = MemoryRecord(
        id="rec-1",
        scope="agent:agent",
        type="artifact_digest",
        title="Roadmap",
        content={"text": "body"},
        created_at="2026-05-23T00:00:00+00:00",
        updated_at="2026-05-23T00:00:00+00:00",
        namespace=_namespace(),
        meta={"properties": {"status": "active", "owner": "memory"}},
    )
    result = evaluate_saved_view(
        [record],
        SavedViewDefinition(
            view_id="view-1",
            name="Active",
            projected_properties=["status"],
        ),
    )

    assert result.rows[0].record_id == "rec-1"
    assert result.rows[0].properties == {"status": "active"}


def test_canvas_round_trips_and_requires_explicit_relation_type() -> None:
    namespace = _namespace()
    board = CanvasBoard(
        board_id="board-1",
        namespace=namespace,
        nodes=[
            CanvasNode(
                id="n1",
                type="record",
                x=0,
                y=0,
                width=100,
                height=100,
                record_id="rec-1",
            ),
            CanvasNode(
                id="n2",
                type="record",
                x=120,
                y=0,
                width=100,
                height=100,
                record_id="rec-2",
            ),
        ],
        edges=[CanvasEdge(id="e1", from_node="n1", to_node="n2", label="supports")],
    )

    imported = CanvasBoard.from_json(
        board.to_json(),
        board_id="board-1",
        namespace=namespace,
    )

    assert imported.nodes[0].record_id == "rec-1"
    assert (
        canvas_edges_to_relations(
            imported,
            relation_type=None,
            created_at="2026-05-23T00:00:00+00:00",
        )
        == []
    )
    assert (
        canvas_edges_to_relations(
            imported,
            relation_type="related_to",
            created_at="2026-05-23T00:00:00+00:00",
        )[0].relation_type
        == "related_to"
    )


def test_extension_registry_is_package_local() -> None:
    registry = SophiaGraphExtensionRegistry()
    registry.register_importer("markdown", lambda payload, **_: payload)
    registry.register_exporter("markdown", lambda payload, **_: str(payload))

    assert "markdown" in registry.importers
    assert registry.exporters["markdown"]("ok") == "ok"
