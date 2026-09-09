# =============================================================================
# Lane Worker Operations (check, run, report, commit, handoff)
# =============================================================================

.PHONY: lane-check lane-run lane-report lane-commit lane-handoff dashboard-live dashboard-tui artifact-search artifact-list

lane-check: lane-worker-guard
	@set -eu; \
	echo "Ensuring lane dependencies are bootstrapped..."; \
	PYTHONPATH="$(MCP_PYTHONPATH)" $(MCP_PYTHON) -m workbay_orchestrator_mcp.orchestration.bootstrap_lane \
		--orchestrator-root "$(ORCHESTRATOR_ROOT)" \
		--task-ref "$(TASK)" \
		--lane-id "$(LANE)" \
		--worktree-path "$(LANE_WORKTREE_TARGET)"; \
	echo ""; \
	echo "Provisioning lane worktree overlays..."; \
	if [ -e "$(LANE_WORKTREE_TARGET)/.acx-secure-offload" ]; then \
		echo "Skipping overlay/dependency provision for secure-offload sandbox at $(LANE_WORKTREE_TARGET)"; \
	else \
		SECURE_OFFLOAD_FLAG=""; \
		case "$(OFFLOAD_BACKEND)" in grok*) SECURE_OFFLOAD_FLAG="--secure-offload" ;; esac; \
		python3 "$(ORCHESTRATOR_ROOT)/scripts/workstate/provision_lane_worktree.py" \
			--worktree "$(LANE_WORKTREE_TARGET)" \
			--primary "$(ORCHESTRATOR_ROOT)" \
			$$SECURE_OFFLOAD_FLAG; \
	fi; \
	echo ""; \
	record_test_result() { \
		command_text="$$1"; \
		step_label="$$2"; \
		output_file="$$(mktemp "$${TMPDIR:-/tmp}/lane-check-$(LANE)-XXXXXX")"; \
		if sh -lc "$$command_text" >"$$output_file" 2>&1; then \
			cat "$$output_file"; \
			result_text="$$(python3 -c 'from pathlib import Path; import sys; lines=[line.strip() for line in Path(sys.argv[1]).read_text(errors="replace").splitlines() if line.strip()]; tail=" | ".join(lines[-10:]) if lines else "command passed"; print(tail[:500])' "$$output_file")"; \
			$(MCP_CMD) --workspace-root "$(LANE_WORKTREE_TARGET)" --state-dir "$(ORCHESTRATOR_ROOT)/.task-state" --current-task-path "$(ORCHESTRATOR_ROOT)/CURRENT_TASK.json" --exports-dir "$(ORCHESTRATOR_ROOT)/.task-state/exports" \
				test --session "$(SESSION)" --command "$$command_text" --passed --result "$$result_text" --exit-code 0 >/dev/null; \
		else \
			status="$$?"; \
			cat "$$output_file"; \
			result_text="$$(python3 -c 'from pathlib import Path; import sys; lines=[line.strip() for line in Path(sys.argv[1]).read_text(errors="replace").splitlines() if line.strip()]; tail=" | ".join(lines[-10:]) if lines else "command failed"; print(tail[:500])' "$$output_file")"; \
			$(MCP_CMD) --workspace-root "$(LANE_WORKTREE_TARGET)" --state-dir "$(ORCHESTRATOR_ROOT)/.task-state" --current-task-path "$(ORCHESTRATOR_ROOT)/CURRENT_TASK.json" --exports-dir "$(ORCHESTRATOR_ROOT)/.task-state/exports" \
				test --session "$(SESSION)" --command "$$command_text" --result "$$result_text" --exit-code "$$status" >/dev/null; \
			rm -f "$$output_file"; \
			return "$$status"; \
		fi; \
		rm -f "$$output_file"; \
		echo ""; \
		echo "$$step_label passed."; \
		echo ""; \
	}; \
	if [ -z "$(LANE_TEST_CMD_1)" ] && [ -z "$(LANE_TEST_CMD_2)" ]; then \
		echo "No test commands configured for lane $(LANE)."; \
		exit 0; \
	fi; \
	if [ -n "$(LANE_TEST_CMD_1)" ]; then \
		echo "Running lane verification step 1..."; \
		record_test_result '$(LANE_TEST_CMD_1)' "Lane verification step 1"; \
	fi; \
	if [ -n "$(LANE_TEST_CMD_2)" ]; then \
		echo "Running lane verification step 2..."; \
		record_test_result '$(LANE_TEST_CMD_2)' "Lane verification step 2"; \
	fi; \
	echo "Lane $(LANE) verification passed."

