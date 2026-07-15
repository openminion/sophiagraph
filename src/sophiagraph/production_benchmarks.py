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
    "PerformanceResult",
    "PerformanceScenario",
    "STANDARD_SCALE_ITEM_COUNTS",
    "build_standard_scale_scenarios",
    "run_performance_scenario",
]
