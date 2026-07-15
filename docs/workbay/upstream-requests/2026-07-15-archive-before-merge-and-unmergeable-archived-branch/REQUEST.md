# Upstream request — a task can be archived `done` with its branch unmerged, and the gate then has no path to merge it

**Target repo:** `darce/mcp-workbay-handoff` (archive / task-status write path) + `darce/workbay` (`workbay-system` lifecycle handlers).
**Consumer:** `context-alt-text-monorepo` (package-mode install).
**Affected release:** `mcp-workbay-handoff==0.2.0`, `workbay-system==0.3.16`, `workbay-bootstrap==0.3.17`, `workbay-protocol==0.2.2`.

## Summary

`UXP-1` was archived with `status=done`. Its branch `feature/uxp-1` had **1,443 lines across 10 files that never reached `main`** — the task's entire output (a UX assessment, the scope decomposition four downstream tasks are derived from, an audit report, and vendored lexicons). `DASHBOARD.txt` reported the task done for eight days. Nothing flagged it.

The state was found by accident: a downstream task plan cited `docs/scopes/uxp-ux-pass-decomposition.md`, and the path did not exist on `main`.

Three defects compound. **Defect 1 creates the state; Defects 2 and 3 make it unrecoverable through the gate**, which forces the operator to bypass the gate — the same class of bypass that produces orphan branches in the first place.

---

## Defect 1 — `archive` / `update_task_status(done)` never checks whether the branch landed

Neither write path consults git. Grepping `workbay_handoff_mcp` for merge-awareness in the archive/status path returns nothing: `merged` appears only in `review_findings_api.py:220` (findings-merge provenance) and `lanes_api.py:16-17` (`LaneStatus`), never in the task-status or archive path.

The vocabulary already exists one layer down and is not used one layer up:

```python
# lanes_api.py:16-17
LaneStatus = Literal["planned", "active", "blocked", "review", "merged", "closed"]
CloseLaneStatus = Literal["closed", "merged"]
```

A **lane** can be closed as `merged` — the model knows the difference between "finished" and "landed". A **task** cannot: `done` conflates them. So `update_task_status(task_ref, status="done")` followed by `archive` is accepted with the branch entirely unmerged, and the dashboard renders the archived snapshot's `done` forever (per the documented behavior that archiving preserves whatever status the task had).

This is the actual bug. Everything below is fallout.

**Ask:** on `update_task_status(status="done")` and on `archive`, resolve the row's `target_branch` and test whether its head is an ancestor of the integration ref (`git merge-base --is-ancestor`). If it is not, emit a **blocker or a loud warning naming the unmerged commit count** — the same fail-closed posture the SHA-provenance and branch-enforcement guards already take on writes. A silent `done` on unmerged work defeats the purpose of the pre-merge gate: the gate guards the merge, but nothing guards *skipping* the merge.

If a deliberate archive-without-merge is legitimate (abandoned spike, superseded task), it should be an explicit status — `abandoned`, or `done` plus an explicit `unmerged_ok=True` — not the silent default.

## Defect 2 — `close-check` on an archived ref emits `no_active_task_row`, and its remediation is unactionable

`close_check.py:139-160` derives `missing_row` from `local_live_handoff_row_exists()` / `_query_active_task_identity()`. An archived task has **no live row by construction**, so any archived ref on a feature branch trips:

```
reasons: ["stale_test_evidence", "no_active_task_row"]
warnings: ["no_active_task_row: no resolvable active handoff row on a feature branch
            — run `make task-start` or pass explicit --task-ref"]
```

Two problems:

1. **The remediation was already followed.** This run *was* `close-check --json --task-ref UXP-1`. The explicit ref resolved well enough to evaluate findings and mergeability against `UXP-1` — the same response carries `findings_open: {high:0,...}` and `mergeable: true` — yet the warning tells the operator to pass the flag they just passed. `args.explicit_task_ref` is consulted for the *ambiguity* probe immediately below (`close_check.py:161-166`) but not for this branch.
2. **`make task-start` is wrong advice for an archived ref.** It would create a *new* task row, not recover the archived one.

