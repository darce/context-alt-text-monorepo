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

### EVID1E-H-03 (high) — `scripts/gpu_burst_evidence.py` audit sequence
Consecutive states are collapsed before the sequence check, so a StopInstance that precedes StartInstance can still read as STOPPED → RUNNING → STOPPED and PASS. Validate the ordered authoritative events and require the start time to precede the matching reaper stop. Test: a bundle whose only stop is timestamped before the start must FAIL.

### EVID1E-M-02 (medium) — reaper snapshot check
The snapshot check validates timestamp and STOPPED state but never the snapshot's `instance_id`. Pass the expected instance id into `_snapshot_check` and reject a mismatch. Test: a well-formed snapshot from a different instance ocid must not corroborate.

### EVID-1-R1-04 (medium) — receipt timestamps
Receipt timestamp handling omits `generated_at` and `generatedAt`, so receipts the exporter actually writes fail verification. Accept both spellings. Test: one receipt per spelling verifies.

### EVID1E-M-07 (medium) — `check_bundle` complexity
`check_bundle` is a ~257-line radon-F function. Split it into pure per-concern checkers (manifest, window, artifacts, audit sequence, receipts) that each return a list of violations; `check_bundle` composes them and assembles the verdict. Behaviour must not change — the existing 52 tests are the contract. Do this last, after the behavioural fixes, so a wall-clock cutoff cannot cost you a correctness fix.

### EVID1E-M-06 (medium) — `scripts/test_gpu_burst_evidence.py` golden payload
Tests never exercise the canonical OCI Audit CloudEvents shape: begin/end event phases, `request.parameters.action`, `response.status`, principal, `stateChange.previous/current`. Add one golden payload in that shape and run it through the check path. If the checker only supports the flattened shape, make it reject the canonical one with a named error rather than silently mis-parsing ([rg-015] — never silently support two shapes).

### EVID1E-L-09 (low) — schema validation
`SCHEMA_VERSION`, manifest `schema_version` and manifest `format` are unvalidated, so a foreign manifest reads as v1. Reject unsupported values explicitly ([RES-06] fail fast).

### Lint-only (fix here; they never block a merge)
- EVID1E-L-08 — `ruff format --check` would reformat the snapshot `identity_detail` expression.
- EVID-1-R1-07 — `lint(mypy)` assignment type error near the top of the module.
- EVID-1-R1-06 — `lint(ruff)` F401 unused import, UP035 deprecated typing import, UP017 `datetime.UTC`.
- EVID-1-R1-05 — `lint(ruff)` I001 unsorted imports in `scripts/gpu_burst_evidence.py` and `scripts/test_gpu_burst_evidence.py` only (the third file named in that finding belongs to another lane — leave it).

## Verification

`python3 -m pytest scripts/test_gpu_burst_evidence.py -q` must end green with strictly more tests than the 52-test baseline. Report the final count.

## Rules

- TDD: each fix gets a test that fails before and passes after. Never weaken an existing test. Name one line whose removal makes your new test fail.
- Commit incrementally on `feature/evid-1-fix-checker` with plain messages. No attribution trailers of any kind. Land partial correct work rather than losing it to the wall clock — the behavioural fixes (H-03, M-02, R1-04) come before the refactor (M-07).
- Never edit `scripts/workbay_lifecycle/**`, `Makefile.d/**`, `config/lane-orchestration/**`, `docs/workbay/contracts/**`, `docs/workbay/rules/**`. Those paths are gitignored in the sandbox mirror and any edit there gets the whole patch rejected. If a fix needs a contract change, do the code side and print the wording under a `CONTRACT-DELTA:` heading.
- Per finding, print one line: `FIXED: <id> <40-char sha> <test name>` / `ALREADY-FIXED: <id> <evidence>` / `NOT-FIXED: <id> <why>`.
- Canon anchors: [RES-06] fail fast on malformed input · [RES-01]/[API-02] idempotent re-runs · [GRPH-27] closed status vocabulary · [OBS-05] expose the full list, not a count · [rg-015] a boundary adapter never invents contract metadata and never silently supports two shapes.
