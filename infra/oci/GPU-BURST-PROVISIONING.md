# Bursty OCI-GPU (A10) Provisioning + Costs

Operational runbook for standing up the scale-to-zero detailed-description GPU tier
(`oci_core_instance.acx_gpu_burst` in `main.tf`, shape `VM.GPU.A10.1`). Companion to
the [VLM-3 task plan](../../docs/tasks/vlm/VLM-3-gpu-detailed-tier-task-plan.md) and
[decision memo](../../docs/tasks/vlm/VLM-3-gpu-detailed-tier-decision-memo.md). The
code + Terraform landed with VLM-3; this doc covers the operator steps that remain
before a GPU can actually serve.

## TL;DR — can A10 quota be procured programmatically over SSH/Tailscale?

**No — not the grant itself.** OCI GPU service limits default to **0** on a new PAYG
tenancy. Raising them is a **console-submitted Service Limit Increase request** that
Oracle Support reviews (**usually a few days**). There is **no public API/CLI that
grants** an increase — the Limits API is **read/validate-only**
(`list_limit_values`, `get-resource-availability`, `getLimitDefinitions`).

**What SSH + Tailscale *can* do** (the admin plane — OCI CLI + Terraform run from the
`acx-backend` A1 host reachable over Tailscale):

| Step | Programmatic over SSH/Tailscale? | Mechanism |
| --- | --- | --- |
| Read current GPU limit / usage | ✅ | `oci limits value list` / `oci limits resource-availability get` |
| Check A10 availability in an AD | ✅ | `oci limits resource-availability get --service-name compute --limit-name gpu-a10-count --availability-domain <AD>` |
| Create compartment **quota policy** (allocate within tenancy limit) | ✅ | `oci limits quota create` |
| **Request a service-limit increase** (raise the tenancy ceiling) | ❌ **console/support only** | Console → Limits, Quotas and Usage → *Request a service limit increase* |
| Validate the increase after approval | ✅ | `oci limits value list` |
| Build golden image, `terraform apply`, start/stop instance, run spike | ✅ | OCI CLI + Terraform + SSH |

So: Tailscale/SSH gives you the full automation plane for **everything except the
quota approval**, which is a human console request Oracle grants asynchronously.

> **Trial / Always-Free tenancies cannot get GPU at all** — a PAYG (pay-as-you-go)
> upgrade is a prerequisite for the limit-increase request to be approvable.

## Procurement sequence

1. **Confirm PAYG.** GPU limit increases are only approvable on a paid tenancy.
2. **Submit the limit-increase request (console).** Governance & Administration →
   *Limits, Quotas and Usage* → *Request a service limit increase*. Service category
   **Compute**, resource **"GPUs for GPU.A10 based VM and BM Instances"**, region
   `us-ashburn-1`, limit **1** (one `VM.GPU.A10.1` = 1 A10), with a justification.
   Track the support request; expect a few days.
3. **Validate the grant** (CLI, over Tailscale):
   ```bash
   oci limits value list --compartment-id <tenancy_ocid> \
     --service-name compute --region us-ashburn-1 \
     --query "data[?contains(\"name\",'a10')]"
   ```
4. **Build the golden GPU image.** x86_64 image with NVIDIA driver + Docker +
   `nvidia-container-toolkit` + the winning VLM weights baked (see
   `gpu-cloud-init.yaml`). Capture its OCID → `gpu_image_ocid` in `terraform.tfvars`.
   Spike measurement candidate: `Qwen3-VL-30B-A3B-Instruct @ Q4 GGUF` (~18 GB, proves
   the 24 GB fit). Boot volume `gpu_boot_volume_size_in_gbs = 400`.
