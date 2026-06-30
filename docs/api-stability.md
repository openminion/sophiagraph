# API Stability

Status: semantic alpha

SophiaGraph is still semantic alpha, but the public surface is intentionally
small and documented. This page summarizes how consumers should read the API
contract.

| Surface | Stability | Consumer guidance |
| --- | --- | --- |
| Top-level `sophiagraph` exports | supported alpha | Preferred import path for common records, stores, query DTOs, and helpers |
| Documented subpackage roots in `API_COMPATIBILITY.md` | supported alpha | Safe for advanced consumers that need owner-specific APIs |
| CLI commands in `python -m sophiagraph` and console scripts | supported alpha | Intended for smoke, workspace, benchmark, and preview workflows |
| `docs/` public references | supported alpha | Source of truth for package-local behavior and operations |
| Underscore-prefixed names | internal | Do not import |
| Test fixtures and `tests/` helpers | internal | Do not import |
| `workspace-tmp/`, caches, `dist/`, build outputs | generated | Do not depend on |

## Compatibility rules

1. Public DTOs should remain explicit and typed.
2. Breaking public changes should update `API_COMPATIBILITY.md`,
   `CHANGELOG.md`, and the relevant docs page.
3. Deprecated public names should receive a documented migration path before
   removal whenever practical.
4. Runtime-owned prose inference, Text2Query generation, and silent graph-edge
   creation are not part of the public API.

## Stability checklist for new public exports

- Add the export to the owning module `__all__`.
- Add or update focused tests.
- Update `API_COMPATIBILITY.md` if the name becomes an external contract.
- Add a docs note when the feature affects install, release, or migration
  behavior.
