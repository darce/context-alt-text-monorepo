# LAND-1 lane brief — `land-1-plan-fix` (planning-review remediation)

Task: LAND-1 · Branch: `feature/land-1-plan-fix` · Worktree: `/Users/daniel/Development/context-alt-text-monorepo-land-1-plan-fix`.
Finding-id range reserved for this lane: `LAND-1-PF-01..PF-20` (never reuse `LAND-1-PR-*`, `LAND1R-*`, `LAND-1-RT-*`).

## Objective

Amend the LAND-1 task plan so every finding below is answered in the document itself. This is a documentation lane: no code, no scripts, no Makefiles. A parallel lane (`land-1-reap-tool`) owns the reaper code findings (`LAND-1-PR-11/12/13/30`, `LAND-1-RT-01..03`) — do not touch `scripts/worktree_reap.py`, and when a plan sentence describes reaper behaviour, describe the *contracted* behaviour those findings mandate (missing-parent handling, branch-only refs, repo lock + expected-tip revalidation, half-failed removal recovery) rather than today's behaviour.

## Owned paths

- `docs/tasks/v0.5.0/LAND-1-inflight-worktree-landing-task-plan.md`
- `docs/tasks/v0.5.0/lanes/LAND-1-plan-review-brief.md`

Nothing else. Never edit `scripts/**`, `mk/**`, `Makefile`, `scripts/workbay_lifecycle/**`, `Makefile.d/**`, `config/lane-orchestration/**`, `docs/workbay/rules/**`, `docs/workbay/contracts/**`.

## Two remote claims that are FALSE in the real repo — do not act on them

`make task-reap` and `make plan-done` both exist and resolve (`make -n` succeeds from the repo root). They live in the gitignored plugin output `Makefile.d/`, which the sandbox mirror drops. The corresponding review findings were rejected and are not listed below. If any other step in the plan cites a make target you cannot see, treat it as present and note it under `SANDBOX-INVISIBLE:` in your report instead of rewriting the plan around it.

## Findings to close

### LAND-1-PR-10 (medium) — plan lines 59-66

The inventory table lists 27+3+3+2+12+1 = 48 branches and 20+3+5+2+0+1 = 31 linked worktrees, while the objective says 50/28 and Slice 1 claims 20/27 dropping 28→8. The stated dry-run and post-apply proofs cannot be reproduced from the plan's own inputs.

**Fix:** Regenerate a disjoint inventory at a named commit, explicitly separate branch-only refs from linked worktrees, and derive the table, dry-run output, and acceptance counts from that manifest.

### LAND-1-PR-14 (high) — plan lines 155-183

Slice 1 says --apply closes lane rows while removing worktrees and branches, but the described new script is explicitly git-only and the plan defines no transaction, ordering, or readback across Git and the lane DB. A filesystem or ref failure can leave one source claiming completion while the other disagrees.

**Fix:** Keep the reaper Git-only and move row closure to an explicit coordinator protocol with close-after-success, expected revision, reclassification, and readback; document recovery for every partial state.

### LAND-1-PR-17 (high) — plan lines 239-245

The orchestration section calls dispatch_wave with wave_max_width, timeout_seconds, effort, and speed, and calls dispatch_lane_work(brief=...). The checked-in dispatch surface exposes different parameters and no dispatch_wave or brief API, so a junior agent cannot execute this workflow as written.

**Fix:** Rewrite the steps against the actual lane-open, lane-dispatch, and brief commands with supported model and reasoning-effort fields, or specify the new wave API schema, timeout behavior, and tests.

### LAND-1-PR-18 (high) — plan lines 155-160

