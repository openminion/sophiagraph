"""Ontology and category validation coverage."""

from __future__ import annotations

from pathlib import Path

import pytest

from sophiagraph import SophiaGraphMemoryStore, SophiaGraphSqliteStore
from sophiagraph.contracts.errors import (
    InvalidArgumentError,
    OntologyNotFoundError,
    OntologyValidationError,
    OntologyVersionConflictError,
)
from sophiagraph.models import (
    CategorySchema,
    EdgeTypeSchema,
    Entity,
    EntityTypeSchema,
    Fact,
    MemoryNamespace,
    MemoryRecord,
    MemoryRelation,
    OntologyDefinition,
    PropertySchema,
)
from sophiagraph.models.entity_fact import EntityFactProvenance
from sophiagraph.portability.codec import (
    read_bundle_snapshot,
    write_bundle_snapshot,
)
from sophiagraph.portability.models import (
    MemoryBundleExportOptions,
    MemoryBundleImportOptions,
)
from sophiagraph.storage.ontology_validator import (
    validate_entity_for_ontology,
    validate_fact_for_ontology,
    validate_record_for_ontology,
    validate_relation_for_ontology,
)


def _ns() -> MemoryNamespace:
    return MemoryNamespace(agent_id="alpha")


def _ns_b() -> MemoryNamespace:
    return MemoryNamespace(agent_id="beta")


def _coding_v1() -> OntologyDefinition:
    return OntologyDefinition(
        ontology_id="coding",
        version="1.0.0",
        owner="openminion-coding",
        namespace=_ns(),
        compatibility="fresh",
        categories=[
            CategorySchema(name="Function"),
            CategorySchema(name="Bug"),
        ],
        entity_types=[
            EntityTypeSchema(
                name="Function",
                properties=[
                    PropertySchema(name="language", value_type="str", required=True),
                    PropertySchema(name="line_count", value_type="int"),
                ],
            ),
            EntityTypeSchema(name="Bug"),
        ],
        edge_types=[
            EdgeTypeSchema(
                name="calls",
                source_entity_types=["Function"],
                target_entity_types=["Function"],
            ),
            EdgeTypeSchema(name="references"),
        ],
        created_at="2026-05-29T10:00:00+00:00",
    )


@pytest.fixture(params=["memory", "sqlite"])
def store(request, tmp_path: Path):
    s = (
        SophiaGraphMemoryStore()
        if request.param == "memory"
        else SophiaGraphSqliteStore(tmp_path / "sg.sqlite3")
    )
    s.put_ontology(_coding_v1())
    return s


def test_category_schema_requires_name() -> None:
    CategorySchema(name="x")
    with pytest.raises(InvalidArgumentError):
        CategorySchema(name="")


def test_property_schema_validates_value_type() -> None:
    PropertySchema(name="x", value_type="str")
    with pytest.raises(InvalidArgumentError):
        PropertySchema(name="x", value_type="cosmic")  # type: ignore[arg-type]


def test_entity_type_rejects_duplicate_property_names() -> None:
    with pytest.raises(InvalidArgumentError):
        EntityTypeSchema(
            name="X",
            properties=[
                PropertySchema(name="dup", value_type="str"),
                PropertySchema(name="dup", value_type="int"),
            ],
        )


def test_edge_type_rejects_duplicate_property_names() -> None:
    with pytest.raises(InvalidArgumentError):
        EdgeTypeSchema(
            name="rel",
            properties=[
                PropertySchema(name="dup", value_type="str"),
                PropertySchema(name="dup", value_type="int"),
            ],
        )


def test_ontology_rejects_duplicate_category() -> None:
    with pytest.raises(InvalidArgumentError):
        OntologyDefinition(
            ontology_id="x",
            version="1",
            owner="me",
            namespace=_ns(),
            categories=[CategorySchema(name="A"), CategorySchema(name="A")],
        )


def test_ontology_rejects_unknown_compatibility() -> None:
    with pytest.raises(InvalidArgumentError):
        OntologyDefinition(
            ontology_id="x",
            version="1",
            owner="me",
            namespace=_ns(),
            compatibility="cosmic",  # type: ignore[arg-type]
        )


def test_ontology_schema_key_property() -> None:
    o = _coding_v1()
    assert o.schema_key == ("coding", "1.0.0")


