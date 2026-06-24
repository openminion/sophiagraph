"""Deterministic object templates and creation-plan helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any, Literal, Protocol
from uuid import uuid4

from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.models import MemoryNamespace, MemoryRecord
from sophiagraph.temporal import utc_now_iso

TemplateObjectKind = Literal["record", "document"]
TemplateFieldType = Literal["str", "int", "float", "bool", "list", "dict"]


class TemplateCreationStore(Protocol):
    """Store subset used by template creation helpers."""

    def put_record(self, record: MemoryRecord) -> str: ...


@dataclass(frozen=True, slots=True)
class TemplateField:
    """One explicit field accepted by an object template."""

    name: str
    value_type: TemplateFieldType
    required: bool = False
    default: Any = None
    description: str = ""

    def __post_init__(self) -> None:
        if not self.name:
            raise InvalidArgumentError("field name is required")
        if self.value_type not in {"str", "int", "float", "bool", "list", "dict"}:
            raise InvalidArgumentError(f"invalid field value_type: {self.value_type!r}")
        if self.default is not None:
            _validate_value_type(self.name, self.default, self.value_type)


@dataclass(frozen=True, slots=True)
class ObjectTemplate:
    """Portable object template with explicit fields and defaults."""

    template_id: str
    object_kind: TemplateObjectKind
    record_type: str
    scope: str
    namespace: MemoryNamespace
    fields: tuple[TemplateField, ...]
    title_template: str | None = None
    tags: tuple[str, ...] = ()
    ontology_id: str | None = None
    version: str = "v1"
    description: str = ""

    def __post_init__(self) -> None:
        if not self.template_id:
            raise InvalidArgumentError("template_id is required")
        if self.object_kind not in {"record", "document"}:
            raise InvalidArgumentError(f"invalid object_kind: {self.object_kind!r}")
        if not self.record_type:
            raise InvalidArgumentError("record_type is required")
        if not self.scope:
            raise InvalidArgumentError("scope is required")
        if not isinstance(self.namespace, MemoryNamespace):
            raise InvalidArgumentError("namespace must be a MemoryNamespace")
        field_names = [field.name for field in self.fields]
        if len(field_names) != len(set(field_names)):
            raise InvalidArgumentError("template fields must have unique names")


@dataclass(frozen=True, slots=True)
class CreationForm:
    """Caller-supplied explicit values for one template application."""

    template_id: str
    values: dict[str, Any]
    actor: str
    submitted_at: str = field(default_factory=utc_now_iso)

    def __post_init__(self) -> None:
        if not self.template_id:
            raise InvalidArgumentError("template_id is required")
        if not isinstance(self.values, dict):
            raise InvalidArgumentError("values must be a dict")
        if not self.actor:
            raise InvalidArgumentError("actor is required")


@dataclass(frozen=True, slots=True)
class CreationPlan:
    """Validated creation plan over an explicit template and form."""

    plan_id: str
    template: ObjectTemplate
    form: CreationForm
    content: dict[str, Any]
    title: str | None
    record_id: str = field(default_factory=lambda: f"record-{uuid4().hex}")
    created_at: str = field(default_factory=utc_now_iso)
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.plan_id:
            raise InvalidArgumentError("plan_id is required")
        if self.form.template_id != self.template.template_id:
            raise InvalidArgumentError("form template_id must match template")
        if not isinstance(self.content, dict):
            raise InvalidArgumentError("content must be a dict")


@dataclass(frozen=True, slots=True)
class CreationApplyResult:
    """Result of applying a template creation plan."""

    plan_id: str
    record_id: str
    object_kind: TemplateObjectKind

    def __post_init__(self) -> None:
        if not self.plan_id:
            raise InvalidArgumentError("plan_id is required")
        if not self.record_id:
            raise InvalidArgumentError("record_id is required")


def build_creation_plan(template: ObjectTemplate, form: CreationForm) -> CreationPlan:
    """Apply explicit template defaults and validate supplied values."""

    if form.template_id != template.template_id:
        raise InvalidArgumentError("form template_id must match template")
    content: dict[str, Any] = {}
    for field_def in template.fields:
        value = form.values.get(field_def.name, field_def.default)
        if value is None and field_def.required:
            raise InvalidArgumentError(f"missing required field: {field_def.name}")
        if value is None:
            continue
        _validate_value_type(field_def.name, value, field_def.value_type)
        content[field_def.name] = value
    extra = set(form.values) - {field.name for field in template.fields}
    if extra:
        raise InvalidArgumentError(f"unknown template fields: {sorted(extra)}")
    title = _render_title(template.title_template, content)
    meta = {
        "template": {
            "template_id": template.template_id,
            "version": template.version,
            "object_kind": template.object_kind,
            "actor": form.actor,
            "submitted_at": form.submitted_at,
        }
    }
    if template.ontology_id:
        meta["ontology"] = {"ontology_id": template.ontology_id}
    if template.object_kind == "document":
        path = str(content.get("path") or f"{template.template_id}.md")
        text = str(content.get("text") or content.get("body") or "")
        meta["document"] = {
            "document_id": f"doc-{uuid4().hex}",
            "path": path,
            "title": title or path.rsplit("/", 1)[-1],
            "aliases": list(content.get("aliases") or []),
            "content_hash": sha256(text.encode("utf-8")).hexdigest(),
            "source_format": "markdown",
            "provenance": {"template_id": template.template_id},
        }
    return CreationPlan(
        plan_id=f"creation-plan-{uuid4().hex}",
        template=template,
        form=form,
        content=content,
        title=title,
        meta=meta,
    )


def apply_creation_plan(
    store: TemplateCreationStore,
    plan: CreationPlan,
) -> CreationApplyResult:
    """Persist one explicit creation plan through the canonical record owner."""

    record = MemoryRecord(
        id=plan.record_id,
        scope=plan.template.scope,
        type=plan.template.record_type,  # type: ignore[arg-type]
        content=plan.content,
        created_at=plan.created_at,
        updated_at=plan.created_at,
        title=plan.title,
        tags=list(plan.template.tags),
        source="user_said",
        confidence=1.0,
        namespace=plan.template.namespace,
        event_time=plan.created_at,
        meta=dict(plan.meta),
    )
    record_id = store.put_record(record)
    return CreationApplyResult(
        plan_id=plan.plan_id,
        record_id=record_id,
        object_kind=plan.template.object_kind,
    )


def _render_title(template: str | None, content: dict[str, Any]) -> str | None:
    if template is None:
        return None
    try:
        return template.format(**{key: str(value) for key, value in content.items()})
    except KeyError as exc:
        raise InvalidArgumentError(
            f"title_template references missing field: {exc.args[0]}"
        ) from exc


def _validate_value_type(name: str, value: Any, value_type: TemplateFieldType) -> None:
    expected: tuple[type, ...]
    if value_type == "str":
        expected = (str,)
    elif value_type == "int":
        expected = (int,)
    elif value_type == "float":
        expected = (int, float)
    elif value_type == "bool":
        expected = (bool,)
    elif value_type == "list":
        expected = (list,)
    else:
        expected = (dict,)
    if not isinstance(value, expected):
        raise InvalidArgumentError(f"{name} must be {value_type}")


__all__ = [
    "CreationApplyResult",
    "CreationForm",
    "CreationPlan",
    "ObjectTemplate",
    "TemplateCreationStore",
    "TemplateField",
    "TemplateFieldType",
    "TemplateObjectKind",
    "apply_creation_plan",
    "build_creation_plan",
]
