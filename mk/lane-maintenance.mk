# =============================================================================
# Lane Maintenance (reset, refresh, clean, path, commits, intake)
# =============================================================================

.PHONY: lane-reset lane-refresh lane-clean lane-path lane-commits lane-intake

lane-reset: lane-guard
	@if [ -z "$(REF)" ]; then \
		echo "REF is required."; \
		exit 1; \
	fi
	@set -eu; \
	if [ "$(DRY_RUN)" = "1" ]; then \
		echo "[dry-run] git -C \"$(LANE_WORKTREE)\" reset --hard \"$(REF)\""; \
		echo "[dry-run] git -C \"$(LANE_WORKTREE)\" clean -fd"; \
	else \
		git -C "$(LANE_WORKTREE)" reset --hard "$(REF)"; \
		git -C "$(LANE_WORKTREE)" clean -fd; \
		git -C "$(LANE_WORKTREE)" status -sb; \
	fi

lane-refresh: lane-guard
	@set -eu; \
	TARGET_WORKTREE="$(LANE_WORKTREE_TARGET)"; \
	STASH_MSG="lane-refresh $(LANE) $$(date +%Y%m%d%H%M%S)"; \
	TOOLING_FILES="$(ROOT_REFRESH_PATHS) $(LANE_APP_TOOLING_PATHS)"; \
	if [ ! -d "$$TARGET_WORKTREE" ]; then \
		echo "Lane worktree does not exist: $$TARGET_WORKTREE"; \
		exit 1; \
	fi; \
	if [ "$(DRY_RUN)" = "1" ]; then \
		echo "[dry-run] target worktree: $$TARGET_WORKTREE"; \
		echo "[dry-run] verify orchestrator workflow tooling is committed on $(ORCHESTRATOR_BRANCH) before refresh"; \
		echo "[dry-run] git -C \"$$TARGET_WORKTREE\" fetch \"$(ORCHESTRATOR_ROOT)\" \"$(ORCHESTRATOR_BRANCH)\""; \
		echo "[dry-run] git -C \"$$TARGET_WORKTREE\" stash push -u -m \"$$STASH_MSG\" (if dirty)"; \
		echo "[dry-run] git -C \"$$TARGET_WORKTREE\" reset --hard FETCH_HEAD && git -C \"$$TARGET_WORKTREE\" clean -fd (if lane has no unique commits)"; \
		echo "[dry-run] git -C \"$$TARGET_WORKTREE\" rebase FETCH_HEAD (if lane has unique commits)"; \
	else \
		if [ -n "$$TOOLING_FILES" ]; then \
			ROOT_TOOLING_DIRTY="$$(git -C "$(ORCHESTRATOR_ROOT)" status --porcelain=v1 --untracked-files=all -- $$TOOLING_FILES 2>/dev/null || true)"; \
			if [ -n "$$ROOT_TOOLING_DIRTY" ]; then \
				echo "Orchestrator workflow tooling has uncommitted changes. Commit them on root before refreshing worker lanes."; \
				printf '%s\n' "$$ROOT_TOOLING_DIRTY"; \
				exit 1; \
			fi; \
		fi; \
		DID_STASH=0; \
		DIRTY="$$(git -C "$$TARGET_WORKTREE" status --porcelain=v1 --untracked-files=all)"; \
		if [ -n "$$DIRTY" ]; then \
			echo "Stashing dirty lane state before refresh..."; \
			git -C "$$TARGET_WORKTREE" stash push -u -m "$$STASH_MSG" >/dev/null; \
			DID_STASH=1; \
		fi; \
		git -C "$$TARGET_WORKTREE" fetch "$(ORCHESTRATOR_ROOT)" "$(ORCHESTRATOR_BRANCH)"; \
		AHEAD_COUNT="$$(git -C "$$TARGET_WORKTREE" rev-list --count FETCH_HEAD..HEAD)"; \
		if [ "$$AHEAD_COUNT" = "0" ]; then \
			git -C "$$TARGET_WORKTREE" reset --hard FETCH_HEAD; \
			git -C "$$TARGET_WORKTREE" clean -fd; \
		else \
			AHEAD_COMMITS="$$(git -C "$$TARGET_WORKTREE" rev-list --reverse FETCH_HEAD..HEAD)"; \
			SUPERSEDED_COUNT=0; \
			IGNORED_COUNT=0; \
			for commit in $$AHEAD_COMMITS; do \
				subject="$$(git -C "$$TARGET_WORKTREE" log -1 --format=%s "$$commit")"; \
				if git -C "$$TARGET_WORKTREE" log FETCH_HEAD --format=%s | grep -Fqx "$$subject"; then \
					SUPERSEDED_COUNT=$$((SUPERSEDED_COUNT + 1)); \
					continue; \
				fi; \
				if [ -n "$(LANE_COMMIT_PATHS)" ]; then \
					COMMIT_FILES="$$(git -C "$$TARGET_WORKTREE" show --name-only --pretty='' "$$commit" | awk 'NF')"; \
					HAS_OWNED_FILE=0; \
					for file in $$COMMIT_FILES; do \
						for prefix in $(LANE_COMMIT_PATHS); do \
							case "$$file" in \
								$$prefix|$$prefix/*) HAS_OWNED_FILE=1; break ;; \
							esac; \
						done; \
						if [ "$$HAS_OWNED_FILE" = "1" ]; then \
							break; \
						fi; \
					done; \
					if [ "$$HAS_OWNED_FILE" = "0" ]; then \
						IGNORED_COUNT=$$((IGNORED_COUNT + 1)); \
					fi; \
				fi; \
			done; \
			if [ $$((SUPERSEDED_COUNT + IGNORED_COUNT)) = "$$AHEAD_COUNT" ]; then \
				echo "Lane commits are already integrated upstream or out of lane scope. Resetting lane to $(ORCHESTRATOR_BRANCH)."; \
				git -C "$$TARGET_WORKTREE" reset --hard FETCH_HEAD; \
				git -C "$$TARGET_WORKTREE" clean -fd; \
			elif ! git -C "$$TARGET_WORKTREE" rebase FETCH_HEAD; then \
				git -C "$$TARGET_WORKTREE" rebase --abort >/dev/null 2>&1 || true; \
				echo "Lane refresh failed during rebase. Root left untouched."; \
				echo "Resolve conflicts in the lane, then rerun lane-refresh."; \
				if [ "$$DID_STASH" = "1" ]; then \
					echo "Restoring stashed work..."; \
					if git -C "$$TARGET_WORKTREE" stash pop >/dev/null 2>&1; then \
						echo "Stashed changes restored."; \
					else \
						echo "WARNING: Stash pop had conflicts. Inspect with: git -C \"$$TARGET_WORKTREE\" stash list"; \
					fi; \
				fi; \
				exit 1; \
			fi; \
		fi; \
		echo "Lane refreshed against $(ORCHESTRATOR_BRANCH)."; \
		echo "Worker tooling now reflects committed orchestrator branch state only."; \
		if [ "$$DID_STASH" = "1" ]; then \
			echo "Restoring stashed work..."; \
			if git -C "$$TARGET_WORKTREE" stash pop >/dev/null 2>&1; then \
				echo "Stashed changes restored cleanly."; \
			else \
				echo "WARNING: Stash pop had conflicts. Resolve them manually:"; \
				echo "  cd \"$$TARGET_WORKTREE\""; \
				echo "  git diff   # inspect conflict markers"; \
				echo "  git checkout --theirs/--ours <file>   # or edit manually"; \
				echo "  git stash drop   # after resolving"; \
			fi; \
		fi; \
		git -C "$$TARGET_WORKTREE" status -sb; \
	fi

lane-clean: lane-guard
	@set -eu; \
	TARGET_WORKTREE="$(LANE_WORKTREE_TARGET)"; \
	TOOLING_FILES="$(LANE_TOOLING_PATHS) $(LANE_APP_TOOLING_PATHS)"; \
	if [ "$(DRY_RUN)" = "1" ]; then \
		echo "[dry-run] git -C \"$$TARGET_WORKTREE\" restore --source=HEAD --staged --worktree -- $$TOOLING_FILES"; \
		echo "[dry-run] git -C \"$$TARGET_WORKTREE\" clean -fd -- docs/agentic/templates scripts/worktree-lane"; \
	else \
		if [ -n "$$TOOLING_FILES" ]; then \
			git -C "$$TARGET_WORKTREE" restore --source=HEAD --staged --worktree -- $$TOOLING_FILES 2>/dev/null || true; \
		fi; \
		git -C "$$TARGET_WORKTREE" clean -fd -- docs/agentic/templates scripts/worktree-lane 2>/dev/null || true; \
		git -C "$$TARGET_WORKTREE" status -sb; \
	fi

lane-path: lane-guard
	@printf '%s\n' "$(LANE_WORKTREE)"

lane-commits: lane-guard lane-orchestrator-guard
	@set -eu; \
	COMMITS="$$(git rev-list --reverse HEAD..$(LANE_BRANCH))"; \
	if [ -z "$$COMMITS" ]; then \
		echo "No commits to intake from $(LANE_BRANCH)."; \
	else \
		git log --oneline --reverse HEAD..$(LANE_BRANCH); \
	fi

lane-intake: lane-guard lane-orchestrator-guard
	@set -eu; \
	if ! git diff --quiet || ! git diff --cached --quiet || [ -n "$$(git ls-files --others --exclude-standard)" ]; then \
		echo "Orchestrator root is dirty. Commit, stash, or clean it before lane intake."; \
		exit 1; \
	fi; \
	REPORT_JSON="$$($(MCP_CMD) $(MCP_STATE_ARGS) lane-report-list --task-ref "$(TASK)" --lane-id "$(LANE)" --limit 1)"; \
	REPORT_SUMMARY="$$(printf '%s' "$$REPORT_JSON" | python3 -c 'import json,sys; data=json.load(sys.stdin); reports=data.get("reports", []); print(reports[0].get("summary","")) if reports else print("")')"; \
	REPORT_MERGE_READY="$$(printf '%s' "$$REPORT_JSON" | python3 -c 'import json,sys; data=json.load(sys.stdin); reports=data.get("reports", []); print(reports[0].get("merge_ready",0)) if reports else print(0)')"; \
	if [ "$$REPORT_MERGE_READY" != "1" ]; then \
		echo "Latest lane report for $(LANE) is missing or not merge-ready. Submit a merge-ready handoff before intake."; \
		exit 1; \
	fi; \
	COMMITS="$$(git rev-list --reverse HEAD..$(LANE_BRANCH))"; \
	if [ -z "$$COMMITS" ]; then \
		echo "No commits to intake from $(LANE_BRANCH)."; \
	elif [ "$(DRY_RUN)" = "1" ]; then \
		echo "Latest lane report summary: $$REPORT_SUMMARY"; \
		echo ""; \
		echo "Lane commits from $(LANE_BRANCH):"; \
		git log --oneline --reverse HEAD..$(LANE_BRANCH); \
		echo ""; \
		echo "[dry-run] create scratch worktree, cherry-pick $$COMMITS there, verify file scope against lane-owned paths, run lane-local verification, then fast-forward merge into $(ORCHESTRATOR_BRANCH)"; \
	else \
		TMP_PARENT="$$(mktemp -d "$${TMPDIR:-/tmp}/lane-intake-$(LANE)-XXXXXX")"; \
		SCRATCH_WORKTREE="$$TMP_PARENT/repo"; \
		SCRATCH_BRANCH="codex/intake-$(LANE)-$$(date +%s)"; \
		cleanup() { \
			git worktree remove --force "$$SCRATCH_WORKTREE" >/dev/null 2>&1 || true; \
			git branch -D "$$SCRATCH_BRANCH" >/dev/null 2>&1 || true; \
			rmdir "$$TMP_PARENT" >/dev/null 2>&1 || true; \
		}; \
		trap cleanup EXIT INT TERM; \
		echo "Latest lane report summary: $$REPORT_SUMMARY"; \
		echo ""; \
		echo "Lane commits from $(LANE_BRANCH):"; \
		git log --oneline --reverse HEAD..$(LANE_BRANCH); \
		echo ""; \
		git worktree add -b "$$SCRATCH_BRANCH" "$$SCRATCH_WORKTREE" HEAD >/dev/null; \
		if ! git -C "$$SCRATCH_WORKTREE" cherry-pick $$COMMITS; then \
			git -C "$$SCRATCH_WORKTREE" cherry-pick --abort >/dev/null 2>&1 || true; \
			echo "Lane intake hit a conflict in scratch worktree $$SCRATCH_WORKTREE. Orchestrator root was not modified."; \
			exit 1; \
		fi; \
		INTAKE_FILES="$$(git -C "$$SCRATCH_WORKTREE" diff --name-only HEAD~$$(echo $$COMMITS | wc -w | tr -d ' ')..HEAD)"; \
		ALLOWED_PATHS="$(LANE_COMMIT_PATHS)"; \
		SCOPE_VIOLATIONS=""; \
		for file in $$INTAKE_FILES; do \
			[ -n "$$file" ] || continue; \
			in_scope=0; \
			for prefix in $$ALLOWED_PATHS; do \
				case "$$file" in \
					$$prefix|$$prefix/*) in_scope=1; break ;; \
				esac; \
			done; \
			if [ "$$in_scope" -ne 1 ]; then \
				SCOPE_VIOLATIONS="$$SCOPE_VIOLATIONS\n  $$file"; \
			fi; \
		done; \
		if [ -n "$$SCOPE_VIOLATIONS" ]; then \
			echo "BLOCKED: Lane intake for $(LANE) contains out-of-scope files:"; \
			printf '%b\n' "$$SCOPE_VIOLATIONS"; \
			echo ""; \
			echo "The worker committed files outside the lane's allowed paths."; \
			echo "Fix in the worker worktree, then submit a new lane-handoff."; \
			exit 1; \
		fi; \
		if [ "$(SKIP_TESTS)" = "1" ]; then \
			echo "WARNING: SKIP_TESTS=1 — skipping scratch-worktree verification. Lane tests were NOT run before merge."; \
		else \
			if [ -n "$(LANE_TEST_CMD_1)" ]; then \
				if ! ( cd "$$SCRATCH_WORKTREE" && sh -lc '$(LANE_TEST_CMD_1)' ); then \
					echo ""; \
					echo "Lane intake ABORTED: verification step 1 failed in scratch worktree."; \
					echo "Fix the issue in the worker lane and submit a new lane-handoff."; \
					exit 1; \
				fi; \
			fi; \
			if [ -n "$(LANE_TEST_CMD_2)" ]; then \
				if ! ( cd "$$SCRATCH_WORKTREE" && sh -lc '$(LANE_TEST_CMD_2)' ); then \
					echo ""; \
					echo "Lane intake ABORTED: verification step 2 failed in scratch worktree."; \
					echo "Fix the issue in the worker lane and submit a new lane-handoff."; \
					exit 1; \
				fi; \
			fi; \
		fi; \
		git merge --ff-only "$$SCRATCH_BRANCH"; \
		$(MCP_CMD) $(MCP_STATE_ARGS) lane-upsert --lane-id "$(LANE)" --worktree-path "$(LANE_WORKTREE)" --branch "$(LANE_BRANCH)" --status merged --notes "Merged into $(ORCHESTRATOR_BRANCH) via scratch intake."; \
		echo "Lane $(LANE) intake completed cleanly via scratch worktree."; \
	fi
