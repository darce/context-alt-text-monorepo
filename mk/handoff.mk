# =============================================================================
# Handoff / Task State / Daemons
# =============================================================================

.PHONY: task dashboard state list-tasks lane-list mcp-serve-http handoff-close-check handoff-integrity-check handoff-inbox handoff-dispatch review-dispatch review-run review-ready worker-daemon worker-daemon-status worker-daemon-stop worker-daemon-resume worker-daemon-tail orchestrator-daemon daemon-pause daemon-resume daemon-status

# Generate CURRENT_TASK.md from handoff DB
task:
	@$(MCP_CMD) $(MCP_STATE_ARGS) task

# Print handoff dashboard
dashboard:
	@$(MCP_CMD) $(MCP_STATE_ARGS) dashboard

# Print full handoff state
state:
	@$(MCP_CMD) $(MCP_STATE_ARGS) state

# List all registered worktree lanes and their status
lane-list:
	@$(MCP_CMD) $(MCP_STATE_ARGS) lane-list --status all

# Start MCP server over streamable-HTTP for remote attachment (e.g. Codex custom MCP)
# Usage: make mcp-serve-http [HOST=127.0.0.1] [PORT=8741]
HOST ?= 127.0.0.1
PORT ?= 8741
mcp-serve-http:
	$(MCP_CMD) $(MCP_STATE_ARGS) serve-http --host "$(HOST)" --port $(PORT)

# List available task manifests
list-tasks:
	@printf '%s\n' $(SUPPORTED_TASKS)

# Validate that active handoff state is ready to close
handoff-close-check:
	@$(MCP_CMD) $(MCP_STATE_ARGS) handoff-close-check --enforce --current-commit-sha "$$(git rev-parse HEAD)"

review-ready:
	@if [ -z "$(TASK)" ]; then \
		echo "TASK is required."; \
		echo "No active task could be inferred from MCP state."; \
		echo "Example: make review-ready TASK=agentic-development-process-hardening-epic"; \
		echo "Inspect current state: make state"; \
		exit 1; \
	fi
	@PYTHONPATH="$(WORKTREE_MCP_PYTHONPATH)" \
		$(MCP_PYTHON) "$(WORKTREE_ORCHESTRATION_DIR)/review_ready.py" \
		--orchestrator-root "$(ORCHESTRATOR_ROOT)" \
		--worktree-root "$(WORKTREE_ROOT_REAL)" \
		--task-ref "$(TASK)" \
		--review-base "$(or $(REVIEW_BASE),$(ORCHESTRATOR_BRANCH))"

# CI/local guard for parser + lifecycle + close-check integrity
handoff-integrity-check:
	@PYTHONPATH="$(MCP_PYTHONPATH)" $(PYTHON) "$(ORCHESTRATION_DIR)/handoff_integrity_guard.py"

handoff-inbox:
	@if [ "$(IN_ORCHESTRATOR_ROOT)" != "1" ]; then \
		echo "handoff-inbox must be run from the orchestrator root."; \
		echo "Current worktree: $(WORKTREE_ROOT_REAL)"; \
		echo "Expected orchestrator root: $(ORCHESTRATOR_ROOT)"; \
		exit 1; \
	fi
	@if [ -z "$(TASK)" ]; then \
		echo "TASK is required."; \
		echo "No active task could be inferred from MCP state."; \
		echo "Example: make handoff-inbox TASK=phase-5-retention-export-and-audit-controls"; \
		echo "Inspect current state: make state"; \
		exit 1; \
	fi
	@echo "Open worker handoff messages:"; \
	$(MCP_CMD) $(MCP_STATE_ARGS) \
		lane-message-list \
		--task-ref "$(TASK)" \
		$(if $(LANE),--lane-id "$(LANE)",) \
		--status open | python3 -c 'import json,sys; data=json.load(sys.stdin); data["messages"]=[m for m in data.get("messages", []) if m.get("direction")=="worker_to_orchestrator"]; data["returned"]=len(data["messages"]); data["total_matching"]=len(data["messages"]); print(json.dumps(data, indent=2))'; \
	echo ""; \
	echo "Latest worker reports:"; \
	$(MCP_CMD) $(MCP_STATE_ARGS) \
		lane-report-list \
		--task-ref "$(TASK)" \
		$(if $(LANE),--lane-id "$(LANE)",) \
		--limit 20 | python3 -c 'import json,sys; data=json.load(sys.stdin); reports=[r for r in data.get("reports", []) if r.get("merge_ready")==1 or r.get("status")=="blocked"]; data["reports"]=reports; data["returned"]=len(reports); data["total_matching"]=len(reports); print(json.dumps(data, indent=2))'
	@echo ""; \
	echo "Guidance summary:"; \
	PYTHONPATH="$(MCP_PYTHONPATH)" \
		$(MCP_PYTHON) "$(ORCHESTRATION_DIR)/handoff_guidance_summary.py" \
		--orchestrator-root "$(ORCHESTRATOR_ROOT)" \
		--task-ref "$(TASK)" \
		$(if $(LANE),--lane-id "$(LANE)",)

