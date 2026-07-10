# Releasing `sophiagraph`

Status: `active`
Scope: package-local release contract for the standalone `sophiagraph` distribution

`sophiagraph` is published under Apache-2.0. This document keeps the
package-local release path explicit so publishing does not depend on host
framework or monorepo context.

## Release Contract

A publishable release must satisfy all of the following:

1. `pyproject.toml` and `src/sophiagraph/__init__.py` agree on the version.
2. `LICENSE` is present and included in built artifacts.
3. `README.md` describes install, quickstart, smoke, name meaning, and import-boundary expectations for external consumers.
4. `API_COMPATIBILITY.md` names the stable import roots and deprecation policy.
5. `docs/` remains the canonical package-local docs root.
6. `docs/source-tree-owner-map.md` continues to document the
   source-tree owner map.
7. `sophiagraph.ui` remains documented as a typed boundary contract.
8. Package tests pass from the package root.
9. Both wheel and sdist build successfully.
10. A clean install smoke passes from a fresh virtualenv using the built wheel.
11. The package still has no imports from host frameworks such as OpenMinion.
12. GitHub Actions release automation, when used, completes the same local
    validation sequence before publishing.

## Version Bump

Update both locations together:

- `pyproject.toml`
- `src/sophiagraph/__init__.py`

If the release changes the external consumer contract, also update:

- `README.md`
- `API_COMPATIBILITY.md`
- `docs/README.md`
- `docs/`
- `docs/source-tree-owner-map.md`

## Build and Validation

Preferred deterministic release check:

```bash
python3.11 scripts/release_check.py
```

The script runs package pytest, wheel+sdist build, `twine check`, and a
fresh-wheel smoke automatically.

Manual equivalent:

```bash
rm -rf build dist src/*.egg-info
python3.11 -m pytest -q
python3.11 -m build
python3.11 -m twine check dist/*
```

Fresh-install smoke:

```bash
TMP_VENV="$(mktemp -d)/sophiagraph-venv"
python3.11 -m venv "$TMP_VENV"
"$TMP_VENV/bin/pip" install dist/sophiagraph-*.whl
"$TMP_VENV/bin/sophiagraph-smoke" --root /tmp/sophiagraph-release-smoke --seed --json
```

Expected smoke result:

- JSON output with `record_count >= 1`
- database path ending in `sophiagraph.sqlite3`

## Publish Sequence

Preferred release path uses GitHub Actions trusted publishing:

1. Prepare and validate a release-candidate branch such as
   `release/sophiagraph-0.0.3rc1`.
2. Push an RC tag such as `v0.0.3rc1`; RC tag pushes publish to TestPyPI only.
3. Install and smoke-test the RC artifact from TestPyPI.
4. Prepare and validate the final branch such as `release/sophiagraph-0.0.3`.
5. Dispatch the `Release` workflow from the final branch with
   `target=testpypi`; final TestPyPI uses the same version that will go to
   production.
6. Install and smoke-test the final artifact from TestPyPI.
7. Push the final non-RC tag such as `v0.0.3`; final tag pushes publish to
   production PyPI.
8. Create the GitHub Release with the bare version title, for example `0.0.3`.
9. Open and merge the release backfill PR, then delete temporary release
   branches after the tag, PyPI artifacts, GitHub Release, and PR are complete.

Manual fallback sequence once validation is green:

```bash
python3.11 -m build
python3.11 -m twine check dist/*
python3.11 -m twine upload dist/*
```

TestPyPI dry run:

```bash
rm -rf build dist src/*.egg-info
python3.11 scripts/release_check.py
python3.11 -m twine upload --repository testpypi dist/*
python3.11 -m venv /tmp/sophiagraph-testpypi-venv
/tmp/sophiagraph-testpypi-venv/bin/pip install \
  --index-url https://test.pypi.org/simple/ \
  --extra-index-url https://pypi.org/simple/ \
  sophiagraph==<version>
/tmp/sophiagraph-testpypi-venv/bin/sophiagraph-smoke \
  --root /tmp/sophiagraph-testpypi-smoke --seed --json
```

Production PyPI upload:

```bash
rm -rf build dist src/*.egg-info
python3.11 scripts/release_check.py
python3.11 -m twine upload dist/*
```

Use PyPI API tokens through `TWINE_USERNAME=__token__` and
`TWINE_PASSWORD=...` or a local `.pypirc`; do not commit credentials. After a
production upload, the project name `sophiagraph` is owned by the publishing
PyPI account/organization for future releases.

## GitHub Actions Trusted Publishing

The release workflow expects PyPI trusted publishing to be configured for this
repository:

- TestPyPI environment: `testpypi`
- PyPI environment: `pypi`
- workflow file: `.github/workflows/release.yml`

The workflow builds artifacts, runs hooks/check/release smoke, uploads `dist/*`
as a GitHub artifact, then publishes through `pypa/gh-action-pypi-publish`.
No PyPI token should be committed to source control.
RC tags publish only to TestPyPI; final non-RC tags publish to production PyPI.
Final TestPyPI verification should be run by workflow dispatch from the final
release branch before the production tag is pushed.

Local release validation uses the published `graphfakos` dependency by
default. To explicitly test against a neighboring GraphFakos checkout during
integration work, set `USE_LOCAL_GRAPHFAKOS=1` for `make check` or
`SOPHIAGRAPH_USE_LOCAL_GRAPHFAKOS=1` for `scripts/release_check.py`. Do not use
that opt-in mode as final PyPI release proof.

## Notes

1. This package intentionally omits repository/homepage metadata until the canonical public release URLs are locked.
2. `sophiagraph` may be published independently; host frameworks consume it as a durable wisdom graph substrate.
3. Generated caches and `*.egg-info` directories are build artifacts and should not be kept as source-of-truth package content.
4. For fast local verification, `python3.11 scripts/release_check.py --skip-twine` is acceptable when `twine` is not available, but full release sign-off should run the default command.
5. Release workflow behavior is documented in `docs/ci-and-release-automation.md`.
