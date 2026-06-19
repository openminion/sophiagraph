# Sophiagraph Package Docs

Status: semantic alpha

This directory holds the public package documentation for standalone
`sophiagraph`.

## Package-local references

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
4. `RELEASING.md` records the package-local release and PyPI publish flow.
5. `scripts/release_check.py` is the canonical package release smoke entrypoint.

## Repository-local but not package API

1. Hosted orchestration, schedulers, transport delivery, and browser-serving
   runtime behavior are owned outside the standalone package.
2. Workspace-root roadmap, tracker, and implementation-planning docs remain
   repository documentation rather than package API.

## Public package stance

The current public package contract is a local-first memory and knowledge-graph
substrate: typed records, relations, retrieval, navigation, governance,
freshness, portability, human note/import management, local workspaces,
file-primary live sync, and deterministic workbench packets/HTML previews.
