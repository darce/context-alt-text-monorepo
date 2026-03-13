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

.PHONY: help check-all check-frontend lint-all test-all clean-all reset-local mcp mcp-start handoff-close-check handoff-integrity-check fix-php-style lane-open lane-status lane-report lane-commit lane-handoff lane-reset lane-guard lane-path lane-commits lane-intake lane-orchestrator-guard

WORKTREE_ROOT := $(shell git rev-parse --show-toplevel 2>/dev/null)
CURRENT_BRANCH := $(shell git -C "$(WORKTREE_ROOT)" rev-parse --abbrev-ref HEAD 2>/dev/null)
WORKTREE_ROOT_REAL := $(abspath $(WORKTREE_ROOT))
ORCHESTRATOR_ROOT := $(patsubst %-p5-backend-domain,%,$(patsubst %-p5-backend-http,%,$(patsubst %-p5-wp-proxy,%,$(patsubst %-p5-frontend,%,$(WORKTREE_ROOT_REAL)))))
ACTIVE_TASK := $(shell agent-handoff-mcp --workspace-root "$(ORCHESTRATOR_ROOT)" state 2>/dev/null | python3 -c 'import sys,json; data=json.load(sys.stdin); print(data.get("task_ref",""))' 2>/dev/null)
INFERRED_LANE := $(if $(filter codex/p5-backend-domain,$(CURRENT_BRANCH)),backend-domain,$(if $(filter codex/p5-backend-http,$(CURRENT_BRANCH)),backend-http,$(if $(filter codex/p5-wp-proxy,$(CURRENT_BRANCH)),wp-proxy,$(if $(filter codex/p5-frontend,$(CURRENT_BRANCH)),frontend,))))
TASK ?= $(ACTIVE_TASK)
LANE ?= $(INFERRED_LANE)
SESSION ?= $(TASK)-$(LANE)
SUMMARY ?= $(LANE) lane ready for orchestrator review.
MESSAGE ?=
STATUS ?= submitted
MERGE_READY ?= 1
DRY_RUN ?= 0
REF ?= $(CURRENT_BRANCH)
ENTER_SHELL ?= 0
PHASE5_LANES := backend-domain backend-http wp-proxy frontend
IN_ORCHESTRATOR_ROOT := $(if $(filter $(WORKTREE_ROOT_REAL),$(ORCHESTRATOR_ROOT)),1,0)

LANE_BRANCH :=
LANE_WORKTREE :=
LANE_TITLE :=
LANE_OBJECTIVE :=
LANE_OWNED_ARGS :=
LANE_DOC_ARGS :=
LANE_TEST_ARGS :=
LANE_TEST_CMD_1 :=
LANE_TEST_CMD_2 :=
LANE_NON_GOAL_ARGS :=
LANE_COMMIT_PATHS :=
LANE_COMMIT_SUBJECT :=
LANE_DONE_DEFINITION := Ready for orchestrator branch review with lane-local verification complete.

