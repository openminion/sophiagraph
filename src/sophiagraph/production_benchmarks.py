"""Scale-profile benchmark contracts for operator-run certification."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Callable, Mapping

from sophiagraph.contracts.errors import InvalidArgumentError

STANDARD_SCALE_ITEM_COUNTS = (10_000, 100_000, 1_000_000)
BenchmarkOperation = Callable[[int], Mapping[str, float | int | str]]


@dataclass(frozen=True, slots=True)
class PerformanceScenario:
    scenario_id: str
    item_count: int
    operation: BenchmarkOperation
    repeats: int = 3

    def __post_init__(self) -> None:
        if not self.scenario_id or self.item_count <= 0 or self.repeats <= 0:
            raise InvalidArgumentError(
                "scenario_id, positive item_count, and repeats are required"
            )


@dataclass(frozen=True, slots=True)
class PerformanceResult:
    scenario_id: str
    item_count: int
    durations_ms: tuple[float, ...]
    p50_ms: float
    p95_ms: float
    observations: tuple[Mapping[str, float | int | str], ...]


@dataclass(frozen=True, slots=True)
class PerformanceBudget:
    """Explicit operator-owned pass criteria for one benchmark scenario."""

    scenario_id: str
    max_p50_ms: float
    max_p95_ms: float
    min_processed_items: int | None = None

    def __post_init__(self) -> None:
        if not self.scenario_id:
            raise InvalidArgumentError("scenario_id is required")
        if self.max_p50_ms < 0 or self.max_p95_ms < 0:
            raise InvalidArgumentError(
                "performance latency budgets must be non-negative"
            )
        if self.max_p95_ms < self.max_p50_ms:
            raise InvalidArgumentError("max_p95_ms cannot be lower than max_p50_ms")
        if self.min_processed_items is not None and self.min_processed_items <= 0:
            raise InvalidArgumentError("min_processed_items must be positive")


@dataclass(frozen=True, slots=True)
class PerformanceAssessment:
    """Deterministic comparison of one result against an explicit budget."""

    result: PerformanceResult
    budget: PerformanceBudget
    passed: bool
    violations: tuple[str, ...] = ()


def run_performance_scenario(scenario: PerformanceScenario) -> PerformanceResult:
    durations = []
    observations = []
    for _ in range(scenario.repeats):
        started = perf_counter()
        observations.append(dict(scenario.operation(scenario.item_count)))
        durations.append((perf_counter() - started) * 1000.0)
    ordered = sorted(durations)
    return PerformanceResult(
        scenario_id=scenario.scenario_id,
        item_count=scenario.item_count,
        durations_ms=tuple(durations),
        p50_ms=_percentile(ordered, 0.50),
        p95_ms=_percentile(ordered, 0.95),
        observations=tuple(observations),
    )


def assess_performance_result(
    result: PerformanceResult,
    budget: PerformanceBudget,
) -> PerformanceAssessment:
    """Return pass/fail evidence without selecting budgets inside the package."""

    if result.scenario_id != budget.scenario_id:
        raise InvalidArgumentError("result and budget scenario_id values must match")
    violations: list[str] = []
    if result.p50_ms > budget.max_p50_ms:
        violations.append("p50_exceeded")
    if result.p95_ms > budget.max_p95_ms:
        violations.append("p95_exceeded")
    if budget.min_processed_items is not None:
        processed: list[int] = []
        for observation in result.observations:
            value = observation.get("processed")
            if isinstance(value, int) and not isinstance(value, bool):
                processed.append(value)
        if not processed or min(processed) < budget.min_processed_items:
            violations.append("processed_items_below_minimum")
    return PerformanceAssessment(
        result=result,
        budget=budget,
        passed=not violations,
        violations=tuple(violations),
    )


def build_standard_scale_scenarios(
    scenario_prefix: str,
    operation: BenchmarkOperation,
    *,
    repeats: int = 3,
) -> tuple[PerformanceScenario, ...]:
    if not scenario_prefix:
        raise InvalidArgumentError("scenario_prefix is required")
    return tuple(
        PerformanceScenario(
            scenario_id=f"{scenario_prefix}-{item_count}",
            item_count=item_count,
            operation=operation,
            repeats=repeats,
        )
        for item_count in STANDARD_SCALE_ITEM_COUNTS
    )


def _percentile(ordered: list[float], fraction: float) -> float:
    index = min(round((len(ordered) - 1) * fraction), len(ordered) - 1)
    return ordered[index]


__all__ = [
    "BenchmarkOperation",
    "PerformanceAssessment",
    "PerformanceBudget",
    "PerformanceResult",
    "PerformanceScenario",
    "STANDARD_SCALE_ITEM_COUNTS",
    "assess_performance_result",
    "build_standard_scale_scenarios",
    "run_performance_scenario",
]