5. **Set tfvars, validate, + apply.** `gpu_shape` (default `VM.GPU.A10.1`),
   `gpu_image_ocid`, then run `make test-infra-terraform` from the repository root.
   This mandatory release gate runs `terraform init -backend=false` and
   `terraform validate`; it fails if Terraform or the OCI provider is unavailable.
   After it passes, run `terraform apply` (or `./retry-apply.sh` — see the capacity
   caveat below).
   The GPU resource carries the `project=acx`, `env=production`, `role=gpu-burst`,
   `scale_to_zero=true`, and `purpose=gpu-spike-bench` freeform tags. The spike bench
   requires that pinned purpose tag before it permits any lifecycle action.
   Terraform ignores subsequent instance `state` drift so an apply does not undo
   an idle-reaper STOP; the declared `RUNNING` state is only for initial cloud-init.
6. **Run the Slice-1 spike bench.** Fill `docs/tasks/vlm/VLM-3-gpu-spike-*.json`
   (`cold_boot`, `stopped→warm_start` vs the 90 s target, `model_load`, `s/img`).
7. **Flip the ProfileSpec.** Set the winner's `available=True` + endpoint in
   `scene/config/profiles.py`; the `gpu_remote_adapter` + describe worker are already
   wired.

> **Quota ≠ capacity.** Even with an approved limit, A10 host capacity in an
> AD can be exhausted ("Out of host capacity"). `retry-apply.sh` cycles the three
> `us-ashburn-1` ADs with backoff to ride out transient shortages — this is why it
> exists.

## Console runbook: request the A10 service-limit increase

The one step that is **not** scriptable (see TL;DR). Do it in the OCI Console as a
tenancy administrator.

