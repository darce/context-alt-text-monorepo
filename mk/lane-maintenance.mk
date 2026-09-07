# =============================================================================
# Lane Maintenance (reset, refresh, clean, close, prune, path, commits, intake)
# =============================================================================

.PHONY: lane-reset lane-refresh lane-clean lane-close lane-prune lane-path lane-commits lane-intake worktree-reap worktree-reap-check worktree-reap-advise

POST_INTAKE_CHECK_CMD ?= $(MAKE) --no-print-directory check-all
REAP_PROTECT ?=
REAP_STRICT ?= 0

# REAP_PROTECT holds newline-separated branch or path values and is passed
# through the environment, never as make words. Word-splitting a path that
# contains a space turns the safety fence into two useless fragments.
worktree-reap: ## Dry-run: list linked worktrees whose branch is already landed in its parent (REAP_ARGS=--apply to remove)
	@REAP_STRICT="$(REAP_STRICT)" REAP_PROTECT="$(REAP_PROTECT)" $(PYTHON) scripts/worktree_reap.py --repo "$(CURDIR)" $(REAP_ARGS)

worktree-reap-check: ## Check for redundant worktrees (REAP_STRICT=1 fails on redundancy; inspection errors always fail)
	@REAP_STRICT="$(REAP_STRICT)" REAP_PROTECT="$(REAP_PROTECT)" $(PYTHON) scripts/worktree_reap.py --repo "$(CURDIR)" --check

# Advisory inside check-all. lane-intake runs check-all straight after merging
# a sub-lane, at which point that lane's worktree is REDUNDANT by definition:
# a hard gate here fails the very flow the reclaimer exists to clean up after.
# REAP_STRICT=1 restores the blocking behaviour.
worktree-reap-advise: ## Print the worktree reap table without failing the build
	@REAP_STRICT="$(REAP_STRICT)" REAP_PROTECT="$(REAP_PROTECT)" $(PYTHON) scripts/worktree_reap.py --repo "$(CURDIR)" --check; \
	status=$$?; \
	if [ "$$status" -eq 0 ]; then exit 0; fi; \
	if [ "$(REAP_STRICT)" = "1" ]; then exit "$$status"; fi; \
	echo "worktree-reap: advisory only (exit $$status; set REAP_STRICT=1 to fail)"

check-all: worktree-reap-advise

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
		echo "[dry-run] git -C \"$$TARGET_WORKTREE\" clean -fd -- docs/workbay/templates scripts/worktree-lane"; \
	else \
		if [ -n "$$TOOLING_FILES" ]; then \
			git -C "$$TARGET_WORKTREE" restore --source=HEAD --staged --worktree -- $$TOOLING_FILES 2>/dev/null || true; \
		fi; \
		git -C "$$TARGET_WORKTREE" clean -fd -- docs/workbay/templates scripts/worktree-lane 2>/dev/null || true; \
		git -C "$$TARGET_WORKTREE" status -sb; \
	fi

lane-close: lane-guard lane-orchestrator-guard
	@set -eu; \
	LANE_JSON="$$( $(MCP_CMD) $(MCP_STATE_ARGS) lane-list --task-ref "$(TASK)" --status all --limit 200 )"; \
	LANE_FIELDS="$$(printf '%s' "$$LANE_JSON" | python3 -c 'import json,sys; data=json.load(sys.stdin); lane_id=sys.argv[1]; row=next((lane for lane in data.get("lanes", []) if lane.get("lane_id") == lane_id), None); sys.exit(1) if row is None else None; print("\t".join([str(row.get("status", "") or ""), str(row.get("worktree_path", "") or ""), str(row.get("branch", "") or "")]))' "$(LANE)")" || { \
		echo "Lane $(LANE) is not registered for task $(TASK)."; \
		exit 1; \
	}; \
	IFS="$(printf '\t')" read -r LANE_STATUS LANE_WORKTREE LANE_BRANCH <<< "$$LANE_FIELDS"; \
	if [ -z "$$LANE_WORKTREE" ]; then LANE_WORKTREE="$(LANE_WORKTREE)"; fi; \
	if [ -z "$$LANE_BRANCH" ]; then LANE_BRANCH="$(LANE_BRANCH)"; fi; \
	if [ "$$LANE_STATUS" != "merged" ] && [ "$$LANE_STATUS" != "closed" ] && [ "$(FORCE)" != "1" ]; then \
		echo "Lane $(LANE) must be merged or closed before cleanup (current status: $$LANE_STATUS)."; \
		exit 1; \
	fi; \
	is_git_repo=0; \
	if [ -d "$$LANE_WORKTREE/.git" ] || [ -f "$$LANE_WORKTREE/.git" ]; then \
		is_git_repo=1; \
	fi; \
	if [ "$$is_git_repo" -eq 1 ] && [ "$(FORCE)" != "1" ]; then \
		DIRTY_STATE="$$(git -C "$$LANE_WORKTREE" status --porcelain=v1 --untracked-files=all 2>/dev/null || true)"; \
		if [ -n "$$DIRTY_STATE" ]; then \
			echo "Lane worktree is dirty. Commit or stash it before closing $(LANE)."; \
			printf '%s\n' "$$DIRTY_STATE"; \
			exit 1; \
		fi; \
	fi; \
	if [ "$(DRY_RUN)" = "1" ]; then \
		if [ "$(FORCE)" = "1" ]; then \
			echo "[dry-run] git -C \"$(ORCHESTRATOR_ROOT)\" worktree remove --force \"$$LANE_WORKTREE\""; \
			echo "[dry-run] git -C \"$(ORCHESTRATOR_ROOT)\" branch -D \"$$LANE_BRANCH\""; \
		else \
			echo "[dry-run] git -C \"$(ORCHESTRATOR_ROOT)\" worktree remove \"$$LANE_WORKTREE\""; \
			echo "[dry-run] git -C \"$(ORCHESTRATOR_ROOT)\" branch -d \"$$LANE_BRANCH\""; \
		fi; \
		echo "[dry-run] $(ORCHESTRATOR_ROOT)/scripts/worktree-lane close --orchestrator-root $(ORCHESTRATOR_ROOT) --task-ref $(TASK) --lane-id $(LANE) --worktree-path \"$$LANE_WORKTREE\" --branch \"$$LANE_BRANCH\""; \
		exit 0; \
	fi; \
	"$(ORCHESTRATOR_ROOT)/scripts/worktree-lane" close \
		--orchestrator-root "$(ORCHESTRATOR_ROOT)" \
		--task-ref "$(TASK)" \
		--lane-id "$(LANE)" \
		--worktree-path "$$LANE_WORKTREE" \
		--branch "$$LANE_BRANCH" \
		$(if $(filter 1,$(FORCE)),--force,)

