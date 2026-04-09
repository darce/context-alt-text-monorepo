# Working-Tree Integrity and Multi-Process Coordination Assessment

> **Metadata**
>
> - **Date**: 2026-04-09
> - **Author**: Claude Opus 4.6 (1M context)
> - **Project**: `agent-handoff-mcp`
> - **Status**: Assessment (no implementation slice yet)
> - **Source incident**: AHMCP-15-BR-FIXES → AHMCP-16 silent `api.py` revert and the `session-bleed` stash@{1} that pre-dates it
> - **Related landed work**: AHMCP-16 (lifecycle robustness base slice), AHMCP-17 (`task-finish.sh` `expected_revision`), AHMCP-18 (working-tree integrity guards in `make context` + `make task-finish` + shell-execution smoke tests + `development-workflow.md` buffer-isolation section)
> - **Items in scope**: E (`working_tree_integrity_check` MCP tool), F (`changed_files` claim verification), G (`post_merge_integrity_check` tool), H (`path_holds` coordination primitive), I (out-of-band write attribution)

## Background

The AHMCP-18 base slice landed **detection** for working-tree integrity violations: `make context` warns on unexpected dirty paths, `make task-finish` refuses to archive when the working tree disagrees with HEAD, and a new shell-execution test suite (`tests/test_lifecycle_scripts.py`) catches bash-wrapper regressions. Those guards close the loop on **identifying** the AHMCP-15-BR-FIXES failure mode after it has already occurred.

This assessment captures the heavier architectural changes that would close the loop on **preventing** the failure mode in the first place, or on **attributing** it to a specific process when prevention fails. Five items are in scope, ranked from smallest to largest:

1. **E.** A `working_tree_integrity_check` MCP tool exposing the same logic as the bash-side guard so the pre-merge gate can call it.
2. **F.** Promote `changed_files` on a decision write from a hint to a claim — verify it against the actual diff and surface drift as a finding.
3. **G.** A `post_merge_integrity_check` MCP tool that callers run **immediately after** a merge to confirm the working tree matches HEAD.
4. **H.** A `path_holds` coordination primitive in the handoff DB so agents can claim exclusive write access to a path range.
5. **I.** Out-of-band write attribution: an `fswatch`-based daemon that records every PID that writes to the protected source dirs.

The assessment is NOT a task plan. It catalogs candidates and tradeoffs so a future planning slice can choose which items to convert into actual work.

---

## Source Incident Recap

Between 22:02:12 EDT (the AHMCP-16 fast-forward merge) and 22:11:21 EDT (the AHMCP-15-BR-FIXES fast-forward merge), the working tree of the root worktree silently reverted exactly 3 hunks of `packages/agent-handoff-mcp/src/agent_handoff_mcp/api.py` — the import re-export, the `TOOL_DESCRIPTIONS` entry, and the `ToolEntry` registration for `get_archived_task` that the AHMCP-16 commit had just added. Other AHMCP-16 changes (`config.py`, `__init__.py`, `import_export.py`, `core.py`, `tests/`) were untouched.

Forensic findings from the AHMCP-15-BR-FIXES post-mortem:

- **No git operation in the window**: `git reflog` shows only the two fast-forward merges. No `checkout`, `reset`, `restore`, `stash apply`, or `pull`.
- **No `agent-handoff-mcp` write in the window**: a wide-net query across `decisions`, `verified_tests`, `blockers`, `next_actions`, `review_findings`, `lane_messages`, `worker_reports`, `plan_cursors` returned only the 6 writes from the active claude session. Whatever modified `api.py` did not go through the handoff layer.
- **No active Codex thread for the project in the window**: the Codex `state_5.sqlite` `threads` table reports zero rows with `cwd=/Users/daniel/Development/context-alt-text-monorepo` updated between 22:00 and 22:30 EDT.
- **Bulk-touch pattern, not single Edit**: 48 files in the root worktree were touched between 22:07:56 and 22:08:56, most matching HEAD content (just touched, not modified). Only 4 files actually differ from HEAD: `CLAUDE.md`, `docs/agentic/instructions.md`, `docs/agentic/rules/development-workflow.md`, and `docs/epics/v0.4.0/public-demo-launch-readiness-epic.md` — exactly the docs the user has been editing in parallel.
- **Cache-correlated Codex plugin refresh**: `/Users/daniel/.codex/.tmp/plugins.sha` and `plugins/cache/openai-curated/github/...` were updated at 22:07:46 EDT, ~8 seconds before the `api.py` revert. The cache refresh itself is harmless, but its timing suggests a Codex CLI process was alive in the user's environment during the window even though no thread had `cwd` set to this repo.

