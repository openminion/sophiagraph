# Sophiagraph Package Docs

This package-local docs directory is reserved for standalone `sophiagraph`
documentation and public release references.

Package-local reusable docs:

- `docs/certification-readiness-matrix.md` records the current standalone and
  integration proof targets for the public package surface.
- `docs/vector-conformance.md` records the package-owned vector metric and
  conformance harness expectations.

Package-local code/docs boundaries:

1. `README.md` is the public package contract and install surface.
2. `API_COMPATIBILITY.md` records the supported public import roots and
   top-level export policy.
3. `RELEASING.md` records the package-local release and PyPI publish flow.
4. `scripts/release_check.py` is the canonical package release smoke entrypoint.

Repository-local but not wheel-shipped:

1. Host-framework orchestration, admin UI, schedulers, and webhook delivery are
   owned outside the standalone package.
2. Root-repo roadmap, tracker, and design docs remain under the workspace
   `docs/` tree rather than this package-local docs directory.
