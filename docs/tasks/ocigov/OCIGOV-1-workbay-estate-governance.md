# OCIGOV-1. WorkBay Estate — VM/OCI governance as a separate application

> **Metadata**
>
> - **Date**: 2026-08-04 EST
> - **Author**: Claude Opus 5 (`claude-opus-5`)
> - **Project**: `workbay` (new package) + `context-alt-text-monorepo` (`infra/oci/`)
> - **Task ID**: `OCIGOV-1`
> - **Target Branch**: `feature/ocigov-1`
> - **Review Coverage Target**: 2
> - **Status**: **DRAFT** — not accepted, not baselined. Written for `plan-analyze` triage.

---

## Objective

Stand up **WorkBay Estate** — a third workbay application, sibling to *handoff*
(task state) and *orchestrator* (work dispatch) — that owns **machines**:
provider inventory, capacity-slot accounting, tag-driven instance lifecycle, and
scheduled reclamation of lanes and disk. When complete, no OCI instance, lane
sandbox, or image generation on the estate persists because nothing was watching
it.

## Problem Statement

The OCI estate has grown six workloads (ACX production, WordPress demo, remote
lane execution, VLM burst GPU, WAN2.2 diffusion, prospective local codegen)
across two shapes of instance, and there is **no component whose job is the
machines themselves**. The consequences are measured, not hypothetical
— see [`docs/operations/acx-vm-workload-organization-2026-08-04.md`](../../operations/acx-vm-workload-organization-2026-08-04.md)
(findings N1–N5b) and [`docs/operations/acx-backend-host-disk-audit-2026-08-04.md`](../../operations/acx-backend-host-disk-audit-2026-08-04.md):

1. **Capacity is accounted in the wrong unit.** A *stopped* A10 still consumes
   its availability domain's `gpu-a10-count` service limit. Region-wide the
   tenancy has **two** free A10 slots; nothing in the system knows that number,
   so "we stopped it, we're fine" is false and the next burst can fail to launch.
2. **Lifecycle policy is pinned to an instance name.** `infra/oci/cloud-init.yaml`
   passes `--instance-id ${GPU_INSTANCE_ID}` to the reaper, and the reaper runs
   *on the instance it is meant to stop*. Hand-created instances get no reaper
   (one already ran 173 h); a wedged OS cannot reap itself; and `acx-backend`,
   the one always-on box, has no `oci` CLI at all so it cannot supervise.
3. **Every reclaimer is dispatch-triggered.** The lane sandbox sweep runs inside
   `remote_agent.sh` at dispatch time, so it stops exactly when a burst ends and
   garbage is at its peak. No principal on the host has both the authority and a
   schedule: `root` and `gate` have no crontab, `gate` has no usable `sudo`.
4. **The resulting leak is roughly half the disk.** ~50 GB of the 92 GB used on
   `acx-backend` is agent-lane residue, across at least three classes that no
   sweep can see (unmarked sandboxes, `~ubuntu` scratch clones, build cache).

These are four symptoms of one absence. Patching them individually inside
`remote_agent.sh`, `infra/oci/`, and ad-hoc root commands reproduces the same
split ownership that produced them.

## Constraints

- **Two-repo split, and it is not negotiable.** The application belongs upstream
  in `agentic-protocol-monorepo` (it is workbay infrastructure, reusable across
  consumer repos). This repo owns only `infra/oci/` and its own estate policy
  file. Per the Plugin Boundary Rule, the upstream half must be filed as an
  upstream request, not edited from here.
- **The governor must not live inside what it governs** — an instance cannot be
  relied on to stop itself `[CARD-16]`.
- **Reclamation must be evidence-gated.** A lane sandbox is the only copy of the
  work of a lane that died before harvest; 197 of 312 unmarked sandboxes hold
  commits beyond the synthetic base.
- **Credentials are the hard constraint.** An estate agent that can terminate
  instances needs OCI API credentials. `acx-backend` also runs disposable agent
  lanes as `gate`. Terminate authority and lane execution must not share a
  trust boundary `[CARD-10]`.