lane-run: lane-guard
	@set -eu; \
	BACKEND_NAME="$(BACKEND)"; \
	CODEX_CMD=""; \
	if [ "$$BACKEND_NAME" = "codex-cli" ]; then \
		CODEX_CMD="$(CODEX_BIN)"; \
		if [ -z "$$CODEX_CMD" ] && [ -x "/Applications/Codex.app/Contents/Resources/codex" ]; then \
			CODEX_CMD="/Applications/Codex.app/Contents/Resources/codex"; \
		fi; \
		if [ -z "$$CODEX_CMD" ] && [ -x "$$HOME/.local/bin/codex" ]; then \
			CODEX_CMD="$$HOME/.local/bin/codex"; \
		fi; \
		if [ -z "$$CODEX_CMD" ]; then \
			echo "codex CLI is required for lane-run when BACKEND=codex-cli."; \
			exit 1; \
		fi; \
	fi; \
	PYTHONPATH="$(MCP_PYTHONPATH)" \
		$(MCP_PYTHON) -m workbay_orchestrator_mcp.orchestration.lane_prompt \
			--orchestrator-root "$(ORCHESTRATOR_ROOT)" \
			--task-ref "$(TASK)" \
			--lane-id "$(LANE)" \
			--worktree-path "$(LANE_WORKTREE_TARGET)" \
			--check >/dev/null 2>&1 && _check_rc=0 || _check_rc=$$?; \
	if [ "$$_check_rc" -ne 0 ]; then \
		if [ "$$_check_rc" -eq 3 ]; then \
			echo "No actionable lane inbox items for $(LANE)."; \
			exit 0; \
		fi; \
		if [ "$$_check_rc" -eq 4 ]; then \
			echo "Lane $(LANE) is waiting for orchestrator response before more work is assigned."; \
			exit 0; \
		fi; \
		exit "$$_check_rc"; \
	fi; \
	RESULT_FILE="$$(mktemp "$${TMPDIR:-/tmp}/lane-result-$(LANE)-XXXXXX.json")"; \
	trap 'rm -f "$$RESULT_FILE"' EXIT INT TERM; \
	set -- $(MCP_PYTHON) -m workbay_orchestrator_mcp.orchestration.lane_exec \
		--orchestrator-root "$(ORCHESTRATOR_ROOT)" \
		--task-ref "$(TASK)" \
		--lane-id "$(LANE)" \
		--session "$(SESSION)" \
		--worktree-path "$(LANE_WORKTREE_TARGET)" \
		--output-path "$$RESULT_FILE" \
		--backend "$$BACKEND_NAME"; \
	if [ -n "$$CODEX_CMD" ]; then \
		set -- "$$@" --codex-bin "$$CODEX_CMD"; \
	fi; \
	if [ -n "$(CODEX_ARGS)" ]; then \
		set -- "$$@" --codex-args "$(CODEX_ARGS)"; \
	fi; \
	if [ -n "$(MODEL)" ]; then \
		set -- "$$@" --model "$(MODEL)"; \
	fi; \
	if [ "$(DRY_RUN)" = "1" ]; then \
		set -- "$$@" --dry-run; \
	fi; \
	if PYTHONPATH="$(MCP_PYTHONPATH)" "$$@"; then \
		$(MCP_PYTHON) -m workbay_orchestrator_mcp.orchestration.lane_result handoff \
			--orchestrator-root "$(ORCHESTRATOR_ROOT)" \
			--task-ref "$(TASK)" \
			--lane-id "$(LANE)" \
			--session "$(SESSION)" \
			--worktree-path "$(LANE_WORKTREE_TARGET)" \
			--result-file "$$RESULT_FILE"; \
	else \
		status=$$?; \
		echo "lane_exec.py failed before automated handoff could be recorded."; \
		if [ -s "$$RESULT_FILE" ]; then \
			FAILURE_DIR="$(ORCHESTRATOR_ROOT)/.task-state/exports/lane-run-failures"; \
			mkdir -p "$$FAILURE_DIR"; \
			PRESERVED_RESULT="$$FAILURE_DIR/$(TASK)-$(LANE)-$$(date +%Y%m%d%H%M%S).json"; \
			cp "$$RESULT_FILE" "$$PRESERVED_RESULT"; \
			echo "Structured result was captured at $$PRESERVED_RESULT"; \
		fi; \
		exit "$$status"; \
	fi

