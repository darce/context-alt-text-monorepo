# =============================================================================
# AltContext Monorepo - Root Makefile
# =============================================================================
#
# This Makefile provides commands for monorepo-wide operations.
# For app-specific commands, use the Makefile in each app directory.
#
# Quick Start:
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

# Scorer 0/1/2/3 contract shared with scripts/eval_exit_contract.py.
# GNU Make still collapses every failed recipe to process exit 2.
include $(ROOT_MAKEFILE_DIR)/scripts/eval_exit_contract.env

# --- Git / Orchestrator detection ---
WORKTREE_ROOT := $(shell git rev-parse --show-toplevel 2>/dev/null)
CURRENT_BRANCH := $(shell git -C "$(WORKTREE_ROOT)" rev-parse --abbrev-ref HEAD 2>/dev/null)
WORKTREE_ROOT_REAL := $(abspath $(WORKTREE_ROOT))
_GIT_COMMON_DIR := $(shell git rev-parse --git-common-dir 2>/dev/null)
ORCHESTRATOR_ROOT := $(if $(filter .git,$(_GIT_COMMON_DIR)),$(WORKTREE_ROOT_REAL),$(patsubst %/.git,%,$(_GIT_COMMON_DIR)))
ORCHESTRATOR_BRANCH := $(shell git -C "$(ORCHESTRATOR_ROOT)" rev-parse --abbrev-ref HEAD 2>/dev/null)
IN_ORCHESTRATOR_ROOT := $(if $(filter $(WORKTREE_ROOT_REAL),$(ORCHESTRATOR_ROOT)),1,0)

# --- MCP runtime ---
UVX ?= uvx
MCP_HANDOFF_PACKAGE ?= mcp-workbay-handoff==0.2.0
MCP_ORCHESTRATOR_PACKAGE ?= mcp-workbay-orchestrator==0.2.0
MCP_PYTHON = $(UVX) --from "$(MCP_ORCHESTRATOR_PACKAGE)" python3
LANE_CONFIG_CMD = $(MCP_PYTHON) -m workbay_orchestrator_mcp.orchestration.lane_config
MCP_PYTHONPATH := $(ORCHESTRATOR_ROOT)/packages/codex-subagent-bridge/src$(if $(PYTHONPATH),:$(PYTHONPATH),)
WORKTREE_MCP_PYTHONPATH := $(WORKTREE_ROOT_REAL)/packages/codex-subagent-bridge/src$(if $(PYTHONPATH),:$(PYTHONPATH),)
MCP_CMD = $(UVX) "$(MCP_HANDOFF_PACKAGE)"
MCP_STATE_ARGS = --workspace-root "$(ORCHESTRATOR_ROOT)" --state-dir "$(ORCHESTRATOR_ROOT)/.task-state" --current-task-path "$(ORCHESTRATOR_ROOT)/CURRENT_TASK.json" --exports-dir "$(ORCHESTRATOR_ROOT)/.task-state/exports"
PYTHON ?= $(MCP_PYTHON)

# --- Task / lane inference ---
_ACTIVE_TASK_CMD = $(shell $(MCP_CMD) $(MCP_STATE_ARGS) state 2>/dev/null | python3 -c 'import sys,json; data=json.load(sys.stdin); print(data.get("task_ref",""))' 2>/dev/null)
ACTIVE_TASK = $(eval ACTIVE_TASK := $(_ACTIVE_TASK_CMD))$(ACTIVE_TASK)
_SUPPORTED_TASKS_CMD = $(shell $(LANE_CONFIG_CMD) list-tasks 2>/dev/null)
SUPPORTED_TASKS = $(eval SUPPORTED_TASKS := $(_SUPPORTED_TASKS_CMD))$(SUPPORTED_TASKS)
SOLE_TASK = $(if $(filter 1,$(words $(SUPPORTED_TASKS))),$(SUPPORTED_TASKS),)
REQUESTED_TASK := $(strip $(TASK))
REQUESTED_LANE := $(strip $(LANE))
_INFERRED_TASK_CMD = $(shell $(LANE_CONFIG_CMD) infer-task --branch "$(CURRENT_BRANCH)" --worktree-path "$(WORKTREE_ROOT_REAL)" --orchestrator-root "$(ORCHESTRATOR_ROOT)" 2>/dev/null)
INFERRED_TASK = $(eval INFERRED_TASK := $(_INFERRED_TASK_CMD))$(INFERRED_TASK)
_RESOLVED_TASK_CMD = $(strip $(shell $(LANE_CONFIG_CMD) resolve-task --explicit-task "$(REQUESTED_TASK)" --active-task "$(ACTIVE_TASK)" --sole-task "$(SOLE_TASK)" --branch "$(CURRENT_BRANCH)" --worktree-path "$(WORKTREE_ROOT_REAL)" --orchestrator-root "$(ORCHESTRATOR_ROOT)" $(if $(REQUESTED_LANE),--lane-id "$(REQUESTED_LANE)",) $(if $(filter 1,$(IN_ORCHESTRATOR_ROOT)),--in-orchestrator-root,) 2>/dev/null))
RESOLVED_TASK = $(eval RESOLVED_TASK := $(_RESOLVED_TASK_CMD))$(RESOLVED_TASK)
TASK ?= $(RESOLVED_TASK)
_INFERRED_LANE_CMD = $(shell $(LANE_CONFIG_CMD) infer-lane --branch "$(CURRENT_BRANCH)" $(if $(TASK),--task-ref "$(TASK)",) 2>/dev/null)
INFERRED_LANE = $(eval INFERRED_LANE := $(_INFERRED_LANE_CMD))$(INFERRED_LANE)
LANE ?= $(INFERRED_LANE)
_TASK_LANES_CMD = $(shell $(if $(TASK),$(LANE_CONFIG_CMD) list-lanes --task-ref "$(TASK)" 2>/dev/null,))
TASK_LANES = $(eval TASK_LANES := $(_TASK_LANES_CMD))$(TASK_LANES)
lane_field = $(shell $(if $(and $(TASK),$(LANE)),$(LANE_CONFIG_CMD) field --task-ref "$(TASK)" --lane-id "$(LANE)" --field $(1) $(if $(2),--orchestrator-root "$(ORCHESTRATOR_ROOT)",) 2>/dev/null,))
IN_LANE_WORKTREE = $(if $(and $(filter 0,$(IN_ORCHESTRATOR_ROOT)),$(LANE)),1,0)

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
LANE_TOOLING_PATHS := Makefile mk docs/workbay/instructions.md docs/workbay/templates/WORKTREE_LANE_BRIEF.template.md docs/workbay/templates/WORKTREE_LANE_REPORT.template.md scripts/README.md scripts/worktree-lane
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
include $(ROOT_MAKEFILE_DIR)/mk/deploy.mk
include $(ROOT_MAKEFILE_DIR)/mk/logs.mk

