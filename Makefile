# =============================================================================
# Context Alt Text Monorepo - Root Makefile
# =============================================================================
#
# This Makefile provides commands for monorepo-wide operations.
# For app-specific commands, use the Makefile in each app directory.
#
# Quick Start:
#   make mcp-start    # Start the MCP server for AI agents
#   make mcp-stop     # Stop the MCP server
#   make check-all    # Run all linters and tests across the monorepo
#

.PHONY: help check-all check-frontend lint-all test-all clean-all mcp mcp-start handoff-close-check handoff-integrity-check

# Default target
help:
	@echo "Context Alt Text Monorepo Commands"
	@echo "==================================="
	@echo ""
	@echo "Cross-Repo Operations:"
	@echo "  make check-all    - Run all checks (lint + types + tests)"
	@echo "  make check-frontend - Run frontend checks (lint + types + arch + tests)"
	@echo "  make lint-all     - Run linters for all apps"
	@echo "  make test-all     - Run tests for all apps"
	@echo "  make clean-all    - Clean cache files in all apps"
	@echo ""
	@echo "App-Specific Commands:"
	@echo "  cd apps/prototype-description-service && make help"
	@echo "  cd apps/prototype-wp-alt-context && make help"
	@echo ""
	@echo "MCP Server (AI Agent Tooling):"
	@echo "  make mcp          - Start the MCP server for AI agents manually"
	@echo "  VS Code auto-manages via .vscode/mcp.json — no manual start needed."
	@echo "  See docs/agentic/BOOTSTRAP.md for details."
	@echo ""
	@echo "Handoff Integrity:"
	@echo "  make handoff-close-check    - Enforce close-readiness on active handoff task"
	@echo "  make handoff-integrity-check - Run parser/lifecycle/sync guard checks"

# =============================================================================
# Cross-Repo Checks
# =============================================================================

# Run all checks across the monorepo
check-all: lint-all test-all
	@echo ""
	@echo "✅ All monorepo checks passed!"

check-frontend:
	@echo "=== Frontend checks (WordPress plugin) ==="
	@cd apps/prototype-wp-alt-context && make check
	@echo ""
	@echo "✅ Frontend checks passed!"

# Lint all apps
lint-all:
	@echo "=== Linting Python (backend) ==="
	@cd apps/prototype-description-service && make lint
	@echo ""
	@echo "=== Linting TypeScript (frontend) ==="
	@cd apps/prototype-wp-alt-context && make lint
	@echo ""
	@echo "=== Linting PHP (plugin) ==="
	@cd apps/prototype-wp-alt-context && composer cs-check || true
	@echo ""
	@echo "✅ Linting complete"

# Test all apps
test-all:
	@echo "=== Testing Python (backend) ==="
	@cd apps/prototype-description-service && make test
	@echo ""
	@echo "=== Testing TypeScript (frontend) ==="
	@cd apps/prototype-wp-alt-context && make test
	@echo ""
	@echo "✅ Tests complete"

# Clean all cache files
clean-all:
	@echo "=== Cleaning Python caches ==="
	@cd apps/prototype-description-service && make clean
	@echo ""
	@echo "=== Cleaning Node caches ==="
	@cd apps/prototype-wp-alt-context && rm -rf node_modules/.cache 2>/dev/null || true
	@echo ""
	@echo "✅ All caches cleaned"

# =============================================================================
# MCP Server (Manual Start)
# =============================================================================

mcp: mcp-start

mcp-start:
	@echo "Starting MCP Server manually..."
	@./scripts/mcp/mcp-server.sh run

# =============================================================================
# Handoff / Task State
# =============================================================================

PYTHON ?= PYENV_VERSION=description-service pyenv exec python

# Generate CURRENT_TASK.md from handoff DB
task:
	@$(PYTHON) scripts/mcp/unified_server.py task

# Print handoff dashboard
dashboard:
	@$(PYTHON) scripts/mcp/unified_server.py dashboard

# Print full handoff state
state:
	@$(PYTHON) scripts/mcp/unified_server.py state

# Validate that active handoff state is ready to close
handoff-close-check:
	@$(PYTHON) scripts/mcp/unified_server.py handoff-close-check --enforce

# CI/local guard for parser + lifecycle + close-check integrity
handoff-integrity-check:
	@$(PYTHON) scripts/mcp/handoff_integrity_guard.py

# =============================================================================
# Development Shortcuts
# =============================================================================

# Start everything for development
dev:
	@echo "Starting backend server..."
	@cd apps/prototype-description-service && make serve
	@echo ""
	@echo "🚀 Development environment ready!"
	@echo "   - MCP server: auto-managed by VS Code (see .vscode/mcp.json)"
	@echo "   - Backend: http://localhost:8000"
	@echo "   - Frontend: run 'npm run dev' in apps/prototype-wp-alt-context"

# Stop everything
dev-stop:
	@cd apps/prototype-description-service && make stop 2>/dev/null || true
	@echo "✅ Development environment stopped"
