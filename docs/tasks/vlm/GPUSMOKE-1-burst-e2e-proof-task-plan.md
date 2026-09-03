# GPUSMOKE-1. Programmatic end-to-end GPU burst proof

**Status:** planned · **Epic:** E14 self-hosting / VLM-3 follow-on · **Branch:** `feature/gpusmoke-1`

## Objective

Prove, by a runnable program and not by hand, the exact path a WordPress user triggers:

```
WP admin "Describe" → POST acx/v1/recognition/describe/runs → service POST /scene/describe/run (202)
  → dump_load_snapshot writes /run/acx/describe-load.json (queue_depth>0)
  → acx-gpu-start.timer (30s) → run_start_cycle → oci instance action START (acx-gpu-burst)
  → worker _wait_for_gpu_ready polls {ACX_GPU_ENDPOINT_URL}/health ≤ ACX_GPU_WARMUP_TIMEOUT_SECONDS (480s default)
  → GpuRemoteDescriptionAdapter → real Qwen3-VL-30B caption → item tier=final_gpu, describe_job_status=FINAL
  → load drains → acx-gpu-reap.timer (2min, idle 300s) → STOP → lifecycle-state=STOPPED, no orphans
```

Operator directive (2026-09-03): "this needs to be proven programmatically because users will trigger image description from the web interface and the bursty gpu must procure gpu resources".

## Prior art (cite, do not re-derive)

- VLM-3B Slice 7c live run 2026-07-14 (verified_test 784, decision 2266): START→healthy 101s; a job enqueued mid-warm-start on the single-job `/describe` route ended `degraded`; a job enqueued after readiness reached `final_gpu` gen 2 at +10s; reaper STOP verified. Ran from the laptop via SSH tunnel — not from the WP trigger.
- Merge `4a07a0ed` (2026-07-16) dropped 2,267 lines from `83d58405`: `scripts/gpu_spike_bench.py`, `scripts/test_gpu_spike_bench.py`, `docs/tasks/vlm/VLM-3-7c-activation-evidence.md`, 4× `VLM-3-gpu-spike-2026-07-14*.json`, `infra/oci/INFRA-TOPOLOGY.md`; reverted 7c checkboxes and memo status. `83d58405` is an ancestor of main → `git checkout 83d58405 -- <paths>` recovers them.
- Worker already bridges warm-start for the describe-run path: `describe_run_worker.py:239` calls `_wait_for_gpu_ready` before the item loop (`gpu_run_policy` only when adapter is GPU + endpoint set). Transient per-item retry is 3 attempts ≈3s (`_GPU_ITEM_MAX_ATTEMPTS`, `_GPU_ITEM_RETRY_BASE_DELAY_SECONDS`) — cannot bridge a warm-start on its own.
- Lifecycle: `infra/oci/gpu_lifecycle/reaper.py` (`run_start_cycle`, `run_reap_cycle`, `JsonFileLoadSource` max_age fence), installer `scripts/deploy/gpu-lifecycle-install.sh` (START_INTERVAL 30s, REAP_INTERVAL 2min, IDLE 300s, MAX_LEASE 3600s). Load producer `scene/application/describe_load.py` (`dump_load_snapshot` on enqueue + worker, `refresh_load_snapshot_loop` 45s).
- **GPUW-1 (merged main @08379faf, 2026-08-31)** already shipped the warm-start bridge: `_wait_for_gpu_ready` gate + `ACX_GPU_WARMUP_TIMEOUT_SECONDS` (validated, default 480), transient classifier chain-walk, load-snapshot refresher + lifespan supervisor. Reviews r08318792 (33 findings) + rdelta0831 dispositioned; VM scene suite 1266 passed @d464b85e. Deferred: D04 breaker half-open, D06 lock-test nondeterminism, D07 boot-time env validation. Slice-complete open thread: "Prod flip pending … E2E with burst A10" — that E2E is this task.
- **MAINT-gpuw-deploy-flip-20260831 (live, on main)**: dev api+worker on acx-backend were force-recreated 2026-09-02 (decision 6497) and now carry `ACX_DESCRIPTION_ADAPTER=gpu_qwen30b` + `ACX_GPU_ENDPOINT_URL=http://<burst-private-ip>:8000`; dev `/health/detailed` reports `description_adapter=gpu_qwen30b`. Prod still @73264a12 (operator-held: blockers 181/182/183 — .env flip, `sync-compose.sh` for the `/run/acx` bind mount, `CONFIRM=PROMOTE` deploy). Whether `acx-gpu-start`/`acx-gpu-reap` timers are installed on the host is unrecorded — S4 verifies before any run.
- Smoke surfaces today are inference-free: `scripts/prod-smoke.sh` (GET /health), `scripts/deploy/lib/smoke-gate.sh` (classifier of stored alt text; Gate A `is_trusted_describe_profile`, Gate B `fixture-denylist.sh`). No deployed env sets `ACX_GPU_ENDPOINT_URL` / `ACX_DESCRIPTION_ADAPTER=gpu_qwen30b`.
- Gate host `gate@acx-backend` has no OCI credentials → live smoke runs from `acx-backend` as `ubuntu` (VCN route + vaulted admin key). A10 burst bills ~$2/hr RUNNING; last live launch required explicit operator approval (decision 2265).

