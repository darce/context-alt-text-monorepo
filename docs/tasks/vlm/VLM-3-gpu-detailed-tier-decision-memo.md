# VLM-3 GPU Detailed-Tier Decision Memo

Date: 2026-07-14 (final; provisional 2026-07-08)
Task: VLM-3 (Slice 7b)
Status: **FINAL** — backed by measured live-GPU `acx-eval/v1` REPORTs (Slice 7b bake-off, 2026-07-14)

## Decision

Decision: **Qwen3-VL-30B-A3B-Instruct Q4_K_M GGUF** (unchanged from provisional, now measured)

The live A10 bake-off is decisive on quality: Qwen3-VL-30B-A3B-Instruct is the **only**
candidate that satisfies the anchor-visual/inject-factual contract — it weaves every
injected roster name into the caption (insertion_rate 1.0, mean gated score 1.0, 0/8
must-right failures). Every smaller candidate collapses on the same contract (gated
0.11–0.22, 7–8 of 8 must-right failures) despite producing fluent generic captions.
The quality gap dwarfs the load-time advantage of the ~16 GB dense models
(~28 s vs 57 s cold model_load).

## Measured head-to-head (live A10, 2026-07-14)

Endpoint: `ghcr.io/ggml-org/llama.cpp:server-cuda` on VM.GPU.A10.1, 400 GB @ 120 VPU
boot volume, greedy decoding, `bakeoff_golden.json` manifest (10 scenes), all runs
10/10 scored with bit-identical deterministic re-score. Harness head SHA
`2cf7898a449e5ecb3275e89ef868193680f38a7d`, manifest sha256 `670e257a…01b6ca`.

| Candidate | Quant | Bytes | Gated score | Insertion rate | Must-right fail | Policy viol. | Mean s/img¹ | Cold model_load |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **Qwen3-VL-30B-A3B-Instruct** | Q4_K_M | 18.6 GB | **1.0** | **1.0** | **0/8** | 0 | 4.42 | 57 s² |
| InternVL3.5-8B | bf16 | 16.4 GB | 0.222 | 0.0 | 7/8 | 0 | 4.20 | 27 s |
| Qwen3-VL-8B-Instruct | F16 | 16.4 GB | 0.222 | 0.222 | 7/8 | 0 | 5.59 | 30 s |
| MiMo-VL-7B-RL | BF16 | 15.3 GB | 0.111 | 0.0 | 8/8 | 0 | 18.74 | 28 s |

¹ Measured through the operator SSH tunnel (laptop → acx-backend → GPU); includes
tunnel RTT and base64 upload of full-resolution scene images, so it is an upper bound.
The 7a direct spike measured 0.58 s/img for the 30B on the same host class.
² From the 7a spike (`VLM-3-7a-spike-findings.md`) on the identical 400 GB @ 120 VPU
volume config; warm-start p95 85.1 s.

**Quality-vs-load-time verdict:** the smaller-model lever (7a recommendation #1:
~½ the load time) is real but **not usable** — no smaller candidate passes the
name-injection contract that defines the detailed tier. Warm-start must be paid at
the 30B's ~57 s model_load; the async `provisional_cpu → final_gpu` supersede path
(which hides warm-up from users) is therefore the operative mitigation, favoring the
relaxed 7c boot-volume spec over the strict-90s $92/mo volume.

