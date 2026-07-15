"""Deterministic capability planning for optional graph backends."""

from __future__ import annotations

from dataclasses import dataclass

from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.graph_backends import GraphBackendCapabilities, GraphBackendFeature


@dataclass(frozen=True, slots=True)
class BackendPlanStep:
    feature: GraphBackendFeature
    execution: str
    reason: str


@dataclass(frozen=True, slots=True)
class BackendExecutionPlan:
    backend_name: str
    steps: tuple[BackendPlanStep, ...]

    @property
    def requires_local_fallback(self) -> bool:
        return any(step.execution == "local_fallback" for step in self.steps)


def plan_backend_execution(
    capabilities: GraphBackendCapabilities,
    requested_features: tuple[GraphBackendFeature, ...],
    *,
    allow_local_fallback: bool = True,
) -> BackendExecutionPlan:
    if not requested_features:
        raise InvalidArgumentError("at least one backend feature is required")
    steps = []
    for feature in requested_features:
        supported = capabilities.supports(feature)
        if not supported and not allow_local_fallback:
            raise InvalidArgumentError(
                f"backend {capabilities.backend_name!r} does not support {feature!r}"
            )
        steps.append(
            BackendPlanStep(
                feature=feature,
                execution="backend" if supported else "local_fallback",
                reason=(
                    "backend_capability_declared"
                    if supported
                    else "backend_capability_absent"
                ),
            )
        )
    return BackendExecutionPlan(
        backend_name=capabilities.backend_name,
        steps=tuple(steps),
    )


__all__ = [
    "BackendExecutionPlan",
    "BackendPlanStep",
    "plan_backend_execution",
]
