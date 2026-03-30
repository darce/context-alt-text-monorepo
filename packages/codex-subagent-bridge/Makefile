PYTHON ?= python3
PACKAGE_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
RUFF_TARGETS := src tests
MYPY_TARGETS := src
PYTEST_TARGETS := tests

LOCAL_PYTHONPATH := $(PACKAGE_ROOT)/src
ifneq ($(PYTHONPATH),)
LOCAL_PYTHONPATH := $(LOCAL_PYTHONPATH):$(PYTHONPATH)
endif

.PHONY: help lint-bridge fix-lint-bridge format-bridge mypy-bridge test-bridge check-bridge

help:
	@echo "codex-subagent-bridge Commands"
	@echo "==============================="
	@echo ""
	@echo "  make lint-bridge     - Run Ruff checks"
	@echo "  make fix-lint-bridge - Auto-fix Ruff violations"
	@echo "  make format-bridge   - Format code with Ruff"
	@echo "  make mypy-bridge     - Run mypy"
	@echo "  make test-bridge     - Run pytest"
	@echo "  make check-bridge    - Run lint, mypy, and tests"

lint-bridge:
	@PYTHONPATH="$(LOCAL_PYTHONPATH)" $(PYTHON) -m ruff check $(RUFF_TARGETS)

fix-lint-bridge:
	@PYTHONPATH="$(LOCAL_PYTHONPATH)" $(PYTHON) -m ruff check --fix $(RUFF_TARGETS)

format-bridge:
	@PYTHONPATH="$(LOCAL_PYTHONPATH)" $(PYTHON) -m ruff format $(RUFF_TARGETS)

mypy-bridge:
	@PYTHONPATH="$(LOCAL_PYTHONPATH)" $(PYTHON) -m mypy $(MYPY_TARGETS)

test-bridge:
	@PYTHONPATH="$(LOCAL_PYTHONPATH)" $(PYTHON) -m pytest $(PYTEST_TARGETS) -q

check-bridge: lint-bridge mypy-bridge test-bridge