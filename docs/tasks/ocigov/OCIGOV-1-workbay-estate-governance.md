# OCIGOV-1. WorkBay Estate — local OCI estate governance

> **Metadata**
>
> - **Date**: 2026-08-04 EST
> - **Author**: Claude Opus 5 (`claude-opus-5`)
> - **Project**: `context-alt-text-monorepo` (`infra/oci/`, local estate policy, host deploy)
> - **Task ID**: `OCIGOV-1`
> - **Target Branch**: `feature/ocigov-1`
> - **Review Coverage Target**: 2
> - **Status**: **DRAFT** — not accepted, not baselined.

---

## Objective

Wire this tenancy to **WorkBay Estate** so machines, slots, and host garbage are governed by tag policy and scheduled reclaimers, not by name-pinned self-stop or dispatch-time hooks. This task ships **only** the consumer-repo half: OCI tags, cloud-init retirement after shadow agreement, `config/estate.yaml`, host timer deploy, credential boundary proofs, OPS-2 fork retirement, and disposition of the stopped A10 occupying AD-1.

## Problem Statement

Six workloads run with **no component that owns the machines**. Measured 2026-08-04 on `acx-backend` — see [`docs/operations/acx-vm-workload-organization-2026-08-04.md`](../../operations/acx-vm-workload-organization-2026-08-04.md) and [`docs/operations/acx-backend-host-disk-audit-2026-08-04.md`](../../operations/acx-backend-host-disk-audit-2026-08-04.md):

1. **Wrong capacity unit.** A STOPPED A10 still consumes that AD's `gpu-a10-count`. Region-wide only two free A10 slots; nothing accounts for them. Stopped ≠ free.
2. **Lifecycle is name-pinned and self-hosted.** `infra/oci/cloud-init.yaml:44` runs the reaper with `--instance-id ${GPU_INSTANCE_ID}` on the instance it should stop. Hand-created instances get no reaper; a wedged OS cannot reap itself; `acx-backend` has no `oci` CLI.
3. **Every reclaimer is dispatch-triggered.** Lane sweep lives inside `remote_agent.sh` at dispatch; it stops when a burst ends and garbage peaks. No principal has both authority and a schedule.
4. **Disk leak is structural.** A large fraction of used space on `acx-backend` is agent-lane residue across classes no dispatch sweep can see (unmarked sandboxes, scratch clones, build cache). Absolute counts go stale within a day `[COST-12]`; the invariant is that **blanket delete is unsafe** because a majority of unmarked sandboxes hold commits beyond the synthetic base `[CARD-11]`.

Patching these inside `remote_agent.sh`, `infra/oci/`, and ad-hoc root commands reproduces the split ownership that created them.

## Constraints

- **Two-repo split, non-negotiable.** Mechanism belongs in `agentic-protocol-monorepo` (`workbay-estate`). This repo may only change paths inside `context-alt-text-monorepo`. Upstream half is filed at [`docs/workbay/upstream-requests/2026-08-04-workbay-estate-governance/README.md`](../../workbay/upstream-requests/2026-08-04-workbay-estate-governance/README.md) — not edited from here (Plugin Boundary Rule).
- **Upstream package is a hard precondition** for every local slice that invokes estate CLI/modules. Until that package exists and is installable on the T0 host, this task ships tags, policy, credential layout, and shadow dry-runs only — no cloud-init deletion, no timer apply.
- **Governor must not live inside what it governs** `[CARD-16]`.
- **Reclamation is evidence-gated.** A lane sandbox may be the only copy of work that died before harvest.
- **Credentials are the hard constraint.** Terminate authority and `gate` lane execution must not share a trust boundary `[CARD-10]`. Timer principal is **stop-only**; terminate is operator-only off-box `[SEC-04]` `[PG-01]`.
- **Two failure axes, not one** `[CARD-07]`:
  - **Destructive action fails open** — never delete/stop under uncertainty.
  - **Process exit fails loud** — non-zero on stall or per-class error after bounded retries `[rg-007]`.
- **Greenfield** — no production users, no migrations, no back-compat shims.

## Workflow Principles

