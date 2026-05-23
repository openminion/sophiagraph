"""Structural link DTOs and explicit resolver contracts."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import re
from typing import Any, Literal

from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.models.namespace import MemoryNamespace

LinkKind = Literal[
    "wikilink",
    "markdown",
    "embed",
    "property",
    "external",
]
LinkResolutionStatus = Literal["resolved", "unresolved", "ambiguous", "external"]
ContextUnit = Literal["characters", "lines"]


def normalize_link_target(target: str) -> str:
    """Normalize explicit link targets without fuzzy or semantic guessing."""
    return " ".join(str(target or "").strip().split())


def _slugify_heading(value: str) -> str:
    lowered = re.sub(r"[^a-z0-9 -]", "", value.lower())
    return re.sub(r"\s+", "-", lowered.strip())


@dataclass(frozen=True)
class StructuralLink:
    """Explicit note/link edge parsed from syntax or supplied by a caller."""

    link_id: str
    source_record_id: str
    raw_target: str
    link_kind: LinkKind
    resolution_status: LinkResolutionStatus
    namespace: MemoryNamespace
    source_path: str | None = None
    target_record_id: str | None = None
    target_path: str | None = None
    target_heading: str | None = None
    target_block_id: str | None = None
    display_text: str | None = None
    original: str | None = None
    start: int | None = None
    end: int | None = None
    context_before: str = ""
    context_after: str = ""
    relation_type: str | None = None
    created_at: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.link_id:
            raise InvalidArgumentError("link_id is required")
        if not self.source_record_id:
            raise InvalidArgumentError("source_record_id is required")
        if not normalize_link_target(self.raw_target):
            raise InvalidArgumentError("raw_target is required")
        if self.link_kind not in {
            "wikilink",
            "markdown",
            "embed",
            "property",
            "external",
        }:
            raise InvalidArgumentError(f"invalid link_kind: {self.link_kind!r}")
        if self.resolution_status not in {
            "resolved",
            "unresolved",
            "ambiguous",
            "external",
        }:
            raise InvalidArgumentError(
                f"invalid resolution_status: {self.resolution_status!r}"
            )
        if self.resolution_status == "resolved" and not (
            self.target_record_id or self.target_path
        ):
            raise InvalidArgumentError(
                "resolved links require target_record_id or target_path"
            )
        if self.start is not None and self.start < 0:
            raise InvalidArgumentError("start must be non-negative")
        if self.end is not None and self.end < 0:
            raise InvalidArgumentError("end must be non-negative")
        if self.start is not None and self.end is not None and self.end < self.start:
            raise InvalidArgumentError("end must be >= start")
        if not isinstance(self.namespace, MemoryNamespace):
            raise TypeError(
                "namespace must be MemoryNamespace"
            )  # allow-bare-raise: defensive dataclass guard
        if not isinstance(self.meta, dict):
            raise TypeError(
                "meta must be a dict"
            )  # allow-bare-raise: defensive dataclass guard

    @property
    def normalized_target(self) -> str:
        return normalize_link_target(self.raw_target)

    def with_context_bounds(
        self,
        *,
        before: int | None = None,
        after: int | None = None,
    ) -> "StructuralLink":
        """Return a copy with context strings truncated to structural bounds."""
        before_len = before if before is not None else len(self.context_before)
        after_len = after if after is not None else len(self.context_after)
        return replace(
            self,
            context_before=self.context_before[-max(0, int(before_len)) :],
            context_after=self.context_after[: max(0, int(after_len))],
        )


@dataclass(frozen=True)
class LinkResolutionCandidate:
    record_id: str
    path: str
    title: str
    aliases: list[str] = field(default_factory=list)
    namespace: MemoryNamespace | None = None

    def __post_init__(self) -> None:
        if not self.record_id:
            raise InvalidArgumentError("record_id is required")
        if not self.path:
            raise InvalidArgumentError("path is required")
        if not self.title:
            raise InvalidArgumentError("title is required")


@dataclass(frozen=True)
class LinkResolution:
    status: LinkResolutionStatus
    target_record_id: str | None = None
    target_path: str | None = None
    ambiguous_record_ids: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.status == "resolved" and not (
            self.target_record_id or self.target_path
        ):
            raise InvalidArgumentError("resolved result requires a target")
        if self.status == "ambiguous" and len(self.ambiguous_record_ids) < 2:
            raise InvalidArgumentError(
                "ambiguous result requires at least two candidates"
            )


class ExplicitLinkResolver:
    """Resolve explicit paths, titles, and aliases without semantic guessing."""

    def __init__(self, candidates: list[LinkResolutionCandidate]) -> None:
        self._candidates = list(candidates)

    def resolve(
        self,
        target: str,
        *,
        namespace: MemoryNamespace | None = None,
    ) -> LinkResolution:
        normalized = normalize_link_target(target).split("#", 1)[0]
        if not normalized:
            return LinkResolution(status="unresolved")
        scoped = [
            candidate
            for candidate in self._candidates
            if namespace is None
            or candidate.namespace is None
            or candidate.namespace.matches(namespace)
        ]
        if "/" in normalized or normalized.endswith(".md"):
            matches = [
                candidate
                for candidate in scoped
                if candidate.path.lower() == normalized.lower()
            ]
        else:
            lowered = normalized.lower()
            matches = [
                candidate
                for candidate in scoped
                if candidate.title.lower() == lowered
                or lowered in {alias.lower() for alias in candidate.aliases}
            ]
        if not matches:
            return LinkResolution(status="unresolved")
        if len(matches) > 1:
            return LinkResolution(
                status="ambiguous",
                ambiguous_record_ids=[candidate.record_id for candidate in matches],
            )
        match = matches[0]
        return LinkResolution(
            status="resolved",
            target_record_id=match.record_id,
            target_path=match.path,
        )


def split_target_parts(raw_target: str) -> tuple[str, str | None, str | None]:
    """Split ``Note#Heading`` or ``Note#^block`` into addressable components."""
    target = normalize_link_target(raw_target)
    if "#" not in target:
        return target, None, None
    path, anchor = target.split("#", 1)
    if anchor.startswith("^"):
        return path, None, anchor[1:]
    return path, _slugify_heading(anchor), None


__all__ = [
    "ContextUnit",
    "ExplicitLinkResolver",
    "LinkKind",
    "LinkResolution",
    "LinkResolutionCandidate",
    "LinkResolutionStatus",
    "StructuralLink",
    "normalize_link_target",
    "split_target_parts",
]