- **Fail-open on reclamation, fail-closed on creation.** A broken sweep must
  leave garbage, never delete live work; a broken slot ledger must refuse to
  launch, never launch blind `[CARD-07]`.

## Workflow Principles

- **Policy keys off tags, never off names or IDs.** A generic lifecycle module
  containing a specific instance identifier is the `[rg-009]` violation this task
  exists to remove.
- **Config is validated at load time and fails loudly** `[rg-008]`; a missing or
  malformed policy key must not degrade to a permissive default. (The
  `host_memory`-at-top-level silent-fallback bug upstream is the cautionary case.)
- **Every sweep loop bounds its own stalls** `[rg-007]`: per-target no-progress
  counters, one target's failure never halts the others, non-zero exit past the
  threshold.
- **Reclamation is steady-state, not event-driven.** Timer, not hook.
- **Every action is reversible until it isn't, and the irreversible ones are
  gated separately** `[CARD-15]`: stop is routine, terminate is a distinct
  authority, delete-with-commits is never automatic.

## Terminology

- **Estate**: the set of provider resources (instances, boot volumes, images,
  service-limit slots) across all availability domains in one tenancy.
- **Slot**: one unit of a provider service limit in one availability domain. The
  scarce GPU resource. Consumed by RUNNING **and STOPPED** instances alike.
- **Tier**: the lifetime class of a workload — `T0` durable, `T1` working,
  `T2` ephemeral. Determines blast-radius policy, not placement alone.
- **Reclaimer**: a scheduled, idempotent, evidence-gated sweep over one garbage
  class.
- **Actuator**: the component that changes provider state (start/stop/terminate).

## Current State Analysis

**What works.** `infra/oci/gpu_lifecycle/reaper.py` is sound *as a decision
function*: it fail-safes to busy (`_BUSY_LOAD = JobLoadSnapshot(queue_depth=1,
in_flight=1)`), it re-samples load after a fence delay before acting, and
`OciCliStopActuator` cleanly separates decision from actuation. The upstream
`remote_agent.sh` sandbox sweep is marker-gated by design so it can never delete
a directory it did not create.

**What is broken or drifting.**

- The reaper's *deployment* undoes its design: name-pinned target, co-located
  with its subject, and only one instance in `infra/oci/main.tf` carries
  `"scale_to_zero" = "true"` — the tag exists but nothing reads it.
- All 10 `acx-*` containers run with `HostConfig.Memory = 0` and
  `NanoCpus = 0`. Production shares an uncapped kernel with disposable lanes.
- This repo's vendored `scripts/remote_agent.sh` fork writes no
  `.workbay-lane-sandbox` marker, so its sandboxes are permanently invisible to
  the marker-gated sweep, and its `MAX_LANES=3` against upstream's 20 produces
  cap split-brain on a shared scope namespace (`OPS-2`).
- No image retention policy exists, and the obvious one is wrong: `system df`
  advertises 11.19 GB reclaimable where the true figure is ~2.29 GB, ~2.2 GB of
  which sits in three images (`OPS-1`).

**What is currently misleading.** `docker system df`'s reclaimable figure; the
assumption that a stopped GPU instance costs nothing (it costs a slot); and the
E14 diagram that centres a "GPU Inference Server", which the local-AI roadmap
already corrects to "GPU is optional burst capacity, not the product definition".

## Target Outcome

A `workbay-estate` package exposing a CLI and an MCP surface, deployed as a
scheduled supervisor, that:

- maintains a **slot ledger** per availability domain reconciled against the
  provider's real service limits, and refuses a launch that would exceed one;
- **stops and terminates by policy tag** — any instance carrying
  `scale_to_zero=true` and idle past its tier's TTL is acted on, regardless of
  who created it or what it is called;
- runs **timer-driven reclaimers** over named garbage classes (lane sandboxes,
  scratch clones, build cache, image generations, journal) with per-class
  evidence gates and per-class byte accounting in its log;
