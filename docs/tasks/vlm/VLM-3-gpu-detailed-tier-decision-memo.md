# VLM-3 GPU Detailed-Tier Decision Memo

Date: 2026-07-08
Task: VLM-3
Status: provisional; license verdict pending; measured JSON reports not regenerated

## Decision

Decision: Qwen3-VL-30B-A3B-Instruct

Use Qwen3-VL-30B-A3B-Instruct Q4 GGUF as the provisional GPU detailed-tier implementation target for the adapter and golden-image work. It is the only candidate in the current slate that combines the existing Qwen family fit from VLM-2B, 30B-class total capacity, MoE active-parameter serving cost, and an estimated 18 GB Q4 footprint inside the `VM.GPU.A10.1` 24 GB target.

Do not promote the provisional decision to final until the live OCI bake-off replaces the pending report stubs with measured `acx-eval/v1` REPORTs and updates the Slice 1 spike artifact with real warm-start and s/img values.

## Evidence

- Spike artifact: `VLM-3-gpu-spike-2026-07-08.json`
- Candidate slate: `VLM-3-gpu-bakeoff-candidates-2026-07-08.json`
- Selected candidate report placeholder: `VLM-3-bakeoff-Qwen3-VL-30B-A3B-Instruct-report.json`
- Current evidence status: pending live OCI bake-off

## Must-Right

- Fits the A10 24 GB target with enough context/KV headroom for alt-text generation.
- Preserves the VLM-2B family continuity so adapter behavior starts from the known Qwen detailed-tier winner.
- Supports the existing endpoint bake-off harness without forking `scripts.eval_harness.bakeoff`.
- Produces a final adapter result through the unchanged `DescriptionAdapter` protocol.

## Easy-Wrong

- Treating pending placeholder REPORTs as measured quality evidence.
- Choosing a dense model only because it is simpler to serve while losing the expected quality lift.
- Selecting a larger Qwen3-VL-32B or GLM-class model that leaves no A10 headroom.
- Ignoring license review when moving from private tenancy spike to public demo use.

## Latency, RSS, and Speedup

Measured GPU latency/RSS: pending live OCI bake-off.

CPU baseline: VLM-2B recorded Qwen3-VL-4B-Instruct at **206 s/img** on A1 CPU (table mean latency in `VLM-2B-detailed-tier-decision-memo.md`; CapRL column is 208 s). That figure is log-derived from A1 serve logs / `VLM-2B-a1-serving-notes.md` — **not** recomputable from the committed run-records (VLM-2B footnote 2). Treat it as a fixed comparison anchor, not as harness-scored evidence.

CPU to GPU speedup: provisional target is 206 s/img divided by measured GPU s/img; the denominator remains pending in `VLM-3-gpu-spike-2026-07-08.json`.

## License verdict

Provisional pass for private in-tenancy evaluation. Final license verdict is blocked on the exact downloaded artifact license for Qwen3-VL-30B-A3B-Instruct Q4 GGUF and must be rechecked before public demo distribution.

## Activation preconditions

Activation status: activated on the spike host on 2026-07-14; production
activation is pending GPUSMOKE-1 S4, including the production reaper timer
install and backend deploy.

Do not treat `terraform apply` alone as tier activation. Before setting the service to the GPU detailed tier, all of the following must hold:

1. **Infra-produced endpoint URL.** After apply, read:
   - `terraform -chdir=infra/oci output -raw gpu_endpoint_url` → set as `ACX_GPU_ENDPOINT_URL` on the description service (shape `http://<private-ip>:8000`). Prefer the private-IP form from this output.
   - `terraform -chdir=infra/oci output -raw gpu_private_ip` is the VCN-private address; `gpu_instance_id` feeds the idle reaper.
2. **Adapter env contract (serving-side gate).** Both must be set before the GPU detailed tier serves traffic:
   - `ACX_DESCRIPTION_ADAPTER=gpu_qwen30b`
   - `ACX_GPU_ENDPOINT_URL` pointing at a private/in-tenancy llama.cpp base URL (port 8000 on the burst host).
   Missing endpoint or a non-private URL fails closed (503 / unavailable adapter) **before** image bytes leave the service.
3. **Endpoint allowlist behavior** (`deps._is_private_gpu_endpoint` + `ACX_GPU_ENDPOINT_ALLOWLIST`, default `localhost`, `acx-gpu-burst`, `*.oraclevcn.com`):
   - **Private/loopback IP literals** (e.g. `http://10.0.x.x:8000`) are accepted without hostname allowlisting.
   - **Allowlisted hostnames** (`acx-gpu-burst`, `localhost`, or `*.oraclevcn.com` FQDNs) are accepted only when DNS resolves **entirely** to private or loopback addresses — public resolution fails closed.
   - Prefer the terraform private-IP URL or the `acx-gpu-burst` alias (with VCN DNS/`/etc/hosts`) over hand-typed FQDNs. OCI VCN FQDNs ending in `.oraclevcn.com` work when they resolve privately inside the tenancy; they are not a substitute for verifying the resolved addresses stay in-boundary.
4. **GPU first boot and verified STOP.** The first Terraform apply provisions
   `acx_gpu_burst` in `state = "RUNNING"` so cloud-init can finish. Terraform's
   `lifecycle.ignore_changes = [state]` then prevents later applies from undoing
   scale-to-zero state. Immediately after cloud-init is verified, the operator must
   issue `oci compute instance action --instance-id <instance_ocid> --action STOP`
   and poll `oci compute instance get --instance-id <instance_ocid>` until the
   lifecycle state is `STOPPED`. Start on demand before serving; the idle reaper
   STOPs when the describe job store reports `queue_depth=0` and `in_flight=0` for
   the configured idle window.
5. **Idle reaper wired.** Run the out-of-band actuator periodically (cron/systemd timer on the backend host or operator workstation with OCI CLI):

   ```bash
   python -m infra.oci.gpu_lifecycle \
     --instance-id "$(terraform -chdir=infra/oci output -raw gpu_instance_id)" \
     --idle-seconds 300 \
     --load-dir /run/acx-write \
     --fence-delay-seconds 1
   ```

   `--load-dir` is a directory of per-environment snapshots (`<load-dir>/<environment>/describe-load.json`), not a single file: WBUX6-MRG-02 moved publication off the one-writer `/run/acx/describe-load.json` so multiple environments can publish concurrently. Each snapshot must mirror `scene/application/describe_load.py::load_snapshot`: `{"queue_depth": N, "in_flight": M, "batch_in_progress": bool, "written_at": ...}`. Fresh snapshots are aggregated; stale or invalid inputs fail closed. The reaper re-samples after a fence delay and cancels STOP if work appeared (decision→STOP fencing).
6. **Bake-off evidence.** Live OCI bake-off replaces pending REPORT stubs (`kind=pending_report`) with measured `kind=report` artifacts and updates the spike artifact before promoting this memo from provisional to final (see Decision above).
