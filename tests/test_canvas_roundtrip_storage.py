"""Canvas DTO, storage, changefeed, and relation-mapping tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from sophiagraph import (
    SophiaGraphMemoryStore,
    SophiaGraphSqliteStore,
)
from sophiagraph.canvas import (
    CanvasBoard,
    CanvasEdge,
    CanvasNode,
    canvas_board_from_dict,
    canvas_board_to_dict,
    canvas_edges_to_relations,
)
from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.models import MemoryNamespace


def _ns() -> MemoryNamespace:
    return MemoryNamespace(agent_id="canvas", session_id="s")


def _board(*, board_id: str = "board-1") -> CanvasBoard:
    return CanvasBoard(
        board_id=board_id,
        namespace=_ns(),
        nodes=[
            CanvasNode(
                id="n1",
                type="record",
                x=0,
                y=0,
                width=100,
                height=100,
                record_id="rec-1",
                color="#3498db",
            ),
            CanvasNode(
                id="n2",
                type="record",
                x=120,
                y=0,
                width=100,
                height=100,
                record_id="rec-2",
                label="title",
            ),
            CanvasNode(
                id="g1",
                type="group",
                x=0,
                y=0,
                width=240,
                height=120,
            ),
        ],
        edges=[
            CanvasEdge(
                id="e1",
                from_node="n1",
                to_node="n2",
                label="supports",
                color="#e74c3c",
                from_side="right",
                to_side="left",
                from_end="none",
                to_end="arrow",
            ),
        ],
    )


@pytest.fixture(params=["memory", "sqlite"])
def store(request, tmp_path: Path):
    if request.param == "memory":
        return SophiaGraphMemoryStore()
    return SophiaGraphSqliteStore(tmp_path / "canvas.sqlite3")


def test_canvas_node_supports_label_and_subpath_fields() -> None:
    node = CanvasNode(
        id="n1",
        type="file",
        x=0,
        y=0,
        width=10,
        height=10,
        file="vault/note.md",
        subpath="#heading",
        label="quick link",
    )
    assert node.subpath == "#heading"
    assert node.label == "quick link"


def test_canvas_edge_validates_from_side_and_to_side() -> None:
    CanvasEdge(
        id="e1",
        from_node="n1",
        to_node="n2",
        from_side="right",
        to_side="left",
    )
    with pytest.raises(InvalidArgumentError):
        CanvasEdge(
            id="e1",
            from_node="n1",
            to_node="n2",
            from_side="diagonal",  # type: ignore[arg-type]
        )


def test_canvas_edge_validates_from_end_and_to_end() -> None:
    CanvasEdge(
        id="e1",
        from_node="n1",
        to_node="n2",
        from_end="none",
        to_end="arrow",
    )
    with pytest.raises(InvalidArgumentError):
        CanvasEdge(
            id="e1",
            from_node="n1",
            to_node="n2",
            from_end="hook",  # type: ignore[arg-type]
        )


def test_canvas_board_to_dict_round_trips_extended_fields() -> None:
    board = _board()
    payload = canvas_board_to_dict(board)
    hydrated = canvas_board_from_dict(payload)
    assert hydrated.board_id == board.board_id
    assert len(hydrated.nodes) == len(board.nodes)
    assert hydrated.edges[0].from_side == "right"
    assert hydrated.edges[0].to_end == "arrow"
    assert hydrated.nodes[1].label == "title"


def test_canvas_board_from_camelcase_json_compat() -> None:
    raw_json = (
        '{"nodes":[{"id":"n1","type":"text","x":0,"y":0,"width":1,"height":1}],'
        '"edges":[{"id":"e1","fromNode":"n1","toNode":"n1",'
        '"fromSide":"right","toEnd":"arrow"}]}'
    )
    board = CanvasBoard.from_json(raw_json, board_id="b", namespace=_ns())
    assert board.edges[0].from_side == "right"
    assert board.edges[0].to_end == "arrow"


def test_put_canvas_board_round_trips(store) -> None:
    board = _board()
    returned_id = store.put_canvas_board(board)
    assert returned_id == "board-1"
    fetched = store.get_canvas_board("board-1")
    assert fetched is not None
    assert fetched.board_id == "board-1"
    assert len(fetched.nodes) == 3
    assert len(fetched.edges) == 1
    assert fetched.edges[0].from_side == "right"


def test_list_canvas_boards_filters_by_namespace(store) -> None:
    a = _board(board_id="board-a")
    b_other = CanvasBoard(
        board_id="board-b",
        namespace=MemoryNamespace(agent_id="other"),
        nodes=[],
        edges=[],
    )
    store.put_canvas_board(a)
    store.put_canvas_board(b_other)
    only_a = store.list_canvas_boards(namespaces=[_ns()])
    assert [x.board_id for x in only_a] == ["board-a"]
    all_rows = store.list_canvas_boards()
    assert {x.board_id for x in all_rows} == {"board-a", "board-b"}


def test_delete_canvas_board_returns_true_and_removes(store) -> None:
    store.put_canvas_board(_board())
    assert store.delete_canvas_board("board-1") is True
    assert store.get_canvas_board("board-1") is None
    assert store.delete_canvas_board("board-1") is False


def test_put_canvas_board_emits_changefeed_event(store) -> None:
    store.put_canvas_board(_board())
    events = store.list_changes()
    canvas_events = [e for e in events if e.object_type == "canvas"]
    assert canvas_events, "expected at least one canvas changefeed event"
    last = canvas_events[-1]
    assert last.object_id == "board-1"
    assert last.operation == "put"
    assert last.schema_identifiers["board_id"] == "board-1"


def test_delete_canvas_board_emits_delete_changefeed_event(store) -> None:
    store.put_canvas_board(_board())
    store.delete_canvas_board("board-1")
    events = [e for e in store.list_changes() if e.object_type == "canvas"]
    operations = [e.operation for e in events]
    assert "put" in operations
    assert "delete" in operations


def test_canvas_edges_to_relations_requires_explicit_relation_type() -> None:
    board = _board()
    assert (
        canvas_edges_to_relations(
            board, relation_type=None, created_at="2026-05-29T00:00:00+00:00"
        )
        == []
    )


def test_canvas_edges_to_relations_skips_edges_without_record_endpoints() -> None:
    """An edge whose endpoints are non-record nodes never becomes a relation."""

    board = CanvasBoard(
        board_id="b",
        namespace=_ns(),
        nodes=[
            CanvasNode(id="n1", type="text", x=0, y=0, width=1, height=1, text="x"),
            CanvasNode(id="n2", type="text", x=0, y=0, width=1, height=1, text="y"),
        ],
        edges=[CanvasEdge(id="e1", from_node="n1", to_node="n2")],
    )
    relations = canvas_edges_to_relations(
        board,
        relation_type="related_to",
        created_at="2026-05-29T00:00:00+00:00",
    )
    assert relations == []


def test_canvas_edges_to_relations_uses_caller_supplied_relation_type_only() -> None:
    """Even an edge labeled "supports" maps to relation_type="related_to" — the
    caller picks the relation type; SophiaGraph never infers from the label."""

    board = _board()
    relations = canvas_edges_to_relations(
        board,
        relation_type="related_to",
        created_at="2026-05-29T00:00:00+00:00",
    )
    assert len(relations) == 1
    assert relations[0].relation_type == "related_to"
    # The label "supports" is preserved as evidence in meta but NEVER as the
    # relation type itself.
    assert relations[0].meta["canvas_edge_id"] == "e1"
