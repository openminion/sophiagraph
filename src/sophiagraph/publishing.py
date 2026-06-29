"""Typed publish/share profiles and runtime-neutral delivery handoffs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.models import MemoryRecord
from sophiagraph.privacy_ops import apply_redaction_plan, privacy_policy_from_record

PublishProfileKind = Literal["private_snapshot", "read_only_share", "public_export"]
DeliveryTargetKind = Literal["static_bundle", "runtime_handoff"]


@dataclass(frozen=True, slots=True)
class PublishProfile:
    """Explicit profile controlling package-local export shaping."""

    profile_id: str
    kind: PublishProfileKind
    include_private: bool = False
    include_redacted: bool = False
    max_records: int = 500
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.profile_id:
            raise InvalidArgumentError("profile_id is required")
        if self.kind not in {"private_snapshot", "read_only_share", "public_export"}:
            raise InvalidArgumentError(f"invalid publish profile kind: {self.kind!r}")
        if self.max_records <= 0:
            raise InvalidArgumentError("max_records must be positive")
        if self.kind == "public_export" and self.include_private:
            raise InvalidArgumentError("public_export cannot include private records")


@dataclass(frozen=True, slots=True)
class DeliveryHandoff:
    """Runtime-neutral handoff for a shaped publish/share bundle."""

    handoff_id: str
    profile_id: str
    target: DeliveryTargetKind
    payload_ref: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.handoff_id:
            raise InvalidArgumentError("handoff_id is required")
        if not self.profile_id:
            raise InvalidArgumentError("profile_id is required")
        if self.target not in {"static_bundle", "runtime_handoff"}:
            raise InvalidArgumentError(f"invalid delivery target: {self.target!r}")
        if not self.payload_ref:
            raise InvalidArgumentError("payload_ref is required")


@dataclass(frozen=True, slots=True)
class PublishPlan:
    """Preview of records included and omitted by one publish profile."""

    profile: PublishProfile
    included_record_ids: tuple[str, ...]
    omitted_record_ids: tuple[str, ...]
    diagnostics: dict[str, Any] = field(default_factory=dict)


def build_publish_plan(
    profile: PublishProfile,
    records: list[MemoryRecord],
) -> PublishPlan:
    """Shape records through existing privacy/export owners."""

    included_records: list[MemoryRecord] = []
    omitted: list[str] = []
    for record in records:
        policy = privacy_policy_from_record(record)
        if policy is None or policy.export_visibility == "visible":
            included_records.append(record)
            continue
        if policy.export_visibility in {"hidden", "audit_only"}:
            if profile.include_private:
                included_records.append(record)
            else:
                omitted.append(record.id)
            continue
        if policy.export_visibility == "redacted":
            if not profile.include_redacted:
                omitted.append(record.id)
                continue
            if policy.redaction_plan is None:
                raise InvalidArgumentError(
                    "redacted export visibility requires redaction_plan"
                )
            redacted, _result = apply_redaction_plan(record, policy.redaction_plan)
            included_records.append(redacted)
    included = [record.id for record in included_records[: profile.max_records]]
    omitted.extend(record.id for record in included_records[profile.max_records :])
    return PublishPlan(
        profile=profile,
        included_record_ids=tuple(included),
        omitted_record_ids=tuple(omitted),
        diagnostics={
            "input_count": len(records),
            "included_count": len(included),
            "omitted_count": len(omitted),
        },
    )


def build_delivery_handoff(
    plan: PublishPlan,
    *,
    target: DeliveryTargetKind,
    payload_ref: str,
) -> DeliveryHandoff:
    """Build explicit metadata for a host/runtime delivery step."""

    return DeliveryHandoff(
        handoff_id=f"delivery-{plan.profile.profile_id}",
        profile_id=plan.profile.profile_id,
        target=target,
        payload_ref=payload_ref,
        metadata={
            "kind": plan.profile.kind,
            "record_count": len(plan.included_record_ids),
            "omitted_count": len(plan.omitted_record_ids),
        },
    )


__all__ = [
    "DeliveryHandoff",
    "DeliveryTargetKind",
    "PublishPlan",
    "PublishProfile",
    "PublishProfileKind",
    "build_delivery_handoff",
    "build_publish_plan",
]
