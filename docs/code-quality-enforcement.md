# Sophiagraph Code Quality Enforcement

Status: active
Last updated: 2026-06-20

Purpose: summarize the public contributor view of the active quality gates for
`sophiagraph`.

## What contributors should expect

Sophiagraph enforces code quality through three layers:

1. package-level ownership and boundary rules,
2. automated lint, tests, and release-check validation,
3. focused public-surface discipline when docs or exports change.

## Required local validation

For normal contribution work, run:

```bash
make lint
make test
```

For broader release proof, also run:

```bash
make release-check
```

## What the gates protect

The active checks are designed to catch drift in areas such as:

1. public-surface export regressions,
2. portability and snapshot boundary drift,
3. storage and backend conformance regressions,
4. docs-to-code contract mismatches,
5. accidental host-framework coupling.

## Public validation expectations

1. Keep changes focused and reviewable.
2. Include exact validation commands and results in the PR description.
3. Do not treat every deep import path as stable API.
4. Do not mix unrelated cleanup into a feature PR.

## See also

1. [`engineering-patterns.md`](engineering-patterns.md)
2. [`getting-started.md`](getting-started.md)
3. [`testing-and-validation.md`](testing-and-validation.md)
