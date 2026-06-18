# Sophiagraph Package Docs

This package-local docs directory is reserved for standalone `sophiagraph`
documentation and public release references.

Package-local reference docs:

- [`reference/certification-readiness-matrix.md`](reference/certification-readiness-matrix.md)
  records the current standalone and integration proof targets for the public
  package surface.
- [`reference/standalone-claim-alignment.md`](reference/standalone-claim-alignment.md)
  maps public standalone claims to the concrete package surfaces and proof that
  ship today.
- [`reference/retrieval-boundary.md`](reference/retrieval-boundary.md) records
  the canonical package-vs-host retrieval ownership split.
- [`reference/vector-conformance.md`](reference/vector-conformance.md) records
  the package-owned vector metric and conformance harness expectations.
- [`reference/human-management.md`](reference/human-management.md) records the
  package-owned human note/import/source management surface.
- [`reference/workspace-mode.md`](reference/workspace-mode.md) records the
  package-owned persistent local workspace and explicit local import-bridge
  surface.
- [`reference/ui-contracts.md`](reference/ui-contracts.md) records the
  package-owned `sophiagraph.ui` boundary for future visual/runtime surfaces.

Package-local code/docs boundaries:

1. `README.md` is the public package contract and install surface.
2. [`../API_COMPATIBILITY.md`](../API_COMPATIBILITY.md) records the supported
   public import roots and top-level export policy.
3. [`../src/sophiagraph/README.md`](../src/sophiagraph/README.md) explains the
   source-tree owner map and public-vs-repo-local boundary.
4. [`../RELEASING.md`](../RELEASING.md) records the package-local release and
   PyPI publish flow.
5. `scripts/release_check.py` is the canonical package release smoke entrypoint.

Repository-local but not package API:

1. Host-framework orchestration, admin UI, schedulers, and webhook delivery are
   owned outside the standalone package.
2. Broader roadmap and implementation-planning material lives outside this
   package-local public docs surface.

The public package surface now includes not only durable-memory/query/storage
substrate APIs but also a package-owned human-management layer for note CRUD,
import dry-runs, source/freshness inspection, a persistent local workspace
posture, and a deterministic local workbench packet/HTML preview.
