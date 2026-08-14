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
| `acx-gpu-burst` | `VM.GPU.A10.1` (1× A10 24 GB VRAM, 30 OCPU / 240 GB host) | **STOPPED** | ~$2.00/GPU-hour **while running**. Created RUNNING so cloud-init finishes, then stopped; `acx-gpu-idle-reaper.timer` stops it after 300 s idle |

Anything else non-terminated in the tenancy is unexpected — investigate.

> **Observed 2026-08-04.** That line earned itself. The tenancy held a *second*
> A10, `acx-gpu-smoke-20260728-0218` (`role=gpu-smoke-ephemeral`,
> `owner=wanlora`), **`RUNNING` for 173 h** since 2026-07-28 — nothing reaped it
> despite the "ephemeral" role tag, because `scale_to_zero` is only set on the
> burst instance. The `acx-gpu-idle-reaper.timer` on `acx-gpu-burst` makes GPU
> spend *look* self-limiting; hand-created smoke and one-off instances have no
> reaper. **Always answer from the full instance list plus Cost Analysis, never
> from one named instance.**

Region: **`us-ashburn-1`** (iad). There are **no child compartments**; every
resource lives under the tenancy root.

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
   `acx-gpu-vlm.service` on the host before stopping; the idle reaper treats an
   in-flight job as busy so a dead writer cannot stop a working GPU.
2. Stop it (billing halts on OCPU/GPU immediately):

   ```sh
   oci compute instance action --action STOP \
     --instance-id "$(terraform -chdir=infra/oci output -raw gpu_instance_id)"
   ```

3. If the idle reaper should have caught it, check `/etc/acx/gpu-reaper.env`
   has `GPU_INSTANCE_ID=…` set (copied from `gpu-reaper.env.example` after
   apply) and read `/var/log/acx-gpu-reaper.log`.

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
