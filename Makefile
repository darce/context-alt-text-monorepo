# =============================================================================
# AltContext Monorepo - Root Makefile
# =============================================================================
#
# This Makefile provides commands for monorepo-wide operations.
# For app-specific commands, use the Makefile in each app directory.
#
# Quick Start:
#   make mcp-start    # Start the MCP server for AI agents
#   make check-all    # Run all linters and tests across the monorepo
#
# Structure:
#   mk/handoff.mk          - Handoff state, task commands, daemons
#   mk/lane-guards.mk      - Lane prerequisite guards, manifest init
#   mk/lane-lifecycle.mk   - Lane open, status, inbox, prompt, dispatch
#   mk/lane-worker.mk      - Lane check, run, report, commit, handoff
#   mk/lane-maintenance.mk - Lane reset, refresh, clean, path, commits, intake
#

ROOT_MAKEFILE := $(abspath $(lastword $(MAKEFILE_LIST)))
ROOT_MAKEFILE_DIR := $(patsubst %/,%,$(dir $(ROOT_MAKEFILE)))

# --- Git / Orchestrator detection ---
WORKTREE_ROOT := $(shell git rev-parse --show-toplevel 2>/dev/null)
CURRENT_BRANCH := $(shell git -C "$(WORKTREE_ROOT)" rev-parse --abbrev-ref HEAD 2>/dev/null)
WORKTREE_ROOT_REAL := $(abspath $(WORKTREE_ROOT))
_GIT_COMMON_DIR := $(shell git rev-parse --git-common-dir 2>/dev/null)
ORCHESTRATOR_ROOT := $(if $(filter .git,$(_GIT_COMMON_DIR)),$(WORKTREE_ROOT_REAL),$(patsubst %/.git,%,$(_GIT_COMMON_DIR)))
ORCHESTRATOR_BRANCH := $(shell git -C "$(ORCHESTRATOR_ROOT)" rev-parse --abbrev-ref HEAD 2>/dev/null)
IN_ORCHESTRATOR_ROOT := $(if $(filter $(WORKTREE_ROOT_REAL),$(ORCHESTRATOR_ROOT)),1,0)

# --- MCP runtime ---
MCP_PYENV_VERSION ?= description-service
MCP_PYENV_BIN := $(shell command -v pyenv 2>/dev/null || true)
MCP_PYTHON = $(if $(MCP_PYENV_BIN),env PYENV_VERSION="$(MCP_PYENV_VERSION)" "$(MCP_PYENV_BIN)" exec python3,env PYENV_VERSION="$(MCP_PYENV_VERSION)" python3)
ORCHESTRATION_DIR := $(ORCHESTRATOR_ROOT)/packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration
WORKTREE_ORCHESTRATION_DIR := $(WORKTREE_ROOT_REAL)/packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration
LANE_CONFIG_CMD = $(MCP_PYTHON) "$(ORCHESTRATION_DIR)/lane_config.py"
MCP_PYTHONPATH := $(ORCHESTRATOR_ROOT)/packages/agent-handoff-mcp/src:$(ORCHESTRATOR_ROOT)/packages/codex-subagent-bridge/src$(if $(PYTHONPATH),:$(PYTHONPATH),)
WORKTREE_MCP_PYTHONPATH := $(WORKTREE_ROOT_REAL)/packages/agent-handoff-mcp/src:$(WORKTREE_ROOT_REAL)/packages/codex-subagent-bridge/src$(if $(PYTHONPATH),:$(PYTHONPATH),)
MCP_CMD = PYTHONPATH="$(MCP_PYTHONPATH)" $(MCP_PYTHON) -m agent_handoff_mcp
MCP_STATE_ARGS = --workspace-root "$(ORCHESTRATOR_ROOT)" --state-dir "$(ORCHESTRATOR_ROOT)/.task-state" --current-task-path "$(ORCHESTRATOR_ROOT)/CURRENT_TASK.md" --exports-dir "$(ORCHESTRATOR_ROOT)/.task-state/exports"
PYTHON ?= $(MCP_PYTHON)

