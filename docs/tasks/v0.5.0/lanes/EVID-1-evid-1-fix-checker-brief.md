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

### EVID1E-H-01 (high) — `scripts/gpu_burst_evidence.py:486-525`

[GAP] _authoritative_audit_events filters out successful StartInstance records that lack stateChange.current before _audit_checks counts starts. The action-sequence check still permits an extra successful START after a valid STOP, so a bundle with two successful StartInstance events can incorrectly return PASS instead of enforcing the documented exactly-one-start invariant.

### EVID-1-R1-02 (high) — `scripts/gpu_burst_evidence.py:391-393`

Audit events missing resourceId are accepted as belonging to the target instance, so unrelated events can satisfy the evidence proof. Mirrored in the exporter at scripts/deploy/lib/export-gpu-evidence.sh:384-386.

### EVID-1-R1-01 (high) — `scripts/gpu_burst_evidence.py:351-355`

Audit-event action matching uses substring comparison, so NotStartInstance is accepted as StartInstance. The same defect exists in the exporter at scripts/deploy/lib/export-gpu-evidence.sh:316-319. This produces false-positive GPU burst evidence.

### EVID1E-H-03 (high) — `scripts/gpu_burst_evidence.py:652-669`

[GAP] EVID-1-H3: Consecutive states are collapsed before checking the sequence, so StopInstance before StartInstance can still become STOPPED → RUNNING → STOPPED and pass.

### EVID1E-M-03 (medium) — `scripts/gpu_burst_evidence.py:35-67`

[GAP] Malformed but finite numeric timestamps can crash the checker with an uncaught OverflowError. For example, a snapshot timestamp of 1e308 reaches datetime.fromtimestamp() during failure reporting. Invalid boundary data should produce an explicit failed check, not a traceback.

### EVID1E-M-02 (medium) — `scripts/gpu_burst_evidence.py:862-883`

[GAP] The reaper snapshot check validates only timestamp and STOPPED state; it never validates the snapshot's instance_id against the selected instance. A valid-looking snapshot from another GPU instance can be accepted as corroborating evidence.

### EVID-1-R1-04 (medium) — `scripts/gpu_burst_evidence.py:481-513`

Receipt timestamp handling omits generated_at and generatedAt, so valid receipts produced by the exporter fail verification.

### EVID1E-M-07 (medium) — `scripts/gpu_burst_evidence.py:531-787`

[COMPLEXITY] EVID-1-M4: check_bundle is a 257-line radon F(53) function combining manifest, window, artifact, lifecycle, audit, optional receipt, and verdict logic.

### EVID1E-M-06 (medium) — `scripts/test_gpu_burst_evidence.py:906-935`

[GAP] The tests do not exercise the canonical OCI Audit CloudEvents shape: the shell fake uses top-level eventName/responseStatus, while this nested test omits event phases, request.parameters.action, and stateChange.previous/current. Parser regressions at the real Audit boundary can therefore pass the current 41-test suite.

### EVID1E-L-09 (low) — `scripts/gpu_burst_evidence.py:549-555`

[GAP] EVID-1-M6: SCHEMA_VERSION, manifest schema_version, and manifest format are not validated, so unknown or foreign manifests can be interpreted as v1.

### EVID1E-L-08 (low) — `scripts/gpu_burst_evidence.py:909-909`

[ANTIPATTERN] ruff format --check reports this file would be reformatted at the snapshot identity_detail expression, so the repository format gate is not clean.

### EVID-1-R1-07 (low) — `scripts/gpu_burst_evidence.py:48-48`

lint(mypy): assignment type error.

### EVID-1-R1-06 (low) — `scripts/gpu_burst_evidence.py:17-22`

lint(ruff): F401 unused import, UP035 deprecated typing import, and UP017 datetime.UTC modernization.

### EVID-1-R1-05 (low) — `scripts/gpu_burst_evidence.py:10-10`

lint(ruff): I001 unsorted import blocks in scripts/gpu_burst_evidence.py:10, scripts/test_gpu_burst_evidence.py:3, and scripts/deploy/tests/test_export_gpu_evidence_shell.py:3.


## Rules (all lanes)

- Work only inside the owned paths above. Never edit `scripts/workbay_lifecycle/**`, `Makefile.d/**`, `config/lane-orchestration/**`, `docs/workbay/contracts/**`, `docs/workbay/rules/**` (the last two are gitignored in the sandbox mirror and any edit there gets the whole patch rejected). If a fix needs a contract/rules/manifest change, do the code side and print the exact wording under a `CONTRACT-DELTA:` / `MANIFEST-DELTA:` heading in your final report.
- TDD: add or extend a test that fails before each fix and passes after. Never weaken an existing test. Mutation check: name one line whose removal makes your new test fail.
- Commit incrementally on the lane branch with plain messages; no attribution trailers. Land partial correct work rather than losing it to the wall clock.
- Close each finding: `review_findings(review={"operation":"resolve","task_ref":"<task>","finding_id":"<id>","status":"fixed","resolution_notes":"<what changed, test name>","verified_commit_sha":"<40-char sha>"})`. If no MCP write path exists in the sandbox, print one line per finding: `FIXED: <id> <sha> <test>`; `ALREADY-FIXED: <id> <evidence>`; `NOT-FIXED: <id> <why>`.
- Lint-only findings (`lint(ruff)`, `lint(mypy)`): fix them here; they never block a merge.
- Canon anchors: [RES-06] fail fast on malformed input · [RES-01]/[API-02] idempotent re-runs · [RES-02] every external wait bounded · [OBS-05] expose the full list, not a count · [SEC-*] never persist secrets/presigned tokens.