def test_record_validates_against_known_category(store) -> None:
    record = MemoryRecord(
        id="rec-1",
        scope="agent:alpha",
        type="fact",
        content="my code",
        created_at="2026-05-29T10:00:00+00:00",
        updated_at="2026-05-29T10:00:00+00:00",
        namespace=_ns(),
        meta={
            "ontology_category": "Function",
            "properties": {"language": "python", "line_count": 12},
        },
    )
    validate_record_for_ontology(store, record, ontology_id="coding", version="1.0.0")


def test_record_unknown_category_raises(store) -> None:
    record = MemoryRecord(
        id="rec-x",
        scope="agent:alpha",
        type="fact",
        content="x",
        created_at="2026-05-29T10:00:00+00:00",
        updated_at="2026-05-29T10:00:00+00:00",
        namespace=_ns(),
        meta={"ontology_category": "Spaceship"},
    )
    with pytest.raises(OntologyValidationError) as info:
        validate_record_for_ontology(
            store, record, ontology_id="coding", version="1.0.0"
        )
    assert info.value.code == "ONTOLOGY_VALIDATION_FAILED"


def test_record_missing_required_property_raises(store) -> None:
    record = MemoryRecord(
        id="rec-missing",
        scope="agent:alpha",
        type="fact",
        content="x",
        created_at="2026-05-29T10:00:00+00:00",
        updated_at="2026-05-29T10:00:00+00:00",
        namespace=_ns(),
        meta={
            "ontology_category": "Function",
            "properties": {"line_count": 5},  # missing required "language"
        },
    )
    with pytest.raises(OntologyValidationError) as info:
        validate_record_for_ontology(
            store, record, ontology_id="coding", version="1.0.0"
        )
    assert "language" in info.value.details["missing_property"]


def test_record_property_type_mismatch_raises(store) -> None:
    record = MemoryRecord(
        id="rec-mistype",
        scope="agent:alpha",
        type="fact",
        content="x",
        created_at="2026-05-29T10:00:00+00:00",
        updated_at="2026-05-29T10:00:00+00:00",
        namespace=_ns(),
        meta={
            "ontology_category": "Function",
            "properties": {"language": "python", "line_count": "twelve"},
        },
    )
    with pytest.raises(OntologyValidationError):
        validate_record_for_ontology(
            store, record, ontology_id="coding", version="1.0.0"
        )


def test_entity_validates_against_known_entity_type(store) -> None:
    e = Entity(
        entity_id="ent-1",
        canonical_name="parse_args",
        namespace=_ns(),
        provenance=EntityFactProvenance(
            source_kind="tool_observation", source_id="x", actor="agent"
        ),
        entity_type="Function",
        meta={"language": "python"},
    )
    validate_entity_for_ontology(store, e, ontology_id="coding", version="1.0.0")


def test_entity_unknown_type_raises(store) -> None:
    e = Entity(
        entity_id="ent-2",
        canonical_name="X",
        namespace=_ns(),
        provenance=EntityFactProvenance(
            source_kind="tool_observation", source_id="x", actor="agent"
        ),
        entity_type="Spaceship",
    )
    with pytest.raises(OntologyValidationError):
        validate_entity_for_ontology(store, e, ontology_id="coding", version="1.0.0")


def test_fact_predicate_unknown_raises(store) -> None:
    f = Fact(
        fact_id="f-1",
        namespace=_ns(),
        subject_entity_id="ent-1",
        predicate="hallucinates_from",
        object_entity_id="ent-2",
        provenance=EntityFactProvenance(
            source_kind="tool_observation", source_id="x", actor="agent"
        ),
        observed_at="2026-05-29T10:00:00+00:00",
    )
    with pytest.raises(OntologyValidationError):
        validate_fact_for_ontology(store, f, ontology_id="coding", version="1.0.0")


def test_fact_known_predicate_validates(store) -> None:
    f = Fact(
        fact_id="f-1",
        namespace=_ns(),
        subject_entity_id="ent-1",
        predicate="calls",
        object_entity_id="ent-2",
        provenance=EntityFactProvenance(
            source_kind="tool_observation", source_id="x", actor="agent"
        ),
        observed_at="2026-05-29T10:00:00+00:00",
    )
    validate_fact_for_ontology(store, f, ontology_id="coding", version="1.0.0")