ifeq ($(TASK),phase-5-retention-export-and-audit-controls)
  ifeq ($(LANE),backend-domain)
    LANE_BRANCH := codex/p5-backend-domain
    LANE_WORKTREE := $(ORCHESTRATOR_ROOT)-p5-backend-domain
    LANE_TITLE := Backend domain
    LANE_OBJECTIVE := Phase 5 backend-domain retention/export/audit slice.
    LANE_OWNED_ARGS := --owned-path "apps/prototype-description-service/db/**" --owned-path "apps/prototype-description-service/recognition/domain/**" --owned-path "apps/prototype-description-service/recognition/infrastructure/**"
    LANE_DOC_ARGS := --required-doc "docs/agentic/instructions.md" --required-doc "docs/tasks/6.0/phase-5-retention-export-and-audit-controls-task-plan.md"
    LANE_TEST_CMD_1 := cd apps/prototype-description-service && pytest recognition/tests/unit/test_retention_policy.py recognition/tests/unit/test_audit_events.py recognition/tests/unit/test_export_service.py recognition/tests/unit/test_purge_service.py
    LANE_TEST_CMD_2 := cd apps/prototype-description-service && mypy recognition/domain/services recognition/infrastructure/repositories recognition/config/settings.py
    LANE_TEST_ARGS := --test-command "cd apps/prototype-description-service && pytest recognition/tests/unit/test_retention_policy.py recognition/tests/unit/test_audit_events.py recognition/tests/unit/test_export_service.py recognition/tests/unit/test_purge_service.py" --test-command "cd apps/prototype-description-service && mypy recognition/domain/services recognition/infrastructure/repositories recognition/config/settings.py"
    LANE_NON_GOAL_ARGS := --non-goal "Do not edit HTTP router files." --non-goal "Do not edit WordPress or frontend files."
    LANE_COMMIT_PATHS := apps/prototype-description-service/db apps/prototype-description-service/recognition/domain apps/prototype-description-service/recognition/infrastructure
    LANE_COMMIT_SUBJECT := update retention domain services
  endif
  ifeq ($(LANE),backend-http)
    LANE_BRANCH := codex/p5-backend-http
    LANE_WORKTREE := $(ORCHESTRATOR_ROOT)-p5-backend-http
    LANE_TITLE := Backend HTTP
    LANE_OBJECTIVE := Phase 5 backend-http retention router and schema slice.
    LANE_OWNED_ARGS := --owned-path "apps/prototype-description-service/recognition/interface_adapters/http/**"
    LANE_DOC_ARGS := --required-doc "docs/agentic/instructions.md" --required-doc "docs/tasks/6.0/phase-5-retention-export-and-audit-controls-task-plan.md"
    LANE_TEST_CMD_1 := cd apps/prototype-description-service && pytest recognition/tests/api/test_retention_api.py
    LANE_TEST_CMD_2 := cd apps/prototype-description-service && mypy recognition/interface_adapters/http
    LANE_TEST_ARGS := --test-command "cd apps/prototype-description-service && pytest recognition/tests/api/test_retention_api.py" --test-command "cd apps/prototype-description-service && mypy recognition/interface_adapters/http"
    LANE_NON_GOAL_ARGS := --non-goal "Do not edit backend domain/repository files outside the HTTP layer." --non-goal "Do not edit WordPress or frontend files."
    LANE_COMMIT_PATHS := apps/prototype-description-service/recognition/interface_adapters/http
    LANE_COMMIT_SUBJECT := update retention HTTP routes
  endif
  ifeq ($(LANE),wp-proxy)
    LANE_BRANCH := codex/p5-wp-proxy
    LANE_WORKTREE := $(ORCHESTRATOR_ROOT)-p5-wp-proxy
    LANE_TITLE := WP proxy
    LANE_OBJECTIVE := Phase 5 WordPress retention proxy slice.
    LANE_OWNED_ARGS := --owned-path "apps/prototype-wp-alt-context/src/**" --owned-path "apps/prototype-wp-alt-context/tests/Unit/**"
    LANE_DOC_ARGS := --required-doc "docs/agentic/instructions.md" --required-doc "docs/tasks/6.0/phase-5-retention-export-and-audit-controls-task-plan.md"
    LANE_TEST_CMD_1 := cd apps/prototype-wp-alt-context && ./vendor/bin/phpunit tests/Unit/RetentionControllerTest.php tests/Unit/RecognitionControllerTest.php tests/Unit/SnapshotClientTest.php tests/Unit/SyncPullJobTest.php tests/Unit/AdminTest.php
    LANE_TEST_ARGS := --test-command "cd apps/prototype-wp-alt-context && ./vendor/bin/phpunit tests/Unit/RetentionControllerTest.php tests/Unit/RecognitionControllerTest.php tests/Unit/SnapshotClientTest.php tests/Unit/SyncPullJobTest.php tests/Unit/AdminTest.php"
    LANE_NON_GOAL_ARGS := --non-goal "Do not edit frontend React/TypeScript files." --non-goal "Do not edit backend Python files."
    LANE_COMMIT_PATHS := apps/prototype-wp-alt-context/src apps/prototype-wp-alt-context/tests/Unit
    LANE_COMMIT_SUBJECT := update retention proxy
  endif
  ifeq ($(LANE),frontend)
    LANE_BRANCH := codex/p5-frontend
    LANE_WORKTREE := $(ORCHESTRATOR_ROOT)-p5-frontend
    LANE_TITLE := Frontend
    LANE_OBJECTIVE := Phase 5 retention admin UI slice.
    LANE_OWNED_ARGS := --owned-path "apps/prototype-wp-alt-context/js/**"
    LANE_DOC_ARGS := --required-doc "docs/agentic/instructions.md" --required-doc "docs/tasks/6.0/phase-5-retention-export-and-audit-controls-task-plan.md"
    LANE_TEST_CMD_1 := cd apps/prototype-wp-alt-context && npm run test -- --run js/admin/api/__tests__/recognitionApi.test.ts js/admin/pages/__tests__/RetentionPage.test.tsx js/admin/pages/__tests__/DashboardPage.test.tsx js/admin/pages/workbench/__tests__/SyncStatusIndicator.test.tsx js/admin/__tests__/routeHelpers.test.ts
    LANE_TEST_CMD_2 := cd apps/prototype-wp-alt-context && npm run typecheck
    LANE_TEST_ARGS := --test-command "cd apps/prototype-wp-alt-context && npm run test -- --run js/admin/api/__tests__/recognitionApi.test.ts js/admin/pages/__tests__/RetentionPage.test.tsx js/admin/pages/__tests__/DashboardPage.test.tsx js/admin/pages/workbench/__tests__/SyncStatusIndicator.test.tsx js/admin/__tests__/routeHelpers.test.ts" --test-command "cd apps/prototype-wp-alt-context && npm run typecheck"
    LANE_NON_GOAL_ARGS := --non-goal "Do not edit PHP or Python files." --non-goal "Do not edit shared task docs unless explicitly assigned."
    LANE_COMMIT_PATHS := apps/prototype-wp-alt-context/js
    LANE_COMMIT_SUBJECT := update retention admin UI
  endif
