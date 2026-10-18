# GPU Tier Fallback Plan — if OCI A10 quota is denied

Contingency for the detailed-description tier if the OCI A10 Service Limit Increase is
denied or stalls (see [GPU-BURST-PROVISIONING.md](GPU-BURST-PROVISIONING.md) for the
request path and denial reasons). Companion to the
[VLM-3 task plan](../../docs/tasks/vlm/VLM-3-gpu-detailed-tier-task-plan.md).

## Why the fallback is cheap — VLM-3 already decoupled the serving backend

The detailed tier does **not** depend on OCI specifically. VLM-3 shipped a
provider-agnostic seam:

- **`gpu_remote_adapter`** POSTs to `{ACX_GPU_ENDPOINT_URL}/v1/chat/completions` —
  a standard **OpenAI-compatible chat-completions** call. Any endpoint that speaks it
  works (self-hosted vLLM/llama.cpp, a serverless GPU container, or an open-model API).
- **Residency is enforced in code.** `_is_private_gpu_endpoint`
  (`interface_adapters/http/deps.py`) accepts the GPU endpoint **only** when it is
  private/loopback and matches `ACX_GPU_ENDPOINT_ALLOWLIST` (default `localhost`,
  `acx-gpu-burst`, `*.oraclevcn.com`). A **public** endpoint is rejected by design.
- **Boundary-crossing serving is a separate, opt-in path.** The `HOSTED_PROVIDER`
  adapter (E20-11) flips `ProviderDisclosure.left_service_boundary = True` and requires
  `ACX_HOSTED_PROVIDER_OPTIN=1` — the honest surface for anything public.
- **The CPU tier is the always-available floor** (`LOCAL_CPU`: Florence-small / Qwen 4B
  on the A1), already wired as the `provisional_cpu` degrade.

**Consequence:** switching backends is mostly **endpoint config + a residency
decision**, not a rebuild. The code already bifurcates: *private endpoint →
`gpu_remote_adapter` (residency preserved); public → `HOSTED_PROVIDER` (disclosed)*.

## The decision fork

In-tenancy GPU existed for **residency** (bytes stay inside the boundary). OCI denial
forces one question: **keep residency** (self-host a private GPU) or **relax it** (use
a hosted/serverless provider, disclosed)?

## Options (ranked)

| # | Option | Residency | Bursty $0-idle | Needs quota | Code change | Path |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | **Self-hosted GPU over Tailscale** | ✅ in-boundary | ⚠️ only if you stop/start the box | ❌ | none | `gpu_remote_adapter` |
| 2 | **Serverless GPU + Tailscale sidecar** | ✅ (private tailnet) | ✅ true scale-to-zero | ❌ | none | `gpu_remote_adapter` |
| 3 | **Hosted frontier VLM API** (GPT-4o / Claude / Gemini) | ❌ disclosed | ✅ pay-per-call | ❌ | already built | `HOSTED_PROVIDER` (E20-11) |
| 4 | **Open-model API host** (Together / Fireworks / OpenRouter) | ❌ disclosed | ✅ pay-per-call | ❌ | already built | `HOSTED_PROVIDER` (E20-11) |
| 5 | **CPU-only floor** (no detailed tier) | ✅ in-boundary | n/a (always on A1) | ❌ | none | `LOCAL_CPU` |

Notes:
- **#1** — join a GPU box (operator-owned, or a bare-metal rental: Hetzner/OVH/RunPod-BM)
  to the tailnet; set `ACX_GPU_ENDPOINT_URL=http://<tailscale-host>:<port>` and add the
  tailscale hostname to `ACX_GPU_ENDPOINT_ALLOWLIST`. A wake-on-burst + idle-stop script
  over Tailscale reproduces the OCI reaper's economics. Zero code change.
- **#2** — run vLLM (serving the winner) in a Modal/RunPod serverless container **with a
  Tailscale sidecar**, so the endpoint is a private `100.x` address you allowlist. Gets
  OCI-like bursty economics (per-second, scale-to-zero) **without** OCI quota, and stays
  in-boundary via the tailnet. Higher setup effort (image + tailnet auth key).
- **#3 / #4** — public providers; must go through `HOSTED_PROVIDER` (opt-in + disclosure).
  #3 is fastest to top quality, zero infra; #4 is cheaper open models (can serve the same
  Qwen-VL family as the in-house pick).