# =============================================================================
# Root targets
# =============================================================================

.PHONY: help check-all check-frontend check-mcp check-handoff check-orchestrator lint-all lint-handoff lint-orchestrator fix-lint-handoff fix-lint-orchestrator fix-lint-mcp format format-all format-handoff format-orchestrator mypy-handoff mypy-orchestrator test-all test-handoff test-orchestrator clean-all reset-local fix-php-style mcp mcp-start gemini-cli-setup dev dev-stop ace-metrics ace-metrics-json ace-reflect ace-curation-report ace-trends worktree-audit worktree-prune task-plan-audit check-codex-command-router check-skills check-harness-sync check-mcp-pins lint-hoisted-paths maint-start check-main-clean install-git-hooks localwp-mirror-integrity localwp-e2e-install localwp-e2e-auth localwp-e2e-smoke localwp-evidence localwp-a11y-smoke check-overrides-digest test-overrides-digest test-scripts test-vm-scripts mutation-guard-license-policy test-hooks test-deploy-contract test-gpu-spike-bench test-infra-terraform test-vlm3 test-gpu-lifecycle test-gpu-snapshot-checker check-gpu-snapshots check-gpu-snapshots-live provision-customer provision-demo expire-demo

# Offline half of the GPU snapshot deployment contract. This validates the
# lifecycle-unit paths against the checked-in rendered compose file without
# requiring live snapshot files or SSH, so it is safe for check-all/CI.
check-gpu-snapshots:
	@ACX_GPU_SNAPSHOT_CONFIG_ONLY=1 \
		bash "$(ROOT_MAKEFILE_DIR)/scripts/deploy/check-gpu-snapshots.sh"

# Live-host deployment gate. The checker reads /run/acx and the deployed
# compose contract on the OCI VM, so running it against a developer laptop is
# never meaningful. GPU_SNAPSHOT_ENV is deliberately mandatory and invalid
# values fail before SSH; inability to reach or inspect the host also fails.
check-gpu-snapshots-live:
	@if [ -z "$(GPU_SNAPSHOT_ENV)" ]; then \
		echo "check-gpu-snapshots-live: GPU_SNAPSHOT_ENV is required (dev|dev-fir|staging|prod)" >&2; \
		exit 2; \
	fi
	@case "$(GPU_SNAPSHOT_ENV)" in dev|dev-fir|staging|prod) ;; \
		*) echo "check-gpu-snapshots-live: invalid GPU_SNAPSHOT_ENV=$(GPU_SNAPSHOT_ENV)" >&2; exit 2 ;; \
	esac
	@host="$${OCI_HOST:-acx-backend.tail1a44b8.ts.net}"; user="$${OCI_USER:-ubuntu}"; \
		echo "==> Checking live GPU snapshots on $$user@$$host ($(GPU_SNAPSHOT_ENV))"; \
		ssh -l "$$user" -- "$$host" 'set -eu; \
			checker=$$(mktemp); \
			trap "rm -f $$checker" EXIT; \
			cat > "$$checker"; \
			sudo env ACX_DESCRIBE_LOAD_DIR=/run/acx-write \
				ACX_GPU_COMPOSE_FILE="/opt/acx-backend/$(GPU_SNAPSHOT_ENV)/docker-compose.env.yml" \
				ACX_GPU_SNAPSHOT_DIR=/run/acx \
				ACX_GPU_STATE_PATH=/run/acx/gpu-state.json \
				ACX_GPU_UNIT_LOAD_DIR=/run/acx-write \
				ACX_GPU_UNIT_STATE_PATH=/run/acx/gpu-state.json \
				bash "$$checker"' \
			< "$(ROOT_MAKEFILE_DIR)/scripts/deploy/check-gpu-snapshots.sh"

