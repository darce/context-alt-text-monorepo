# Backend-Domain Lane Closure And Orchestration Retrospective

Date: 2026-03-21
Task: `remaining-sync-workbench-and-retention`
Lane: `backend-domain`
Worktree: `/Users/daniel/Development/context-alt-text-monorepo-rswr2-backend-domain`

## Executive Summary

The `backend-domain` lane was closed by the orchestrator after repeated non-converged review cycles, scope drift across unrelated concerns, and growing mismatch between lane status and actual runtime state.

The lane did produce potentially valuable partial work, but it was no longer safe to treat it as an active or trustworthy implementation path. The worktree remains on disk for manual salvage. It should not be auto-pruned, and its lane-only tooling and retention spillover should not be merged automatically.

## Closure Decision

The orchestrator performed these actions:

- stopped the active backend-domain worker with `worker-stop --force`
- closed open backend-domain messages `131`, `133`, and `134`
- updated the lane record to `status: closed`
- preserved the dirty worktree for later manual review instead of deleting it

Final lane note in MCP:

> Closed by orchestrator after repeated non-converged review cycles and scope drift. Dirty lane artifacts remain in the worktree for manual salvage; do not prune or merge lane-only tooling/retention spillover automatically.

## Final Observed State

At closure time:

- lane status: `closed`
- worker state: `stopped`
- worker summary: `Worker daemon stop requested via SIGKILL.`
- lane model: `gpt-5.4-mini`
- lane backend: `codex-subagent`
- reasoning effort: `low`

Latest observed run stats before shutdown:

- run id: `347d130e-c663-4398-bc97-009192acd442`
- last execution cycle observed: `2`
- last recorded execution timestamp: `2026-03-21T06:19:23.807200+00:00`
- latest turn tokens: `54,458`
- latest turn reasoning tokens: `29`
- cumulative tokens for that run snapshot: `1,267,428`
- cumulative reasoning tokens for that run snapshot: `519`

Important orchestration defect observed after stop:

- `worker_state` reported `stopped`
- but the worker lock still showed `held: true`
- and the stale PID `89975` remained in the lock payload

That is a real observability bug. Operators should not need to infer whether a lane is truly stopped by combining multiple contradictory fields.

## Why The Lane Failed To Converge

The backend-domain lane repeatedly expanded beyond a single coherent ownership slice.

Observed spillover in the lane worktree included all of the following categories at once:

- NameSuggestion cleanup
- retention provenance and schema version changes
- purge and retention policy changes
- HTTP retention router changes
- orchestration tooling changes under `scripts/mcp`
- lane-exec test changes
- docs and bootstrap changes

This made review convergence unlikely even after redispatch, because each new pass was operating on top of an already mixed worktree.

The open lane reports show that pattern clearly:

- report `62`: mixed `lane_exec` and purge/retention work
- report `63`: retention provenance and export schema work
- neither report was merge-ready
- both ended with `Review did not converge after 3 cycles.`

## Root Causes

### 1. Scope Enforcement Was Advisory, Not Hard

The redispatch brief narrowed ownership to a NameSuggestion slice, but the lane still carried a broader dirty diff. The worker could continue operating in a worktree whose existing state already violated the brief.

### 2. Redispatch Reused A Contaminated Worktree

Even when the prompt became narrower, the lane itself was not reset or isolated. That meant the next run inherited:

- unrelated changed files
- unresolved review residue
- prior partial implementations
- earlier conceptual drift

### 3. Review Exhaustion Did Not Trigger Automatic Escalation

The system allowed repeated review cycles to accumulate without forcing one of these outcomes:

- salvage now
- split the lane
- freeze and close
- require orchestrator decision before another pass

### 4. Runtime State Was Ambiguous

Even after stop, lane state could look partially live:

- lane records existed
- worker locks could remain marked held
- stale PID information stayed visible
- the last event did not make it immediately obvious whether the run was still active

This creates operator confusion and delays intervention.

### 5. Lane Ownership Boundaries Were Too Coarse

`backend-domain` owned a conceptually broad surface area:

- domain services
- infrastructure repositories
- exports
- retention interactions
- package exports

That was too much for a late-stage cleanup pass that was supposed to land a narrow fix.

## Recommended Orchestration Improvements

## 1. Enforce Owned-Path Write Barriers

When a lane is dispatched with a narrowed ownership set, the worker runtime should reject writes outside that allowlist unless the orchestrator explicitly reopens scope.