lane-report: lane-worker-guard
	@set -eu; \
	set -- "$(ORCHESTRATOR_ROOT)/scripts/worktree-lane" report \
		--orchestrator-root "$$ORCHESTRATOR_ROOT" \
		--task-ref "$$TASK" \
		--lane-id "$$LANE" \
		--session "$$SESSION" \
		--summary "$$SUMMARY" \
		--status "$$STATUS" \
		--worktree-path "$(LANE_WORKTREE_TARGET)"; \
	if [ -n "$${LANE_TEST_CMD_1:-}" ]; then set -- "$$@" --test-command "$$LANE_TEST_CMD_1"; fi; \
	if [ -n "$${LANE_TEST_CMD_2:-}" ]; then set -- "$$@" --test-command "$$LANE_TEST_CMD_2"; fi; \
	if [ "$${MERGE_READY:-0}" = "1" ]; then set -- "$$@" --merge-ready; fi; \
	if [ "$${DRY_RUN:-0}" = "1" ]; then set -- "$$@" --dry-run; fi; \
	if [ -n "$${MESSAGE:-}" ]; then \
		report_subject="$${SUBJECT:-}"; \
		if [ -z "$$report_subject" ] || [ "$$report_subject" = "$$LANE next assignment" ]; then \
			set -- "$$@" --message "$$MESSAGE"; \
		else \
			set -- "$$@" --message "$$MESSAGE" --subject "$$report_subject"; \
		fi; \
	fi; \
	"$$@"

