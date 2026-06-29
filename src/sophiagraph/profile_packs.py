"""Typed interoperability profile packs over OKF/Obsidian portability."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from sophiagraph.contracts.errors import InvalidArgumentError

ProfilePackTarget = Literal["okf", "obsidian", "markdown", "json"]
MappingDiagnosticKind = Literal["unknown_field", "lossy_field", "version_skew"]


@dataclass(frozen=True, slots=True)
class ProfileFieldMapping:
    """Explicit field mapping for a profile pack."""

    source_field: str
    target_field: str
    lossy: bool = False
    required: bool = False

    def __post_init__(self) -> None:
        if not self.source_field:
            raise InvalidArgumentError("source_field is required")
        if not self.target_field:
            raise InvalidArgumentError("target_field is required")


@dataclass(frozen=True, slots=True)
class ProfilePack:
    """Portable mapping profile for non-native ecosystem exchange."""

    pack_id: str
    target: ProfilePackTarget
    version: str
    mappings: tuple[ProfileFieldMapping, ...]
    source_revision: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.pack_id:
            raise InvalidArgumentError("pack_id is required")
        if self.target not in {"okf", "obsidian", "markdown", "json"}:
            raise InvalidArgumentError(f"invalid profile target: {self.target!r}")
        if not self.version:
            raise InvalidArgumentError("version is required")


@dataclass(frozen=True, slots=True)
class ProfilePackDiagnostic:
    """Structural mapping diagnostic; no silent destructive conversion."""

    kind: MappingDiagnosticKind
    field: str
    detail: str = ""

    def __post_init__(self) -> None:
        if self.kind not in {"unknown_field", "lossy_field", "version_skew"}:
            raise InvalidArgumentError(f"invalid diagnostic kind: {self.kind!r}")
        if not self.field:
            raise InvalidArgumentError("field is required")


@dataclass(frozen=True, slots=True)
class ProfilePackPlan:
    """Import/export mapping plan with explicit diagnostics."""

    pack: ProfilePack
    direction: Literal["import", "export"]
    mapped_fields: dict[str, str]
    diagnostics: tuple[ProfilePackDiagnostic, ...] = ()


def build_profile_pack_plan(
    pack: ProfilePack,
    fields: dict[str, Any],
    *,
    direction: Literal["import", "export"],
) -> ProfilePackPlan:
    """Build an explicit field mapping plan over one profile pack."""

    if direction not in {"import", "export"}:
        raise InvalidArgumentError(f"invalid profile direction: {direction!r}")
    mapped: dict[str, str] = {}
    diagnostics: list[ProfilePackDiagnostic] = []
    mapping_by_source = {mapping.source_field: mapping for mapping in pack.mappings}
    for field_name in fields:
        mapping = mapping_by_source.get(field_name)
        if mapping is None:
            diagnostics.append(
                ProfilePackDiagnostic(kind="unknown_field", field=field_name)
            )
            continue
        mapped[field_name] = mapping.target_field
        if mapping.lossy:
            diagnostics.append(
                ProfilePackDiagnostic(
                    kind="lossy_field",
                    field=field_name,
                    detail=mapping.target_field,
                )
            )
    for mapping in pack.mappings:
        if mapping.required and mapping.source_field not in fields:
            diagnostics.append(
                ProfilePackDiagnostic(
                    kind="unknown_field",
                    field=mapping.source_field,
                    detail="required field missing",
                )
            )
    return ProfilePackPlan(
        pack=pack,
        direction=direction,
        mapped_fields=mapped,
        diagnostics=tuple(diagnostics),
    )


__all__ = [
    "ProfileFieldMapping",
    "MappingDiagnosticKind",
    "ProfilePack",
    "ProfilePackDiagnostic",
    "ProfilePackPlan",
    "ProfilePackTarget",
    "build_profile_pack_plan",
]