The most consistent explanation that survives all the evidence: **a long-lived editor process held buffers from before the AHMCP-16 merge and flushed them all at once**, overwriting the merged content for the files whose buffers had unsaved edits. Stash@{1} on this checkout — `session-bleed accumulated working-tree at codex/e15-7-plan-fixes pre-merge stash 2026-04-08` — confirms the user has hit this same class of failure before and has named it.

---

## Item E: `working_tree_integrity_check` MCP Tool

### Problem

The bash-side integrity guard in `scripts/task-finish.sh` and the Python-side warning in `scripts/check-task-context.py` (both AHMCP-18) duplicate the same logic. The `handoff_close_check(enforce=True)` pre-merge gate cannot call either of them — it has no way to know whether the working tree agrees with HEAD when validating that a slice is ready to merge.

### Proposed surface

```python
def working_tree_integrity_check(
    workspace_root: str | None = None,
    expected_dirty: list[str] | None = None,
) -> dict:
    """Check tracked-but-modified files against an expected-dirty allowlist.

    Returns ok=True with an empty `unexpected_dirty` list when the working
    tree is clean (or only differs on `expected_dirty` paths). Returns
    ok=False with `unexpected_dirty=[...]` when integrity is violated.
    """
```

The implementation runs `git diff --name-only HEAD` against `workspace_root` (defaulting to the resolved primary worktree via `RuntimeConfig.for_repo`), reads `.task-state/dirty-allowlist` if `expected_dirty` is omitted, and returns the diff. Wire it into `handoff_close_check` as a new check (`working_tree_integrity`) so the pre-merge gate refuses to pass when integrity is violated.

### Cost

Small. The logic is already in two places; a third Python implementation in `packages/agent-handoff-mcp/src/agent_handoff_mcp/working_tree.py` (~50 lines) plus a `ToolEntry` registration in `api.py` and a new check in `handoff_close_check.py` (~30 lines).

### Tradeoffs

- **Pro**: Brings the pre-merge gate into the same defense layer as `make context` and `make task-finish`. An agent that bypasses the bash scripts (e.g. by calling `archive_task_state` directly) still hits the gate via the MCP tool.
- **Con**: Adds one more tool to the registry (currently 18 → 19). The token cost is small (the description fits in ~200 chars).
- **Risk**: If the `dirty-allowlist` file diverges between the bash side and the Python side (unlikely — both read the same file), agents will see different verdicts from `make task-finish` vs `handoff_close_check`. Mitigation: the MCP tool reads exactly the same file.

---

## Item F: `changed_files` Claim Verification

### Problem

`record_event(event_kind="decision", changed_files=[...])` and `close_slice(changed_files=[...])` accept a list of files the agent claims to have changed in the slice. Today this is a **hint** stored on the row (`decisions.changed_files_json`) for later inspection. Nothing verifies that the listed files were actually changed, or that no other files were changed.

This means an agent could record `clo_slice_complete_AHMCP-X_my_slice` with `changed_files=["a.py"]` while the actual diff includes `b.py` and `c.py`. The audit trail says "AHMCP-X touched only a.py" but reality says otherwise. In the AHMCP-15-BR-FIXES incident, the api.py revert was an unauthorized side effect that no decision row claimed.

### Proposed surface

When a decision write arrives with `changed_files=[...]`, the write path:

1. Resolves the previous slice-complete decision's `commit_sha` for the same task (or merge-base if no previous slice).
2. Runs `git diff --name-only <prev_sha> HEAD` to get the actual changed-file set.
3. Compares against `changed_files`. If they disagree, attach a `changed_files_drift` warning to the decision response **and** open a new review finding tagged `<task>-CFD-<n>` with severity `medium` so the drift is audited.

The check is best-effort: it only fires when both `commit_sha` and `changed_files` are populated, and only when a previous slice anchor exists. It does not block the write.

### Cost

Medium. Requires a new `_compute_decision_diff` helper in `decisions.py` (~80 lines), a new finding-emission code path in the decision write, and tests covering the agree / disagree / no-anchor cases.

### Tradeoffs

- **Pro**: Turns `changed_files` from documentation into a trustable claim. Catches the AHMCP-15-BR-FIXES failure mode at decision-write time, even if the agent that did the unauthorized write was not the one recording the decision.
- **Con**: Requires the agent to actually populate `changed_files`, which most decisions today omit. Without adoption the check is silent.
- **Risk**: False positives when slices include automated formatter runs that touch files outside the agent's intent. Mitigation: a `<task>-CFD-N` finding with `severity=medium` and clear rationale lets the agent close it as `wontfix` with one click.

---

## Item G: `post_merge_integrity_check` MCP Tool

### Problem

The pre-merge gate validates **intent** (review pass, findings closed, slice decision recorded, fresh tests, status=done). It runs **before** the merge. There is no equivalent check that validates **outcome** after the merge fast-forwards. If a stale editor buffer flushes 30 seconds after `git merge --ff-only`, the gate has already passed and nothing notices the regression until a downstream operation fails on it.