lane-commit: lane-worker-guard
	@set -eu; \
	if [ -z "$(LANE_COMMIT_PATHS)" ]; then \
		echo "No lane-owned commit paths configured for $(LANE)."; \
		exit 1; \
	fi; \
	TOOLING_FILES="$(LANE_TOOLING_PATHS) $(LANE_APP_TOOLING_PATHS)"; \
	ALL_CHANGED="$$( { git diff --name-only; git diff --cached --name-only; git ls-files --others --exclude-standard; } | sort -u )"; \
	OUT_OF_SCOPE=""; \
	for file in $$ALL_CHANGED; do \
		[ -n "$$file" ] || continue; \
		tooling=0; \
		for tooling_file in $$TOOLING_FILES; do \
			case "$$file" in \
				$$tooling_file|$$tooling_file/*) tooling=1; break ;; \
			esac; \
		done; \
		if [ "$$tooling" -eq 1 ]; then \
			continue; \
		fi; \
		allowed=0; \
		for prefix in $(LANE_COMMIT_PATHS); do \
			case "$$file" in \
				$$prefix|$$prefix/*) allowed=1; break ;; \
			esac; \
		done; \
		if [ "$$allowed" -ne 1 ]; then \
			OUT_OF_SCOPE="$$OUT_OF_SCOPE\n$$file"; \
		fi; \
	done; \
	if [ -n "$$OUT_OF_SCOPE" ]; then \
		echo "Refusing to commit lane $(LANE) with out-of-scope changes present:"; \
		printf '%b\n' "$$OUT_OF_SCOPE"; \
		exit 1; \
	fi; \
	if [ "$(DRY_RUN)" = "1" ]; then \
		echo "[dry-run] git add -A -- $(LANE_COMMIT_PATHS)"; \
		echo "[dry-run] git commit -m \"$(LANE): $(if $(COMMIT_MSG),$(COMMIT_MSG),$(LANE_COMMIT_SUBJECT))\""; \
	else \
		git add -A -- $(LANE_COMMIT_PATHS); \
		if git diff --cached --quiet -- $(LANE_COMMIT_PATHS); then \
			echo "No lane-owned changes to commit for $(LANE)."; \
		else \
			git commit -m "$(LANE): $(if $(COMMIT_MSG),$(COMMIT_MSG),$(LANE_COMMIT_SUBJECT))"; \
		fi; \
	fi

lane-handoff: lane-worker-guard
	@set -eu; \
	$(MAKE) lane-commit TASK="$(TASK)" LANE="$(LANE)" DRY_RUN="$(DRY_RUN)" COMMIT_MSG="$(COMMIT_MSG)"; \
	if [ "$(DRY_RUN)" != "1" ]; then \
		AHEAD_COUNT="$$(git -C "$(LANE_WORKTREE_TARGET)" rev-list --count "$(ORCHESTRATOR_BRANCH)..HEAD" 2>/dev/null || printf '0')"; \
		if [ "$$AHEAD_COUNT" = "0" ] && [ "$(STATUS)" != "blocked" ]; then \
			echo "No unique lane commits exist for $(LANE), so there is nothing merge-ready to hand off."; \
			echo "If the lane is blocked without code changes, use: make lane-report STATUS=blocked MERGE_READY=0 SUMMARY=\"...\" MESSAGE=\"...\""; \
			exit 1; \
		fi; \
	fi; \
	echo ""; \
	$(MAKE) lane-status TASK="$(TASK)" LANE="$(LANE)"; \
	echo ""; \
	$(MAKE) lane-report TASK="$(TASK)" LANE="$(LANE)" SESSION="$(SESSION)" SUMMARY="$(SUMMARY)" STATUS="$(STATUS)" MERGE_READY="$(MERGE_READY)" DRY_RUN="$(DRY_RUN)" MESSAGE="$(MESSAGE)"

dashboard-live:
	@PYTHONPATH="$(MCP_PYTHONPATH)" $(MCP_PYTHON) -m workbay_orchestrator_mcp.orchestration.dashboard_live \
		--orchestrator-root "$(ORCHESTRATOR_ROOT)" \
		--task-ref "$(TASK)" \
		$(if $(LANES),$(addprefix --lanes ,$(LANES)),) \
		--interval "$(or $(INTERVAL),10)" \
		$(if $(filter 1,$(ONCE)),--once,)

dashboard-tui:
	@PYTHONPATH="$(MCP_PYTHONPATH)" $(MCP_PYTHON) -m workbay_orchestrator_mcp.orchestration.dashboard_tui \
		--orchestrator-root "$(ORCHESTRATOR_ROOT)" \
		--task-ref "$(TASK)" \
		$(if $(LANES),$(addprefix --lanes ,$(LANES)),) \
		--interval "$(or $(INTERVAL),10)" \
		$(if $(filter 1,$(ONCE)),--once,)

# Search indexed artifacts by keyword (QUERY variable required, optionally LANE=<id>)
# Usage: make artifact-search TASK=<task> QUERY="schema missing" [LANE=<lane-id>]
artifact-search:
	@$(if $(QUERY),,$(error QUERY is required: make artifact-search TASK=<task> QUERY="..."))
	@$(MCP_CMD) $(MCP_STATE_ARGS) \
		artifact-search \
		--query "$(QUERY)" \
		$(if $(TASK),--task-ref "$(TASK)",) \
		$(if $(LANE),--lane-id "$(LANE)",) \
		--limit "$(or $(LIMIT),10)"

# List indexed artifact sources for the current task/lane
# Usage: make artifact-list TASK=<task> [LANE=<lane-id>]
artifact-list:
	@$(MCP_CMD) $(MCP_STATE_ARGS) \
		artifact-list \
		$(if $(TASK),--task-ref "$(TASK)",) \
		$(if $(LANE),--lane-id "$(LANE)",) \
		--limit "$(or $(LIMIT),20)"