## Non-goals

- GPU tier UI (GPUUX-1 D/E1/E2, blocker 296).
- Terraform-managed burst instance (`main.tf` private subnet is fictional; CLI-provisioned instance stays).
- Changing the reaper/start policy values.

## DAG

```
wave 1 (width 2)          wave 2            integration                 gate                    live
C  S3 smoke findings ──┐
                       ├──► A  S1 remainder ──► E trial-merge ──► F adversarial ──► G close ──► S4 live-run
B  S2 warm-start TDD ──┘      (bench+docs)        + remote gate      review (1L+N R)    (enforce)   (operator)
```
Edges only where a landed SHA moves (GRPH-32). A/B/C touch disjoint files except `Makefile` (A adds `test-gpu-spike-bench`, C extends `test-scripts`): resolved at E, not a blocking edge (GRPH-09). Critical path C→E→F→G (GRPH-31). Width cap 2: the 8 GB host OOMs at 3 remote lanes (blocker 305). Recorded as decision 7490.

## Smoke ↔ UI observability parity (ux-map)

Source of truth for the UI vocabulary: `apps/prototype-wp-alt-context/docs/ux-maps/describe-gpu-tier.uxmap.json` (GPUUX-1; `gpu_state` ∈ unknown|stopped|starting|warming|ready|degraded). The smoke script is the programmatic twin of Screen 2 of that map: every transition a user would watch on the Workbench must be an assertion the smoke observes from the outside, in order.

```
 elapsed   smoke observation (assertion name)                  Workbench zone (describe-gpu-tier)
 ───────   ───────────────────────────────────────────────     ───────────────────────────────────
 t=0       POST acx/v1/…/describe/runs → 202 run_id            z-bulk-cta pressed
 ≤30 s     describe-load.json + gpu-state.json snapshotted      z-gpu-tier-chip  stopped → starting
           once before submit (gpu_state_json, load_json:
           recorded as evidence, NOT asserted)
 ≤60 s     OCI STARTING → RUNNING  (warm_start_running)        "⏳ Warming GPU … ~1 min 30 s left"
 ≈101 s    /health 200             (gpu_state: warming→ready)  chip ready
 ≤480 s    items pending → completed tier=final_gpu            "✔ Complete · N final (GPU) · 0 provisional"
           for EVERY requested media_id (run_terminal_success,
           tier_final_gpu, model_id_qwen30b, model_revision_pinned,
           caption_not_fixture)
 drain     idle 300 s + reap ≤120 s → STOPPED                  chip stopped
           (instance_stopped_after_reaper, exactly_one_start_transition)
 finally   STOP issued and STOPPED re-verified                 —  (billing invariant, no UI)
           (finally_stop_issued, instance_stopped_finally, no_orphans)
```

Interactivity reasoning derived from the map:
- Screen 3 (degraded, CPU drafts kept) is a *designed* UI state but a smoke **failure**: a run that ends `completed_with_errors` or with any `provisional_cpu` item means the burst path did not procure the GPU (RLSE-05: the UI must never present degraded as success, and the smoke must never exit 0 on it).
- The items poll during warm-up mirrors the "0 of N processed" progress row: while `gpu_state` is starting/warming no item may be terminal (OBS-08: silence during warm-up is expected, a terminal item during warm-up is the wrong kind of noise).
- "Cancel run" during warming maps to `cancel_requested` inside `_wait_for_gpu_ready`; the smoke does not exercise cancel (non-goal), S2's T4 covers the deadline branch instead.
- Cost line on the chip (≈$0.07 per 2 min) is the same arithmetic the evidence JSON records (`running_seconds × $2/3600`), so UI copy and evidence cannot drift.

## Slices

### Slice 1 — Recover the dropped 7c evidence and bench (codex-remote)
- [ ] `git checkout 83d58405 -- scripts/gpu_spike_bench.py scripts/test_gpu_spike_bench.py docs/tasks/vlm/VLM-3-7c-activation-evidence.md docs/tasks/vlm/VLM-3-gpu-spike-2026-07-14.json docs/tasks/vlm/VLM-3-gpu-spike-2026-07-14-400gb.json docs/tasks/vlm/VLM-3-gpu-spike-2026-07-14-400gb-60vpu.json docs/tasks/vlm/VLM-3-gpu-spike-2026-07-14-750gb-balanced.json infra/oci/INFRA-TOPOLOGY.md`; scrub any OCID/IP literal into `<placeholder>` before commit.
- [ ] Re-check the 7c boxes in `docs/tasks/vlm/VLM-3-gpu-detailed-tier-task-plan.md` (lines ~300-302, 318-321) and set `VLM-3-gpu-detailed-tier-decision-memo.md` status to "activated 2026-07-14 (evidence: VLM-3-7c-activation-evidence.md)"; fix line 58 stale claim.
- [ ] `make test-gpu-spike-bench` target running `scripts/test_gpu_spike_bench.py`; gate on remote: `scripts/remote_gate.sh run test-gpu-spike-bench`.
- [ ] Decision recording the lost-work merge (`4a07a0ed`) as the root cause.

