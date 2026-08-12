PYTHON ?= python
SRC ?= src/easy_docker_manager
TESTS ?= tests/unit_tests

RUFF ?= ruff
BLACK ?= black
MYPY ?= mypy
BANDIT ?= bandit
PRE_COMMIT ?= pre-commit
PYTEST ?= $(PYTHON) -m pytest
PIP_AUDIT ?= $(PYTHON) -m pip_audit
BUILD ?= $(PYTHON) -m build
TWINE ?= $(PYTHON) -m twine

.PHONY: audit bandit black black-check check format lint mypy package-build \
	package-check pre-commit ruff ruff-fix security test

ruff:
	$(RUFF) check $(SRC) $(TESTS)

ruff-fix:
	$(RUFF) check --fix $(SRC) $(TESTS)

black:
	$(BLACK) $(SRC) $(TESTS)

black-check:
	$(BLACK) --check $(SRC) $(TESTS)

mypy:
	$(MYPY) $(SRC)

bandit:
	$(BANDIT) -r $(SRC) -c pyproject.toml

audit:
	$(PIP_AUDIT) .

security: bandit audit

test:
	$(PYTEST) $(TESTS)

package-build:
	$(BUILD)

package-check: package-build
	$(TWINE) check dist/*

format: ruff-fix black

lint: ruff mypy bandit

check: black-check lint test

pre-commit:
	$(PRE_COMMIT) run --all-files
