# VLM-3 Slice 7c — GPU Tier Activation Evidence (2026-07-14)

Live proof from the activation run and E2E burst on the provisioned spike host.
This is not evidence of production activation. Companion to the decision memo
§Activation preconditions and `VLM-3-7a-spike-findings.md`.

Status: proven on the 2026-07-14 spike host; production reaper timer install +
backend deploy are open GPUSMOKE-1 S4 preconditions.

## Provisioned host (operator-approved launch)

- Instance `acx-gpu-burst` = `<burst-instance-ocid>`
  (VM.GPU.A10.1, golden image `acx-gpu-qwen3vl30b-golden`, private IP `<burst-private-ip>`,
  hostname `acx-gpu-burst`, NSG `acx-gpu-bench-nsg`, tags `env:production role:gpu-burst
  scale_to_zero:true`).
- Boot volume `<burst-boot-volume-ocid>` — **400 GB @ 30 VPU (the relaxed spec,
  operator-decided)**, ~$31/mo standing;
  compute ~$2/hr only while RUNNING.
- End state after the proof: instance **STOPPED** (reaper-actuated), no orphaned
  instance, boot volume retained by design.

## E2E burst (measured, 2026-07-14 UTC)

| Step | Evidence |
| --- | --- |
| START issued (from STOPPED) | 14:56:45Z |
| Warm-start (STOPPED → `/v1/models` serving) | **101 s** — beats the 7a relaxed-spec prediction (~106–111 s) |
| Enqueue DURING warm-start (media 43) | job `3a542b84…` → `degraded`, tier `provisional_cpu` gen 1 preserved, GPU connection error surfaced verbatim — the user never waits or loses the provisional |
| Enqueue with GPU ready (media 44) | job `047c3fd8…` → `provisional` (`provisional_cpu`, gen 1) at +5 s → **`final` (`final_gpu`, gen 2) at +10 s** with a real GPU caption |
| Drain + reaper | `python3 -m infra.oci.gpu_lifecycle --instance-id … --idle-seconds 30 --load-json <snapshot> --fence-delay-seconds 2 --probe-oci` → `decided=[('STOP', …)] actuated=[('STOP', …)] fenced_off=False errors=[]`; instance `STOPPED` |
| Load snapshot | DB-derived (`describe_load.py`, VLM-5 producer) at `ACX_DESCRIBE_LOAD_PATH`; `{"queue_depth":0,"in_flight":0,"written_at":…}` consumed by the reaper |

## Spike-host activation preconditions (memo §Activation) — status

1. **Endpoint URL**: `ACX_GPU_ENDPOINT_URL=http://localhost:18000` on the spike host (loopback →
   SSH tunnel `localhost:18000 → acx-backend → <burst-private-ip>:8000`); loopback/private
   forms accepted per the allowlist contract. ✅
2. **Adapter env contract**: with the env set, async GPU-final serves; with it
   unset the adapter fails closed (`ACX_GPU_ENDPOINT_URL must be set to a
   private/loopback in-tenancy endpoint`) *before* image bytes leave the service. ✅ live
3. **Allowlist fail-closed**: 10 endpoint/allowlist unit tests green at branch
   HEAD + live unset-env fail-closed observed. ✅
4. **GPU instance start**: provisioned, first-boot completed, control-plane
   STOPPED as the scale-to-zero start state; burst START/STOP exercised. ✅
5. **Idle reaper spike proof**: actuated a real STOP off the DB-derived snapshot
   (fence honored). The production timer (cron/systemd on the backend host)
   remains an open GPUSMOKE-1 S4 precondition. ☐ production
6. **Bake-off evidence**: memo remains provisional; the license verdict is
   pending and measured JSON reports were not regenerated. ☐ open

## Rollback (RLSE-07/08)

On the spike host, the service restarted with **no** `ACX_GPU_ENDPOINT_URL`:
sync describe serves
`tier=provisional_cpu` (CPU adapter), async degrades gracefully preserving the
provisional, `/health` green throughout (`commit_sha=2f52fe94`). Stop criteria:
unset the env (or stop the timer) and the CPU tier carries all traffic — no
restart of dependent systems required.

## Found & fixed during the live proof

- **VLM-5 RLS enqueue defect** (`2f52fe94`): the post-commit read-back in
  `enqueue_describe_image` ran without tenant context (`SET LOCAL` is
  transaction-scoped) → RLS hid the just-created row → every async enqueue
  500'd on Postgres. Invisible to the SQLite suite (no RLS); caught by this
  live proof exactly as the runtime-parity requirement intended.
- Local dev DBs predating the VLM-5 greenfield schema need `make db-reset`
  (known AP-7-era lesson; hit again here).

## Deviations (recorded)

- **CLI-provisioned, not terraform**: no tfstate exists anywhere (the stack was
  never applied — `terraform init` only); applying `main.tf` now would attempt
  to recreate the live CLI-managed VCN, and it references a private subnet that
  does not exist. Terraform state import (or config realignment to the live
  stack) is follow-up work; the memo's precondition *outputs* (endpoint URL,
  private IP, instance id) were produced by CLI equivalents above.
- **Serving host for the proof**: the description service ran from the branch
  worktree on the operator laptop against the real OCI GPU host + real reaper
  actuation. Rolling the same env contract onto the VM deployment is the
  operator's deploy step (push → dev auto-deploy), unchanged in shape.
