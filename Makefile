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
MCP_RUNTIME_ENV = env PYENV_VERSION="$(MCP_PYENV_VERSION)"
ORCHESTRATION_DIR := $(ORCHESTRATOR_ROOT)/packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/orchestration
WORKTREE_ORCHESTRATION_DIR := $(WORKTREE_ROOT_REAL)/packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/orchestration
LANE_CONFIG_CMD = $(MCP_PYTHON) "$(ORCHESTRATION_DIR)/lane_config.py"
MCP_PYTHONPATH := $(ORCHESTRATOR_ROOT)/packages/agent-orchestrator-mcp/src:$(ORCHESTRATOR_ROOT)/packages/codex-subagent-bridge/src$(if $(PYTHONPATH),:$(PYTHONPATH),)
WORKTREE_MCP_PYTHONPATH := $(WORKTREE_ROOT_REAL)/packages/agent-orchestrator-mcp/src:$(WORKTREE_ROOT_REAL)/packages/codex-subagent-bridge/src$(if $(PYTHONPATH),:$(PYTHONPATH),)
MCP_CMD = $(MCP_RUNTIME_ENV) agent-handoff-mcp
MCP_STATE_ARGS = --workspace-root "$(ORCHESTRATOR_ROOT)" --state-dir "$(ORCHESTRATOR_ROOT)/.task-state" --current-task-path "$(ORCHESTRATOR_ROOT)/CURRENT_TASK.md" --exports-dir "$(ORCHESTRATOR_ROOT)/.task-state/exports"
PYTHON ?= $(MCP_PYTHON)
ORCHESTRATOR_SRC := packages/agent-orchestrator-mcp/src
ORCHESTRATOR_TESTS := packages/agent-orchestrator-mcp/tests

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
include $(ROOT_MAKEFILE_DIR)/mk/orchestrator.mk
include $(ROOT_MAKEFILE_DIR)/mk/lane-guards.mk
include $(ROOT_MAKEFILE_DIR)/mk/lane-lifecycle.mk
include $(ROOT_MAKEFILE_DIR)/mk/lane-worker.mk
include $(ROOT_MAKEFILE_DIR)/mk/lane-maintenance.mk

# =============================================================================
# Root targets
# =============================================================================

.PHONY: help check-all check-frontend check-mcp check-handoff check-orchestrator lint-all lint-handoff lint-orchestrator fix-lint-handoff fix-lint-orchestrator fix-lint-mcp format-handoff format-orchestrator mypy-handoff mypy-orchestrator test-all test-handoff test-orchestrator clean-all reset-local fix-php-style mcp mcp-start gemini-cli-setup dev dev-stop ace-metrics ace-metrics-json ace-reflect ace-curation-report ace-trends context task-start task-finish

# Default target
help:
	@echo "Context Alt Text Monorepo Commands"
	@echo "==================================="
	@echo ""
	@echo "Cross-Repo Operations:"
	@echo "  make check-all    - Run all checks (lint + types + tests)"
	@echo "  make check-frontend - Run frontend checks (lint + types + arch + tests)"
	@echo "  make check-mcp    - Run lint, mypy, and tests for the monorepo MCP consumer package"
	@echo "  make check-orchestrator - Run lint, mypy, and tests for agent-orchestrator-mcp"
	@echo "  make lint-all     - Run linters for all apps"
	@echo "  make lint-orchestrator - Run Ruff for agent-orchestrator-mcp"
	@echo "  make format-orchestrator - Format agent-orchestrator-mcp with Ruff"
	@echo "  make mypy-orchestrator - Run mypy for agent-orchestrator-mcp"
	@echo "  make fix-php-style - Auto-fix WordPress plugin PHPCS violations (manual)"
	@echo "  make test-all     - Run tests for all apps"
	@echo "  make test-orchestrator - Run agent-orchestrator-mcp tests"
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
	@echo "  make review-ready [TASK=<task-ref>] [REVIEW_BASE=$(ORCHESTRATOR_BRANCH)]"
	@echo "    Summarize pre-review readiness from handoff findings/blockers, CURRENT_TASK sync, test evidence, and contract co-change."
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
	@echo "  make lane-intake TASK=<task-ref> LANE=<lane> [DRY_RUN=1] [SKIP_TESTS=1] [SKIP_POST_INTAKE=1] [POST_INTAKE_CHECK_CMD='...']"
	@echo "    Prints the latest merge-ready lane report, cherry-picks into a scratch worktree, runs lane-local verification there, fast-forwards root if clean, verifies CURRENT_TASK.md sync with agent-handoff-mcp handoff-close-check, then runs cross-lane post-intake verification from the orchestrator root."
	@echo "    Use SKIP_TESTS=1 to bypass scratch-worktree test commands, SKIP_POST_INTAKE=1 to skip the cross-lane gate, or POST_INTAKE_CHECK_CMD to override the default post-intake check command."
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
			$(MAKE) lint-task-plans; \
			$(MAKE) lint-scripts; \
			$(MAKE) mypy-orchestrator; \
			$(MAKE) test-all; \
			echo ""; \
			echo "✅ All monorepo checks passed!"; \
		fi

