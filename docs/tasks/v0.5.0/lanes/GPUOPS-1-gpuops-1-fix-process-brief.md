# GPUOPS-1 lane brief — `gpuops-1-fix-process`

Task: GPUOPS-1 · Branch: `feature/gpuops-1-fix-process` (from `feature/gpuops-1`) · Worktree: `/Users/daniel/Development/context-alt-text-monorepo-gpuops-1-fix-process`
Title: GPUOPS-1 process: gate visibility, stock observation, lane-brief commit discipline, guard-test ownership
New finding-id range reserved for this lane (only if you must file new ones): `GPUOPS-1-PRO-01..20`.

## Objective

Close the 5 open findings below with tests. Verification command: `python3 scripts/hooks/guard-task-plan-findings.py --scan-staged || true`.

## Owned paths

- `docs/tasks/v0.5.0/GPUOPS-1-gpu-operator-control-and-named-captions-task-plan.md`
- `docs/tasks/v0.5.0/lanes/GPUOPS-1-_common.md`

## Design notes

A pre-tool hook rejects any task-plan edit containing three or more consecutive bullets that start with a finding id — describe work, never paste finding lists (see CLAUDE.md § Review Findings Placement). CANON-01: add a 'Live-safety gate' subsection to the plan stating that D1 findings (OPSGPU-H-01/02/03, OPSGPU-R3-01) are pre-merge blockers for the whole task, and that `handoff_close_check(enforce=True)` runs against GPUOPS-1, not a sub-lane. CANON-05: add the observable surface for the controlled stock ('an A10 is powered on and billing') — name the endpoint/field and the alert rule ([OBS-12]). VW-05 + DISP-04: in `_common.md` mandate incremental commits (every green test, ≤30 min) and define that a non-success outcome with commit_landed=true is 'partial-landed' and must be re-briefed against the landed SHA, never re-dispatched from scratch. CANON-02: name the owning lane for `scripts/deploy/tests/test_gpu_cost_runbook_matches_verified_state.py` in `_common.md` and print the manifest `owned_paths` line under `MANIFEST-DELTA:`.

## Findings to close

### GPUOPS-1-CANON-01 (high) — `docs/tasks/v0.5.0/GPUOPS-1-gpu-operator-control-and-named-captions-task-plan.md:None`

[RES-16/RLSE-12] Gate blindness: the D1 live-safety findings (OPSGPU-H-01/H-02/H-03, OPSGPU-R3-01) are filed on MAINT-reap-20260906, not on GPUOPS-1, which currently carries ZERO findings. handoff_close_check(enforce=True) on GPUOPS-1 therefore goes green while both live stop arms are non-functional on acx-backend: the installed units still pass the retired --load-json /run/acx/describe-load.json path, lack the flock and running-since lease, and prod compose does not mount the load path. The plan checklist also orders 'merge main' BEFORE 'operator precondition D1 confirmed done'. Net effect: a one-click Start for a ~$2/hr A10 can ship into an environment where idle reap and lease cap have never been observed working, with fakes as the only coverage. This finding is the gate binding: it must not be closed until D1 is confirmed done on the host.

### GPUOPS-1-CANON-05 (medium) — `docs/tasks/v0.5.0/GPUOPS-1-gpu-operator-control-and-named-captions-task-plan.md:None`

[OBS-12] The controlled stock is 'an A10 is powered on and billing', and no new surface observes it. C3's GET /scene/gpu/status reads gpu-state.json, which is written by the reaper itself, so if the reaper unit is dead - exactly D1's current live condition - the sensor freezes at its last value, the SPA steers on a corpse, and Start stays armed. C1's STOP arm is additionally conditioned on load.has_work sourced from describe-load.json, whose writer D1 records as non-functional in prod, and JobLoadSnapshot.untrustworthy fails closed toward busy, so a dead load sensor reads as 'do not stop'. Only the OCI API and the durable lease touch the real stock and neither is on the operator's status path. Needs a staleness bound on the snapshot that the status endpoint enforces, not merely reports.

