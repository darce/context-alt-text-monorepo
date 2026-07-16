# Plan + findings: clean remote-VM reachability via Tailscale subnet router + private VCN

> Culmination of the 2026-07-16 session's reachability/capacity work. Supersedes the ad-hoc
> public-IP + security-list approach that kept breaking. Companion to
> [`oci-vlm-batch-compute-learnings.md`](oci-vlm-batch-compute-learnings.md),
> [`../assessments/current/gpu-procurement-reachability-decomposition-2026-07-16.md`](../assessments/current/gpu-procurement-reachability-decomposition-2026-07-16.md),
> and the async-pool adversarial review
> [`../assessments/current/gpu-availability-async-pool-adversarial-review-2026-07-16.md`](../assessments/current/gpu-availability-async-pool-adversarial-review-2026-07-16.md).
>
> Revised 2026-07-16 to close plan-analyze findings PA-TSVCN-01..05 (review-run 429,
> session `plan-analyze-tsvcn-20260716`) and to fold in the **CPU-first bake-off** requirement.

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
   - Public-IP SSH also fights OCI **jumbo-frame (9000) MTU** on the 1500-MTU internet path.
   - Editing the *shared* subnet security list has blast radius (rightly guardrailed).
3. **Compute must stay off the laptop** (8 GB RAM, near-zero free; grok offload admission-refused
   on swap floor). The laptop is control-plane only.
4. **Tailscale-per-node has a baked-identity trap.** The original A10 image carried a fixed
   Tailscale node identity; a fresh instance from it collides. Fresh nodes need *ephemeral* keys.

**Conclusion:** stop using IPs as identity. Tailscale gives every node a stable identity
(100.x + MagicDNS) independent of IP, and WireGuard carries its own MTU — killing both the
rotating-IP and jumbo-MTU problems at once.

## Requirement update (2026-07-16): CPU-first bake-off

GPU provisioning is unreliable (capacity lottery above), so the description/caption bake-off must
**not depend on GPU at all**. This plan's batch topology now serves a CPU-first matrix:

- **Shape**: `VM.Standard.E4.Flex` (start 16 OCPU / 64 GB; resize per model if throughput demands).
- **Models**:
  - Florence-2-large on CPU torch (existing baseline path).
  - Qwen3-VL **Q4 GGUF via llama.cpp** on CPU (quantization already pinned in VLM-3B) — replaces
    the GPU Qwen path on the critical path.
  - **Caption-synthesis pass (ALTQ-1)**: dual-length output (short alt + long description),
    describe-then-ground — rides the same private-VM harness and the same 646-image corpus /
    Golden-150 subset.
- **GPU is opportunistic only**: if an A10 launch happens to succeed, the identical private-only
  pattern applies (custom image, private IP, terminate after). A failed GPU launch never blocks
  the bake-off.
- **Consequence for networking**: every CPU VM installs deps at boot (CPU torch, llama.cpp,
  GGUF/HF weights ≈ several GB), so **NAT egress is mandatory** (Decision D1 below). Once the CPU
  stack stabilizes, optionally pre-bake a CPU image to cut boot time — an optimization, not a
  prerequisite.

## Verified network facts (OCI CLI, 2026-07-16) — closes PA-TSVCN-02's unknowns

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
  and no inbound exposure. OCI NAT gateways have no hourly charge. Pre-baking images remains an
  optional later optimization (see CPU-first section), not the egress fix.
- **D2 (closes PA-TSVCN-02)** — CIDRs pinned: VCN `10.0.0.0/16`; batch subnet **`10.0.2.0/24`**
  (new, private); `advertise-routes=10.0.2.0/24` **only** — never the full `/16`.
