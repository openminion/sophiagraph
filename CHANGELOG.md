# Sophiagraph Changelog

Status: active
Last updated: 2026-08-08

This file tracks package-facing release notes for `sophiagraph`.

## 0.0.7 - 2026-08-08

### Added

- Added the public `sophiagraph.access` delegated-memory authorization and
  gateway contracts.
- Added public namespace-selector intersection for host adapters that must
  narrow grant projections before authorization.
- Added alpha knowledge-explorer cursor pagination with deterministic
  `(updated_at, record_id)` ordering across in-memory and SQLite stores.
- Added deterministic typed pattern-query parity across the in-memory, Kuzu,
  and Neo4j graph adapters without exposing free-form backend query text.
- Added explicit performance-budget assessments for operator-run scale
  certification.
- Added public `sophiagraph.models.SCOPE_PATTERN`; the underscore-prefixed
  spelling remains a temporary compatibility alias for existing 0.x clients.

## 0.0.4 - 2026-07-18

### Added

- Added idempotent workbench action execution with typed request context,
  result, and journal contracts for candidate approval/rejection/promotion,
  file-primary note capture, host-required restore posture, and preview-only
  repair/publish/selection actions.
- Added memory and SQLite action-journal persistence with scoped lookup,
  retention pruning, audit references, replay, stale-precondition, conflict,
  recovery-required, and payload-impersonation guards.
- Added bounded stdlib HTTP routes for core knowledge operations plus
  workbench capabilities, preview, execute, and status operations over the
  same service-core contracts used by MCP.
- Added server-owned principal/scope binding, local loopback posture,
  bearer-token auth support, origin/body/quota guards, and canonical HTTP
  status mappings for workbench action outcomes.
- Added one-shot projection and journal operation commands for scheduler-owned
  execution without hidden package threads.
- Added GraphFakos local-preview action integration so live `sophiagraph-ui`
  sessions can submit provider-neutral capture/action payloads through the
  package executor while static exports remain read-only.
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
