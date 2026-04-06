PYTHON ?= python3
PACKAGE_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
RUFF_TARGETS := src tests
MYPY_TARGETS := src
PYTEST_TARGETS := tests

LOCAL_PYTHONPATH := $(PACKAGE_ROOT)/src
ifneq ($(wildcard $(PACKAGE_ROOT)/../codex-subagent-bridge/src),)
LOCAL_PYTHONPATH := $(LOCAL_PYTHONPATH):$(PACKAGE_ROOT)/../codex-subagent-bridge/src
endif
ifneq ($(PYTHONPATH),)
LOCAL_PYTHONPATH := $(LOCAL_PYTHONPATH):$(PYTHONPATH)
endif

.PHONY: help lint-orchestrator fix-lint-orchestrator format-orchestrator mypy-orchestrator test-orchestrator check-orchestrator

help:
	@echo "agent-orchestrator-mcp Commands"
	@echo "==============================="
	@echo ""
	@echo "  make lint-orchestrator     - Run Ruff checks"
	@echo "  make fix-lint-orchestrator - Auto-fix Ruff violations"
	@echo "  make format-orchestrator   - Format code with Ruff"
	@echo "  make mypy-orchestrator     - Run mypy"
	@echo "  make test-orchestrator     - Run pytest"
	@echo "  make check-orchestrator    - Run lint, mypy, and tests"

lint-orchestrator:
	@PYTHONPATH="$(LOCAL_PYTHONPATH)" $(PYTHON) -m ruff check $(RUFF_TARGETS)

fix-lint-orchestrator:
	@PYTHONPATH="$(LOCAL_PYTHONPATH)" $(PYTHON) -m ruff check --fix $(RUFF_TARGETS)

format-orchestrator:
	@PYTHONPATH="$(LOCAL_PYTHONPATH)" $(PYTHON) -m ruff format $(RUFF_TARGETS)

mypy-orchestrator:
	@PYTHONPATH="$(LOCAL_PYTHONPATH)" $(PYTHON) -m mypy $(MYPY_TARGETS)

test-orchestrator:
	@PYTHONPATH="$(LOCAL_PYTHONPATH)" $(PYTHON) -m pytest $(PYTEST_TARGETS) -q

check-orchestrator: lint-orchestrator mypy-orchestrator test-orchestrator
