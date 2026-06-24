"""Typed scope and namespace primitives."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, get_args

from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.models.primitives import (
    NamespaceKind,
    Scope,
    ScopeKind,
    _SCOPE_PATTERN,
    _assert_literal,
    _assert_namespace_id,
    _assert_scope,
)


def _optional_namespace_id(value: Any) -> str | None:
    if value is None or value == "":
        return None
    return str(value)


@dataclass(frozen=True)
class MemoryScope:
    """Canonical parser/coercer for memory scope strings."""

    kind: ScopeKind
    value: str

    def __post_init__(self) -> None:
        _assert_scope(str(self))

    def __str__(self) -> str:
        return f"{self.kind}:{self.value}"

    @property
    def is_session(self) -> bool:
        return self.kind == "session"

    @property
    def is_agent(self) -> bool:
        return self.kind == "agent"

    @property
    def is_project(self) -> bool:
        return self.kind == "project"

    @property
    def is_global(self) -> bool:
        return self.kind == "global"

    @classmethod
    def parse(cls, scope: Scope) -> "MemoryScope":
        normalized = str(scope or "").strip()
        _assert_scope(normalized)
        kind, value = normalized.split(":", 1)
        return cls(kind=kind, value=value)  # type: ignore[arg-type]

    @classmethod
    def coerce(
        cls,
        scope: Scope,
        *,
        default_kind: ScopeKind = "session",
    ) -> "MemoryScope":
        normalized = str(scope or "").strip()
        if _SCOPE_PATTERN.match(normalized):
            return cls.parse(normalized)
        if not normalized:
            raise InvalidArgumentError("scope is required")
        return cls(kind=default_kind, value=normalized)


@dataclass(frozen=True)
class MemoryNamespaceComponent:
    """One explicit namespace dimension supplied by a caller or host runtime."""

    kind: NamespaceKind
    id: str

    def __post_init__(self) -> None:
        _assert_literal(self.kind, get_args(NamespaceKind), "namespace kind")
        _assert_namespace_id(self.id, f"{self.kind}_id")

    def as_scope(self) -> Scope:
        if self.kind in {"agent", "session", "project"}:
            return f"{self.kind}:{self.id}"
        if self.kind == "graph":
            return f"global:{self.id}"
        raise InvalidArgumentError(
            f"namespace kind cannot be represented as legacy scope: {self.kind!r}"
        )


@dataclass(frozen=True)
class MemoryNamespace:
    """Typed isolation dimensions for future multi-agent memory records."""

    tenant_id: str | None = None
    org_id: str | None = None
    user_id: str | None = None
    agent_id: str | None = None
    session_id: str | None = None
    conversation_id: str | None = None
    project_id: str | None = None
    graph_id: str | None = None

    def __post_init__(self) -> None:
        values = self.as_dict()
        if not values:
            raise InvalidArgumentError("at least one namespace id is required")
        for key, value in values.items():
            _assert_namespace_id(value, key)

    @property
    def components(self) -> list[MemoryNamespaceComponent]:
        return [
            MemoryNamespaceComponent(kind=kind, id=value)
            for kind, value in (
                ("tenant", self.tenant_id),
                ("org", self.org_id),
                ("user", self.user_id),
                ("agent", self.agent_id),
                ("session", self.session_id),
                ("conversation", self.conversation_id),
                ("project", self.project_id),
                ("graph", self.graph_id),
            )
            if value is not None
        ]

    def as_dict(self) -> dict[str, str]:
        values = {
            "tenant_id": self.tenant_id,
            "org_id": self.org_id,
            "user_id": self.user_id,
            "agent_id": self.agent_id,
            "session_id": self.session_id,
            "conversation_id": self.conversation_id,
            "project_id": self.project_id,
            "graph_id": self.graph_id,
        }
        return {key: value for key, value in values.items() if value is not None}

    def matches(self, namespace_filter: "MemoryNamespace") -> bool:
        values = self.as_dict()
        return all(
            values.get(key) == value
            for key, value in namespace_filter.as_dict().items()
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MemoryNamespace":
        return cls(
            tenant_id=_optional_namespace_id(data.get("tenant_id")),
            org_id=_optional_namespace_id(data.get("org_id")),
            user_id=_optional_namespace_id(data.get("user_id")),
            agent_id=_optional_namespace_id(data.get("agent_id")),
            session_id=_optional_namespace_id(data.get("session_id")),
            conversation_id=_optional_namespace_id(data.get("conversation_id")),
            project_id=_optional_namespace_id(data.get("project_id")),
            graph_id=_optional_namespace_id(data.get("graph_id")),
        )

    @classmethod
    def from_scope(cls, scope: Scope) -> "MemoryNamespace":
        parsed = MemoryScope.parse(scope)
        if parsed.kind == "session":
            return cls(session_id=parsed.value)
        if parsed.kind == "agent":
            return cls(agent_id=parsed.value)
        if parsed.kind == "project":
            return cls(project_id=parsed.value)
        return cls(graph_id=parsed.value)

    def to_scope(self, kind: ScopeKind) -> Scope:
        if kind == "session" and self.session_id is not None:
            return f"session:{self.session_id}"
        if kind == "agent" and self.agent_id is not None:
            return f"agent:{self.agent_id}"
        if kind == "project" and self.project_id is not None:
            return f"project:{self.project_id}"
        if kind == "global" and self.graph_id is not None:
            return f"global:{self.graph_id}"
        raise InvalidArgumentError(
            f"namespace does not contain a {kind!r} scope-compatible id"
        )


def sorted_namespace_key(namespace: MemoryNamespace) -> str:
    """Return a stable namespace key sorted by dimension name for derived IDs."""

    return "|".join(
        f"{key}={value}" for key, value in sorted(namespace.as_dict().items())
    )


__all__ = [
    "MemoryScope",
    "MemoryNamespaceComponent",
    "MemoryNamespace",
    "sorted_namespace_key",
]
