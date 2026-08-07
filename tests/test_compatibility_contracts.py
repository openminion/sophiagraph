from __future__ import annotations

import sophiagraph

from sophiagraph.backend_planning import plan_backend_execution
from sophiagraph.compatibility import (
    build_public_api_manifest,
    graphfakos_compatibility,
)
from sophiagraph.graph_backends import FakeGraphBackendAdapter


def test_graphfakos_supported_range_is_explicit() -> None:
    assert graphfakos_compatibility("0.0.5").supported is False
    assert graphfakos_compatibility("0.0.8").supported is True
    assert graphfakos_compatibility("1.0.0").supported is False


def test_public_api_manifest_is_sorted_and_versioned() -> None:
    manifest = build_public_api_manifest(sophiagraph)
    assert manifest.package_version == sophiagraph.__version__
    assert manifest.exports == tuple(sorted(sophiagraph.__all__))
    assert manifest.dependencies[0].package == "graphfakos"


def test_backend_plan_explains_pushdown_and_fallback() -> None:
    capabilities = FakeGraphBackendAdapter().capabilities()
    plan = plan_backend_execution(
        capabilities,
        ("neighbors", "temporal_filter"),
    )
    assert [step.execution for step in plan.steps] == ["backend", "local_fallback"]
    assert plan.requires_local_fallback is True
