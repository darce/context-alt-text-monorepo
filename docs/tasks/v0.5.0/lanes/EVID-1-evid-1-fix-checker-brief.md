# EVID-1 lane brief — `evid-1-fix-checker`

Task: EVID-1 · Branch: `feature/evid-1-fix-checker` (from `feature/evid-1`) · Worktree: `/Users/daniel/Development/context-alt-text-monorepo-evid-1-fix-checker`
Title: EVID-1 checker: gpu_burst_evidence.py audit/receipt/window correctness
New finding-id range reserved for this lane (only if you must file new ones): `EVID-1-CHE-01..20`.

## Objective

Close the 14 open findings below with tests. Verification command: `python3 -m pytest scripts/test_gpu_burst_evidence.py -q`.

## Owned paths

- `scripts/gpu_burst_evidence.py`
- `scripts/test_gpu_burst_evidence.py`

## Design notes

Split `check_bundle` (EVID1E-M-07) into pure per-concern checkers (manifest, window, artifacts, audit sequence, receipts) that each return a list of violations; `check_bundle` composes them. Build test fixtures in the canonical OCI Audit CloudEvents shape (EVID1E-M-06) and keep the old shape only if the checker explicitly supports both — otherwise reject with a named error ([rg-015]).

## Findings to close

This lane's scope was the fourteen checker findings tracked in handoff under `task_ref=EVID-1`:
EVID1E-H-01, EVID1E-H-03, EVID-1-R1-01, EVID-1-R1-02, EVID-1-R1-04, EVID1E-M-02, EVID1E-M-03, EVID1E-M-06, EVID1E-M-07, EVID1E-L-09, EVID-1-R1-05, EVID-1-R1-06, EVID-1-R1-07 and EVID1E-L-08.

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