endif

# Default target
help:
	@echo "Context Alt Text Monorepo Commands"
	@echo "==================================="
	@echo ""
	@echo "Cross-Repo Operations:"
	@echo "  make check-all    - Run all checks (lint + types + tests)"
	@echo "  make check-frontend - Run frontend checks (lint + types + arch + tests)"
	@echo "  make lint-all     - Run linters for all apps"
	@echo "  make fix-php-style - Auto-fix WordPress plugin PHPCS violations (manual)"
	@echo "  make test-all     - Run tests for all apps"
	@echo "  make clean-all    - Clean cache files in all apps"
	@echo "  make reset-local  - Reset local backend DB + WordPress projection data (destructive, dev-only)"
	@echo ""
	@echo "App-Specific Commands:"
	@echo "  cd apps/prototype-description-service && make help"
	@echo "  cd apps/prototype-wp-alt-context && make help"
	@echo ""
	@echo "MCP Server (AI Agent Tooling):"
	@echo "  make mcp          - Start the MCP server for AI agents manually"
	@echo "  make gemini-cli-setup - Register the MCP server with gemini-cli"
	@echo "  VS Code auto-manages via .vscode/mcp.json — no manual start needed."
	@echo "  See docs/agentic/BOOTSTRAP.md for details."
	@echo ""
	@echo "Handoff Integrity:"
	@echo "  make handoff-close-check    - Enforce close-readiness on active handoff task"
	@echo "  make handoff-integrity-check - Run parser/lifecycle/sync guard checks"
	@echo ""
	@echo "Worktree Lanes (task-aware wrappers around scripts/worktree-lane):"
	@echo "  make lane-open TASK=phase-5-retention-export-and-audit-controls LANE=frontend"
	@echo "    Add ENTER_SHELL=1 to drop into a subshell in the worktree after setup."
	@echo "  make lane-status TASK=phase-5-retention-export-and-audit-controls LANE=frontend"
	@echo "  make lane-report TASK=phase-5-retention-export-and-audit-controls LANE=frontend"
	@echo "    Optional overrides: SESSION=<name> SUMMARY=\"...\" MERGE_READY=0 MESSAGE=\"...\""
	@echo "  make lane-commit"
	@echo "    Worker default commit step: stage lane-owned paths and create a commit like '<lane>: <subject>'."
	@echo "  make lane-handoff"
	@echo "    Worker default: commit lane-owned changes, show lane status, then submit a merge-ready lane report using inferred TASK/LANE/SESSION."
	@echo "  make lane-reset TASK=phase-5-retention-export-and-audit-controls LANE=frontend [REF=$(CURRENT_BRANCH)]"
	@echo "  make lane-path TASK=phase-5-retention-export-and-audit-controls LANE=frontend"
	@echo "  make lane-commits TASK=phase-5-retention-export-and-audit-controls LANE=frontend"
	@echo "  make lane-intake TASK=phase-5-retention-export-and-audit-controls LANE=frontend [DRY_RUN=1]"
	@echo "    Prints the unique lane commits first, then cherry-picks them in order."
	@echo "  Enumerated Phase 5 lanes: $(PHASE5_LANES)"

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
	@cd apps/prototype-wp-alt-context && composer cs-check
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

