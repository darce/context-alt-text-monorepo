# Runbook: OCI instance state & cost verification

> **Purpose.** Answer "is the GPU running / am I being billed?" from the
> laptop, without guessing. Every command here is read-only and was verified
> against the live tenancy on 2026-07-14. The machine-readable variants in
> [§ Dashboard feed](#dashboard-feed) are the intended data source for the
> in-house cost dashboard.

## The distinction that matters

**Instance state ≠ billing.** They answer different questions and you usually
want both:

- **State** (`RUNNING`/`STOPPED`) — is compute *currently* accruing? A
  `STOPPED` instance bills **$0 for OCPU/GPU**, but its **boot volume keeps
  billing** (block storage). `acx-gpu-burst` carries a 400 GB boot volume
  (baked VLM weights, ~$10–17/mo) — a deliberate trade for fast burst starts.
  Terminating the instance *with* its boot volume is the only way to zero that.
- **Actual charges** — what did the A10 really cost today? Only Cost Analysis
  answers this. A GPU that ran for three hours and was then stopped shows
  `STOPPED` but is not free.

## Expected steady state

| Instance | Shape | Expected state | Notes |
| --- | --- | --- | --- |
| `acx-backend` | `VM.Standard.A1.Flex` (4 OCPU / 24 GB, ARM, no GPU) | **RUNNING** | Always-Free; serves dev/staging/prod recognition |
| `acx-gpu-burst` | `VM.GPU.A10.1` (1× A10 24 GB VRAM, 30 OCPU / 240 GB host) | **STOPPED** | ~$2.00/GPU-hour **while running**. Created RUNNING so cloud-init finishes, then stopped. Live backend idle reaper plus guest self-stop cap — verify both, see below |

Anything else non-terminated in the tenancy is unexpected — investigate.

> **The GPU cost cap has two layers. Verify both before trusting either.**
>
> **Layer 1 — live backend-side idle reaper (`acx-backend`).**
> `scripts/deploy/gpu-lifecycle-install.sh` installs `acx-gpu-reap.timer` /
> `.service` on `acx-backend`. With the installer's defaults it runs every 2 min,
> STOPs the pinned `acx-gpu-burst` after the 300-second (5-minute) idle
> threshold, and forcibly STOPs it when the default max lease expires at 3600 seconds (60-minute cap).
> `--idle-seconds` and `--max-lease-seconds` can override those defaults;
> verify the installed values in `/etc/acx/gpu-lifecycle.env`. It
> reads the current per-environment load snapshots under `/run/acx-write/`
> and **fails closed** — if the snapshot is missing or stale it logs `load
> snapshot untrustworthy; refusing STOP`, exits `1`, and stops nothing. A
> failing `acx-gpu-reap.service` therefore means **no backend-side cap is in
> effect**, even though the timer looks healthy. Check both units, not just the
> timer:
>
> ```bash
> ssh ubuntu@acx-backend 'systemctl status acx-gpu-reap.timer acx-gpu-reap.service --no-pager | head -20'
> ssh ubuntu@acx-backend 'journalctl -u acx-gpu-reap.service -n 20 --no-pager'
> ssh ubuntu@acx-backend 'find /run/acx-write -type f \( -name "*.json" \) -ls'
> ```
>
> **Layer 2 — guest-side self-stop watchdog (`acx-gpu-burst`).**
> `infra/oci/gpu-cloud-init.yaml` installs `acx-gpu-self-stop.timer`, gated by
> `gpu_watchdog_enabled` and bounded by `gpu_max_uptime_seconds`
> (`infra/oci/variables.tf`). It calls OCI `instance-action --action STOP`
> using an instance principal, retries with explicit connect/read timeouts, and
> falls back to a local `poweroff` if the API path does not converge. It runs
> **inside the guest**, so a guest kernel hang or broken systemd defeats it;
> it is a backstop for layer 1, not a replacement.
>
> **The backend reaper covers only the pinned OCID** — it targets
> `acx-gpu-burst` by id and never stops hand-created smoke or one-off GPUs.
> It also refuses to stop on missing/stale load evidence; the guest watchdog
> is the second layer, not a substitute for checking the backend service.
> Always answer from the full instance list plus Cost Analysis, and keep the
> Budget alert below.

> **Observed 2026-08-04.** The unreaped-instance risk is not theoretical. The
> tenancy held a *second* A10, `acx-gpu-smoke-20260728-0218`
> (`role=gpu-smoke-ephemeral`, `owner=wanlora`), **`RUNNING` for 173 h** since
> 2026-07-28 — nothing reaped it despite the "ephemeral" role tag, because it
> was outside the OCID pin.

Region: **`us-ashburn-1`** (iad). There are **no child compartments**; every
resource lives under the tenancy root.

## Tenancy inventory snapshot (2026-07-16)

> Dated snapshot — the live CLI (commands in this runbook) is the source of
> truth; re-derive rather than trust this table when it matters. Captured
> during the VLM-6 A10 capacity drought.

**Instances** (non-terminated):

| Instance | Shape | AD | State | Notes |
| --- | --- | --- | --- | --- |
| `acx-backend` | `VM.Standard.A1.Flex` (4 OCPU / 24 GB) | AD-3 | RUNNING | Always-Free; dev/staging/prod recognition; Tailscale + SSH jump host |
| `acx-gpu-burst` | `VM.GPU.A10.1` | AD-1 | STOPPED | START blocked on "Out of host capacity" since 2026-07-16 |

**Custom images**:

| Image | Created | Purpose |
| --- | --- | --- |
| `acx-gpu-vlm-multiad-20260716` | 2026-07-16 | Baked Qwen3-VL-30B Q4 weights + `acx-gpu-vlm.service`; built for multi-AD launch (see quota caveat below) |
| `acx-gpu-qwen3vl30b-golden` | 2026-07-14 | Earlier golden image of the same stack |

**Boot volumes** (block volumes: none):

| Volume | Size | Cost |
| --- | --- | --- |
| `acx-gpu-burst (Boot Volume)` | 400 GB | ~$10–17/mo (bills while instance exists, even STOPPED) |
| `acx-backend (Boot Volume)` | 200 GB | Always-Free allowance |

**Service limits** (the binding constraint for GPU work):

| Limit | AD-1 | AD-2 | AD-3 | Implication |
| --- | --- | --- | --- | --- |
| `gpu-a10-count` | 1 (used 1) | **0** | **0** | Multi-AD fresh launch is quota-blocked everywhere; AD-1 quota consumed by `acx-gpu-burst`. Only levers: START retry on the existing instance, or a (free) service-limit increase request for AD-2/3 |
| `standard-a1-core-count` | 250 avail | — | — | Abundant ARM CPU headroom (Always-Free A1 counted separately) |
| `standard-e4-core-count` | 100 avail | — | — | Abundant x86 CPU headroom for Florence/Qwen CPU batch VMs |

**Network**:

| VCN | CIDR | Subnets |
| --- | --- | --- |
| `acx-vcn` | 10.0.0.0/16 | `acx-public-subnet` 10.0.1.0/24 (regional — usable in any AD; public IPs permitted) |
| `marketing-vcn` | 10.0.0.0/16 | `marketing-public-subnet` 10.0.1.0/24 (separate stack, no peering) |

Planned but not yet created: `acx-batch-subnet` 10.0.2.0/24 (private, NAT +
service gateway) per
[`oci-vm-reachability-tailscale-vcn-plan.md`](oci-vm-reachability-tailscale-vcn-plan.md).

Cost steady state at this snapshot: **~$10–17/mo** (the GPU boot volume) —
everything else is Always-Free or stopped.

For the disk/Docker side of the always-on `acx-backend` VM (what is consuming
the 193 GB root filesystem, which reapers exist, and which accounts can see
what), see
[`docs/operations/acx-backend-host-disk-audit-2026-08-04.md`](../operations/acx-backend-host-disk-audit-2026-08-04.md).

## Check instance state (CLI)

Verified working. Prints name / shape / state for every instance in the
compartment:

```sh
oci compute instance list \
  --compartment-id "$(grep -E '^\s*compartment_ocid' \
    ~/Development/context-alt-text-monorepo/infra/oci/terraform.tfvars \
    | sed -E 's/.*"(.*)".*/\1/')" \
  --all \
  --query 'data[].{name:"display-name",shape:shape,state:"lifecycle-state",created:"time-created"}' \
  --output table
```

Expected output shape:

```text
+----------------------------------+---------------+---------------------+---------+
| created                          | name          | shape               | state   |
+----------------------------------+---------------+---------------------+---------+
| 2026-07-14T14:50:59.828000+00:00 | acx-gpu-burst | VM.GPU.A10.1        | STOPPED |
| 2026-03-04T09:13:24.309000+00:00 | acx-backend   | VM.Standard.A1.Flex | RUNNING |
+----------------------------------+---------------+---------------------+---------+
```

**Tenancy-wide sweep** — catches anything outside the terraform-managed set
(orphaned bake hosts, manual experiments). Prefer this when the question is
"is *anything* running?":

```sh
oci search resource structured-search \
  --query-text "query instance resources where lifeCycleState != 'TERMINATED'" \
  --query 'data.items[].{name:"display-name",state:"lifecycle-state",id:identifier}' \
  --output table
```

Prereqs: `oci` CLI (`brew install oci-cli`) with `~/.oci/config` present. Both
commands are read-only — safe to run anytime.

## Check instance state (console)

[cloud.oracle.com](https://cloud.oracle.com) → hamburger menu → **Compute →
Instances**. Confirm region is **us-ashburn-1** (top-right region picker).
Look for `acx-gpu-burst` = **Stopped**.

## Check actual charges (console)

**This is the authoritative answer for "am I being billed?"** — instance state
is a proxy, this is the ledger.

Console → **Billing & Cost Management → Cost Analysis** → filter **Service =
Compute**. Shows GPU-hours actually incurred (today / this month). Break down
by resource to separate A10 compute from boot-volume storage.

Set a **Budget** with an alert (Billing & Cost Management → Budgets) if you
want to be told rather than having to remember to look.

## If the GPU is unexpectedly RUNNING

1. Confirm nothing is legitimately using it (a bake or eval in flight) — check
   `acx-gpu-vlm.service` on the host before stopping. The backend reaper
   refuses to stop while load evidence is missing or stale, but it is scoped to
   the pinned burst instance and is not a substitute for this manual check.
2. Stop it (billing halts on OCPU/GPU immediately):

   ```sh
   oci compute instance action --action STOP \
     --instance-id "$(terraform -chdir=infra/oci output -raw gpu_instance_id)"
   ```

3. The backend reaper is not a tenancy-wide safety net: it can stop only the
   pinned `acx-gpu-burst` instance. Confirm its state with
   `systemctl list-timers 'acx-gpu*'` and inspect
   `/etc/acx/gpu-lifecycle.env` (`GPU_INSTANCE_ID=…`) before relying on it for
   that instance. Hand-created or differently pinned GPUs still require this
   explicit operator stop path.

See [`infra/oci/README.md` § GPU burst host](../../infra/oci/README.md#gpu-burst-host-acx_gpu_burst)
for the lifecycle design and
[`infra/oci/GPU-BURST-PROVISIONING.md`](../../infra/oci/GPU-BURST-PROVISIONING.md)
for shape/quota/pricing details.

## Dashboard feed

For the in-house dashboard, use `--output json` and parse. The tenancy-wide
search is the better feed — it needs no compartment plumbing and catches
unmanaged instances:

```sh
oci search resource structured-search \
  --query-text "query instance resources where lifeCycleState != 'TERMINATED'" \
  --output json
```

Per-instance detail (shape config → OCPU/RAM, GPU shape, time-created):

```sh
oci compute instance list --compartment-id "$COMPARTMENT_OCID" --all --output json
```

Field notes for whoever builds the dashboard:

- `lifecycle-state` casing is **not stable across endpoints** — instance-list
  returns `RUNNING`, structured-search returns `Running`. Compare
  case-insensitively.
- **Derive "is billing compute" as `state == RUNNING`**, not from shape.
  Storage bills regardless; model boot volumes separately via `oci bv
  boot-volume list` if the dashboard should show true total cost.
- Shape alone doesn't imply cost tier — read `shape-config.ocpus` /
  `memory-in-gbs` for Flex shapes (`VM.Standard.A1.Flex` is Always-Free at
  4 OCPU / 24 GB; larger Flex configs are not).
- Rates (list, us-ashburn-1, for display only — confirm in Cost Analysis):
  `VM.GPU.A10.1` ≈ **$2.00/GPU-hour**; A1.Flex within Always-Free limits = $0.
- **Do not build billing totals from instance state.** Uptime × rate is an
  estimate; the Usage/Cost APIs are the ledger. If the dashboard must show
  real spend, drive it from the Usage API
  (`oci usage-api usage-summary request-summarized-usages`) rather than
  inferring from state.
- Credentials: the CLI uses `~/.oci/config`. A dashboard running unattended
  should use an **instance principal** (as the deploy path does) or a
  dedicated read-only API key — not an operator's personal key.
