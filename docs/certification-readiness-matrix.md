# Sophiagraph Standalone + OpenMinion Certification Readiness Matrix

Status: semantic alpha
Scope: public package proof matrix

## Purpose

Single map of the current public SophiaGraph surface, the standalone package
proof for each lane, and the OpenMinion direct-library proof where one exists.

## Scope

The matrix below lists each shipped SophiaGraph capability area, the exact
package test target that proves the standalone surface works, and the exact
OpenMinion proof when the lane has one. Rows with no host-facing surface are
marked `n/a`.

## Non-goals

This matrix does not cover hosted-service behavior, scheduled-worker
behavior, or webhook delivery transport.

## Success criteria

Every row that is not `n/a` points to a passing package-local or OpenMinion
test that exercises public SophiaGraph imports.

## Matrix

| Lane | Standalone proof | OpenMinion direct-library proof |
| --- | --- | --- |
| Vault sync + round-trip | `sophiagraph/tests/test_vault_sync.py` | `openminion/tests/memory/test_sophiagraph_vault_direct_library.py` |
| Temporal context graph convergence | `sophiagraph/tests/test_temporal_convergence.py` | `openminion/tests/memory/test_sophiagraph_temporal_convergence.py` |
| Context assembly + retrieval modes | `sophiagraph/tests/test_context_assembly.py` | `openminion/tests/memory/test_sophiagraph_context_assembly.py` |
| Hybrid retrieval staging + explanations | `sophiagraph/tests/test_hybrid_retrieval.py` | `openminion/tests/memory/test_sophiagraph_context_assembly.py` |
| Custom ontology + categories | `sophiagraph/tests/test_ontology_and_categories.py`, `sophiagraph/tests/test_ontology_examples.py` | `openminion/tests/memory/test_sophiagraph_ontology_binding.py` |
| Governance + observability hooks | `sophiagraph/tests/test_governance_observability.py` | `openminion/tests/memory/test_sophiagraph_governance_and_lifecycle.py` |
| Background lifecycle engine | `sophiagraph/tests/test_lifecycle_policy.py`, `sophiagraph/tests/test_lifecycle_policy_storage.py` | `openminion/tests/memory/test_sophiagraph_governance_and_lifecycle.py` |
| Local sync + freshness replay | `sophiagraph/tests/test_local_sync_and_freshness.py` | n/a |
| Human note/import/source management | `sophiagraph/tests/test_human_management.py` | n/a |
| Graph algorithms | `sophiagraph/tests/test_obsidian_links_and_graph.py` | n/a |
| Memory blocks v1 | `sophiagraph/tests/test_memory_block_*.py` | covered by submissions tests |
| Embedding hooks | `sophiagraph/tests/test_embedding_hooks.py`, `sophiagraph/tests/test_vector_conformance.py` | n/a |
| Entity / fact / contradiction | `sophiagraph/tests/test_entity_fact_temporal.py` | `openminion/tests/memory/test_entity_episode_submissions.py` |
| Episodic + procedural memory | `sophiagraph/tests/test_episodic_procedural.py` | `openminion/tests/memory/test_entity_episode_submissions.py` |
| Portability bundle hardening | `sophiagraph/tests/test_portability_bundle_hardening.py` | covered by submissions tests |
| Changefeed | `sophiagraph/tests/test_changefeed.py` | n/a |
| **Cross-surface certification suite** | `sophiagraph/tests/test_certification_suite.py` | `openminion/tests/memory/test_sophiagraph_certification.py` |

## Run-the-suite commands

```bash
make check
python3.11 scripts/release_check.py
```

From the `openminion` package root, with SophiaGraph source available on disk:

```bash
PYTHONPATH=src:<sophiagraph-src> .venv/bin/python3.11 -m pytest -q tests -k 'sophiagraph'
.venv/bin/python3.11 -m ruff check .
make lint
```

## Boundary reminder

Every row in the matrix exercises typed structural surfaces only. No row
depends on freeform model output. OpenMinion-side proofs stay on documented
public `sophiagraph` import roots rather than private storage or audit
submodules.
