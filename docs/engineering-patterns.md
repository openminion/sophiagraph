# Sophiagraph Engineering Patterns

Status: active
Last updated: 2026-06-20

Purpose: give public contributors one package-local summary of the engineering
patterns that shape `sophiagraph` changes.

## Core rule

Prefer typed, deterministic, package-owned durable-memory contracts over
implicit behavior or host-specific shortcuts.

## Main package split

Use this source-tree ladder when deciding where code belongs:

1. `models/` owns durable-memory DTOs and typed domain records.
2. `query/` owns retrieval, navigation, and explorer request/result surfaces.
3. `storage/` owns in-memory, SQLite, and backend adapter behavior.
4. `portability/` owns snapshot/bundle codecs.
5. `graph_backends/`, `audit/`, `trust/`, and `temporal/` own their named
   boundaries and should stay explicit.

## Shared-owner rules

1. Shared constants should live in their canonical owner rather than being
   repeated inline.
2. Public roots should stay intentional; not every internal import path is a
   stable promise.
3. Keep compatibility helpers thin and explicit.

## Runtime-boundary rules

1. Keep outputs deterministic and typed.
2. Do not add runtime-owned semantic inference to the package core.
3. Do not auto-promote links, community matches, or structural hints into
   graph edges without explicit contract ownership.
4. Keep provider SDK behavior outside the core package unless the public
   contract explicitly owns it.

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
