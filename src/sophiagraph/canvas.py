"""JSON Canvas-compatible DTOs and explicit relation mapping helpers."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from typing import Literal

from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.models import MemoryNamespace, MemoryRelation

CanvasNodeType = Literal["text", "file", "link", "group", "record"]

CanvasEdgeSide = Literal["top", "right", "bottom", "left"]
CanvasEdgeEnd = Literal["none", "arrow"]

_CANVAS_EDGE_SIDES = frozenset({"top", "right", "bottom", "left"})
_CANVAS_EDGE_ENDS = frozenset({"none", "arrow"})


@dataclass(frozen=True, slots=True)
class CanvasNode:
    id: str
    type: CanvasNodeType
    x: int
    y: int
    width: int
    height: int
    text: str | None = None
    file: str | None = None
    url: str | None = None
    record_id: str | None = None
    color: str | None = None
    subpath: str | None = None
    label: str | None = None

    def __post_init__(self) -> None:
        if not self.id:
            raise InvalidArgumentError("canvas node id is required")
        if self.width <= 0 or self.height <= 0:
            raise InvalidArgumentError("canvas node dimensions must be positive")


@dataclass(frozen=True, slots=True)
class CanvasEdge:
    id: str
    from_node: str
    to_node: str
    label: str | None = None
    color: str | None = None
    from_side: CanvasEdgeSide | None = None
    to_side: CanvasEdgeSide | None = None
    from_end: CanvasEdgeEnd | None = None
    to_end: CanvasEdgeEnd | None = None

    def __post_init__(self) -> None:
        if not self.id:
            raise InvalidArgumentError("canvas edge id is required")
        if not self.from_node or not self.to_node:
            raise InvalidArgumentError("canvas edge endpoints are required")
        if self.from_side is not None and self.from_side not in _CANVAS_EDGE_SIDES:
            raise InvalidArgumentError(
                f"unknown from_side: {self.from_side!r}; "
                f"allowed: {sorted(_CANVAS_EDGE_SIDES)}"
            )
        if self.to_side is not None and self.to_side not in _CANVAS_EDGE_SIDES:
            raise InvalidArgumentError(
                f"unknown to_side: {self.to_side!r}; "
                f"allowed: {sorted(_CANVAS_EDGE_SIDES)}"
            )
        if self.from_end is not None and self.from_end not in _CANVAS_EDGE_ENDS:
            raise InvalidArgumentError(
                f"unknown from_end: {self.from_end!r}; "
                f"allowed: {sorted(_CANVAS_EDGE_ENDS)}"
            )
        if self.to_end is not None and self.to_end not in _CANVAS_EDGE_ENDS:
            raise InvalidArgumentError(
                f"unknown to_end: {self.to_end!r}; allowed: {sorted(_CANVAS_EDGE_ENDS)}"
            )


@dataclass(frozen=True, slots=True)
class CanvasBoard:
    board_id: str
    namespace: MemoryNamespace
    nodes: list[CanvasNode] = field(default_factory=list)
    edges: list[CanvasEdge] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.board_id:
            raise InvalidArgumentError("board_id is required")

    def to_json(self) -> str:
        payload = {
            "nodes": [asdict(node) for node in self.nodes],
            "edges": [asdict(edge) for edge in self.edges],
        }
        return json.dumps(payload, sort_keys=True)

    @classmethod
    def from_json(
        cls,
        text: str,
        *,
        board_id: str,
        namespace: MemoryNamespace,
    ) -> "CanvasBoard":
        data = json.loads(text)
        nodes = [
            CanvasNode(
                id=str(item["id"]),
                type=str(item["type"]),  # type: ignore[arg-type]
                x=int(item["x"]),
                y=int(item["y"]),
                width=int(item["width"]),
                height=int(item["height"]),
                text=item.get("text"),
                file=item.get("file"),
                url=item.get("url"),
                record_id=item.get("record_id"),
                color=item.get("color"),
            )
            for item in data.get("nodes", [])
        ]
        edges = [
            CanvasEdge(
                id=str(item["id"]),
                from_node=str(
                    item["fromNode"] if "fromNode" in item else item["from_node"]
                ),
                to_node=str(item["toNode"] if "toNode" in item else item["to_node"]),
                label=item.get("label"),
                color=item.get("color"),
                from_side=item.get("fromSide") or item.get("from_side"),
                to_side=item.get("toSide") or item.get("to_side"),
                from_end=item.get("fromEnd") or item.get("from_end"),
                to_end=item.get("toEnd") or item.get("to_end"),
            )
            for item in data.get("edges", [])
        ]
        return cls(board_id=board_id, namespace=namespace, nodes=nodes, edges=edges)


def canvas_edges_to_relations(
    board: CanvasBoard,
    *,
    relation_type: str | None = None,
    created_at: str,
) -> list[MemoryRelation]:
    """Map canvas edges to graph relations only with explicit relation type."""
    if relation_type is None:
        return []
    node_records = {
        node.id: node.record_id for node in board.nodes if node.record_id is not None
    }
    relations: list[MemoryRelation] = []
    for edge in board.edges:
        source_id = node_records.get(edge.from_node)
        target_id = node_records.get(edge.to_node)
        if source_id is None or target_id is None:
            continue
        relations.append(
            MemoryRelation(
                relation_id=f"canvas-{board.board_id}-{edge.id}",
                source_record_id=source_id,
                target_record_id=target_id,
                relation_type=relation_type,  # type: ignore[arg-type]
                created_at=created_at,
                meta={"canvas_board_id": board.board_id, "canvas_edge_id": edge.id},
            )
        )
    return relations


def canvas_board_to_dict(board: "CanvasBoard") -> dict:
    """Serialize a board for cross-backend storage."""

    return {
        "board_id": board.board_id,
        "namespace": board.namespace.as_dict(),
        "nodes": [asdict(node) for node in board.nodes],
        "edges": [asdict(edge) for edge in board.edges],
    }


def canvas_board_from_dict(data: dict) -> "CanvasBoard":
    """Hydrate a board from a cross-backend storage row."""

    payload = dict(data)
    namespace = MemoryNamespace.from_dict(payload["namespace"])
    nodes = [CanvasNode(**dict(n)) for n in payload.get("nodes", [])]
    edges = [CanvasEdge(**dict(e)) for e in payload.get("edges", [])]
    return CanvasBoard(
        board_id=payload["board_id"],
        namespace=namespace,
        nodes=nodes,
        edges=edges,
    )


__all__ = [
    "CanvasBoard",
    "CanvasEdge",
    "CanvasEdgeEnd",
    "CanvasEdgeSide",
    "CanvasNode",
    "CanvasNodeType",
    "canvas_board_from_dict",
    "canvas_board_to_dict",
    "canvas_edges_to_relations",
]