- reports **cost and slot occupancy** as first-class output, so a burst's true
  price (GPU-hours *and* the slot it held) is visible.

Consumer repos supply an `estate.yaml` describing their tiers and classes; the
application supplies mechanism only.

## Context Loading

- Assessment: `docs/operations/acx-vm-workload-organization-2026-08-04.md`
- Audit: `docs/operations/acx-backend-host-disk-audit-2026-08-04.md`
- Deferred debt this task supersedes: `docs/tech-debt/OPS-1-vm-host-retention-hygiene.md`,
  `docs/tech-debt/OPS-2-vendored-remote-agent-fork.md`
- Existing decision function: `infra/oci/gpu_lifecycle/reaper.py`
- Existing deployment: `infra/oci/cloud-init.yaml`, `infra/oci/main.tf`
- Prior art for the shape (admission governance on one host, upstream):
  `packages/mcp-workbay-orchestrator/src/workbay_orchestrator_mcp/orchestration/host_resources.py`
  (`probe_host`, `load_host_memory_policy`, `evaluate_admission`,
  `acquire_heavy_slot`, `crash_breaker_width_cap`, `record_admission_telemetry`)
  and its CLI `orchestration/hostgov_cli.py`
- Lane sweep semantics: `packages/workbay-system/workbay_system/payload/scripts/remote_agent.sh`
  (`AGENT_ROOT`, `MAX_LANES`, `SANDBOX_TTL_SEC`, the `.workbay-lane-sandbox` marker)

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| `estate.yaml` policy file | workbay-estate (new) | none | new schema, load-time validated | no — greenfield | schema test + malformed-config test asserting a raised error, not a default |
| OCI provider API | workbay-estate (new) | `OciCliStopActuator` in this repo | actuator moves upstream, gains terminate + launch-gate | no — same CLI calls | dry-run against live tenancy, recorded |
| lane sandbox marker | workbay-system `remote_agent.sh` | `.workbay-lane-sandbox` marker file, 48 h TTL | reclaimer becomes a second, timer-driven consumer of the same marker | **yes** — marker semantics must not change | reclaimer dry-run reports the same set the dispatch sweep would |
| `infra/oci/` | this repo | name-pinned reaper in cloud-init | reduced to policy + tags; decision logic leaves | no | `terraform plan` clean; tag present on every managed instance |
| orchestrator host admission | workbay-orchestrator | `host_memory` under `orchestrator:` | none — estate governs machines, orchestrator governs work on a machine | n/a | assert no import from estate into `host_resources.py` |

## Proposed Solution

Split the existing reaper along its already-visible seam. The **decision
function** (idle detection, fence, fail-safe-to-busy) is good and moves upstream
largely intact. What is added around it is everything it lacks: a target
*selector* driven by tags, a slot *ledger* that knows stopped instances still
cost, a *scheduler* that is not the dispatch path, and reclaimers for the
non-instance garbage classes.

Deployment answers "who governs the governor" by **not requiring an always-live
governor**: every action is idempotent and derived from provider state at run
time, so a missed tick costs latency, never correctness. The supervisor runs as
a root-owned systemd timer on the T0 host, under a **separate OCI principal from
the lane-execution account**, with `terminate` authority withheld from the timer
principal entirely — terminate is operator-invoked from the laptop.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| upstream package | `packages/workbay-estate/…/estate/policy.py` | `load_estate_policy(root)`, load-time validation, raise on malformed |
| upstream package | `…/estate/inventory.py` | `probe_estate()` → instances + boot volumes + limits per AD |
| upstream package | `…/estate/slots.py` | `SlotLedger`, `reserve()`, counts STOPPED as consuming |
| upstream package | `…/estate/lifecycle.py` | tag-driven selector + the ported idle/fence decision function |
| upstream package | `…/estate/reclaim/` | one module per garbage class, each with an evidence gate |
| upstream package | `…/estate/cli.py` | `estate inventory|plan|apply|reclaim`, `--dry-run` default |
| upstream package | `…/estate/telemetry.py` | per-class removed count + bytes; slot occupancy; cost |
| this repo | `infra/oci/main.tf` | tag every managed instance with tier + `scale_to_zero` |
| this repo | `infra/oci/cloud-init.yaml` | delete the name-pinned `ExecStart` reaper unit |
| this repo | `infra/oci/gpu_lifecycle/` | retire in favour of the upstream package |
| this repo | `config/estate.yaml` | this estate's tiers, classes, TTLs, retention counts |
| this repo | `docs/workbay/upstream-requests/REQUEST-workbay-estate.md` | the upstream half of this plan |
| this repo | `scripts/remote_agent.sh` | delete (OPS-2 resolution A) so one marker-writing implementation remains |

