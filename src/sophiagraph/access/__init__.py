"""Delegated-memory authorization contracts and gateway."""

from sophiagraph.access.contracts import (
    AccessConstraint,
    AccessConstraintMode,
    DelegationGrantState,
    DelegationMemoryGrant,
    DelegationMemoryGrantResolver,
    MemoryAccessContext,
    MemoryAccessDecision,
    MemoryAccessOperation,
    MemoryAccessReason,
    MemoryAccessRequest,
)
from sophiagraph.access.policy import (
    evaluate_memory_access,
    intersect_memory_namespaces,
    project_child_memory_grant,
)
from sophiagraph.access.telemetry import (
    AccessTelemetryOutcome,
    MemoryAccessTelemetryEvent,
    MemoryAccessTelemetryRecorder,
    ResolverTelemetryOutcome,
    noop_access_telemetry_recorder,
)
from sophiagraph.access.gateway import (
    AuthorizedSophiaGraphGateway,
    DelegatedMemoryAccessDeniedError,
)

__all__ = [
    "AccessConstraint",
    "AccessConstraintMode",
    "AccessTelemetryOutcome",
    "AuthorizedSophiaGraphGateway",
    "DelegationGrantState",
    "DelegationMemoryGrant",
    "DelegationMemoryGrantResolver",
    "DelegatedMemoryAccessDeniedError",
    "MemoryAccessContext",
    "MemoryAccessDecision",
    "MemoryAccessOperation",
    "MemoryAccessReason",
    "MemoryAccessRequest",
    "MemoryAccessTelemetryEvent",
    "MemoryAccessTelemetryRecorder",
    "ResolverTelemetryOutcome",
    "evaluate_memory_access",
    "intersect_memory_namespaces",
    "noop_access_telemetry_recorder",
    "project_child_memory_grant",
]
