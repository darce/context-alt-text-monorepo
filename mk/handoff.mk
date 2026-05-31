# =============================================================================
# Handoff / Task State / Daemons
# =============================================================================
#
# Lifecycle targets (handoff-close-check, handoff-review-run, plan-analyze,
# plan-review, slice-start, slice-commit, review-ready, review-run) were
# removed in MAINT-workstate-migration-20260530: the repo is now a thin
# consumer of the canonical Makefile.d/lifecycle.mk, which owns those names.
# The orchestrator-lane variants of review-ready / review-run that previously
# lived here are tracked as lost-functionality findings for the upstream
# orchestrator package (see docs/workstate upstream-asks note).

.PHONY: task state list-tasks lane-list mcp-serve-http handoff-integrity-check handoff-inbox handoff-dispatch review-dispatch

# Generate CURRENT_TASK.json from handoff DB
task:
	@$(MCP_CMD) $(MCP_STATE_ARGS) render-handoff --kind current_task $(if $(TASK),--task-ref "$(TASK)",)

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

# CI/local guard for parser + lifecycle + close-check integrity
handoff-integrity-check:
	@$(MCP_PYTHON) "$(WORKTREE_ROOT_REAL)/scripts/mcp/handoff_integrity_guard.py"

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
		$(MCP_PYTHON) -m workstate_orchestrator_mcp.orchestration.handoff_guidance_summary \
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
		$(MCP_PYTHON) -m workstate_orchestrator_mcp.orchestration.review_dispatch \
		--orchestrator-root "$(ORCHESTRATOR_ROOT)" \
		--task-ref "$(TASK)" \
		$(if $(filter 1,$(DRY_RUN)),--dry-run,)

review-dispatch: handoff-dispatch