Recommended implementation:

- add an `owned_paths_enforced` mode to lane manifests
- before review, diff the lane against root
- fail the turn if touched files fall outside the current assignment
- emit a structured blocker like `scope_violation`

This would have stopped the backend-domain lane from silently carrying `scripts/mcp`, retention router, and purge changes in a NameSuggestion-only pass.

## 2. Redispatch Into Fresh Worktrees For Narrow Retries

If a lane has already drifted, a narrow redispatch should not reuse the same dirty worktree by default.

Recommended implementation:

- support `redispatch_mode: fresh_worktree`
- create a clean sibling worktree from root
- replay only explicitly accepted files or patches into that new lane
- archive the old contaminated lane as evidence

This gives the next worker a clean substrate instead of asking it to reason over residue from prior failed passes.

## 3. Add Automatic Escalation On Review Exhaustion

After `N` review cycles without convergence, the worker should stop and emit a required orchestrator decision, not continue normal lane reuse.

Recommended policy:

- after 2 non-converged review cycles, mark `attention_required: true`
- after 3 cycles, auto-transition to `needs_orchestrator_decision`
- require one of:
  - `salvage`
  - `split_lane`
  - `close_lane`
  - `promote_model`
  - `expand_scope`

This makes exhaustion a routing event instead of an opaque failure.

## 4. Make Worker Stop Semantics Authoritative

`worker-stop` should cleanly resolve all worker-state artifacts.

Required fixes:

- clear or rewrite the lockfile immediately on stop
- record a terminal event such as `worker_stopped`
- set `lock.held: false`
- null out dead PID references
- stamp `stopped_at`

The operator should never have to interpret `worker_state: stopped` while `lock.held: true`.

## 5. Distinguish Lane Status From Worker Status More Clearly

A lane can be:

- open
- blocked
- review
- closed

while a worker can be:

- executing
- reviewing
- waiting_for_orchestrator
- stopped

The pipeline should present both separately and derive a human-readable composite state such as:

- `closed / stopped`
- `blocked / waiting`
- `review / executing`
- `closed / stale-lock anomaly`

This is especially important for the planned orchestration TUI.

## 6. Add A Salvage-Then-Close Path

Some lanes fail as active execution paths but still contain useful implementation fragments.

Recommended addition:

- operator action: `salvage_and_close`
- steps:
  - freeze lane
  - classify touched files by ownership
  - generate candidate salvage groups
  - mark unsafe spillover explicitly
  - close lane while preserving worktree

This would turn what is currently a manual forensic process into a first-class workflow.

## 7. Split Domain Cleanup From Retention Provenance

The pipeline should not treat these as one lane objective:

- NameSuggestion duplicate/export cleanup
- retention provenance / disposal / schema-version work

They touch adjacent code, but they are not the same review unit.

Recommended lane split:

- `backend-domain-namesuggestion`
- `backend-domain-retention`

That keeps the review surface small and gives clearer ownership to findings.

## 8. Add Lane Health Heuristics

The orchestrator should mark a lane as unhealthy before it becomes expensive drift.

Suggested signals:

- touched file count grows outside owned slice
- repeated findings shift categories between cycles
- review cycles keep shrinking but never converge
- token usage grows while changed-file set remains broad
- open guidance messages accumulate on one lane

When these triggers fire, the orchestrator should recommend split, salvage, or closure.

## 9. Surface Dirty-Worktree Risk In The TUI

The TUI should expose:

- total changed files in lane
- changed files outside owned scope
- open message count
- latest report convergence outcome
- stale lock anomalies

That would have made the backend-domain lane’s condition obvious much earlier.

## Immediate Follow-Up Recommendations

1. Do not redispatch `backend-domain` again in its current worktree.
2. Manually inspect the saved worktree and salvage only coherent product slices.
3. Treat `scripts/mcp` and retention spillover in that lane as suspect unless separately reviewed.
4. Implement authoritative stop-state cleanup for worker locks.
5. Add owned-path diff enforcement before another narrow redispatch workflow is used.
6. Fold the composite lane/worker health model into the orchestration TUI implementation plan.

## Suggested Next Engineering Tasks

1. Add `scope_violation` enforcement in `scripts/mcp/lane_exec.py`.
2. Add a fresh-worktree redispatch mode in the orchestration pipeline.
3. Fix `worker-stop` to clear stale lock state.
4. Add an MCP action for `salvage_and_close`.
5. Expose composite lane health in the future TUI state model.
