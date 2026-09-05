PYTHON ?= python
SRC ?= src/easy_docker_manager
TESTS ?= tests
UNIT_TESTS ?= tests/unit_tests
INTEGRATION_TESTS ?= tests/integration_tests
REMOTE_INTEGRATION_TEST_SCRIPT ?= tests/integration_tests/remote/run_remote_integration_tests.sh
SMOKE_TESTS ?= tests/smoke_tests

RUFF ?= ruff
BLACK ?= black
MYPY ?= mypy
BANDIT ?= bandit
PRE_COMMIT ?= pre-commit
PYTEST ?= $(PYTHON) -m pytest
PIP_AUDIT ?= $(PYTHON) -m pip_audit
BUILD ?= $(PYTHON) -m build
TWINE ?= $(PYTHON) -m twine

.PHONY: all-integration-tests audit bandit black black-check check format \
	integration-test lint mypy package-build package-check pre-commit \
	remote-integration-test ruff ruff-fix security smoke-test test

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
	$(PYTEST) $(UNIT_TESTS)

integration-test:
	$(PYTEST) --no-cov -m integration $(INTEGRATION_TESTS)

remote-integration-test:
	PYTHON="$(PYTHON)" $(REMOTE_INTEGRATION_TEST_SCRIPT)

all-integration-tests: integration-test remote-integration-test

smoke-test:
	$(PYTEST) --no-cov -m smoke $(SMOKE_TESTS)

package-build:
	$(BUILD)

package-check: package-build
	$(TWINE) check dist/*

format: ruff-fix black

lint: ruff mypy bandit

check: black-check lint test

pre-commit:
	$(PRE_COMMIT) run --all-files