# --- Task / lane inference ---
_ACTIVE_TASK_CMD = $(shell $(MCP_CMD) $(MCP_STATE_ARGS) state 2>/dev/null | python3 -c 'import sys,json; data=json.load(sys.stdin); print(data.get("task_ref",""))' 2>/dev/null)
ACTIVE_TASK = $(eval ACTIVE_TASK := $(_ACTIVE_TASK_CMD))$(ACTIVE_TASK)
SUPPORTED_TASKS := $(shell $(LANE_CONFIG_CMD) list-tasks 2>/dev/null)
SOLE_TASK := $(if $(filter 1,$(words $(SUPPORTED_TASKS))),$(SUPPORTED_TASKS),)
REQUESTED_TASK := $(strip $(TASK))
REQUESTED_LANE := $(strip $(LANE))
INFERRED_TASK := $(shell $(LANE_CONFIG_CMD) infer-task --branch "$(CURRENT_BRANCH)" --worktree-path "$(WORKTREE_ROOT_REAL)" --orchestrator-root "$(ORCHESTRATOR_ROOT)" 2>/dev/null)
RESOLVED_TASK := $(strip $(shell $(LANE_CONFIG_CMD) resolve-task --explicit-task "$(REQUESTED_TASK)" --active-task "$(ACTIVE_TASK)" --sole-task "$(SOLE_TASK)" --branch "$(CURRENT_BRANCH)" --worktree-path "$(WORKTREE_ROOT_REAL)" --orchestrator-root "$(ORCHESTRATOR_ROOT)" $(if $(REQUESTED_LANE),--lane-id "$(REQUESTED_LANE)",) $(if $(filter 1,$(IN_ORCHESTRATOR_ROOT)),--in-orchestrator-root,) 2>/dev/null))
TASK ?= $(RESOLVED_TASK)
INFERRED_LANE := $(shell $(LANE_CONFIG_CMD) infer-lane --branch "$(CURRENT_BRANCH)" $(if $(TASK),--task-ref "$(TASK)",) 2>/dev/null)
LANE ?= $(INFERRED_LANE)
TASK_LANES := $(shell $(if $(TASK),$(LANE_CONFIG_CMD) list-lanes --task-ref "$(TASK)" 2>/dev/null,))
lane_field = $(shell $(if $(and $(TASK),$(LANE)),$(LANE_CONFIG_CMD) field --task-ref "$(TASK)" --lane-id "$(LANE)" --field $(1) $(if $(2),--orchestrator-root "$(ORCHESTRATOR_ROOT)",) 2>/dev/null,))
IN_LANE_WORKTREE := $(if $(and $(filter 0,$(IN_ORCHESTRATOR_ROOT)),$(LANE)),1,0)

# --- Override defaults ---
SESSION ?= $(TASK)-$(LANE)
SUMMARY ?= $(LANE) lane ready for orchestrator review.
MESSAGE ?=
SUBJECT ?= $(LANE) next assignment
STATUS ?= submitted
MERGE_READY ?= 1
DRY_RUN ?= 0
OVERWRITE ?= 0
SKIP_TESTS ?= 0
COMMIT_MSG ?=
REF ?= $(CURRENT_BRANCH)
ENTER_SHELL ?= 1
CODEX_ARGS ?=
CODEX_BIN ?= $(shell command -v codex 2>/dev/null || true)
BACKEND ?= codex-cli
TASK_PLAN ?=
LANE_IDS ?=

# --- Tooling paths (used by lane-commit, lane-clean, lane-refresh) ---
LANE_WORKTREE_TARGET = $(if $(filter 1,$(IN_ORCHESTRATOR_ROOT)),$(LANE_WORKTREE),$(WORKTREE_ROOT_REAL))
LANE_TOOLING_PATHS := Makefile mk docs/agentic/instructions.md docs/agentic/templates/WORKTREE_LANE_BRIEF.template.md docs/agentic/templates/WORKTREE_LANE_REPORT.template.md scripts/README.md scripts/worktree-lane
ROOT_REFRESH_PATHS := $(LANE_TOOLING_PATHS) config/lane-orchestration
LANE_APP_TOOLING_PATHS :=

export ORCHESTRATOR_ROOT TASK LANE SESSION SUMMARY MESSAGE SUBJECT STATUS MERGE_READY DRY_RUN LANE_WORKTREE LANE_TEST_CMD_1 LANE_TEST_CMD_2