### GPUOPS-1-VW-05 (high) — `docs/tasks/v0.5.0/lanes/GPUOPS-1-_common.md:None`

[process] Systemic, not incidental: every lane that returned a non-success outcome with commit_landed=true shipped at least one defect its own declared verify command would have caught (spa 62 failures, naming-toggle 1, naming-provenance-ui tsc exit 2). commit_landed is orthogonal to correctness, and the coordinator currently has no gate between 'the patch applied' and 'the lane branch is green'. Three of eight lanes needed local repair before they could be reviewed at all.

### GPUOPS-1-DISP-04 (medium) — `docs/tasks/v0.5.0/lanes/GPUOPS-1-_common.md:None`

Lane briefs do not mandate incremental commits, so a turn that hits the wall clock with correct work in the sandbox working tree loses all of it. gpuops-1-naming-gpu-tier wrote scene/tests/test_naming_provenance_gpu_tier.py covering six cases, then ended handoff_action=needs_guidance because a verification subprocess returned 'Resource temporarily unavailable'. The sandbox is discarded on timeout and turn.patch was 0 bytes, so the whole turn was lost.

### GPUOPS-1-CANON-02 (high) — `scripts/deploy/tests/test_gpu_cost_runbook_matches_verified_state.py:None`

[CLM-03] Guard-test ownership gap with no owner in the lane manifest. test_gpu_cost_runbook_matches_verified_state.py:73 asserts the literal string 'no automatic gpu cost cap' stays in docs/runbooks/oci-instance-state-and-cost.md, and a sibling assertion requires every reaper mention in that runbook to stay qualified as not-live (the runbook at :148 says 'Do not wait for a reaper to catch it - there is none installed'). GPUOPS-1 installs a live reaper and ships a confirm strip promising a 60-minute lease cap. Lane gpuops-1-installer owns docs/runbooks/ but NO lane owns this guard file, so the lane that must change the runbook cannot re-point the test. Either the suite fails at integration, or the repo ships a UI promising a cost cap while its own tested operator doc asserts none exists. Fix: add the guard to the installer lane's owned_paths and re-point it at the post-GPUOPS-1 truth in the same change as the runbook rewrite.


## Rules (all lanes)

- Work only inside the owned paths above. Never edit `scripts/workbay_lifecycle/**`, `Makefile.d/**`, `config/lane-orchestration/**`, `docs/workbay/contracts/**`, `docs/workbay/rules/**` (the last two are gitignored in the sandbox mirror and any edit there gets the whole patch rejected). If a fix needs a contract/rules/manifest change, do the code side and print the exact wording under a `CONTRACT-DELTA:` / `MANIFEST-DELTA:` heading in your final report.
- TDD: add or extend a test that fails before each fix and passes after. Never weaken an existing test. Mutation check: name one line whose removal makes your new test fail.
- Commit incrementally on the lane branch with plain messages; no attribution trailers. Land partial correct work rather than losing it to the wall clock.
- Close each finding: `review_findings(review={"operation":"resolve","task_ref":"<task>","finding_id":"<id>","status":"fixed","resolution_notes":"<what changed, test name>","verified_commit_sha":"<40-char sha>"})`. If no MCP write path exists in the sandbox, print one line per finding: `FIXED: <id> <sha> <test>`; `ALREADY-FIXED: <id> <evidence>`; `NOT-FIXED: <id> <why>`.
- Lint-only findings (`lint(ruff)`, `lint(mypy)`): fix them here; they never block a merge.
- Canon anchors: [RES-06] fail fast on malformed input · [RES-01]/[API-02] idempotent re-runs · [RES-02] every external wait bounded · [OBS-05] expose the full list, not a count · [SEC-*] never persist secrets/presigned tokens.