VERIFIED PARTIAL. docs/workbay/rules/development-workflow.md is present but UNTRACKED (.gitignore covers docs/workbay/rules/**), so the plan's Landing Protocol wording cannot be committed here. docs/workbay/contracts/gpu-lifecycle.md IS tracked - the remote claim was wrong about that half.

**Fix:** Do not plan to edit docs/workbay/rules/**. Replace that step with: print the exact Landing Protocol wording under a `CONTRACT-DELTA:` heading for the operator to apply out-of-band, and state in the plan that the rules directory is gitignored in this checkout.

### LAND-1-PR-19 (high) — plan lines 121-140

The graph documents a shared api/main.py include_router edge between healthobs and GPUOPS, yet the DAG schedules healthobs independently alongside GPUOPS B/D/F. File-disjoint coloring cannot make shared-file branches independent, so one merge can invalidate the other's gate evidence.

**Fix:** Add the healthobs↔GPUOPS dependency or intake node and serialize or rebase the shared-file merge; recompute components and coloring from complete diffs before dispatch.

### LAND-1-PR-20 (high) — plan lines 219-224

The GPUOPS lane table contains bare, repo-ambiguous paths such as scene/application/gpu_state.py, gpu-lifecycle-install.sh, and test_gpu_lifecycle_install.py, and gives E only intent.py. The listed test commands do not establish where those files live, so ownership and verification are not executable from the plan.

**Fix:** Use exact repository-relative paths for every owned file and test, include the working directory for each command, and mark genuinely new files with their creation path and owner.

### LAND-1-PR-21 (high) — plan lines 221-224

GPUOPS E and GPUOPS A both own docs/workbay/contracts/gpu-lifecycle.md, while the color list names A/C/wiring but omits E. The plan also says wiring and A edit that contract, so declared ownership and conflict protections miss an actual overlap.

**Fix:** Assign one contract owner and make other lanes consume it, or add an explicit dependency and merge-intake step and include every owner in the conflict coloring.

### LAND-1-PR-22 (high) — plan lines 117-119

N0 rows-hygiene and N10 park-August are both dependency-free, but Slice 2 has both mutate task rows and findings: 45 plan-done rows, 12 archive decisions, and 143 deferred findings. The graph has no DB resource edge or optimistic-revision protocol, so parallel writes can overwrite or miscount one another.

**Fix:** Model the handoff DB and findings store as a shared resource, serialize or transactionally batch these operations with expected revisions, and verify exact before/after counts.

### LAND-1-PR-23 (high) — plan lines 230-233

The plan parallelizes component work and then performs root-main merges, but specifies no merge queue, lock, or intake serialization for concurrent coordinators. Independent file changes still mutate one main ref and can race or invalidate previously recorded ancestry and gate state.

**Fix:** Parallelize lane work and reviews only; serialize root-ref updates under one coordinator lock, and recompute ancestry, tests, and close-check evidence after each merge.

### LAND-1-PR-24 (high) — plan lines 230-241

LAND-1's feature branch is held until the end while sibling work lands on main, but no step refreshes feature/land-1 from that final main before its own landing. Its local evidence can be based on a stale parent, and fast-forward-only landing may fail after sibling merges.

**Fix:** Before Slice 5, merge the exact latest main into feature/land-1, rerun local, remote, and close-check verification at that SHA, then land and verify the resulting main tip.

### LAND-1-PR-25 (high) — plan lines 129-135

GPUOPS B/D/F are launched in parallel from a common parent, while the generic landing protocol only says fast-forward the parent when a sub-lane is strictly ahead. After the first sibling lands, the others are no longer fast-forwardable; the plan omits their intake, conflict, and fresh-verification strategy.

**Fix:** Add explicit sibling intake nodes and a rebase, cherry-pick, or merge strategy, with conflict checks and per-sibling retest and close-check before the parent advances.

### LAND-1-PR-26 (high) — plan lines 142-149

The remote gate is launched detached with nohup … & disown, then the plan immediately records a second test result and proceeds. make check-remote has no plan-level wait or poll deadline or required exit/log proof, so a running, hung, or red gate can be treated as green.

**Fix:** Run the gate in the foreground under a bounded timeout, or poll a recorded job to a deadline and require exit 0 plus the shipped SHA in the result before recording evidence or merging.

### LAND-1-PR-27 (high) — plan lines 142-150

The pre-merge sequence closes the handoff check before the detached remote gate and only records a later test result; it never requires a final enforced handoff_close_check after all tests at the exact merge-candidate SHA. New findings or a SHA change can therefore occur between the check and merge.

**Fix:** Order local test, remote completion, test_result at the exact SHA, findings update, final enforced close check at that SHA, and merge; then verify main and render state.

### LAND-1-PR-28 (medium) — plan lines 189-190

Archive tags are specified as archive/<branch>-<yyyymmdd>, but no create-if-existing, target-SHA validation, or tag type and ownership rule is given. Re-running the claimed idempotent flow can fail or preserve a tag pointing at the wrong tip.

**Fix:** Make tagging deterministic: accept an existing tag only when it resolves to the recorded branch SHA, otherwise fail; store annotated archive metadata with owner, date, and revisit information.

### LAND-1-PR-29 (medium) — plan lines 188-190

The August inventory has 12 stale branches, but the plan names only six task rows for blocked and archived treatment and gives no disposition map for the other six refs, including branch-only refs. Tagging all 12 does not prove each branch has a retained task decision or intentional branch-only disposition.

**Fix:** Publish a 12-entry branch-to-task or branch-only disposition manifest, require one tag and status/rationale per ref, and assert the counts after parking.

### LAND1R-M-05 (medium) — plan lines 180-184

The Slice 1 goal says `--apply` closes lane rows as well as removing worktrees and branches, but `scripts/worktree_reap.py` is git-only and has no handoff integration; row closure belongs to the `land-1-hygiene` lane.

**Fix:** State that the reaper is git-only and that handoff-row closure is a separate step owned by `land-1-hygiene`, sequenced before the reap.

### LAND1R-M-06 (medium) — `docs/tasks/v0.5.0/lanes/LAND-1-plan-review-brief.md:3`

The brief names branch `review/land-1`; the branch-review guide forbids `review/*` for dispatched reviewer branches because the push naming hook rejects them.

**Fix:** Change the brief's branch to `feature/rev-land-1-plan-r2` and note the naming rule.

### LAND1R-M-07 (medium) — `docs/tasks/v0.5.0/lanes/LAND-1-plan-review-brief.md:4`

The brief authorizes printing findings as a fenced JSON block when MCP is unavailable. This actually happened: the round-2 reviewer printed 21 findings with no handoff ids, and the coordinator had to transcribe them by hand.

**Fix:** Require the repo-local Python-API fallback (`from workbay_handoff_mcp import review_findings`) and, only if that also fails, stop with an explicit blocker plus the JSON block clearly marked `UNRECORDED`.

### LAND1R-L-09 (low) — plan line 159

The plan says `worktree-reap-check` exits 1 when redundancy exists; the CLI returns 3 by design and `check-all` will make it advisory (exit 0 unless `REAP_STRICT=1`) per LAND-1-RT-03.

**Fix:** Document exit 3 for the explicit `worktree-reap` dry run, and advisory/`REAP_STRICT=1` semantics for `worktree-reap-check` inside `check-all`.

## Method

- Keep the plan conformant to `docs/workbay/templates/TASK_PLAN.template.md`; the `## Consolidated Checklist` structure stays.
- Never paste finding bodies or finding-status trailers into the plan — a `PreToolUse` hook and `make lint-task-plans` reject three or more consecutive bulleted lines opening with a finding-style id. Reference by id in prose only where genuinely needed.
- Every number in the inventory table must be reproducible from one named command at one named commit (`git worktree list --porcelain`, `git for-each-ref refs/heads`). Separate branch-only refs from linked worktrees. If you cannot verify a count from the sandbox, say so under `SANDBOX-INVISIBLE:` rather than inventing one.
- Where the plan orchestrates (waves, merges, gates), add the missing bounds explicitly: a merge/intake serialization point, a bounded wait with a deadline and a required exit-code check for the detached remote gate, and a final `handoff_close_check(enforce=True)` at the exact SHA that is merged.

## Verification

- `python3 -m pytest scripts/test_worktree_reap.py -q` still green (smoke; you changed no code).
- `python3 scripts/hooks/guard-task-plan-findings.py --scan-paths docs/tasks/v0.5.0/LAND-1-inflight-worktree-landing-task-plan.md` exits 0 — if that script is not visible in your checkout, say so and skip it.
- Report one line per finding: `FIXED: <id> <sha> <plan section>` / `ALREADY-FIXED: <id> <evidence>` / `NOT-FIXED: <id> <why>`.

## Constraints

- Commit incrementally on `feature/land-1-plan-fix` with plain messages; no attribution trailers. Land partial correct work rather than losing it to the wall clock.
- Close each finding with `review_findings(review={"operation":"resolve","task_ref":"LAND-1","finding_ids":["<id>"],"resolution_notes":"...","verification_evidence":"..."})`; if no MCP write path exists, print the `FIXED:` lines instead.

## Canon anchors

[RES-02] every wait bounded, no unbounded detached gate · [RES-10] fencing: one owner per file, declared up front · [RES-01]/[API-02] idempotent re-runs (archive tags, reap, intake) · [FLOW-06] derive counts from git at a named commit, never carry them forward · [OBS-01]/[OBS-05] expose the full list, not a count · [GRPH-03] reachability is the landed predicate · [GRPH-09] colour conflicts: a shared file forbids parallel scheduling · [HAI-06] reconstructable record of every automated mutation.
