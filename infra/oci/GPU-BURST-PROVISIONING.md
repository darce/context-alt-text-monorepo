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
5. **Set tfvars + apply.** `gpu_shape` (default `VM.GPU.A10.1`), `gpu_image_ocid`,
   then `terraform apply` (or `./retry-apply.sh` — see the capacity caveat below).
6. **Run the Slice-1 spike bench.** Fill `docs/tasks/vlm/VLM-3-gpu-spike-*.json`
   (`cold_boot`, `stopped→warm_start` vs the 90 s target, `model_load`, `s/img`).
7. **Flip the ProfileSpec.** Set the winner's `available=True` + endpoint in
   `scene/config/profiles.py`; the `gpu_remote_adapter` + describe worker are already
   wired.

> **Quota ≠ capacity.** Even with an approved limit, A10 host capacity in an
> AD can be exhausted ("Out of host capacity"). `retry-apply.sh` cycles the three
> `us-ashburn-1` ADs with backoff to ride out transient shortages — this is why it
> exists.

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

## Sources

- [Oracle Cloud price list](https://www.oracle.com/cloud/price-list/) — GPU compute + Block Volume (source of truth)
- [OCI — Manage Your Service Limits](https://docs.oracle.com/en/solutions/oci-best-practices/manage-your-service-limits1.html)
- [OCI — Limits by Service (defaults)](https://docs.oracle.com/en-us/iaas/Content/General/service-limits/default.htm)
- [OCI LimitsClient API (read/validate only)](https://docs.oracle.com/en-us/iaas/tools/python/latest/api/limits/client/oci.limits.LimitsClient.html)
