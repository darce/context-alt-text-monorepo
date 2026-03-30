PYTHON ?= python3
PACKAGES_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))

.PHONY: help fix-lint-handoff fix-lint-orchestrator fix-lint-mcp

help:
	@echo "MCP Package Commands"
	@echo "===================="
	@echo ""
	@echo "  make fix-lint-handoff      - Auto-fix Ruff issues for agent-handoff-mcp"
	@echo "  make fix-lint-orchestrator - Auto-fix Ruff issues for agent-orchestrator-mcp"
	@echo "  make fix-lint-mcp          - Run both MCP Ruff auto-fix targets"

fix-lint-handoff:
	@$(MAKE) -C "$(PACKAGES_ROOT)/agent-handoff-mcp" fix-lint-handoff PYTHON="$(PYTHON)"

fix-lint-orchestrator:
	@$(MAKE) -C "$(PACKAGES_ROOT)/agent-orchestrator-mcp" fix-lint-orchestrator PYTHON="$(PYTHON)"

fix-lint-mcp: fix-lint-handoff fix-lint-orchestrator
