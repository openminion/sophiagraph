# Sophiagraph Changelog

Status: active
Last updated: 2026-06-20

This file tracks package-facing release notes for `sophiagraph`.

## Unreleased

### Added

- Added durable graph/vector projection targets, checkpoints, fenced leases,
  bounded retry and dead-letter state, backend watermarks, deterministic
  reconciliation, and explicitly authorized repair plans.
- Added privacy-bounded embedding change events and provider-neutral fake,
  Kuzu, Neo4j, and Qdrant projection conformance coverage.
- Added a lazily loaded Qdrant stored-vector backend with caller-supplied
  embeddings, namespace/payload filters, deletion, and health checks.
- Added dependency/API compatibility reporting, capability-aware backend
  planning, resumable bulk ingestion, low-cardinality telemetry, caller-owned
  authenticated-encryption contracts, enforceable server deployment profiles,
  materialized saved views, conflict-preserving three-way merges, and
  operator-run scale benchmark profiles.

- Added package-local public contributor references for testing, engineering
  patterns, agent bootstrap, and code-quality enforcement.
- Added public CI/release automation docs, example-pack docs, backend
  compatibility matrix, API stability guide, migration guide, benchmark report
  guide, and UI workbench guide.
- Added GitHub Actions release workflow support for TestPyPI/PyPI trusted
  publishing.

### Changed

- Polished the public package docs surface so external contributors can follow
  package-local references without internal workspace context.

### Notes

- The project remains in semantic alpha. Until the next tagged release,
  changes may land ahead of a published semantic-versioned changelog entry.