# --- Lane config (resolved from manifest) ---
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
LANE_BRANCH := $(call lane_field,branch)
LANE_WORKTREE := $(call lane_field,worktree_path,1)
LANE_TITLE := $(call lane_field,title)
LANE_OBJECTIVE := $(call lane_field,objective)
LANE_OWNED_ARGS := $(call lane_field,owned_args)
LANE_DOC_ARGS := $(call lane_field,doc_args)
LANE_TEST_ARGS := $(call lane_field,test_args)
LANE_TEST_CMD_1 := $(call lane_field,test_command_1)
LANE_TEST_CMD_2 := $(call lane_field,test_command_2)
LANE_NON_GOAL_ARGS := $(call lane_field,non_goal_args)
LANE_COMMIT_PATHS := $(call lane_field,commit_paths)
LANE_COMMIT_SUBJECT := $(call lane_field,commit_subject)
LANE_DONE_DEFINITION := $(or $(call lane_field,done_definition),$(LANE_DONE_DEFINITION))
LANE_APP_TOOLING_PATHS := $(call lane_field,tooling_paths)

# =============================================================================
# Included modules
# =============================================================================

include $(ROOT_MAKEFILE_DIR)/mk/handoff.mk
include $(ROOT_MAKEFILE_DIR)/mk/lane-guards.mk
include $(ROOT_MAKEFILE_DIR)/mk/lane-lifecycle.mk
include $(ROOT_MAKEFILE_DIR)/mk/lane-worker.mk
include $(ROOT_MAKEFILE_DIR)/mk/lane-maintenance.mk

# =============================================================================
# Root targets
# =============================================================================

.PHONY: help check-all check-frontend lint-all test-all test-handoff clean-all reset-local fix-php-style mcp mcp-start gemini-cli-setup dev dev-stop ace-metrics ace-metrics-json ace-reflect ace-curation-report ace-trends

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
	@echo "  make test-handoff - Run agent-handoff-mcp tests"
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
	@echo "  make list-tasks"
	@echo "    List available lane-orchestration task manifests."
	@echo "  make handoff-close-check    - Enforce close-readiness on active handoff task"
	@echo "  make handoff-integrity-check - Run parser/lifecycle/sync guard checks"
	@echo "  make handoff-dispatch TASK=<task-ref> [DRY_RUN=1]"
	@echo "    Route open handoff review findings, blockers, and next actions from the orchestrator root to the correct worker lanes."
	@echo "  make handoff-inbox TASK=<task-ref> [LANE=<lane>]"
	@echo "    Poll open worker-to-orchestrator handoff messages and the latest worker reports from root."
	@echo "  make review-dispatch TASK=<task-ref> [DRY_RUN=1]"
	@echo "    Backward-compatible alias for handoff-dispatch."
	@echo ""
	@echo "Worktree Lanes (task-aware wrappers around scripts/worktree-lane):"
	@echo "  make lane-list"
	@echo "    List all registered worktree lanes and their status."
	@echo "  make lane-manifest-init TASK=<task-ref> LANE_IDS='lane-a lane-b' [TASK_PLAN=docs/tasks/...md]"
	@echo "    Generate a reusable config/lane-orchestration/<task-ref>.json scaffold for any task, then fill in owned paths/tests."
	@echo "  make lane-open TASK=<task-ref> LANE=<lane>"
	@echo "    Adds the lane brief, fails fast if an existing worktree is on the wrong branch, polls the inbox, and opens a subshell in the lane by default. Set ENTER_SHELL=0 to stay in root."
	@echo "  make lane-status TASK=<task-ref> LANE=<lane>"
	@echo "  make lane-inbox TASK=<task-ref> LANE=<lane>"
	@echo "    Worker default: poll open dispatch messages, latest handoff, and lane activity from shared MCP state."
	@echo "  make lane-prompt TASK=<task-ref> LANE=<lane>"
	@echo "    Render a concise worker prompt from the current lane inbox."
	@echo "  make lane-check"
	@echo "    Worker default: run the lane's configured test commands in the current worktree and record results into MCP. Use before lane-handoff."
	@echo "  make lane-run TASK=<task-ref> LANE=<lane> [CODEX_ARGS='...']"
	@echo "    Launch a fresh codex exec in the lane worktree using the generated lane prompt."
	@echo "  make worker-daemon-status"
	@echo "    Show the shared-root lock path, PID/process state, and latest worker log event for the current lane."
	@echo "  make worker-daemon-stop [FORCE=1]"
	@echo "    Stop the current lane worker daemon without manually finding PIDs."
	@echo "  make worker-daemon-resume"
	@echo "    Resume a stopped/suspended lane worker daemon with SIGCONT."
	@echo "  make worker-daemon-tail"
	@echo "    Tail the current lane worker daemon JSONL log."
	@echo "  make lane-dispatch TASK=<task-ref> LANE=<lane> MESSAGE=\"...\""
	@echo "    Orchestrator default: set/update the lane to active and send an open orchestrator->worker assignment message."
	@echo "  make lane-report TASK=<task-ref> LANE=<lane>"
	@echo "    Optional overrides: SESSION=<name> SUMMARY=\"...\" MERGE_READY=0 MESSAGE=\"...\""
	@echo "  make lane-commit [COMMIT_MSG='describe this change']"
	@echo "    Worker default commit step: stage lane-owned paths and create a commit like '<lane>: <subject>'. Override subject with COMMIT_MSG."
	@echo "  make lane-handoff"
	@echo "    Worker default: verify scope, commit lane-owned changes, show lane status, then submit a merge-ready lane report from lane commits."
	@echo "  make lane-reset TASK=<task-ref> LANE=<lane> [REF=$(CURRENT_BRANCH)]"
	@echo "  make lane-refresh TASK=<task-ref> LANE=<lane>"
	@echo "    Refresh a worker lane from the orchestrator branch using reset/rebase and optional auto-stash."
	@echo "  make lane-clean TASK=<task-ref> LANE=<lane>"
	@echo "    Remove copied tooling drift from a worker lane without touching lane-owned product files."
	@echo "  make lane-path TASK=<task-ref> LANE=<lane>"
	@echo "  make lane-commits TASK=<task-ref> LANE=<lane>"
	@echo "  make lane-intake TASK=<task-ref> LANE=<lane> [DRY_RUN=1] [SKIP_TESTS=1]"
	@echo "    Prints the latest merge-ready lane report, cherry-picks into a scratch worktree, runs lane-local verification there, and only fast-forwards root if clean."
	@echo "    Use SKIP_TESTS=1 to bypass scratch-worktree test commands (e.g. when deps are not installable in the scratch checkout)."
	@echo "  make orchestrator-daemon [TASK=<task-ref>] [BACKEND=codex-cli|codex-subagent]"
	@echo "    Shared singleton orchestrator loop rooted at $(ORCHESTRATOR_ROOT). Start it from any worktree; pause/resume/status use the same shared root state."
	@echo "  Supported task manifests: $(SUPPORTED_TASKS)"
	@echo "  Enumerated lanes for $(if $(TASK),$(TASK),the active task): $(TASK_LANES)"