# Default target
help:
	@echo "Context Alt Text Monorepo Commands"
	@echo "==================================="
	@echo ""
	@echo "Cross-Repo Operations:"
	@echo "  make check-all        - Run all checks (lint + types + tests)"
	@echo "  make mutation-guard-license-policy - Opt-in remote-VM licence-policy mutation guard (~5h --mutation all)"
	@echo "  make format-all       - Fix lint + format across all apps and packages (run before check-all)"
	@echo "  make check-frontend   - Run frontend checks (lint + types + arch + tests)"
	@echo "  make lint-all         - Run linters for all apps and packages"
	@echo "  make test-all         - Run tests for all apps and packages"
	@echo "  make check-gpu-snapshots-live GPU_SNAPSHOT_ENV=dev - Verify live OCI snapshots (SSH required; never a laptop-local check)"
	@echo "  make fix-php-style    - Auto-fix WordPress plugin PHPCS violations"
	@echo "  make clean-all        - Clean cache files in all apps"
	@echo "  make reset-local      - Reset local backend DB + WordPress projection data (destructive)"
	@echo "  make provision-customer EMAIL=<e> [PLAN=pro] [LABEL=\"Name\"] [ENV=local] - Concierge mint real tenant+key (AP-7)"
	@echo "  make localwp-mirror-integrity - Run the WordPress mirror integrity check through the plugin app wrapper"
	@echo "  make localwp-e2e-install - Install Chromium for the LocalWP Playwright harness"
	@echo "  make localwp-e2e-auth - Bootstrap shared Playwright auth state against LocalWP"
	@echo "  make localwp-e2e-smoke - Run the LocalWP smoke Playwright project"
	@echo "  make localwp-evidence - Run the headed LocalWP evidence Playwright project"
	@echo "  make localwp-a11y-smoke - Run the LocalWP axe Playwright project"
	@echo ""
	@echo "App-Specific Commands:"
	@echo "  cd apps/prototype-description-service && make help"
	@echo "  cd apps/prototype-wp-alt-context && make help"
	@echo ""
	@echo "Handoff Integrity:"
	@echo "  make list-tasks"
	@echo "    List available lane-orchestration task manifests."
	@echo "  make handoff-close-check    - Enforce close-readiness on active handoff task"
	@echo "  make review-ready [TASK=<task-ref>] [REVIEW_BASE=$(ORCHESTRATOR_BRANCH)]"
	@echo "    Summarize pre-review readiness from handoff findings/blockers, CURRENT_TASK sync, test evidence, and contract co-change."
	@echo "  make handoff-integrity-check - Run parser/lifecycle/sync guard checks"
	@echo "  make worktree-audit"
	@echo "    Detect orphan local feature/codex branches with no active or archived handoff registration."
	@echo "  make worktree-prune"
	@echo "    Interactively prompt to delete orphan local feature/codex branches with git branch -d."
	@echo "    Add WORKTREE_PRUNE_ARGS=--dry-run to preview deletions without mutating git state."
	@echo "  make task-plan-audit"
	@echo "    Detect tagged main-branch task refs whose task-plan files are missing from docs/tasks surfaces."
	@echo "  make generate-agent-workflows"
	@echo "    Generate Claude, VS Code, and Codex workflow artifacts from config/agent-workflows/portable_commands.json."
	@echo "  make check-agent-workflows"
	@echo "    Fail if generated workflow artifacts drift from the canonical manifest."
	@echo "  make check-codex-command-router"
	@echo "    Fail if the marker-delimited Codex router blocks in docs drift from the manifest-rendered content."
	@echo "  make smoke-agent-workflows [BACKEND=claude|copilot|codex]"
	@echo "    Optional host-surface smoke check for /branch-review and /planning-review against the manifest contract."
	@echo "  make handoff-dispatch TASK=<task-ref> [DRY_RUN=1]"
	@echo "    Route open handoff review findings, blockers, and next actions from the orchestrator root to the correct worker lanes."
	@echo "  make handoff-inbox TASK=<task-ref> [LANE=<lane>]"
	@echo "    Poll open worker-to-orchestrator handoff messages and the latest worker reports from root."
	@echo "  make maint-start TASK=MAINT-<slug>-<YYYYMMDD> OBJECTIVE=\"...\""
	@echo "    Register a MAINT-* task on main/master for permitted ad-hoc docs/config work."
	@echo "  make review-dispatch TASK=<task-ref> [DRY_RUN=1]"
	@echo "    Backward-compatible alias for handoff-dispatch."
	@echo "  make plan-analyze DOC=<path>"
	@echo "    Agent-assisted planning triage entry point; prints the constitution + skill surfaces for the document."
	@echo "  make plan-review DOC=<path>"
	@echo "    Agent-assisted planning review entry point; prints the planning-review surfaces for the document."
	@echo "  make handoff-review-run TASK_REF=<task-ref> MODE=<branch|planning|release_audit> SUBJECT=<path-or-.> SUBJECT_KIND=<kind> VERDICT=<verdict> DECISION=<decision-id> SESSION=<session> RUN_ID=<run-id>"
	@echo "    Repo-local fallback for recording a review run via the Python API when the MCP review_runs tool is unavailable."
	@echo "  make slice-start TASK=<task-ref> TEST_CMD='...'"
	@echo "    Record the failing-test TDD gate before implementation begins."
	@echo "  make slice-commit TASK=<task-ref> MSG='...'"
	@echo "    Commit staged changes and record a slice-complete decision atomically."
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
	@echo "    Prints the latest merge-ready lane report, cherry-picks into a scratch worktree, runs lane-local verification there, fast-forwards root if clean, verifies CURRENT_TASK.json sync with mcp-workbay-handoff handoff-close-check, then runs cross-lane post-intake verification from the orchestrator root."
	@echo "    Use SKIP_TESTS=1 to bypass scratch-worktree test commands, SKIP_POST_INTAKE=1 to skip the cross-lane gate, or POST_INTAKE_CHECK_CMD to override the default post-intake check command."
	@echo "  make orchestrator-daemon [TASK=<task-ref>] [BACKEND=codex-cli|codex-subagent]"
	@echo "    Shared singleton orchestrator loop rooted at $(ORCHESTRATOR_ROOT). Start it from any worktree; pause/resume/status use the same shared root state."
	@echo "  Supported task manifests: $(SUPPORTED_TASKS)"
	@echo "  Enumerated lanes for $(if $(TASK),$(TASK),the active task): $(TASK_LANES)"

LOCALWP_PLAYWRIGHT_TASK_ENV = $(if $(ACX_PLAYWRIGHT_TASK_REF),ACX_PLAYWRIGHT_TASK_REF="$(ACX_PLAYWRIGHT_TASK_REF)",)

localwp-e2e-install:
	@cd apps/prototype-wp-alt-context && npm run e2e:install

localwp-e2e-auth:
	@cd apps/prototype-wp-alt-context && $(LOCALWP_PLAYWRIGHT_TASK_ENV) npm run e2e:auth

