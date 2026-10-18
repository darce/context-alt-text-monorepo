# Runbook + learnings: running VLM description baselines on OCI

> Captures what we learned getting the VLM-6 description baseline (Florence CPU, Qwen-VL GPU)
> to run over the ~646-image corpus, the blockers hit, and the solutions that worked / could
> work. Companion to the strategic decomposition in
> [`docs/assessments/current/gpu-procurement-reachability-decomposition-2026-07-16.md`](../assessments/current/gpu-procurement-reachability-decomposition-2026-07-16.md).

## TL;DR

- **The laptop is control-plane only.** It is an 8 GB-RAM machine that runs at near-zero free
  RAM under normal load (offload admission refused: swap-volume disk floor breached). It cannot
  host torch / model inference. **All model compute runs on OCI**, orchestrated from the laptop.
- **Two independent blockers**, not one: (1) OCI **A10 GPU capacity** ("Out of host capacity"),
  and (2) **reachability** of a freshly-provisioned instance.
- **The reachability unlock:** `acx-public-subnet` is **public + regional** → any fresh instance
  gets a public IP → **direct SSH** (inject `~/.ssh/id_rsa`). This removes the Tailscale-new-node
  problem for both CPU and GPU boxes. Then run the describe **on-box** (rsync images + a
  standalone script) so there is no cross-host reachability at all.
- **Compute placement that works:** a *dedicated, isolated* OCI VM per batch — never the laptop,
  never the shared prod host (`acx-backend`).

## The blockers, and what each taught us

### 1. OCI A10 GPU capacity

- **Stopping an A10 releases its host** (Oracle billing doc: `VM.GPU.A10` "stopping pauses
  billing"). So a `START` of a stopped A10 re-enters the capacity lottery and returns
  `InternalError: Out of host capacity`. This is not a lock, budget, or config problem — it is
  genuine host scarcity (verified: no resource locks, no work-requests, no capacity reservation,
  MTD spend ~$14, budget fine).
- **Capacity is per shape + availability domain.** us-ashburn has **AD-1/2/3**. A *stopped*
  instance is pinned to its AD; a fresh **`launch`** can rotate all 3 ADs.
- **Bare-metal A100/H100 keep their host across stop** (reliable restart) but cost $32–100/hr
  (8-GPU minimum) and are scarce at provision — overkill for a batch.
- **On-demand Capacity Reservation** is the only *guarantee*, but bills a reserved A10
  continuously (~$1,400/mo) and still needs capacity to *create* → not viable for burst.
- **Community-proven pattern:** a tight multi-AD `launch`-retry loop; capacity frees in small
  random windows and "whoever is retrying that second gets it."

### 2. Reachability (the hidden blocker)

- The original A10 (`acx-gpu-burst`) was reachable only over **Tailscale** (private subnet, no
  public endpoint by design). A *fresh* instance is a **new Tailscale node**, and a custom image
  carries the original node's identity → a fresh launch would need Tailscale re-auth with a
  **guarded auth key** via cloud-init. The security classifier (correctly) blocks handling that
  key casually.
- **`docs/runbooks/key-management.md` does NOT help here** — it governs API-key/tenant auth
  (client→service), a different layer from instance networking. Same category error twice.
- **Solution that works:** launch on **`acx-public-subnet`** (`prohibit-public-ip-on-vnic: false`,
  regional). The instance gets a **public IP**; SSH directly with an injected key. No Tailscale,
  no jump host, no guarded key. Lock the security list to SSH-from-operator only; never expose
  the model port publicly.

### 3. Compute placement / host selection

- **Not the laptop** — 8 GB RAM, no torch, no disk headroom.
- **Not the shared prod host (`acx-backend`)** — running a multi-hour torch batch there competes
  with prod recognition + the operator's curation, and the sanctioned footprint on that box is
  *narrow, validated ops only* (cf. `make admin-oci-mint`), not arbitrary heavy compute.
- **Dedicated, isolated VM per batch** — provision, run, tear down. Zero prod impact.

## Working solution (proven for Florence, same shape for Qwen)

1. **Provision a dedicated VM** on `acx-public-subnet` with a public IP + injected SSH key.
   - Florence CPU: `VM.Standard.E4.Flex` (x86, abundant), 16 OCPU / 32 GB (~$0.45/hr). Ubuntu 22.04.
   - Qwen GPU: `VM.GPU.A10.1` **from the custom image** `acx-gpu-vlm-multiad-20260716` (carries the
     baked Qwen-VL-30B GGUF + `acx-gpu-vlm.service`), rotating AD-1/2/3 until one has capacity.
2. **On-box compute.** rsync the exact 646 originals (from the attachment TSV) + a standalone
   describe script. No service deploy, no harness on the box:
   - `florence_describe.py` loads Florence-2-large-ft in-process (torch CPU) and captions each image.
   - the Qwen equivalent POSTs each image to the box's local `llama.cpp` (`localhost:8000`).
   - Both write a **progressive, resumable** JSONL + markdown report with per-image latency.
3. **Pull results** back to the durable committed dir (`docs/tasks/vlm/bakeoff-results/`).
4. **Tear down** the instance (owed every time — pair every launch with a terminate).

Custom images can be created from a **stopped** instance and are **region-scoped**, so they let
the baked weights travel to whichever AD has capacity — the image doesn't change capacity odds,
it just makes AD-rotation viable.

## Candidate solutions by goal

| Goal | Best option | Notes |
| --- | --- | --- |
| One-off baseline, reliable | **Dedicated CPU VM + Florence-large** | abundant capacity, ~$0.45/hr, ~2.5–7h; slower/lower-quality than Qwen |
| One-off baseline, best quality | **Multi-AD A10 launch-from-image + on-box Qwen** | fast (~1–3.5h) but capacity-gated; reachability solved via public subnet |
| Production serving, reliable | **CPU-Florence default** | no GPU lottery, privacy-safe; needs the ML-deps description image actually built (prod ships the seeded stub, no torch) |
| Production, GPU quality tier | **Reservation-backed A10** (optional) | ~$1,400/mo reserved; only if the bake-off proves Qwen materially better |
| Never viable here | Hosted VLM API | sends user images off-box → violates the privacy stance |

## Operational gotchas (learned the hard way)

- **Fresh VM SSH resets/times out during cloud-init** (~2–5 min). Poll with backoff; "connection
  reset" early is normal, not a failure.
- **Florence-2 on CPU** may try to import `flash_attn`; use the eager-attention fallback (recent
  `transformers` handle it) rather than building flash-attn on CPU.
- **The classifier gates prod-host shell** (`acx-backend`) and **billed transactions**; dedicated
  isolated instances launch fine, but expect prompts on `oci ... launch/terminate` and `ssh`.
- **Durability:** irreplaceable outputs go to `docs/tasks/vlm/bakeoff-results/` (committed), never
  only the session scratchpad (a prior face-pass was lost that way).
- **Teardown discipline:** every A10 start/launch must pair with a stop/terminate; the on-VM
  idle-reaper (300 s) is a backstop, not a substitute.

## Bigger picture

The description pipeline should be **architected not to depend on scarce GPUs**: CPU-Florence as
the reliable production baseline, GPU-Qwen as an *optional* reservation-backed quality tier. The
bake-off's job is to quantify the Qwen-vs-Florence quality gap so that decision is evidence-based.
For *one-off* baselines, dedicated isolated OCI VMs + the public-subnet + on-box pattern above is
the repeatable recipe.