- **Policy keys off tags, never names or IDs in generic modules** `[rg-009]`. Instance names appear only in this plan, operator runbooks, and `config/estate.yaml`.
- **Config validated at load time** `[rg-008]`; missing/malformed required keys raise, never silent defaults.
- **Sweep loops bound stalls** `[rg-007]`: per-target no-progress counters; one target's failure never halts others; non-zero exit past threshold.
- **Reclamation is steady-state** — timer, not dispatch hook `[RES-07]`.
- **Reversible until irreversible** `[CARD-15]`: stop routine; terminate distinct authority; delete-with-commits never automatic.
- **Shadow then cut over** `[AIPX-06]`; **rollback written before ship** `[RLSE-08]`; **kill switch first** `[BOOT-06]`.

## Terminology

| Term | Meaning |
| --- | --- |
| **Estate** | Provider resources (instances, boot volumes, images, service-limit slots) across all ADs in this tenancy. Prefer *estate* over *tenancy* in success criteria and ops language. |
| **Slot** | One unit of a provider service limit in one AD. Scarce GPU resource. Consumed by RUNNING **and STOPPED** instances. |
| **Tier** | Lifetime class — `T0` durable, `T1` working, `T2` ephemeral. Blast-radius policy, not placement alone. |
| **Reclaimer** | Scheduled, idempotent, evidence-gated sweep over one garbage class. |
| **Actuator** | Component that changes provider state (start/stop/terminate). |
| **Supervisor** | The off-box scheduled process (systemd timer + estate CLI) that selects targets by tag and invokes reclaimers/actuators. Not co-located with T2 subjects. |
| **Reaper / sweep** | Legacy names: existing `infra/oci/gpu_lifecycle/reaper.py` decision path and `remote_agent.sh` dispatch-time sandbox cleanup. Both are reclaimer *shapes*; this plan uses **reclaimer** for new work and **reaper** only for the current on-box unit. |

## Current State Analysis

**What works.** `infra/oci/gpu_lifecycle/reaper.py` is sound as a decision function: fail-safe busy (`_BUSY_LOAD = JobLoadSnapshot(queue_depth=1, in_flight=1)`), re-sample after fence delay, `OciCliStopActuator` separates decision from actuation. Upstream `remote_agent.sh` sweep is marker-gated (`.workbay-lane-sandbox`) so it cannot delete directories it did not create.

**What is broken or drifting.**

- Reaper *deployment* undoes design: name-pinned, co-located with subject; `infra/oci/main.tf:270` sets `"scale_to_zero" = "true"` on one instance and **nothing reads that tag**.
- All 10 `acx-*` containers: `HostConfig.Memory = 0`, `NanoCpus = 0`. Production shares an uncapped kernel with disposable lanes.
- Vendored `scripts/remote_agent.sh` (git-excluded, often absent from feature worktrees) writes no marker; `MAX_LANES=3` vs upstream 20 → cap split-brain (OPS-2).
- No image retention policy; `docker system df` reclaimable figure is misleading.

**What is misleading.** Assumption that stopped GPU costs nothing (it costs a slot); E14-style "GPU Inference Server" framing already corrected by the local-AI roadmap.

**Bring-up observation (not a test oracle)** `[CARD-11]`. Hand-measured 2026-08-04: AD-1 used 1 / limit 1 (stopped `acx-gpu-burst`), AD-2 used 1 / available 1, AD-3 used 0 / available 1. Record in handoff; do not assert these ratios in CI.

## Target Outcome

When this local task is done:

- Every managed instance carries tier + `scale_to_zero` tags; generic modules contain no instance ids.
- Estate supervisor runs **off-box** on the T0 host under a **stop-only** OCI principal; credentials unreadable by `gate`.
- On-box name-pinned reaper unit is gone **only after** shadow agreement.
- Timer-driven reclaimers bound lane/disk residue; dispatch-time sweep remains a second consumer of the same marker, not the only one.
- `acx-gpu-burst` is disposed (image + terminate) or kept with explicit slot-cost decision recorded.
- Slot-aware launch gating may still be upstream/stretch; **interim contract** for GPU dispatch is stated below `[REF-13]`.