lane-prune: lane-orchestrator-guard
	@set -eu; \
	LANES_JSON="$$( $(MCP_CMD) $(MCP_STATE_ARGS) lane-list --task-ref "$(TASK)" --status all --limit 200 )"; \
	LANES_TO_PRUNE="$$(printf '%s' "$$LANES_JSON" | python3 -c 'import json,sys; data=json.load(sys.stdin); lanes=[lane.get("lane_id", "") for lane in data.get("lanes", []) if lane.get("status") in {"merged", "closed"}]; print("\n".join([lane for lane in lanes if lane]))')"; \
	if [ -z "$$LANES_TO_PRUNE" ]; then \
		echo "No merged or closed lanes found for $(TASK)."; \
	else \
		while IFS= read -r lane_id; do \
			[ -n "$$lane_id" ] || continue; \
			$(MAKE) --no-print-directory lane-close TASK="$(TASK)" LANE="$$lane_id" DRY_RUN="$(DRY_RUN)" FORCE="$(FORCE)"; \
		done <<< "$$LANES_TO_PRUNE"; \
	fi; \
	if [ "$(DRY_RUN)" = "1" ]; then \
		echo "[dry-run] git -C \"$(ORCHESTRATOR_ROOT)\" worktree prune"; \
	else \
		git -C "$(ORCHESTRATOR_ROOT)" worktree prune; \
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
		echo "[dry-run] preserve CURRENT_TASK.json regeneration via lane-upsert and verify CURRENT_TASK sync with $(MCP_CMD) handoff-close-check"; \
		if [ "$(SKIP_POST_INTAKE)" = "1" ]; then \
			echo "[dry-run] skip post-intake cross-lane verification because SKIP_POST_INTAKE=1"; \
		else \
			echo "[dry-run] run post-intake verification from orchestrator root: $(POST_INTAKE_CHECK_CMD)"; \
		fi; \
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
		$(MCP_CMD) $(MCP_STATE_ARGS) lane-upsert --task-ref "$(TASK)" --lane-id "$(LANE)" --worktree-path "$(LANE_WORKTREE)" --branch "$(LANE_BRANCH)" --status merged --notes "Merged into $(ORCHESTRATOR_BRANCH) via scratch intake."; \
		CURRENT_TASK_PATH="$(ORCHESTRATOR_ROOT)/CURRENT_TASK.json"; \
		if ! $(MCP_CMD) $(MCP_STATE_ARGS) handoff-close-check --task-ref "$(TASK)" | python3 -c 'import json,sys; sys.exit(0 if json.load(sys.stdin).get("checks", {}).get("current_task_sync", {}).get("is_in_sync") else 1)'; then \
			echo "WARNING: lane-upsert completed but handoff close-check reported CURRENT_TASK.json out of sync at $$CURRENT_TASK_PATH."; \
			$(MCP_CMD) $(MCP_STATE_ARGS) blocker --operation add --description "CURRENT_TASK.json sync verification failed after lane $(LANE) intake for task $(TASK)."; \
			exit 1; \
		fi; \
		if [ "$(SKIP_POST_INTAKE)" = "1" ]; then \
			echo "WARNING: SKIP_POST_INTAKE=1 — skipping post-intake cross-lane verification."; \
		else \
			if ! ( cd "$(ORCHESTRATOR_ROOT)" && sh -lc '$(POST_INTAKE_CHECK_CMD)' ); then \
				echo "WARNING: post-intake verification failed after merging lane $(LANE). The merge was kept; blocker recorded in MCP."; \
				$(MCP_CMD) $(MCP_STATE_ARGS) blocker --operation add --description "Post-intake verification failed after lane $(LANE) intake for task $(TASK). Rerun $(POST_INTAKE_CHECK_CMD) from the orchestrator root and fix the regression before further intake."; \
				exit 1; \
			fi; \
		fi; \
		echo "Lane $(LANE) intake completed cleanly via scratch worktree."; \
	fi