- **D3 (closes PA-TSVCN-04)** — the tailnet ACL grants the laptop access **only to
  `10.0.2.0/24`**, not the VCN. Prod (`acx-backend`, recognition, Postgres on `10.0.1.0/24`) is
  never reachable via the subnet route; the laptop keeps reaching `acx-backend` itself the way it
  already does — by its Tailscale node identity (100.x/MagicDNS), which needs no subnet route.
  Note: Tailscale subnet routers SNAT by default (`--snat-subnet-routes=true`), so routed packets
  arrive in the batch subnet with `acx-backend`'s VCN source IP (`10.0.1.x`) — the intra-VCN
  security-list rule covers them; no tailnet CIDRs appear inside the VCN.

## Plan (steps to execute)

### Phase 0 — One-time setup (operator; `acx-backend` shell + Tailscale admin are gated for the agent)

OCI side (operator or agent — OCI CLI is available; `$TENANCY` = root compartment OCID,
`$VCN` = `acx-vcn` OCID):

1. Create the NAT gateway:
   `oci network nat-gateway create --compartment-id $TENANCY --vcn-id $VCN --display-name acx-nat`
2. Create the private route table:
   `oci network route-table create --compartment-id $TENANCY --vcn-id $VCN --display-name acx-batch-rt --route-rules '[{"destination":"0.0.0.0/0","destinationType":"CIDR_BLOCK","networkEntityId":"<nat-gateway-ocid>"}]'`
3. Create the batch security list (ingress: all protocols from `10.0.0.0/16`; egress: all to
   `0.0.0.0/0`) and the subnet:
   `oci network subnet create --compartment-id $TENANCY --vcn-id $VCN --display-name acx-batch-subnet --cidr-block 10.0.2.0/24 --prohibit-public-ip-on-vnic true --route-table-id <acx-batch-rt-ocid> --security-list-ids '["<batch-seclist-ocid>"]'`

Tailscale side (operator):

4. On `acx-backend`: enable forwarding — `net.ipv4.ip_forward=1`, `net.ipv6.conf.all.forwarding=1`
   (persist in `/etc/sysctl.d/99-tailscale.conf`).
5. On `acx-backend`: `sudo tailscale up --advertise-routes=10.0.2.0/24 --accept-routes` (keep
   existing flags — rerunning `tailscale up` drops flags not restated).
6. Tailscale admin console: **approve** the `10.0.2.0/24` route for `acx-backend` (or add an
   `autoApprovers` entry if the node is tagged, e.g. `"autoApprovers": {"routes": {"10.0.2.0/24": ["tag:infra"]}}`).
7. Tailscale ACL — scoped, not VCN-wide:

   ```jsonc
   {"action": "accept", "src": ["<laptop-user-or-tag>"], "dst": ["10.0.2.0/24:22"]}
   ```

   Widen ports only when a concrete need appears (e.g. a metrics port). Do **not** add a
   `10.0.0.0/16` or `10.0.1.0/24` destination.

**Phase 0 acceptance (must pass before any batch launch — closes PA-TSVCN-03's Phase-0 gap):**

- a. `oci network nat-gateway list ... --vcn-id $VCN` shows `acx-nat` AVAILABLE with
  `block-traffic: false`; subnet list shows `acx-batch-subnet 10.0.2.0/24` with
  `prohibit-public-ip-on-vnic: true` and the batch route table.
- b. On `acx-backend`: `sysctl net.ipv4.ip_forward` returns `1`; `tailscale status --json | jq '.Self.PrimaryRoutes'` (or admin console) shows `10.0.2.0/24` advertised **and approved**.
- c. On the laptop: `tailscale status` shows `acx-backend` online; `netstat -rn | grep '10.0.2'`
  shows the subnet routed via the Tailscale interface.
- d. **End-to-end canary**: launch one minimal private VM in `acx-batch-subnet` (any small flex
  shape), then `ssh -o ConnectTimeout=30 ubuntu@<private-ip>` from the laptop and, on the VM,
  `curl -sI --max-time 30 https://pypi.org` (proves NAT egress). Terminate the canary. If SSH
  fails, walk the ladder in order: route approved (b) → ACL (7) → forwarding (b) → security list
  (3). Do not proceed to Phase 1 until the canary passes.

### Phase 1 — Batch launches switch to private-only (agent-automatable once Phase 0 lands)

8. Launch bake-off VMs in `acx-batch-subnet` with `--assign-public-ip false`:
   **CPU-first** — `E4.Flex` (16 OCPU/64 GB) for Florence-2 CPU, Qwen3-VL Q4 GGUF (llama.cpp),
   and the ALTQ-1 caption-synthesis pass. GPU (A10 from the custom image, rotating AD-1/2/3) is
   opportunistic acceleration only — a capacity miss never blocks the run.
9. Discover each VM's private IP (closes PA-TSVCN-03's Phase-1 gap):
   `oci compute instance list-vnics --instance-id <id> --query 'data[0]."private-ip"' --raw-output`
   Then verify reachability with a bounded probe before handing the VM to the batch driver:
   `ssh -o ConnectTimeout=30 -o BatchMode=yes ubuntu@<private-ip> true` — on failure, rerun the
   Phase-0 ladder instead of relaunching the VM (the VM is almost never the problem; this session
   proved it).