# =============================================================================
# Cross-Repo Checks
# =============================================================================

# Run all checks across the monorepo, or lane-scoped verification inside a lane worktree.
check-all:
	@set -eu; \
	if [ "$(IN_LANE_WORKTREE)" = "1" ]; then \
		echo "Lane worktree detected ($(LANE)); running only the checks configured for this lane."; \
		$(MAKE) lane-check TASK="$(TASK)" LANE="$(LANE)"; \
		echo ""; \
		echo "✅ Lane-scoped checks passed for $(LANE)!"; \
	else \
		$(MAKE) lint-all; \
		$(MAKE) test-all; \
		echo ""; \
		echo "✅ All monorepo checks passed!"; \
	fi

check-frontend:
	@set -eu; \
	if [ "$(IN_LANE_WORKTREE)" = "1" ] && [ "$(LANE)" != "frontend" ]; then \
		echo "Lane $(LANE) does not own frontend checks; nothing to run."; \
		exit 0; \
	fi
	@echo "=== Frontend checks (WordPress plugin) ==="
	@cd apps/prototype-wp-alt-context && make check
	@echo ""
	@echo "✅ Frontend checks passed!"

# Lint all apps, or lane-scoped verification inside a lane worktree.
lint-all:
	@set -eu; \
	if [ "$(IN_LANE_WORKTREE)" = "1" ]; then \
		echo "Lane worktree detected ($(LANE)); suppressing monorepo-wide lint targets."; \
		echo "Running lane-scoped verification commands instead."; \
		$(MAKE) lane-check TASK="$(TASK)" LANE="$(LANE)"; \
		echo ""; \
		echo "✅ Lane-scoped verification passed for $(LANE)!"; \
	else \
		echo "=== Linting Python (backend) ==="; \
		( cd apps/prototype-description-service && make lint ); \
		echo ""; \
		echo "=== Linting TypeScript (frontend) ==="; \
		( cd apps/prototype-wp-alt-context && make lint ); \
		echo ""; \
		echo "=== Linting PHP (plugin) ==="; \
		( cd apps/prototype-wp-alt-context && composer cs-check ); \
		echo ""; \
		echo "✅ Linting complete"; \
	fi

