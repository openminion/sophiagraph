# Sophiagraph Retrieval Boundary

Status: semantic alpha
Scope: package-owned retrieval and navigation contract

## Purpose

This note keeps the package-owned retrieval boundary explicit so the shipped
query surface, README, and broader product positioning stay aligned.

## Canonical rule

SophiaGraph owns retrieval and navigation **over approved graph state already
stored in the package**.

That includes:

1. deterministic search over records, links, and graph neighborhoods,
2. hybrid retrieval assembly across keyword, vector, graph, recency, trust,
   and rerank stages,
3. retrieval explanations and structural evidence payloads,
4. local context assembly modes that operate only on stored package facts,
5. caller-supplied vector and rerank adapter protocols.

OpenMinion and other hosts own:

1. deciding when retrieval should run in a turn,
2. cross-system merge/orchestration across memory, third-brain, tool, or live
   runtime sources,
3. prompt assembly and user-visible answer composition,
4. provider execution for embeddings, rerankers, or model-backed retrieval
   helpers,
5. degradation policy when upstream sources or providers fail.

## What the package does not do

Even though the package owns retrieval stages, it still does **not**:

1. call embedding providers directly,
2. schedule or automatically refresh embeddings,
3. infer new memory facts from retrieved prose,
4. run hosted retrieval services or browser-facing APIs by itself,
5. widen retrieval into freeform semantic judgment outside explicit typed
   inputs.

## Why this matters

This split preserves both halves of the architecture:

1. the package stays a strong standalone retrieval substrate,
2. host runtimes keep orchestration and policy ownership,
3. vector/rerank support can exist in-package without turning the package into
   a hosted inference service.

## Proof pointers

- `tests/test_hybrid_retrieval.py`
- `tests/test_context_assembly.py`
- `tests/test_certification_suite.py`
- `docs/vector-conformance.md`
