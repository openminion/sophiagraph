"""Low-cardinality operational telemetry for delegated memory access."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Literal

from sophiagraph.access.contracts import MemoryAccessOperation, MemoryAccessReason
from sophiagraph.contracts.errors import InvalidArgumentError

AccessTelemetryOutcome = Literal["allow", "deny"]
ResolverTelemetryOutcome = Literal["not_required", "resolved", "failed"]


@dataclass(frozen=True, slots=True)
class MemoryAccessTelemetryEvent:
    """One bounded metric event without identities, content, or query values."""

    operation: MemoryAccessOperation
    outcome: AccessTelemetryOutcome
    reason: MemoryAccessReason
    resolver_outcome: ResolverTelemetryOutcome
    resolver_duration_ms: float = 0.0
    omitted_count: int = 0
    effective_max_results: int = 0
    effective_max_context_tokens: int = 0

    def __post_init__(self) -> None:
        if self.outcome not in {"allow", "deny"}:
            raise InvalidArgumentError("invalid telemetry outcome")
        if self.resolver_outcome not in {"not_required", "resolved", "failed"}:
            raise InvalidArgumentError("invalid resolver telemetry outcome")
        if self.resolver_duration_ms < 0 or self.omitted_count < 0:
            raise InvalidArgumentError("telemetry measurements cannot be negative")


MemoryAccessTelemetryRecorder = Callable[[MemoryAccessTelemetryEvent], None]


def noop_access_telemetry_recorder(
    event: MemoryAccessTelemetryEvent,
) -> None:  # pragma: no cover - trivial callback
    return None


__all__ = [
    "AccessTelemetryOutcome",
    "MemoryAccessTelemetryEvent",
    "MemoryAccessTelemetryRecorder",
    "ResolverTelemetryOutcome",
    "noop_access_telemetry_recorder",
]
