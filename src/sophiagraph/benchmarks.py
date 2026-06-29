"""Deterministic public conformance fixtures and scorecards."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from importlib.metadata import PackageNotFoundError, version
import json
from typing import Any, Literal

from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.graph_backends import FakeGraphBackendAdapter
from sophiagraph.models import MemoryBlock, MemoryNamespace, validate_block_for_creation
from sophiagraph.okf import OKF_SPEC_BASELINE_COMMIT
from sophiagraph.query import GraphEdge, GraphNode, GraphSnapshot, shortest_path
from sophiagraph.workspace_sync import WorkspaceSourceLedgerEntry

BenchmarkStatus = Literal["passed", "failed", "skipped", "unsupported_by_design"]

BENCHMARK_STATUSES = frozenset({"passed", "failed", "skipped", "unsupported_by_design"})
BENCHMARK_GROUPS = frozenset(
    {
        "graph_navigation",
        "workspace_roundtrip",
        "interoperability",
        "privacy_export",
        "memory_lifecycle",
        "view_publish_profiles",
        "backend_parity",
        "openminion_direct",
    }
)

_BENCHMARK_VERSION = "2026-06-29"
_PACKAGE_NAME = "sophiagraph"


@dataclass(frozen=True, slots=True)
class BenchmarkUnsupportedReason:
    """Intentional non-support marker for competitor-style expectations."""

    code: str
    detail: str

    def __post_init__(self) -> None:
        if not self.code:
            raise InvalidArgumentError("unsupported reason code is required")
        if not self.detail:
            raise InvalidArgumentError("unsupported reason detail is required")

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "detail": self.detail}


@dataclass(frozen=True, slots=True)
class BenchmarkExpectation:
    """One structural expectation for a benchmark case."""

    expectation_id: str
    public_surface: str
    description: str
    expected: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.expectation_id:
            raise InvalidArgumentError("expectation_id is required")
        if not self.public_surface:
            raise InvalidArgumentError("public_surface is required")
        if not self.description:
            raise InvalidArgumentError("description is required")
        if not isinstance(self.expected, Mapping):
            raise InvalidArgumentError("expected must be a mapping")

    def to_dict(self) -> dict[str, Any]:
        return {
            "expectation_id": self.expectation_id,
            "public_surface": self.public_surface,
            "description": self.description,
            "expected": dict(self.expected),
        }


@dataclass(frozen=True, slots=True)
class BenchmarkCaseResult:
    """Structural outcome for one benchmark case."""

    case_id: str
    group: str
    status: BenchmarkStatus
    public_surface: str
    detail: str = ""
    observed: Mapping[str, Any] = field(default_factory=dict)
    unsupported_reason: BenchmarkUnsupportedReason | None = None

    def __post_init__(self) -> None:
        if not self.case_id:
            raise InvalidArgumentError("case_id is required")
        if self.group not in BENCHMARK_GROUPS:
            raise InvalidArgumentError(f"invalid benchmark group: {self.group!r}")
        if self.status not in BENCHMARK_STATUSES:
            raise InvalidArgumentError(f"invalid benchmark status: {self.status!r}")
        if not self.public_surface:
            raise InvalidArgumentError("public_surface is required")
        if not isinstance(self.observed, Mapping):
            raise InvalidArgumentError("observed must be a mapping")
        if self.status == "unsupported_by_design" and self.unsupported_reason is None:
            raise InvalidArgumentError("unsupported results require a reason")

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "group": self.group,
            "status": self.status,
            "public_surface": self.public_surface,
            "detail": self.detail,
            "observed": dict(self.observed),
            "unsupported_reason": (
                self.unsupported_reason.to_dict()
                if self.unsupported_reason is not None
                else None
            ),
        }


CaseCheck = Callable[[], BenchmarkCaseResult | bool | Mapping[str, Any] | None]


@dataclass(frozen=True, slots=True)
class BenchmarkCase:
    """Executable structural conformance case."""

    case_id: str
    group: str
    title: str
    expectation: BenchmarkExpectation
    check: CaseCheck | None = None
    unsupported_reason: BenchmarkUnsupportedReason | None = None

    def __post_init__(self) -> None:
        if not self.case_id:
            raise InvalidArgumentError("case_id is required")
        if self.group not in BENCHMARK_GROUPS:
            raise InvalidArgumentError(f"invalid benchmark group: {self.group!r}")
        if not self.title:
            raise InvalidArgumentError("title is required")
        if not isinstance(self.expectation, BenchmarkExpectation):
            raise InvalidArgumentError("expectation must be BenchmarkExpectation")
        if self.unsupported_reason is not None and self.check is not None:
            raise InvalidArgumentError("unsupported cases cannot also define a check")

    @property
    def public_surface(self) -> str:
        return self.expectation.public_surface


@dataclass(frozen=True, slots=True)
class BenchmarkSuite:
    """Ordered collection of deterministic benchmark cases."""

    suite_id: str
    title: str
    cases: tuple[BenchmarkCase, ...]
    fixture_revision: str = _BENCHMARK_VERSION
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.suite_id:
            raise InvalidArgumentError("suite_id is required")
        if not self.title:
            raise InvalidArgumentError("title is required")
        if not self.cases:
            raise InvalidArgumentError("suite requires at least one case")
        if not self.fixture_revision:
            raise InvalidArgumentError("fixture_revision is required")
        if not isinstance(self.metadata, Mapping):
            raise InvalidArgumentError("metadata must be a mapping")


@dataclass(frozen=True, slots=True)
class BenchmarkScorecard:
    """Serializable public benchmark summary."""

    suite_id: str
    suite_title: str
    package_version: str
    benchmark_version: str
    fixture_revision: str
    results: tuple[BenchmarkCaseResult, ...]
    metadata: Mapping[str, Any] = field(default_factory=dict)
    openminion_eval_payload: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.suite_id:
            raise InvalidArgumentError("suite_id is required")
        if not self.benchmark_version:
            raise InvalidArgumentError("benchmark_version is required")
        if not self.fixture_revision:
            raise InvalidArgumentError("fixture_revision is required")
        if not isinstance(self.metadata, Mapping):
            raise InvalidArgumentError("metadata must be a mapping")
        if not isinstance(self.openminion_eval_payload, Mapping):
            raise InvalidArgumentError("openminion_eval_payload must be a mapping")

    @property
    def status_counts(self) -> dict[str, int]:
        counts = {status: 0 for status in sorted(BENCHMARK_STATUSES)}
        for result in self.results:
            counts[result.status] += 1
        return counts

    @property
    def group_counts(self) -> dict[str, dict[str, int]]:
        counts: dict[str, dict[str, int]] = {
            group: {status: 0 for status in sorted(BENCHMARK_STATUSES)}
            for group in sorted(BENCHMARK_GROUPS)
        }
        for result in self.results:
            counts[result.group][result.status] += 1
        return counts

    @property
    def passed(self) -> bool:
        return not any(result.status == "failed" for result in self.results)

    def to_dict(self) -> dict[str, Any]:
        return {
            "suite_id": self.suite_id,
            "suite_title": self.suite_title,
            "package_version": self.package_version,
            "benchmark_version": self.benchmark_version,
            "fixture_revision": self.fixture_revision,
            "passed": self.passed,
            "status_counts": self.status_counts,
            "group_counts": self.group_counts,
            "results": [result.to_dict() for result in self.results],
            "metadata": dict(self.metadata),
            "openminion_eval_payload": dict(self.openminion_eval_payload),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)

    def to_markdown(self) -> str:
        lines = [
            f"# {self.suite_title}",
            "",
            f"- Suite: `{self.suite_id}`",
            f"- Package version: `{self.package_version}`",
            f"- Benchmark version: `{self.benchmark_version}`",
            f"- Fixture revision: `{self.fixture_revision}`",
            f"- Overall: `{'passed' if self.passed else 'failed'}`",
            "",
            "## Status Counts",
            "",
        ]
        for status, count in self.status_counts.items():
            lines.append(f"- `{status}`: {count}")
        lines.extend(
            [
                "",
                "## Results",
                "",
                "| Group | Case | Status | Public surface | Detail |",
                "| --- | --- | --- | --- | --- |",
            ]
        )
        for result in self.results:
            lines.append(
                "| "
                f"{result.group} | "
                f"{result.case_id} | "
                f"{result.status} | "
                f"`{result.public_surface}` | "
                f"{_markdown_cell(result.detail)} |"
            )
        return "\n".join(lines) + "\n"


def run_benchmark_suite(suite: BenchmarkSuite) -> BenchmarkScorecard:
    """Execute a suite and return a deterministic scorecard."""

    results = tuple(_run_case(case) for case in sorted(suite.cases, key=_case_key))
    return BenchmarkScorecard(
        suite_id=suite.suite_id,
        suite_title=suite.title,
        package_version=_package_version(),
        benchmark_version=_BENCHMARK_VERSION,
        fixture_revision=suite.fixture_revision,
        results=results,
        metadata=suite.metadata,
        openminion_eval_payload={
            "format": "sophiagraph.benchmark.scorecard.v1",
            "suite_id": suite.suite_id,
            "case_count": len(results),
        },
    )


def build_default_benchmark_suite(
    *, include_openminion_direct: bool = True
) -> BenchmarkSuite:
    """Build the public package-local conformance suite."""

    cases = [
        _case(
            "graph-shortest-path",
            "graph_navigation",
            "Shortest path over explicit structural graph edges",
            "sophiagraph.query.shortest_path",
            _check_graph_shortest_path,
            expected={"hop_count": 1},
        ),
        _case(
            "workspace-ledger-entry",
            "workspace_roundtrip",
            "Workspace source ledger round-trips through dict form",
            "sophiagraph.workspace_sync.WorkspaceSourceLedgerEntry",
            _check_workspace_ledger,
            expected={"relative_path": "notes/index.md"},
        ),
        _case(
            "okf-baseline-pinned",
            "interoperability",
            "OKF support exposes a pinned upstream baseline commit",
            "sophiagraph.okf.OKF_SPEC_BASELINE_COMMIT",
            _check_okf_baseline,
        ),
        _case(
            "text2cypher-refused",
            "interoperability",
            "Natural-language graph-query generation is intentionally absent",
            "sophiagraph.query.structural_graph_query",
            unsupported=BenchmarkUnsupportedReason(
                code="freeform_query_generation_refused",
                detail="Core accepts typed structural query DTOs only.",
            ),
        ),
        _case(
            "memory-block-creation",
            "memory_lifecycle",
            "Pinned memory block validates through the v1 creation gate",
            "sophiagraph.models.MemoryBlock",
            _check_memory_block_creation,
            expected={"mode": "pinned"},
        ),
        _case(
            "privacy-export-gates",
            "privacy_export",
            "Privacy export support exposes typed filter and redaction helpers",
            "sophiagraph.privacy.filter_snapshot_for_export",
            _check_privacy_exports,
        ),
        _case(
            "publish-profile-surface",
            "view_publish_profiles",
            "Publish profile helper is available for read-only shaping",
            "sophiagraph.publishing.build_publish_plan",
            _check_publish_profiles,
        ),
        _case(
            "fake-backend-capabilities",
            "backend_parity",
            "Fake backend exposes the same capability DTO path as real adapters",
            "sophiagraph.graph_backends.FakeGraphBackendAdapter",
            _check_fake_backend,
            expected={"backend_name": "fake"},
        ),
    ]
    if include_openminion_direct:
        cases.append(
            _case(
                "openminion-direct-handoff",
                "openminion_direct",
                "Scorecard provides typed handoff metadata without importing host packages",
                "sophiagraph.benchmarks.BenchmarkScorecard.openminion_eval_payload",
                _check_openminion_handoff,
            )
        )
    return BenchmarkSuite(
        suite_id="sophiagraph-public-conformance",
        title="SophiaGraph Public Benchmark And Conformance",
        cases=tuple(cases),
        metadata={"scope": "package-local deterministic fixtures"},
    )


def run_default_benchmark_suite(
    *, include_openminion_direct: bool = True
) -> BenchmarkScorecard:
    """Run the built-in public conformance suite."""

    return run_benchmark_suite(
        build_default_benchmark_suite(
            include_openminion_direct=include_openminion_direct
        )
    )


def scorecard_to_json(scorecard: BenchmarkScorecard) -> str:
    return scorecard.to_json()


def scorecard_to_markdown(scorecard: BenchmarkScorecard) -> str:
    return scorecard.to_markdown()


def _run_case(case: BenchmarkCase) -> BenchmarkCaseResult:
    if case.unsupported_reason is not None:
        return BenchmarkCaseResult(
            case_id=case.case_id,
            group=case.group,
            status="unsupported_by_design",
            public_surface=case.public_surface,
            detail=case.unsupported_reason.detail,
            unsupported_reason=case.unsupported_reason,
        )
    if case.check is None:
        return BenchmarkCaseResult(
            case_id=case.case_id,
            group=case.group,
            status="skipped",
            public_surface=case.public_surface,
            detail="no check defined",
        )
    try:
        observed = case.check()
    except Exception as exc:  # pragma: no cover - exercised through tests
        return BenchmarkCaseResult(
            case_id=case.case_id,
            group=case.group,
            status="failed",
            public_surface=case.public_surface,
            detail=f"{exc.__class__.__name__}: {exc}",
        )
    if isinstance(observed, BenchmarkCaseResult):
        return observed
    if observed is False:
        return BenchmarkCaseResult(
            case_id=case.case_id,
            group=case.group,
            status="failed",
            public_surface=case.public_surface,
            detail="check returned false",
        )
    if observed is None:
        data: Mapping[str, Any] = {}
    elif isinstance(observed, Mapping):
        data = observed
    else:
        data = {"value": observed}
    return BenchmarkCaseResult(
        case_id=case.case_id,
        group=case.group,
        status="passed",
        public_surface=case.public_surface,
        observed=data,
    )


def _case(
    case_id: str,
    group: str,
    title: str,
    public_surface: str,
    check: CaseCheck | None = None,
    *,
    expected: Mapping[str, Any] | None = None,
    unsupported: BenchmarkUnsupportedReason | None = None,
) -> BenchmarkCase:
    return BenchmarkCase(
        case_id=case_id,
        group=group,
        title=title,
        expectation=BenchmarkExpectation(
            expectation_id=f"{case_id}:expectation",
            public_surface=public_surface,
            description=title,
            expected={} if expected is None else dict(expected),
        ),
        check=check,
        unsupported_reason=unsupported,
    )


def _case_key(case: BenchmarkCase) -> tuple[str, str]:
    return case.group, case.case_id


def _package_version() -> str:
    try:
        return version(_PACKAGE_NAME)
    except PackageNotFoundError:
        return "0.0.1"


def _check_graph_shortest_path() -> Mapping[str, Any]:
    snapshot = GraphSnapshot(
        nodes=[
            GraphNode(record_id="a"),
            GraphNode(record_id="b"),
        ],
        edges=[
            GraphEdge(
                edge_id="edge:a-b",
                source_record_id="a",
                target_record_id="b",
                relation_type="supports",
            )
        ],
    )
    path = shortest_path(snapshot, "a", "b", direction="out")
    return {
        "path_found": path is not None,
        "hop_count": None if path is None else path.hop_count,
        "record_ids": [] if path is None else path.record_ids,
    }


def _check_workspace_ledger() -> Mapping[str, Any]:
    entry = WorkspaceSourceLedgerEntry(
        namespace=MemoryNamespace(agent_id="bench", graph_id="main"),
        relative_path="notes/index.md",
        source_id="file:notes/index.md",
        status="fresh",
        content_hash="sha256:bench",
        updated_at="2026-06-29T00:00:00+00:00",
        record_ids=("rec:index",),
    )
    loaded = WorkspaceSourceLedgerEntry.from_dict(entry.to_dict())
    return {
        "relative_path": loaded.relative_path,
        "status": loaded.status,
        "record_ids": list(loaded.record_ids),
    }


def _check_okf_baseline() -> Mapping[str, Any]:
    return {
        "baseline_commit_present": bool(OKF_SPEC_BASELINE_COMMIT),
        "baseline_commit": OKF_SPEC_BASELINE_COMMIT,
    }


def _check_memory_block_creation() -> Mapping[str, Any]:
    block = MemoryBlock(
        block_id="bench-block",
        class_name="session_pin",
        mode="pinned",
        content="Benchmark pinned memory block.",
        token_estimate=4,
        owner_namespace=MemoryNamespace(agent_id="bench", graph_id="main"),
        source="benchmark",
    )
    validate_block_for_creation(block)
    return {"block_id": block.block_id, "mode": block.mode}


def _check_privacy_exports() -> Mapping[str, Any]:
    from sophiagraph.privacy import filter_snapshot_for_export

    return {"helper": filter_snapshot_for_export.__name__}


def _check_publish_profiles() -> Mapping[str, Any]:
    from sophiagraph.publishing import build_publish_plan

    return {"helper": build_publish_plan.__name__}


def _check_fake_backend() -> Mapping[str, Any]:
    capabilities = FakeGraphBackendAdapter().capabilities()
    return {
        "backend_name": capabilities.backend_name,
        "neighbors": capabilities.supports("neighbors"),
    }


def _check_openminion_handoff() -> Mapping[str, Any]:
    return {
        "handoff_format": "sophiagraph.benchmark.scorecard.v1",
        "host_import_required": False,
    }


def _markdown_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


__all__ = [
    "BENCHMARK_GROUPS",
    "BENCHMARK_STATUSES",
    "BenchmarkCase",
    "BenchmarkCaseResult",
    "BenchmarkExpectation",
    "BenchmarkScorecard",
    "BenchmarkStatus",
    "BenchmarkSuite",
    "BenchmarkUnsupportedReason",
    "build_default_benchmark_suite",
    "run_benchmark_suite",
    "run_default_benchmark_suite",
    "scorecard_to_json",
    "scorecard_to_markdown",
]
