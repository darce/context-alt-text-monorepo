# =============================================================================
# Lane Lifecycle (open, status, inbox, prompt, dispatch)
# =============================================================================

.PHONY: lane-open lane-status lane-inbox lane-prompt lane-dispatch

# OFFLOAD_BACKEND routes untrusted backends (grok*) to the secure shallow clone
# inside worktree-lane create. Default empty = plain worktree (current behavior).
# Example: make lane-open TASK=... LANE=... OFFLOAD_BACKEND=grok-cli
OFFLOAD_BACKEND ?=

lane-open: lane-guard
	@set -eu; \
	DRY_FLAG=""; \
	if [ "$(DRY_RUN)" = "1" ]; then DRY_FLAG="--dry-run"; fi; \
	"$(ORCHESTRATOR_ROOT)/scripts/worktree-lane" create \
		--orchestrator-root "$(ORCHESTRATOR_ROOT)" \
		--lane-id "$(LANE)" \
		--branch "$(LANE_BRANCH)" \
		--worktree-path "$(LANE_WORKTREE)" \
		--title "$(LANE_TITLE)" \
		--objective "$(LANE_OBJECTIVE)" \
		--owner-agent codex \
		--status active \
		--notes "Makefile-managed worker lane for $(TASK)." \
		--offload-backend "$(OFFLOAD_BACKEND)" \
		$$DRY_FLAG; \
	echo ""; \
	"$(ORCHESTRATOR_ROOT)/scripts/worktree-lane" brief \
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
	echo ""; \
	echo "Prepared lane worktree state:"; \
	git -C "$(LANE_WORKTREE)" status -sb; \
	if [ "$(DRY_RUN)" != "1" ]; then \
		echo ""; \
		echo "Bootstrapping lane dependencies..."; \
		PYTHONPATH="$(MCP_PYTHONPATH)" $(MCP_PYTHON) -m workbay_orchestrator_mcp.orchestration.bootstrap_lane \
			--orchestrator-root "$(ORCHESTRATOR_ROOT)" \
			--task-ref "$(TASK)" \
			--lane-id "$(LANE)" \
			--worktree-path "$(LANE_WORKTREE)"; \
		echo ""; \
		echo "Provisioning lane worktree overlays..."; \
		python3 "$(ORCHESTRATOR_ROOT)/scripts/workstate/provision_lane_worktree.py" \
			--worktree "$(LANE_WORKTREE)" \
			--primary "$(ORCHESTRATOR_ROOT)"; \
		echo ""; \
		echo "Initial lane inbox:"; \
		$(MAKE) --no-print-directory lane-inbox TASK="$(TASK)" LANE="$(LANE)"; \
	fi; \
	if [ "$(ENTER_SHELL)" = "1" ] && [ "$(DRY_RUN)" != "1" ]; then \
		echo ""; \
		echo "Opening interactive shell in $(LANE_WORKTREE)"; \
		cd "$(LANE_WORKTREE)" && exec "$${SHELL:-/bin/zsh}" -l; \
	else \
		echo ""; \
		echo "Worktree ready at $(LANE_WORKTREE)"; \
		echo "Your current shell is still at $(WORKTREE_ROOT_REAL)."; \
		echo "Next step: cd \"$(LANE_WORKTREE)\" or rerun without ENTER_SHELL=0."; \
	fi

lane-status: lane-guard
	@set -eu; \
	"$(ORCHESTRATOR_ROOT)/scripts/worktree-lane" status \
		--orchestrator-root "$(ORCHESTRATOR_ROOT)" \
		--task-ref "$(TASK)" \
		--lane-id "$(LANE)" \
		--worktree-path "$(LANE_WORKTREE)"; \
	echo ""; \
	git -C "$(LANE_WORKTREE)" status -sb

