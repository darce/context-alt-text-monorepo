# EVID-1 lane brief — `evid-1-fix-checker` ROUND 2 (continuation, not a restart)

Task: EVID-1 · Branch: `feature/evid-1-fix-checker` · Worktree: `/Users/daniel/Development/context-alt-text-monorepo-evid-1-fix-checker`
New finding-id range if you must file new ones: `EVID-1-CHE-01..20`. Do not reuse any other id.

## Where round 1 stopped

Round 1 hit the 1800s wall clock and committed `a5a531b74 wip(offload): evid-1-fix-checker checkpoint 1`. That work is on your branch and is good: it replaced `_authoritative_audit_events` with `_audit_event_groups` / `_representative_audit_event` / `_audit_operation_events`, added `_event_timestamp_key`, and hardened `_parse_time`. The branch has since been merged up from `feature/evid-1` (HEAD `39e16d6fd7da16771c975cd477bbd0ff6ffb0f78`), which brought in the sibling exporter and make-wiring fixes.

**Do not redo round 1.** Start by running the suite, then triage each finding below as already-closed or still-open.

Baseline established locally at `39e16d6fd`: `python3 -m pytest scripts/test_gpu_burst_evidence.py -q` → **52 passed, 0 failed**. If your first run does not reproduce that, stop and report the delta before changing anything.

## Owned paths (unchanged)

- `scripts/gpu_burst_evidence.py`
- `scripts/test_gpu_burst_evidence.py`

Nothing else. The exporter (`scripts/deploy/lib/export-gpu-evidence.sh`) and the make wiring are already fixed and merged by sibling lanes — do not touch them. Where a finding says the same defect is "mirrored in the exporter", fix only the checker side and note the exporter as out of scope.

## Step 1 — triage (do this first, report before fixing)

For each id below, decide from the current code whether round 1 already closed it. Emit exactly one line per id:
`ALREADY-FIXED: <id> — <symbol/line evidence + the test that covers it>` or `STILL-OPEN: <id> — <what remains>`.

Likely already closed by checkpoint 1 (verify, do not assume): EVID-1-R1-01 (substring action match), EVID-1-R1-02 (missing resourceId accepted), EVID1E-M-03 (OverflowError on 1e308 timestamps), EVID1E-H-01 (extra successful START after a valid STOP).

## Step 2 — close what remains

This lane's remaining checker findings are tracked in handoff under `task_ref=EVID-1`:
EVID1E-H-03, EVID1E-M-02, EVID-1-R1-04, EVID1E-M-07, EVID1E-M-06, EVID1E-L-09,
EVID1E-L-08, EVID-1-R1-05, EVID-1-R1-06 and EVID-1-R1-07.

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

Do EVID1E-M-07 last, after the behavioural fixes, so a wall-clock cutoff cannot cost a
correctness fix. For `EVID-1-R1-05`, fix only the two files this lane owns; the third file it
names belongs to another lane.

## Verification

`python3 -m pytest scripts/test_gpu_burst_evidence.py -q` must end green with strictly more tests than the 52-test baseline. Report the final count.

## Rules

- TDD: each fix gets a test that fails before and passes after. Never weaken an existing test. Name one line whose removal makes your new test fail.
- Commit incrementally on `feature/evid-1-fix-checker` with plain messages. No attribution trailers of any kind. Land partial correct work rather than losing it to the wall clock — the behavioural fixes (H-03, M-02, R1-04) come before the refactor (M-07).
- Never edit `scripts/workbay_lifecycle/**`, `Makefile.d/**`, `config/lane-orchestration/**`, `docs/workbay/contracts/**`, `docs/workbay/rules/**`. Those paths are gitignored in the sandbox mirror and any edit there gets the whole patch rejected. If a fix needs a contract change, do the code side and print the wording under a `CONTRACT-DELTA:` heading.
- Per finding, print one line: `FIXED: <id> <40-char sha> <test name>` / `ALREADY-FIXED: <id> <evidence>` / `NOT-FIXED: <id> <why>`.
- Canon anchors: [RES-06] fail fast on malformed input · [RES-01]/[API-02] idempotent re-runs · [GRPH-27] closed status vocabulary · [OBS-05] expose the full list, not a count · [rg-015] a boundary adapter never invents contract metadata and never silently supports two shapes.