## Related Files

| File | Note |
| --- | --- |
| `docs/roadmaps/local-ai-managed-default-roadmap-2026-07-31.md` | §4.1 already rejects GPU-as-product-centre; estate must not re-introduce it |
| `docs/tech-debt/OPS-1-vm-host-retention-hygiene.md` | its acceptance criteria become Slice 4's; delete on completion |
| `docs/tech-debt/OPS-2-vendored-remote-agent-fork.md` | its resolution A is a precondition for Slice 4's lane reclaimer |

## Verification Strategy

- Deterministic tests (upstream package):
  - `uv run --extra dev pytest packages/workbay-estate/tests`
  - malformed `estate.yaml` raises, does **not** return an empty default `[rg-008]`
  - a reclaimer whose target errors still processes the remaining targets and
    exits non-zero past the stall threshold `[rg-007]`
  - the slot ledger counts a STOPPED instance as occupying a slot (the N1 regression test)
  - a sandbox fixture holding commits beyond base is **not** selected for deletion
- Runtime-parity:
  - `estate plan` against the live tenancy reproduces the hand-measured AD slot
    table (AD-1 1/1, AD-2 1/1, AD-3 0/1) before any policy change
  - the reclaimer's dry-run set equals the dispatch sweep's set on the same host
- Manual verification:
  - the timer fires twice on `acx-backend` and its log shows per-class bytes both times
  - a deliberately wedged GPU instance is stopped by the off-box supervisor

## Slice Delivery

### Slice 1: Estate inventory and the slot ledger (read-only)

**Goal**: Make capacity visible in the unit that is actually scarce.

Changes:

- `probe_estate()` enumerating instances, lifecycle state, AD, shape, tags,
  boot volumes; `SlotLedger` computing used/available per AD **counting STOPPED**.
- `estate inventory --json`; no actuation in this slice.

Proof:

- Output matches the hand-measured AD table; unit test pins the STOPPED-counts
  rule.

### Slice 2: Policy file with load-time validation

**Goal**: Tiers, TTLs, and retention counts come from validated config, never
from code.

Changes:

- `estate.yaml` schema (tiers, per-tier idle TTL, reclaim classes, retention
  counts); `load_estate_policy()` raising on missing/malformed required keys.
- This repo's `config/estate.yaml` encoding T0/T1/T2 as assessed.

Proof:

- Malformed-config test asserts a raised error; a nested-vs-top-level key
  mistake is rejected loudly rather than silently defaulted.

### Slice 3: Tag-driven lifecycle, off-box

**Goal**: Replace the name-pinned, self-hosted reaper.

Changes:

- Port the idle/fence/fail-safe decision function; add a **tag selector** so any
  `scale_to_zero=true` instance is in scope; `estate apply --dry-run` default.
- Install `oci` CLI + a read/stop-only principal on the T0 host; delete the
  cloud-init unit and the `${GPU_INSTANCE_ID}` pin.

Proof:

- A hand-created, untagged-by-terraform GPU instance is selected once tagged;
  the `[rg-009]` violation is gone from `infra/oci/`.

### Slice 4: Timer-driven reclaimers

**Goal**: Garbage is collected on a schedule, by a principal that has authority.

Changes:

