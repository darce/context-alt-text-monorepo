# EVID-1 lane brief — `evid-1-fix-make`

Task: EVID-1 · Branch: `feature/evid-1-fix-make` (from `feature/evid-1`) · Worktree: `/Users/daniel/Development/context-alt-text-monorepo-evid-1-fix-make`
Title: EVID-1 make wiring: gpu-evidence.mk quoting and test-scripts registration
New finding-id range reserved for this lane (only if you must file new ones): `EVID-1-MAK-01..20`.

## Objective

Close the 3 open findings below with tests. Verification command: `make -n gpu-evidence-tests test-scripts`.

## Owned paths

- `mk/gpu-evidence.mk`
- `Makefile`

## Design notes

Pass make variables to the shell via single-quoted or `$(call ...)`-escaped arguments (EVID1E-M-04). Add `scripts/test_gpu_burst_evidence.py` to the explicit `test-scripts` pytest file list in `Makefile` (~line 553) rather than only chaining a prerequisite (EVID1E-M-08, EVID1E-L-07). Note: another lane (LAND-1) adds `scripts/test_worktree_reap.py` to the same list; keep your edit to a single added line so the merge is trivial.

## Findings to close

This lane's scope was the three make-wiring findings tracked in handoff under `task_ref=EVID-1`:
EVID1E-M-04, EVID1E-L-07 and EVID1E-M-08.

Read them live rather than from a copy here:

```
review_findings(review={"operation": "list", "task_ref": "EVID-1"})
```

Their bodies used to be pasted into this file. That duplicated the source of truth, escaped the
pre-merge gate (`handoff_close_check` audits only MCP-stored findings), and went stale the moment
a finding was reopened or re-classified. Findings live in handoff; a brief references them by id.
See the Review Findings Placement rule in `CLAUDE.md`.

If a future lane brief genuinely needs the finding text inlined — a remote sandbox is
history-stripped and cannot query handoff — write that brief under `.task-state/coord/briefs/`,
which is untracked and outside the scope of the task-plan guard. The rule is about placement, not
about whether an agent may ever read a finding body.


## Rules (all lanes)

- Work only inside the owned paths above. Never edit `scripts/workbay_lifecycle/**`, `Makefile.d/**`, `config/lane-orchestration/**`, `docs/workbay/contracts/**`, `docs/workbay/rules/**` (the last two are gitignored in the sandbox mirror and any edit there gets the whole patch rejected). If a fix needs a contract/rules/manifest change, do the code side and print the exact wording under a `CONTRACT-DELTA:` / `MANIFEST-DELTA:` heading in your final report.
- TDD: add or extend a test that fails before each fix and passes after. Never weaken an existing test. Mutation check: name one line whose removal makes your new test fail.
- Commit incrementally on the lane branch with plain messages; no attribution trailers. Land partial correct work rather than losing it to the wall clock.
- Close each finding: `review_findings(review={"operation":"resolve","task_ref":"<task>","finding_id":"<id>","status":"fixed","resolution_notes":"<what changed, test name>","verified_commit_sha":"<40-char sha>"})`. If no MCP write path exists in the sandbox, print one line per finding: `FIXED: <id> <sha> <test>`; `ALREADY-FIXED: <id> <evidence>`; `NOT-FIXED: <id> <why>`.
- Lint-only findings (`lint(ruff)`, `lint(mypy)`): fix them here; they never block a merge.
- Canon anchors: [RES-06] fail fast on malformed input · [RES-01]/[API-02] idempotent re-runs · [RES-02] every external wait bounded · [OBS-05] expose the full list, not a count · [SEC-*] never persist secrets/presigned tokens.