# Reset local backend DB + local WordPress projection data.
# Usage:
#   make reset-local WP_PATH="/path/to/wordpress/site" CONFIRM_LOCAL_RESET="RESET"
#
# This is intentionally dev-only. The backend reset already targets the local dev
# database, and the plugin target refuses non-local WordPress sites unless
# ALLOW_NON_LOCAL=1 is passed explicitly.
# For LocalWP on this machine, WP_PATH is typically the site's `app/public`
# directory, e.g. `/Users/daniel/Development/wp-context-alt-text/app/public`.
reset-local:
	@if [ "$(CONFIRM_LOCAL_RESET)" != "RESET" ]; then \
		echo "Refusing destructive local reset."; \
		echo "Re-run with CONFIRM_LOCAL_RESET=\"RESET\" to confirm."; \
		echo "Example: make reset-local WP_PATH=\"$$HOME/Development/wp-context-alt-text/app/public\" CONFIRM_LOCAL_RESET=\"RESET\""; \
		exit 1; \
	fi
	@if [ -z "$(WP_PATH)" ]; then \
		echo "WP_PATH is required (path to WordPress root containing wp-load.php)."; \
		echo "Example: make reset-local WP_PATH=\"$$HOME/Development/wp-context-alt-text/app/public\" CONFIRM_LOCAL_RESET=\"RESET\""; \
		exit 1; \
	fi
	@echo "=== Resetting local backend database ==="
	@$(MAKE) -C apps/prototype-description-service reset
	@echo ""
	@echo "=== Resetting local WordPress projection data ==="
	@$(MAKE) -C apps/prototype-wp-alt-context projection-reset \
		WP_PATH="$(WP_PATH)" \
		CONFIRM_ACX_PROJECTION_RESET="RESET" \
		LOCALWP_SOCKET="$(LOCALWP_SOCKET)" \
		ALLOW_NON_LOCAL="$(ALLOW_NON_LOCAL)"
	@echo ""
	@echo "✅ Local backend DB and WordPress projection data reset"

# Auto-fix PHP style violations in the WordPress plugin (manual, mutating).
fix-php-style:
	@cd apps/prototype-wp-alt-context && make php-cs-fix
	@echo "✅ PHP style auto-fixes applied"

# =============================================================================
# MCP Server (Manual Start)
# =============================================================================

mcp: mcp-start

mcp-start:
	@echo "Starting MCP Server manually..."
	@./scripts/mcp/mcp-server.sh run

gemini-cli-setup:
	@echo "Registering unified_server.py with gemini-cli..."
	@gemini mcp add context-alt-text-handoff "$(shell pwd)/scripts/mcp/mcp-server.sh" run
	@echo "✓ MCP server 'context-alt-text-handoff' registered with gemini-cli"
	@echo "💡 Tip: Store your API key in a .env file at the monorepo root to keep it out of your .zshrc."

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
# Worktree Lane Orchestration
# =============================================================================

