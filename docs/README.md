# Sophiagraph Package Docs

Status: semantic alpha

This directory holds the public package documentation for standalone
`sophiagraph`.

## Package-local references

- [`getting-started.md`](getting-started.md) gives the
  package-local bootstrap and execution summary for contributors and automation.
- [`engineering-patterns.md`](engineering-patterns.md)
  summarizes the package-local engineering and boundary rules for contributors.
- [`code-quality-enforcement.md`](code-quality-enforcement.md)
  summarizes the active public quality gates and validation posture.
- [`testing-and-validation.md`](testing-and-validation.md)
  records the package-local install, smoke, test, lint, and release-check
  flow.
- [`ci-and-release-automation.md`](ci-and-release-automation.md)
  records the GitHub Actions quality and release-publishing workflow.
- [`examples.md`](examples.md) maps runnable public examples to the package
  surfaces they exercise.
- [`backend-compatibility-matrix.md`](backend-compatibility-matrix.md)
  records backend adapter support and optional dependency boundaries.
- [`production-foundations.md`](production-foundations.md) records dependency
  compatibility, Qdrant, ingestion, telemetry, encryption, deployment,
  materialized-view, collaboration, and scale-certification boundaries.
- [`storage-retrieval-backends.md`](storage-retrieval-backends.md)
  records store capability reports, default memory/SQLite backend parity,
  portability posture, and vector lifecycle boundaries.
- [`api-stability.md`](api-stability.md) summarizes public import stability,
  internal boundaries, and new-export checklist.
- [`migration-and-upgrade.md`](migration-and-upgrade.md) records package-local
  upgrade, rollback, and generated-artifact guidance.
- [`benchmark-reports.md`](benchmark-reports.md) explains the deterministic
  benchmark/conformance scorecard and report-publishing shape.
- [`ui-workbench.md`](ui-workbench.md) records the local GraphFakos-backed
  workbench and artifact-export workflow.
- [`standalone-claim-alignment.md`](standalone-claim-alignment.md)
  keeps public package claims aligned with the surfaces that ship today.
- [`certification-readiness-matrix.md`](certification-readiness-matrix.md)
  maps each public capability area to its current standalone and OpenMinion
  proof.
- [`retrieval-boundary.md`](retrieval-boundary.md) records
  the package-owned retrieval and navigation boundary.
- [`vector-conformance.md`](vector-conformance.md) records
  the vector metric registry and backend-neutral conformance harness.
- [`human-management.md`](human-management.md) records the
  local note, import, and source-management surface.
- [`workspace-mode.md`](workspace-mode.md) records the
  package-owned persistent local workspace and live file-primary sync contract.
- [`ui-contracts.md`](ui-contracts.md) records the typed
  `sophiagraph.ui` boundary for deterministic local workbench screens.

## Package-local code/docs boundaries

1. `README.md` is the public package contract and install surface.
2. `API_COMPATIBILITY.md` records the supported public import roots and
   top-level export policy.
3. The Source Tree Owner Map reference explains the source-tree owner map and
   public-vs-repo-local boundary.
4. `CHANGELOG.md` records package-facing release notes.
5. `CODE_QUALITY.md` summarizes the public contributor code-quality rules.
6. `RELEASING.md` records the package-local release and PyPI publish flow.
7. `scripts/release_check.py` is the canonical package release smoke entrypoint.
8. `.github/workflows/quality.yml` and `.github/workflows/release.yml` mirror
   the local Makefile gates for public PR and release automation.

## Repository-local but not package API

1. Hosted orchestration, schedulers, transport delivery, and browser-serving
   runtime behavior are owned outside the standalone package.
2. Package planning and execution materials live outside this public package
   docs directory and are not part of the standalone package API.

## Public package stance

The current public package contract is a local-first memory and knowledge-graph
substrate: typed records, relations, retrieval, navigation, governance,
freshness, storage capability reports, portability, human note/import
management, local workspaces, file-primary live sync, and deterministic
workbench packets/HTML previews.
