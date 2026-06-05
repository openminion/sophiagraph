# Sophiagraph Package Docs

This package-local docs directory is reserved for standalone `sophiagraph`
documentation and public release references.

Package-local reference docs:

- `docs/reference/certification-readiness-matrix.md` records the current
  standalone and integration proof targets for the public package surface.
- `docs/reference/vector-conformance.md` records the package-owned vector
  metric and conformance harness expectations.
- `docs/reference/ui-contracts.md` records the package-owned `sophiagraph.ui`
  boundary for future visual/runtime surfaces.

Package-local code/docs boundaries:

1. `README.md` is the public package contract and install surface.
2. `API_COMPATIBILITY.md` records the supported public import roots and
   top-level export policy.
3. `RELEASING.md` records the package-local release and PyPI publish flow.
4. `scripts/release_check.py` is the canonical package release smoke entrypoint.

Repository-local but not package API:

1. Host-framework orchestration, admin UI, schedulers, and webhook delivery are
   owned outside the standalone package.
2. Root-repo roadmap, tracker, and design docs remain under the workspace
   `docs/` tree rather than this package-local docs directory.
