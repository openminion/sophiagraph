# Sophiagraph Getting Started

Status: active
Last updated: 2026-06-20

Purpose: give contributors and automation authors a package-local bootstrap
and execution summary for work inside the `sophiagraph` repo.

## Fast bootstrap

```bash
cd sophiagraph
python3.11 -m venv .venv
source .venv/bin/activate
make dev-install
```

## Read first

Before substantial code changes, read:

1. [`engineering-patterns.md`](engineering-patterns.md)
2. [`code-quality-enforcement.md`](code-quality-enforcement.md)
3. [`testing-and-validation.md`](testing-and-validation.md)
4. [`source-tree-owner-map.md`](source-tree-owner-map.md)
5. [`retrieval-boundary.md`](retrieval-boundary.md) when the work touches
   retrieval, navigation, or explorer behavior

## Normal execution loop

1. Pick one focused change.
2. Implement code and docs together when the public surface changes.
3. Add or update tests for the behavior you changed.
4. Run focused validation while iterating.
5. Run `make lint` and `make test` before calling the work ready.
6. Record validation commands in the PR description.

## Pull request shape

Preferred PR shape:

1. short, GitHub-native title,
2. flat bullet summary of what changed,
3. short validation block with exact commands.

## Boundary reminder

1. `README.md` is the package contract and install surface.
2. `API_COMPATIBILITY.md` is the public import/export promise.
3. `docs/` is the package-local public docs layer.
4. `tests/` and `scripts/` are important, but they are not public library API.
