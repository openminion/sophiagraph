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
USE_LOCAL_GRAPHFAKOS ?= 0
LOCAL_GRAPHFAKOS_SRC :=
ifneq ($(filter 1 true yes,$(USE_LOCAL_GRAPHFAKOS)),)
ifneq ($(wildcard $(GRAPHFAKOS_SRC_LOCAL)),)
LOCAL_GRAPHFAKOS_SRC := $(GRAPHFAKOS_SRC_LOCAL)
else ifneq ($(wildcard $(GRAPHFAKOS_SRC_SIBLING)),)
LOCAL_GRAPHFAKOS_SRC := $(GRAPHFAKOS_SRC_SIBLING)
endif
endif
TEST_PYTHONPATH := $(REPO_ROOT)/src$(if $(LOCAL_GRAPHFAKOS_SRC),:$(LOCAL_GRAPHFAKOS_SRC),)

.PHONY: help venv dev-install hooks-install hooks-run fix format format-check lint test validate-patterns loc-check method-loc-check helper-duplicates-check path-structure-check filename-underscore-check broad-exception-check type-ignore-check public-surface-check check release-check

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
		'  make validate-patterns Run package structural quality ratchets' \
		'  make check         Run format-check, lint, validate-patterns, and test' \
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

loc-check: $(DEV_STAMP)
	$(PYTHON) "$(REPO_ROOT)/scripts/validate_quality_patterns.py" --check max-file-loc

method-loc-check: $(DEV_STAMP)
	$(PYTHON) "$(REPO_ROOT)/scripts/validate_quality_patterns.py" --check method-loc

helper-duplicates-check: $(DEV_STAMP)
	$(PYTHON) "$(REPO_ROOT)/scripts/validate_quality_patterns.py" --check helper-duplicates

path-structure-check: $(DEV_STAMP)
	$(PYTHON) "$(REPO_ROOT)/scripts/validate_quality_patterns.py" --check path-structure

filename-underscore-check: $(DEV_STAMP)
	$(PYTHON) "$(REPO_ROOT)/scripts/validate_quality_patterns.py" --check filename-underscore

broad-exception-check: $(DEV_STAMP)
	$(PYTHON) "$(REPO_ROOT)/scripts/validate_quality_patterns.py" --check broad-exception

type-ignore-check: $(DEV_STAMP)
	$(PYTHON) "$(REPO_ROOT)/scripts/validate_quality_patterns.py" --check type-ignore

public-surface-check: $(DEV_STAMP)
	$(PYTHON) "$(REPO_ROOT)/scripts/validate_quality_patterns.py" --check public-surface

validate-patterns: loc-check method-loc-check helper-duplicates-check path-structure-check filename-underscore-check broad-exception-check type-ignore-check public-surface-check

check: format-check lint validate-patterns test

release-check: $(DEV_STAMP)
	cd "$(REPO_ROOT)" && $(PYTHON) scripts/release_check.py