localwp-e2e-smoke:
	@cd apps/prototype-wp-alt-context && $(LOCALWP_PLAYWRIGHT_TASK_ENV) npm run e2e:localwp

localwp-evidence:
	@cd apps/prototype-wp-alt-context && $(LOCALWP_PLAYWRIGHT_TASK_ENV) npm run e2e:evidence

localwp-a11y-smoke:
	@cd apps/prototype-wp-alt-context && $(LOCALWP_PLAYWRIGHT_TASK_ENV) npm run a11y:localwp

# =============================================================================
# Cross-Repo Checks
# =============================================================================

# Run all checks across the monorepo, or lane-scoped verification inside a lane worktree.
check-all: check-gpu-snapshots
	@set -eu; \
	if [ "$(IN_LANE_WORKTREE)" = "1" ]; then \
		echo "Lane worktree detected ($(LANE)); running only the checks configured for this lane."; \
		$(MAKE) lane-check TASK="$(TASK)" LANE="$(LANE)"; \
		echo ""; \
		echo "✅ Lane-scoped checks passed for $(LANE)!"; \
		else \
			$(MAKE) lint-all; \
			$(MAKE) lint-task-plans; \
			$(MAKE) lint-dashboard-txt; \
			$(MAKE) lint-scripts; \
			$(MAKE) check-overrides-digest; \
			$(MAKE) check-skills; \
			$(MAKE) check-harness-sync; \
			$(MAKE) check-mcp-pins; \
			$(MAKE) lint-hoisted-paths; \
			$(MAKE) check-agent-workflows; \
			$(MAKE) check-codex-command-router; \
			$(MAKE) worktree-audit; \
			$(MAKE) task-plan-audit; \
			$(MAKE) test-scripts; \
			$(MAKE) test-all; \
			echo ""; \
			echo "✅ All monorepo checks passed!"; \
		fi

# Run the full monorepo check suite before merging a feature branch to main.
# Pairs with the external handoff-close-check evidence gate, which validates
# recorded test_result evidence but does NOT execute checks itself (see
# agentic-protocol-monorepo/docs/upstream-requests/2026-06-28-refactoring-lens-and-overlay-mechanism/REQUEST.md § E7).
# Run by habit before
# the close-check so the working tree is actually verified, not trusted.
pre-merge:
	@$(MAKE) check-all

# Offload gate suites to the remote test host (unprivileged, resource-capped
# gate user over Tailscale SSH). Host/dir/targets come from the operator-local
# .workbay/remote-gate.env (gitignored) or WORKBAY_REMOTE_GATE_* env vars —
# there is deliberately no baked-in host (fail-closed, exit 78 when unset).
# Only committed HEAD is gated. See docs/runbooks/remote-test-gate.md.
#   make check-remote                          # configured/default targets
#   make check-remote TARGETS="test lint"      # explicit target list
.PHONY: check-remote
check-remote:
	@bash scripts/remote_gate.sh run $(TARGETS)

# Guard: every editable current-pin reference to the workbay MCP packages must
# match the Makefile MCP_*_PACKAGE canonical. Frozen records (docs/adrs|specs|tasks)
# are exempt; overlay manifest + range/git+ssh forms surface as advisories.
check-mcp-pins:
	@python3 "$(WORKTREE_ROOT_REAL)/scripts/check_mcp_pins.py"

localwp-mirror-integrity:
	@$(MAKE) -C apps/prototype-wp-alt-context localwp-mirror-integrity \
		WP_PATH="$(WP_PATH)" \
		ATTACHMENT_ID="$(ATTACHMENT_ID)" \
		THRESHOLD="$(THRESHOLD)" \
		LIMIT="$(LIMIT)" \
		FORMAT="$(FORMAT)"

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
			echo "=== Linting Codex Subagent Bridge ==="; \
			$(MAKE) -C packages/codex-subagent-bridge lint-bridge; \
			echo ""; \
			echo "=== Linting TypeScript (frontend) ==="; \
			( cd apps/prototype-wp-alt-context && make lint ); \
			echo ""; \
			echo "=== Typechecking TypeScript (frontend) ==="; \
			( cd apps/prototype-wp-alt-context && make typecheck ); \
			echo ""; \
			echo "=== Checking frontend architecture ==="; \
			( cd apps/prototype-wp-alt-context && make arch ); \
			echo ""; \
		echo "=== Linting PHP (plugin) ==="; \
		$(MAKE) -C apps/prototype-wp-alt-context php-cs; \
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
			echo "=== Testing Python (backend fast) ==="; \
			( cd apps/prototype-description-service && make test ); \
			echo ""; \
			echo "=== Testing Python (backend integration) ==="; \
			( cd apps/prototype-description-service && make test-integration ); \
			echo ""; \
			echo "=== Testing TypeScript (frontend) ==="; \
			( cd apps/prototype-wp-alt-context && make test ); \
			echo ""; \
			echo "✅ Tests complete"; \
		fi

# Sweep every tracked task-plan / epic markdown for pasted review-finding
# lists. Review findings live in workbay-handoff-mcp; pasting them inline
# duplicates the source of truth and bypasses the pre-merge gate. --scan-repo
# enumerates `git ls-files '*.md'` and applies the same path scope used by
# the Claude Code PreToolUse hook, so CI catches drift in any file the hook
# would block — not just a hard-coded subset of directories (AHMCP-14-BR-03).
# Wired into `make check-all` so CI catches drift even if the PreToolUse
# hooks are bypassed locally.
lint-task-plans:
	@python3 scripts/hooks/guard-task-plan-findings.py --scan-repo

# E17-9 Slice 4 / E17-7 Slice 4 follow-up. Guard tracked files from
# reintroducing the obsolete dashboard markdown name after the rename
# to DASHBOARD.txt. Archived plans, test fixtures, test modules, the
# rename/drift task plans, and the .gitignore exclusion entry are
# excluded by the script's `is_excluded()` patterns.
lint-dashboard-txt:
	@python3 scripts/hooks/lint-dashboard-txt.py

