# Sophiagraph Testing And Validation

Status: active
Last updated: 2026-06-20

Purpose: give package users and contributors one package-local reference for
the validation commands that prove `sophiagraph` installs and runs correctly.

## Install baseline

Sophiagraph currently expects:

1. Python 3.11 or newer
2. a recent `pip` that supports editable installs

Recommended local setup from the package root:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
make dev-install
```

## First-user smoke flow

From the package root:

```bash
sophiagraph-smoke --root /tmp/sophiagraph-smoke --seed --json
```

Expected outcome:

1. the command exits successfully,
2. it returns JSON,
3. the seeded store contains at least one record.

## Package validation gates

Run from the package root:

```bash
make lint
make test
```

## Focused regression tests

The public standalone surface is protected by targeted tests under `tests/`.

Example focused run:

```bash
python3.11 -m pytest -q \
  tests/test_package_layout.py \
  tests/test_release_check.py
```

## Release smoke

For package-release validation, use:

```bash
make release-check
```

That command runs the package release smoke that builds artifacts, checks the
wheel, and verifies the documented standalone install path.