- **#5** — the day-0 unblock; no new anything, just a slower/lower ceiling detailed tier.

## Recommendation (layered)

1. **Day 0 — unblock regardless of the SR outcome:** serve the detailed tier on the
   **CPU provisional path (#5)**. Already built; the demo is not blocked by Oracle's
   decision. No work.
2. **Best next option — pick by residency:**
   - **Residency non-negotiable → #2 (serverless GPU + Tailscale sidecar)**, falling to
     **#1 (self-host over Tailscale)** if the sidecar setup is too much for the timeline.
     #2 is the closest drop-in for what OCI would have provided: bursty scale-to-zero
     economics, no quota, residency preserved, existing adapter reused.
   - **Residency can flex → #3 (hosted API, E20-11)** — fastest to quality, zero ops,
     per-image cost, disclosure fires. Prefer #4 if cost matters more than top quality.

**Single best next option: #2.** It reproduces the OCI bursty design (per-second,
scale-to-zero, in-boundary) using the adapter VLM-3 already shipped, and removes the one
thing OCI gated on — quota. If its ops feel heavy under launch pressure, drop to #3.

## Concrete steps — recommended path (#2), with #1/#3 as forks

1. Pick a serverless GPU host with custom-container + persistent-volume support
   (Modal or RunPod serverless). Confirm A10/L4/A100-class availability for the
   winner's VRAM (see the [decision memo](../../docs/tasks/vlm/VLM-3-gpu-detailed-tier-decision-memo.md)).
2. Build the serving image: vLLM (or llama.cpp) + the winning VLM weights, exposing
   `/v1/chat/completions`; reuse the same weights/quantization the OCI golden image would
   have baked.
3. Add a **Tailscale sidecar** (ephemeral auth key) so the container joins the tailnet;
   note its `100.x` address / MagicDNS name.
4. Config (no code change):
   - `ACX_GPU_ENDPOINT_URL=http://<tailnet-name>:<port>`
   - `ACX_GPU_ENDPOINT_ALLOWLIST=<tailnet-name>` (keeps `_is_private_gpu_endpoint` happy)
   - `ACX_GPU_ENDPOINT_API_KEY=<key>` if the container requires it
5. Flip the winner's `ProfileSpec` (`GPU_QWEN30B` or the decision-memo winner) to
   `available=True` in `scene/config/profiles.py`.
6. Re-run the **Slice-1 spike bench** + **bake-off** against the new endpoint
   (`scripts/eval_harness/bakeoff.py --endpoint <tailnet-url>`) — same scoring, confirm
   `provisional_cpu → final_gpu` supersede + the idle-stop leaves nothing running.

**Fork #1 (self-host):** skip serverless; point the same env at a Tailscale-joined GPU
box + a start/stop wake script. **Fork #3 (hosted API):** ignore the GPU env entirely;
set `ACX_HOSTED_PROVIDER_OPTIN=1` + `ACX_HOSTED_PROVIDER_API_KEY`, select the
`HOSTED_PROVIDER` profile, and confirm the `left_service_boundary=true` disclosure
surfaces to the operator/WP consent copy.

## Cost sketch

| Option | Cost shape |
| --- | --- |
| #1 self-host (owned) | capex only; ~$0 marginal (+ electricity) |
| #1 self-host (bare-metal rental) | ~$0.30–0.80/GPU-hr; cheap only if stopped between bursts |
| #2 serverless + sidecar | per-second GPU (~$0.5–2/hr equivalent) billed only during a burst → burst cost ≈ the OCI `~$0.20–0.40/100-img` estimate, no standing boot-volume charge |
| #3 hosted frontier API | per-image (~$0.001–0.01/img typical vision call); zero standing |
| #4 open-model API | per-token, cheaper than #3; zero standing |
| #5 CPU-only | $0 new (already on the A1) |

See [GPU-BURST-PROVISIONING.md § Costs](GPU-BURST-PROVISIONING.md#costs) for the OCI
baseline. Re-confirm live provider pricing before committing spend.

## Decision trigger

If the OCI SR is **denied** (capacity/risk/"contact sales") and the documented remedies
(confirm PAYG + billing history, lower the ask to 1, try another AD/region) do not clear
within the launch window, execute **#2** (or **#3** if residency can flex). Until then,
ship on **#5 (CPU)** so nothing is blocked.
