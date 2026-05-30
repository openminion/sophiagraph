"""Vector similarity primitives and conformance harness."""

from __future__ import annotations

import enum
import math
from dataclasses import dataclass, field
from typing import Callable, Sequence

from sophiagraph.contracts.errors import InvalidArgumentError

__all__ = [
    "ConformanceCaseOutcome",
    "ConformanceCaseResult",
    "ConformanceReport",
    "SimilarityMetric",
    "VectorBackendConformanceCase",
    "VectorSearchProtocol",
    "compute_similarity",
    "nearest_neighbors",
    "run_conformance_harness",
]


class SimilarityMetric(str, enum.Enum):
    """Closed enum of supported vector-similarity metrics."""

    COSINE = "cosine"
    L2 = "l2"
    DOT = "dot"


def _validate_pair(a: Sequence[float], b: Sequence[float]) -> None:
    if not isinstance(a, (list, tuple)) or not isinstance(b, (list, tuple)):
        raise InvalidArgumentError("similarity inputs must be sequences of floats")
    if len(a) == 0 or len(b) == 0:
        raise InvalidArgumentError("similarity inputs must be non-empty")
    if len(a) != len(b):
        raise InvalidArgumentError(f"vector dimension mismatch: {len(a)} vs {len(b)}")


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity in [-1.0, 1.0]; higher = more similar."""
    _validate_pair(a, b)
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for x, y in zip(a, b):
        fx = float(x)
        fy = float(y)
        dot += fx * fy
        norm_a += fx * fx
        norm_b += fy * fy
    if norm_a == 0.0 or norm_b == 0.0:
        raise InvalidArgumentError("cosine similarity undefined for zero vector")
    return dot / (math.sqrt(norm_a) * math.sqrt(norm_b))


def _l2_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """L2 similarity as negative euclidean distance."""
    _validate_pair(a, b)
    total = 0.0
    for x, y in zip(a, b):
        diff = float(x) - float(y)
        total += diff * diff
    return -math.sqrt(total)


def _dot(a: Sequence[float], b: Sequence[float]) -> float:
    """Dot-product similarity; higher = more similar."""
    _validate_pair(a, b)
    return sum(float(x) * float(y) for x, y in zip(a, b))


_METRIC_DISPATCH: dict[
    SimilarityMetric,
    Callable[[Sequence[float], Sequence[float]], float],
] = {
    SimilarityMetric.COSINE: _cosine,
    SimilarityMetric.L2: _l2_similarity,
    SimilarityMetric.DOT: _dot,
}


def compute_similarity(
    metric: SimilarityMetric,
    a: Sequence[float],
    b: Sequence[float],
) -> float:
    """Compute the typed similarity score between two vectors."""
    if not isinstance(metric, SimilarityMetric):
        raise InvalidArgumentError("metric must be a SimilarityMetric enum value")
    return _METRIC_DISPATCH[metric](a, b)


def nearest_neighbors(
    metric: SimilarityMetric,
    query: Sequence[float],
    candidates: Sequence[tuple[str, Sequence[float]]],
    *,
    k: int = 1,
) -> list[tuple[str, float]]:
    """Return the top-k candidate IDs and scores."""
    if k < 1:
        raise InvalidArgumentError("k must be >= 1")
    scored: list[tuple[str, float]] = []
    for candidate_id, vector in candidates:
        score = compute_similarity(metric, query, vector)
        scored.append((str(candidate_id), score))
    scored.sort(key=lambda item: item[1], reverse=True)
    return scored[: min(k, len(scored))]


@dataclass(frozen=True, slots=True)
class VectorBackendConformanceCase:
    """Operator-supplied test case for a vector backend."""

    case_id: str
    metric: SimilarityMetric
    query: tuple[float, ...]
    candidates: tuple[tuple[str, tuple[float, ...]], ...]
    expected_top_k: tuple[str, ...]
    k: int = 1
    description: str = ""

    def __post_init__(self) -> None:
        if not self.case_id:
            raise InvalidArgumentError("case_id is required")
        if not isinstance(self.metric, SimilarityMetric):
            raise InvalidArgumentError("metric must be a SimilarityMetric")
        if not isinstance(self.query, tuple) or len(self.query) == 0:
            raise InvalidArgumentError("query must be a non-empty tuple of floats")
        if not isinstance(self.candidates, tuple) or len(self.candidates) == 0:
            raise InvalidArgumentError("candidates must be a non-empty tuple")
        seen_ids: set[str] = set()
        for entry in self.candidates:
            if not (isinstance(entry, tuple) and len(entry) == 2):
                raise InvalidArgumentError(
                    "each candidate must be a (id, vector) tuple"
                )
            cid, vec = entry
            if not isinstance(cid, str) or not cid:
                raise InvalidArgumentError("candidate id must be a non-empty string")
            if cid in seen_ids:
                raise InvalidArgumentError(f"duplicate candidate id: {cid}")
            seen_ids.add(cid)
            if not isinstance(vec, tuple) or len(vec) != len(self.query):
                raise InvalidArgumentError(
                    f"candidate {cid} vector must match query dimension"
                )
        if not isinstance(self.expected_top_k, tuple) or len(self.expected_top_k) == 0:
            raise InvalidArgumentError("expected_top_k must be a non-empty tuple")
        for cid in self.expected_top_k:
            if cid not in seen_ids:
                raise InvalidArgumentError(
                    f"expected_top_k id {cid!r} not present in candidates"
                )
        if self.k < 1:
            raise InvalidArgumentError("k must be >= 1")
        if len(self.expected_top_k) != self.k:
            raise InvalidArgumentError("expected_top_k length must equal k")


class ConformanceCaseOutcome(str, enum.Enum):
    """Closed enum for per-case conformance outcomes."""

    PASS = "pass"
    FAIL = "fail"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class ConformanceCaseResult:
    case_id: str
    outcome: ConformanceCaseOutcome
    actual_top_k: tuple[str, ...] = ()
    error_message: str = ""


@dataclass(frozen=True, slots=True)
class ConformanceReport:
    case_results: tuple[ConformanceCaseResult, ...] = field(default_factory=tuple)

    @property
    def total(self) -> int:
        return len(self.case_results)

    @property
    def passed(self) -> int:
        return sum(
            1 for r in self.case_results if r.outcome is ConformanceCaseOutcome.PASS
        )

    @property
    def failed(self) -> int:
        return sum(
            1 for r in self.case_results if r.outcome is ConformanceCaseOutcome.FAIL
        )

    @property
    def errored(self) -> int:
        return sum(
            1 for r in self.case_results if r.outcome is ConformanceCaseOutcome.ERROR
        )

    @property
    def is_clean(self) -> bool:
        return self.failed == 0 and self.errored == 0 and self.total > 0


class VectorSearchProtocol:
    """Structural protocol any vector backend can satisfy."""

    def search(
        self,
        metric: SimilarityMetric,
        query: Sequence[float],
        candidates: Sequence[tuple[str, Sequence[float]]],
        *,
        k: int = 1,
    ) -> list[tuple[str, float]]:
        raise NotImplementedError


class _BuiltinBackend(VectorSearchProtocol):
    """Sophiagraph's built-in deterministic vector backend."""

    def search(
        self,
        metric: SimilarityMetric,
        query: Sequence[float],
        candidates: Sequence[tuple[str, Sequence[float]]],
        *,
        k: int = 1,
    ) -> list[tuple[str, float]]:
        return nearest_neighbors(metric, query, candidates, k=k)