def test_relation_unknown_type_raises(store) -> None:
    # "related_to" is a valid MemoryRelationType literal but is NOT one of
    # the edge_types declared in the coding ontology — exactly the case
    # the validator must catch.
    r = MemoryRelation(
        relation_id="rel-1",
        source_record_id="rec-a",
        target_record_id="rec-b",
        relation_type="related_to",
        created_at="2026-05-29T10:00:00+00:00",
    )
    with pytest.raises(OntologyValidationError):
        validate_relation_for_ontology(store, r, ontology_id="coding", version="1.0.0")


def test_validator_resolves_unknown_ontology_with_typed_error(store) -> None:
    record = MemoryRecord(
        id="rec-x",
        scope="agent:alpha",
        type="fact",
        content="x",
        created_at="2026-05-29T10:00:00+00:00",
        updated_at="2026-05-29T10:00:00+00:00",
        namespace=_ns(),
    )
    with pytest.raises(OntologyNotFoundError):
        validate_record_for_ontology(
            store, record, ontology_id="ghost", version="9.9.9"
        )


def test_re_registering_different_payload_raises_version_conflict(store) -> None:
    rewritten = OntologyDefinition(
        ontology_id="coding",
        version="1.0.0",  # same version
        owner="openminion-coding",
        namespace=_ns(),
        categories=[CategorySchema(name="DifferentCategory")],  # different payload
    )
    with pytest.raises(OntologyVersionConflictError):
        store.put_ontology(rewritten)


def test_re_registering_same_payload_idempotent(store) -> None:
    # No error.
    store.put_ontology(_coding_v1())
    fetched = store.get_ontology(ontology_id="coding", version="1.0.0")
    assert fetched is not None


def test_list_ontologies_namespace_isolation(tmp_path: Path) -> None:
    s = SophiaGraphSqliteStore(tmp_path / "sg.sqlite3")
    s.put_ontology(_coding_v1())
    s.put_ontology(
        OntologyDefinition(
            ontology_id="research",
            version="1.0.0",
            owner="openminion-research",
            namespace=_ns_b(),
        )
    )
    only_a = s.list_ontologies(namespaces=[_ns()])
    only_b = s.list_ontologies(namespaces=[_ns_b()])
    assert [o.ontology_id for o in only_a] == ["coding"]
    assert [o.ontology_id for o in only_b] == ["research"]


def test_bundle_round_trips_ontology_section(tmp_path: Path) -> None:
    source = SophiaGraphSqliteStore(tmp_path / "src.sqlite3")
    source.put_ontology(_coding_v1())
    snapshot = source.export_snapshot(
        MemoryBundleExportOptions(scopes=[], include_ontologies=True)
    )
    assert [o.ontology_id for o in snapshot.ontologies] == ["coding"]
    bundle_path = write_bundle_snapshot(snapshot, tmp_path / "bundle.tar.gz")
    rehydrated = read_bundle_snapshot(bundle_path)
    assert [o.ontology_id for o in rehydrated.ontologies] == ["coding"]

    target = SophiaGraphMemoryStore()
    result = target.import_snapshot(rehydrated, MemoryBundleImportOptions())
    assert result.imported_ontologies == 1
    assert target.get_ontology(ontology_id="coding", version="1.0.0") is not None


def test_bundle_without_ontology_section_still_loads(tmp_path: Path) -> None:
    """Backward compat: existing bundles must keep working."""
    source = SophiaGraphSqliteStore(tmp_path / "src.sqlite3")
    snapshot = source.export_snapshot(MemoryBundleExportOptions(scopes=[]))
    assert snapshot.ontologies == []
    bundle_path = write_bundle_snapshot(snapshot, tmp_path / "bundle.tar.gz")
    rehydrated = read_bundle_snapshot(bundle_path)
    assert rehydrated.ontologies == []


# Anti-LLM boundary


def test_anti_llm_no_inference_helpers_on_ontology_module() -> None:
    from sophiagraph.models import ontology as mod

    forbidden = {
        "infer_categories_from_prose",
        "auto_classify_record",
        "guess_entity_type",
        "summarize_ontology",
    }
    assert set(mod.__all__) & forbidden == set()