### Slice 2 — Worker warm-start bridge: prove GPUW-1 end to end (codex-remote, TDD)
GPUW-1 implemented the gate; this slice proves the *composed* behaviour (enqueue → snapshot → START → wait → final_gpu) in one contract test, which GPUW-1's unit tests do not cover.
- [ ] RED: contract test in `scene/tests/test_describe_run_worker_gpu_warmstart.py` with a fake llama.cpp server whose `/health` returns connection-refused for N polls, then 503 (loading), then 200; assert the run's item ends `tier=final_gpu` / `describe_job_status=FINAL`, never `degraded`, and that `_wait_for_gpu_ready` treats `ConnectError` as "not ready yet" (not fatal).
- [ ] RED: budget test — START_INTERVAL (30s) + `JsonFileLoadSource` max_age + observed warm-start (101s) + first inference (≤175s read timeout) must fit inside `DEFAULT_GPU_WARMUP_TIMEOUT_SECONDS` (480s); assert the constant relationship in one place so a future tweak fails loudly.
- [ ] RED: mid-run enqueue — a second run enqueued while the first waits must not be marked degraded by the 3-attempt transient retry; it must also pass through `_wait_for_gpu_ready` (or share readiness).
- [ ] GREEN: minimal worker change only if a test fails for a real reason; otherwise the slice is proof-only. Any change to `gpu_run_policy` / `_wait_for_gpu_ready` updates `docs/workbay/contracts/` per contract-change-checklist.
- [ ] Gate: `scripts/remote_gate.sh run test-describe-run-worker` (or the owning make target).

### Slice 3 — `scripts/gpu_burst_smoke.py` + `make gpu-burst-smoke` (codex-remote)
- [ ] Trigger through the **WP REST route** the admin SPA uses (`POST acx/v1/recognition/describe/runs`, application-password auth from env), not directly against the service — that is the user path. Poll `GET .../runs/{run_id}/items` until terminal.
- [ ] Assertions: at least one item `tier=final_gpu`; caption fails `scripts/deploy/lib/fixture-denylist.sh`; item-level `tier=final_gpu` (service exposes `tier` on each run item; wave 6) and provenance `model_id` parsed as `<hub_repo>@<pinned revision>` matching the Qwen3-VL-30B profile; `/run/acx/gpu-state.json` and `describe-load.json` are snapshotted into the evidence file (recorded, not asserted — OCI lifecycle state is the asserted signal); after drain the reaper returns it to STOPPED (poll ≤ IDLE+REAP_INTERVAL+fence); `oci compute instance get` reports `STOPPED`; no orphan instances in the compartment tag scope.
- [ ] Safety: `--dry-run` (default) uses `httpx.MockTransport` + `FixedLoadSource` and runs on the gate; live mode refuses unless `ACX_GPU_SMOKE_CONFIRM=RUN`; hard wall-clock budget `--max-seconds` (default 900); `finally:` always issues STOP and asserts it; exit non-zero on any assertion (never `tail`-masked, rg-006).
- [ ] Artifact: `docs/tasks/vlm/GPUSMOKE-1-evidence-<date>.json` with timestamps per transition, cost estimate (`running_seconds × $2/3600`), model provenance; `assert_no_null_measurement_values` reused from `gpu_spike_bench.py` (S1).
- [ ] `make gpu-burst-smoke` (dry) and `make gpu-burst-smoke-live`; tests `scripts/test_gpu_burst_smoke.py` gated remotely.

### Slice 4 — Operator-gated live run on **dev** (local coordinator + operator)
- [ ] Preflight (read-only, no sudo): dev `/health/detailed` still reports `gpu_qwen30b`; `systemctl --user/list-timers` shows `acx-gpu-start.timer` + `acx-gpu-reap.timer` (else operator runs `scripts/deploy/gpu-lifecycle-install.sh`); `/run/acx/describe-load.json` fresh; burst instance `STOPPED`.
- [ ] Operator approves burst spend (~$2/hr, budget ≤ 1h, `--max-seconds 900`).
- [ ] Run `make gpu-burst-smoke-live` from acx-backend as ubuntu; commit the evidence JSON; record `verified_test` with the HEAD SHA.
- [ ] Roll env back to `seeded` unless operator promotes GPU as default; record the decision.

## Verification
- S1–S3 gated on the remote gate (`scripts/remote_gate.sh run …`); nothing runs locally.
- Adversarial `/wb-review-slice`: 1 local reviewer + remote reviewers against heuristics canon (release-it stability patterns: timeouts, circuit breaker, fail-fast; DDIA: idempotent trigger; latency: budget arithmetic).
- Pre-merge: `handoff_close_check(enforce=True)`.

## Open threads
- `oci` binary and vaulted key live only on acx-backend as `ubuntu`; the gate user cannot actuate. S3 live mode documents this and refuses elsewhere.
- Whether the demo stack (frozen container env) can ever point at the burst endpoint is out of scope; the target is dev/staging on acx-backend.