lane-inbox: lane-guard
	@set -eu; \
	WORKTREE_PATH="$(LANE_WORKTREE_TARGET)"; \
	echo "Open dispatch messages for lane $(LANE):"; \
	$(MCP_CMD) $(MCP_STATE_ARGS) \
		lane-message-list \
		--task-ref "$(TASK)" \
		--lane-id "$(LANE)" \
		--status open | python3 -c 'import json,sys; data=json.load(sys.stdin); data["messages"]=[m for m in data.get("messages", []) if m.get("direction")=="orchestrator_to_worker"]; data["returned"]=len(data["messages"]); data["total_matching"]=len(data["messages"]); print(json.dumps(data, indent=2))'; \
	echo ""; \
	echo "Latest worker report for lane $(LANE):"; \
	$(MCP_CMD) $(MCP_STATE_ARGS) \
		lane-report-list \
		--task-ref "$(TASK)" \
		--lane-id "$(LANE)" \
		--limit 1; \
	echo ""; \
	"$(ORCHESTRATOR_ROOT)/scripts/worktree-lane" status \
		--orchestrator-root "$(ORCHESTRATOR_ROOT)" \
		--task-ref "$(TASK)" \
		--lane-id "$(LANE)" \
		--worktree-path "$$WORKTREE_PATH"; \
	echo ""; \
	echo "Worker action summary:"; \
	PYTHONPATH="$(MCP_PYTHONPATH)" \
		$(MCP_PYTHON) -m workbay_orchestrator_mcp.orchestration.lane_prompt \
			--orchestrator-root "$(ORCHESTRATOR_ROOT)" \
			--task-ref "$(TASK)" \
			--lane-id "$(LANE)" \
			--worktree-path "$$WORKTREE_PATH" \
			--summary

lane-prompt: lane-guard
	@PYTHONPATH="$(MCP_PYTHONPATH)" \
		$(MCP_PYTHON) -m workbay_orchestrator_mcp.orchestration.lane_prompt \
		--orchestrator-root "$(ORCHESTRATOR_ROOT)" \
		--task-ref "$(TASK)" \
		--lane-id "$(LANE)" \
		--worktree-path "$(LANE_WORKTREE_TARGET)" \
		$(EXTRA_ARGS)

lane-dispatch: lane-guard lane-orchestrator-guard
	@if [ -z "$(MESSAGE)" ]; then \
		echo "MESSAGE is required."; \
		echo "Example: make lane-dispatch TASK=phase-5-retention-export-and-audit-controls LANE=backend-http MESSAGE=\"Wire the retention router to the real services and verify pytest + mypy.\""; \
		exit 1; \
	fi
	@set -eu; \
	DISPATCH_SESSION="$(TASK)-dispatch-$(LANE)-$$(date +%Y%m%d%H%M%S)"; \
	if [ "$(DRY_RUN)" = "1" ]; then \
		echo "[dry-run] mcp-workbay-handoff lane-upsert --lane-id \"$(LANE)\" --worktree-path \"$(LANE_WORKTREE)\" --branch \"$(LANE_BRANCH)\" --status active"; \
		echo "[dry-run] mcp-workbay-handoff lane-message --lane-id \"$(LANE)\" --session \"$$DISPATCH_SESSION\" --direction orchestrator_to_worker --subject \"$(SUBJECT)\" --message \"$(MESSAGE)\" --status open"; \
		echo "[dry-run] $(MAKE) task"; \
		echo "Dispatch preview ready for $(LANE)."; \
		exit 0; \
	fi; \
	$(MCP_CMD) $(MCP_STATE_ARGS) \
		lane-upsert \
		--task-ref "$(TASK)" \
		--lane-id "$(LANE)" \
		--worktree-path "$(LANE_WORKTREE)" \
		--branch "$(LANE_BRANCH)" \
		--title "$(LANE_TITLE)" \
		--objective "$(LANE_OBJECTIVE)" \
		--owner-agent codex \
		--status active \
		--notes "Makefile-managed worker lane for $(TASK)."; \
	$(MCP_CMD) $(MCP_STATE_ARGS) \
		lane-message \
		--lane-id "$(LANE)" \
		--session "$$DISPATCH_SESSION" \
		--direction orchestrator_to_worker \
		--subject "$(SUBJECT)" \
		--message "$(MESSAGE)" \
		--status open; \
	$(MAKE) task; \
	echo ""; \
	echo "Dispatch recorded for $(LANE). Workers can poll it with: make lane-inbox TASK=$(TASK) LANE=$(LANE)"
