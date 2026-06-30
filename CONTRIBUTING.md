# Contributing to Sophiagraph

Thanks for contributing.

## Before coding

Read these docs before coding:

1. [README.md](./README.md)
2. [API_COMPATIBILITY.md](./API_COMPATIBILITY.md)
3. [docs/README.md](./docs/README.md)
4. [docs/source-tree-owner-map.md](./docs/source-tree-owner-map.md)
5. [docs/getting-started.md](./docs/getting-started.md)
6. [docs/engineering-patterns.md](./docs/engineering-patterns.md)
7. [docs/code-quality-enforcement.md](./docs/code-quality-enforcement.md)
8. [docs/testing-and-validation.md](./docs/testing-and-validation.md)
9. [RELEASING.md](./RELEASING.md) when the work affects packaging or release
   behavior

Treat the package README and API compatibility policy as the stable public
contract, and use the docs index plus owner map to understand which surfaces
the package does and does not own.

## Quick start

1. Fork and create a branch.
2. Make focused changes.
3. Add or update tests.
4. Open a PR with a clear summary.

## Repository layout

```text
sophiagraph/
├── src/sophiagraph/            # public package shipped on PyPI
│   ├── models/  query/  storage/  adapters/
│   ├── audit/  contracts/  trust/  temporal/
│   ├── graph_backends/  portability/  ui/
│   ├── workspace.py  workspace_sync.py
│   ├── workspace_notes.py  workspace_common.py
│   ├── human.py  sync.py  freshness.py
│   └── okf.py
├── tests/                      # package tests and fixture-backed coverage
│   └── fixtures/okf/           # bundle and interoperability fixtures
├── docs/                       # public package-local docs
├── pyproject.toml
└── scripts/release_check.py    # package release smoke
```

The public wheel is everything under `src/sophiagraph/`. The repository also
ships package docs, tests, and release tooling, but those do not expand the
runtime API beyond what is documented in `README.md`,
`API_COMPATIBILITY.md`, and `docs/`.

## Setup

Requires Python 3.11+.

```bash
# 1. Clone and enter the repo
git clone https://github.com/openminion/sophiagraph.git sophiagraph
cd sophiagraph

# 2. Create and activate a virtualenv
python3.11 -m venv .venv
source .venv/bin/activate

# 3. Install in editable mode with dev extras
make dev-install

# 4. Install local hooks, including commit-message enforcement
make hooks-install
```

## Running tests

```bash
# Full package test suite
make test

# Full local quality gate
make check

# Release/install smoke
make release-check
```

If you need a narrower loop while iterating, run `python3.11 -m pytest -q
tests/<target>` inside the activated virtualenv.

## Running lint and formatting

```bash
# Lint only
make lint

# Check formatting without rewriting files
make format-check

# Apply formatting and autofixes
make fix
```

## Development basics

1. Follow the existing typed, deterministic package style.
2. Keep PRs small and reviewable.
3. Include validation commands and results in the PR description.
4. Prefer a short GitHub-native PR title plus a flat bullet summary of what the
   commit set landed.
5. Keep PR descriptions easy to scan and easy to copy:
   1. short title
   2. bullet summary of changes
   3. validation commands/results
6. Prefer typed facts, policies, and structural outputs over prose-owned or
   implicit interpretation.
7. Do not introduce runtime-owned semantic inference, automatic relation
   promotion, or provider SDK behavior into the core package unless the public
   contract already owns it.
8. Add or update tests for any behavior change. Tests live under `tests/`.
9. Keep package docs public-facing and portable. Do not add local-machine
   paths, private environment assumptions, or repo-planning language to the
   public package docs.
10. Do not bundle unrelated refactors into the same PR.

Commit message guidance:

1. Use commit messages in the form `<type>: <summary>` or
   `<type>(<scope>): <summary>`.
2. Approved current types are `feat`, `fix`, `docs`, `refactor`, `test`,
   `chore`, `style`, and `build`.
3. In this package, scope is optional but encouraged when it improves owner
   clarity, for example `ui`, `workspace`, `storage`, `query`, `docs`, or
   `release`.
4. Keep the summary specific to the landed change and avoid vague messages like
   `update`.
5. Prefer the most specific truthful type; do not use `chore` when `docs`,
   `test`, `refactor`, or `build` is more accurate.
6. Do not use local shorthand or planning labels as normal commit types.

The same policy runs locally through `make hooks-install` and again in GitHub
Actions on pull requests plus `dev`/`main` pushes.

Preferred PR shape:

1. `Title`
   - short and literal, for example `Add typed privacy policy substrate`
2. `Description`
   - `- add ...`
   - `- align ...`
   - `- polish ...`
3. `Validation`
   - `- <command>`
   - `- <command>`

## Submitting a pull request

1. Fork and create a branch from `main`.
2. Make your change; add or update tests; run the relevant local validation.
3. Open a PR with a clear summary. In the description, include:
   - what changed and why,
   - the exact commands you ran for validation,
   - whether the change affects the public standalone package surface,
     docs-only packaging, or repo-local test/release tooling.
4. Keep PRs small and reviewable.
5. Do not bundle unrelated refactors into the same PR.

## Legal basics (plain English)

1. You keep ownership of your contributions.
2. By submitting a contribution, you license it under the project license
   (Apache-2.0).
3. Apache-2.0 includes a patent license for your contribution, with the
   standard patent-termination condition in the license text.
4. Only submit code or content you have the right to contribute.
5. Do not add third-party code or assets unless their license is compatible
   and clearly documented.
6. Project names and logos are not granted for endorsement use.
7. `sophiagraph` is provided on an "as is" basis under the project license;
   there are no guarantees about performance, reliability, availability, or
   fitness for a particular use case.
8. If you configure third-party services or paid infrastructure while
   developing or testing, you are responsible for any resulting charges.
9. See [LICENSE](./LICENSE) for the full legal terms, disclaimers, and
   limitations of liability.

## Security

If you find a security issue, do not open a public issue with exploit details.
Use the project security reporting process.

## Code of conduct

By participating, you agree to follow [CODE_OF_CONDUCT.md](./CODE_OF_CONDUCT.md).