# AHMCP-20 / Layer 3 of the heredoc-eradication bug class fix.
# Walks scripts/**/*.sh and fails on any multi-line `python -c '...'`
# heredoc — the AHMCP-17 apostrophe-in-heredoc bug class. Promotes
# inline Python to standalone files via scripts/_my_inline.py instead.
# See scripts/_task_start_inline.py and scripts/_task_finish_inline.py
# for the canonical pattern.
lint-scripts:
	@python3 scripts/hooks/lint-no-inline-python-heredoc.py
	@python3 scripts/hooks/lint-expected-revision.py
	@python3 scripts/check_published_head_sha.py
	@ruff check infra/oci scripts/gpu_burst_smoke.py scripts/gpu_spike_bench.py scripts/test_gpu_burst_smoke.py scripts/test_gpu_spike_bench.py
	@ruff format --check infra/oci scripts/gpu_burst_smoke.py scripts/gpu_spike_bench.py scripts/test_gpu_burst_smoke.py scripts/test_gpu_spike_bench.py

# MAINT-FB-B-05: validate every workbay-overrides/*/overrides.lock.json
# component upstream_digest against the materialized upstream base copy
# (whole-file sha256 of base_path, e.g. SKILL.base.md). The generated base
# surface under .workbay/generated/ injects Global Instructions and is
# deliberately not the digest subject (MAINT-FB-A-02 convention). Without
# this check, digest drift only surfaces on the next manual bootstrap update.
check-overrides-digest:
	@python3 scripts/check_overrides_lock_digest.py
	@$(MAKE) test-overrides-digest

# Single pytest invocation covering the union of the four narrow targets below
# (hooks, deploy-contract, vlm3, overrides-digest). check-all runs this once
# instead of four separate pytest processes — one interpreter + collection pass.
# The narrow targets keep their original scopes for standalone/documented use.
test-scripts:
	@status=0; \
	set -- \
		scripts/test_e15_31_admin_deploy_contract.py scripts/test_e15_33_deploy_convergence.py scripts/test_e15_33_boot_smoke.py \
		scripts/test_vlm3_oci_gpu_infra.py \
		scripts/test_vlm3_gpu_lifecycle.py \
		infra/oci/gpu_lifecycle/tests \
		scripts/deploy/tests \
		scripts/test_vlm3_owlv2_deferral.py \
		scripts/test_vlm3_gpu_bakeoff_artifacts.py \
		scripts/test_vlm3_decision_memo.py \
		scripts/test_check_overrides_lock_digest.py scripts/test_consumer_setup_doc.py \
		scripts/test_remote_gate_guards.py \
		scripts/train/occlusion/test_license_policy.py \
		scripts/train/occlusion/test_license_policy_hardening.py \
		scripts/train/occlusion/test_equivalence_claims.py \
		scripts/train/occlusion/test_mutation_guard_env.py \
		scripts/test_acx_backend_image_contract.py \
		scripts/test_gpu_burst_smoke.py scripts/test_gpu_spike_bench.py; \
	if [ -d scripts/hooks ] && [ -d .github/hooks ] && [ -d scripts/consumer-hooks/git ]; then \
		set -- scripts/hooks .github/hooks scripts/test_php_characterization_gate.py "$$@"; \
	fi; \
	python3 -m pytest "$$@" -q --tb=short --durations=25 || status=$$?; \
	bash scripts/deploy/tests/test-smoke-gate.sh || status=$$?; \
	bash scripts/deploy/tests/test-check-gpu-snapshots.sh || status=$$?; \
	$(MAKE) test-vm-scripts || status=$$?; \
	exit "$$status"

# VMDISK-1: the lane reaper is the VM's only disk reclaimer, and neither it nor
# its cron installer was reachable from any make target -- so its guards were
# never exercised while the disk climbed to 96%.
# Kept pytest-free and separate from test-scripts because the remote gate host's
# root .venv carries no pytest (only the description-service venv does), so a
# guard reachable only via test-scripts is still unreachable from the gate --
# the very failure mode above. This target is what check-remote runs.
test-vm-scripts:
	@bash scripts/vm/tests/test_reap_lane.sh
	@bash scripts/vm/tests/test_install_reap_cron.sh

# Permanent [TEST-15] discrimination guard for the licence/provenance gate.
# OPT-IN / REMOTE-VM ONLY. Not a prerequisite of test-scripts or check-all:
# laptop `make test-scripts` / `make check-all` must stay a fast self-checking
# suite (TEST-01). Standing rule: mutation testing is remote-VM only
# (CARD-09 / feedback-bounded-waiting). Measured wall clock on a 4-core VM:
#   ≈5 h  for  --mutation all
#   ≈12 min per single mutation
# The default remote-gate workdir is apps/prototype-description-service, so
# this root target never runs there. Invoke from the monorepo root on the
# remote VM (do not attach to REMOTE_GATE_TARGETS while workdir is the
# description service):
#   make mutation-guard-license-policy
# or override workdir to the repo root for that run only:
#   WORKBAY_REMOTE_GATE_WORKDIR=. make check-remote TARGETS="mutation-guard-license-policy"
#
# test-scripts above proves test_license_policy.py is green; this proves that
# green can go red. Its victim suite is test_license_policy.py only —
# test_license_policy_hardening.py is gated by test-scripts but kills no
# mutant, so coverage that lives only there is not discrimination evidence.
# Applies every entry in the MUTATIONS table to scratch copies of
# license_policy.py under a temp dir (the real tree is never written) and fails
# unless each required mutant is killed by its own named victim tests and the
# semantically inert CONTROL survives. Child pytest runs get a scrubbed
# allowlist env and verdicts come from junitxml on disk plus a
# baseline-executed-count invariant, so an injected plugin cannot forge kills.
#
# What it floors, precisely: the collected node-id set (may grow, must not
# shrink), the existence of the pinned victim names, and that each required
# mutant dies. What it does NOT floor: assertion strength inside a test body,
# skip marks, or fixture-data diversity — a test whose body is replaced by
# `pass` keeps its node id and still counts as executed. EXIT=0 means the suite
# still has its shape and its pins, not that the suite was not gutted.
mutation-guard-license-policy:
	@python3 scripts/train/occlusion/mutation_guard.py --mutation all

