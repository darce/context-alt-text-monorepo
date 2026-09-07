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

### EVID1E-M-04 (medium) — `mk/gpu-evidence.mk:63-86`

[ANTIPATTERN] Make variables are interpolated directly inside double-quoted shell arguments. Values containing shell metacharacters can terminate the quote and execute commands, defeating the exporter’s read-only boundary; the same issue affects bundle paths, URLs, principals, and Python command values.

### EVID1E-L-07 (low) — `mk/gpu-evidence.mk:54-60`

[COMPLEXITY] gpu-evidence-tests is added as a prerequisite of the root test-scripts target, but the existing root test-scripts recipe already collects scripts/deploy/tests, including test_export_gpu_evidence_shell.py. The exporter shell suite runs twice through make test-scripts.

### EVID1E-M-08 (medium) — `scripts/test_gpu_burst_evidence.py:1-15`

[GAP] EVID-1-M5: The substantive checker suite is absent from the explicit make test-scripts pytest list; lint-scripts and formatting also omit the new checker and tests.


## Rules (all lanes)

- Work only inside the owned paths above. Never edit `scripts/workbay_lifecycle/**`, `Makefile.d/**`, `config/lane-orchestration/**`, `docs/workbay/contracts/**`, `docs/workbay/rules/**` (the last two are gitignored in the sandbox mirror and any edit there gets the whole patch rejected). If a fix needs a contract/rules/manifest change, do the code side and print the exact wording under a `CONTRACT-DELTA:` / `MANIFEST-DELTA:` heading in your final report.
- TDD: add or extend a test that fails before each fix and passes after. Never weaken an existing test. Mutation check: name one line whose removal makes your new test fail.
- Commit incrementally on the lane branch with plain messages; no attribution trailers. Land partial correct work rather than losing it to the wall clock.
- Close each finding: `review_findings(review={"operation":"resolve","task_ref":"<task>","finding_id":"<id>","status":"fixed","resolution_notes":"<what changed, test name>","verified_commit_sha":"<40-char sha>"})`. If no MCP write path exists in the sandbox, print one line per finding: `FIXED: <id> <sha> <test>`; `ALREADY-FIXED: <id> <evidence>`; `NOT-FIXED: <id> <why>`.
- Lint-only findings (`lint(ruff)`, `lint(mypy)`): fix them here; they never block a merge.
- Canon anchors: [RES-06] fail fast on malformed input · [RES-01]/[API-02] idempotent re-runs · [RES-02] every external wait bounded · [OBS-05] expose the full list, not a count · [SEC-*] never persist secrets/presigned tokens.