**Slate cuts (named, per plan):** Kimi-VL-A3B-2506 (llama.cpp `kimivl` projector
unstable — ggml-org GGUF mmproj load failures, llama.cpp #15600/#16254),
Molmo-7B-D (no llama.cpp vision support), Phi-4-multimodal (no llama.cpp vision
support; abandoned research PR ggml-org/llama.cpp#12274 only). Qwen3-VL-8B-Instruct
was benched in Phi-4's place as the second smaller-model baseline. Cut rationale is
also recorded in each candidate's `pending_report` artifact
(`status=cut_from_live_slate`).

**Bench budget:** total GPU-on wall-clock 51 min (2026-07-14 07:21–08:12 UTC,
~$1.70) against the operator-approved ≤ 12 h line; per-candidate ≤ 15 min against
the 2 h cap. No overrun, no partial commits [PERF-07][RES-07].

## Evidence

- Measured REPORTs: `VLM-3-bakeoff-<model>-report.json` + `.md` (kind=report) for the
  four benched candidates; run-records `VLM-3-bakeoff-<model>-run-record.json`.
- Deterministic re-score: `--check-determinism` passed (bit-identical) on all four.
- Spike artifacts: `VLM-3-7a-spike-findings.md`,
  `VLM-3-gpu-spike-2026-07-14{,-400gb,-400gb-60vpu,-750gb-balanced}.json`.
- Candidate slate: `VLM-3-gpu-bakeoff-candidates-2026-07-08.json`.

## Must-Right

- Fits the A10 24 GB target with enough context/KV headroom for alt-text generation. ✅ measured (7a)
- Preserves the VLM-2B family continuity so adapter behavior starts from the known Qwen detailed-tier winner. ✅
- Supports the existing endpoint bake-off harness without forking `scripts.eval_harness.bakeoff`. ✅ (unchanged walker drove all four candidates)
- Produces a final adapter result through the unchanged `DescriptionAdapter` protocol. ✅ (adapter work landed in earlier slices)

## Easy-Wrong

- Treating pending placeholder REPORTs as measured quality evidence. (Resolved — all slate REPORTs are measured or explicitly cut.)
- Choosing a dense model only because it is simpler to serve while losing the expected quality lift. (Measured: the quality lift is the whole game — gated 1.0 vs ≤ 0.22.)
- Selecting a larger Qwen3-VL-32B or GLM-class model that leaves no A10 headroom.
- Ignoring license review when moving from private tenancy spike to public demo use. (Resolved below.)

## Latency, RSS, and Speedup

Measured GPU s/img: **0.58 s/img** direct (7a spike, same host class); 4.42 s/img
through the bench tunnel (upper bound, includes transport).

CPU baseline: VLM-2B recorded Qwen3-VL-4B-Instruct at **206 s/img** on A1 CPU (table mean latency in `VLM-2B-detailed-tier-decision-memo.md`; CapRL column is 208 s). That figure is log-derived from A1 serve logs / `VLM-2B-a1-serving-notes.md` — **not** recomputable from the committed run-records (VLM-2B footnote 2). Treat it as a fixed comparison anchor, not as harness-scored evidence.

CPU to GPU speedup: **~355×** direct (206 / 0.58); ≥ 46× even at the tunnel-measured
upper bound (206 / 4.42).

## License verdict (FINAL)

**Pass for public-demo distribution.** Exact downloaded artifacts checked 2026-07-14
against their Hugging Face source repos:

| Artifact | Source repo | License |
| --- | --- | --- |
| Qwen3VL-30B-A3B-Instruct Q4_K_M GGUF + F16 mmproj | `Qwen/Qwen3-VL-30B-A3B-Instruct-GGUF` | Apache-2.0 |
| Qwen3VL-8B-Instruct F16 GGUF + mmproj | `Qwen/Qwen3-VL-8B-Instruct-GGUF` | Apache-2.0 |
| InternVL3_5-8B bf16 GGUF + mmproj | `bartowski/OpenGVLab_InternVL3_5-8B-GGUF` (derivative of `OpenGVLab/InternVL3_5-8B`) | Apache-2.0 (upstream; quant repo carries no separate license tag) |
| MiMo-VL-7B-RL BF16 GGUF + mmproj | `unsloth/MiMo-VL-7B-RL-GGUF` / `XiaomiMiMo/MiMo-VL-7B-RL` | MIT |

The selected serving artifact (Qwen3-VL-30B Q4 GGUF) is Apache-2.0 from the
first-party Qwen repo: attribution + license text in distribution artifacts is the
only obligation; no copyleft, no usage restriction blocking the public demo.

## Activation preconditions

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
4. **GPU instance start.** Terraform provisions `acx_gpu_burst` in `state = "STOPPED"` (no A10 compute bill at apply). Start on demand (`oci compute instance action --action START` or console) before serving; the idle reaper STOPs when the describe job store reports `queue_depth=0` and `in_flight=0` for the configured idle window.
5. **Idle reaper wired.** Run the out-of-band actuator periodically (cron/systemd timer on the backend host or operator workstation with OCI CLI):

   ```bash
   python -m infra.oci.gpu_lifecycle \
     --instance-id "$(terraform -chdir=infra/oci output -raw gpu_instance_id)" \
     --idle-seconds 300 \
     --load-json /run/acx/describe-load.json \
     --fence-delay-seconds 1
   ```

   Load JSON must mirror `InMemoryDescribeJobStore.load_snapshot()`: `{"queue_depth": N, "in_flight": M}`. The reaper re-samples after a fence delay and cancels STOP if work appeared (decision→STOP fencing).
6. **Bake-off evidence.** ✅ Satisfied 2026-07-14: measured `kind=report` artifacts replaced all slate stubs (cuts named), spike artifacts updated in 7a. This memo is final.