# Test all apps, or lane-scoped verification inside a lane worktree.
test-all:
	@set -eu; \
	if [ "$(IN_LANE_WORKTREE)" = "1" ]; then \
		echo "Lane worktree detected ($(LANE)); suppressing monorepo-wide test targets."; \
		echo "Running lane-scoped verification commands instead."; \
		$(MAKE) lane-check TASK="$(TASK)" LANE="$(LANE)"; \
		echo ""; \
		echo "✅ Lane-scoped verification passed for $(LANE)!"; \
	else \
		echo "=== Testing Python (backend) ==="; \
		( cd apps/prototype-description-service && make test ); \
		echo ""; \
		echo "=== Testing TypeScript (frontend) ==="; \
		( cd apps/prototype-wp-alt-context && make test ); \
		echo ""; \
		echo "=== Testing Agent Handoff MCP ==="; \
		$(MAKE) test-handoff; \
		echo ""; \
		echo "✅ Tests complete"; \
	fi

# Test the handoff/MCP package from the monorepo root.
test-handoff:
	@set -eu; \
	if [ "$(IN_LANE_WORKTREE)" = "1" ]; then \
		echo "Lane worktree detected ($(LANE)); agent-handoff-mcp tests are orchestrator-root tooling tests, so they are skipped here."; \
		exit 0; \
	fi; \
	PYTHONPATH="$(MCP_PYTHONPATH)" \
	$(PYTHON) -m pytest packages/agent-handoff-mcp/tests -q

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
	@echo "Registering agent-handoff-mcp (via mcp-server.sh) with gemini-cli..."
	@gemini mcp add context-alt-text-handoff "$(shell pwd)/scripts/mcp/mcp-server.sh" run
	@echo "✓ MCP server 'context-alt-text-handoff' registered with gemini-cli"
	@echo "💡 Tip: Store your API key in a .env file at the monorepo root to keep it out of your .zshrc."

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

# =============================================================================
# ACE Observability
# =============================================================================

# Print a markdown metrics snapshot for the current task.
# Usage: make ace-metrics TASK=<task-ref>
ace-metrics:
	@PYTHONPATH="$(MCP_PYTHONPATH)" $(MCP_PYTHON) -m agent_handoff_mcp.orchestration.ace_metrics \
		--task-ref "$(TASK)" \
		--state-dir .task-state \
		--logs-dir logs \
		--output-format markdown

# Print a JSON metrics snapshot (also appends to .task-state/metrics.jsonl).
# Usage: make ace-metrics-json TASK=<task-ref>
ace-metrics-json:
	@PYTHONPATH="$(MCP_PYTHONPATH)" $(MCP_PYTHON) -m agent_handoff_mcp.orchestration.ace_metrics \
		--task-ref "$(TASK)" \
		--state-dir .task-state \
		--logs-dir logs \
		--output-format json

# Apply pending ACE counter updates from ace_reflect_log.jsonl to instruction files.
# Must be run from the orchestrator root; never from daemon or worker context.
# Usage: make ace-reflect TASK=<task-ref>
ace-reflect:
	@PYTHONPATH="$(MCP_PYTHONPATH)" $(MCP_PYTHON) -m agent_handoff_mcp.orchestration.ace_reflect \
		--task-ref "$(TASK)" \
		--state-dir .task-state \
		--instruction-files docs/agentic/instructions.md

# Show pruning candidates across instruction files.
# Usage: make ace-curation-report
ace-curation-report:
	@PYTHONPATH="$(MCP_PYTHONPATH)" $(MCP_PYTHON) -m agent_handoff_mcp.orchestration.ace_reflect \
		--task-ref "$(TASK)" \
		--state-dir .task-state \
		--instruction-files docs/agentic/instructions.md \
		--curation-report-only

# Print time-series sparklines from accumulated metrics history.
# Usage: make ace-trends TASK=<task-ref>
ace-trends:
	@PYTHONPATH="$(MCP_PYTHONPATH)" $(MCP_PYTHON) -m agent_handoff_mcp.orchestration.ace_metrics \
		--task-ref "$(TASK)" \
		--state-dir .task-state \
		--sparklines
