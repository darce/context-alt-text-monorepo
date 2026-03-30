# =============================================================================
# Orchestrator / Worker Daemon Lifecycle
# =============================================================================
# These targets require agent-orchestrator-mcp (packages/agent-orchestrator-mcp).
# Core handoff targets (task, dashboard, state, handoff-close-check) remain in mk/handoff.mk.
# =============================================================================

ORCHESTRATOR_MCP_CMD = PYTHONPATH="$(MCP_PYTHONPATH)" $(MCP_PYTHON) -m agent_orchestrator_mcp

.PHONY: worker-daemon worker-daemon-status worker-daemon-stop worker-daemon-resume worker-daemon-tail orchestrator-daemon daemon-pause daemon-resume daemon-status

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