# Unit tests backing check-overrides-digest (incl. the committed-lock
# consistency regression guard). Also collected by test-scripts in check-all;
# kept narrow here so standalone check-overrides-digest stays test-backed.
test-overrides-digest:
	@python3 -m pytest scripts/test_check_overrides_lock_digest.py scripts/test_consumer_setup_doc.py -q --tb=short

# Run unit tests for scripts/hooks and .github/hooks.
# Addresses AHMCP-14-BR-02: hook tests were not reachable via package Makefiles.
test-hooks:
	@python3 -m pytest scripts/hooks .github/hooks scripts/test_php_characterization_gate.py -q --tb=short

# E15-31B: deploy-contract guard — prod deploys/systemd restarts must install
# and retain the /admin compose overlay. Covered by test-scripts in check-all.
test-deploy-contract:
	@python3 -m pytest scripts/test_e15_31_admin_deploy_contract.py scripts/test_e15_33_deploy_convergence.py scripts/test_e15_33_boot_smoke.py -q --tb=short
	@bash scripts/deploy/tests/test-smoke-gate.sh
	@bash scripts/deploy/tests/test-check-gpu-snapshots.sh

# GPUUX-1: narrow, gate-reachable slice of the GPU lifecycle suite. test-vlm3
# also covers infra/oci/gpu_lifecycle/tests, but it collects test_vlm3_oci_gpu_infra.py
# alongside them, and that module imports PyYAML -- absent from the remote gate
# host's system python -- so a collection error there takes the lifecycle tests
# down with it before a single one runs. This target imports stdlib + pytest only,
# so the state-snapshot writer/reader contract is provable on the gate.
#   WORKBAY_REMOTE_GATE_WORKDIR=. make check-remote TARGETS="test-gpu-lifecycle"
test-gpu-lifecycle:
	@python3 -m pytest infra/oci/gpu_lifecycle/tests -q --tb=short

# GPUUX-1: narrow, gate-reachable route to the deployment-checker shell suite.
# Both existing callers abort before reaching it on a fresh clone, for unrelated
# reasons: test-scripts dies on the gitignored scripts/hooks path, and
# test-deploy-contract dies on `import yaml` in
# scripts/test_e15_33_deploy_convergence.py. Verified on the remote gate at
# 15f74a60 -- both EXIT=2 with zero tests run -- so check-gpu-snapshots.sh and
# its guards are unverified on every runner that is not a developer laptop.
# This target is bash-only and has no Python dependency at all.
#   WORKBAY_REMOTE_GATE_WORKDIR=. make check-remote TARGETS="test-gpu-snapshot-checker"
test-gpu-snapshot-checker:
	@bash scripts/deploy/tests/test-check-gpu-snapshots.sh

test-gpu-spike-bench:
	@python3 -m pytest scripts/test_gpu_spike_bench.py -q --tb=short

test-infra-terraform:
	@terraform -chdir=infra/oci init -backend=false -input=false
	@terraform -chdir=infra/oci validate

# VLM-3 / VLMRP: OCI GPU infra posture, idle-reaper lifecycle, decision memo,
# bake-off artifact guards, and OWLv2 deferral. Covered by test-scripts in check-all.
test-vlm3:
	@python3 -m pytest \
		scripts/test_vlm3_oci_gpu_infra.py \
		scripts/test_vlm3_gpu_lifecycle.py \
		infra/oci/gpu_lifecycle/tests \
		scripts/test_vlm3_owlv2_deferral.py \
		scripts/test_vlm3_gpu_bakeoff_artifacts.py \
		scripts/test_vlm3_decision_memo.py \
		-q --tb=short

# E17-8 BR-16 / BR-22: on-demand scan for dirty protected paths on main.
# Mirrors what post-checkout / post-commit / post-merge / post-rewrite / pre-push run.
# Prints OK when clean on main; silent / exit 0 on non-protected branches.
check-main-clean:
	@python3 scripts/hooks/check_main_clean.py --trigger manual

# REFA-10: consumer hooksPath wraps overlay lifecycle hooks and adds the
# characterization merge-result gate on pre-push. Overlay scripts/hooks/git/*
# remain bootstrap-managed; consumer-hooks/git symlinks delegate to them.
# Idempotent: safe to re-run. Uninstall with `git config --unset core.hooksPath`.
install-git-hooks:
	@git config core.hooksPath scripts/consumer-hooks/git
	@for h in post-checkout post-commit post-merge post-rewrite pre-commit; do \
		ln -sfn ../../hooks/git/$$h scripts/consumer-hooks/git/$$h; \
	done
	@echo "git core.hooksPath -> scripts/consumer-hooks/git (overlay guards + consumer characterization gate)"
	@chmod +x scripts/consumer-hooks/run-php-characterization.sh scripts/consumer-hooks/git/pre-push
	@ls -1 scripts/consumer-hooks/git

