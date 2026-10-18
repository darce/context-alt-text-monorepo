# GPUOPS-1 lane brief — `gpuops-1-fix-intent`

Task: GPUOPS-1 · Branch: `feature/gpuops-1-fix-intent` (from `feature/gpuops-1`) · Worktree: `/Users/daniel/Development/context-alt-text-monorepo-gpuops-1-fix-intent`
Title: GPUOPS-1 intent semantics: durable write-ahead intent, monotonic authority, traced deferred stop
New finding-id range reserved for this lane (only if you must file new ones): `GPUOPS-1-INT-01..20`.

## Objective

Close the 5 open findings below with tests. Verification command: `python3 -m pytest infra/oci/gpu_lifecycle -q`.

## Owned paths

- `infra/oci/gpu_lifecycle/intent.py`
- `infra/oci/gpu_lifecycle/`
- `infra/oci/cloud-init.yaml`
- `scripts/deploy/tests/test_gpu_cost_runbook_matches_verified_state.py`
- `infra/oci/gpu_lifecycle/tests/test_state_snapshot_contract.py`
- `infra/oci/gpu_lifecycle/tests/conftest.py`
- `infra/oci/gpu_lifecycle/tests/test_start_actuator.py`
- `infra/oci/gpu_lifecycle/tests/test_reap_untrustworthy_lease_cap.py`
- `infra/oci/gpu_lifecycle/tests/test_cpu_fallback.py`
- `infra/oci/gpu_lifecycle/tests/test_readiness_probe.py`
- `infra/oci/gpu_lifecycle/tests/test_intent.py`
- `infra/oci/gpu_lifecycle/tests/test_instance_states.py`
- `infra/oci/gpu_lifecycle/tests/test_state_snapshot.py`
- `infra/oci/gpu_lifecycle/tests/test_load_source_aggregate.py`
- `infra/oci/gpu_lifecycle/tests/test_max_lease.py`
- `infra/oci/gpu_lifecycle/tests/test_batch_fence.py`
- `infra/oci/gpu_lifecycle/tests/test_intent_controller.py`

## Design notes

Authority token (CANON-04): add a monotonic `sequence` (or fencing token) to the intent record; precedence is highest sequence, wall-clock is a tiebreak only ([RES-10]). Durability (CANON-03): move the intent file off tmpfs to a persistent path under the service state dir and fsync before acting; cloud-init.yaml only changes the path/dir provisioning. Deferred stop (CANON-06): persist `deferred_until`/`deferred_reason` and emit a log line + status field; never drop it silently ([FLOW-08]). Decision record (CANON-08): append every automated start/stop decision (who/why/intent sequence/outcome) to an append-only JSONL under the same state dir ([HAI-06]). OPSGPU-R3-02: the idle reaper timer must be fenced by the same intent authority — a `keep` intent with a higher sequence wins over the timer. The contract text lives in docs/workbay/contracts/gpu-lifecycle.md which you MUST NOT edit — print the wording changes under `CONTRACT-DELTA:`.

## Findings to close

### GPUOPS-1-CANON-04 (high) — `infra/oci/gpu_lifecycle/intent.py:None`

[RES-10] The intent's authority token is wall-clock only: expires_at is an ISO string and precedence is 'newest unexpired requested_at wins', both wall-clock, neither monotonic, and the nonce is per-START idempotency rather than a fence. A backwards NTP correction on acx-backend silently re-arms an already-expired 'start' intent, which is precisely the arm that suppresses idle reap and disables the cost governor. This codebase already paid for this lesson and rejected the pattern: RunningSinceLeaseStore.age_seconds refuses non-monotonic origins with 'Persisted lease metadata is unsafe to use as a duration origin' (reaper.py). Apply the same monotonic-origin discipline to intent expiry, or fence stale grants by nonce generation.

### GPUOPS-1-CANON-03 (high) — `docs/workbay/contracts/gpu-lifecycle.md:None`

[RES-17] The operator intent is a write-ahead record for a durable external mutation, but C1 puts it on tmpfs at /run/acx-write/<ACX_ENV>/gpu-intent.json, which gpu-lifecycle-install.sh recreates empty on every boot. What it authorises is not ephemeral: the A10 keeps running in OCI and the lease record is durable at /var/lib/acx-gpu/running-since.json. After a backend reboot the durable half survives while the intent and its requested_by vanish, so a 'start' that was suppressing idle reap silently reverts to 'auto' and the GPU is reaped mid-demo, with last_transition_reason recording 'idle' rather than 'operator'. There is no record to replay and nothing to explain the transition.

