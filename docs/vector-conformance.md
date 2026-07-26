# Vector Conformance Harness

Status: semantic alpha
Scope: metric registry and backend-neutral conformance checks

`sophiagraph.vectors` ships a typed similarity-metric registry and a
backend-agnostic conformance harness. Any vector backend that wants to
claim parity with SophiaGraph's built-in substrate runs the same
operator-supplied test cases through the harness and reports structural
pass/fail per case.

This is the bounded package-owned slice:

1. typed conformance,
2. deterministic `L2` / `dot` / `cosine` metrics, and
3. backend-neutral parity checks over the built-in substrate.

Concrete backend integrations remain separate follow-on work when real consumer
demand exists.

Storage capability reports expose whether a selected store supports vector
lifecycle metadata, external vector ids, active model sets, and default
vector-backend posture. See
[`storage-retrieval-backends.md`](storage-retrieval-backends.md) for the
storage/retrieval contract that wraps this harness.

## What's in the box

- `SimilarityMetric` — closed enum: `COSINE`, `L2`, `DOT`. All metrics
  follow a "higher = more similar" convention so backend code can
  always rank with `sorted(..., reverse=True)`.
- `compute_similarity(metric, a, b)` — pure scalar similarity.
- `nearest_neighbors(metric, query, candidates, *, k=1)` — top-k ranked
  `(candidate_id, score)` pairs.
- `VectorBackendConformanceCase` — frozen, validated operator-supplied
  test case (query vector + candidate set + expected top-k).
- `run_conformance_harness(backend, cases)` — pure function that runs
  each case and emits a typed `ConformanceReport`.
- `VectorSearchProtocol` — structural protocol any backend implements
  (`search(metric, query, candidates, *, k)`).
- `BUILTIN_VECTOR_BACKEND` — SophiaGraph's built-in deterministic
  backend (delegates to `nearest_neighbors`).

## Quick start - registering a backend

A backend is anything with a `search` method matching `VectorSearchProtocol`:

```python
from sophiagraph.vectors import (
    SimilarityMetric,
    VectorSearchProtocol,
    nearest_neighbors,
)


class MyBackend(VectorSearchProtocol):
    def search(self, metric, query, candidates, *, k=1):
        # Delegate to your real backend or, for parity testing, the
        # built-in implementation.
        return nearest_neighbors(metric, query, candidates, k=k)
```

Backends are passed as instances; there is no global registry. This
keeps the harness side-effect-free.

## Quick start - registering a case

```python
from sophiagraph.vectors import (
    SimilarityMetric,
    VectorBackendConformanceCase,
)

case = VectorBackendConformanceCase(
    case_id="orthogonal-pair-cosine",
    metric=SimilarityMetric.COSINE,
    query=(1.0, 0.0),
    candidates=(
        ("aligned", (1.0, 0.0)),
        ("orthogonal", (0.0, 1.0)),
    ),
    expected_top_k=("aligned",),
    k=1,
    description="aligned vector should rank above orthogonal one",
)
```

Validation runs at construction:

- `case_id` must be non-empty.
- `metric` must be a `SimilarityMetric` enum value.
- `query` must be a non-empty tuple of floats.
- Every candidate vector must match the query dimension.
- Candidate ids must be unique.
- `expected_top_k` ids must all appear in the candidate set and the
  tuple length must equal `k`.

## Quick start - running the harness

```python
from sophiagraph.vectors import (
    BUILTIN_VECTOR_BACKEND,
    run_conformance_harness,
)

report = run_conformance_harness(BUILTIN_VECTOR_BACKEND, [case])
assert report.is_clean  # passed > 0 and failed + errored == 0
assert report.passed == 1
```

`ConformanceReport` is a frozen dataclass with these accessors:

- `total` — total case count.
- `passed` / `failed` / `errored` — per-outcome counts.
- `is_clean` — `True` iff `total > 0` and there are no failures or
  errors.
- `case_results` — tuple of per-case `ConformanceCaseResult` records
  carrying `case_id`, `outcome` (`PASS` / `FAIL` / `ERROR`),
  `actual_top_k`, and `error_message`.

## Anti-LLM boundary

The harness is deterministic by design:

1. `SimilarityMetric` is a closed enum; adding a new metric is a
   deliberate code change.
2. Similarity is scalar math; there is no "is this match close enough"
   LLM call.
3. Conformance cases carry operator-supplied vectors and expected
   top-k. The harness does not invent test vectors.
4. `ConformanceCaseOutcome` is a closed enum and equality on top-k ids
   is structural string comparison.

## Out of scope

- Per-backend client integrations (pgvector, Qdrant, Pinecone, Weaviate). Each
  should ship as its own additive package surface only when a concrete consumer
  requires it.
- HNSW / IVF / approximate-search recall measurement. The harness
  pins exact top-k ordering for the cases it is given.
- Numpy-backed bulk operations. Sophiagraph maintains a
  zero-dependency runtime; metric implementations are hand-rolled.
