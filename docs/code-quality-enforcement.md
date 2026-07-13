# Sophiagraph Code Quality Enforcement

Status: active
Last updated: 2026-06-20

Purpose: summarize the public contributor view of the active quality gates for
`sophiagraph`.

## What contributors should expect

Sophiagraph enforces code quality through four layers:

1. package-level ownership and boundary rules,
2. automated lint, tests, and release-check validation,
3. structural quality ratchets for source shape and package boundaries,
4. focused public-surface discipline when docs or exports change.

## Required local validation

For normal contribution work, run:

```bash
make check
```

For the structural ratchets alone, run:

```bash
make validate-patterns
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
6. new oversized files/functions, duplicate helpers, broad exceptions, path
   drift, bare type-ignore pragmas, and hidden sibling imports.

## Public validation expectations

1. Keep changes focused and reviewable.
2. Include exact validation commands and results in the PR description.
3. Do not treat every deep import path as stable API.
4. Do not mix unrelated cleanup into a feature PR.

## See also

1. [`engineering-patterns.md`](engineering-patterns.md)
2. [`getting-started.md`](getting-started.md)
3. [`testing-and-validation.md`](testing-and-validation.md)
