from __future__ import annotations

import pytest

from sophiagraph import (
    CreationForm,
    MemoryNamespace,
    ObjectTemplate,
    SophiaGraphMemoryStore,
    TemplateField,
    apply_creation_plan,
    build_creation_plan,
)
from sophiagraph.contracts.errors import InvalidArgumentError


def _namespace() -> MemoryNamespace:
    return MemoryNamespace(agent_id="templates", graph_id="main")


def _template(kind: str = "record") -> ObjectTemplate:
    return ObjectTemplate(
        template_id="decision-template",
        object_kind=kind,  # type: ignore[arg-type]
        record_type="decision",
        scope="agent:templates",
        namespace=_namespace(),
        fields=(
            TemplateField("title", "str", required=True),
            TemplateField("risk", "str", default="low"),
            TemplateField("tags", "list", default=["reviewed"]),
        ),
        title_template="{title}",
        tags=("template",),
        ontology_id="decisions",
    )


def test_template_defaults_and_validation_are_explicit() -> None:
    form = CreationForm(
        template_id="decision-template",
        values={"title": "Ship v1"},
        actor="alice",
    )

    plan = build_creation_plan(_template(), form)

    assert plan.content == {
        "title": "Ship v1",
        "risk": "low",
        "tags": ["reviewed"],
    }
    assert plan.title == "Ship v1"
    assert plan.meta["template"]["actor"] == "alice"
    assert plan.meta["ontology"]["ontology_id"] == "decisions"


def test_template_rejects_unknown_or_missing_fields() -> None:
    with pytest.raises(InvalidArgumentError, match="missing required"):
        build_creation_plan(
            _template(),
            CreationForm(
                template_id="decision-template",
                values={},
                actor="alice",
            ),
        )
    with pytest.raises(InvalidArgumentError, match="unknown template fields"):
        build_creation_plan(
            _template(),
            CreationForm(
                template_id="decision-template",
                values={"title": "Ship v1", "extra": "not allowed"},
                actor="alice",
            ),
        )


def test_apply_creation_plan_uses_record_store_owner() -> None:
    store = SophiaGraphMemoryStore()
    plan = build_creation_plan(
        _template(),
        CreationForm(
            template_id="decision-template",
            values={"title": "Ship v1"},
            actor="alice",
        ),
    )

    result = apply_creation_plan(store, plan)
    record = store.get_record(result.record_id)

    assert result.object_kind == "record"
    assert record is not None
    assert record.type == "decision"
    assert record.content["risk"] == "low"
    assert record.meta["template"]["template_id"] == "decision-template"


def test_document_template_adds_document_metadata_without_parsing_prose() -> None:
    template = ObjectTemplate(
        template_id="doc-template",
        object_kind="document",
        record_type="artifact_digest",
        scope="agent:templates",
        namespace=_namespace(),
        fields=(
            TemplateField("path", "str", required=True),
            TemplateField("text", "str", required=True),
            TemplateField("aliases", "list", default=[]),
        ),
        title_template="{path}",
    )

    plan = build_creation_plan(
        template,
        CreationForm(
            template_id="doc-template",
            values={
                "path": "notes/alpha.md",
                "text": "# Alpha\n\nBody",
                "aliases": ["Alpha"],
            },
            actor="alice",
        ),
    )

    assert plan.meta["document"]["path"] == "notes/alpha.md"
    assert plan.meta["document"]["aliases"] == ["Alpha"]
    assert plan.meta["document"]["content_hash"]
