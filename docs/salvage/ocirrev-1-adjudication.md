# OCIRREV-1 stranded rev-ops adjudication

## Superseding landing review (2026-09-08)

The initial assessment below is retained as historical evidence, not the current
landing verdict. Luna MAX review of all 87 stranded hunks against the recovered
implementation rejected its “no novel work” conclusion. Dropping an unsafe old
implementation does not discharge a valid requirement (REF-13/REF-14, RES-02).

The source branch was ancestry-consolidated into `feature/ocir-landing-1` without
reapplying its obsolete runtime. Five current defects were recorded on
`OCIR-LANDING-1` as `OCIR-LUNA-20260908-01` through `05`:

- Remote builds must publish only the immutable SHA tag until push/verification.
  Commit `79747d8da` removes premature local environment-tag publication.
- A failed restart after cutover has ambiguous runtime state. The same commit
  restores the prior runtime for post-restart failures; pre-restart failures
  retain the lighter rollback. Executable phase tests cover deploy and promote.
- An accepted Vault mutation followed by failed readback is outcome UNKNOWN,
  including deadline exhaustion. Commit `d874e59ef` returns exit 75 and verifies
  that rotation does not compensate an accepted username write blindly.
- Pending Vault updates need stable identity and paged reconciliation. The same
  commit uses deterministic version names and follows version-list pagination
  before an ETag-fenced update. The explicit zero-readback mode remains intact.
- Serialization and elapsed-time bounds do not limit build memory or CPU.
  Finding `05` requires a resource-limited BuildKit container while retaining
  the existing generation directories, global lock and whole-operation budget.
  Its implementation and final review are tracked on the consolidated feature;
  the initial rejection of the unsafe old helper is not a waiver of this gate.

The Vault fixes passed 27 readiness tests, 21 helper tests and the shell rotation
harness (MCP test receipts 1920–1922). Deployment publication/rollback fixes
passed 17 focused tests (receipt 1916). These are slice receipts, not a claim
that a live deployment or Vault rotation was performed. The final feature
verdict requires the remaining capacity fix and Astra MEDIUM harmonization.

Applicable canon: `CARD-09`/`RES-02` resource isolation, `RES-03` whole-operation
budgets, `CARD-15`/`DATA-13` durable mutation identity, `API-02`/`API-04` outcome
ambiguity, and `TEST-15` executable regressions. The recovery coordinator read
the local heuristics-canon-research corpus; the historical worker's missing
checkout below is not the evidence boundary of this superseding review.

## Initial result (superseded)

The source of record is `rev-ops-stranded.patch`, with commit subjects and
scope cross-checked against `rev-ops-commits.txt` and
`rev-ops-diffstat.txt`. The current checkout was treated as current main; no
branch range, merge, rebase, or cherry-pick was used.

No stranded hunk is both novel and safe against the current implementation.
Most of the operability ideas landed later in stronger forms. In particular,
current main has a shared whole-rotation deadline, full-jitter Vault reads,
idempotent create and update reconciliation, ETag fencing, a credential
generation marker, bounded process-tree termination, immutable digest capture,
rollback concurrency fences, and rollback health verification. Reapplying the
older versions would either duplicate those controls or weaken them.

The one superficially missing idea is the named, resource-limited Buildx
container. I deliberately dropped it as doubtful: the stranded implementation
would replace current main's deadline-bounded, per-generation build directory
and `flock` serialization with unbounded SSH/buildx calls, and its tests only
look for source strings rather than proving that the target VM supports the
driver options. On the demo-launch critical path that is not enough evidence to
replace the current coordinator.

No category (d) hunk was proposed, so the requirement to ground every retained
hunk in the canon did not trigger. The requested read-only
`~/Development/heuristics-canon-research` checkout is not present on this
execution filesystem. No codemap structural or semantic channel is exposed to
this worker, so neither channel returned evidence and none is implied below.

## Classification table

Hunk ids are ordinal within each file in patch order. Categories are exactly
the requested `(a) ALREADY-LANDED`, `(b) SUPERSEDED`, `(c) STALE-WRONG`, and
`(d) STILL-NOVEL` taxonomy.

