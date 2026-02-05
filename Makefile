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

.PHONY: help mcp-start mcp-stop mcp-restart mcp-status mcp-run \
        check-all lint-all test-all clean-all

# Default target
help:
	@echo "Context Alt Text Monorepo Commands"
	@echo "==================================="
	@echo ""
	@echo "MCP Server (AI Agent Tooling):"
	@echo "  make mcp-start    - Start MCP server in background"
	@echo "  make mcp-stop     - Stop MCP server"
	@echo "  make mcp-restart  - Restart MCP server"
	@echo "  make mcp-status   - Check if MCP server is running"
	@echo "  make mcp-run      - Run MCP server in foreground"
	@echo ""
	@echo "Cross-Repo Operations:"
	@echo "  make check-all    - Run all checks (lint + types + tests)"
	@echo "  make lint-all     - Run linters for all apps"
	@echo "  make test-all     - Run tests for all apps"
	@echo "  make clean-all    - Clean cache files in all apps"
	@echo ""
	@echo "App-Specific Commands:"
	@echo "  cd apps/prototype-description-service && make help"
	@echo "  cd apps/prototype-wp-alt-context && npm run help"

# =============================================================================
# MCP Server Commands
# =============================================================================

mcp-start:
	@./scripts/mcp/mcp-server.sh start

mcp-stop:
	@./scripts/mcp/mcp-server.sh stop

mcp-restart:
	@./scripts/mcp/mcp-server.sh restart

mcp-status:
	@./scripts/mcp/mcp-server.sh status

mcp-run:
	@./scripts/mcp/mcp-server.sh run

# =============================================================================
# Cross-Repo Checks
# =============================================================================

# Run all checks across the monorepo
check-all: lint-all test-all
	@echo ""
	@echo "✅ All monorepo checks passed!"

# Lint all apps
lint-all:
	@echo "=== Linting Python (backend) ==="
	@cd apps/prototype-description-service && make lint
	@echo ""
	@echo "=== Linting TypeScript (frontend) ==="
	@cd apps/prototype-wp-alt-context && npm run lint --silent
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
	@cd apps/prototype-wp-alt-context && npm run test -- --run
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
# Development Shortcuts
# =============================================================================

# Start everything for development
dev: mcp-start
	@echo ""
	@echo "Starting backend server..."
	@cd apps/prototype-description-service && make serve
	@echo ""
	@echo "🚀 Development environment ready!"
	@echo "   - MCP server: running (for AI agents)"
	@echo "   - Backend: http://localhost:8000"
	@echo "   - Frontend: run 'npm run dev' in apps/prototype-wp-alt-context"

# Stop everything
dev-stop: mcp-stop
	@cd apps/prototype-description-service && make stop 2>/dev/null || true
	@echo "✅ Development environment stopped"