1. **Sign in** to the [OCI Console](https://cloud.oracle.com) as an admin in the
   **home region** (GPU is requested per-region; use the region you will run the
   burst in — this repo assumes `us-ashburn-1`).
2. Top-left **hamburger menu → Governance & Administration → Limits, Quotas and
   Usage** (older tenancies: **Governance → Limits, Quotas and Usage**).
3. Set the **Region** selector (top of the page) to `US East (Ashburn)`.
4. In the **Service** filter choose **Compute**. In the **Resource** search box type
   `A10` and select **"GPUs for GPU.A10 based VM and BM Instances"**. Confirm the
   current **Limit** column reads **0** (the default) and note the per-AD breakdown.
5. Click **Request a service limit increase** (top-right, or the link on the row).
6. Fill the request form:
   - **Service Category:** Compute
   - **Resource:** GPUs for GPU.A10 based VM and BM Instances
   - **Availability Domain:** pick one AD (or "region-wide" if offered); you can name
     the specific AD with A10 capacity from step 4.
   - **New limit value:** **1** (one `VM.GPU.A10.1` = 1 A10). Ask for exactly what you
     need — an oversized ask invites scrutiny (see below).
   - **Reason:** a concrete business justification, e.g. *"Bursty scale-to-zero
     inference for an image alt-text service; one A10 warm-started on demand, stopped
     when idle. Est. <X> GPU-hours/month."* Vague reasons slow manual review.
7. **Create Support Request.** You get a Support Request (SR) number; track it under
   **Help → Support / Support Requests**. A confirmation email goes to the primary
   contact when granted.
8. **After approval, validate over Tailscale/CLI** (do not trust the email alone):
   ```bash
   oci limits value list --compartment-id <tenancy_ocid> \
     --service-name compute --region us-ashburn-1 \
     --query "data[?contains(\"name\",'a10')].{name:name,ad:\"availability-domain\",value:value}"
   ```
   A non-zero `value` for the A10 name means you can `terraform apply`.

## What the approval hinges on — and why a PAYG GPU request can be denied

**Timing.** Non-GPU limit bumps are often auto-approved in minutes. GPU requests are
high-cost, capacity-constrained, and abuse-prone, so they usually route to **manual
review — typically 1–3 business days**, occasionally longer or escalated to sales.

**What the decision hinges on:**

- **Account risk / billing standing.** New tenancies with thin or no payment history,
  an outstanding balance, or risk/fraud flags are the most common cause of GPU denials
  — Oracle (like other clouds) limits high-cost GPU to bound unpaid-cost exposure.
  A tenancy with a clean billing record and some spend history clears faster.
- **PAYG vs credits/trial.** It must be a genuine **pay-as-you-go** tenancy. Free
  Tier / trial / credits-only accounts **cannot** get GPU limits — upgrade to PAYG
  first.
- **Regional & AD capacity.** The grant is region/AD-specific. If the requested AD has
  no free A10 capacity, the request can be held or denied even for a good account
  (quota and capacity are separate — a grant still meets "Out of host capacity" at
  launch; that is what `retry-apply.sh` handles).
- **Requested size.** Asking for 1 A10 is routine; large GPU asks (many GPUs, or the
  bigger A100/H100/B200 tiers) are more likely to be routed to **sales consultation**
  ("contact sales") rather than auto-approved.
- **Justification quality.** A specific, plausible workload reason speeds manual
  review; a blank or generic reason invites back-and-forth.
- **Region availability of the shape.** If `VM.GPU.A10.1` is not offered in the
  tenancy's selected region at all, the resource will not appear — switch to a region
  that lists it before requesting.

**If denied:** read the SR response — it usually names the cause (risk hold, capacity,
or "contact sales"). Typical remedies: confirm PAYG + add/settle a payment method and
let some billing history accrue; lower the requested limit to 1; pick a different AD or
region with A10 capacity; or engage OCI sales for the tier. Re-submitting the same
request against the same conditions will be denied again. **If it stays denied, see
[GPU-TIER-FALLBACK-PLAN.md](GPU-TIER-FALLBACK-PLAN.md)** — the detailed tier is
backend-agnostic (VLM-3's `gpu_remote_adapter` + hosted-provider seam), so falling back
to a self-hosted-over-Tailscale, serverless, or hosted-API GPU is a config decision, not
a rebuild.

## Costs

Figures are **PAYG list** and region/time-dependent — treat the live
[Oracle Cloud price list](https://www.oracle.com/cloud/price-list/) as the source of
truth and re-confirm before committing spend. Annual Universal Credits typically
discount GPU 25–45% below list.

| Item | Basis | Approx. cost |
| --- | --- | --- |
| `VM.GPU.A10.1` compute (1× A10 24 GB, 30 OCPU, 240 GB) | PAYG, **billed only while running** | **~$2.00 / GPU-hour** (list) |
| Per detailed-description **burst** (100-img batch ≈ ~90 s warm-start + ~5 s/img ≈ ~10 min) | scale-to-zero: stops when queue drains | **~$0.20–0.40 / 100-img batch** |
| Boot volume (400 GB, balanced) — **standing**, persists while instance is stopped | Block Volume storage + performance units | **~$15–20 / month** |
| Idle compute between bursts | instance stopped by the reaper | **$0** |
| Egress / NAT | image pulls on first boot; reuses existing VCN NAT | negligible |

**Scale-to-zero is not zero.** Compute is $0 between bursts, but the **400 GB boot
volume with the baked weights bills continuously (~$15–20/mo)** whether or not the
GPU is running. To reach true $0-at-rest you would terminate the instance + boot
volume and rebuild the image per burst — trading the standing storage cost for a
much longer cold-boot on every burst. The design keeps the boot volume warm on
purpose to hit the 90 s warm-start target.

**Headroom shapes** (only if the bake-off winner does not fit 24 GB): `VM.GPU.A100.1`
(40 GB) or `VM.GPU.A10.2` (48 GB) at higher $/hr — each needs its **own** service-limit
increase request; an A10 grant does not cover them.

## GPU burst smoke proof and cost reconciliation

Run the offline proof before an operator considers a live run. The live command is
deliberately gated and must run on `acx-backend`; it is never a substitute for the
compensating STOP or the host reaper.

The smoke records four independent checks:

1. **STOP attribution.** After the instance is `STOPPED`, it queries the OCI Audit
   event window for the first completed `STOP`/`StopInstance` event for that OCID and
   records its `principalName` (or `principalId`) as `stop_principal`, together with
   `stop_event_time`. The default allow-list principal is **`gpu_lifecycle`**, the
   dedicated lifecycle reaper identity. A human console principal fails the smoke.
   Override or add an accepted name/OCID with repeatable
   `--expected-stop-principal PRINCIPAL` options.
2. **Second-burst idempotence.** Once the first run and reaper have completed, the
   smoke submits the same fixture sample a second time, requires the same run/tenant
   envelope in the response, then polls the same `/items` endpoint once more. It
   compares persisted item IDs (falling back to `created_at`) and records the replay
   POST and follow-up poll transport counters. Missing counter telemetry is
   inconclusive and fails the gate. The report check is named
   `second_burst_no_enqueue`.
3. **Shared GPU-state timeline.** Dry mode feeds the same state snapshot vocabulary
   used by `gpu_lifecycle` through the live transition recorder. Its report therefore
   has the same transition shape,
   `STOPPED→STARTING→RUNNING→STOPPING→STOPPED`, with monotonic elapsed timestamps.
4. **Usage reconciliation.** `scripts/gpu_cost_report.py` is stdlib-only and never
   calls the network. It multiplies each burst's RUNNING seconds by the hourly rate
   (default **$2.00/GPU-hour**, matching the [OCI instance state and cost runbook](../../docs/runbooks/oci-instance-state-and-cost.md), rate line 175)
   and compares that estimate with the OCI Usage API's `computedAmount` for the same
   resource/time window. The default disagreement tolerance is 25%; a larger
   disagreement exits 2.

Export the Usage API JSON with the OCI CLI, then reconcile it with the smoke report:

```bash
cat > usage-request.json <<'JSON'
{
  "tenantId": "<tenancy-ocid>",
  "timeFrom": "2026-01-01T00:00:00Z",
  "timeTo": "2026-01-01T01:00:00Z",
  "granularity": "HOURLY",
  "queryType": "COST",
  "groupBy": ["resourceId", "resourceName", "service"]
}
JSON
oci usage-api usage-summary request-summarized-usages \
  --request-summarized-usages-details file://usage-request.json \
  --output json > usage.json
SMOKE_EVIDENCE="$(find .workbay/tmp/gpu-burst-smoke -maxdepth 1 -type f \
  -name 'GPUSMOKE-1-evidence-*.json' -print -quit)"
test -n "$SMOKE_EVIDENCE"
python3 scripts/gpu_cost_report.py usage.json --smoke-report "$SMOKE_EVIDENCE"
```

Multiple exports may be supplied by repeating `--usage-json` (or by passing
multiple positional paths). The equivalent Make target is:

```bash
SMOKE_EVIDENCE="$(find .workbay/tmp/gpu-burst-smoke -maxdepth 1 -type f \
  -name 'GPUSMOKE-1-evidence-*.json' -print -quit)"
test -n "$SMOKE_EVIDENCE"
make gpu-cost-report GPU_COST_USAGE_JSON="usage.json" \
  GPU_COST_SMOKE_REPORT="$SMOKE_EVIDENCE"
```

## Sources

- [Oracle Cloud price list](https://www.oracle.com/cloud/price-list/) — GPU compute + Block Volume (source of truth)
- [OCI — Manage Your Service Limits](https://docs.oracle.com/en/solutions/oci-best-practices/manage-your-service-limits1.html)
- [OCI — Limits by Service (defaults)](https://docs.oracle.com/en-us/iaas/Content/General/service-limits/default.htm)
- [OCI LimitsClient API (read/validate only)](https://docs.oracle.com/en-us/iaas/tools/python/latest/api/limits/client/oci.limits.LimitsClient.html)
