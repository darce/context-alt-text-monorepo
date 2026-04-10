PYTHON ?= python3
PACKAGES_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))

.PHONY: help fix-lint-handoff fix-lint-orchestrator fix-lint-mcp check-handoff check-orchestrator check-all-packages

help:
	@echo "MCP Package Commands"
	@echo "===================="
	@echo ""
	@echo "  make check-handoff         - Lint, mypy, and tests for agent-handoff-mcp"
	@echo "  make check-orchestrator    - Lint, mypy, and tests for agent-orchestrator-mcp"
	@echo "  make check-all-packages    - Run checks for all packages"
	@echo "  make fix-lint-handoff      - Auto-fix Ruff issues for agent-handoff-mcp"
	@echo "  make fix-lint-orchestrator - Auto-fix Ruff issues for agent-orchestrator-mcp"
	@echo "  make fix-lint-mcp          - Auto-fix Ruff issues for all MCP packages"

fix-lint-handoff:
	@$(MAKE) -C "$(PACKAGES_ROOT)/agent-handoff-mcp" fix-lint-handoff PYTHON="$(PYTHON)"

fix-lint-orchestrator:
	@$(MAKE) -C "$(PACKAGES_ROOT)/agent-orchestrator-mcp" fix-lint-orchestrator PYTHON="$(PYTHON)"

fix-lint-mcp: fix-lint-handoff fix-lint-orchestrator

check-handoff:
	@$(MAKE) -C "$(PACKAGES_ROOT)/agent-handoff-mcp" check-handoff PYTHON="$(PYTHON)"

check-orchestrator:
	@$(MAKE) -C "$(PACKAGES_ROOT)/agent-orchestrator-mcp" check-orchestrator PYTHON="$(PYTHON)"

check-all-packages: check-handoff check-orchestrator
