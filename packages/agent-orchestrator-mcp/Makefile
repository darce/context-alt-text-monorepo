PYENV_ROOT ?= $(HOME)/.pyenv
PYTHON ?= $(PYENV_ROOT)/versions/description-service/bin/python
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

.PHONY: help lint-orchestrator fix-lint-orchestrator format-orchestrator mypy-orchestrator test-orchestrator check-orchestrator tools-list-snapshot

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
	@echo "  make tools-list-snapshot   - Capture a normalized tools/list snapshot"

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

tools-list-snapshot:
	@PHASE="$${PHASE:-current}"; \
	if [ -n "$$OUT" ]; then :; \
	elif [ "$$PHASE" = "current" ]; then OUT="$(PACKAGE_ROOT)/.task-state/tools-list-snapshot.json"; \
	else OUT="$(PACKAGE_ROOT)/.task-state/tools-list-snapshot-$$PHASE.json"; fi; \
	PYTHONPATH="$(LOCAL_PYTHONPATH)" $(PYTHON) -m agent_orchestrator_mcp \
		--workspace-root "$(PACKAGE_ROOT)" \
		tools-snapshot --phase "$$PHASE" --output "$$OUT"
