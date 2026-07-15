from __future__ import annotations

import pytest

from sophiagraph.production_benchmarks import (
    STANDARD_SCALE_ITEM_COUNTS,
    PerformanceScenario,
    build_standard_scale_scenarios,
    run_performance_scenario,
)
from sophiagraph.server.contracts import RequestRejectedError
from sophiagraph.server.deployment import DeploymentProfile, enforce_deployment_profile


def test_production_profile_requires_auth_request_id_and_size_limit() -> None:
    profile = DeploymentProfile(
        profile_id="production",
        max_request_bytes=100,
        require_auth=True,
        require_request_id=True,
    )
    with pytest.raises(RequestRejectedError, match="auth_required"):
        enforce_deployment_profile(
            profile,
            {"jsonrpc": "2.0", "id": 1, "method": "ping"},
            transport="stdio",
            auth_mode="none",
        )
    with pytest.raises(RequestRejectedError, match="request_id_required"):
        enforce_deployment_profile(
            profile,
            {"jsonrpc": "2.0", "method": "ping"},
            transport="stdio",
            auth_mode="static_bearer",
        )


def test_scale_profiles_and_percentiles_are_operator_driven() -> None:
    scenarios = build_standard_scale_scenarios(
        "sqlite-retrieval",
        lambda item_count: {"processed": item_count},
        repeats=2,
    )
    assert tuple(item.item_count for item in scenarios) == STANDARD_SCALE_ITEM_COUNTS
    result = run_performance_scenario(
        PerformanceScenario(
            scenario_id="smoke",
            item_count=10,
            operation=lambda count: {"processed": count},
            repeats=2,
        )
    )
    assert result.p50_ms >= 0
    assert result.p95_ms >= result.p50_ms
    assert result.observations[0]["processed"] == 10
