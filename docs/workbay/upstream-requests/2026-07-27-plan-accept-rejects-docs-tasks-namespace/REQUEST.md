# Upstream request — `plan-accept` apply rejects consumer-root `docs/tasks/**` plans as `not_planning_namespace`

**Target repo:** `darce/agentic-protocol-monorepo` (workbay-system lifecycle runner; payload `scripts/workbay_lifecycle/`).
**Consumer:** `context-alt-text-monorepo` (package-mode install; runner vendored at `scripts/workbay_lifecycle/`).
**Observed:** repo HEAD `f1c4006a` (main), 2026-07-27. Reproduced against the vendored payload copy of `plan_baseline.py` / `plan_accept.py`.
**Session:** WBUX-5 planning gate → `pass` (0 open findings) → `make plan-accept TASK=WBUX-5` failed to land the baseline.

---

## Summary

`make plan-accept` correctly evaluates the plan as acceptance-ready (`acceptance_ready: true`, `latest_planning_verdict: "pass"`, `open_planning_findings: 0`) but the **apply step is unconditionally rejected** for any plan living in the consumer-repo-root `docs/tasks/**` namespace:

```json
{"ok": true, "command": "plan-accept", "task_ref": "WBUX-5",
 "acceptance_ready": true, "latest_planning_verdict": "pass", "open_planning_findings": 0,
 "baseline_status": "missing", "reason": "plan_baseline_missing",
 "applied": false,
 "apply_error": "plan_path_rejected: not_planning_namespace",
 "apply_skip_reason": "plan_path_rejected: not_planning_namespace"}
```

`docs/tasks/**` is the **canonical task-plan namespace** for this consumer — it is what `TASK_PLAN.template.md` targets, what the `planning-review` / `plan-analyze` skills review, and what `guard-task-plan-findings.py` scans (`docs/tasks/**`). Yet `plan-accept` can **never** land a `docs/tasks/**` baseline on `main`, so `task-start`, `review-ready`, and `handoff-close-check` are permanently stuck reporting `plan_baseline_missing` for every task whose plan follows the documented convention. The gate passes but the lifecycle cannot advance.

## Root cause

`scripts/workbay_lifecycle/handlers/plan_baseline.py`:

```python
PLANNING_DIR_PREFIXES: tuple[str, ...] = (   # lines 16-23
    "docs/scopes/", "docs/plans/", "docs/assessments/",
    "docs/adrs/", "docs/reviews/", "docs/tech-debt/",
)   # <-- omits "docs/tasks/"

def is_planning_path(path: str) -> bool:      # lines 55-62
    if any(path.startswith(prefix) for prefix in PLANNING_DIR_PREFIXES):
        return True
    if path.startswith("packages/"):          # <-- allows docs/tasks ONLY under packages/*
        parts = path.split("/")
        if len(parts) >= 5 and parts[2] == "docs" and parts[3] == "tasks":
            return True
    return False
```

`plan_accept.py::_validate_apply_plan_path` (lines 277-298) calls `is_planning_path`; a `False` result returns `"not_planning_namespace"`, which the handler surfaces as `plan_path_rejected` (line ~636) and refuses to apply.

The `packages/*/docs/tasks/` special-case is the tell: the authors already treat `docs/tasks/` as a planning namespace — they just scoped the allowance to package sub-trees and never added the consumer-repo-root form. `is_planning_path` is otherwise the same gate `review_ready.py` uses, so this omission is centralized in one predicate.

## Reproduction

```python
# pure-logic reproduction (is_planning_path has no external deps beyond the tuple)
>>> is_planning_path("docs/tasks/21.0/WBUX-5-workbench-2pane-roster-v1-task-plan.md")
False        # <-- rejected: not_planning_namespace
>>> is_planning_path("docs/plans/x.md")
True
>>> is_planning_path("packages/foo/docs/tasks/x.md")
True         # <-- proves docs/tasks IS intended as a planning namespace
```

No `plan-accept` argument avoids it: the namespace check is unconditional in the apply path, so `LIFECYCLE_ARGS="--local --plan docs/tasks/... --source-branch feature/..."` hits the same rejection.

## Ask (fix)

Add the consumer-repo-root task-plan namespace to the allowlist:

```python
PLANNING_DIR_PREFIXES: tuple[str, ...] = (
    "docs/scopes/", "docs/plans/", "docs/assessments/",
    "docs/adrs/", "docs/reviews/", "docs/tech-debt/",
    "docs/tasks/",   # canonical task-plan namespace (TASK_PLAN.template.md, guard-task-plan-findings.py)
)
```

One line, centralized in `is_planning_path`, so `plan-accept`, `review-ready`, and the baseline evaluator all agree. Please also add a `test_plan_accept_apply` case asserting `is_planning_path("docs/tasks/<n.n>/<ref>-task-plan.md")` is `True` and that apply lands the baseline for a root `docs/tasks/**` plan (the existing suite only exercises the `packages/*/docs/tasks/` and `docs/plans/` forms, so the gap is untested).

## Impact / workaround

- **Impact:** every task using the documented `docs/tasks/**` plan location is un-acceptable; the whole `plan-accept → task-start → close-check` chain is blocked despite a clean `pass`. High — it breaks the primary planning-lifecycle path for the canonical namespace.
- **Local workaround:** implementation can still proceed on the existing `feature/<ref>` worktree (plan is committed there); the missing on-`main` baseline degrades `task-start`/`close-check` to a `plan_baseline_missing` **warning**, not a hard stop. A stopgap patch to the vendored `PLANNING_DIR_PREFIXES` would unblock inline `--local` acceptance but is clobbered on the next `workbay-bootstrap update`, so the durable fix must land upstream.
