# Sophiagraph Standalone + OpenMinion Certification Readiness Matrix

## Purpose

SGSOCT-05 — single map of every competitive child lane to its
standalone SophiaGraph proof and its OpenMinion direct-library proof.

## Scope

The matrix below lists each completed substrate lane, the exact test
target that proves the public surface works standalone, and the exact
test target that proves OpenMinion can consume it as a direct library.
Lanes with no OpenMinion-facing surface are marked `n/a`.

## Non-goals

This matrix does not cover hosted-service behavior, scheduled-worker
behavior, or webhook delivery transport.

## Success criteria

Every row that is not `n/a` must point to a passing test in the
SophiaGraph or OpenMinion repository. The certification suite re-runs
on every release-check pass.

## Acceptance criteria

The matrix is current as of the latest tracker QA pass. New lanes must
add a row before promoting from `wip/` to `qa/`.

## Failure criteria

A missing test target, a row pointing to a deleted test, or a row that
relies on private SophiaGraph modules from the OpenMinion side fails
certification and blocks release.

## Matrix

| Lane | Standalone proof | OpenMinion direct-library proof |
| --- | --- | --- |
| Vault sync + round-trip (SGVSR) | `sophiagraph/tests/test_vault_sync.py` | `openminion/tests/memory/test_sophiagraph_vault_direct_library.py` |
| Temporal context graph convergence (SGTKG) | `sophiagraph/tests/test_temporal_convergence.py` | `openminion/tests/memory/test_sophiagraph_temporal_convergence.py` |
| Context assembly + retrieval modes (SGCARM) | `sophiagraph/tests/test_context_assembly.py` | `openminion/tests/memory/test_sophiagraph_context_assembly.py` |
| Hybrid retrieval staging + explanations | `sophiagraph/tests/test_hybrid_retrieval.py` | `openminion/tests/memory/test_sophiagraph_context_assembly.py` |
| Custom ontology + categories (SOCC) | `sophiagraph/tests/test_ontology_and_categories.py`, `sophiagraph/tests/test_ontology_examples.py` | `openminion/tests/memory/test_sophiagraph_ontology_binding.py` |
| Governance + observability hooks (SGGOV) | `sophiagraph/tests/test_governance_observability.py` | `openminion/tests/memory/test_sophiagraph_governance_and_lifecycle.py` |
| Background lifecycle engine (SLCE) | `sophiagraph/tests/test_lifecycle_policy.py`, `sophiagraph/tests/test_lifecycle_policy_storage.py` | `openminion/tests/memory/test_sophiagraph_governance_and_lifecycle.py` |
| Local sync + freshness replay | `sophiagraph/tests/test_local_sync_and_freshness.py` | n/a |
| Human note/import/source management | `sophiagraph/tests/test_human_management.py` | n/a |
| Graph algorithms (SGGA) | `sophiagraph/tests/test_obsidian_links_and_graph.py` | n/a |
| Memory blocks v1 (SMBL) | `sophiagraph/tests/test_memory_block_*.py` | covered by submissions tests |
| Embedding hooks | `sophiagraph/tests/test_embedding_hooks.py`, `sophiagraph/tests/test_vector_conformance.py` | n/a |
| Entity / fact / contradiction (SEFT) | `sophiagraph/tests/test_entity_fact_temporal.py` | `openminion/tests/memory/test_entity_episode_submissions.py` |
| Episodic + procedural memory (SEPM) | `sophiagraph/tests/test_episodic_procedural.py` | `openminion/tests/memory/test_entity_episode_submissions.py` |
| Portability bundle hardening | `sophiagraph/tests/test_portability_bundle_hardening.py` | covered by submissions tests |
| Changefeed | `sophiagraph/tests/test_changefeed.py` | n/a |
| **Cross-lane certification suite (SGSOCT)** | `sophiagraph/tests/test_certification_suite.py` | `openminion/tests/memory/test_sophiagraph_certification.py` |

## Run-the-suite commands

```bash
cd sophiagraph
make check
python3.11 scripts/release_check.py
```

```bash
cd openminion
PYTHONPATH=src:../sophiagraph/src .venv/bin/python3.11 -m pytest -q tests -k 'sophiagraph'
.venv/bin/python3.11 -m ruff check .
make lint
```

## Anti-LLM substrate boundary

Every row in the matrix exercises a typed structural surface. No row
generates or evaluates freeform model output. The OpenMinion-side
tests carry an AST-based regression check that the test file imports
only public ``sophiagraph``, ``sophiagraph.audit``, and
``sophiagraph.models`` paths — never the private storage or audit
submodules.
