"""Benchmark scorecard example."""

from __future__ import annotations

import json

from sophiagraph import run_default_benchmark_suite


def run_example() -> dict[str, object]:
    scorecard = run_default_benchmark_suite()
    return {
        "suite_id": scorecard.suite_id,
        "passed": scorecard.passed,
        "case_count": len(scorecard.results),
        "failed": scorecard.status_counts["failed"],
    }


def main() -> int:
    print(json.dumps(run_example(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
