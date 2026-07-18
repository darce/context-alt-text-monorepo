# Oracle Cloud Support Requests — A10 GPU capacity + limit (us-ashburn-1)

**Prepared:** 2026-07-16 · **Region:** us-ashburn-1 (home region) · **Shape:** `VM.GPU.A10.1`
**Tenancy OCID:** `ocid1.tenancy.oc1..aaaaaaaarnwywmplftprwcpsytd2g5wjxht45o4jgpidrjhulnzv24qp7q5q`

> Two separate Service Requests. **SR-1 (service limit increase) is the near-term
> unblock** — capacity currently exists in AD-2 and is gated only by a 0 limit.
> SR-2 documents the AD-1 host-capacity incident on the existing instance. All
> evidence below is from read-only OCI APIs (`ComputeCapacityReport`,
> `limits resource-availability get`) — no instance launch was performed.

## Confirmed state (verified 2026-07-16T18:18:13Z)

| Availability Domain | A10 host capacity (`ComputeCapacityReport`) | `gpu-a10-count` limit (available / used) |
| --- | --- | --- |
| `US-ASHBURN-AD-1` | `OUT_OF_HOST_CAPACITY` | 0 / **1** (held by stopped instance) |
| `US-ASHBURN-AD-2` | **`AVAILABLE`** | 0 / 0 (**limit is 0**) |
| `US-ASHBURN-AD-3` | `OUT_OF_HOST_CAPACITY` | 0 / 0 (**limit is 0**) |

**Interpretation:** the tenancy's entire A10 allowance is **1 unit, pinned to
AD-1**, and consumed by a stopped instance. AD-1 stop released its host, so a
`START` re-enters the capacity pool and fails (`Out of host capacity`). AD-2 has
host capacity right now but a service limit of 0 blocks any launch there. This is
therefore both a capacity issue (AD-1/AD-3) **and** a limit-headroom issue (AD-2).

---

## SR-1 — Service Limit Increase (PRIMARY)

- **Request type:** Service limit increase
- **Service category:** Compute
- **Resource:** *GPUs for GPU.A10 based VM and BM Instances* (`gpu-a10-count`)
- **Region:** us-ashburn-1
- **Scope:** per Availability Domain

| Availability Domain | Current limit | Requested limit | Justification |
| --- | --- | --- | --- |
| `US-ASHBURN-AD-2` | 0 | **1** (2 preferred) | Host capacity is currently `AVAILABLE`; a limit grant here unblocks immediately. |
| `US-ASHBURN-AD-3` | 0 | **1** | Structural multi-AD headroom; AD-3 host capacity is momentarily out but a limit is independent of instantaneous capacity and lets us launch when it returns. |

**Business justification (paste into SR):**

> We run short, bursty GPU workloads (VLM image-description batch jobs) on a single
> `VM.GPU.A10.1`. Our only A10 limit slot (1) is in US-ASHBURN-AD-1, which is
> currently out of host capacity, so our stopped instance cannot restart. We have
> verified via ComputeCapacityReport that US-ASHBURN-AD-2 has A10 host capacity
> available, but our service limit there is 0. We request a limit of 1 (ideally 2)
> in AD-2 and 1 in AD-3 so we can launch a fresh instance in whichever AD has
> capacity, rather than being pinned to a single AD. Total concurrent A10 usage
> remains 1; this is headroom for AD rotation, not a fleet increase.

**Expected outcome:** with AD-2 limit ≥ 1, launch a fresh `VM.GPU.A10.1` from our
existing region-scoped custom image in AD-2 (host capacity confirmed available),
run the batch, and terminate.

---

## SR-2 — Host-capacity incident report (AD-1)

- **Request type:** Technical support / capacity
- **Service category:** Compute — GPU capacity
- **Region:** us-ashburn-1
- **Availability Domain:** `US-ASHBURN-AD-1`
- **Shape:** `VM.GPU.A10.1`
- **Affected instance OCID:** `ocid1.instance.oc1.iad.anuwcljr2mcagaqcki4d2szgsymtr4ucpc3dsqzfsvwoj2gtemrjx2dlammq` (`acx-gpu-burst`, STOPPED)

**Description (paste into SR):**

> Stopped instance `acx-gpu-burst` (`VM.GPU.A10.1`) in US-ASHBURN-AD-1 cannot be
> started: every START returns "Out of host capacity". This is not a service-limit
> issue — our gpu-a10-count limit in AD-1 shows used=1 (this instance) with the
> instance already holding its slot. A ComputeCapacityReport for VM.GPU.A10.1 in
> US-ASHBURN-AD-1 returns availabilityStatus = OUT_OF_HOST_CAPACITY (verified
> 2026-07-16T18:18:13Z). We understand stopping an A10 releases its host; we are
> reporting the sustained AD-1 A10 scarcity and requesting guidance on when A10
> host capacity is expected to return to AD-1, and/or confirmation that the AD-2
> limit-increase path (SR-1) is the recommended route.

**Ask:** (a) ETA / guidance on A10 host-capacity return to AD-1; (b) confirm
whether an On-Demand Capacity Reservation is the recommended durable path for a
recurring A10 need in Ashburn.

---

## Evidence appendix — reproducible read-only commands

All commands below are non-mutating (no launch, no billing). `$COMP` =
tenancy/compartment OCID above.

**Host capacity (the authoritative check):**
```
oci compute compute-capacity-report create \
  --compartment-id $COMP --region us-ashburn-1 \
  --availability-domain "saEG:US-ASHBURN-AD-1" \
  --shape-availabilities '[{"instanceShape":"VM.GPU.A10.1"}]'
# -> shape-availabilities[0].availability-status = OUT_OF_HOST_CAPACITY   (AD-1)
# AD-2 -> AVAILABLE ; AD-3 -> OUT_OF_HOST_CAPACITY   (2026-07-16T18:18:13Z)
```

**Service limit vs usage:**
```
oci limits resource-availability get \
  --compartment-id $COMP --region us-ashburn-1 \
  --service-name compute --limit-name gpu-a10-count \
  --availability-domain "saEG:US-ASHBURN-AD-1"
# AD-1 -> available:0 used:1  |  AD-2 -> available:0 used:0  |  AD-3 -> available:0 used:0
```

**Affected instance:**
```
oci compute instance get --instance-id <instance OCID above>
# lifecycle-state: STOPPED | shape: VM.GPU.A10.1 | AD: saEG:US-ASHBURN-AD-1
```

## Submission notes

- Console path: **Help → Give feedback / Create support request**, or My Oracle
  Support. SR-1 uses the **Service limit increase** flow; SR-2 uses **Technical**.
- Submit **SR-1 first** — it is the fastest actual unblock.
- Do not delete/terminate `acx-gpu-burst` before SR-2 is filed: terminating frees
  the AD-1 limit slot but loses the only on-record A10 allocation while AD-1 has no
  capacity to re-grant it.
