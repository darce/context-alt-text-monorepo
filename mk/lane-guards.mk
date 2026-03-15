# =============================================================================
# Lane Guards and Manifest Init
# =============================================================================

.PHONY: lane-guard lane-orchestrator-guard lane-worker-guard lane-manifest-init

lane-guard:
	@if [ -z "$(TASK)" ]; then \
		echo "TASK is required."; \
		echo "No active task could be inferred from MCP state."; \
		echo "Example: make lane-open TASK=<task-ref> LANE=<lane>"; \
		echo "Inspect current state: make state"; \
		exit 1; \
	fi
	@if [ -z "$(LANE)" ]; then \
		echo "LANE is required."; \
		echo "No lane could be inferred from branch $(CURRENT_BRANCH)."; \
		echo "Allowed lanes for $(TASK): $(TASK_LANES)"; \
		echo "List lane status: make lane-list"; \
		exit 1; \
	fi
	@if [ -z "$(TASK_LANES)" ]; then \
		echo "Unsupported TASK: $(TASK)"; \
		echo "Supported task manifests: $(SUPPORTED_TASKS)"; \
		exit 1; \
	fi
	@if [ -z "$(LANE_BRANCH)" ]; then \
		echo "Unsupported LANE: $(LANE)"; \
		echo "Allowed lanes for $(TASK): $(TASK_LANES)"; \
		exit 1; \
	fi

lane-orchestrator-guard: lane-guard
	@if [ "$(IN_ORCHESTRATOR_ROOT)" != "1" ]; then \
		echo "lane-commits and lane-intake must be run from the orchestrator root."; \
		echo "Current worktree: $(WORKTREE_ROOT_REAL)"; \
		echo "Expected orchestrator root: $(ORCHESTRATOR_ROOT)"; \
		exit 1; \
	fi

lane-worker-guard: lane-guard
	@if [ "$(IN_ORCHESTRATOR_ROOT)" = "1" ]; then \
		echo "This command must run from the worker worktree for lane $(LANE), not the orchestrator root."; \
		exit 1; \
	fi
	@if [ "$(CURRENT_BRANCH)" != "$(LANE_BRANCH)" ]; then \
		echo "Current branch $(CURRENT_BRANCH) does not match lane branch $(LANE_BRANCH)."; \
		exit 1; \
	fi

lane-manifest-init:
	@if [ -z "$(TASK)" ]; then \
		echo "TASK is required."; \
		exit 1; \
	fi
	@if [ -z "$(LANE_IDS)" ]; then \
		echo "LANE_IDS is required."; \
		echo "Example: make lane-manifest-init TASK=my-task LANE_IDS='backend frontend' TASK_PLAN=docs/tasks/x.md"; \
		exit 1; \
	fi
	@set -eu; \
	set -- python3 "$(ORCHESTRATOR_ROOT)/scripts/mcp/generate_lane_manifest.py" --task-ref "$(TASK)"; \
	for lane in $(LANE_IDS); do set -- "$$@" --lane "$$lane"; done; \
	if [ -n "$(TASK_PLAN)" ]; then set -- "$$@" --task-plan "$(TASK_PLAN)"; fi; \
	if [ "$(DRY_RUN)" = "1" ]; then \
		set -- "$$@" --stdout; \
	elif [ "$(OVERWRITE)" = "1" ]; then \
		set -- "$$@" --force; \
	fi; \
	"$$@"
