PYTHON ?= python3
PACKAGES_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))

.PHONY: help fix-lint-orchestrator fix-lint-mcp check-orchestrator check-all-packages

help:
	@echo "MCP Package Commands"
	@echo "===================="
	@echo ""
	@echo "  make fix-lint-orchestrator - Auto-fix Ruff issues for agent-orchestrator-mcp"
	@echo "  make fix-lint-mcp          - Run the monorepo MCP Ruff auto-fix target"
	@echo "  make check-orchestrator    - Lint, mypy, and tests for agent-orchestrator-mcp"
	@echo "  make check-all-packages    - Run check-orchestrator"

fix-lint-orchestrator:
	@$(MAKE) -C "$(PACKAGES_ROOT)/agent-orchestrator-mcp" fix-lint-orchestrator PYTHON="$(PYTHON)"

fix-lint-mcp: fix-lint-orchestrator

check-orchestrator:
	@$(MAKE) -C "$(PACKAGES_ROOT)/agent-orchestrator-mcp" check-orchestrator PYTHON="$(PYTHON)"

check-all-packages: check-orchestrator