- Reclaimers for lane sandboxes (marker + no-commits-beyond-base gate), scratch
  clones, build cache, images (**count-based on `rollback-*`**, never age-based),
  journal, apt; per-class byte accounting; root-owned daily systemd timer.
- Retire the vendored `remote_agent.sh` fork so one marker-writing implementation
  remains.

Proof:

- Two consecutive firings bound every class; the census of commits-beyond-base
  sandboxes is untouched; ~50 GB reclaimed across the one-time backlog.

### Slice 5: Cost and occupancy telemetry

**Goal**: A burst's true price is visible without an OCI console trip.

Changes:

- Per-run cost estimate (GPU-hours × rate, A1 hours × rate) and slot-occupancy
  duration; emitted with each `apply` and each reclaim.

Proof:

- A completed VLM burst reports GPU-hours, dollars, and the wall-clock time its
  slot was held including while stopped.

---

## Consolidated Checklist

## Context and Ownership

- [ ] Loaded the assessment, the disk audit, OPS-1, OPS-2, and the existing
      `gpu_lifecycle` decision function before editing.
- [ ] Filed the upstream request for the `workbay-estate` package and recorded
      the two-repo ownership split.

### Checklist for Slice 1: Estate inventory and the slot ledger

- [ ] `probe_estate()` enumerates instances, state, AD, shape, tags, boot volumes.
- [ ] `SlotLedger` counts STOPPED instances against the AD limit.
- [ ] `estate inventory --json` output matches the hand-measured AD table.
- [ ] Unit test pins the STOPPED-counts-a-slot rule.

### Checklist for Slice 2: Policy file with load-time validation

- [ ] `estate.yaml` schema defined with tiers, TTLs, reclaim classes, retention counts.
- [ ] `load_estate_policy()` raises on missing/malformed keys; no permissive default.
- [ ] This repo's `config/estate.yaml` encodes T0/T1/T2.
- [ ] Malformed-config test asserts the raise.

### Checklist for Slice 3: Tag-driven lifecycle, off-box

- [ ] Idle/fence/fail-safe-to-busy decision function ported with its tests.
- [ ] Tag selector replaces the instance-ID pin.
- [ ] `oci` CLI and a read/stop-only principal installed on the T0 host.
- [ ] Cloud-init reaper unit and `${GPU_INSTANCE_ID}` deleted from `infra/oci/`.
- [ ] `apply` defaults to dry-run; terminate authority withheld from the timer principal.

### Checklist for Slice 4: Timer-driven reclaimers

- [ ] One reclaimer module per garbage class, each with its evidence gate.
- [ ] Image retention is count-based on `rollback-*` aliases.
- [ ] Per-class removed-count and bytes logged on every run.
- [ ] Bounded stall detection: one class's failure does not halt the others.
- [ ] Root-owned daily systemd timer installed on the T0 host.
- [ ] Vendored `scripts/remote_agent.sh` fork deleted.

### Checklist for Slice 5: Cost and occupancy telemetry

- [ ] Cost estimate emitted per apply and per reclaim.
- [ ] Slot-occupancy duration includes stopped time.

## Review Readiness

- [ ] No provider-mutating path ships without a dry-run mode and a recorded
      live dry-run against the real tenancy.
- [ ] Evidence gates are tested against fixtures that would be destroyed if the
      gate were absent.
- [ ] Handoff decision records the two-repo split and the credential boundary.

## Stretch Goals

- [ ] Boot-volume-to-custom-image capture so T2 persists as an image, not an instance.
- [ ] Slot-aware launch gating wired into the orchestrator's dispatch path.

## Success Criteria

- [ ] No instance in the tenancy is outside the tag-driven policy's scope.
- [ ] `~gate/grok-sandbox` and `~ubuntu` scratch are bounded across two timer firings.
- [ ] `infra/oci/` contains no instance-specific identifier in a generic module.
- [ ] The AD slot table is queryable in one command and is correct for stopped instances.
- [ ] OPS-1 and OPS-2 are deleted, superseded by shipped mechanism.