check-mcp: check-orchestrator
	@echo "✅ MCP consumer checks passed!"

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
			echo "=== Linting Agent Orchestrator MCP ==="; \
			$(MAKE) lint-orchestrator; \
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
			echo "=== Testing Agent Orchestrator MCP ==="; \
			$(MAKE) test-orchestrator; \
			echo ""; \
			echo "=== Testing TypeScript (frontend) ==="; \
			( cd apps/prototype-wp-alt-context && make test ); \
			echo ""; \
			echo "✅ Tests complete"; \
		fi

# Test the handoff/MCP package from the monorepo root.
test-handoff:
	@echo "agent-handoff-mcp is now verified in its standalone repository."
	@echo "Run the handoff test suite from darce/mcp-agent-handoff instead of this monorepo."
	@exit 1

test-orchestrator:
	@set -eu; \
	if [ "$(IN_LANE_WORKTREE)" = "1" ]; then \
		echo "Lane worktree detected ($(LANE)); agent-orchestrator-mcp tests are orchestrator-root tooling tests, so they are skipped here."; \
		exit 0; \
	fi; \
	PYTHONPATH="$(MCP_PYTHONPATH)" \
	$(PYTHON) -m pytest $(ORCHESTRATOR_TESTS) -q

lint-handoff:
	@echo "agent-handoff-mcp lint now runs in the standalone repository."
	@echo "Run lint from darce/mcp-agent-handoff instead of this monorepo."
	@exit 1

lint-orchestrator:
	@PYTHONPATH="$(MCP_PYTHONPATH)" \
	$(PYTHON) -m ruff check $(ORCHESTRATOR_SRC) $(ORCHESTRATOR_TESTS)

fix-lint-handoff:
	@echo "agent-handoff-mcp lint fixes now run in the standalone repository."
	@echo "Run fix-lint from darce/mcp-agent-handoff instead of this monorepo."
	@exit 1

fix-lint-orchestrator:
	@PYTHONPATH="$(MCP_PYTHONPATH)" \
	$(PYTHON) -m ruff check --fix $(ORCHESTRATOR_SRC) $(ORCHESTRATOR_TESTS)

fix-lint-mcp: fix-lint-orchestrator

# Sweep every tracked task-plan / epic markdown for pasted review-finding
# lists. Review findings live in agent-handoff-mcp; pasting them inline
# duplicates the source of truth and bypasses the pre-merge gate. --scan-repo
# enumerates `git ls-files '*.md'` and applies the same path scope used by
# the Claude Code PreToolUse hook, so CI catches drift in any file the hook
# would block — not just a hard-coded subset of directories (AHMCP-14-BR-03).
# Wired into `make check-all` so CI catches drift even if the PreToolUse
# hooks are bypassed locally.
lint-task-plans:
	@python3 scripts/hooks/guard-task-plan-findings.py --scan-repo

# AHMCP-20 / Layer 3 of the heredoc-eradication bug class fix.
# Walks scripts/**/*.sh and fails on any multi-line `python -c '...'`
# heredoc — the AHMCP-17 apostrophe-in-heredoc bug class. Promotes
# inline Python to standalone files via scripts/_my_inline.py instead.
# See scripts/_task_start_inline.py and scripts/_task_finish_inline.py
# for the canonical pattern.
lint-scripts:
	@python3 scripts/hooks/lint-no-inline-python-heredoc.py
	@python3 scripts/hooks/lint-expected-revision.py

format-handoff:
	@echo "agent-handoff-mcp formatting now runs in the standalone repository."
	@echo "Run format from darce/mcp-agent-handoff instead of this monorepo."
	@exit 1

format-orchestrator:
	@PYTHONPATH="$(MCP_PYTHONPATH)" \
	$(PYTHON) -m ruff format $(ORCHESTRATOR_SRC) $(ORCHESTRATOR_TESTS)

