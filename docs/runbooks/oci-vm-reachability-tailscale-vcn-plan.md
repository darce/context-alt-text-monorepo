# Plan + findings: clean remote-VM reachability via Tailscale subnet router + private VCN

> Culmination of the 2026-07-16 session's reachability/capacity work. Supersedes the ad-hoc
> public-IP + security-list approach that kept breaking. Companion to
> [`oci-vlm-batch-compute-learnings.md`](oci-vlm-batch-compute-learnings.md),
> [`../assessments/current/gpu-procurement-reachability-decomposition-2026-07-16.md`](../assessments/current/gpu-procurement-reachability-decomposition-2026-07-16.md),
> [`../assessments/current/cpu-tiered-serving-plan-2026-07-16.md`](../assessments/current/cpu-tiered-serving-plan-2026-07-16.md),
> and the async-pool adversarial review
> [`../assessments/current/gpu-availability-async-pool-adversarial-review-2026-07-16.md`](../assessments/current/gpu-availability-async-pool-adversarial-review-2026-07-16.md).
>
> Revised 2026-07-16 (r3) closing planning-review rounds 1+2 (runs
> `planning-review-tsvcn-20260716-01/-02`, findings PR-TSVCN-01..20 and PR2-TSVCN-01..23) —
> finding bodies live in handoff, not here.

## What we found this session (why this plan exists)

Trying to run description baselines (Florence CPU, Qwen-VL GPU) over the 646-image corpus, we hit
a chain of blockers and root-caused each:

1. **GPU capacity.** OCI `VM.GPU.A10.1` stop *releases the host* (Oracle billing doc), so restart
   re-enters the "Out of host capacity" lottery. Capacity is per **shape + AD** (us-ashburn has 3
   ADs); a stopped instance is AD-pinned, a fresh `launch` can rotate ADs. Not a lock/budget issue.
2. **Reachability was the real wall — and IP-based access is fundamentally fragile here:**
   - The laptop is an **M1 Mac, 8 GB RAM**, behind a **VPN with a rotating exit IP**
     (`37.120.137.201` now, `99.237.250.28` earlier). Any security-list `/32` rule goes stale the
     moment the exit rotates. **Root cause of every Florence SSH failure this session**: the
     subnet allowed SSH only from `99.237.250.28/32`; the laptop was on `37.120.137.201`. The VMs
     were fine — we burned 3 relaunches chasing an MTU red herring first.
   - MTU was investigated and **ruled out** (OCI 9000-MTU VNICs interoperate with 1500-MTU
     internet paths via PMTUD/MSS negotiation); WireGuard carries its own fixed MTU, removing the
     variable entirely.
   - Editing the *shared* subnet security list has blast radius (rightly guardrailed).
3. **Compute must stay off the laptop** (8 GB RAM, near-zero free; grok offload admission-refused
   on swap floor). The laptop is control-plane only — but note: laptop-*driven* request loops
   (the Qwen cell below) still require the laptop awake for the run's duration; the JSONL resume
   design makes interruptions cheap.
4. **Tailscale-per-node has a baked-identity trap.** The original A10 image carried a fixed
   Tailscale node identity; a fresh instance from it collides. Fresh nodes need *ephemeral* keys —
   and any reuse of that custom image must scrub the baked state (Phase 1 step 8).

**Conclusion:** stop using IPs as identity. Tailscale gives every node a stable identity
(100.x + MagicDNS) independent of IP, and WireGuard's fixed MTU sidesteps path-MTU concerns —
killing the rotating-IP problem and the MTU variable at once.

## Requirement update (2026-07-16): CPU-first bake-off

GPU provisioning is unreliable (capacity lottery above), so the description/caption bake-off must
**not depend on GPU at all**. The CPU-first matrix, with per-cell budgets, owners, and drivers
(all repo paths are repo-root-relative):