# Apply deterministic lint fixes and formatting across every app and package.
# Run this before `make check-all` — many violations are auto-fixable and
# resolving them first keeps the check output signal-to-noise clean.
# Python: ruff check --fix --unsafe-fixes + ruff format
# TypeScript/JS: npm run lint:fix + npm run format:fix
# PHP: composer cs-fix
format-all:
	@echo "=== Formatting codex-subagent-bridge ==="
	@$(MAKE) -C packages/codex-subagent-bridge format-bridge
	@echo "=== Formatting description-service ==="
	@( cd apps/prototype-description-service && $(MAKE) format )
	@echo "=== Formatting WordPress plugin (TS/JS + PHP) ==="
	@( cd apps/prototype-wp-alt-context && $(MAKE) format )
	@echo "✅ All components formatted!"
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
# AP-7: concierge sell-and-provision fast-path.
# Mints a real (non-demo) tenant + API key via the recognition minter.
# Prints the raw key once + tenant id + WP install snippet. Idempotent on EMAIL.
# Usage:
#   make provision-customer EMAIL=customer@example.com PLAN=pro LABEL="Acme Co"
#   make provision-customer EMAIL=... ENV=prod   # against a remote DSN (container)
provision-customer:
	@if [ -z "$(EMAIL)" ]; then \
		echo "EMAIL is required. Example: make provision-customer EMAIL=customer@example.com PLAN=pro LABEL=\"Acme Co\""; \
		exit 1; \
	fi
	@cd apps/prototype-description-service && \
		$(MAKE) --no-print-directory provision-customer \
			EMAIL="$(EMAIL)" \
			PLAN="$(or $(PLAN),pro)" \
			LABEL="$(LABEL)" \
			ENV="$(or $(ENV),local)"

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

# VLM-2A caption + face eval harness (laptop CLI, remote OCI inference).
# Requires: ACX_EVAL_LIVE=1, ACX_EVAL_BASE_URL, ACX_EVAL_API_KEY (dedicated
# eval-tenant key, never the demo tenant's), ACX_EVAL_TENANT_ID (eval tenant
# UUID, required by all live subcommands), GOLDEN_IMAGES_DIR. Details:
# apps/prototype-description-service/scripts/eval_harness/README.md
#
# Scorer contract (scripts.eval_harness.cli score/run): 0 clean or
# refused-with-consent; 1 partial/determinism/env; 2 argparse; 3 REFUSED
# without --allow-refused. GNU Make converts every failed recipe to make
# exit 2, so this target cannot publish that contract as *make's* status:
#   scorer 0 -> make 0
#   scorer 1/2/3/other -> make 2
# Read the real scorer status from the last stdout line
#   eval-captions: scorer_exit=<N>
# or from
#   apps/prototype-description-service/scripts/eval_harness/out/eval-captions.status
# To observe exit 3 directly, run scripts/eval-captions.sh (same args).
# Shipped golden is roster_only (34/37 unboxed claims) so the scorer ends
# in 3. That is a correct refusal. Do not default --allow-refused here
# (auto-consent greenwashes a no-score report). Consent only at the call
# site: make eval-captions EVAL_ARGS='--allow-refused'
#        scripts/eval-captions.sh --allow-refused
.PHONY: eval-captions
eval-captions:
	@$(ROOT_MAKEFILE_DIR)/scripts/eval-captions.sh $(EVAL_ARGS)

.PHONY: gpu-burst-smoke gpu-burst-smoke-live
GPU_SMOKE_PYTHON ?= apps/prototype-description-service/.venv/bin/python
gpu-burst-smoke:
	@$(GPU_SMOKE_PYTHON) scripts/gpu_burst_smoke.py --dry-run

# Operator-only: needs ACX_GPU_SMOKE_CONFIRM=RUN and runs on acx-backend as
# ubuntu, since only that host has the OCI binary and vaulted key. Override
# GPU_SMOKE_PYTHON only when the service virtualenv lives elsewhere.
gpu-burst-smoke-live:
	@test -n "$${ACX_GPU_SMOKE_SERVICE_BASE_URL:-}" || { \
	  echo "ACX_GPU_SMOKE_SERVICE_BASE_URL must name the description service" >&2; \
	  exit 2; \
	}
	@$(GPU_SMOKE_PYTHON) scripts/gpu_burst_smoke.py --live --max-seconds 1200 \
	  --evidence-out "docs/tasks/vlm/GPUSMOKE-1-evidence-$$(date -u +%Y%m%dT%H%M%SZ).json" \
	  --wp-base-url "$${ACX_GPU_SMOKE_WP_BASE_URL:-https://wordpress.invalid}" \
	  --wp-user "$${ACX_GPU_SMOKE_WP_USER:-gpu-smoke-operator}" \
	  --wp-app-password-env "$${ACX_GPU_SMOKE_PASSWORD_ENV:-ACX_WP_APP_PASSWORD}" \
	  --media-ids "$${ACX_GPU_SMOKE_MEDIA_IDS:-101}" \
	  --service-base-url "$${ACX_GPU_SMOKE_SERVICE_BASE_URL}" \
	  --service-api-key-env "$${ACX_GPU_SMOKE_SERVICE_API_KEY_ENV:-ACX_DESCRIPTION_API_KEY}" \
	  --instance-id "$${ACX_GPU_SMOKE_INSTANCE_ID:-<burst-instance-ocid>}" \
	  --oci-bin "$${ACX_GPU_SMOKE_OCI_BIN:-/home/ubuntu/.oci-venv/bin/oci}"

# FIR-5 face bake-off: offline candidate walk (+ optional score). No tenant writes.
# Usage: make bakeoff-face
#        make bakeoff-face EVAL_ARGS="--limit 10"
#        make bakeoff-face-score FACE_RUN=scripts/eval_harness/out/face-run-....json
.PHONY: bakeoff-face bakeoff-face-score
bakeoff-face:
	@cd apps/prototype-description-service && uv run python -m scripts.eval_harness.cli face-bakeoff $(EVAL_ARGS)

bakeoff-face-score:
	@if [ -z "$(FACE_RUN)" ]; then echo "error: FACE_RUN is required" >&2; exit 2; fi
	@cd apps/prototype-description-service && uv run python -m scripts.eval_harness.cli score-face --run-record "$(FACE_RUN)" $(EVAL_ARGS)