## Context Loading

- Assessment: `docs/operations/acx-vm-workload-organization-2026-08-04.md`
- Disk audit: `docs/operations/acx-backend-host-disk-audit-2026-08-04.md`
- Superseded debt: `docs/tech-debt/OPS-1-vm-host-retention-hygiene.md`, `docs/tech-debt/OPS-2-vendored-remote-agent-fork.md`
- Decision function: `infra/oci/gpu_lifecycle/reaper.py`
- Deploy surfaces: `infra/oci/cloud-init.yaml`, `infra/oci/main.tf`
- Local policy: `config/estate.yaml` (companion deliverable)
- Upstream request (precondition): `docs/workbay/upstream-requests/2026-08-04-workbay-estate-governance/README.md`
- Prior art (upstream, do not edit): `host_resources.py` / `hostgov_cli.py` — host admission, not machine governance
- Lane marker semantics (upstream): `remote_agent.sh` — `AGENT_ROOT`, `MAX_LANES`, `SANDBOX_TTL_SEC`, `.workbay-lane-sandbox`

## Contract and Boundary Impact

| Boundary | Owner | Current | Expected change | Compat? | Verification |
| --- | --- | --- | --- | --- | --- |
| Upstream `workbay-estate` package | upstream request doc | none | inventory, policy load, tag lifecycle, reclaimers, CLI | **precondition** — not built in this task | package installable; CLI present on T0 before apply/timer slices |
| `config/estate.yaml` | this repo | none | tiers, TTLs, classes, kill switch, retention | greenfield | load-time validation fails loud on malformed keys `[rg-008]` |
| `infra/oci/main.tf` tags | this repo | one instance tagged | every managed instance: tier + `scale_to_zero` | no | `terraform plan` clean; tags present |
| `infra/oci/cloud-init.yaml` reaper unit | this repo | name-pinned on-box reaper | deleted **after** shadow agreement | rollback: restore unit | shadow N-day agreement; then delete |
| OCI principal on T0 | this repo / tenancy IAM | no `oci` CLI | stop+read principal; no terminate | n/a | negative terminate test; `gate` cannot read creds |
| Lane marker | upstream `remote_agent.sh` | marker + dispatch sweep | timer reclaimer is second consumer | **yes** — marker semantics unchanged | dry-run set ⊆ marker-gated set |
| Orchestrator dispatch ↔ slots | temporal coupling `[REF-13]` | no check | **interim:** operator or launch path checks estate inventory before GPU launch; opaque provider error is not acceptable as sole signal `[CARD-07]` `[RES-09]` | document until upstream gate | handoff names checker + operator-visible error |
| `host_resources.py` | upstream orchestrator | host admission | no import from estate into host admission | n/a | assert no such import in this repo |

### Interim slot contract (delivered scope)

Until slot-aware launch gating ships upstream:

1. **Who checks:** operator (or any local launch wrapper this repo owns) runs estate inventory / plan and confirms free `gpu-a10-count` in the target AD **before** requesting a GPU instance.
2. **What the operator sees:** explicit "no free A10 slot in AD-*" from inventory/plan — not a raw provider launch failure after work is already queued.
3. **What still fails closed:** estate refuses apply/launch actions when the slot ledger would exceed limit (upstream package behaviour once present).

## Proposed Solution

Keep the reaper decision function; change **deployment and ownership**.