handoff-dispatch:
	@if [ "$(IN_ORCHESTRATOR_ROOT)" != "1" ]; then \
		echo "handoff-dispatch must be run from the orchestrator root."; \
		echo "Current worktree: $(WORKTREE_ROOT_REAL)"; \
		echo "Expected orchestrator root: $(ORCHESTRATOR_ROOT)"; \
		exit 1; \
	fi
	@if [ -z "$(TASK)" ]; then \
		echo "TASK is required."; \
		echo "No active task could be inferred from MCP state."; \
		echo "Example: make handoff-dispatch TASK=<task-ref>"; \
		echo "Inspect current state: make state"; \
		exit 1; \
	fi
	@if [ -z "$(TASK_LANES)" ]; then \
		echo "Unsupported TASK: $(TASK)"; \
		echo "Supported task manifests: $(SUPPORTED_TASKS)"; \
		exit 1; \
	fi
	@PYTHONPATH="$(WORKTREE_MCP_PYTHONPATH)" \
		$(MCP_PYTHON) "$(WORKTREE_ORCHESTRATION_DIR)/review_dispatch.py" \
		--orchestrator-root "$(ORCHESTRATOR_ROOT)" \
		--task-ref "$(TASK)" \
		$(if $(filter 1,$(DRY_RUN)),--dry-run,)

review-run:
	@if [ -z "$(LANE_WORKTREE_TARGET)" ] && [ -z "$(WORKTREE_PATH)" ]; then \
		echo "review-run requires a lane worktree. Set WORKTREE_PATH or run from a lane."; \
		exit 1; \
	fi
	@PYTHONPATH="$(WORKTREE_MCP_PYTHONPATH)" \
		$(MCP_PYTHON) "$(WORKTREE_ORCHESTRATION_DIR)/review_runner.py" run \
		--worktree-path "$(or $(WORKTREE_PATH),$(LANE_WORKTREE_TARGET))" \
		$(if $(LANE),--lane-id "$(LANE)",) \
		$(if $(TASK),--task-ref "$(TASK)",) \
		$(if $(SESSION),--session "$(SESSION)",) \
		$(if $(BACKEND),--backend "$(BACKEND)",) \
		$(if $(filter 1,$(RECORD_FINDINGS)),--record-findings,) \
		$(if $(ORCHESTRATOR_ROOT),--orchestrator-root "$(ORCHESTRATOR_ROOT)",$(if $(filter 1,$(RECORD_FINDINGS)),--orchestrator-root "$(WORKTREE_ROOT_REAL)",)) \
		$(if $(filter 1,$(DRY_RUN)),--dry-run,)

review-dispatch: handoff-dispatch