### Proposed surface

```python
def post_merge_integrity_check(
    merged_sha: str,
    expected_changed_files: list[str],
    workspace_root: str | None = None,
) -> dict:
    """Verify the working tree at HEAD matches the merge expectation.

    After a merge fast-forward, runs `git diff --name-only HEAD` and
    asserts the result is a subset of `expected_changed_files`. Returns
    `ok=False` with the divergence list when the working tree has been
    modified outside the expected change set since the merge committed.
    """
```

Callers run this **immediately after** `git merge --ff-only` and before `make task-finish`. The expected-changed-files list comes from the slice-complete decision's `changed_files` (item F's promotion makes this trustworthy). On failure, the caller decides whether to abort or restore the divergent files via `git checkout HEAD --`.

### Cost

Small. Mostly a wrapper around `git diff` plus a `RuntimeConfig.for_repo` resolution. ~40 lines of implementation, ~5 tests.

### Tradeoffs

- **Pro**: Closes the post-merge half of the integrity loop. Combined with item E, every transition (slice-complete write, pre-merge gate, post-merge audit) runs the same logic.
- **Con**: Requires callers to know to call it. Could be made automatic by integrating it into the `make task-finish` flow (effectively folding into AHMCP-18 item B retroactively).
- **Risk**: The "expected changed files" come from a decision the agent wrote. If item F is not landed, this tool relies on a hint, not a claim, and false negatives are likely.

---

## Item H: `path_holds` Coordination Primitive

### Problem

The handoff DB tracks tasks, decisions, findings, lanes, and lifecycle, but it has no concept of **"agent X holds an exclusive write lock on path Y until time Z."** The closest existing primitive is `worktree_lanes`, which scopes work to a branch and a worktree but does not prevent two agents from touching the same file in the same root worktree.

This matters specifically for the failure mode the source incident exhibited: a long-lived editor in the root worktree and a Claude agent in a linked worktree both writing to `packages/agent-handoff-mcp/src/agent_handoff_mcp/api.py` over a 5-minute window. There is no agent-layer mechanism that would have detected the conflict in real time.

### Proposed surface

A new `path_holds` table:

```sql
CREATE TABLE path_holds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path_glob TEXT NOT NULL,
    holder_agent TEXT NOT NULL,
    holder_session TEXT NOT NULL,
    holder_branch TEXT,
    holder_lane_id TEXT,
    acquired_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    released_at TEXT,
    reason TEXT
);
```

And tools:

```python
def acquire_path_hold(path_glob: str, ttl_seconds: int, reason: str, ...) -> dict
def release_path_hold(hold_id: int, ...) -> dict
def list_path_holds(path: str | None = None, ...) -> dict
```

Every write-side MCP tool (`record_event`, `set_handoff_state`, `record_review_finding`, etc.) calls `list_path_holds(path=...)` and emits a warning when its `actor.branch` or `actor.lane_id` does not match the holder. The handoff write path remains non-blocking — warnings only.

A `pre_write_check` integration: when a slice-complete decision lists `changed_files`, the DB enforces that those paths are either unheld or held by the writing agent.

### Cost

High. New schema migration, new table, new tools (3 minimum), and coordinated changes across every write path that should respect holds. The warning emission is cheap; the integration with every write path is the expensive part. ~300 lines of implementation, ~15 tests.

### Tradeoffs

- **Pro**: First real coordination primitive for multi-agent / multi-process flows in the same root worktree. Necessary if the project ever runs more than 2-3 concurrent agents on the same physical repo.
- **Con**: Adds friction. Agents must remember to acquire holds before editing. Forgotten releases create stale rows that need cleanup. Bash-side editors do not participate at all (they cannot acquire holds), so this only protects agent-vs-agent conflicts, not agent-vs-editor.
- **Risk**: Significant. The schema cost is permanent, and adoption requires every write tool to participate. **Recommend deferring until items E + F + G prove the simpler measures are insufficient.** A live failure mode that path holds would have prevented but the simpler measures did not catch is the right trigger to revisit this.

---

## Item I: Out-of-Band Write Attribution Daemon — LANDED IN AHMCP-19

> **Status: implemented.** AHMCP-19 added `scripts/integrity-watcher.sh`, the `make integrity-watch` target, and three smoke tests under `tests/test_lifecycle_scripts.py`. The implementation matches the proposed surface in this section, and `AHMCP-16-FU-02` was closed in the same slice using the watcher as the verification path. The remainder of this section is preserved as the design rationale.

### Problem

When the AHMCP-15-BR-FIXES api.py revert happened, **the trail went cold**. Handoff DB had no clue. Git reflog had no clue. Codex state DB had no active thread. The cause is still unidentified at the time of this assessment. The most likely explanation is a stale editor buffer flush, but there is no positive evidence for that or any other process.