lane-guard:
	@if [ -z "$(TASK)" ]; then \
		echo "TASK is required."; \
		echo "No active task could be inferred from MCP state."; \
		echo "Example: make lane-open TASK=phase-5-retention-export-and-audit-controls LANE=frontend"; \
		exit 1; \
	fi
	@if [ -z "$(LANE)" ]; then \
		echo "LANE is required."; \
		echo "No lane could be inferred from branch $(CURRENT_BRANCH)."; \
		echo "Allowed lanes for Phase 5: $(PHASE5_LANES)"; \
		exit 1; \
	fi
	@if [ "$(TASK)" != "phase-5-retention-export-and-audit-controls" ]; then \
		echo "Unsupported TASK: $(TASK)"; \
		echo "This Makefile currently enumerates lanes only for phase-5-retention-export-and-audit-controls."; \
		exit 1; \
	fi
	@if [ -z "$(LANE_BRANCH)" ]; then \
		echo "Unsupported LANE: $(LANE)"; \
		echo "Allowed lanes for $(TASK): $(PHASE5_LANES)"; \
		exit 1; \
	fi

lane-orchestrator-guard: lane-guard
	@if [ "$(IN_ORCHESTRATOR_ROOT)" != "1" ]; then \
		echo "lane-commits and lane-intake must be run from the orchestrator root."; \
		echo "Current worktree: $(WORKTREE_ROOT_REAL)"; \
		echo "Expected orchestrator root: $(ORCHESTRATOR_ROOT)"; \
		exit 1; \
	fi

lane-open: lane-guard
	@set -eu; \
	DRY_FLAG=""; \
	if [ "$(DRY_RUN)" = "1" ]; then DRY_FLAG="--dry-run"; fi; \
	scripts/worktree-lane create \
		--orchestrator-root "$(ORCHESTRATOR_ROOT)" \
		--lane-id "$(LANE)" \
		--branch "$(LANE_BRANCH)" \
		--worktree-path "$(LANE_WORKTREE)" \
		--title "$(LANE_TITLE)" \
		--objective "$(LANE_OBJECTIVE)" \
		--owner-agent codex \
		--status active \
		--notes "Makefile-managed worker lane for $(TASK)." \
		$$DRY_FLAG; \
	echo ""; \
	scripts/worktree-lane brief \
		--orchestrator-root "$(ORCHESTRATOR_ROOT)" \
		--task-ref "$(TASK)" \
		--lane-id "$(LANE)" \
		--branch "$(LANE_BRANCH)" \
		--worktree-path "$(LANE_WORKTREE)" \
		--title "$(LANE_TITLE)" \
		--objective "$(LANE_OBJECTIVE)" \
		$(LANE_OWNED_ARGS) \
		$(LANE_DOC_ARGS) \
		$(LANE_TEST_ARGS) \
		$(LANE_NON_GOAL_ARGS) \
		--definition "$(LANE_DONE_DEFINITION)"; \
	if [ "$(ENTER_SHELL)" = "1" ] && [ "$(DRY_RUN)" != "1" ]; then \
		echo ""; \
		echo "Opening interactive shell in $(LANE_WORKTREE)"; \
		cd "$(LANE_WORKTREE)" && exec "$${SHELL:-/bin/zsh}" -l; \
	else \
		echo ""; \
		echo "Worktree ready at $(LANE_WORKTREE)"; \
		echo "Next step: cd \"$(LANE_WORKTREE)\""; \
	fi

lane-status: lane-guard
	@set -eu; \
	scripts/worktree-lane status \
		--orchestrator-root "$(ORCHESTRATOR_ROOT)" \
		--lane-id "$(LANE)" \
		--worktree-path "$(LANE_WORKTREE)"; \
	echo ""; \
	git -C "$(LANE_WORKTREE)" status -sb

