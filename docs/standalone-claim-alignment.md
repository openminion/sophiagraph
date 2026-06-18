# Sophiagraph Standalone Claim Alignment

Status: semantic alpha
Scope: public package claims and current shipped surfaces

## Purpose

This note maps the current public standalone SophiaGraph story to the package
surface that ships today.

It exists to:

1. keep public claims honest,
2. narrow vague claims before widening them,
3. name the differentiators that are worth preserving as real package value.

## Named differentiators kept explicit

Two package-owned differentiators stay explicit:

1. typed governance, policy-denial, and observability surfaces,
2. temporal freshness, lifecycle, and invalidation helpers.

These are worth preserving because they are already real, typed, and
cross-backend. This document keeps the proof around them visible without
broadening the story into hosted governance or freeform policy intelligence.

## Claim inventory

| Public claim | Shipped package surface | Proof today | Alignment |
| --- | --- | --- | --- |
| Sophiagraph is a standalone wisdom graph substrate for durable agent memory. | Public stores, models, query DTOs, portability bundles, release smoke, sibling server. | `README.md`, `tests/test_certification_suite.py`, `scripts/release_check.py` | Keep. This claim is already true. |
| Trust and temporal primitives are part of the package. | `sophiagraph.trust`, `sophiagraph.temporal`, lifecycle helpers, freshness ledger, invalidation/supersession helpers. | `tests/test_governance_observability.py`, `tests/test_local_sync_and_freshness.py`, `tests/test_temporal_convergence.py` | Narrow the wording to typed trust/policy and temporal freshness/lifecycle helpers, not a general trust-reasoning engine. |
| Governance and observability are package-owned. | Typed audit events, policy request/decision DTOs, denial-event builders, lifecycle decisions. | `tests/test_governance_observability.py`, `tests/test_certification_suite.py` | Keep, but say clearly that the package owns typed contracts and deterministic evaluation, not hosted operations. |
| Retrieval and navigation belong to Sophiagraph. | Deterministic search, hybrid retrieval assembly, graph traversal, retrieval explanations, context assembly. | `tests/test_context_assembly.py`, `tests/test_hybrid_retrieval.py`, `tests/test_certification_suite.py` | Keep with a tighter boundary: Sophiagraph owns retrieval over approved graph state; hosts own orchestration and provider execution. |
| Vector and rerank support are future-only. | Typed vector stage, rerank stage, vector metric registry, adapter protocols, hybrid request assembly already ship now. | `tests/test_hybrid_retrieval.py`, `docs/vector-conformance.md` | Correct the old underclaim. The package already owns typed vector/rerank stages, but not provider calls or auto-embedding. |
| Human note/import/source management is package-owned. | `sophiagraph.human` note CRUD, dry-run import planning, freshness/conflict console, HTML workbench preview. | `tests/test_human_management.py`, `docs/human-management.md` | Keep. This is a real package surface and part of the standalone story. |
| Webhook/lifecycle/governance operations are package-owned end to end. | Typed webhook delivery event shape and pure lifecycle evaluation exist; network delivery, schedulers, and hosted operations do not. | `tests/test_governance_observability.py`, `README.md` | Narrow. The package owns contract/evaluator shapes, not transport or hosted admin behavior. |

## Resulting public stance

The resulting honest standalone SophiaGraph story is:

1. a durable graph substrate for approved memory state,
2. a package-owned retrieval and navigation engine over that approved graph
   state,
3. a typed governance and observability contract surface,
4. a temporal freshness/lifecycle helper surface,
5. a local-first human management surface for notes, import dry-runs, and
   source inspection.

It is not:

1. a hosted governance control plane,
2. a background operations service,
3. a semantic policy engine driven by freeform model output,
4. a provider-owned vector service,
5. an automatic raw-chat-to-memory extractor.
