"""Typed privacy, consent, redaction, and retention DTOs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Final, Literal

from sophiagraph.contracts.errors import InvalidArgumentError

ConsentStatus = Literal["unknown", "granted", "denied", "revoked"]
CONSENT_STATUSES: Final[frozenset[str]] = frozenset(
    {"unknown", "granted", "denied", "revoked"}
)

VisibilityScope = Literal["visible", "hidden", "redacted", "audit_only"]
VISIBILITY_SCOPES: Final[frozenset[str]] = frozenset(
    {"visible", "hidden", "redacted", "audit_only"}
)

RetentionClass = Literal[
    "default",
    "retain",
    "retain_hidden",
    "redact_and_retain",
    "tombstone",
    "erase_requested",
]
RETENTION_CLASSES: Final[frozenset[str]] = frozenset(
    {
        "default",
        "retain",
        "retain_hidden",
        "redact_and_retain",
        "tombstone",
        "erase_requested",
    }
)

EraseIntent = Literal["none", "user_requested", "policy_required", "operator_requested"]
ERASE_INTENTS: Final[frozenset[str]] = frozenset(
    {"none", "user_requested", "policy_required", "operator_requested"}
)

PolicyDecisionReason = Literal[
    "explicit_allow",
    "consent_required",
    "consent_denied",
    "consent_revoked",
    "visibility_hidden",
    "redaction_required",
    "retention_hold",
    "erase_requested",
    "export_restricted",
]
POLICY_DECISION_REASONS: Final[frozenset[str]] = frozenset(
    {
        "explicit_allow",
        "consent_required",
        "consent_denied",
        "consent_revoked",
        "visibility_hidden",
        "redaction_required",
        "retention_hold",
        "erase_requested",
        "export_restricted",
    }
)

RedactionTargetKind = Literal[
    "record_content",
    "metadata_key",
    "block_id",
    "artifact_text",
    "export_field",
]
REDACTION_TARGET_KINDS: Final[frozenset[str]] = frozenset(
    {
        "record_content",
        "metadata_key",
        "block_id",
        "artifact_text",
        "export_field",
    }
)

RedactionReason = Literal[
    "privacy_request",
    "consent_revoked",
    "operator_policy",
    "export_minimization",
]
REDACTION_REASONS: Final[frozenset[str]] = frozenset(
    {
        "privacy_request",
        "consent_revoked",
        "operator_policy",
        "export_minimization",
    }
)

RetentionOutcomeKind = Literal[
    "retain",
    "hide",
    "redact_and_retain",
    "tombstone",
    "erase",
]
RETENTION_OUTCOME_KINDS: Final[frozenset[str]] = frozenset(
    {"retain", "hide", "redact_and_retain", "tombstone", "erase"}
)


def _string_field(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value)


def _optional_string_field(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _dict_field(value: Any, field_name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise InvalidArgumentError(f"{field_name} must be a dict")
    return dict(value)


@dataclass(frozen=True)
class ConsentState:
    status: ConsentStatus
    granted_at: str | None = None
    revoked_at: str | None = None
    source_owner: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.status not in CONSENT_STATUSES:
            raise InvalidArgumentError(f"invalid consent status: {self.status!r}")
        if self.source_owner is not None and not self.source_owner:
            raise InvalidArgumentError("source_owner must be non-empty or None")
        if not isinstance(self.details, dict):
            raise InvalidArgumentError("details must be a dict")

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "granted_at": self.granted_at,
            "revoked_at": self.revoked_at,
            "source_owner": self.source_owner,
            "details": dict(self.details),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ConsentState":
        return cls(
            status=_string_field(payload.get("status"), "unknown"),  # type: ignore[arg-type]
            granted_at=_optional_string_field(payload.get("granted_at")),
            revoked_at=_optional_string_field(payload.get("revoked_at")),
            source_owner=_optional_string_field(payload.get("source_owner")),
            details=_dict_field(payload.get("details"), "details"),
        )


@dataclass(frozen=True)
class RedactionTarget:
    kind: RedactionTargetKind
    key: str | None = None
    block_id: str | None = None
    artifact_ref: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in REDACTION_TARGET_KINDS:
            raise InvalidArgumentError(f"invalid redaction target kind: {self.kind!r}")
        if self.kind == "metadata_key" and not self.key:
            raise InvalidArgumentError("metadata_key target requires key")
        if self.kind == "block_id" and not self.block_id:
            raise InvalidArgumentError("block_id target requires block_id")
        if self.kind == "artifact_text" and not self.artifact_ref:
            raise InvalidArgumentError("artifact_text target requires artifact_ref")
        if self.kind == "export_field" and not self.key:
            raise InvalidArgumentError("export_field target requires key")

    @property
    def target_ref(self) -> str:
        if self.kind in {"metadata_key", "export_field"}:
            return str(self.key)
        if self.kind == "block_id":
            return str(self.block_id)
        if self.kind == "artifact_text":
            return str(self.artifact_ref)
        return "content"

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "key": self.key,
            "block_id": self.block_id,
            "artifact_ref": self.artifact_ref,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RedactionTarget":
        return cls(
            kind=_string_field(payload.get("kind")),  # type: ignore[arg-type]
            key=_optional_string_field(payload.get("key")),
            block_id=_optional_string_field(payload.get("block_id")),
            artifact_ref=_optional_string_field(payload.get("artifact_ref")),
        )


@dataclass(frozen=True)
class RedactionPlan:
    plan_id: str
    reason: RedactionReason
    targets: tuple[RedactionTarget, ...]
    replace_with: str = "[redacted]"
    applied_by: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.plan_id:
            raise InvalidArgumentError("plan_id is required")
        if self.reason not in REDACTION_REASONS:
            raise InvalidArgumentError(f"invalid redaction reason: {self.reason!r}")
        if not self.targets:
            raise InvalidArgumentError("targets must not be empty")
        for target in self.targets:
            if not isinstance(target, RedactionTarget):
                raise InvalidArgumentError(
                    "targets must contain RedactionTarget entries"
                )
        if not self.replace_with:
            raise InvalidArgumentError("replace_with is required")
        if self.applied_by is not None and not self.applied_by:
            raise InvalidArgumentError("applied_by must be non-empty or None")
        if not isinstance(self.details, dict):
            raise InvalidArgumentError("details must be a dict")

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "reason": self.reason,
            "targets": [target.to_dict() for target in self.targets],
            "replace_with": self.replace_with,
            "applied_by": self.applied_by,
            "details": dict(self.details),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RedactionPlan":
        raw_targets = payload.get("targets")
        return cls(
            plan_id=_string_field(payload.get("plan_id")),
            reason=_string_field(payload.get("reason")),  # type: ignore[arg-type]
            targets=tuple(
                RedactionTarget.from_dict(item)
                for item in raw_targets
                if isinstance(item, dict)
            )
            if isinstance(raw_targets, list)
            else (),
            replace_with=_string_field(payload.get("replace_with"), "[redacted]"),
            applied_by=_optional_string_field(payload.get("applied_by")),
            details=_dict_field(payload.get("details"), "details"),
        )


@dataclass(frozen=True)
class PrivacyPolicyState:
    policy_id: str
    consent: ConsentState
    retrieval_visibility: VisibilityScope
    export_visibility: VisibilityScope
    retention_class: RetentionClass
    erase_intent: EraseIntent
    decision_reason: PolicyDecisionReason
    source_owner: str
    applied_at: str
    redaction_plan: RedactionPlan | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.policy_id:
            raise InvalidArgumentError("policy_id is required")
        if not isinstance(self.consent, ConsentState):
            raise InvalidArgumentError("consent must be a ConsentState")
        if self.retrieval_visibility not in VISIBILITY_SCOPES:
            raise InvalidArgumentError(
                f"invalid retrieval_visibility: {self.retrieval_visibility!r}"
            )
        if self.export_visibility not in VISIBILITY_SCOPES:
            raise InvalidArgumentError(
                f"invalid export_visibility: {self.export_visibility!r}"
            )
        if self.retention_class not in RETENTION_CLASSES:
            raise InvalidArgumentError(
                f"invalid retention_class: {self.retention_class!r}"
            )
        if self.erase_intent not in ERASE_INTENTS:
            raise InvalidArgumentError(f"invalid erase_intent: {self.erase_intent!r}")
        if self.decision_reason not in POLICY_DECISION_REASONS:
            raise InvalidArgumentError(
                f"invalid decision_reason: {self.decision_reason!r}"
            )
        if not self.source_owner:
            raise InvalidArgumentError("source_owner is required")
        if not self.applied_at:
            raise InvalidArgumentError("applied_at is required")
        if self.redaction_plan is not None and not isinstance(
            self.redaction_plan, RedactionPlan
        ):
            raise InvalidArgumentError("redaction_plan must be RedactionPlan or None")
        if not isinstance(self.details, dict):
            raise InvalidArgumentError("details must be a dict")

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy_id": self.policy_id,
            "consent": self.consent.to_dict(),
            "retrieval_visibility": self.retrieval_visibility,
            "export_visibility": self.export_visibility,
            "retention_class": self.retention_class,
            "erase_intent": self.erase_intent,
            "decision_reason": self.decision_reason,
            "source_owner": self.source_owner,
            "applied_at": self.applied_at,
            "redaction_plan": (
                self.redaction_plan.to_dict() if self.redaction_plan else None
            ),
            "details": dict(self.details),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PrivacyPolicyState":
        raw_consent = payload.get("consent")
        if not isinstance(raw_consent, dict):
            raise InvalidArgumentError("consent is required")
        raw_redaction = payload.get("redaction_plan")
        return cls(
            policy_id=_string_field(payload.get("policy_id")),
            consent=ConsentState.from_dict(raw_consent),
            retrieval_visibility=_string_field(payload.get("retrieval_visibility")),  # type: ignore[arg-type]
            export_visibility=_string_field(payload.get("export_visibility")),  # type: ignore[arg-type]
            retention_class=_string_field(payload.get("retention_class")),  # type: ignore[arg-type]
            erase_intent=_string_field(payload.get("erase_intent"), "none"),  # type: ignore[arg-type]
            decision_reason=_string_field(payload.get("decision_reason")),  # type: ignore[arg-type]
            source_owner=_string_field(payload.get("source_owner")),
            applied_at=_string_field(payload.get("applied_at")),
            redaction_plan=RedactionPlan.from_dict(raw_redaction)
            if isinstance(raw_redaction, dict)
            else None,
            details=_dict_field(payload.get("details"), "details"),
        )


@dataclass(frozen=True)
class RedactionResult:
    record_id: str
    plan_id: str
    reason: RedactionReason
    redacted_targets: tuple[str, ...] = ()
    skipped_targets: tuple[str, ...] = ()
    content_redacted: bool = False
    meta_keys_redacted: tuple[str, ...] = ()
    export_fields_redacted: tuple[str, ...] = ()
    block_ids_redacted: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.record_id:
            raise InvalidArgumentError("record_id is required")
        if not self.plan_id:
            raise InvalidArgumentError("plan_id is required")
        if self.reason not in REDACTION_REASONS:
            raise InvalidArgumentError(f"invalid redaction reason: {self.reason!r}")


@dataclass(frozen=True)
class RetentionOutcome:
    record_id: str
    kind: RetentionOutcomeKind
    retention_class: RetentionClass
    erase_intent: EraseIntent
    redaction_plan: RedactionPlan | None = None

    def __post_init__(self) -> None:
        if not self.record_id:
            raise InvalidArgumentError("record_id is required")
        if self.kind not in RETENTION_OUTCOME_KINDS:
            raise InvalidArgumentError(f"invalid retention outcome: {self.kind!r}")
        if self.retention_class not in RETENTION_CLASSES:
            raise InvalidArgumentError(
                f"invalid retention_class: {self.retention_class!r}"
            )
        if self.erase_intent not in ERASE_INTENTS:
            raise InvalidArgumentError(f"invalid erase_intent: {self.erase_intent!r}")
        if self.redaction_plan is not None and not isinstance(
            self.redaction_plan, RedactionPlan
        ):
            raise InvalidArgumentError("redaction_plan must be RedactionPlan or None")


__all__ = [
    "CONSENT_STATUSES",
    "ERASE_INTENTS",
    "POLICY_DECISION_REASONS",
    "REDACTION_REASONS",
    "REDACTION_TARGET_KINDS",
    "RETENTION_CLASSES",
    "RETENTION_OUTCOME_KINDS",
    "VISIBILITY_SCOPES",
    "ConsentState",
    "ConsentStatus",
    "EraseIntent",
    "PolicyDecisionReason",
    "PrivacyPolicyState",
    "RedactionPlan",
    "RedactionReason",
    "RedactionResult",
    "RedactionTarget",
    "RedactionTargetKind",
    "RetentionClass",
    "RetentionOutcome",
    "RetentionOutcomeKind",
    "VisibilityScope",
]
