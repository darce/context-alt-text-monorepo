# LAND-1 lane brief — `land-1-reap-tool` round 2 (fix local review findings)

Task: LAND-1 · Branch: `feature/land-1` · Base: your own commit `15827465e` (reaper landed, 6 tests green). New ids, if you find more: `LAND-1-RT-04..20`.

## Findings to close

`LAND-1-RT-01`, `LAND-1-RT-02`, `LAND-1-RT-03`.

Read the live bodies, severities, and current status from handoff — this brief
deliberately does not copy them. A copy drifts the moment a finding is
reopened, deferred, or re-scoped, and handoff is the pre-merge gate's only
source of truth:

```python
from workbay_handoff_mcp import review_findings

review_findings(review={"operation": "list", "task_ref": "LAND-1", "status": "open"})
```

or `review_findings(review={"operation": "get", "finding_id": "LAND-1-RT-01"})` for one.

## Verification / constraints

- `python3 -m pytest scripts/test_worktree_reap.py -q` green (≥ 9 tests).
- `make -n worktree-reap worktree-reap-check REAP_PROTECT="a b"` resolves, and a protected path containing a space survives intact (REAP_PROTECT is newline-delimited and passed through the environment, never as make words).
- Owned paths unchanged: `scripts/worktree_reap.py`, `scripts/test_worktree_reap.py`, `mk/lane-maintenance.mk`, `Makefile`. Never edit `scripts/workbay_lifecycle/**`, `Makefile.d/**`, `config/lane-orchestration/**`, `docs/workbay/contracts/**`, `docs/workbay/rules/**`.
- No `--force`, no `branch -D`. Commit on `feature/land-1`, plain message, no attribution trailers. Report `FIXED: <id> <sha>` per finding.

Canon: [GRPH-03] reachability into the integration branch is the landed predicate · [RES-10] explicit fencing for shared resources · [RES-06] fail fast on the mutation, never on unrelated gates · [OBS-05] print the full list.