### GPUOPS-1-CANON-06 (medium) — `docs/workbay/contracts/gpu-lifecycle.md:None`

[FLOW-08] A deferred stop is dropped without a trace. C1 defers a 'stop' while work is in flight (intent_status=blocked_work_in_flight, 're-evaluate next cycle') but the same intent carries expires_at with a 1800s default. A describe run longer than the TTL means the deferred stop is never honoured: the intent transitions to 'expired' and the GPU runs to the lease cap. There is no drop counter, no correction event and no re-arm. The operator saw 'Stop requested - waiting for work to finish', closed the tab, and their explicit stop was discarded with the only trace an enum value in a tmpfs JSON file nobody watches. Either re-arm the deferred stop past expiry or surface the drop.

### GPUOPS-1-CANON-08 (medium) — `docs/workbay/contracts/gpu-lifecycle.md:None`

[HAI-06] No reconstructable record of an automated decision that spends money. There is one tmpfs intent file per env, overwritten per POST, with requested_by clobbered by the next write; the durable half (honoured_nonce in /var/lib/acx-gpu/running-since.json) carries no requester and no outcome history. 'Who started the $2/hr A10 at 03:00, and did the controller honour it?' is unanswerable after two clicks or one reboot. Add an append-only decision log (requested_by, nonce, effective intent, intent_status, actuation outcome) on durable storage, keyed so a reader can reconstruct a cycle after the fact.

### OPSGPU-R3-02 (medium) — `infra/oci/cloud-init.yaml:29-167`

[RES-10][CON-13][RLSE-11] cloud-init.yaml:29-59 provisions acx-gpu-idle-reaper.service/.timer and line 167 enables it, but scripts/deploy/gpu-lifecycle-install.sh never references, disables, or purges that unit -- grep for 'idle-reaper' in the installer returns nothing, while its own disable/purge lists (196, 237) cover only acx-gpu-start/acx-gpu-reap. The cloud-init reaper runs 'gpu_lifecycle --load-dir /run/acx-write --probe-oci --idle-seconds 300' every 2 minutes with NO flock prefix, NO --running-since-path and NO --max-lease-seconds, so it would bypass the /var/lib/acx-gpu/lifecycle.lock mutual exclusion the installer's two units take, and could issue an unfenced STOP that races a burst. Latent today, not live: acx-gpu-idle-reaper.timer reports 'not-found inactive' on acx-backend, so the current host is unaffected. The hazard lands on the next fresh provision from cloud-init.yaml, which would also corrupt the smoke's STOP-principal attribution check.


## Rules (all lanes)

- Work only inside the owned paths above. Never edit `scripts/workbay_lifecycle/**`, `Makefile.d/**`, `config/lane-orchestration/**`, `docs/workbay/contracts/**`, `docs/workbay/rules/**` (the last two are gitignored in the sandbox mirror and any edit there gets the whole patch rejected). If a fix needs a contract/rules/manifest change, do the code side and print the exact wording under a `CONTRACT-DELTA:` / `MANIFEST-DELTA:` heading in your final report.
- TDD: add or extend a test that fails before each fix and passes after. Never weaken an existing test. Mutation check: name one line whose removal makes your new test fail.
- Commit incrementally on the lane branch with plain messages; no attribution trailers. Land partial correct work rather than losing it to the wall clock.
- Close each finding: `review_findings(review={"operation":"resolve","task_ref":"<task>","finding_id":"<id>","status":"fixed","resolution_notes":"<what changed, test name>","verified_commit_sha":"<40-char sha>"})`. If no MCP write path exists in the sandbox, print one line per finding: `FIXED: <id> <sha> <test>`; `ALREADY-FIXED: <id> <evidence>`; `NOT-FIXED: <id> <why>`.
- Lint-only findings (`lint(ruff)`, `lint(mypy)`): fix them here; they never block a merge.
- Canon anchors: [RES-06] fail fast on malformed input · [RES-01]/[API-02] idempotent re-runs · [RES-02] every external wait bounded · [OBS-05] expose the full list, not a count · [SEC-*] never persist secrets/presigned tokens.
