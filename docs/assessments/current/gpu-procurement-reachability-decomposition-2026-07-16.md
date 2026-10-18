# Evaluation: GPU procurement + reachability for VLM description (2026-07-16)

> Written to decompose the "can't get an A10" blocker hit while running the VLM-6 Qwen3-VL-30B
> baseline, and to separate the **one-time bake-off** problem from the **production serving** risk.

## Problem statement

The VLM-6 image-description baseline needs Qwen3-VL-30B, which only runs on the OCI A10 GPU
(`acx-gpu-burst`). Every `START` returns `InternalError: "Out of host capacity"`. This is not a
config/lock/budget issue — it is genuine OCI on-demand A10 scarcity in `us-ashburn-1`. Two
distinct problems hide inside it:

1. **One-time:** get *this* bake-off/baseline run to happen.
2. **Structural:** if production ever serves a GPU-tier caption model, the same procurement
   scarcity becomes a live availability risk — the user's key concern.

## What we learned this turn (facts, verified)

- **A10 stop releases its host** (Oracle billing doc: A10 "stopping pauses billing"). So every
  restart re-enters the capacity lottery. Bare-metal A100/H100 *keep* their host across stop.
- **Capacity is per shape+AD.** A *stopped* instance is pinned to its AD (`US-ASHBURN-AD-1`); a
  *fresh launch* can rotate AD-1/2/3 → 3× the search surface. A custom image doesn't change
  capacity odds; it only lets the baked weights travel (custom image is region-scoped; **boot
  volumes are AD-local**).
- **Custom image created** (`acx-gpu-vlm-multiad-20260716`, PROVISIONING) — captures the baked
  Qwen weights + `acx-gpu-vlm.service` (llama.cpp on :8000). Subnet + 3 ADs gathered.
- **Reachability is the real multi-AD blocker, not capacity.** The GPU has **no public endpoint
  by design** — it is reached only over **Tailscale**. A fresh instance is a *new* Tailscale
  node; the image carries the original node's identity, so a fresh launch needs Tailscale
  re-auth (a **guarded auth key**, via cloud-init user-data) to be reachable from the laptop.
- **`docs/runbooks/key-management.md` does NOT solve reachability.** It governs **API key /
  tenant** minting (Track 1 `api.altcontext.com` prod DB vs Track 2 `localhost:8000` fixtures).
  The A10 Qwen endpoint is a raw llama.cpp `/v1/chat/completions` server hit by the eval-harness
  `BakeoffClient` — **no API key involved**. Reachability is a *networking* problem (Tailscale /
  VCN routing), a different domain from key-management. Key-mgmt is orthogonal here.
- **CPU shapes are abundant but slow for VLM:** Florence-CPU ~14–39s/img (≈2.5–7h for 646,
  feasible) but needs the ML-deps description image built (prod image ships without torch);
  Qwen-VL on CPU ~3.4min/img (≈37h, infeasible).
- **Bare-metal A100/H100 keep host across stop (reliable) but cost $32–100/hr** (8-GPU minimum)
  and are scarce at *provision* — overkill for a 646-image job.
- **Laptop host is resource-starved** (offload admission refused: swap-volume 4.4GiB < 8GiB
  floor; 8GB RAM heavily swapped). A separate constraint that blocks local heavy work (grok).

## Decomposition

| # | Sub-problem | Owner surface | Coupling |
| --- | --- | --- | --- |
| **P1** | Land the one-time Qwen bake-off/baseline run | eval harness + a GPU (any AD) | independent of prod |
| **P2** | Reach a bake GPU without the fresh-node Tailscale problem | run describe **on-box** + acx-backend jump | unblocks P1 |
| **P3** | Production serving tier: CPU-Florence (reliable) vs GPU-Qwen (quality) | description-service profiles + deploy | informed by the bake-off numbers |
| **P4** | Production GPU procurement strategy (if P3 picks GPU) | infra: reservation / multi-region / CPU fallback | the user's structural concern |

## Reachability evaluation — is on-box + rsync practical? **Yes.**

The cleanest sidestep of the fresh-node Tailscale problem is the **standard bake-host pattern**
(exactly what `VLM-6-...-task-plan.md` §Execution locus already specifies):

1. Launch a fresh A10 from the custom image in whichever AD has capacity (rotate).
2. **Reach it via `acx-backend` as an SSH jump** — acx-backend is in the same VCN, so it reaches
   the fresh A10 by **private IP**; the laptop reaches acx-backend over Tailscale. **No Tailscale
   on the fresh node, no guarded auth key.**
3. `rsync` the 646 images (~140 MB) to the fresh A10 through the jump.
4. Run the describe **on the fresh A10 against `localhost:8000`** (its own llama.cpp Qwen server).
5. Pull the JSONL/report back through the jump; **terminate** the instance.

This is practical and removes the credential dependency. Cost: SSH-jump plumbing + rsync + a
terminate step; the instance still lives outside terraform (drift/teardown discipline). It does
NOT remove the *capacity* gamble — you still need one AD to have a free A10.

## Production risk (P3/P4) — the user's real concern

**If production serves a GPU caption model, OCI A10 scarcity is a live availability risk**, not
just a bake-off nuisance. Options, filtered by the product's self-hosted/privacy stance
(user images never leave to a third party; only celebs01 is publishable):

- **CPU-Florence baseline (recommended default):** abundant capacity, no GPU lottery, privacy
  intact. Cost: lower caption quality than Qwen, and needs the ML-deps description image built +
  deployed (the current prod image is seeded-stub, no torch). Latency ~14–39s/img (async worker).
- **GPU-Qwen quality tier, gated on reservable capacity:** only viable with an **on-demand
  capacity reservation** (~$1,400/mo per reserved A10) or accepting intermittent availability.
  Not a reliable always-on prod path on burst capacity.
- **Hosted VLM API:** fastest + no procurement, but **conflicts with the privacy stance** (sends
  user images off-box) → effectively off the table for the product surface.

**The bake-off's job is to quantify the Qwen-vs-Florence quality gap** so P3 is decided on
evidence: if Florence-CPU is "good enough," production is GPU-free and the procurement risk
evaporates; if Qwen is materially better, production needs a reservation-backed GPU tier (cost)
or a hybrid (CPU default + GPU for a flagged subset).

## Recommended next steps (decomposed)

1. **P1+P2 (unblock now):** keep the AD-1 start-retry running; add an **on-box + jump** path so
   any caught A10 (any AD) runs the describe locally on the box — no Tailscale-new-node, no key.
2. **P3 (decide the tier):** finish the bake-off (Qwen baseline + Florence-CPU comparison on the
   same 646) to get the quality-vs-cost delta. This is the gate for the production decision.
3. **P4 (de-risk prod):** default the production plan to **CPU-Florence** (reliable, privacy-
   safe); treat GPU-Qwen as an *optional* reservation-backed quality tier, not the baseline —
   so production is never hostage to A10 capacity.