worker-daemon: lane-guard
	@set -eu; \
	SESSION="$(or $(SESSION),$(TASK)-$(LANE))"; \
	PYTHONPATH="$(MCP_PYTHONPATH)" \
		$(MCP_PYTHON) "$(ORCHESTRATION_DIR)/worker_daemon.py" \
		--orchestrator-root "$(ORCHESTRATOR_ROOT)" \
		--task-ref "$(TASK)" \
		--lane-id "$(LANE)" \
		--session "$$SESSION" \
		--worktree-path "$(LANE_WORKTREE_TARGET)" \
		$(if $(BACKEND),--backend "$(BACKEND)",) \
		$(if $(MAX_REVIEW_CYCLES),--max-review-cycles "$(MAX_REVIEW_CYCLES)",) \
		$(if $(POLL_INTERVAL),--poll-interval "$(POLL_INTERVAL)",) \
		$(if $(filter 1,$(SINGLE_PASS)),--single-pass,) \
		$(if $(CODEX_BIN),--codex-bin "$(CODEX_BIN)",) \
		$(if $(CODEX_ARGS),--codex-args "$(CODEX_ARGS)",) \
		$(if $(MODEL),--model "$(MODEL)",) \
		$(if $(filter 1,$(DRY_RUN)),--dry-run,)

worker-daemon-status: lane-guard
	@$(MCP_PYTHON) "$(ORCHESTRATION_DIR)/worker_daemon_ctl.py" status \
		--state-dir "$(ORCHESTRATOR_ROOT)/.task-state" \
		--log-dir "$(ORCHESTRATOR_ROOT)/logs/worker-daemon" \
		--task-ref "$(TASK)" \
		--lane-id "$(LANE)"

worker-daemon-stop: lane-guard
	@$(MCP_PYTHON) "$(ORCHESTRATION_DIR)/worker_daemon_ctl.py" stop \
		--state-dir "$(ORCHESTRATOR_ROOT)/.task-state" \
		--log-dir "$(ORCHESTRATOR_ROOT)/logs/worker-daemon" \
		--task-ref "$(TASK)" \
		--lane-id "$(LANE)" \
		$(if $(filter 1,$(FORCE)),--force,)

worker-daemon-resume: lane-guard
	@$(MCP_PYTHON) "$(ORCHESTRATION_DIR)/worker_daemon_ctl.py" resume \
		--state-dir "$(ORCHESTRATOR_ROOT)/.task-state" \
		--log-dir "$(ORCHESTRATOR_ROOT)/logs/worker-daemon" \
		--task-ref "$(TASK)" \
		--lane-id "$(LANE)"

worker-daemon-tail: lane-guard
	@tail -f "$(ORCHESTRATOR_ROOT)/logs/worker-daemon/worker-$(LANE).jsonl"

orchestrator-daemon: lane-orchestrator-guard
	@PYTHONPATH="$(MCP_PYTHONPATH)" \
		$(MCP_PYTHON) "$(ORCHESTRATION_DIR)/orchestrator_daemon.py" run \
		--orchestrator-root "$(ORCHESTRATOR_ROOT)" \
		$(if $(TASK),--task-ref "$(TASK)",) \
		$(if $(BACKEND),--backend "$(BACKEND)",) \
		$(if $(MODEL),--model "$(MODEL)",) \
		$(if $(POLL_INTERVAL),--poll-interval "$(POLL_INTERVAL)",) \
		$(if $(filter 1,$(SINGLE_PASS)),--single-pass,) \
		$(if $(filter 1,$(DRY_RUN)),--dry-run,)

daemon-pause:
	@$(MCP_PYTHON) "$(ORCHESTRATION_DIR)/orchestrator_daemon.py" pause \
		--state-dir "$(ORCHESTRATOR_ROOT)/.task-state"

daemon-resume:
	@$(MCP_PYTHON) "$(ORCHESTRATION_DIR)/orchestrator_daemon.py" resume \
		--state-dir "$(ORCHESTRATOR_ROOT)/.task-state"

daemon-status:
	@PYTHONPATH="$(MCP_PYTHONPATH)" \
		$(MCP_PYTHON) "$(ORCHESTRATION_DIR)/orchestrator_daemon.py" status \
		--state-dir "$(ORCHESTRATOR_ROOT)/.task-state" \
		--log-dir "$(ORCHESTRATOR_ROOT)/logs/daemon"
