# EVID-1 lane brief — `evid-1-fix-exporter`

Task: EVID-1 · Branch: `feature/evid-1-fix-exporter` (from `feature/evid-1`) · Worktree: `/Users/daniel/Development/context-alt-text-monorepo-evid-1-fix-exporter`
Title: EVID-1 exporter: export-gpu-evidence.sh atomic bundle, honest states, no token leak
New finding-id range reserved for this lane (only if you must file new ones): `EVID-1-EXP-01..20`.

## Objective

Close the 6 open findings below with tests. Verification command: `python3 -m pytest scripts/deploy/tests/test_export_gpu_evidence_shell.py -q -p no:randomly`. That pytest entry wraps `scripts/deploy/tests/test-export-gpu-evidence.sh` (`LC_ALL=C`) and is already collected by root `make test-scripts` via `scripts/deploy/tests`. There is no `scripts/deploy/tests/run.sh`; do not swallow a missing runner with `2>/dev/null` and a broader `-k evidence` fallback ([RLSE-05]).

## Owned paths

- `scripts/deploy/lib/export-gpu-evidence.sh`
- `scripts/deploy/tests/`

## Design notes

Write the new bundle into a temp sibling dir and `mv` it into place only after every step succeeds (EVID1E-H-02, [RES-01]); keep the previous bundle untouched on any failure. Never fabricate a STOPPED state at --since (EVID-1-R1-03): emit `unknown` with a `reason` so state history stays independently observed Audit lineage (DDIA). Strip query strings from snapshot URLs before persisting (EVID1E-M-10): keep the object path and omit the query entirely; do not replace it with `<redacted-url>` ([REF-33]). Add `--max-time`/`--connect-timeout` to every curl (EVID-1-R1-08, [RES-02]). Replace the denylist guard with an allowlist of read-only OCI verbs (EVID1E-L-11). Add shell tests under scripts/deploy/tests/ following the existing pattern there; run them with the verification command above, not a nonexistent `run.sh`.

## Findings to close

### EVID1E-H-02 (high) — `scripts/deploy/lib/export-gpu-evidence.sh:168-174`

[ANTIPATTERN] Re-exporting into an existing bundle deletes the prior manifest and receipts before OCI calls, history generation, optional copies, and manifest creation succeed. A transient OCI failure or interruption therefore destroys the last valid evidence and can leave a partial bundle.

### EVID1E-M-05 (medium) — `scripts/deploy/lib/export-gpu-evidence.sh:144-148`

[GAP] The documented/default destination is docs/evidence/gpu-burst, but generated raw OCI audit and WordPress receipts are not excluded from Git and are created with the caller’s normal umask. This makes accidental commits or local disclosure of potentially sensitive identity/request metadata likely.

### EVID-1-R1-03 (medium) — `scripts/deploy/lib/export-gpu-evidence.sh:393-413`

The exporter fabricates a STOPPED state at --since and labels the current state as --until, so the exported state history is synthesized rather than independently observed.

### EVID1E-M-10 (medium) — `scripts/deploy/lib/export-gpu-evidence.sh:428-446`

[ANTIPATTERN] EVID-1-M7: A snapshot URL, including query tokens from a presigned URL, is persisted verbatim in manifest.json and may be attached to handoff. The fix is to strip the query string entirely so only the object path remains; do not replace the URL with `<redacted-url>` ([REF-33]).

### EVID-1-R1-08 (low) — `scripts/deploy/lib/export-gpu-evidence.sh:432-434`

The curl retrieval has no timeout, so a hung endpoint can stall evidence capture indefinitely.

### EVID1E-L-11 (low) — `scripts/deploy/lib/export-gpu-evidence.sh:152-177`

[ANTIPATTERN] EVID-1-L1: The read-only guard is a narrow denylist, allowing other mutating OCI verbs such as update, delete, create, launch, attach, or detach if future calls are added.


## Rules (all lanes)

- Work only inside the owned paths above. Never edit `scripts/workbay_lifecycle/**`, `Makefile.d/**`, `config/lane-orchestration/**`, `docs/workbay/contracts/**`, `docs/workbay/rules/**` (the last two are gitignored in the sandbox mirror and any edit there gets the whole patch rejected). If a fix needs a contract/rules/manifest change, do the code side and print the exact wording under a `CONTRACT-DELTA:` / `MANIFEST-DELTA:` heading in your final report.
- TDD: add or extend a test that fails before each fix and passes after. Never weaken an existing test. Mutation check: name one line whose removal makes your new test fail.
- Commit incrementally on the lane branch with plain messages; no attribution trailers. Land partial correct work rather than losing it to the wall clock.
- Close each finding: `review_findings(review={"operation":"resolve","task_ref":"<task>","finding_id":"<id>","status":"fixed","resolution_notes":"<what changed, test name>","verified_commit_sha":"<40-char sha>"})`. If no MCP write path exists in the sandbox, print one line per finding: `FIXED: <id> <sha> <test>`; `ALREADY-FIXED: <id> <evidence>`; `NOT-FIXED: <id> <why>`.
- Lint-only findings (`lint(ruff)`, `lint(mypy)`): fix them here; they never block a merge.
- Canon anchors: [RES-06] fail fast on malformed input · [RES-01]/[API-02] idempotent re-runs · [RES-02] every external wait bounded · [OBS-05] expose the full list, not a count · [SEC-*] never persist secrets/presigned tokens.