mypy-handoff:
	@echo "agent-handoff-mcp type checking now runs in the standalone repository."
	@echo "Run mypy from darce/mcp-agent-handoff instead of this monorepo."
	@exit 1

mypy-orchestrator:
	@MYPYPATH="$(ORCHESTRATOR_ROOT)/packages/agent-orchestrator-mcp/src:$(ORCHESTRATOR_ROOT)/packages/codex-subagent-bridge/src" \
	PYTHONPATH="$(MCP_PYTHONPATH)" \
	$(PYTHON) -m mypy --ignore-missing-imports $(ORCHESTRATOR_SRC)

check-handoff:
	@echo "agent-handoff-mcp is no longer checked from this monorepo."
	@echo "Run checks from darce/mcp-agent-handoff instead."
	@exit 1

check-orchestrator: lint-orchestrator mypy-orchestrator test-orchestrator
	@echo "✅ agent-orchestrator-mcp checks passed!"

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
	@PYTHONPATH="$(MCP_PYTHONPATH)" $(MCP_PYTHON) -m agent_orchestrator_mcp.orchestration.ace_metrics \
		--task-ref "$(TASK)" \
		--state-dir .task-state \
		--logs-dir logs \
		--output-format markdown

# Print a JSON metrics snapshot (also appends to .task-state/metrics.jsonl).
# Usage: make ace-metrics-json TASK=<task-ref>
ace-metrics-json:
	@PYTHONPATH="$(MCP_PYTHONPATH)" $(MCP_PYTHON) -m agent_orchestrator_mcp.orchestration.ace_metrics \
		--task-ref "$(TASK)" \
		--state-dir .task-state \
		--logs-dir logs \
		--output-format json

# Apply pending ACE counter updates from ace_reflect_log.jsonl to instruction files.
# ACE is project-local (scripts/ace/), not part of any MCP package.
# Usage: make ace-reflect
ace-reflect:
	@$(MCP_PYTHON) scripts/ace/ace_reflect.py \
		--state-dir .task-state \
		--instruction-files docs/agentic/instructions.md

# Show pruning candidates across instruction files.
# Usage: make ace-curation-report
ace-curation-report:
	@$(MCP_PYTHON) scripts/ace/ace_reflect.py \
		--state-dir .task-state \
		--instruction-files docs/agentic/instructions.md \
		--curation-report-only

# Print time-series sparklines from accumulated metrics history.
# Usage: make ace-trends TASK=<task-ref>
ace-trends:
	@PYTHONPATH="$(MCP_PYTHONPATH)" $(MCP_PYTHON) -m agent_orchestrator_mcp.orchestration.ace_metrics \
		--task-ref "$(TASK)" \
		--state-dir .task-state \
		--sparklines

# =============================================================================
# Lane / worktree context discipline (E15-LANE-ORCH slice 2)
# =============================================================================

# Verify the current shell is aligned with the active task's target_branch and
# target_worktree_path. Exits 0 when aligned, 2 on drift, 1 on infra error.
# Run at the start of every session before recording any handoff state.
# Usage: make context
context:
	@PYTHONPATH="$(MCP_PYTHONPATH)" $(MCP_PYTHON) scripts/check-task-context.py

# Convenience wrapper that scaffolds a feature branch + worktree + MCP task in
# one go. Computes the canonical path /Users/.../context-alt-text-monorepo-<task>
# and registers it as target_worktree_path on the active handoff state.
# Usage: make task-start TASK=<task-id> [OBJECTIVE="..."]
task-start:
	@./scripts/task-start.sh "$(TASK)" "$(OBJECTIVE)"

# Run handoff_close_check, return root to main, remove the worktree, and
# delete the merged feature branch in a single call. Run after the merge train
# has landed the task on main.
# Usage: make task-finish TASK=<task-id>
task-finish:
	@./scripts/task-finish.sh "$(TASK)"

# Start the integrity-watcher daemon (AHMCP-19 / item I from the AHMCP-18
# tech-debt assessment). Wraps fswatch (or inotifywait on Linux) over the
# protected source dirs and records every write event with PID/lsof
# attribution to .task-state/integrity-watcher.jsonl. Run in the
# foreground; Ctrl+C exits cleanly with a daemon_stop event.
#
# Pair with `make context` and `make task-finish` integrity guards: the
# guards detect drift, the watcher names the responsible PID.
#
# Usage:
#   make integrity-watch                    # watch the default paths
#   make integrity-watch ARGS="path1 path2" # watch explicit paths
integrity-watch:
	@./scripts/integrity-watcher.sh $(ARGS)
