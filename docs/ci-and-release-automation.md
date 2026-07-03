# CI and Release Automation

Status: active

SophiaGraph uses the same public package workflow shape as the sibling
OpenMinion packages: local Makefile gates first, GitHub Actions parity second,
and PyPI publishing only through an explicit release workflow.

## Local parity commands

Run these from the package root:

```bash
make hooks-run
make check
python3.11 scripts/release_check.py
```

For fast pre-release iteration when `twine` is not installed locally:

```bash
python3.11 scripts/release_check.py --skip-twine
```

That is not the final publish gate. A release sign-off should run the default
`scripts/release_check.py` path.

## Pull request and branch CI

`.github/workflows/quality.yml` runs on pull requests, pushes to `main` and
`dev`, and manual dispatch. It validates:

- pre-commit configuration
- pre-commit hooks on the changed range
- pushed commit-message subjects
- `make check`
- release smoke through `scripts/release_check.py --skip-twine`

The release-smoke step builds artifacts and runs a fresh-wheel smoke without
attempting an upload.

## Release workflow

`.github/workflows/release.yml` builds, validates, stores the `dist/*`
artifacts, and publishes through PyPI trusted publishing.

Use TestPyPI first with an RC tag:

```text
Push v<version>rc<N>
```

RC tag pushes publish to TestPyPI only. After the RC artifact is installed and
smoke-tested, prepare the final version branch and publish that exact final
version to TestPyPI by workflow dispatch:

```text
Actions -> Release -> Run workflow -> target=testpypi
```

Use production PyPI only after final-version TestPyPI verification. Push the
final non-RC tag, such as `v0.0.2`, to publish to production PyPI after the
same validation sequence. The GitHub Release is created after production PyPI
publishing succeeds, with a bare version title such as `0.0.2`.

## Credential boundary

The release workflow is designed for PyPI trusted publishing. Do not commit
PyPI tokens, `.pypirc`, local credential files, or workflow secrets into this
repository.