1. **Precondition.** Land upstream request; install `workbay-estate` on T0 when available. Local work that only needs tags/policy/creds may proceed in parallel; anything that deletes the on-box reaper or runs apply/timer **waits**.
2. **Policy + tags.** `config/estate.yaml` encodes this estate. Terraform tags every managed instance. Kill switch lives in `config/estate.yaml` (companion schema); supervisor checks it before any mutating plan `[BOOT-06]`. **Hard refusal:** never act on tier `T0`, independent of `scale_to_zero` `[CARD-15]`.
3. **Shadow.** Run tag selector **report-only** alongside existing on-box reaper for N days; assert agreement on stop candidates before deleting cloud-init unit `[AIPX-06]`.
4. **Credentials.** Install `oci` CLI + stop/read-only principal on T0. Cred files mode/owner exclude `gate` `[PG-09]` `[SEC-16]`. Terminate only from operator laptop principal `[CARD-04]` `[CARD-12]`.
5. **Cut over.** Enable supervised stop (still dry-run default until explicit apply flag); remove name-pinned unit and `${GPU_INSTANCE_ID}` pin.
6. **Reclaimers.** Root-owned systemd timer; per-class evidence gates; fail-open deletes, fail-loud exits. On non-zero exit: unit `OnFailure=` journal-visible failure + automatic next timer tick (retry by schedule, not tight loop); no silent success `[CARD-07]`.
7. **OPS-2.** Identify dispatch redirect; switch to marker-writing upstream script; then remove laptop-local fork — or fall back to isolate fork under distinct `AGENT_ROOT` and align `MAX_LANES` `[CARD-15]`.
8. **N1 disposition.** Capture `acx-gpu-burst` boot volume as custom image, verify image, then terminate; assert AD-1 used drops per provider limits `[OPS-16]` `[CARD-06]`. Or record deliberate keep + ongoing slot cost.

## Files and Surfaces to Change

Every row is inside `context-alt-text-monorepo`.

