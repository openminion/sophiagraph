# SophiaGraph Package Docs

Status: semantic alpha

This directory holds the public package documentation for standalone
`sophiagraph`.

## Start Here

| If you want to... | Read |
| --- | --- |
| Install and smoke-test the package | [`getting-started.md`](getting-started.md) |
| Try runnable examples | [`examples.md`](examples.md) |
| Understand storage and retrieval backends | [`storage-retrieval-backends.md`](storage-retrieval-backends.md) and [`backend-compatibility-matrix.md`](backend-compatibility-matrix.md) |
| Understand projections, reconciliation, and graph/vector delivery | [`durable-projections.md`](durable-projections.md) |
| Use the local workbench | [`ui-workbench.md`](ui-workbench.md) and [`ui-contracts.md`](ui-contracts.md) |
| Check public claim/proof boundaries | [`standalone-claim-alignment.md`](standalone-claim-alignment.md) and [`certification-readiness-matrix.md`](certification-readiness-matrix.md) |

## Topic Map

- Runtime readiness: [`production-foundations.md`](production-foundations.md),
  [`migration-and-upgrade.md`](migration-and-upgrade.md), and
  [`api-stability.md`](api-stability.md).
- Retrieval and graph behavior: [`retrieval-boundary.md`](retrieval-boundary.md),
  [`vector-conformance.md`](vector-conformance.md), and
  [`benchmark-reports.md`](benchmark-reports.md).
- Human/local workflows: [`human-management.md`](human-management.md) and
  [`workspace-mode.md`](workspace-mode.md).
- Contributor workflow: [`engineering-patterns.md`](engineering-patterns.md),
  [`code-quality-enforcement.md`](code-quality-enforcement.md),
  [`cleanup-workflow.md`](cleanup-workflow.md),
  [`testing-and-validation.md`](testing-and-validation.md), and
  [`ci-and-release-automation.md`](ci-and-release-automation.md).

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
