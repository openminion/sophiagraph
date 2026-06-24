"""Vector conformance harness coverage."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
import math
from pathlib import Path

import pytest

from sophiagraph.contracts.errors import InvalidArgumentError
from sophiagraph.vectors import (
    BUILTIN_VECTOR_BACKEND,
    ConformanceCaseOutcome,
    ConformanceCaseResult,
    ConformanceReport,
    SimilarityMetric,
    VectorBackendConformanceCase,
    VectorSearchProtocol,
    compute_similarity,
    nearest_neighbors,
    run_conformance_harness,
)


class TestL2Similarity:
    def test_identical_vectors_have_zero_distance(self):
        score = compute_similarity(
            SimilarityMetric.L2, [1.0, 2.0, 3.0], [1.0, 2.0, 3.0]
        )
        assert score == 0.0  # -sqrt(0) = -0.0 == 0.0

    def test_closer_vectors_score_higher(self):
        query = [0.0, 0.0]
        close = compute_similarity(SimilarityMetric.L2, query, [0.1, 0.1])
        far = compute_similarity(SimilarityMetric.L2, query, [10.0, 10.0])
        assert close > far  # higher = more similar

    def test_l2_is_negative_euclidean_distance(self):
        score = compute_similarity(SimilarityMetric.L2, [0.0, 0.0], [3.0, 4.0])
        assert score == pytest.approx(-5.0)

    def test_l2_nearest_neighbor_against_synthetic_vectors(self):
        query = [1.0, 0.0]
        candidates = [
            ("near", [1.0, 0.1]),
            ("far", [0.0, 10.0]),
            ("medium", [0.5, 0.5]),
        ]
        results = nearest_neighbors(SimilarityMetric.L2, query, candidates, k=3)
        assert results[0][0] == "near"
        assert results[1][0] == "medium"
        assert results[2][0] == "far"


class TestDotSimilarity:
    def test_orthogonal_vectors_have_zero_dot(self):
        score = compute_similarity(SimilarityMetric.DOT, [1.0, 0.0], [0.0, 1.0])
        assert score == 0.0

    def test_aligned_vectors_score_high(self):
        score = compute_similarity(SimilarityMetric.DOT, [2.0, 0.0], [3.0, 0.0])
        assert score == pytest.approx(6.0)

    def test_dot_is_sum_of_products(self):
        score = compute_similarity(
            SimilarityMetric.DOT, [1.0, 2.0, 3.0], [4.0, 5.0, 6.0]
        )
        assert score == pytest.approx(1 * 4 + 2 * 5 + 3 * 6)

    def test_dot_nearest_neighbor_against_synthetic_vectors(self):
        query = [1.0, 0.0]
        candidates = [
            ("aligned", [2.0, 0.0]),
            ("orthogonal", [0.0, 5.0]),
            ("opposite", [-1.0, 0.0]),
        ]
        results = nearest_neighbors(SimilarityMetric.DOT, query, candidates, k=3)
        assert [cid for cid, _ in results] == ["aligned", "orthogonal", "opposite"]


# Cosine + shared metric infrastructure


class TestCosineSimilarity:
    def test_identical_unit_vectors_score_one(self):
        score = compute_similarity(SimilarityMetric.COSINE, [1.0, 0.0], [1.0, 0.0])
        assert score == pytest.approx(1.0)

    def test_opposite_vectors_score_neg_one(self):
        score = compute_similarity(SimilarityMetric.COSINE, [1.0, 0.0], [-1.0, 0.0])
        assert score == pytest.approx(-1.0)

    def test_orthogonal_vectors_score_zero(self):
        score = compute_similarity(SimilarityMetric.COSINE, [1.0, 0.0], [0.0, 1.0])
        assert score == pytest.approx(0.0)

    def test_zero_vector_raises(self):
        with pytest.raises(InvalidArgumentError):
            compute_similarity(SimilarityMetric.COSINE, [0.0, 0.0], [1.0, 1.0])


class TestSimilarityValidation:
    def test_metric_must_be_enum(self):
        with pytest.raises(InvalidArgumentError):
            compute_similarity("cosine", [1.0], [1.0])  # type: ignore[arg-type]

    def test_dimension_mismatch_raises(self):
        with pytest.raises(InvalidArgumentError):
            compute_similarity(SimilarityMetric.DOT, [1.0, 2.0], [1.0])

    def test_empty_vectors_raise(self):
        with pytest.raises(InvalidArgumentError):
            compute_similarity(SimilarityMetric.DOT, [], [])

    def test_non_sequence_raises(self):
        with pytest.raises(InvalidArgumentError):
            compute_similarity(SimilarityMetric.DOT, 1.0, [1.0])  # type: ignore[arg-type]


class TestSimilarityMetricEnumClosed:
    def test_metric_set_is_exactly_three(self):
        names = sorted(m.name for m in SimilarityMetric)
        assert names == ["COSINE", "DOT", "L2"]

    def test_metric_values_are_strings(self):
        values = {m.value for m in SimilarityMetric}
        assert values == {"cosine", "l2", "dot"}

    def test_anti_llm_source_token_check(self):
        """Anti-LLM boundary: the vectors module must not import anything
        that suggests LLM-judge of similarity."""
        src = (
            Path(__file__).resolve().parent.parent
            / "src"
            / "sophiagraph"
            / "vectors.py"
        ).read_text()
        for banned in ("openai", "anthropic", "llm_judge", "LLMJudge"):
            assert banned not in src, f"vectors.py must not reference {banned}"


def _sample_case(case_id: str = "sample") -> VectorBackendConformanceCase:
    return VectorBackendConformanceCase(
        case_id=case_id,
        metric=SimilarityMetric.COSINE,
        query=(1.0, 0.0),
        candidates=(("a", (1.0, 0.0)), ("b", (0.0, 1.0))),
        expected_top_k=("a",),
        k=1,
        description="alignment test",
    )


class TestVectorBackendConformanceCase:
    def test_construction_accepts_valid_payload(self):
        case = _sample_case()
        assert case.case_id == "sample"
        assert case.metric is SimilarityMetric.COSINE
        assert case.k == 1
        assert case.expected_top_k == ("a",)

    def test_case_is_frozen(self):
        case = _sample_case()
        with pytest.raises(FrozenInstanceError):
            case.case_id = "other"  # type: ignore[misc]

    def test_missing_case_id_raises(self):
        with pytest.raises(InvalidArgumentError):
            VectorBackendConformanceCase(
                case_id="",
                metric=SimilarityMetric.COSINE,
                query=(1.0,),
                candidates=(("a", (1.0,)),),
                expected_top_k=("a",),
            )

    def test_metric_must_be_enum(self):
        with pytest.raises(InvalidArgumentError):
            VectorBackendConformanceCase(
                case_id="x",
                metric="cosine",  # type: ignore[arg-type]
                query=(1.0,),
                candidates=(("a", (1.0,)),),
                expected_top_k=("a",),
            )

    def test_query_must_be_non_empty_tuple(self):
        with pytest.raises(InvalidArgumentError):
            VectorBackendConformanceCase(
                case_id="x",
                metric=SimilarityMetric.COSINE,
                query=(),
                candidates=(("a", (1.0,)),),
                expected_top_k=("a",),
            )

    def test_candidates_must_be_non_empty(self):
        with pytest.raises(InvalidArgumentError):
            VectorBackendConformanceCase(
                case_id="x",
                metric=SimilarityMetric.COSINE,
                query=(1.0,),
                candidates=(),
                expected_top_k=("a",),
            )

    def test_candidate_dimension_must_match_query(self):
        with pytest.raises(InvalidArgumentError):
            VectorBackendConformanceCase(
                case_id="x",
                metric=SimilarityMetric.COSINE,
                query=(1.0, 0.0),
                candidates=(("a", (1.0,)),),
                expected_top_k=("a",),
            )

    def test_duplicate_candidate_ids_raise(self):
        with pytest.raises(InvalidArgumentError):
            VectorBackendConformanceCase(
                case_id="x",
                metric=SimilarityMetric.COSINE,
                query=(1.0,),
                candidates=(("a", (1.0,)), ("a", (0.5,))),
                expected_top_k=("a",),
            )

    def test_expected_top_k_must_exist_in_candidates(self):
        with pytest.raises(InvalidArgumentError):
            VectorBackendConformanceCase(
                case_id="x",
                metric=SimilarityMetric.COSINE,
                query=(1.0,),
                candidates=(("a", (1.0,)),),
                expected_top_k=("z",),
            )

    def test_expected_top_k_length_must_equal_k(self):
        with pytest.raises(InvalidArgumentError):
            VectorBackendConformanceCase(
                case_id="x",
                metric=SimilarityMetric.COSINE,
                query=(1.0,),
                candidates=(("a", (1.0,)), ("b", (0.0,))),
                expected_top_k=("a",),
                k=2,
            )

    def test_k_must_be_positive(self):
        with pytest.raises(InvalidArgumentError):
            VectorBackendConformanceCase(
                case_id="x",
                metric=SimilarityMetric.COSINE,
                query=(1.0,),
                candidates=(("a", (1.0,)),),
                expected_top_k=("a",),
                k=0,
            )


class TestRunConformanceHarness:
    def test_all_pass(self):
        cases = [
            VectorBackendConformanceCase(
                case_id="c1",
                metric=SimilarityMetric.COSINE,
                query=(1.0, 0.0),
                candidates=(("a", (1.0, 0.0)), ("b", (0.0, 1.0))),
                expected_top_k=("a",),
            ),
            VectorBackendConformanceCase(
                case_id="c2",
                metric=SimilarityMetric.L2,
                query=(0.0, 0.0),
                candidates=(("near", (0.1, 0.1)), ("far", (10.0, 10.0))),
                expected_top_k=("near",),
            ),
        ]
        report = run_conformance_harness(BUILTIN_VECTOR_BACKEND, cases)
        assert isinstance(report, ConformanceReport)
        assert report.total == 2
        assert report.passed == 2
        assert report.failed == 0
        assert report.errored == 0
        assert report.is_clean is True

    def test_failure_when_expected_top_k_wrong(self):
        case = VectorBackendConformanceCase(
            case_id="bad-expectation",
            metric=SimilarityMetric.COSINE,
            query=(1.0, 0.0),
            candidates=(("a", (1.0, 0.0)), ("b", (0.0, 1.0))),
            expected_top_k=("b",),  # truth is "a"
        )
        report = run_conformance_harness(BUILTIN_VECTOR_BACKEND, [case])
        assert report.passed == 0
        assert report.failed == 1
        assert report.is_clean is False
        result = report.case_results[0]
        assert result.outcome is ConformanceCaseOutcome.FAIL
        assert result.actual_top_k == ("a",)

    def test_partial_mix(self):
        cases = [
            VectorBackendConformanceCase(
                case_id="passes",
                metric=SimilarityMetric.DOT,
                query=(1.0, 0.0),
                candidates=(("a", (2.0, 0.0)), ("b", (0.0, 5.0))),
                expected_top_k=("a",),
            ),
            VectorBackendConformanceCase(
                case_id="fails",
                metric=SimilarityMetric.DOT,
                query=(1.0, 0.0),
                candidates=(("a", (2.0, 0.0)), ("b", (0.0, 5.0))),
                expected_top_k=("b",),  # wrong expectation
            ),
        ]
        report = run_conformance_harness(BUILTIN_VECTOR_BACKEND, cases)
        assert report.passed == 1
        assert report.failed == 1
        assert report.is_clean is False

    def test_error_outcome_when_backend_raises(self):
        class _BoomBackend(VectorSearchProtocol):
            def search(self, metric, query, candidates, *, k=1):
                raise RuntimeError("simulated backend failure")

        case = _sample_case("boom")
        report = run_conformance_harness(_BoomBackend(), [case])
        assert report.errored == 1
        result = report.case_results[0]
        assert result.outcome is ConformanceCaseOutcome.ERROR
        assert "RuntimeError" in result.error_message
        assert "simulated backend failure" in result.error_message

    def test_empty_case_list_yields_empty_non_clean_report(self):
        report = run_conformance_harness(BUILTIN_VECTOR_BACKEND, [])
        assert report.total == 0
        # is_clean requires at least one case so empty != clean
        assert report.is_clean is False

    def test_backend_must_implement_search(self):
        class _NotABackend:
            pass

        with pytest.raises(InvalidArgumentError):
            run_conformance_harness(_NotABackend(), [_sample_case()])  # type: ignore[arg-type]

    def test_non_case_entry_raises(self):
        with pytest.raises(InvalidArgumentError):
            run_conformance_harness(BUILTIN_VECTOR_BACKEND, [object()])  # type: ignore[list-item]

    def test_top_k_greater_than_one(self):
        case = VectorBackendConformanceCase(
            case_id="top2",
            metric=SimilarityMetric.L2,
            query=(0.0, 0.0),
            candidates=(
                ("near", (0.1, 0.1)),
                ("medium", (1.0, 1.0)),
                ("far", (10.0, 10.0)),
            ),
            expected_top_k=("near", "medium"),
            k=2,
        )
        report = run_conformance_harness(BUILTIN_VECTOR_BACKEND, [case])
        assert report.passed == 1
        assert report.case_results[0].actual_top_k == ("near", "medium")

    def test_report_is_frozen(self):
        report = run_conformance_harness(BUILTIN_VECTOR_BACKEND, [])
        with pytest.raises(FrozenInstanceError):
            report.case_results = ()  # type: ignore[misc]


# Convenience: ConformanceCaseResult typing


class TestConformanceCaseResult:
    def test_default_actual_and_error(self):
        result = ConformanceCaseResult(case_id="x", outcome=ConformanceCaseOutcome.PASS)
        assert result.actual_top_k == ()
        assert result.error_message == ""

    def test_outcome_must_be_enum(self):
        # ConformanceCaseResult is a frozen dataclass — accepts the enum
        # value directly; runtime callers must construct with the enum.
        result = ConformanceCaseResult(
            case_id="x",
            outcome=ConformanceCaseOutcome.FAIL,
            actual_top_k=("b",),
        )
        assert result.outcome is ConformanceCaseOutcome.FAIL


# nearest_neighbors guardrails


class TestNearestNeighbors:
    def test_k_clamped_to_candidate_count(self):
        results = nearest_neighbors(
            SimilarityMetric.COSINE,
            [1.0, 0.0],
            [("a", [1.0, 0.0])],
            k=5,
        )
        assert len(results) == 1

    def test_k_must_be_positive(self):
        with pytest.raises(InvalidArgumentError):
            nearest_neighbors(
                SimilarityMetric.COSINE,
                [1.0, 0.0],
                [("a", [1.0, 0.0])],
                k=0,
            )

    def test_results_are_sorted_high_to_low(self):
        results = nearest_neighbors(
            SimilarityMetric.DOT,
            [1.0, 1.0],
            [("low", [0.0, 0.0]), ("high", [10.0, 10.0]), ("mid", [1.0, 1.0])],
            k=3,
        )
        scores = [score for _, score in results]
        assert scores == sorted(scores, reverse=True)


# Cross-metric monotonicity sanity


def test_higher_is_better_convention_holds_across_all_metrics():
    """All three metrics use the same 'higher = more similar' convention.

    Sanity check: the closest candidate to a unit vector must rank first
    under cosine, L2, and dot.
    """
    query = [1.0, 0.0]
    candidates = [
        ("aligned", [1.0, 0.0]),
        ("near", [0.9, 0.1]),
        ("far", [-1.0, 0.0]),
    ]
    for metric in (SimilarityMetric.COSINE, SimilarityMetric.L2, SimilarityMetric.DOT):
        top = nearest_neighbors(metric, query, candidates, k=1)
        assert top[0][0] == "aligned", f"metric {metric.value} mis-ranked"
        # Score for aligned >= score for far for all three metrics.
        all_scored = nearest_neighbors(metric, query, candidates, k=3)
        far_score = next(s for cid, s in all_scored if cid == "far")
        aligned_score = next(s for cid, s in all_scored if cid == "aligned")
        assert aligned_score >= far_score


def test_l2_distance_matches_manual_calculation():
    """Known-vector regression."""
    score = compute_similarity(SimilarityMetric.L2, [1.0, 2.0, 3.0], [4.0, 5.0, 6.0])
    expected_distance = math.sqrt((1 - 4) ** 2 + (2 - 5) ** 2 + (3 - 6) ** 2)
    assert score == pytest.approx(-expected_distance)