| Surface | File | Change |
| --- | --- | --- |
| tags | `infra/oci/main.tf` | tier + `scale_to_zero` on every managed instance; no generic module hardcodes instance ids |
| on-box reaper deploy | `infra/oci/cloud-init.yaml` | after shadow gate: remove name-pinned reaper `ExecStart` / `${GPU_INSTANCE_ID}` |
| retire local decision deploy | `infra/oci/gpu_lifecycle/` | stop shipping as the production governor; decision logic superseded by upstream package (local tree retired or reduced to thin wrapper only if install path requires it — prefer delete once upstream is live) |
| estate policy | `config/estate.yaml` | this estate's tiers, TTLs, classes, retention, kill switch (schema in companion deliverable) |
| upstream request | `docs/workbay/upstream-requests/2026-08-04-workbay-estate-governance/README.md` | precondition artifact; do not implement package here |
| host timer units | operator-installed under `/etc/systemd/system/` on T0 (not git) | root-owned timer invoking estate reclaim/apply; documents unit names in handoff |
| OPS-2 fork | `scripts/remote_agent.sh` | **operator action**, not a reviewable git delete (file is `.git/info/exclude`'d) — see Slice 4 |
| tech-debt close | `docs/tech-debt/OPS-1-vm-host-retention-hygiene.md`, `docs/tech-debt/OPS-2-vendored-remote-agent-fork.md` | delete when acceptance criteria met by shipped mechanism |

## Related Files

| File | Note |
| --- | --- |
| `docs/roadmaps/local-ai-managed-default-roadmap-2026-07-31.md` | §4.1 rejects GPU-as-product-centre; estate must not re-introduce it |
| `docs/tech-debt/OPS-1-vm-host-retention-hygiene.md` | acceptance criteria become reclaimer slice proof |
| `docs/tech-debt/OPS-2-vendored-remote-agent-fork.md` | resolution A preferred; B is reversible fallback |
| `docs/operations/acx-vm-workload-organization-2026-08-04.md` | dated measurements; re-run census at implement time |
| `docs/operations/acx-backend-host-disk-audit-2026-08-04.md` | dated disk classes; not absolute oracles |

## Verification Strategy

**Invariants (CI / automated where package tests live upstream; this repo asserts integration):**

- Inventory per-AD **used** equals provider-reported limit usage for the same resource, whatever current values are `[CARD-11]`.
- Slot ledger counts STOPPED as occupying (regression for N1 rule).
- Malformed `config/estate.yaml` fails load; no empty default `[rg-008]`.
- Kill switch armed → zero mutating actions.
- Tier `T0` never appears in stop/terminate candidate set.
- Reclaimer: destructive path skips on uncertainty; process exits non-zero if any class stalls past threshold; other classes still processed `[rg-007]`.
- Sandbox with commits beyond base is not selected for delete.

**Credential proofs (local, mandatory):**

- Timer principal: stop allowed; **terminate call rejected** (negative test).
- Credential file(s) on T0: not readable by `gate` (filesystem permission assertion as `gate`).
- No terminate capability installed for the timer principal on the box.

**Shadow gate:**

- For N consecutive days (default N=3 unless operator sets higher), report-only selector and existing reaper agree on the set of stop candidates (same instance ocids). Disagreement blocks cloud-init deletion `[AIPX-06]`.

**Bring-up (handoff only, not oracle):**

- Record first inventory snapshot vs hand-measured 2026-08-04 table for human orientation.
- Re-run sandbox census at implement time; do not paste stale absolute counts into success criteria `[COST-12]`.

**Manual:**

- Two timer firings log per-class removed count + bytes.
- Deliberately idle tagged T2 is stopped by off-box supervisor while on-box unit is already gone (post-cutover).

## Slices

### Precondition: Upstream package available

**Gate.** `docs/workbay/upstream-requests/2026-08-04-workbay-estate-governance/README.md` accepted path exists; `workbay-estate` installable on T0 with CLI (`inventory`, `plan`, `apply`, `reclaim`).

**Interim without package.** Land tags + `config/estate.yaml` + IAM principal layout only. Do not delete cloud-init reaper. Do not install apply timer.

### Slice 1: Tags, policy, kill switch

**Goal.** This estate is described in validated config; every managed instance is selectable by tag.

**Changes.**

- `infra/oci/main.tf`: tier + `scale_to_zero` on all managed instances.
- `config/estate.yaml`: tiers/TTLs/classes/retention/kill switch per companion schema.
- Document hard rule: supervisor never mutates `T0`.

**Proof.**

- `terraform plan` shows tag changes only as intended.
- Loading policy with kill switch on yields plan with empty action set.
- No instance-specific id in generic Python modules under `infra/oci/`.

### Slice 2: Credentials and least privilege

**Goal.** Enforce the credential boundary the constraints assert `[SEC-04]` `[CARD-10]`.

**Changes.**

- Install `oci` CLI on T0.
- Create/stop-only dynamic group + IAM policy for timer principal: allow read instance/family and stop instance; **no** terminate/launch-delete.
- Store credentials outside paths `gate` can read; ownership/mode exclude uid 1002.

**Proof.**

- As timer principal: stop on a disposable T2 test target succeeds (or dry-run equivalent accepted by operator).
- As timer principal: terminate is **rejected** by IAM.
- As `gate`: cannot read credential files.
- Terminate remains operator-laptop-only.

### Slice 3: Shadow supervisor (report-only)

**Goal.** Prove tag selector before removing the on-box reaper `[AIPX-06]` `[RLSE-08]`.

**Changes.**

- Install report-only timer/service on T0: estate plan against tags; log candidates; **no stop**.
- Leave `infra/oci/cloud-init.yaml` reaper unit in place.
- Kill switch must force empty candidate set when armed.

**Agreement criterion.** N=3 consecutive daily runs where report-only candidate set equals the set the existing reaper would stop (same ocids), or documented empty-empty agreement if none idle.

**Rollback.** Disable shadow timer; on-box reaper unchanged.

### Slice 4: Cut over lifecycle + reclaimers + OPS-2

**Goal.** Off-box stop; scheduled reclaim; single marker-writing lane path.

**Depends on.** Precondition package; Slice 2 proofs; Slice 3 agreement.

**Changes.**

- Enable supervised stop path (apply still defaults dry-run; explicit flag for mutate).
- Delete name-pinned reaper unit and `${GPU_INSTANCE_ID}` from `infra/oci/cloud-init.yaml`.
- Root-owned daily reclaim timer; per-class gates (marker + no-commits-beyond-base for lanes; count-based `rollback-*` for images; scratch; build cache; journal; apt as policy lists).
- OPS-2: identify dispatch → script resolution; redirect to upstream marker-writing `remote_agent.sh`; **then** remove laptop-local `scripts/remote_agent.sh`. If redirect unknown, stop and resolve Open Question before delete. Fallback B: distinct `AGENT_ROOT` + aligned `MAX_LANES` without deleting fork `[CARD-15]`.
- Re-run sandbox census at start of slice (dated note in handoff).

**Failure posture.**

| Axis | Behaviour |
| --- | --- |
| Uncertain delete/stop | skip target; leave resource |
| Class error / stall past threshold | continue other classes; process exit non-zero |
| systemd on non-zero | failure recorded in journal; next tick retries by schedule; no auto-disable of kill switch |

**Proof.**

- Cloud-init no longer passes instance id to reaper.
- Two reclaim firings bound classes without touching commits-beyond-base census.
- Dispatch produces sandbox containing `.workbay-lane-sandbox` after redirect.
- Rollback note: restore cloud-init reaper unit from git; stop apply timer; keep kill switch armed `[RLSE-08]`.

### Slice 5: Dispose stopped A10 occupying AD-1

**Goal.** Use the instrument on the instance that motivated N1 `[OPS-16]`.

**Changes (operator-driven; name only in plan/config, not generic modules)** `[rg-009]`.

1. Capture `acx-gpu-burst` boot volume → custom image.
2. Verify image bootable / inspectable `[CARD-06]`.
3. Terminate instance (operator principal).
4. Confirm provider AD-1 `gpu-a10-count` used decreased (inventory matches provider).

**Alternative.** Operator records **keep** decision with ongoing slot cost (1 of 1 in AD-1) in handoff; success criteria then require that record, not free slot.

### Slice 6: Cost / occupancy telemetry (local consumption)

**Goal.** Burst true price visible from estate CLI output once upstream emits it.

**Changes.** This repo documents operator runbook fields only (GPU-hours, A1-hours, slot-hold including stopped). No new package code here.

**Proof.** One completed VLM burst (or dry-run sample) shows slot-hold duration including stopped time in handoff.

---

## Consolidated Checklist

### Context and Ownership

- [ ] Load assessment, disk audit, OPS-1, OPS-2, and `infra/oci/gpu_lifecycle/reaper.py` before edits.
- [ ] Confirm upstream request path `docs/workbay/upstream-requests/2026-08-04-workbay-estate-governance/README.md` is the sole channel for package work.
- [ ] Confirm companion `config/estate.yaml` schema deliverable is present or coordinated.
- [ ] Record two-repo split and credential boundary in handoff.

### Checklist for Precondition: Upstream package

- [ ] Upstream request documents inventory, slot ledger (STOPPED counts), policy load, tag lifecycle, reclaimers, CLI.
- [ ] `workbay-estate` installable on T0; `estate inventory` / `estate plan` invoke successfully.
- [ ] Until install succeeds: block Slice 4 mutate/cutover and Slice 5 terminate automation; allow Slice 1 tags/policy and Slice 2 IAM layout.

### Checklist for Slice 1: Tags, policy, kill switch

- [ ] `infra/oci/main.tf`: every managed instance has tier and `scale_to_zero` tags.
- [ ] `config/estate.yaml` committed with kill switch key per companion schema; load fails on malformed required keys.
- [ ] Supervisor path checks kill switch before mutate; armed → empty actions.
- [ ] Hard refusal: no stop/terminate candidate with tier `T0`.
- [ ] `terraform plan` reviewed; no instance id hardcoded into generic modules under `infra/oci/`.

### Checklist for Slice 2: Credentials

- [ ] `oci` CLI installed on `acx-backend` (T0).
- [ ] Timer principal IAM: read + stop allowed; terminate denied (negative test recorded).
- [ ] Credential files not readable by `gate` (permission test as uid 1002).
- [ ] Terminate not available to timer principal on the box; operator-laptop principal documented for terminate.
- [ ] Lane execution account `gate` unchanged: no sudo, no docker, no estate creds.

### Checklist for Slice 3: Shadow

- [ ] Report-only supervisor timer installed; on-box reaper in `infra/oci/cloud-init.yaml` still present.
- [ ] N=3 days candidate-set agreement logged (or empty-empty).
- [ ] Kill switch test during shadow: armed run emits zero candidates.
- [ ] Rollback path documented: disable shadow timer only.

### Checklist for Slice 4: Cut over, reclaim, OPS-2

- [ ] Slice 3 agreement satisfied before editing `infra/oci/cloud-init.yaml`.
- [ ] Name-pinned reaper unit and `${GPU_INSTANCE_ID}` removed from `infra/oci/cloud-init.yaml`.
- [ ] Apply defaults dry-run; mutate requires explicit flag.
- [ ] Reclaim timer root-owned; per-class evidence gates; per-class count+bytes logged.
- [ ] Stall policy: per-class no-progress counters; one class failure does not halt others; non-zero exit; systemd journal shows failure; next tick retries.
- [ ] Identify dispatch→script resolution mechanism (Open Question if unknown); redirect **before** any fork removal.
- [ ] After redirect: one dispatch creates sandbox with `.workbay-lane-sandbox`.
- [ ] Remove laptop-local `scripts/remote_agent.sh` only after redirect proof — or implement OPS-2 fallback B (`AGENT_ROOT` isolation + `MAX_LANES` align).
- [ ] Re-run sandbox census; record dated counts in handoff only.
- [ ] Rollback: restore cloud-init reaper from git; stop apply timer; arm kill switch.

### Checklist for Slice 5: `acx-gpu-burst` disposition

- [ ] Custom image from boot volume captured and verified before terminate.
- [ ] Terminate via operator principal (not timer).
- [ ] Provider + inventory agree AD-1 usage dropped — **or** handoff records keep + slot cost (1 AD-1 slot).
- [ ] Instance name used only in plan/handoff/config, not generic modules.

### Checklist for Slice 6: Telemetry consumption

- [ ] Runbook lists fields: GPU-hours, host-hours, slot-hold including stopped.
- [ ] One sample burst/handoff line shows slot-hold including stopped time.

### Review Readiness

- [ ] No provider-mutating path without dry-run and a recorded live dry-run.
- [ ] Evidence gates tested against fixtures that would be destroyed if gates were absent.
- [ ] Negative IAM terminate test and `gate` credential-read denial attached to handoff.
- [ ] Shadow agreement log attached before cloud-init deletion review.
- [ ] Interim GPU slot check contract named (who checks, operator-visible error).
- [ ] Handoff states two-repo split, kill switch location in `config/estate.yaml`, and rollback steps.

### Success Criteria

- [ ] No managed instance outside tag-driven policy scope.
- [ ] Off-box supervisor is the production stop path; on-box name-pinned reaper gone post-shadow.
- [ ] `infra/oci/` generic modules contain no instance-specific identifiers.
- [ ] Estate inventory per-AD used matches provider limit usage (invariant, not the 2026-08-04 ratios).
- [ ] Lane/scratch residue bounded across two timer firings without deleting commits-beyond-base sandboxes.
- [ ] Timer principal cannot terminate; `gate` cannot read estate credentials.
- [ ] `acx-gpu-burst` disposed with free AD-1 slot, or keep decision with slot cost recorded.
- [ ] OPS-1 and OPS-2 debt docs deleted only when their acceptance criteria are met by shipped mechanism.

## Stretch Goals

- [ ] Boot-volume→custom-image automation for T2 as routine path (Slice 5 remains manual until then).
- [ ] Slot-aware launch gating in orchestrator dispatch (replaces interim operator contract) — upstream request follow-on.
- [ ] Host cgroup caps for `acx-*` containers (N3); out of estate ownership but residual risk.

## Open Questions

- What exact env var, make target, or compose path resolves which `remote_agent.sh` dispatch uses on `acx-backend`? Must be identified before OPS-2 fork removal; do not invent a name.
- Exact OCI IAM policy statement identifiers / dynamic-group names for the stop-only principal (create in tenancy; record in handoff — not invented here).
- Shadow window N: default 3 days acceptable, or operator requires longer given burst cadence?
- Preferred `acx-gpu-burst` path: terminate after image, or keep with permanent AD-1 slot cost?
- Systemd unit names and install path conventions on `acx-backend` (new vs existing ops patterns).
- Whether local tree `infra/oci/gpu_lifecycle/` is deleted outright post-cutover or kept as a thin deprecated shim until upstream pin is mandatory in all images.
