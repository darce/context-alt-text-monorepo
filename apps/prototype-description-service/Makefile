.PHONY: help test lint format check clean install setup typecheck serve stop mcp postgres-start dev-ready logs-tail logs-rotate logs-clean logs-archive lane-open lane-status lane-report lane-commit lane-handoff lane-reset lane-path

# Default target
help:
	@echo "Available commands:"
	@echo "  make setup      - Full setup (deps + face detection, platform-aware)"
	@echo "  make install    - Install core dependencies only"
	@echo "  make postgres-start - Start local PostgreSQL via Homebrew (if needed)"
	@echo "  make dev-ready  - Prepare local env for development/testing (no dependency install)"
	@echo "  make serve      - Start PostgreSQL + development server + scan worker"
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
	@echo "  make lane-open  - Prepare + brief the current worker lane via the root Makefile"
	@echo "  make lane-status - Show shared MCP + git status for the current worker lane"
	@echo "  make lane-report - Submit a lane handback via the root Makefile"
	@echo "  make lane-commit - Stage and commit lane-owned changes via the root Makefile"
	@echo "  make lane-handoff - Show lane status and submit the default worker handoff"
	@echo "  make lane-reset - Reset the current worker lane to a ref via the root Makefile"
	@echo ""
	@echo "Log Management:"
	@echo "  make logs-tail    - Tail the main recognition log"
	@echo "  make logs-rotate  - Rotate logs (current→.1→.2→...→.10)"
	@echo "  make logs-clean   - Remove rotated logs (keep current)"
	@echo "  make logs-archive - Archive and compress old logs"

# Start MCP server (delegates to root Makefile)
mcp:
	@cd ../.. && make mcp-start

lane-open lane-status lane-report lane-commit lane-handoff lane-reset lane-path:
	@ROOT_MAKE_DIR="$$(git rev-parse --show-toplevel)"; \
	$(MAKE) -C "$$ROOT_MAKE_DIR" $@

# Start local PostgreSQL service (native Homebrew install)
postgres-start:
	@if ! command -v pg_isready >/dev/null 2>&1; then \
		echo "pg_isready not found. Install PostgreSQL tools first." >&2; \
		exit 1; \
	fi
	@DB_HOST="$${PGHOST:-localhost}"; \
	DB_PORT="$${PGPORT:-5432}"; \
	if pg_isready -h "$$DB_HOST" -p "$$DB_PORT" >/dev/null 2>&1; then \
		echo "✓ PostgreSQL already running at $$DB_HOST:$$DB_PORT"; \
	elif command -v brew >/dev/null 2>&1; then \
		echo "Starting PostgreSQL (postgresql@17) via Homebrew..."; \
		brew services start postgresql@17 >/dev/null; \
		for i in 1 2 3 4 5 6 7 8 9 10; do \
			if pg_isready -h "$$DB_HOST" -p "$$DB_PORT" >/dev/null 2>&1; then \
				echo "✓ PostgreSQL is ready at $$DB_HOST:$$DB_PORT"; \
				exit 0; \
			fi; \
			sleep 1; \
		done; \
		echo "PostgreSQL did not become ready at $$DB_HOST:$$DB_PORT." >&2; \
		exit 1; \
	else \
		echo "PostgreSQL is not running and Homebrew is unavailable." >&2; \
		echo "Start PostgreSQL manually, then rerun this command." >&2; \
		exit 1; \
	fi

# Prepare local environment for development/testing (dependencies assumed installed)
dev-ready: postgres-start
	@echo "✓ Local environment ready for development and testing"

# Start development server
serve: dev-ready
	@RECOGNITION_ASYNC_ANALYZE_INLINE=0 \
	START_SCAN_WORKER=1 \
	UVICORN_EXTRA_ARGS="--timeout-graceful-shutdown 1" \
	SKIP_INSTALL=1 \
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

# =============================================================================
# Log Management
# =============================================================================

# Tail the main recognition log
logs-tail:
	@tail -f logs/recognition.log

# Rotate logs (shift current to .1, .1 to .2, etc., keep 10 rotations)
# NOTE: WatchedFileHandler in api/logging_config.py auto-detects rotation,
# so no server restart is needed after running this target.
logs-rotate:
	@echo "Rotating logs..."
	@for log in logs/recognition.log logs/scan_worker.log; do \
		if [ -f "$$log" ]; then \
			for i in 9 8 7 6 5 4 3 2 1; do \
				[ -f "$$log.$$i" ] && mv "$$log.$$i" "$$log.$$((i+1))"; \
			done; \
			mv "$$log" "$$log.1"; \
			touch "$$log"; \
			echo "  ✓ Rotated $$log"; \
		fi; \
	done
	@echo "✓ Log rotation complete"

# Remove rotated log files (keep current logs)
logs-clean:
	@echo "Removing rotated logs..."
	@rm -f logs/*.log.[0-9]* 2>/dev/null || true
	@rm -f logs/*_[0-9]*.log 2>/dev/null || true
	@echo "✓ Rotated logs removed"
	@echo "Remaining logs:"
	@ls -lh logs/*.log 2>/dev/null || echo "  (no active logs)"

# Archive old logs to compressed tarball
logs-archive:
	@echo "Archiving logs..."
	@mkdir -p logs/archive
	@ARCHIVE_NAME="logs/archive/logs_$$(date +%Y%m%d_%H%M%S).tar.gz"; \
	if ls logs/*.log.[0-9]* logs/*_[0-9]*.log 1>/dev/null 2>&1; then \
		tar -czf "$$ARCHIVE_NAME" logs/*.log.[0-9]* logs/*_[0-9]*.log 2>/dev/null && \
		rm -f logs/*.log.[0-9]* logs/*_[0-9]*.log && \
		echo "✓ Archived to $$ARCHIVE_NAME"; \
	else \
		echo "No rotated logs to archive"; \
	fi