| Cell | Owner | Substrate | Corpus | Wall-clock budget | Driver |
|---|---|---|---|---|---|
| Florence-2-large CPU baseline | VLM-6 | `E4.Flex` 16 OCPU/64 GB, private-only | 646 images | ~7 h @ 39 s/img — **A1-measured** (`apps/prototype-description-service/scene/config/profiles.py:12`); sanity-check the first 10 images on E4 before committing to fan-out; 2 VMs ≈ 3.5 h | **(new)** on-box `florence_describe.py` wrapping `apps/prototype-description-service/scene/infrastructure/vlm/florence_local_adapter.py` — committed to `scripts/eval_harness/` before the first batch run (handoff next-action **#6**) |
| Qwen3-VL-30B-A3B Q4 GGUF CPU | VLM-6 | same | **spike first**, then subset (see gate below) | decided by spike | laptop-side `apps/prototype-description-service/scripts/eval_harness/describe_baseline.py` (tracked; moved out of the gitignored `out/` dir in r3) with `BAKEOFF_BASE_URL=http://<vm-private-ip>:8080` — **requires step-7's `:8080` ACL widening first**, and the llama.cpp server on the VM must use the serving flags below |
| ALTQ-1 caption-synthesis cells | ALTQ-1 | per ALTQ-1's plan | `apps/prototype-description-service/scene/tests/seed/golden.json` (37 entries) | **GPU-gated**: the A10 config matrix (≤ 1 h) is deferred until a launch lands — it is *not* part of the CPU-first critical path; only the text-only pass-2 weave cell runs on CPU | ALTQ-1's `bakeoff.py` — the `PROMPT_VARIANTS`/`dual_length` **version** exists only on `feature/altq-1` (it supersedes main's VLM-2B transport in the *same file* that `describe_baseline.py` imports). Merging `feature/altq-1` is owned by ALTQ-1 (handoff next-action **#5**) and must land **before** Qwen bake-off runs start — a mid-run merge rewrites the Qwen cell's transport under a resumable run |

**Qwen serving config (mandatory).** The llama.cpp server must run the live protocol from
[`../tasks/vlm/VLM-2B-a1-serving-notes.md`](../tasks/vlm/VLM-2B-a1-serving-notes.md) (normative —
see its "full live serving command"), in particular **`--image-max-tokens 1536`** and the vision
`--mmproj`: without the cap, Qwen3-VL dynamic resolution blew large golden images past 600 s and
aborted the first live run via bounded-stall; with it, healthy items run ~206–208 s/img. The
driver's per-item ceiling is 900 s (`--timeout 900`, the `bakeoff.py` default).

**Qwen CPU spike gate.** No CPU measurement exists for the 30B-A3B model
([`cpu-tiered-serving-plan-2026-07-16.md`](../assessments/current/cpu-tiered-serving-plan-2026-07-16.md)
§ model table and § 4): the nearest anchor is the 4B at **206 s/img** (A1 CPU, capped config).
Run that plan's **timeboxed 10-image probe** on the E4 box first — abort on **mean > 600 s/img
or RSS beyond the box** (both legs of the plan's criteria; the RSS leg is near-moot at 64 GB).
Be explicit about the expected outcome: at the 206 s anchor, the full 646-image corpus is
**37 h on one box — not a viable primary path** (≤ 12 h would require 67 s/img, a 3× improvement
no evidence supports). Therefore:

- **Primary (bake-off comparison): subset.** `golden.json` (37 entries, exists) now; **Golden-150
  when VLM-6 S1 curation lands** (no manifest exists yet). The tiered-serving plan's "Golden-100"
  award names a manifest that also doesn't exist — reconciling that ladder is handoff next-action
  **#7**. 37 × 206 s ≈ **2.1 h** — comfortably inside any session.
- **Full-646 is reserved for the winning config only**, via either **≥ 4-VM fan-out**
  (~162 img × 206 s ≈ 9.3 h per VM, at the cost of ~18 GB weight + mmproj NAT egress *per VM*)
  or an explicitly accepted single-box multi-day run (~37 h). Neither happens by default.

**GPU is opportunistic only**: if an A10 launch happens to succeed, the identical private-only
pattern applies. A failed GPU launch never blocks the CPU-first cells; the one GPU-*gated* row
(ALTQ-1's config matrix) carries its own deferral disposition in the matrix.

**Ownership / cross-plan drift:** VLM-6 owns the Florence and Qwen description baselines and this
topology; ALTQ-1 owns the synthesis cells. Two adjacent plans still prescribe the retired
public-subnet pattern and are flagged for amendment in handoff: the **ALTQ-1 task plan**
(next-action **#5**, owner ALTQ-1) and the **cpu-tiered-serving plan** (next-action **#7**, owner
VLM-6, which also settles the post-probe corpus ladder).

**Consequence for networking**: every CPU VM provisions at boot via **(new)**
`infra/oci/cpu-batch-cloud-init.yaml` (owned by next-action **#6**; `infra/oci/` today has only
the prod and GPU cloud-inits, and the GPU one bakes weights at image-bake time — a different
pattern). Boot downloads: llama.cpp build, the pinned **~18 GB** Q4 GGUF
(`docs/tasks/vlm/VLM-3-gpu-detailed-tier-task-plan.md` pins it) **plus the vision mmproj** —
so **NAT egress is mandatory** (Decision D1). At ~18 GB per boot, pre-baking a CPU image pays for
itself after roughly two relaunches — still an optimization, not the egress fix.

## Verified network facts (OCI CLI, 2026-07-16) — closes PA-TSVCN-02's unknowns

Re-runnable verification (run these before Phase 0 to confirm the facts still hold):

```bash
TENANCY=$(grep -m1 tenancy ~/.oci/config | cut -d= -f2 | tr -d ' ')
oci network vcn list --compartment-id "$TENANCY" \
  --query 'data[].{name:"display-name",cidr:"cidr-blocks"}' --output table
VCN=$(oci network vcn list --compartment-id "$TENANCY" \
  --query 'data[?"display-name"==`acx-vcn`].id | [0]' --raw-output)
oci network subnet list --compartment-id "$TENANCY" --vcn-id "$VCN" \
  --query 'data[].{name:"display-name",cidr:"cidr-block",private:"prohibit-public-ip-on-vnic"}' --output table
oci network nat-gateway list --compartment-id "$TENANCY" --vcn-id "$VCN" --output table
oci network service-gateway list --compartment-id "$TENANCY" --vcn-id "$VCN" --output table
```

Facts as of 2026-07-16:

- VCN **`acx-vcn` = `10.0.0.0/16`** (single CIDR block), us-ashburn-1.
- Its **only** subnet: `acx-public-subnet` **`10.0.1.0/24`** (public IPs permitted; virtual router
  `10.0.1.1`). Its route table `acx-route-table` has exactly one rule:
  `0.0.0.0/0 → internet gateway`.
- **No NAT gateway and no service gateway exist** in `acx-vcn`.
- A second VCN `marketing-vcn` **also uses `10.0.0.0/16`** — an advertised full-/16 route can only
  ever mean one of them and invites confusion/collision. Advertise only the batch subnet.

Two hard implications:

1. An OCI **internet gateway provides egress only to instances with public IPs**. A
   `--assign-public-ip false` VM in `acx-public-subnet` has **zero internet egress** — pip/HF/apt
   would stall silently after boot (the exact failure mode this plan exists to end).
2. Route tables are **per-subnet** in OCI, so private VMs cannot get NAT egress inside
   `acx-public-subnet` (its route table must keep the IGW rule for `acx-backend`). Reusing the
   public subnet for private batch VMs is therefore **rejected**, settling the open decision.

## Decisions

- **D1 (closes PA-TSVCN-01)** — create a **NAT gateway** in `acx-vcn` plus a **new private batch
  subnet `10.0.2.0/24` (`acx-batch-subnet`)** with its own route table (`0.0.0.0/0 → NAT`).
  All batch/bake-off VMs launch there, private-only, with full outbound internet (pip, HF, apt)
  and no inbound exposure. OCI NAT gateways have no hourly charge.
- **D2 (closes PA-TSVCN-02)** — CIDRs pinned: VCN `10.0.0.0/16`; batch subnet **`10.0.2.0/24`**
  (new, private); `advertise-routes=10.0.2.0/24` **only** — never the full `/16`.
- **D3 (closes PA-TSVCN-04)** — the tailnet ACL grants the laptop access **only to
  `10.0.2.0/24`**, not the VCN (see step 7's additive-ACL precondition). Prod (`acx-backend`,
  recognition, Postgres on `10.0.1.0/24`) is never reachable via the subnet route; the laptop
  keeps reaching `acx-backend` itself by its Tailscale node identity (100.x/MagicDNS), which
  needs no subnet route. Note: Tailscale subnet routers SNAT by default
  (`--snat-subnet-routes=true`), so routed packets arrive in the batch subnet with
  `acx-backend`'s VCN source IP (`10.0.1.x`) — covered by the batch security list's
  `10.0.1.0/24` ingress rule; no tailnet CIDRs appear inside the VCN.
- **D4 (closes PR-TSVCN-05)** — batch-subnet ingress is scoped to **`10.0.1.0/24`** (subnet
  router SNAT source + Phase-2 in-VCN prod callers) plus **`10.0.2.0/24`** (worker
  intercommunication), NOT the full `/16`. Trade-off accepted: any future legitimate consumer
  subnet needs a seclist edit, and the scoping is CIDR-granular only (`protocol: all` keeps all
  ports open *from* those two subnets) — finer port scoping can come later if the batch subnet
  ever hosts anything sensitive.

## Plan (steps to execute)

### Phase 0 — One-time setup (operator; `acx-backend` shell + Tailscale admin are gated for the agent)

OCI side (agent-runnable; each command captures the OCID the next one consumes):

```bash
# 1. NAT gateway (wait until AVAILABLE so step 2 can reference it)
TENANCY=$(grep -m1 tenancy ~/.oci/config | cut -d= -f2 | tr -d ' ')
VCN=$(oci network vcn list --compartment-id "$TENANCY" \
  --query 'data[?"display-name"==`acx-vcn`].id | [0]' --raw-output)
NAT=$(oci network nat-gateway create --compartment-id "$TENANCY" --vcn-id "$VCN" \
  --display-name acx-nat --wait-for-state AVAILABLE \
  --query 'data.id' --raw-output)

# 2. Private route table (0.0.0.0/0 -> NAT)
RT=$(oci network route-table create --compartment-id "$TENANCY" --vcn-id "$VCN" \
  --display-name acx-batch-rt \
  --route-rules "[{\"destination\":\"0.0.0.0/0\",\"destinationType\":\"CIDR_BLOCK\",\"networkEntityId\":\"$NAT\"}]" \
  --query 'data.id' --raw-output)

# 3. Batch security list (scoped ingress per D4) + subnet
SL=$(oci network security-list create --compartment-id "$TENANCY" --vcn-id "$VCN" \
  --display-name acx-batch-seclist \
  --ingress-security-rules '[{"protocol":"all","source":"10.0.1.0/24"},{"protocol":"all","source":"10.0.2.0/24"}]' \
  --egress-security-rules '[{"protocol":"all","destination":"0.0.0.0/0"}]' \
  --query 'data.id' --raw-output)
SUBNET=$(oci network subnet create --compartment-id "$TENANCY" --vcn-id "$VCN" \
  --display-name acx-batch-subnet --cidr-block 10.0.2.0/24 \
  --prohibit-public-ip-on-vnic true --route-table-id "$RT" \
  --security-list-ids "[\"$SL\"]" --query 'data.id' --raw-output)
```

Tailscale side (operator):

4. On `acx-backend`: enable forwarding — `net.ipv4.ip_forward=1`, `net.ipv6.conf.all.forwarding=1`
   (persist in `/etc/sysctl.d/99-tailscale.conf`).
5. On `acx-backend`: first capture current prefs — `tailscale debug prefs` (note every
   non-default flag) — then `sudo tailscale up --advertise-routes=10.0.2.0/24` **restating those
   flags**. Modern `tailscale up` (≥1.8) **errors and prints the required flag set** if
   non-default flags are omitted — read the error, restate, rerun; it only silently drops flags
   with `--reset`, which must not be used here. Do **not** add `--accept-routes`: the router
   advertises, it has no route to consume, and accepting future third-party routes would widen
   prod's surface.
6. Tailscale admin console: **approve** the `10.0.2.0/24` route for `acx-backend` (or add an
   `autoApprovers` entry — the node is tagged `tag:oci-vm`, so:
   `"autoApprovers": {"routes": {"10.0.2.0/24": ["tag:oci-vm"]}}`).
7. Tailscale ACL — **precondition: ACL grants are additive.** Inspect the policy file first; if
   the default `{"action":"accept","src":["*"],"dst":["*:*"]}` rule (or any rule whose dst covers
   `10.0.2.0/24`) is present, a scoped rule below is decorative — every tailnet node reaches the
   batch subnet regardless. Either remove/narrow the broad rule (default-deny posture) or
   explicitly accept tailnet-wide batch-subnet reachability in writing here. Then add:

   ```jsonc
   {"action": "accept", "src": ["<laptop-user-or-tag>"], "dst": ["10.0.2.0/24:22"]}
   ```

   The Qwen cell additionally needs `"10.0.2.0/24:8080"` (llama.cpp) — add it when that cell
   runs; the matrix row calls this out. Never add a `10.0.0.0/16` or `10.0.1.0/24` destination.

**Phase 0 acceptance (must pass before any batch launch).** Re-derive the shell context first —
steps 4–7 happen on other machines, plausibly days later:

```bash
TENANCY=$(grep -m1 tenancy ~/.oci/config | cut -d= -f2 | tr -d ' ')
VCN=$(oci network vcn list --compartment-id "$TENANCY" \
  --query 'data[?"display-name"==`acx-vcn`].id | [0]' --raw-output)
SUBNET=$(oci network subnet list --compartment-id "$TENANCY" --vcn-id "$VCN" \
  --query 'data[?"display-name"==`acx-batch-subnet`].id | [0]' --raw-output)
```

- a. `oci network nat-gateway list --compartment-id "$TENANCY" --vcn-id "$VCN"` shows `acx-nat`
  AVAILABLE with `block-traffic: false`; subnet list shows `acx-batch-subnet 10.0.2.0/24` with
  `prohibit-public-ip-on-vnic: true` and route table `acx-batch-rt`.
- b. On `acx-backend`: `sysctl net.ipv4.ip_forward net.ipv6.conf.all.forwarding` returns `1` for
  **both**. Route approval — check from the **laptop** (peer view; `Self.PrimaryRoutes` is
  omitempty and unreliable): `tailscale status --json | jq '.Peer[] | select(.HostName=="acx-backend") | .PrimaryRoutes'`
  must list `10.0.2.0/24`; the admin console is authoritative if the field is null.
- c. On the laptop: `netstat -rn | grep '10.0.2'` shows the subnet routed via the Tailscale
  interface (macOS renders it `10.0.2/24`), and `tailscale ping acx-backend` succeeds. If the
  route is absent, confirm **"Use Tailscale subnets"** is enabled in the macOS Tailscale app
  before debugging anything else.
- d. **End-to-end canary**: launch one minimal private VM in `acx-batch-subnet` (any small flex
  shape **on an Ubuntu image**) **with the laptop's public key injected**
  (`--ssh-authorized-keys-file ~/.ssh/id_ed25519.pub`), then
  `ssh -o ConnectTimeout=30 ubuntu@<private-ip>` from the laptop and, on the VM,
  `curl -sI --max-time 30 https://pypi.org` (proves NAT egress). On SSH failure walk the ladder
  in order: **laptop route installed (c)** → route approved (b) → ACL (7) → forwarding (b) →
  security list (3). **Terminate the canary on both success and failure paths** (reuse one canary
  across ladder iterations; don't accumulate debug VMs), with `--preserve-boot-volume false`.
  Do not proceed to Phase 1 until the canary passes.

**Phase 0 abort:** if Phase 0 half-completes (NAT created but subnet fails; route advertised but
approval abandoned), run the decommission deletes (**step 15, *Decommission* bullet**) for
whatever was created — half-built state is inert but must not linger unrecorded; note the abort
in the handoff log.

### Phase 1 — Batch launches switch to private-only (agent-automatable once Phase 0 lands)

Corpus source (both the rsync source and the Qwen driver depend on it): the originals root is
`/Volumes/Butter/WP/vlm/app/public/wp-content/uploads/` per the tracked inventory
`benchmarks/private/vlm-corpus-attachments-20260716.tsv` (untracked: name-bearing)
(646 rows, no size column — measure with `du -sh` before transfer). **Pre-run mount check:**
`test -d /Volumes/Butter/WP/vlm/app/public/wp-content/uploads || echo "MOUNT BUTTER FIRST"` —
an unmounted volume means silent empty rsyncs and mid-run driver crashes.

8. Launch bake-off VMs in `acx-batch-subnet` with `--assign-public-ip false` and the laptop
   pubkey injected. Reference launch (fill AD/image from `oci compute image list`):

   ```bash
   oci compute instance launch --compartment-id "$TENANCY" \
     --availability-domain <AD> --shape VM.Standard.E4.Flex \
     --shape-config '{"ocpus":16,"memoryInGBs":64}' \
     --image-id <ubuntu-22.04-image-ocid> --subnet-id "$SUBNET" \
     --assign-public-ip false --ssh-authorized-keys-file ~/.ssh/id_ed25519.pub \
     --user-data-file infra/oci/cpu-batch-cloud-init.yaml \
     --display-name acx-batch-<run-id>
   ```

   `<run-id>` format: `<model>-<substrate>-YYYYMMDD-HHMM` (e.g. `qwen30b-cpu-20260716-1430`).
   GPU (A10 from the custom image, rotating AD-1/2/3) is opportunistic acceleration only — and
   any launch from that image **must scrub the baked Tailscale identity** (cloud-init:
   `systemctl disable --now tailscaled && rm -rf /var/lib/tailscale`) — it carries the fixed
   node identity this doc's finding #4 diagnosed.
9. Discover each VM's private IP:
   `oci compute instance list-vnics --instance-id <id> --query 'data[0]."private-ip"' --raw-output`
   Then gate on **both** reachability and provisioning:
   `ssh -o ConnectTimeout=30 -o BatchMode=yes ubuntu@<private-ip> 'timeout 1800 cloud-init status --wait'`
   **Triage by failure class** — they are not interchangeable:
   - *SSH connection fails* → network problem → walk the Phase-0 ladder (the VM is almost never
     the problem; this session proved it).
   - *Exit 124 (timeout)* → provisioning still running — the ~18 GB weight pull can exceed
     30 min on throttled mirrors; extend the timeout or wait, don't touch the network.
   - *cloud-init exit 1/2 (error/degraded)* → provisioning failed; SSH already proved
     reachability, so read `/var/log/cloud-init-output.log` on the VM — the ladder will find
     nothing.
   For the **Qwen cell** add a server-readiness gate before the first request:
   `curl -s --max-time 10 http://<private-ip>:8080/health` (needs step-7's `:8080` ACL widening) —
   `cloud-init` done ≠ 18 GB model loaded.
10. **On-box cells (Florence):** transfer the corpus with bounded I/O —
    `rsync -az --timeout=60 -e "ssh -o ServerAliveInterval=15 -o ServerAliveCountMax=4" /Volumes/Butter/WP/vlm/app/public/wp-content/uploads/ ubuntu@<private-ip>:corpus/`
    — then run the driver named in the matrix. A cell without a committed driver does not launch.
    **Laptop-driven cells (Qwen):** no corpus transfer — `describe_baseline.py` streams each
    image over `/v1/chat/completions`; run it from the laptop repo with `BAKEOFF_BASE_URL` set.
    The laptop must stay awake for the run; the JSONL progressive log makes it resumable after
    interruption (`CHUNK`-sized appends, completed IDs skipped on restart).
11. **Secure results before terminate** (a face-pass output was already lost once to ephemeral
    storage). *Florence (on-box results):*
    `rsync -az --timeout=60 ubuntu@<private-ip>:results/ docs/tasks/vlm/bakeoff-results/<run-id>/`.
    *Qwen (results land laptop-side in `docs/tasks/vlm/bakeoff-results/` already):* nothing to
    pull. **Both:** verify **row count = corpus count**, commit — THEN terminate.
12. Terminate the VM with `--preserve-boot-volume false` (otherwise boot volumes orphan and
    accumulate across launches). Nothing else to clean up — no Tailscale node, no security-list
    rule, no public IP.

### Phase 2 — Production async worker pool (later; separate task)

13. The in-VCN service launches private worker VMs in `acx-batch-subnet` and reaches them by
    private IP directly (no Tailscale in the prod path). Apply the adversarial review's fixes:
    bounded GPU-claim timeout + shared backoff + circuit breaker + **CPU-Florence fallback** so a
    request never hangs. The CPU-first bake-off results directly inform which CPU model becomes
    that fallback.

### Phase 3 — Decommission the fragile path (and, eventually, the router)

14. Once migrated, remove the stale public-IP SSH `/32` rules from the shared security list; keep
    batch subnets no-public-IP.
15. **Router health + decommission:**
    - *Health*: before each batch session, run acceptance check c (laptop route present, plus
      `tailscale ping acx-backend`). If the router is down, dev access is down (known SPOF, prod
      unaffected); break-glass fallback is **Option A** (per-VM ephemeral key) for that session
      only.
    - *Decommission* (retirement, or Phase-0 abort cleanup): on `acx-backend`
      `sudo tailscale up --advertise-routes=` (restating other flags), delete the route + ACL
      entry in the admin console, revert the sysctl forwarding entries, and delete
      `acx-batch-subnet` + `acx-batch-rt` + `acx-batch-seclist` + `acx-nat` in OCI (that order).
      Record the decommission in the handoff log so the router doesn't linger as unaudited
      infrastructure.

## Option A — Tailscale on each VM (fallback / break-glass)

Each fresh VM joins the tailnet via cloud-init
`tailscale up --authkey=<ephemeral+preauth+tagged+reusable key>` (`tag:batch`); reach by MagicDNS.
Ephemeral keys auto-remove dead nodes (avoids the baked-identity trap). Use only when the subnet
router is down (Phase 3 health step) or if putting `acx-backend` in the routing path becomes
undesirable; it reintroduces per-VM secret handling.

## Risks / open items

- **Single point for dev access**: if `acx-backend` (subnet router) is down, laptop→VM access is
  down. Production is unaffected (in-VCN). Mitigated by the Phase-3 health check + Option A
  break-glass; acceptable for dev.
- **Prod host on the batch data plane**: with SNAT, all laptop↔VM bytes (corpus up, results
  down, Qwen request loop) transit `acx-backend` as the relay hop. This is network relay only —
  no batch *compute* on the prod host (the learnings doc forbids that) — but sustained multi-GB
  transfers share the prod NIC; schedule large transfers off peak and watch the host during
  them. Weight downloads (~18 GB + mmproj per boot for Qwen) go via the NAT gateway, **not**
  through `acx-backend`.
- **CIDR overlap**: `marketing-vcn` also uses `10.0.0.0/16`. Mitigated by advertising only
  `10.0.2.0/24`; if marketing ever needs tailnet routing, it must be re-IPed or given a distinct
  advertised range first.
- **Operator-gated bootstrap**: Phase 0 steps 4–7 need `acx-backend` shell + Tailscale admin —
  the agent is gated from both; the operator runs them once. OCI steps 1–3 are agent-runnable as
  written (commands capture their own OCIDs).
- **Prod ML deps**: the description service still ships the seeded stub (no torch); real
  Florence/Qwen workers need the ML-deps images built regardless of reachability. The CPU-first
  bake-off produces exactly the dependency manifest those images need.

## Immediate next action

Operator runs **Phase 0** (agent can run OCI steps 1–3; Tailscale steps 4–7 are operator-only),
finishing with the canary acceptance check (d). In parallel, the agent completes handoff
next-action **#6** (commit `florence_describe.py` + `infra/oci/cpu-batch-cloud-init.yaml`). Then:
the **Qwen CPU 10-image spike**, and on its projection the **subset bake-off** (golden.json now,
Golden-150 post-S1) — CPU-first and private-only in `acx-batch-subnet`, ending the
security-list/IP churn permanently. The stranded public-IP VM#3 (`132.145.140.89`) is already
terminated.