# DS-3 per-prospect demo provisioning (backend registry + minter wrap only).
# Usage: make provision-demo LABEL="Acme Gallery" SEED=default
#        make expire-demo SLUG=<slug>
# Optional: ENV=local|dev|prod (default local). Requires DB DSN for the service.
LABEL ?=
SEED ?= default
SLUG ?=
DEMO_ENV ?= $(or $(ENV),local)

.PHONY: provision-demo expire-demo
provision-demo:
	@if [ -z "$(LABEL)" ]; then echo "error: LABEL is required (e.g. LABEL=\"Acme Gallery\")" >&2; exit 2; fi
	@cd apps/prototype-description-service && uv run python -m scripts.provision_demo \
		--env "$(DEMO_ENV)" provision --label "$(LABEL)" --seed "$(SEED)"

expire-demo:
	@if [ -z "$(SLUG)" ]; then echo "error: SLUG is required (e.g. SLUG=7fQ2abX)" >&2; exit 2; fi
	@cd apps/prototype-description-service && uv run python -m scripts.provision_demo \
		--env "$(DEMO_ENV)" expire --slug "$(SLUG)"

# =============================================================================
# ACE Observability
# =============================================================================

# The ace-* recipes are owned by the canonical Makefile.d/ace.mk, which is
# included below and overrides anything defined here. Repo-local copies used to
# live at this spot; GNU make silently preferred the fragment and only said so
# via `overriding commands` warnings. The consumer's job is to declare its
# playbook surface — the canonical recipes require a non-empty value.
# constitution.md, not instructions.md: the `helpful=/harmful=` counters ACE
# reflects on live in the Short Rules / regression-guard tables there (the
# CLAUDE.md and instructions.md copies are derived surfaces).
WORKBAY_ACE_PLAYBOOK_FILES ?= docs/workbay/constitution.md

# =============================================================================
# Lane / worktree context discipline (E15-LANE-ORCH slice 2)
# =============================================================================

# context + dashboard are owned by the canonical Makefile.d/lifecycle.mk
# (thin-consumer adoption, MAINT-workstate-migration-20260530).

worktree-audit:
	@$(MCP_PYTHON) scripts/worktree_audit.py

worktree-prune:
	@$(MCP_PYTHON) scripts/worktree_prune.py $(WORKTREE_PRUNE_ARGS)

# Archive stale MAINT-* handoff rows whose status is already `done` or
# `review`. Stale MAINT rows sharing the repo-root target_worktree_path
# cause cwd-resolution ambiguity for cold-start /branch-review and other
# ad-hoc skills. Run interactively; pass MAINT_ARCHIVE_ARGS="--yes" to
# archive every hit without prompting, or "--dry-run" to preview.
# Usage: make maint-archive-stale [MAINT_ARCHIVE_ARGS="--yes"]
maint-archive-stale:
	@$(MCP_PYTHON) scripts/maint_archive_stale.py $(MAINT_ARCHIVE_ARGS)

# maint-start is owned by the canonical Makefile.d/lifecycle.mk, which overrides
# this file and takes TASK=MAINT-<slug>-<YYYYMMDD>, not SLUG=. The repo-local
# scripts/maint-start.sh wrapper was already unreachable through make.

task-plan-audit:
	@$(MCP_PYTHON) scripts/task_plan_audit.py

# generate-agent-workflows + check-agent-workflows are owned by the canonical
# Makefile.d/workflows.mk (thin-consumer adoption). Force the shared generator
# to check this consumer's generated adapters by default; otherwise the
# symlinked generator resolves its own shared package root.
WORKFLOW_TARGET_ROOT ?= $(CURDIR)

# check-codex-command-router stays repo-local: canonical check-agent-workflows
# does not run the codex router-block check (recorded as an upstream finding);
# WORKFLOWS_PYTHON + the symlinked generator are provided by workflows.mk.
check-codex-command-router:
	@$(WORKFLOWS_PYTHON) scripts/generate_agent_workflows.py $(WORKFLOW_TARGET_ARG) --check-codex-router-blocks

smoke-agent-workflows:
	@$(MCP_PYTHON) scripts/smoke_agent_workflows.py $(if $(BACKEND),--backend $(BACKEND),)

check-skills:
	@$(MCP_PYTHON) scripts/check_skills.py

check-harness-sync:
	@$(MCP_PYTHON) scripts/check_harness_sync.py --check-api-surface

lint-hoisted-paths:
	@$(MCP_PYTHON) scripts/lint_hoisted_paths.py

# task-start + task-finish are owned by the canonical Makefile.d/lifecycle.mk.
# Canonical task-start derives the same context-alt-text-monorepo-<task-id>
# worktree path generically (handlers/task_start.py _derive_worktree_path), so
# no repo-local wrapper is needed (MAINT-workstate-migration-20260530).

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
# LIFECYCLE_FORMATTER: monorepo formatter wired to the branch-lifecycle
# post-slice `make format` step (Makefile.d/lifecycle.mk defaults it to a loud
# no-op via `?=`). Kept OUTSIDE the bootstrap-managed markers below so a future
# overlay migration cannot strip it again (regressed during the v0.1.24 upgrade).
LIFECYCLE_FORMATTER = $(MAKE) format-all
# >>> WORKBAY_BOOTSTRAP LIFECYCLE INCLUDE >>>
-include Makefile.d/*.mk
# <<< WORKBAY_BOOTSTRAP LIFECYCLE INCLUDE <<<

# Cursor discovers workflows from .cursor/skills; command markdown duplicates picker entries.
.PHONY: apply-cursor-skills-only-surface apply-cursor-skills-only-surface-check
apply-cursor-skills-only-surface:
	@$(PYTHON) scripts/apply_cursor_skills_only_surface.py
apply-cursor-skills-only-surface-check:
	@$(PYTHON) scripts/apply_cursor_skills_only_surface.py --check
