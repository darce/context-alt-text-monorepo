# LAND-1 lane brief — `land-1-plan-review` (adversarial planning review, remote pass 2 of 2)

Task: LAND-1 · Branch: `feature/rev-land-1-plan-r2` (read-only review; commit nothing but a findings report is fine; the branch-review naming rule rejects `review/*` branches) · Subject: `docs/tasks/v0.5.0/LAND-1-inflight-worktree-landing-task-plan.md`.
Finding-id range reserved for this lane: `LAND-1-PR-10..PR-30`. Record findings with `review_findings` (`batch_record` when ≥3) on `task_ref=LAND-1`, `file_path` = the plan path, `details.line_start/line_end/fix` nested. Use the fallback sequence below if the MCP write path is unavailable.

If the MCP write path is unavailable, first use the repo-local Python API from the review checkout, not a hand-transcribed fallback:

```python
from workbay_handoff_mcp import review_findings

review_findings(review={
    "operation": "batch_record",
    "task_ref": "LAND-1",
    "findings": findings,
})
```

If that import or API call also fails, stop and report the concrete blocker. Only then may the reviewer print a fenced JSON block titled `UNRECORDED FINDINGS` (never plain `FINDINGS`), preserving the same fields so the coordinator can record it without implying that the DB write succeeded.

## What the plan does

Lands or retires 28 worktrees / 50 branches: reaps ancestor sub-lane worktrees (a new tracked `scripts/worktree_reap.py`), lands five live components through the pre-merge gate in a DAG whose cut vertex is the `gpulife-1-r3-wiring → gpuops-1` edge (both branches independently implemented the same `groupadd` fix), parks the stale August eval-harness branches under archive tags, and closes ~60 stale handoff rows. Local pass 1 recorded and fixed `LAND-1-PR-01..06` (reaper was placed in gitignored plugin paths; manifest treated as versioned; template sections missing; invented glob; missing symbol anchors; broken `plan-analyze`).

## Your lenses (be adversarial; a finding needs evidence, a line range, and a concrete fix)

1. **Failure modes** — Release It!: what happens when `git worktree remove` half-fails, when a parent branch is deleted before its sub-lane is classified, when two coordinators run the reaper concurrently, when the remote gate is red on one component. Does the plan bound every wait ([RES-02])? Does any step retry without idempotence ([RES-01])? Is there a fencing gap where two lanes own the same file ([RES-10])?
2. **Data integrity** — DDIA: is git truly the single source of truth for "landed", or does the plan let the DB or filesystem override it? Is derived state ever cached across runs ([FLOW-06])? Can a squash-merged branch be misclassified as live, or a rebased one as redundant when it carries unlanded work?
3. **Graph theory** — is the printed DAG actually acyclic? Are the connected components correct given the stated file intersections? Is the critical path the longest chain? Is anything serialised that could run in parallel, or parallelised that shares a file (colour conflicts, [GRPH-09])?
4. **Junior-agent implementability** — every cited path/symbol must exist on the branch it names; every step must be executable from the text alone; flag any invented API, make target, or MCP operation.
5. **Scope and risk** — the August-cluster parking: is "tag and keep" the right default; are the 143 deferred findings handled honestly; is anything destructive (`--force`, `branch -D`, `worktree remove` on a dirty tree) reachable?
6. **Template and rules** — TASK_PLAN.template.md conformance; finding bodies must not be pasted into the plan; lint findings never block merge; no attribution trailers.

## Output

- Findings via MCP using the required API fallback sequence above (`finding_id`, `severity` high|medium|low, `category` ANTIPATTERN|DEAD_CODE|COMPLEXITY|GAP, `file_path`, `description`, `details{line_start,line_end,fix}`); only an API failure permits the explicitly marked `UNRECORDED FINDINGS` block.
- One line verdict: `VERDICT: pass | pass_with_findings | conditional_pass | fail` with a one-sentence reason.
- Do not edit the plan. Do not run `--apply` of anything. Do not touch `scripts/workbay_lifecycle/**`, `Makefile.d/**`, `config/lane-orchestration/**`.

## Canon references available in the repo

`docs/workbay/rules/graph-theory-heuristics.md` (GRPH-01/02/03/05/06/09/31), `docs/workbay/rules/development-workflow.md` § Pre-Merge Gate, § Dirty Worktree Teardown, `docs/workbay/templates/TASK_PLAN.template.md`, `docs/workbay/rules/planning-review-guide.md`. Canon rule ids used in the plan: RES-01/02/06/07/10/12/14, API-02, FLOW-06, PERF-04/14, OBS-01/05.
