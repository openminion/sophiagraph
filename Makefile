REPO_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
VENV := $(REPO_ROOT)/.venv
DEV_STAMP := $(VENV)/.baseline-tools-installed
PYTHON := $(VENV)/bin/python3.11
PIP := $(PYTHON) -m pip
PRE_COMMIT := $(PYTHON) -m pre_commit
PYTEST := $(PYTHON) -m pytest
RUFF := $(PYTHON) -m ruff
GRAPHFAKOS_SRC_LOCAL := $(abspath $(REPO_ROOT)/graphfakos/src)
GRAPHFAKOS_SRC_SIBLING := $(abspath $(REPO_ROOT)/../graphfakos/src)
TEST_PYTHONPATH := $(REPO_ROOT)/src$(if $(wildcard $(GRAPHFAKOS_SRC_LOCAL)),:$(GRAPHFAKOS_SRC_LOCAL),$(if $(wildcard $(GRAPHFAKOS_SRC_SIBLING)),:$(GRAPHFAKOS_SRC_SIBLING),))

.PHONY: help venv dev-install hooks-install hooks-run fix format format-check lint test check release-check

help:
	@printf '%s\n' \
		'Targets:' \
		'  make dev-install   Create/update .venv and install sophiagraph with dev extras' \
		'  make hooks-install Install pre-commit and commit-msg hooks into .git/hooks' \
		'  make hooks-run     Run pre-commit across the sophiagraph repo' \
		'  make fix           Apply Ruff formatting and autofixes' \
		'  make format        Run Ruff formatter' \
		'  make format-check  Check formatting without changing files' \
		'  make lint          Run Ruff lint' \
		'  make test          Run package pytest suite' \
		'  make check         Run format-check, lint, and test' \
		'  make release-check Run package release smoke'

venv:
	@test -x "$(PYTHON)" || python3.11 -m venv "$(VENV)"

$(DEV_STAMP): pyproject.toml | venv
	$(PIP) install --upgrade pip setuptools wheel
	cd "$(REPO_ROOT)" && $(PIP) install -e ".[dev]"
	@touch "$(DEV_STAMP)"

dev-install: $(DEV_STAMP)

hooks-install: $(DEV_STAMP)
	$(PRE_COMMIT) install --install-hooks --hook-type pre-commit --hook-type commit-msg

hooks-run: $(DEV_STAMP)
	$(PRE_COMMIT) run --all-files

fix: $(DEV_STAMP)
	$(RUFF) format "$(REPO_ROOT)"
	$(RUFF) check --fix "$(REPO_ROOT)"

format: $(DEV_STAMP)
	$(RUFF) format "$(REPO_ROOT)"

format-check: $(DEV_STAMP)
	$(RUFF) format --check "$(REPO_ROOT)"

lint: $(DEV_STAMP)
	$(RUFF) check "$(REPO_ROOT)"

test: $(DEV_STAMP)
	PYTHONPATH="$(TEST_PYTHONPATH)" $(PYTEST) -q "$(REPO_ROOT)/tests"

check: format-check lint test

release-check: $(DEV_STAMP)
	cd "$(REPO_ROOT)" && $(PYTHON) scripts/release_check.py
