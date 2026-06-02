from __future__ import annotations

from dataclasses import asdict

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

from sophiagraph.views import (
    SavedViewDefinition,
    SavedViewFilter,
    SavedViewFilterGroup,
    SavedViewSummary,
    evaluate_saved_view,
)


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


def test_saved_view_evaluator_filters_groups_sorts_summarizes_and_preserves_records() -> (
    None
):
    records = [
        MemoryRecord(
            id="rec-1",
            scope="agent:agent",
            type="artifact_digest",
            title="Roadmap",
            content={"text": "body"},
            tags=["project"],
            created_at="2026-05-23T00:00:00+00:00",
            updated_at="2026-05-23T00:00:00+00:00",
            namespace=_namespace(),
            meta={"properties": {"status": "active", "owner": "memory", "score": 7}},
        ),
        MemoryRecord(
            id="rec-2",
            scope="agent:agent",
            type="artifact_digest",
            title="Inbox",
            content={"text": "body"},
            tags=["project"],
            created_at="2026-05-23T00:00:00+00:00",
            updated_at="2026-05-23T00:00:00+00:00",
            namespace=_namespace(),
            meta={"properties": {"status": "active", "owner": "runtime", "score": 3}},
        ),
        MemoryRecord(
            id="rec-3",
            scope="agent:agent",
            type="artifact_digest",
            title="Archive",
            content={"text": "body"},
            tags=["done"],
            created_at="2026-05-23T00:00:00+00:00",
            updated_at="2026-05-23T00:00:00+00:00",
            namespace=_namespace(),
            meta={"properties": {"status": "archived", "owner": "memory", "score": 1}},
        ),
    ]
    before = [asdict(record) for record in records]

    result = evaluate_saved_view(
        records,
        SavedViewDefinition(
            view_id="view-active",
            name="Active projects",
            filters=SavedViewFilterGroup(
                operator="and",
                filters=[
                    SavedViewFilter("status", "eq", "active"),
                    SavedViewFilter("tags", "contains", "project"),
                    SavedViewFilter("score", "gte", 3),
                ],
            ),
            projected_properties=["owner", "score"],
            sort="-score",
            group_by="owner",
            summaries=[
                SavedViewSummary("count"),
                SavedViewSummary("sum", field="score", label="score_total"),
                SavedViewSummary("avg", field="score", label="score_avg"),
            ],
        ),
    )

    assert [row.record_id for row in result.rows] == ["rec-1", "rec-2"]
    assert result.groups == {"memory": ["rec-1"], "runtime": ["rec-2"]}
    assert result.summaries == {"count": 2, "score_total": 10.0, "score_avg": 5.0}
    assert [asdict(record) for record in records] == before


def test_saved_view_evaluator_supports_or_and_link_predicates() -> None:
    records = [
        MemoryRecord(
            id="rec-1",
            scope="agent:agent",
            type="artifact_digest",
            title="Roadmap",
            content={"text": "body"},
            created_at="2026-05-23T00:00:00+00:00",
            updated_at="2026-05-23T00:00:00+00:00",
            namespace=_namespace(),
            meta={"properties": {"status": "blocked"}},
        ),
        MemoryRecord(
            id="rec-2",
            scope="agent:agent",
            type="artifact_digest",
            title="Spec",
            content={"text": "body"},
            created_at="2026-05-23T00:00:00+00:00",
            updated_at="2026-05-23T00:00:00+00:00",
            namespace=_namespace(),
            meta={"properties": {"status": "active"}},
        ),
    ]

    result = evaluate_saved_view(
        records,
        SavedViewDefinition(
            view_id="view-links",
            name="Linked",
            filters=SavedViewFilterGroup(
                operator="or",
                filters=[
                    SavedViewFilter("status", "eq", "done"),
                    SavedViewFilter("links", "link_to", "rec-target"),
                ],
            ),
        ),
        link_context={"rec-1": {"link_to": ["rec-target"]}},
    )

    assert [row.record_id for row in result.rows] == ["rec-1"]


def test_saved_view_evaluator_rejects_type_errors_and_unsafe_formulas() -> None:
    record = MemoryRecord(
        id="rec-1",
        scope="agent:agent",
        type="artifact_digest",
        title="Roadmap",
        content={"text": "body"},
        created_at="2026-05-23T00:00:00+00:00",
        updated_at="2026-05-23T00:00:00+00:00",
        namespace=_namespace(),
        meta={
            "properties": {
                "status": "active",
                "score": 4,
                "weight": 3,
                "updated_cutoff": "2026-05-22T00:00:00+00:00",
            }
        },
    )

    with pytest.raises(InvalidArgumentError, match="in filters require"):
        evaluate_saved_view(
            [record],
            SavedViewDefinition(
                view_id="bad-in",
                name="Bad",
                filters=SavedViewFilter("status", "in", "active"),
            ),
        )
    result = evaluate_saved_view(
        [record],
        SavedViewDefinition(
            view_id="formula",
            name="Formula",
            projected_properties=["formula"],
            formula="score * weight + len(status)",
        ),
    )
    timestamp_result = evaluate_saved_view(
        [record],
        SavedViewDefinition(
            view_id="timestamp-formula",
            name="Timestamp Formula",
            projected_properties=["formula"],
            formula="updated > updated_cutoff",
        ),
    )

    assert result.rows[0].properties["formula"] == 18
    assert timestamp_result.rows[0].properties["formula"] is True
    for formula in (
        "__import__('os').system('echo bad')",
        "status.upper()",
        "missing + 1",
    ):
        with pytest.raises(InvalidArgumentError, match="formula|unknown"):
            evaluate_saved_view(
                [record],
                SavedViewDefinition(
                    view_id=f"bad-{formula}",
                    name="Bad",
                    formula=formula,
                ),
            )
    with pytest.raises(InvalidArgumentError, match="invalid formula syntax"):
        evaluate_saved_view(
            [record],
            SavedViewDefinition(
                view_id="bad-syntax",
                name="Formula",
                formula="status = active",
            ),
        )


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


def test_extension_registry_rejects_blank_names_with_package_error() -> None:
    registry = SophiaGraphExtensionRegistry()

    with pytest.raises(InvalidArgumentError, match="extension name is required"):
        registry.register_importer(" ", lambda payload, **_: payload)
