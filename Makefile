REPO_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
VENV := $(REPO_ROOT)/.venv
DEV_STAMP := $(VENV)/.baseline-tools-installed
PYTHON := $(VENV)/bin/python3.11
PIP := $(PYTHON) -m pip
PYTEST := $(PYTHON) -m pytest
RUFF := $(PYTHON) -m ruff

.PHONY: help venv dev-install fix format format-check lint test check release-check

help:
	@printf '%s\n' \
		'Targets:' \
		'  make dev-install   Create/update .venv and install sophiagraph with dev extras' \
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
	PYTHONPATH="$(REPO_ROOT)/src" $(PYTEST) -q "$(REPO_ROOT)/tests"

check: format-check lint test

release-check: $(DEV_STAMP)
	cd "$(REPO_ROOT)" && $(PYTHON) scripts/release_check.py
