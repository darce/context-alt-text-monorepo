# =============================================================================
# Orchestrator / Worker Daemon Lifecycle
# =============================================================================
# These targets require the installed agent-orchestrator-mcp package.
# Core handoff targets (task, dashboard, state, handoff-close-check) remain in mk/handoff.mk.
# =============================================================================

ORCHESTRATOR_MCP_CMD = $(MCP_RUNTIME_ENV) mcp-agent-orchestrator $(MCP_STATE_ARGS)

.PHONY: worker-daemon worker-daemon-status worker-daemon-stop worker-daemon-resume worker-daemon-tail orchestrator-daemon daemon-pause daemon-resume daemon-status

worker-daemon: lane-guard
	@set -eu; \
	SESSION="$(or $(SESSION),$(TASK)-$(LANE))"; \
	$(ORCHESTRATOR_MCP_CMD) worker-start \
		--task-ref "$(TASK)" \
		--lane-id "$(LANE)" \
		--session "$$SESSION" \
		$(if $(BACKEND),--backend "$(BACKEND)",) \
		$(if $(POLL_INTERVAL),--poll-interval "$(POLL_INTERVAL)",) \
		$(if $(filter 1,$(SINGLE_PASS)),--single-pass,) \
		$(if $(SESSION_MODE),--session-mode "$(SESSION_MODE)",) \
		$(if $(REASONING_EFFORT),--reasoning-effort "$(REASONING_EFFORT)",) \
		$(if $(MODEL),--model "$(MODEL)",) \
		$(if $(filter 1,$(DRY_RUN)),--single-pass,)

worker-daemon-status: lane-guard
	@$(ORCHESTRATOR_MCP_CMD) worker-status \
		--task-ref "$(TASK)" \
		--lane-id "$(LANE)"

worker-daemon-stop: lane-guard
	@$(ORCHESTRATOR_MCP_CMD) worker-stop \
		--task-ref "$(TASK)" \
		--lane-id "$(LANE)" \
		$(if $(filter 1,$(FORCE)),--force,)

worker-daemon-resume: lane-guard
	@$(ORCHESTRATOR_MCP_CMD) worker-resume \
		--task-ref "$(TASK)" \
		--lane-id "$(LANE)"

worker-daemon-tail: lane-guard
	@tail -f "$(ORCHESTRATOR_ROOT)/logs/worker-daemon/worker-$(LANE).jsonl"

orchestrator-daemon: lane-orchestrator-guard
	@$(ORCHESTRATOR_MCP_CMD) orchestrator-start \
		--task-ref "$(TASK)" \
		$(if $(BACKEND),--backend "$(BACKEND)",) \
		$(if $(MODEL),--model "$(MODEL)",) \
		$(if $(POLL_INTERVAL),--poll-interval "$(POLL_INTERVAL)",) \
		$(if $(filter 1,$(SINGLE_PASS)),--single-pass,) \
		$(if $(WORKER_START_MODE),--worker-start-mode "$(WORKER_START_MODE)",) \
		$(if $(WORKER_REASONING_EFFORT),--worker-reasoning-effort "$(WORKER_REASONING_EFFORT)",)

daemon-pause:
	@$(ORCHESTRATOR_MCP_CMD) orchestrator-pause

daemon-resume:
	@$(ORCHESTRATOR_MCP_CMD) orchestrator-resume

daemon-status:
	@$(ORCHESTRATOR_MCP_CMD) orchestrator-status