lane-report: lane-guard
	@set -eu; \
	set -- scripts/worktree-lane report \
		--orchestrator-root "$(ORCHESTRATOR_ROOT)" \
		--task-ref "$(TASK)" \
		--lane-id "$(LANE)" \
		--session "$(SESSION)" \
		--summary "$(SUMMARY)" \
		--status "$(STATUS)" \
		--worktree-path "$(LANE_WORKTREE)"; \
	if [ -n "$(LANE_TEST_CMD_1)" ]; then set -- "$$@" --test-command "$(LANE_TEST_CMD_1)"; fi; \
	if [ -n "$(LANE_TEST_CMD_2)" ]; then set -- "$$@" --test-command "$(LANE_TEST_CMD_2)"; fi; \
	if [ "$(MERGE_READY)" = "1" ]; then set -- "$$@" --merge-ready; fi; \
	if [ "$(DRY_RUN)" = "1" ]; then set -- "$$@" --dry-run; fi; \
	if [ -n "$(MESSAGE)" ]; then set -- "$$@" --message "$(MESSAGE)" --subject "$(LANE) lane update"; fi; \
	"$$@"

lane-commit: lane-guard
	@set -eu; \
	if [ -z "$(LANE_COMMIT_PATHS)" ]; then \
		echo "No lane-owned commit paths configured for $(LANE)."; \
		exit 1; \
	fi; \
	if [ "$(DRY_RUN)" = "1" ]; then \
		echo "[dry-run] git add -A -- $(LANE_COMMIT_PATHS)"; \
		echo "[dry-run] git commit -m \"$(LANE): $(LANE_COMMIT_SUBJECT)\""; \
	else \
		git add -A -- $(LANE_COMMIT_PATHS); \
		if git diff --cached --quiet -- $(LANE_COMMIT_PATHS); then \
			echo "No lane-owned changes to commit for $(LANE)."; \
		else \
			git commit -m "$(LANE): $(LANE_COMMIT_SUBJECT)"; \
		fi; \
	fi

lane-handoff: lane-guard
	@set -eu; \
	$(MAKE) lane-commit TASK="$(TASK)" LANE="$(LANE)" DRY_RUN="$(DRY_RUN)"; \
	echo ""; \
	$(MAKE) lane-status TASK="$(TASK)" LANE="$(LANE)"; \
	echo ""; \
	$(MAKE) lane-report TASK="$(TASK)" LANE="$(LANE)" SESSION="$(SESSION)" SUMMARY="$(SUMMARY)" STATUS="$(STATUS)" MERGE_READY="$(MERGE_READY)" DRY_RUN="$(DRY_RUN)" MESSAGE="$(MESSAGE)"

lane-reset: lane-guard
	@if [ -z "$(REF)" ]; then \
		echo "REF is required."; \
		exit 1; \
	fi
	@set -eu; \
	if [ "$(DRY_RUN)" = "1" ]; then \
		echo "[dry-run] git -C \"$(LANE_WORKTREE)\" reset --hard \"$(REF)\""; \
		echo "[dry-run] git -C \"$(LANE_WORKTREE)\" clean -fd"; \
	else \
		git -C "$(LANE_WORKTREE)" reset --hard "$(REF)"; \
		git -C "$(LANE_WORKTREE)" clean -fd; \
		git -C "$(LANE_WORKTREE)" status -sb; \
	fi

lane-path: lane-guard
	@printf '%s\n' "$(LANE_WORKTREE)"

lane-commits: lane-orchestrator-guard
	@set -eu; \
	COMMITS="$$(git rev-list --reverse HEAD..$(LANE_BRANCH))"; \
	if [ -z "$$COMMITS" ]; then \
		echo "No commits to intake from $(LANE_BRANCH)."; \
	else \
		git log --oneline --reverse HEAD..$(LANE_BRANCH); \
	fi

lane-intake: lane-orchestrator-guard
	@set -eu; \
	COMMITS="$$(git rev-list --reverse HEAD..$(LANE_BRANCH))"; \
	if [ -z "$$COMMITS" ]; then \
		echo "No commits to intake from $(LANE_BRANCH)."; \
	elif [ "$(DRY_RUN)" = "1" ]; then \
		echo "Lane commits from $(LANE_BRANCH):"; \
		git log --oneline --reverse HEAD..$(LANE_BRANCH); \
		echo ""; \
		echo "[dry-run] git cherry-pick $$COMMITS"; \
	else \
		echo "Lane commits from $(LANE_BRANCH):"; \
		git log --oneline --reverse HEAD..$(LANE_BRANCH); \
		echo ""; \
		git cherry-pick $$COMMITS; \
	fi

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