**Ask:** when the ref resolves to an archive snapshot rather than a live row, say so — `archived_task_row` with remediation naming the actual options (reactivate, or disposition as an operator merge). Distinguish "no such task" from "task exists but is archived"; they need different fixes. At minimum, suppress the "pass explicit `--task-ref`" clause when `explicit_task_ref` is not `None`.

## Defect 3 — `stale_test_evidence` has no notion of whether the diff has a runtime surface

`review_ready.py:637-638`:

```python
latest_sha, evidence_ok = _query_latest_passing_test_sha(repo, task_ref)
if evidence_ok and latest_sha != head:
    reasons.append("stale_test_evidence")
```

Unconditional on `latest_sha != head`. For a **docs-only** branch this is unsatisfiable in any meaningful sense: there is no test whose passing says anything about a markdown diff, so the operator either fabricates evidence to clear a gate (worse than bypassing it — it pollutes the audit trail) or bypasses.

Worse, it is *self-perpetuating*: dropping the lane-only `pyproject.toml` shim before merge — which the shim's own commit message instructs — advances HEAD and re-staleifies the evidence. Doing the right thing trips the gate.

**Ask:** exempt diffs with no runtime surface, or let the reason be discharged by an explicit `test_result` recorded as `not_applicable` with a rationale. The repo already has the concept — `make lint-task-plans` is the meaningful check for a docs diff. Precedent: `check_model_cache`-style probes elsewhere in this stack distinguish "checked and fine" from "nothing to check"; `stale_test_evidence` currently cannot.

---

## Combined effect

For an archived task with an unmerged docs branch there is **no gate-passing path at all**:

| Reason | Can the operator clear it? |
| --- | --- |
| `no_active_task_row` | Not without reactivating an archived task — which the warning doesn't mention |
| `stale_test_evidence` | Not on a docs diff without fabricating evidence |

`mergeable: true` and `findings_open: {high:0, medium:0, low:0}` throughout. The gate agrees the merge is safe and still cannot say yes.

The consumer resolved this by merging under explicit operator authorization and recording the gate output in the merge commit rather than silently bypassing it. That is the correct *recovery*, but it should not be the only route, and Defect 1 means nothing stops the next task from landing in the same state.

## Suggested priority

1. **Defect 1** — the integrity gap. Silent `done` on unmerged work is how orphan branches are manufactured, and it is invisible until something downstream trips over the missing path. Highest value; smallest change (one `merge-base --is-ancestor` at two write sites).
2. **Defect 2** — cheap, and the misleading remediation actively wastes operator time.
3. **Defect 3** — needs a small design decision (exemption vs. `not_applicable` evidence), so it is the least mechanical.

## Reproduction

```bash
# 1. Create a docs-only task, commit on its branch, do not merge.
make task-start TASK=repro-1 OBJECTIVE="docs only"
#    ... commit a markdown file on feature/repro-1 ...

# 2. Archive it as done. Observe: accepted, no warning about the unmerged branch.
#    update_task_status(task_ref="repro-1", status="done"); archive(...)

# 3. Try to merge it through the gate, from the branch worktree:
make close-check LIFECYCLE_ARGS="--json --task-ref repro-1"
# => ready: false
#    reasons: ["stale_test_evidence", "no_active_task_row"]
#    mergeable: true, findings_open: {high:0, medium:0, low:0}
#    warning tells you to pass --task-ref, which you just passed.
```

## Consumer-side note (not an upstream ask)

`docs/workbay/rules/`, `Makefile.d/`, and `scripts/{hooks,workbay,workbay_lifecycle}/` are gitignored and **absent on fresh feature-branch worktrees**, so `make close-check` / `make plan-analyze` fail with "No rule to make target" until they are rsynced from the root. Tracked separately under the overlay-materialization thread; noted here only because it obscured the diagnosis above — the first `close-check` attempt failed for overlay reasons and had to be re-run from the root, which then silently evaluated `main` instead of the feature branch and produced a third, misleading reason set (`on_protected_base`, `dirty_worktree`).