The only way to root-cause the next incident with confidence is to **capture every write to the protected source dirs at the OS level**, naming the responsible PID and command line.

### Proposed surface

A new optional tool: `scripts/integrity-watcher.sh`. Wraps `fswatch -o packages/agent-handoff-mcp/src packages/agent-orchestrator-mcp/src` and on every event records:

- The watched path
- The current `git rev-parse HEAD` and `git rev-parse --abbrev-ref HEAD`
- The list of changed files via `git diff --name-only HEAD`
- The output of `lsof -t <path>` to identify any process currently holding the file
- A timestamp and the watcher's own session id

Output goes to `.task-state/integrity-watcher.jsonl` (one event per line), and the watcher runs as a per-session daemon started by `make context` (or as a manual `make integrity-watch` target).

When an integrity violation later fires from `make context` or `make task-finish`, the watcher log can be replayed to find the exact event (and PID) that wrote the divergent file.

### Cost

Small (script). Medium (operational). The script is ~60 lines of bash. The operational cost is the per-session daemon — needs to start with `make context`, stop on session end, and not leak processes across sessions. `fswatch` is a runtime dependency (Homebrew install on macOS, separate package on Linux).

### Tradeoffs

- **Pro**: When integrity violations recur, this is the only thing that will name the culprit. The AHMCP-15-BR-FIXES post-mortem dead-ended specifically because no such record exists.
- **Con**: Cost-of-running. A watcher that fires on every save in `packages/agent-handoff-mcp/src/` will accumulate many uninteresting events in normal use. The replay-on-violation flow keeps the cost manageable but only if the log is bounded (rotate after N MB).
- **Risk**: Low. The watcher is observation-only; it cannot break anything. The biggest risk is forgetting to start it — addressed by hooking it into `make context`.

---

## Recommended sequencing

If/when the project decides to convert any of this assessment into a task plan, the recommended order is:

1. **Item I first** (operational + cheap). ✅ **LANDED IN AHMCP-19.** `scripts/integrity-watcher.sh` and `make integrity-watch` are live. Run the watcher for one week to gather baseline data on what processes write to the protected dirs in normal use. This dataset is the ground truth for evaluating items E and F.

2. **Items E + G together**. They share the same `_check_working_tree_integrity` helper and integrate at the same write path (`handoff_close_check` for E, post-merge for G). Land them as a single AHMCP slice with the helper extracted into a new `working_tree.py` module.

3. **Item F as a follow-up**. Promote `changed_files` to a claim only after E + G are landed and the helper is reusable. Item F's value depends on `changed_files` being widely populated; without the upstream agents being trained to use it, the check is silent.

4. **Item H last, conditional**. Defer until either (a) E + F + G prove insufficient at catching a real incident, or (b) the project moves to a multi-agent topology where two agents in the same root worktree become routine. The schema cost is permanent and the adoption cost is high; both should be earned by evidence.

## Out of scope for this assessment

- **Editor-side mitigations** (auto-reload, save-on-focus-loss, etc.) are documented in `docs/agentic/rules/development-workflow.md` § Concurrent Editor Buffers, landed in AHMCP-18. They are doc-only and require user action; nothing for the codebase to enforce.
- **Cross-package application of `RuntimeConfig.for_repo`**: 9 call sites in `packages/agent-orchestrator-mcp/` still use `RuntimeConfig.for_workspace(...)` with explicit per-worktree state overrides. This is a parallel bug class to the AHMCP-16 fix in agent-handoff-mcp, but each call site needs case-by-case analysis (some legitimately want per-instance state for daemon logs). Recommend filing as **AOMCP-4** rather than folding into this assessment, since the orchestrator package owns its own task ref space.

## References

- AHMCP-16 base slice: `RuntimeConfig.for_repo()` introduction, `task-start.sh` `expected_revision` fix, `make context` done-status warning, `get_archived_task` MCP tool.
- AHMCP-16-BR-01: `RuntimeConfig.from_args()` migration to `for_repo()` (closed before AHMCP-16 merged).
- AHMCP-17: `task-finish.sh` `expected_revision` fix.
- AHMCP-18: working-tree integrity guards in `make context` + `make task-finish`, shell-execution smoke tests for the lifecycle scripts, `development-workflow.md` § Concurrent Editor Buffers.
- AHMCP-19: integrity-watcher.sh + `make integrity-watch` (item I from this assessment). Closes `AHMCP-16-FU-02`.
- AHMCP-16-FU-02: closed in AHMCP-19 with `scripts/integrity-watcher.sh` as the verification path. Future api.py-revert-class incidents are now root-cause-able by replaying `.task-state/integrity-watcher.jsonl`.
