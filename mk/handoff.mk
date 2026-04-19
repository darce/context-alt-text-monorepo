# =============================================================================
# Handoff / Task State / Daemons
# =============================================================================

.PHONY: task state list-tasks lane-list mcp-serve-http handoff-close-check handoff-integrity-check handoff-inbox handoff-dispatch review-dispatch review-run review-ready plan-analyze plan-review slice-start slice-commit

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

# Validate that active handoff state is ready to close
handoff-close-check:
	@$(MCP_CMD) $(MCP_STATE_ARGS) handoff-close-check --enforce --current-commit-sha "$$(git rev-parse HEAD)"

plan-analyze:
	@if [ -z "$(DOC)" ]; then \
		echo "DOC is required."; \
		echo "Example: make plan-analyze DOC=docs/tasks/17.0/E17-1-skill-anatomy-template-and-constitution-task-plan.md"; \
		exit 1; \
	fi
	@if [ ! -f "$(DOC)" ]; then \
		echo "Document not found: $(DOC)"; \
		exit 1; \
	fi
	@printf '%s\n' \
		"Agent-assisted target: plan-analyze" \
		"Document: $(DOC)" \
		"Skill: .claude/skills/plan-analyze/SKILL.md (Phase 2 deliverable)" \
		"Constraint surface: docs/agentic/constitution.md" \
		"Review checklist: docs/agentic/rules/planning-review-guide.md" \
		"Expected output: MCP planning findings + a plan-analyze review_runs marker before planning review."

plan-review:
	@if [ -z "$(DOC)" ]; then \
		echo "DOC is required."; \
		echo "Example: make plan-review DOC=docs/epics/v0.4.0/skill-formalization-and-process-automation-epic.md"; \
		exit 1; \
	fi
	@if [ ! -f "$(DOC)" ]; then \
		echo "Document not found: $(DOC)"; \
		exit 1; \
	fi
	@set +e; \
		$(MCP_PYTHON) scripts/check_plan_analyze.py --doc "$(DOC)" $(if $(TASK),--task-ref $(TASK),); \
		status=$$?; \
		set -e; \
		if [ "$$status" -eq 1 ]; then \
			exit 1; \
		fi; \
		if [ "$$status" -eq 2 ] && [ "$(PLAN_ANALYZE_REQUIRED)" = "1" ]; then \
			exit 2; \
		fi
	@printf '%s\n' \
		"Agent-assisted target: plan-review" \
		"Document: $(DOC)" \
		"Skill: .claude/skills/planning-review/SKILL.md (Phase 2 deliverable)" \
		"Checklist: docs/agentic/rules/planning-review-guide.md" \
		"Expected output: MCP findings (reported with finding_id / handoff gap ids) + review_runs(record) + verdict decision + DASHBOARD.txt refresh."

slice-start:
	@if [ -z "$(TASK)" ]; then \
		echo "TASK is required."; \
		echo "No active task could be inferred from MCP state."; \
		echo "Example: make slice-start TASK=E17 TEST_CMD='pytest path/to/test -q'"; \
		exit 1; \
	fi
	@if [ -z "$(TEST_CMD)" ]; then \
		echo "TEST_CMD is required."; \
		echo "Example: make slice-start TASK=$(TASK) TEST_CMD='pytest path/to/test -q'"; \
		exit 1; \
	fi
	@SESSION_NAME="$(SESSION)"; \
	if [ -z "$$SESSION_NAME" ] || [ "$$SESSION_NAME" = "$(TASK)-" ]; then \
		SESSION_NAME="$(TASK)-slice-start"; \
	fi; \
	$(MCP_CMD) $(MCP_STATE_ARGS) event \
		--event-kind test_result \
		--task-ref "$(TASK)" \
		--session "$$SESSION_NAME" \
		--command "$(TEST_CMD)" \
		--result "$(or $(RESULT),Expected failing test before implementation begins.)" \
		--exit-code $(or $(EXIT_CODE),1) >/dev/null
	@$(MCP_CMD) $(MCP_STATE_ARGS) render-handoff --kind current_task --task-ref "$(TASK)" >/dev/null
	@echo "Recorded failing test gate for $(TASK)."

slice-commit:
	@if [ -z "$(TASK)" ]; then \
		echo "TASK is required."; \
		echo "No active task could be inferred from MCP state."; \
		echo "Example: make slice-commit TASK=E17 MSG='docs(agentic): add lifecycle map'"; \
		exit 1; \
	fi
	@if [ -z "$(or $(MSG),$(COMMIT_MSG))" ]; then \
		echo "MSG or COMMIT_MSG is required."; \
		echo "Example: make slice-commit TASK=$(TASK) MSG='feat(scope): add capability'"; \
		exit 1; \
	fi
	@SESSION_NAME="$(SESSION)"; \
	if [ -z "$$SESSION_NAME" ] || [ "$$SESSION_NAME" = "$(TASK)-" ]; then \
		SESSION_NAME="$(TASK)-slice-commit"; \
	fi; \
	PYTHONPATH="$(WORKTREE_MCP_PYTHONPATH)" \
		$(MCP_PYTHON) "$(WORKTREE_ROOT_REAL)/scripts/agentic/slice_commit.py" \
		--repo-root "$(WORKTREE_ROOT_REAL)" \
		--workspace-root "$(ORCHESTRATOR_ROOT)" \
		--state-dir "$(ORCHESTRATOR_ROOT)/.task-state" \
		--current-task-path "$(ORCHESTRATOR_ROOT)/CURRENT_TASK.json" \
		--exports-dir "$(ORCHESTRATOR_ROOT)/.task-state/exports" \
		--task-ref "$(TASK)" \
		--session "$$SESSION_NAME" \
		--message "$(or $(MSG),$(COMMIT_MSG))" \
		$(if $(FOCUS),--focus "$(FOCUS)",)

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