BUILTIN_VECTOR_BACKEND: VectorSearchProtocol = _BuiltinBackend()


def run_conformance_harness(
    backend: VectorSearchProtocol,
    cases: Sequence[VectorBackendConformanceCase],
) -> ConformanceReport:
    """Run each conformance case against ``backend`` and report results."""
    if not hasattr(backend, "search"):
        raise InvalidArgumentError(
            "backend must implement search(metric, query, candidates, *, k)"
        )
    results: list[ConformanceCaseResult] = []
    for case in cases:
        if not isinstance(case, VectorBackendConformanceCase):
            raise InvalidArgumentError(
                "every case must be a VectorBackendConformanceCase"
            )
        try:
            actual = backend.search(
                case.metric,
                list(case.query),
                [(cid, list(vec)) for cid, vec in case.candidates],
                k=case.k,
            )
        except Exception as exc:  # noqa: BLE001 - report-time conversion
            results.append(
                ConformanceCaseResult(
                    case_id=case.case_id,
                    outcome=ConformanceCaseOutcome.ERROR,
                    error_message=f"{type(exc).__name__}: {exc}",
                )
            )
            continue
        actual_ids = tuple(str(item[0]) for item in actual)
        outcome = (
            ConformanceCaseOutcome.PASS
            if actual_ids == case.expected_top_k
            else ConformanceCaseOutcome.FAIL
        )
        results.append(
            ConformanceCaseResult(
                case_id=case.case_id,
                outcome=outcome,
                actual_top_k=actual_ids,
            )
        )
    return ConformanceReport(case_results=tuple(results))
