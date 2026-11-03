# Sophiagraph Engineering Patterns

Status: active
Last updated: 2026-11-01

Purpose: give public contributors one package-local summary of the engineering
patterns that shape `sophiagraph` changes.

## Core rule

Prefer typed, deterministic, package-owned durable-memory contracts over
implicit behavior or host-specific shortcuts.

## Main package split

Use this source-tree ladder when deciding where code belongs:

1. `models/` owns durable-memory, lifecycle, privacy, projection, artifact, and
   workbench-action DTOs.
2. `query/` owns retrieval, graph, structural, temporal, replay, block, and
   artifact-backed request/result surfaces.
3. `storage/` owns in-memory and SQLite persistence, lifecycle, changefeed,
   portability, projection, backup, lease, compaction, and migration behavior.
4. `contracts/`, `audit/`, `trust/`, `privacy*`, and `temporal/` own typed
   policy, provenance, error, omission, and governance facts.
5. `workspace*`, `vault*`, `okf*`, `human*`, `workbench*`, and `operations*`
   own explicit human-facing and operational workflows over the canonical
   storage and query contracts.
6. `server/` owns optional process and transport boundaries. `ui/`, `views*`,
   and `projections*` own visual adaptation, saved views, and derived-index
   delivery without becoming new durable-memory stores.
7. `graph_backends/` and `vector_backends/` own optional provider contracts and
   concrete adapters; the package core depends on protocols, not one backend.

## Shared-owner rules

1. Shared constants should live in their canonical owner rather than being
   repeated inline.
2. Public roots should stay intentional; not every internal import path is a
   stable promise.
3. Keep compatibility helpers thin and explicit.
4. Split DTOs, pure evaluation, persistence, transport, and rendering when a
   façade begins to own more than one of those concerns.

## Runtime-boundary rules

1. Keep outputs deterministic and typed.
2. Do not add runtime-owned semantic inference to the package core.
3. Do not auto-promote links, community matches, or structural hints into
   graph edges without explicit contract ownership.
4. Keep provider SDK behavior outside the core package unless the public
   contract explicitly owns it.

## Durable mutation rules

1. Mutations require an explicit owner, typed request, authorization context,
   and durable outcome. Query, view, preview, inspection, and projection-diff
   helpers remain read-only unless their contract says otherwise.
2. Workbench actions preserve idempotency keys, execution context, journal
   state, reason codes, and host-required outcomes. A preview is not an applied
   mutation, and a dispatched action is not durable proof.
3. Projection reconciliation may describe drift without authority. Repair
   application must be explicit, bounded, and followed by readback.
4. Storage changes preserve transaction, changefeed, lifecycle, backup,
   migration, and cross-backend behavior where those contracts apply.

## Evidence, privacy, and provenance

1. Preserve namespace, provenance, evidence, citation, consent, retention, and
   omission facts across storage, query, portability, UI, and service
   boundaries.
2. Redaction and privacy filtering must return typed omissions; do not silently
   turn hidden records into claims that no record exists.
3. Keep caller-supplied embeddings, provider responses, and derived indexes
   attributable to their namespace, model/backend, version, and freshness
   posture.
4. Treat synthetic backends, demos, and deterministic fixtures as contract
   proof only. Live backend, persistence, migration, and service claims require
   the corresponding named acceptance tier.

## Transport and UI composition

HTTP, stdio, MCP, CLI, and GraphFakos adapters translate package-owned typed
facts without inventing memory semantics or reshaping errors inconsistently.
Sophiagraph owns its adapter and package screens; GraphFakos owns shared viewer
shells, browser assets, routes, and reusable interaction behavior.

## Cleanup and refactor rules

1. Preserve ownership clarity over broad rewrites.
2. Keep boundary changes paired with matching tests and docs.
3. Keep public docs portable and package-local.

## Use with

Read this doc together with:

1. [`code-quality-enforcement.md`](code-quality-enforcement.md)
2. [`getting-started.md`](getting-started.md)
3. [`testing-and-validation.md`](testing-and-validation.md)
4. [`source-tree-owner-map.md`](source-tree-owner-map.md)

Apply the [comment and docstring review](../CODE_QUALITY.md#comment-and-docstring-review)
to the final diff, including tests and scripts.