10. SSH/rsync the 646 originals, run the on-box describe/caption jobs.
11. Terminate the VM after the batch — nothing to clean up (no Tailscale node, no security-list
    rule, no public IP).

### Phase 2 — Production async worker pool (later; separate task)

12. The in-VCN service launches private worker VMs in `acx-batch-subnet` and reaches them by
    private IP directly (no Tailscale in the prod path). Apply the adversarial review's fixes:
    bounded GPU-claim timeout + shared backoff + circuit breaker + **CPU-Florence fallback** so a
    request never hangs. The CPU-first bake-off results directly inform which CPU model becomes
    that fallback.

### Phase 3 — Decommission the fragile path (and, eventually, the router)

13. Once migrated, remove the stale public-IP SSH `/32` rules from the shared security list; keep
    batch subnets no-public-IP.
14. **Router health + decommission (closes PA-TSVCN-05):**
    - *Health*: before each batch session, run the laptop-side checks (Phase 0 acceptance c) —
      one command, `tailscale status`, plus a `tailscale ping acx-backend`. If the router is down,
      dev access is down (known SPOF, prod unaffected); break-glass fallback is **Option A**
      (per-VM ephemeral key) for that session only.
    - *Decommission* (if/when the batch pattern is retired): on `acx-backend`
      `sudo tailscale up --advertise-routes=` (restating other flags), delete the route + ACL
      entry in the admin console, revert the sysctl forwarding entries, and delete
      `acx-batch-subnet` + `acx-batch-rt` + `acx-nat` in OCI. Record the decommission in the
      handoff log so the router doesn't linger as unaudited infrastructure.

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
- **CIDR overlap**: `marketing-vcn` also uses `10.0.0.0/16`. Mitigated by advertising only
  `10.0.2.0/24`; if marketing ever needs tailnet routing, it must be re-IPed or given a distinct
  advertised range first.
- **Operator-gated bootstrap**: Phase 0 steps 4–7 need `acx-backend` shell + Tailscale admin —
  the agent is gated from both; the operator runs them once. OCI steps 1–3 are agent-runnable.
- **`tailscale up` flag amnesia**: rerunning `tailscale up` with new flags drops unstated ones —
  capture the current flag set on `acx-backend` before step 5.
- **Prod ML deps**: the description service still ships the seeded stub (no torch); real
  Florence/Qwen workers need the ML-deps images built regardless of reachability. The CPU-first
  bake-off produces exactly the dependency manifest those images need.

## Immediate next action

Operator runs **Phase 0** (OCI steps 1–3 can be delegated to the agent; Tailscale steps 4–7 are
operator-only), finishing with the canary acceptance check (d). Then the agent relaunches the
bake-off **CPU-first and private-only** in `acx-batch-subnet` — ending the security-list/IP churn
permanently. The stranded public-IP VM#3 (`132.145.140.89`) is already terminated.