| File | Hunk | Category | Reason |
|---|---:|---|---|
| `.lane-anchor/ocirv-1-rev-ops.txt` | H01 | STALE-WRONG | A timestamped review anchor is stranded-branch bookkeeping, has no runtime value, and is outside this lane's owned paths. |
| `.task-state/review-ocirv1-rev-ops.md` | H01 | SUPERSEDED | Its findings are adjudicated here against current code; copying the obsolete line references would misdescribe current main. |
| `Makefile` | H01 | SUPERSEDED | The current target directly runs all four shell contract suites, including the OCIR rotation suite; recursively collecting all of `scripts/deploy/tests` would duplicate those entry points and is outside lane ownership. |
| `docs/runbooks/deploy-recognition-cicd.md` | H01 | ALREADY-LANDED | Both prod rollback commands now prefix `CONFIRM=PROMOTE`, use `GOOD_SHA`, and explain how to set it, satisfying rg-006 more completely. |
| `infra/oci/README.md` | H01 | ALREADY-LANDED | Current documentation already states remote build is the Make default and `REMOTE_BUILD=0` is the local opt-out. |
| `infra/oci/README.md` | H02 | STALE-WRONG | The stranded hunk deletes an old remote-default export, while current main intentionally documents `ACX_REMOTE_BUILD=0` as the local-default override. |
| `infra/oci/README.md` | H03 | SUPERSEDED | Ephemeral Vault-backed auth is already documented; the Buildx resource-limit claims were dropped because current main uses a different bounded/serialized builder design and cannot truthfully claim those limits. |
| `scripts/deploy/_vault_put_secret.py` | H01 | ALREADY-LANDED | Current docstring states that identical active input does not add a version. |
| `scripts/deploy/_vault_put_secret.py` | H02 | ALREADY-LANDED | `random` is already imported for retry jitter. |
| `scripts/deploy/_vault_put_secret.py` | H03 | SUPERSEDED | Current `OperationDeadline` distinguishes safe read timeouts from mutation-outcome-unknown errors instead of flattening both into `TimeoutError`. |
| `scripts/deploy/_vault_put_secret.py` | H04 | SUPERSEDED | Current `call_with_deadline` bounds every SDK call and preserves mutation ambiguity explicitly; the older rename loses that contract. |
| `scripts/deploy/_vault_put_secret.py` | H05 | SUPERSEDED | Current read and general-call deadline paths deliberately remain separate so consumer-read errors and mutation uncertainty retain distinct types. |
| `scripts/deploy/_vault_put_secret.py` | H06 | ALREADY-LANDED | `wait_until_readable` already accepts an injectable random source. |
| `scripts/deploy/_vault_put_secret.py` | H07 | STALE-WRONG | Current main intentionally permits zero read-back time while retaining a positive whole-operation deadline and reports `ACCEPTED-BUT-UNVERIFIED`; rejecting zero removes that explicit recovery mode. |
| `scripts/deploy/_vault_put_secret.py` | H08 | SUPERSEDED | Current retries use full jitter over `[0, cap]`, which spreads callers more effectively than the stranded narrow 0.8-1.2 multiplier while preserving the deadline. |
| `scripts/deploy/_vault_put_secret.py` | H09 | SUPERSEDED | Current `invoke` bounds list calls and `_list_active_secrets` also rejects repeated pagination tokens, a safety check absent from the stranded wrapper. |
| `scripts/deploy/_vault_put_secret.py` | H10 | SUPERSEDED | Current context resolution routes KMS and Vault calls through the typed `invoke` adapter with remaining-budget and retry controls. |
| `scripts/deploy/_vault_put_secret.py` | H11 | ALREADY-LANDED | `find_secret` already forwards the bounded invocation adapter. |
| `scripts/deploy/_vault_put_secret.py` | H12 | STALE-WRONG | The current CLI separates non-negative propagation wait from a strictly positive overall operation deadline; conflating them would regress the accepted-but-unverified contract. |
| `scripts/deploy/_vault_put_secret.py` | H13 | SUPERSEDED | Current main adds deterministic create retry tokens, active-value no-op, ETag-fenced update, read-after-timeout reconciliation, distinct exit 75 uncertainty, and bounded clients without relying on version-name support. |
| `scripts/deploy/ocir-token-rotate.sh` | H01 | STALE-WRONG | Zero remains a deliberate accepted-but-unverified mode with old-token revocation withheld; describing it as forbidden contradicts current behavior. |
| `scripts/deploy/ocir-token-rotate.sh` | H02 | SUPERSEDED | Current main uses one `--rotation-timeout` plus per-operation Vault budgets, avoiding independent login/verify budgets that could cumulatively exceed the rotation deadline. |
| `scripts/deploy/ocir-token-rotate.sh` | H03 | STALE-WRONG | The positive-only wording contradicts the explicit zero-mode state machine and its safe revocation behavior. |
| `scripts/deploy/ocir-token-rotate.sh` | H04 | SUPERSEDED | Current parsing validates a positive whole-rotation deadline and the Vault fetch budget while retaining separately validated non-negative readiness time. |
| `scripts/deploy/ocir-token-rotate.sh` | H05 | SUPERSEDED | Current `run_bounded_for` preserves stdin through fd 3, caps each call by remaining rotation time, reports missing commands, and kills stragglers. |
| `scripts/deploy/ocir-token-rotate.sh` | H06 | ALREADY-LANDED | `run_bounded` already delegates to the generalized bounded runner. |
| `scripts/deploy/ocir-token-rotate.sh` | H07 | STALE-WRONG | The stranded helper emits decoded secret bytes through command substitution; current main keeps fetch/decode handling explicit and adds generation/ETag controls around mutations. |
| `scripts/deploy/ocir-token-rotate.sh` | H08 | SUPERSEDED | Current username resolution is bounded and validated, and its explicit files live only in a mode-0700 runtime directory removed by the exit trap. |
| `scripts/deploy/ocir-token-rotate.sh` | H09 | ALREADY-LANDED | Fresh-token `docker login` already runs under the bounded runner with stdin preserved. |
| `scripts/deploy/ocir-token-rotate.sh` | H10 | SUPERSEDED | Current two-secret rotation uses an UPDATING/STABLE generation marker, ETag-fenced compensation, and ambiguity-aware exit 75; blind compensating writes from the stranded code could overwrite a concurrent rotation. |
| `scripts/deploy/ocir-token-rotate.sh` | H11 | ALREADY-LANDED | Laptop Vault-backed verification already runs through the shared bounded runner. |
| `scripts/deploy/ocir-token-rotate.sh` | H12 | SUPERSEDED | Remote verification already has an outer deadline, BatchMode, connect timeout, keepalive, and a session sentinel; the rotation-wide budget is stricter than an independent timeout. |
| `scripts/deploy/recognition-service.sh` | H01 | SUPERSEDED | Current post-cutover failures restore through digest-fenced rollback while retaining optional failure policy only after restoration; the stranded comment overstates unconditional verification. |
| `scripts/deploy/recognition-service.sh` | H02 | SUPERSEDED | Current usage documents push, pull, ordinary remote-command, and remote-build deadlines rather than only push timeout. |
| `scripts/deploy/recognition-service.sh` | H03 | SUPERSEDED | Deadline values are validated at their call sites and rollback state is stored as immutable digest/image-base/tag, not mutable tag plus expected label SHA. |
| `scripts/deploy/recognition-service.sh` | H04 | SUPERSEDED | Current deadline runner owns and terminates the entire child process tree; a single global child PID can leave grandchildren behind. |
| `scripts/deploy/recognition-service.sh` | H05 | SUPERSEDED | `run_with_deadline` preserves stdin, detects zombies, terminates descendants, validates ownership before SIGKILL, and reports outcome UNKNOWN. |
| `scripts/deploy/recognition-service.sh` | H06 | SUPERSEDED | Current `validated_deadline` validates every deadline close to use; the old global validation cannot cover newer pull/build/inspect/command budgets. |
| `scripts/deploy/recognition-service.sh` | H07 | STALE-WRONG | The named Buildx builder is doubtful and conflicts with current deadline-bounded, unique-generation, `flock`-serialized builds; its VM driver options were never functionally verified. |
| `scripts/deploy/recognition-service.sh` | H08 | STALE-WRONG | Current main snapshots rollback before any build; changing local build tagging is no longer the rollback fence and would disturb current digest capture without adding safety. |
| `scripts/deploy/recognition-service.sh` | H09 | STALE-WRONG | The stranded integration removes current generation-directory uniqueness and deadline/lock coordination in favor of an unverified shared named builder. |
| `scripts/deploy/recognition-service.sh` | H10 | STALE-WRONG | Its raw SSH `buildx build` is unbounded and omits current cleanup and `flock`; this would regress timeout and concurrent-coordinator safety even if Buildx exists. |
| `scripts/deploy/recognition-service.sh` | H11 | SUPERSEDED | Current `_push_ref` applies validated deadlines to local/remote pushes, uses bounded SSH, and confines credentials through explicit Docker adapters. |
| `scripts/deploy/recognition-service.sh` | H12 | SUPERSEDED | Current `do_push_tag` retags the exact captured candidate digest and verifies registry resolution, rather than re-deriving a mutable local SHA tag. |
| `scripts/deploy/recognition-service.sh` | H13 | SUPERSEDED | Current promote flow captures and promotes an immutable source digest; generic tag-to-tag promotion is vulnerable to concurrent mutable-tag movement. |
| `scripts/deploy/recognition-service.sh` | H14 | SUPERSEDED | Rollback is mandatory for prod and captured before the build; current dev behavior is provenance-aware rather than based only on tier comments. |
| `scripts/deploy/recognition-service.sh` | H15 | STALE-WRONG | Current repair remains coupled to restart/candidate digest validation; moving it into the older gate ordering would bypass newer rollback and immutable-image checks. |
| `scripts/deploy/recognition-service.sh` | H16 | STALE-WRONG | The stranded rollback derives identity from mutable tags and short image ids; current main snapshots the serving image, resolves registry digest provenance, publishes it, and verifies the rollback tag maps to that immutable digest. |
| `scripts/deploy/recognition-service.sh` | H17 | STALE-WRONG | Removing repair from restart contradicts current main's idempotent pre-restart migration and would drop the check from flows that do not use the old gate shape. |
| `scripts/deploy/recognition-service.sh` | H18 | STALE-WRONG | The old automatic rollback has no candidate-generation concurrency fence and can overwrite a newer deployment; current restore refuses stale rollback and verifies both health and immutable image id. |
| `scripts/deploy/recognition-service.sh` | H19 | SUPERSEDED | Current main preserves the running rollback digest before build, making pre-build mutable env-tag avoidance unnecessary while retaining compatibility with the established build path. |
| `scripts/deploy/recognition-service.sh` | H20 | SUPERSEDED | Current deploy restores tags with concurrency fences, restores sticky repo, restarts when needed, and verifies immutable identity; it also correctly allows optional reporting only after restoration. |
| `scripts/deploy/recognition-service.sh` | H21 | SUPERSEDED | Promotion now captures the pulled source digest, promotes that exact digest, and uses the same fenced restoration path on tag, restart, or health failure. |
| `scripts/deploy/recognition-service.sh` | H22 | STALE-WRONG | Current comment correctly documents that standalone verify and optional policy still consume a returned status; replacing it with rollback-only wording is false. |
| `scripts/deploy/recognition-service.sh` | H23 | STALE-WRONG | Same as H22: this helper is also used by standalone verify, so rollback-only documentation would narrow the real contract incorrectly. |
| `scripts/deploy/recognition-service.sh` | H24 | ALREADY-LANDED | `verify_retry_sleep` already avoids terminal sleeps and adds bounded jitter. |
| `scripts/deploy/recognition-service.sh` | H25 | ALREADY-LANDED | Missing/unknown SHA retries already use the shared no-terminal-sleep helper. |
| `scripts/deploy/recognition-service.sh` | H26 | SUPERSEDED | All ordinary verify retry branches use the helper, while current main additionally validates immutable image identity and GPU snapshot state; comments retain standalone-verify semantics. |
| `scripts/deploy/recognition-service.sh` | H27 | ALREADY-LANDED | SHA-skew retries already use the jittered helper and do not sleep after the final attempt. |
| `scripts/deploy/tests/test-ocir-rotate.sh` | H01 | SUPERSEDED | Current fake writer has richer ETag, generation-marker, ambiguity, and compensation fault controls rather than one secret-name failure switch. |
| `scripts/deploy/tests/test-ocir-rotate.sh` | H02 | SUPERSEDED | Current reset clears the expanded generation, revocation, timeout, and mutation-fault state. |
| `scripts/deploy/tests/test-ocir-rotate.sh` | H03 | SUPERSEDED | Current harness exports the expanded fault model used by the current rotation protocol. |
| `scripts/deploy/tests/test-ocir-rotate.sh` | H04 | SUPERSEDED | Current happy/partial-failure cases assert UPDATING/STABLE generation transitions and ETag-fenced compensation, which is stronger than the stranded two-write log assertion. |
| `scripts/deploy/tests/test-ocir-rotate.sh` | H05 | STALE-WRONG | Zero wait is now a supported accepted-but-unverified path that intentionally skips consumer verification and prior-token revocation. |
| `scripts/deploy/tests/test-ocir-rotate.sh` | H06 | STALE-WRONG | Positive-only test prose contradicts current supported zero propagation wait. |
| `scripts/deploy/tests/test-ocir-rotate.sh` | H07 | STALE-WRONG | Treating zero as invalid would delete the explicit ambiguity-safe fast-mode contract and its revocation fence. |
| `scripts/deploy/tests/test-ocir-rotate.sh` | H08 | STALE-WRONG | The non-negative missing-value diagnostic matches the current CLI contract; positive-only wording is obsolete. |
| `scripts/deploy/tests/test_recognition_ocir_config.py` | H01 | ALREADY-LANDED | Import ordering/blank-line formatting already matches the stranded post-image. |
| `scripts/deploy/tests/test_recognition_ocir_config.py` | H02 | ALREADY-LANDED | The survivor comprehension is already formatted equivalently. |
| `scripts/deploy/tests/test_recognition_ocir_config.py` | H03 | ALREADY-LANDED | The `_push_ref` command string already uses the normalized quoting. |
| `scripts/deploy/tests/test_recognition_ocir_config.py` | H04 | ALREADY-LANDED | The parametrized function signature already uses the normalized one-line form. |
| `scripts/deploy/tests/test_recognition_ocir_config.py` | H05 | ALREADY-LANDED | The second `_push_ref` command string already uses normalized quoting. |
| `scripts/deploy/tests/test_recognition_ocir_config.py` | H06 | SUPERSEDED | Current tests exercise executable local/remote deadline behavior, credential scoping, digest promotion, rollback fencing, and cleanup rather than brittle source strings for the obsolete helper/build design. |
| `scripts/test_deploy_workflow_gate.py` | H01 | ALREADY-LANDED | `RUNBOOK_PATH` and the rollback-section parser are already present. |
| `scripts/test_deploy_workflow_gate.py` | H02 | SUPERSEDED | Current tests pin copy-pasteable commands and require prose to define `GOOD_SHA`; the Make target already names credential suites directly. |
| `scripts/test_e15_33_boot_smoke.py` | H01 | ALREADY-LANDED | The gate double already includes `repair_blob_volume_ownership`. |
| `scripts/test_e15_33_boot_smoke.py` | H02 | ALREADY-LANDED | The formatting-only assertion changes are already present or semantically identical. |
| `scripts/test_e15_33_boot_smoke.py` | H03 | ALREADY-LANDED | The teardown assertions retain the same strength with current formatting; no assertion was relaxed (sr-001). |
| `scripts/test_ocirv1_vault_readiness.py` | H01 | SUPERSEDED | Current helpers separately assert capped exponential scheduling and full jitter `[0, cap]`, stronger and less timing-flaky than the stranded 6-second envelope. |
| `scripts/test_ocirv1_vault_readiness.py` | H02 | STALE-WRONG | Current main intentionally tests zero as a no-read accepted mode; rejecting it contradicts the writer and wrapper state machine. |
| `scripts/test_ocirv1_vault_readiness.py` | H03 | SUPERSEDED | The current 503 test asserts the exact cap plus the full-jitter draw range, not merely a value in 0.8-1.2. |
| `scripts/test_ocirv1_vault_readiness.py` | H04 | SUPERSEDED | Current fake Vault tracks ETags, create retry tokens, read history, and mutation ambiguity rather than synthetic version names unsupported by the chosen reconciliation design. |
| `scripts/test_ocirv1_vault_readiness.py` | H05 | SUPERSEDED | Fake create/update now record retry-token and `if_match` fencing needed by current idempotency semantics. |
| `scripts/test_ocirv1_vault_readiness.py` | H06 | SUPERSEDED | Current fake clients accept bounded SDK controls and preserve timeout state across all exercised clients. |
| `scripts/test_ocirv1_vault_readiness.py` | H07 | SUPERSEDED | Current fakes implement get-secret ETags and conditional update behavior; listing invented version names is not the current contract. |
| `scripts/test_ocirv1_vault_readiness.py` | H08 | SUPERSEDED | Current rotation test proves active-value no-op, deterministic create retry token, ETag-fenced update, full jitter, and timeout reconciliation without relying on version-name metadata. |
| `scripts/test_ocirv1_vault_readiness.py` | H09 | STALE-WRONG | Bootstrap with zero wait is still supported and deliberately avoids creating a Secrets client; forcing a read removes the explicit accepted-but-unverified mode. |

## Applied changes

None. There are no `(d) STILL-NOVEL` rows. The only repository change from
this lane is this audit record; no runtime, test, source-material, or
out-of-scope file was modified.
