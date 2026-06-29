"""Public benchmark and conformance scorecard coverage."""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

import sophiagraph
from sophiagraph import (
    BENCHMARK_GROUPS,
    BenchmarkCase,
    BenchmarkExpectation,
    BenchmarkSuite,
    BenchmarkUnsupportedReason,
    build_default_benchmark_suite,
    run_benchmark_suite,
    run_default_benchmark_suite,
    scorecard_to_json,
    scorecard_to_markdown,
)
from sophiagraph.contracts.errors import InvalidArgumentError


def test_benchmark_dtos_validate_closed_statuses() -> None:
    expectation = BenchmarkExpectation(
        expectation_id="exp",
        public_surface="sophiagraph.example",
        description="example expectation",
    )
    with pytest.raises(InvalidArgumentError):
        sophiagraph.BenchmarkCaseResult(
            case_id="case",
            group="graph_navigation",
            status="maybe",  # type: ignore[arg-type]
            public_surface=expectation.public_surface,
        )


def test_benchmark_runner_records_pass_failure_skip_and_unsupported() -> None:
    suite = BenchmarkSuite(
        suite_id="unit",
        title="Unit Suite",
        cases=(
            _case("pass", lambda: {"ok": True}),
            _case("fail", lambda: False),
            BenchmarkCase(
                case_id="skip",
                group="graph_navigation",
                title="skipped",
                expectation=_expect("skip"),
            ),
            BenchmarkCase(
                case_id="unsupported",
                group="graph_navigation",
                title="unsupported",
                expectation=_expect("unsupported"),
                unsupported_reason=BenchmarkUnsupportedReason(
                    code="not_in_core",
                    detail="Intentionally owned by a host runtime.",
                ),
            ),
        ),
    )

    scorecard = run_benchmark_suite(suite)

    assert scorecard.status_counts["passed"] == 1
    assert scorecard.status_counts["failed"] == 1
    assert scorecard.status_counts["skipped"] == 1
    assert scorecard.status_counts["unsupported_by_design"] == 1
    assert not scorecard.passed


def test_default_benchmark_suite_covers_all_public_groups() -> None:
    suite = build_default_benchmark_suite()

    assert {case.group for case in suite.cases} == set(BENCHMARK_GROUPS)


def test_default_scorecard_is_deterministic_and_serializable() -> None:
    first = run_default_benchmark_suite()
    second = run_default_benchmark_suite()

    assert first.to_dict() == second.to_dict()
    assert first.passed
    assert first.status_counts["failed"] == 0
    assert first.status_counts["unsupported_by_design"] == 1
    assert first.openminion_eval_payload["format"] == (
        "sophiagraph.benchmark.scorecard.v1"
    )

    payload = json.loads(scorecard_to_json(first))
    assert payload["suite_id"] == "sophiagraph-public-conformance"
    assert payload["passed"] is True


def test_markdown_scorecard_has_no_local_paths() -> None:
    markdown = scorecard_to_markdown(run_default_benchmark_suite())

    assert "# SophiaGraph Public Benchmark And Conformance" in markdown
    assert "/Users/" not in markdown
    assert "Jongs-MacBook" not in markdown
    assert "| Group | Case | Status | Public surface | Detail |" in markdown


def test_benchmark_cli_emits_json_and_markdown() -> None:
    json_result = subprocess.run(
        [sys.executable, "-m", "sophiagraph", "benchmark"],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(json_result.stdout)
    assert payload["suite_id"] == "sophiagraph-public-conformance"

    md_result = subprocess.run(
        [sys.executable, "-m", "sophiagraph", "benchmark", "--format", "markdown"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "## Status Counts" in md_result.stdout


def test_benchmark_core_does_not_import_host_eval_package() -> None:
    import sophiagraph.benchmarks as benchmarks

    assert "openminion_eval" not in benchmarks.__dict__


def _expect(case_id: str) -> BenchmarkExpectation:
    return BenchmarkExpectation(
        expectation_id=f"{case_id}:expect",
        public_surface="sophiagraph.tests",
        description=f"{case_id} expectation",
    )


def _case(case_id: str, check) -> BenchmarkCase:
    return BenchmarkCase(
        case_id=case_id,
        group="graph_navigation",
        title=case_id,
        expectation=_expect(case_id),
        check=check,
    )
