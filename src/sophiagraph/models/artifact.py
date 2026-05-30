"""Typed multimodal artifact reference DTOs."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Final, Literal

from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.models.namespace import MemoryNamespace


ArtifactSourceClass = Literal[
    "user_upload",
    "tool_output",
    "edited_file",
    "screenshot",
    "command_evidence",
    "external_link",
    "imported_bundle",
]

ARTIFACT_SOURCE_CLASSES: Final[frozenset[str]] = frozenset(
    {
        "user_upload",
        "tool_output",
        "edited_file",
        "screenshot",
        "command_evidence",
        "external_link",
        "imported_bundle",
    }
)

ArtifactRetentionPolicy = Literal[
    "default",
    "session_only",
    "until_replaced",
    "indefinite",
    "purge_on_export",
]

ARTIFACT_RETENTION_POLICIES: Final[frozenset[str]] = frozenset(
    {
        "default",
        "session_only",
        "until_replaced",
        "indefinite",
        "purge_on_export",
    }
)


# Conservative MIME validator: <type>/<subtype> with optional parameters.
_MIME_PATTERN = re.compile(r"^[a-zA-Z0-9!#$&\-\^_.+]+/[a-zA-Z0-9!#$&\-\^_.+]+$")
_URI_PATTERN = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.\-]*:")


@dataclass(frozen=True)
class ArtifactRecord:
    """Durable reference row for caller-owned artifact bytes."""

    artifact_id: str
    uri: str
    sha256: str
    mime: str
    size_bytes: int
    namespace: MemoryNamespace
    source_class: ArtifactSourceClass
    source_owner: str
    created_at: str
    retention: ArtifactRetentionPolicy = "default"
    label: str | None = None
    target_record_id: str | None = None
    derived_text_record_id: str | None = None
    provenance: dict[str, Any] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.artifact_id, str) or not self.artifact_id:
            raise InvalidArgumentError("artifact_id must be a non-empty string")
        if not isinstance(self.uri, str) or not self.uri:
            raise InvalidArgumentError("uri must be a non-empty string")
        if not _URI_PATTERN.match(self.uri):
            raise InvalidArgumentError(
                f"uri must include a scheme prefix (e.g. file:, https:, vault:): "
                f"{self.uri!r}"
            )
        if not isinstance(self.sha256, str) or not self.sha256:
            raise InvalidArgumentError("sha256 must be a non-empty string")
        if len(self.sha256) != 64 or not re.match(r"^[0-9a-fA-F]+$", self.sha256):
            raise InvalidArgumentError(
                "sha256 must be a 64-char hex digest; provide the actual digest, "
                "not a placeholder"
            )
        if not isinstance(self.mime, str) or not self.mime:
            raise InvalidArgumentError("mime must be a non-empty string")
        if not _MIME_PATTERN.match(self.mime):
            raise InvalidArgumentError(f"mime is not a valid MIME type: {self.mime!r}")
        if not isinstance(self.size_bytes, int) or self.size_bytes < 0:
            raise InvalidArgumentError("size_bytes must be a non-negative int")
        if not isinstance(self.namespace, MemoryNamespace):
            raise InvalidArgumentError("namespace must be a MemoryNamespace")
        if self.source_class not in ARTIFACT_SOURCE_CLASSES:
            raise InvalidArgumentError(
                f"unknown source_class: {self.source_class!r}; "
                f"allowed: {sorted(ARTIFACT_SOURCE_CLASSES)}"
            )
        if not isinstance(self.source_owner, str) or not self.source_owner:
            raise InvalidArgumentError("source_owner must be a non-empty string")
        if not isinstance(self.created_at, str) or not self.created_at:
            raise InvalidArgumentError("created_at must be a non-empty ISO string")
        if self.retention not in ARTIFACT_RETENTION_POLICIES:
            raise InvalidArgumentError(
                f"unknown retention: {self.retention!r}; "
                f"allowed: {sorted(ARTIFACT_RETENTION_POLICIES)}"
            )
        if self.target_record_id is not None and (
            not isinstance(self.target_record_id, str) or not self.target_record_id
        ):
            raise InvalidArgumentError(
                "target_record_id must be a non-empty string or None"
            )
        if self.derived_text_record_id is not None and (
            not isinstance(self.derived_text_record_id, str)
            or not self.derived_text_record_id
        ):
            raise InvalidArgumentError(
                "derived_text_record_id must be a non-empty string or None"
            )
        if not isinstance(self.provenance, dict):
            raise InvalidArgumentError("provenance must be a dict")
        if not isinstance(self.meta, dict):
            raise InvalidArgumentError("meta must be a dict")


__all__ = [
    "ARTIFACT_RETENTION_POLICIES",
    "ARTIFACT_SOURCE_CLASSES",
    "ArtifactRecord",
    "ArtifactRetentionPolicy",
    "ArtifactSourceClass",
]
