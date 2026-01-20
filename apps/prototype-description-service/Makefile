.PHONY: help test lint format check clean install setup typecheck serve stop mcp

# Default target
help:
	@echo "Available commands:"
	@echo "  make setup      - Full setup (deps + face detection, platform-aware)"
	@echo "  make install    - Install core dependencies only"
	@echo "  make serve      - Start the development server + scan worker"
	@echo "  make stop       - Stop the development server"
	@echo "  make check      - Run linting, type checking, and tests"
	@echo "  make lint       - Run code linting checks"
	@echo "  make typecheck  - Run type checking with mypy"
	@echo "  make format     - Auto-fix code formatting"
	@echo "  make test       - Run pytest"
	@echo "  make ci         - Format code and run all checks"
	@echo "  make clean      - Remove cache and build files"
	@echo "  make reset      - Drop and recreate the local database"
	@echo "  make mcp        - Start the MCP server for AI agents (monorepo-wide)"

# Start MCP server (delegates to root Makefile)
mcp:
	@cd ../.. && make mcp-start

# Start development server
serve:
	@RECOGNITION_ASYNC_ANALYZE_INLINE=0 \
	START_SCAN_WORKER=1 \
	UVICORN_EXTRA_ARGS="--timeout-graceful-shutdown 1" \
	./scripts/start_prototype_local.sh start &

# Stop development server
stop:
	@./scripts/start_prototype_local.sh stop

# Reset local database
reset:
	@./scripts/reset_dev_db.sh
	@echo "✓ Local database reset"

# Run all checks and tests
check: lint typecheck test
	@echo "✓ All checks passed!"

# Lint only
lint:
	@echo "Running Ruff checks..."
	@ruff check .
	@ruff format --check .

# Type check only
typecheck:
	@echo "Running mypy type checks..."
	@mypy .

# Format code
format:
	@echo "Auto-fixing code..."
	@ruff check --fix .
	@ruff format .

# Test only
test:
	@echo "Running tests..."
	@pytest

# Auto-fix and test (for CI)
ci: format typecheck test

# Install core dependencies only (no face detection)
install:
	@pip install -e ".[dev]"

# Full setup with platform-aware face detection
setup:
	@./scripts/setup.sh

# Clean cache and build artifacts
clean:
	@find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	@echo "✓ Cleaned cache files"
