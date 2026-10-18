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

**Build** (not migrate) this repo's half of WorkBay Estate so machines, slots, and host garbage are governed by tag policy and scheduled reclaimers. No lifecycle actuator runs anywhere today; there is nothing to cut over from. This task ships: OCI tags on managed and hand-created instances, `config/estate.yaml` wiring, dead-template cleanup of the never-deployed reaper block, host timer deploy of a new tag-selecting supervisor, credential boundary proofs, host-copy OPS-2 fix under `~gate` on `acx-backend`, and disposition of stopped A10s — **`acx-gpu-smoke` first**, then `acx-gpu-burst` as an operator call.

## Problem Statement

Six workloads run with **no component that owns the machines**. Measured 2026-08-04 on `acx-backend` — see [`docs/operations/acx-vm-workload-organization-2026-08-04.md`](../../operations/acx-vm-workload-organization-2026-08-04.md) and [`docs/operations/acx-backend-host-disk-audit-2026-08-04.md`](../../operations/acx-backend-host-disk-audit-2026-08-04.md):

1. **Wrong capacity unit.** A STOPPED A10 still consumes that AD's `gpu-a10-count`. Region-wide only two free A10 slots; nothing accounts for them. Stopped ≠ free. Only terminate frees a slot; stop does not.
2. **Lifecycle was designed and never deployed.** `infra/oci/cloud-init.yaml` (attached to `acx_backend` at `main.tf:226`) contains a reaper unit block that has **never taken effect** on the running host: no `oci` CLI, no timer, no unit files, no `/etc/acx`. The design's real defects (not "wedged OS cannot reap itself") are: (a) **OCID-pinned** — `cloud-init.yaml:44` passes `--instance-id ${GPU_INSTANCE_ID}`, `reaper.py` requires that argument, and cloud-init writes only a `.env.example`, so it covers at most one instance; (b) host has **no `oci` CLI**, so `OciCliStopActuator` could never actuate; (c) `main.tf:270` carries `"scale_to_zero" = "true"` and **nothing reads that tag**. Hand-created instances (notably `acx-gpu-smoke`) are outside terraform and untagged.
3. **Every reclaimer is dispatch-triggered.** Lane cleanup lives inside host `remote_agent.sh` at dispatch; it stops when a burst ends and garbage peaks. No principal has both authority and a schedule. No account has a crontab. `gate` has no sudo and no docker.
4. **Disk leak is structural.** A large fraction of used space on `acx-backend` is agent-lane residue across classes no dispatch path can see (unmarked sandboxes under the host fork, scratch clones, build cache). Absolute counts go stale within a day `[COST-12]`; the invariant is that **blanket delete is unsafe** because a majority of unmarked sandboxes hold commits beyond the synthetic base `[CARD-11]`.

There is **nothing to migrate**. The plan builds a tag-selecting supervisor, bootstraps the CLI it needs, and cleans a dead template. Patching only inside `remote_agent.sh` or ad-hoc root commands reproduces the split ownership that created the gaps.

## Constraints

- **Two-repo split, non-negotiable.** Mechanism belongs in `agentic-protocol-monorepo` (`workbay-estate`). This repo may only change paths inside `context-alt-text-monorepo`. Upstream half is filed at [`docs/workbay/upstream-requests/2026-08-04-workbay-estate-governance/README.md`](../../workbay/upstream-requests/2026-08-04-workbay-estate-governance/README.md) — not edited from here (Plugin Boundary Rule).
- **Upstream package is a hard precondition** for every local slice that invokes estate CLI/modules. Until that package exists and is installable on the T0 host (`acx-backend`), this task ships tags, policy, and credential layout only — no timer apply, no reclaim mutate, no instance terminate automation.
- **Governor must not be co-located with any instance it may stop or terminate** `[CARD-16]`. T0 is structurally excluded from its own candidate set (IAM tag condition + code-level defence in depth). The supervisor runs as a scheduled process on `acx-backend` (T0); it must never select T0. What happens if `acx-backend` is wedged is an Open Question — this design does not claim independent hosting.
- **Reclamation is evidence-gated.** A lane sandbox may be the only copy of work that died before harvest.
- **Credentials are the hard constraint.** Terminate authority and `gate` lane execution must not share a trust boundary `[CARD-10]`. Timer principal is **stop-only**; terminate is operator-only off-box `[SEC-04]` `[PG-01]`.
- **Two failure axes, not one** `[CARD-07]` (see Terminology):
  - **Destructive axis:** *refuse-to-act under uncertainty*.
  - **Exit-status axis:** *fail loud* — non-zero on stall or per-class error after bounded retries; one class failing must not halt the others `[rg-007]`.
- **Greenfield** — no production users, no migrations, no back-compat shims. Build, do not migrate.
- **Slot pressure raises an operator blocker.** `slots.free_trigger` must not name an automated action that frees a slot. Stop does not free a slot; terminate is forbidden to the scheduled principal.
- **Emergency stop** is exactly: **set `control.mutations: disabled`**.

## Workflow Principles

- **Policy keys off tags, never names or IDs in generic modules** `[rg-009]`. Instance names appear only in this plan, operator runbooks, and `config/estate.yaml`.
- **Config validated at load time** `[rg-008]`: file absent, malformed, missing any required key, unknown key, or duplicate overrides → refuse to start, exit non-zero, mutate nothing. No silent defaults for required keys.
- **Reclaimer loops bound stalls** `[rg-007]`: per-class no-progress counters; one class's failure never halts others; non-zero exit past threshold.
- **Reclamation is steady-state** — timer, not dispatch hook `[RES-07]`.
- **Reversible until irreversible** `[CARD-15]`: stop routine; terminate distinct authority; delete-with-commits never automatic.
- **Report-only then live** `[AIPX-06]` via `control.observation.mode`; **rollback written before ship and rehearsed once inside the slice** `[RLSE-08]`; mutation gate first via `control.mutations: disabled` `[BOOT-06]`.

## Terminology

| Term | Meaning |
| --- | --- |
| **Estate** | The set of machines under governance. Use this word, never "tenancy", in success criteria and ops language. |
| **Slot** | One unit of a per-availability-domain service limit. A stopped instance still holds its slot. |
| **Tier** | A governance class (T0 never touched, T1…, T2 disposable) carried as an instance tag. |
| **Supervisor** | The scheduled process that plans and actuates. Holds the reservation lease. Installed as systemd timer + estate CLI on the T0 host; selects targets by tag, never by hardcoded instance id. |
| **Reclaimer** | The component that frees disk by class. Scheduled, idempotent, evidence-gated. |
| **Actuator** | The thin layer that performs one provider call. Separate from the decision function. |
| **Reaper-sweep** | Reserved for the *legacy* dispatch-triggered paths only (`remote_agent.sh` dispatch cleanup, never-deployed `infra/oci/gpu_lifecycle/reaper.py`). Never use "sweep" for new work — use *reclaimer*. |
| **Refuse-to-act under uncertainty** | Destructive axis: if the system cannot prove a resource is idle, unreferenced, and in scope, it does not touch it. |
| **Fail loud** | Exit-status axis: a failed pass exits non-zero; systemd marks the unit failed; the timer keeps its schedule; the next pass re-evaluates from scratch. One class failing must not halt the others. |

## Current State Analysis

**What exists as code but is not live.** `infra/oci/gpu_lifecycle/reaper.py` is a sound decision function: busy-load default when probes fail, re-sample after fence delay, `OciCliStopActuator` separates decision from actuation. It has **never been deployed**. Verified 2026-08-04 on `acx-backend`: `which oci` absent; no `acx-gpu` timer; no gpu/reaper unit files; `/etc/acx` does not exist; `acx-gpu-idle-reaper.timer` not-found. The cloud-init reaper block is a **dead template** with no runtime effect on any booted host.

**Attachment topology (already off-box design, never actuated).** `infra/oci/main.tf:226` attaches `cloud-init.yaml` to `acx_backend`. `infra/oci/main.tf:263` attaches `gpu-cloud-init.yaml` to `acx_gpu_burst`. The reaper was never co-located with its GPU subject; the design defects are the OCID pin, absent CLI, and unread `scale_to_zero` tag.

**What is broken or drifting.**

- No tag-selecting supervisor exists. Nothing reads `scale_to_zero`. Hand-created `acx-gpu-smoke` is not terraform-managed and is untagged; a "managed-only" tag pass leaves it permanently outside policy.
- All 10 `acx-*` containers: `HostConfig.Memory = 0`, `NanoCpus = 0`. Production shares an uncapped kernel with disposable lanes.
- Repo-root `scripts/remote_agent.sh` (mtime 2026-08-02) **already** writes `.workbay-lane-sandbox` (4 occurrences) and sets `MAX_LANES="${_env_max_lanes:-20}"`. The marker-less `MAX_LANES=3` fork OPS-2 describes lived under `~gate` **on acx-backend** and produced the 8.8 GB unmarked residue. Work targets the **host copy**, not a laptop-local vendored path.
- No image retention policy; `docker system df` reclaimable figure is misleading. Dual-tag builds (40-hex SHA + `rollback-<image-id>`) mean dropping only `rollback-*` frees zero bytes.
- Two committed tests pin the never-deployed tree: `scripts/test_vlm3_gpu_lifecycle.py` imports `infra.oci.gpu_lifecycle.controller` and `.reaper`; `scripts/test_vlm3_decision_memo.py` asserts the literal string `python -m infra.oci.gpu_lifecycle` in a committed memo.

**What is misleading.** Assumption that stopped GPU costs nothing (it costs a slot); E14-style "GPU Inference Server" framing already corrected by the local-AI roadmap.

**Bring-up observation (not a test oracle)** `[CARD-11]`. Hand-measured 2026-08-04: AD-1 used 1 / limit 1 (stopped `acx-gpu-burst`), AD-2 used 1 / limit 1 (stopped `acx-gpu-smoke`), AD-3 used 0 / limit 1. **Two free A10 slots region-wide.** Record in handoff; do not assert these ratios in CI. Assessment ranks terminating `acx-gpu-smoke` #1 (400 GB billed boot volume + AD-2 slot, low risk); `acx-gpu-burst` disposition is ranked 7th and is an operator call.

## Target Outcome

When this local task is done:

- Every instance in the estate inventory — terraform-managed **and** explicitly enumerated hand-created — carries tier + `scale_to_zero` tags; inventory count equals managed count + hand-created set; generic modules contain no instance ids.
- Estate supervisor runs on the T0 host under a **stop-only** OCI principal whose IAM policy excludes tier T0 at the provider; credentials unreadable by `gate`.
- Report-only observation period completed against a **hand audit** of the full instance list with a **non-empty** candidate set observed at least once; then live stop path enabled under `control.mutations: enabled` + per-class `enabled:` + `control.observation.mode: live`.
- Dead-template reaper block removed from `infra/oci/cloud-init.yaml` (no runtime decommission — it was never live).
- Timer-driven reclaimers bound lane/disk residue for the nine canonical classes (staged enable); dispatch-time reaper-sweep remains a second consumer of the same marker where the host path still uses it, not the only cleaner.
- `acx-gpu-smoke` disposed (image + restore rehearsal + terminate) freeing AD-2 slot, or keep decision with slot cost recorded. `acx-gpu-burst` disposed or keep decision recorded (operator call, after smoke).
- Slot-aware launch gating may still be upstream/stretch; **interim contract** for GPU dispatch is stated below `[REF-13]`.

## Context Loading

- Assessment: `docs/operations/acx-vm-workload-organization-2026-08-04.md`
- Disk audit: `docs/operations/acx-backend-host-disk-audit-2026-08-04.md`
- Superseded debt: `docs/tech-debt/OPS-1-vm-host-retention-hygiene.md`, `docs/tech-debt/OPS-2-vendored-remote-agent-fork.md`
- Decision function (never deployed): `infra/oci/gpu_lifecycle/reaper.py`
- Deploy surfaces: `infra/oci/cloud-init.yaml`, `infra/oci/main.tf`
- Local policy (pre-landed companion artifact on branch): `config/estate.yaml`
- Tests pinning retired tree: `scripts/test_vlm3_gpu_lifecycle.py`, `scripts/test_vlm3_decision_memo.py`
- Upstream request (precondition, out of bounds to implement here): `docs/workbay/upstream-requests/2026-08-04-workbay-estate-governance/README.md`
- Prior art (upstream, do not edit): `packages/mcp-workbay-orchestrator/.../orchestration/host_resources.py` — exports `probe_host`, `load_host_memory_policy`, `evaluate_admission`, `acquire_heavy_slot`, `acquire_backend_local_slot`, `count_held_heavy_slots`, `crash_breaker_width_cap`, `record_admission_telemetry`; governs admission of *work onto one host*, not machines
- Lane marker semantics (repo root, current upstream script): `scripts/remote_agent.sh` — `AGENT_ROOT`, `MAX_LANES`, `.workbay-lane-sandbox`
- Host OPS-2 target: fork under `~gate` on `acx-backend` (not the repo-root path)

## Contract and Boundary Impact

| Boundary | Owner | Current | Expected change | Compat? | Verification |
| --- | --- | --- | --- | --- | --- |
| Upstream `workbay-estate` package | upstream request doc (out of bounds) | none | inventory, policy load, tag lifecycle, reclaimers, CLI | **precondition** — not built in this task | package installable; CLI present on T0 before apply/timer/observation slices that shell out to it |
| `config/estate.yaml` | this repo | **pre-landed** on branch (companion artifact) | required keys present; loader wired in Slice 1/package install; no silent defaults | greenfield | load-time validation fails loud on absent/malformed/unknown keys `[rg-008]` |
| `infra/oci/main.tf` tags | this repo | one instance tagged `scale_to_zero` | every managed instance: tier + `scale_to_zero`; hand-created tagged out of band | no | `terraform -chdir=infra/oci plan`; full-instance census vs inventory |
| `infra/oci/cloud-init.yaml` reaper block | this repo | dead template (never live) | delete as dead-template cleanup after report-only hand audit passes | **no runtime effect** on booted hosts; rollback is no-op on host | template absent from file; host still has no reaper unit (unchanged) |
| `infra/oci/gpu_lifecycle/` | this repo | never-deployed decision tree | retire when upstream package live; migrate or remove pinning tests in same change | greenfield | tests that import the tree updated or removed; memo string updated |
| OCI principal on T0 | this repo / estate IAM | no `oci` CLI | stop+read principal; IAM tag condition excludes T0; no terminate | n/a | negative terminate asserts specific auth error; positive control in same run; `gate` cannot read creds |
| Host lane script under `~gate` | operator on `acx-backend` | marker-less residue source | redirect dispatch to marker-writing path **or** fallback B | yes if marker semantics hold | one dispatch: marker present under intended `AGENT_ROOT`; no unmarked sibling created |
| Host timer units | operator-installed under `/etc/systemd/system/` on T0 (not git) | none | root-owned timer invoking estate reclaim/apply | n/a | unit active; journal shows per-class lines; rollback rehearsed once |
| Orchestrator dispatch ↔ slots | temporal coupling `[REF-13]` | no checker exists | **interim gap accepted** — see contract below | document until upstream gate | handoff records gap + operator procedure |
| `host_resources.py` | upstream orchestrator | host admission | no import from estate into host admission | n/a | `rg` asserts no such import in this repo |

### Interim slot contract (delivered scope)

Until slot-aware launch gating ships upstream:

1. **No automated checker exists in this repo today.** There is no component, function, or command in `context-alt-text-monorepo` that refuses a GPU launch for slot exhaustion. This is an **accepted interim gap**, not a shipped gate.
2. **Operator procedure that substitutes:** before requesting a GPU instance, operator runs (once package is installed) `estate inventory` (exact CLI name from upstream package) and refuses launch unless free `gpu-a10-count` in the target AD is ≥ 1. Until the package exists, operator runs the provider limit query and records free-slot count in the launch ticket.
3. **Operator-visible refusal string (manual):** `REFUSED: no free A10 slot in AD-<n> (stopped instances still hold slots)`. This string is not emitted by automation in this task; the operator pastes it into the ticket when refusing.
4. **Slot pressure under policy:** when free slots ≤ `slots.free_trigger`, the supervisor raises an **operator blocker** only. It does **not** terminate, does not free a slot, and does not launch. Stop never frees a slot.

## Proposed Solution

Build a tag-selecting supervisor. The never-deployed decision function is historical context only; production behaviour comes from the upstream package once installed.

1. **Precondition.** Land upstream request; install `workbay-estate` on T0 when available. Local work that only needs tags/policy/creds may proceed in parallel; anything that shells out to the estate CLI or mutates provider/host reclaim state **waits**.
2. **Policy + tags.** `config/estate.yaml` is pre-landed; remaining work is tags plus loader wiring. All nine reclaim classes defined with per-class `enabled:`. Canonical control keys: `control.mutations`, `control.observation.*`. **Structural T0 refusal:** stop principal's IAM policy bound to a tag condition that excludes tier T0 at the provider; code-level check is defence in depth only `[CARD-15]` `[SEC-04]`.
3. **Report-only observation.** Run tag selector with `control.observation.mode: report_only` for `control.observation.max_duration_days` from `started_on`. Judge against a **hand audit** of the selector's output over the full instance list: non-empty candidate set observed at least once; each instance decision matches the auditor `[AIPX-06]` `[CARD-11]`. No agreement with a non-existent reaper.
4. **Credentials.** Install `oci` CLI + stop/read-only principal on T0. Cred files mode/owner exclude `gate` `[PG-09]` `[SEC-16]`. Terminate only from operator principal `[CARD-04]` `[CARD-12]`. Auth proofs use existing `acx-gpu-burst` OCID **without actuating**, or a non-A10 throwaway that consumes no scarce slot (teardown checklist item if used).
5. **Live supervisor + dead-template cleanup.** Set observation to `live` only after hand audit. Apply defaults dry-run; mutate requires explicit flag **and** `control.mutations: enabled` **and** per-class `enabled:`. Delete never-live reaper block from `infra/oci/cloud-init.yaml` (template cleanup; no host unit to stop).
6. **Reclaimers.** Root-owned systemd timer; per-class evidence gates; refuse-to-act under uncertainty; fail loud exits. On non-zero exit: journal-visible failure + next timer tick re-evaluates from scratch; one class failing does not halt others `[rg-007]` `[CARD-07]`.
7. **OPS-2 on host.** Identify dispatch → which `remote_agent.sh` the host uses under `~gate` / operator path. Redirect **before** any fork removal so one dispatch creates a sandbox under the intended `AGENT_ROOT` **with** `.workbay-lane-sandbox` **and** no unmarked sibling in the same dispatch. Fallback B: isolate fork under distinct `AGENT_ROOT` and align `MAX_LANES` `[CARD-15]`. Repo-root script is already marker-writing; do not treat it as the leak source.
8. **Disposition order.** (1) `acx-gpu-smoke` — capture, wait AVAILABLE, record image OCID durably, restore rehearsal on cheap non-A10 shape, then terminate; resume skips re-image if verified OCID exists `[RES-19]` `[FLOW-05]`. (2) `acx-gpu-burst` — same procedure as operator call, or keep with slot cost recorded `[OPS-16]` `[CARD-06]`.

## Files and Surfaces to Change

Rows under **this monorepo** are in-bounds. Rows under **operator / host** or **upstream request** are not monorepo code changes; they are listed so implementers do not invent anchors.

| Scope | Surface | File / target | Change |
| --- | --- | --- | --- |
| monorepo | tags | `infra/oci/main.tf` | tier + `scale_to_zero` on every managed instance; no generic module hardcodes instance ids |
| monorepo | dead template | `infra/oci/cloud-init.yaml` | after report-only hand audit: remove never-live reaper unit block and `${GPU_INSTANCE_ID}` pin |
| monorepo | retire local tree | `infra/oci/gpu_lifecycle/` | stop shipping as production governor once upstream package is live; delete preferred (greenfield) |
| monorepo | pinning tests | `scripts/test_vlm3_gpu_lifecycle.py` | imports `infra.oci.gpu_lifecycle.controller` and `.reaper` — migrate or remove in same change as tree retirement |
| monorepo | pinning tests | `scripts/test_vlm3_decision_memo.py` | asserts literal `python -m infra.oci.gpu_lifecycle` — update or remove memo string in same change |
| monorepo | estate policy | `config/estate.yaml` | **pre-landed companion artifact**; remaining: keep required keys complete, no silent defaults; loader wiring is package + install path (Slice 1 records which command loads it) |
| monorepo | tech-debt close | `docs/tech-debt/OPS-1-vm-host-retention-hygiene.md`, `docs/tech-debt/OPS-2-vendored-remote-agent-fork.md` | delete only when acceptance criteria met by shipped mechanism (or criterion narrowed and deferred items listed) |
| out of bounds | upstream request | `docs/workbay/upstream-requests/2026-08-04-workbay-estate-governance/README.md` | precondition artifact only; package work does not happen in this task |
| operator / host | timer units | `/etc/systemd/system/` on `acx-backend` (not git) | root-owned timer invoking estate reclaim/apply; unit names recorded in handoff |
| operator / host | OPS-2 fork | host copy under `~gate` on `acx-backend` | redirect or fallback B; not the repo-root marker-writing script |
| operator / host | hand-created tags | `acx-gpu-smoke` (and any other non-terraform instance) | tag out of band so estate inventory includes them |
| operator / host | dispositions | `acx-gpu-smoke`, then `acx-gpu-burst` | image + restore rehearsal + terminate via operator principal; durable image OCID for resume |

## Related Files

| File | Note |
| --- | --- |
| `docs/roadmaps/local-ai-managed-default-roadmap-2026-07-31.md` | §4.1 rejects GPU-as-product-centre; estate must not re-introduce it |
| `docs/tech-debt/OPS-1-vm-host-retention-hygiene.md` | dual-tag builds; `protected_tags`; `keep_count` 5; acceptance criteria become reclaimer proof or explicit deferrals |
| `docs/tech-debt/OPS-2-vendored-remote-agent-fork.md` | describes pre-2026-08-02 fork; residual is host `~gate` copy; resolution A preferred; B is reversible fallback |
| `docs/operations/acx-vm-workload-organization-2026-08-04.md` | dated measurements and disposition ranking; re-run census at implement time |
| `docs/operations/acx-backend-host-disk-audit-2026-08-04.md` | dated disk classes; not absolute oracles |
| `infra/oci/gpu_lifecycle/reaper.py` | never-deployed decision function; historical |
| `scripts/test_vlm3_gpu_lifecycle.py` | pins module path; must change with tree |
| `scripts/test_vlm3_decision_memo.py` | pins memo string; must change with tree |
| `scripts/remote_agent.sh` | repo root: already marker-writing, `MAX_LANES` default 20 — not the leak source |

## Verification Strategy

Per `docs/workbay/templates/TASK_PLAN.template.md`. Commands below must run as written once their slice preconditions hold `[rg-006]`. Nothing in this repo currently loads `config/estate.yaml`; **Slice 1** wires load through the upstream package CLI (or a proposed-new local loader test if the package is not yet installed — package path preferred).

### Deterministic tests

```bash
# Policy load: absent file refuses start (exit non-zero). Wired in Slice 1 via package CLI once installed.
estate policy-check --config /nonexistent/estate.yaml ; test $? -ne 0

# Policy load: missing required key refuses start.
estate policy-check --config /tmp/estate-missing-key.yaml ; test $? -ne 0

# Policy load: unknown key refuses start.
estate policy-check --config /tmp/estate-unknown-key.yaml ; test $? -ne 0

# control.mutations: disabled → plan emits zero mutating actions.
estate plan --config config/estate.yaml  # with control.mutations: disabled in fixture
# expected: action count == 0

# Tag selector selects by tag alone (no instance id supplied) — must fail today before Slice 1+package.
estate plan --config config/estate.yaml --select-by-tag-only
# expected: acx-gpu-burst OCID appears when tagged; newly tagged fixture instance appears without code change

# Pinning tests: after gpu_lifecycle retirement, suite must not import retired path.
python -m pytest scripts/test_vlm3_gpu_lifecycle.py scripts/test_vlm3_decision_memo.py -q
```

### Runtime parity

```bash
# Inventory used matches provider limit usage (invariant; not 2026-08-04 ratios).
estate inventory
oci limits resource-availability get --service-name compute --limit-name gpu-a10-count \
  --compartment-id "$COMPARTMENT_OCID" --availability-domain "$AD"
# expected: per-AD used from inventory == provider used

# Slot ledger counts STOPPED as occupying.
estate inventory --format json | python3 -c "import sys,json; d=json.load(sys.stdin); assert all(i['holds_slot'] for i in d['instances'] if i['lifecycle_state'] in ('STOPPED','STOPPING'))"

# Report-only: mutations never issued.
# control.observation.mode: report_only; run plan/apply path; assert zero provider stop calls in audit log.
```

### Contract verification

```bash
# Terraform tags only as intended.
terraform -chdir=infra/oci plan -no-color
# expected: tag changes on managed instances; no destroy of T0

# Positive control + negative terminate (timer principal; no scarce-slot launch).
#
# NEVER issue a live `instance terminate` against a production instance as an
# IAM proof. If the tag condition is wrong the call SUCCEEDS and destroys the
# GPU. The authority is proved by reading the policy, not by attempting the
# destructive verb (CARD-06, CARD-15).

# Positive control — read is permitted. $T2_OCID is any T2-tier instance.
oci compute instance get --instance-id "$T2_OCID" --auth api_key \
  --config-file /etc/acx/estate/oci-timer-principal.cfg
# expected: HTTP 200 / instance JSON

# Negative proof, read-only: no policy statement reachable by the timer
# principal's group grants a terminate verb, and the group holds no
# manage-instance-family statement.
oci iam policy list --compartment-id "$ESTATE_COMPARTMENT_OCID" --all \
  --query 'data[].statements[]' --raw-output \
  | grep -iE "group +estate-timer-principal" > /tmp/term-neg.txt
! grep -qiE "manage +instance-family|INSTANCE_TERMINATE|instance_terminate" /tmp/term-neg.txt
# expected: exit 0 — no terminate authority in any statement bound to the principal.
# This assertion goes red the moment a broadening policy edit lands, and it
# destroys nothing when it does.

# Live-call confirmation is permitted ONLY against a purpose-created,
# disposable T2 instance whose loss is acceptable, never against an instance
# carrying production or burst workload, and only after the read-only proof
# above passes:
#   oci compute instance terminate --instance-id "$THROWAWAY_OCID" --auth api_key \
#     --config-file /etc/acx/estate/oci-timer-principal.cfg --force 2>&1 \
#     | tee /tmp/term-live.txt ; test ${PIPESTATUS[0]} -ne 0
# expected stderr: an authorization denial naming the terminate verb
#   (NotAuthorizedOrNotFound, or the provider's own authorization-denial text).
# must NOT be "command not found", a bare connection error, or empty stderr.
# `--force` is required or the CLI prompts and the step hangs non-interactively.

# gate cannot read estate credentials.
sudo -u gate test ! -r /etc/acx/estate/oci-timer-principal.cfg ; echo gate_denied:$?
# expected: gate_denied:0

# OPS-2 host redirect proof (paths recorded in handoff; do not invent AGENT_ROOT).
# One dispatch under intended AGENT_ROOT creates sandbox WITH marker; no unmarked sibling created.
test -f "$SANDBOX/.workbay-lane-sandbox"
test -z "$(find "$AGENT_ROOT" -mindepth 1 -maxdepth 1 -type d ! -exec test -e '{}/.workbay-lane-sandbox' \; -print)"
```

**Invariants (asserted by the commands above and package tests upstream):**

- Inventory per-AD **used** equals provider-reported limit usage for the same resource `[CARD-11]`.
- Slot ledger counts STOPPED as occupying.
- Malformed / absent / unknown-key `config/estate.yaml` fails load; no empty default `[rg-008]`.
- `control.mutations: disabled` → zero mutating actions.
- Tier `T0` never appears in stop/terminate candidate set (IAM structural + code defence in depth).
- Reclaimer: refuse-to-act under uncertainty; process exits non-zero if any class stalls past threshold; other classes still processed `[rg-007]`.
- Sandbox with commits beyond base is not selected for delete.
- `slots.free_trigger` surfaces operator blocker only; never an automated slot-freeing action.

**Report-only gate (not agreement with a non-existent reaper):**

- Hand audit over the full instance list for `control.observation.max_duration_days` (committed value 7 in `config/estate.yaml`; the operator may raise it, never silently): each selector decision matches auditor; **non-empty** candidate set observed at least once. Vacuous empty-empty does not pass `[AIPX-06]` `[CARD-11]`.

**Bring-up (handoff only, not oracle):**

- Record first inventory snapshot vs hand-measured 2026-08-04 table for human orientation.
- Re-run sandbox census at implement time; do not paste stale absolute counts into success criteria `[COST-12]`.

## Slices

### Precondition: Upstream package available

**Gate.** `docs/workbay/upstream-requests/2026-08-04-workbay-estate-governance/README.md` accepted path exists; `workbay-estate` installable on T0 with CLI (`inventory`, `plan`, `apply`, `reclaim`, `policy-check`).

**Blocked until install succeeds.** Slice 3 (shells out to estate CLI), Slice 4 mutate/reclaim/apply, automated terminate paths. Slice 5/5b operator dispose may use raw `oci` once CLI is installed (Slice 2) without full package, but inventory agreement checks need the package.

**Allowed without package.** Slice 1 tags + policy file completeness review; Slice 2 IAM principal layout and `oci` CLI install.

### Slice 1: Tags, policy, mutation gate

**Goal.** This estate is described in validated config; every managed instance is selectable by tag; hand-created instances are enumerated and tagged out of band.

**Depends on.** None for terraform tags and policy file review. Loader/`estate policy-check` commands depend on Precondition package.

**Changes.**

- `infra/oci/main.tf`: tier + `scale_to_zero` on all managed instances.
- Out-of-band tags on every hand-created instance (at minimum `acx-gpu-smoke`).
- `config/estate.yaml`: **already on branch** — remaining work is confirming required keys (`control.mutations`, `control.observation.mode`, `control.observation.max_duration_days`, `control.observation.started_on`, `inventory.max_items`, `slots.reservation_lease_ttl_seconds`, `slots.free_floor`, `slots.free_trigger`, `slots.launch_min_free`, `untagged_instance_posture`, `never_automate`, `tiers.*`, all nine `reclaim.classes.*`) and wiring load through package CLI once installed. No silent defaults `[rg-008]` `[PROV-08]`.
- Document structural T0 refusal (IAM) + code defence in depth.

**Proof.**

- `terraform -chdir=infra/oci plan -no-color` shows only intended tag changes.
- Full instance list (provider) counted; hand-created set enumerated in handoff; `estate inventory` count equals terraform-managed count + hand-created set (after package install).
- Loading policy with `control.mutations: disabled` yields plan with empty action set.
- Tag selector selects `acx-gpu-burst` by tag alone with no instance id supplied, and selects a newly tagged instance without a code change (fails today; must pass after tags + package).
- Emergency stop instruction in handoff is exactly: set `control.mutations: disabled`.

### Slice 2: Credentials and least privilege

**Goal.** Enforce the credential boundary the constraints assert `[SEC-04]` `[CARD-10]`. Bootstrap the CLI the supervisor needs.

**Depends on.** None for install/IAM. Auth command proofs require CLI present and principal created.

**Changes.**

- Install `oci` CLI on `acx-backend` (T0).
- Create stop-only dynamic group + IAM policy for timer principal: allow read instance/family and stop instance; **no** terminate; **tag condition excludes tier T0 at the provider** (structural refusal). Exact policy statement identifiers recorded in handoff (not invented here).
- Store credentials outside paths `gate` can read; ownership/mode exclude uid of `gate`.
- Code-level T0 refusal is defence in depth only.

**Proof.**

- Same run, timer principal against live `acx-gpu-burst` OCID **without stop or terminate actuation**:
  - Positive control: `oci compute instance get --instance-id $GPU_BURST_OCID ...` succeeds (HTTP 200).
  - Negative: `oci compute instance terminate --instance-id $GPU_BURST_OCID ...` fails with authorization error naming terminate (see Verification Strategy); not CLI-missing or network-only failure `[CARD-11]`.
- If a throwaway is preferred over dry auth checks: launch a **non-A10** cheap shape only, record OCID, run stop positive + terminate negative, then terminate the throwaway via **operator** principal; teardown is a checklist item. Do not consume a scarce A10 slot for proof `[SEC-04]`.
- `sudo -u gate test ! -r <cred-file>` exits 0.
- Terminate remains operator-principal-only.

**Rollback (host actions; rehearse once).** Remove timer-principal config file; `rm` installed API key material under the estate path; leave system `oci` package installed or remove via package manager if this slice added it — record which. Rehearsal: remove cred file, confirm timer unit (if any) cannot authenticate, restore cred file from operator secret store (not git).

### Slice 3: Report-only observation

**Goal.** Prove tag selector against a hand audit before any live mutate or dead-template cleanup `[AIPX-06]` `[CARD-11]`.

**Depends on.** Precondition package; Slice 1 tags complete (otherwise selector yields vacuous empty set); Slice 2 CLI + credentials for inventory reads.

**Changes.**

- Install report-only timer/service on T0: estate plan against tags; log candidates; **no stop**. Set `control.observation.mode: report_only`, write `control.observation.started_on` (ISO date) when observation begins, set `control.observation.max_duration_days` (committed value 7).
- Leave `infra/oci/cloud-init.yaml` as-is (dead template; no live unit to preserve).
- With `control.mutations: disabled`, plan emits zero mutating actions even if observation later flips.

**Hand-audit criterion.** For `max_duration_days` consecutive daily runs, auditor compares selector output to full instance list: every decision matches; **at least one run has a non-empty candidate set**. Empty-empty does not pass.

**Rollback (host actions; rehearse once).** `systemctl disable --now <report-only-unit>`; remove unit files from `/etc/systemd/system/`; `systemctl daemon-reload`. Cloud-init reaper rollback is a **no-op** (never live).

### Slice 4: Live supervisor, reclaimers, OPS-2 host path, dead-template cleanup

**Goal.** Tag-selecting stop path live under explicit flags; scheduled reclaim; single marker-writing lane path on host; remove dead reaper template.

**Depends on.** Precondition package; Slice 2 proofs; Slice 3 hand-audit criterion satisfied.

**Changes.**

- Enable supervised stop path: apply still defaults dry-run; mutate requires explicit flag **and** `control.mutations: enabled` **and** `control.observation.mode: live` **and** per-class/action `enabled:`.
- Delete never-live reaper unit block and `${GPU_INSTANCE_ID}` from `infra/oci/cloud-init.yaml` (dead-template cleanup; no host unit to stop).
- Root-owned daily reclaim timer. Canonical nine classes — enable staged:

  | Class | Slice 4 enable | Notes |
  | --- | --- | --- |
  | `marker_lane_sandboxes` | enabled | evidence: marker present; no commits-beyond-base |
  | `unmarked_lane_sandboxes` | enabled | evidence gates strict; refuse-to-act under uncertainty |
  | `scratch_clones` | enabled | per policy params |
  | `docker_build_cache` | enabled | per policy params |
  | `container_images` | enabled | drop companion 40-hex SHA **and** `rollback-*`; `protected_tags: [dev, latest, staging]`; skip images referenced by running containers; `keep_count: 5` (OPS-1) or inline comment justifying deviation |
  | `journal` | deferred | leave `enabled: false` until operator signs residual risk |
  | `apt_cache` | deferred | leave `enabled: false` |
  | `uv_cache` | deferred | leave `enabled: false` |
  | `grok_logs` | deferred | leave `enabled: false` |

  OPS-1 debt doc closes only for criteria covered by enabled classes (`container_images` dual-tag drop, protected tags, keep_count, running-ref skip, plus lane/scratch/build-cache bounds). Deferred classes remain open debt until enabled — do not delete OPS-1 until those are met or the criterion is explicitly narrowed in handoff.
- OPS-2: identify dispatch → script resolution on `acx-backend` (Open Question if unknown); redirect **before** any host-fork removal. Proof: one dispatch creates sandbox under intended `AGENT_ROOT` **with** `.workbay-lane-sandbox` **and** no unmarked sibling created in that dispatch. Fallback B: distinct `AGENT_ROOT` + aligned `MAX_LANES` without deleting fork `[CARD-15]`. Repo-root `scripts/remote_agent.sh` is not the residue source.
- If retiring `infra/oci/gpu_lifecycle/`: same change updates `scripts/test_vlm3_gpu_lifecycle.py` and `scripts/test_vlm3_decision_memo.py` (and memo string).
- Re-run sandbox census at start of slice (dated note in handoff only).

**Failure posture.**

| Axis | Behaviour |
| --- | --- |
| Uncertain delete/stop | refuse-to-act under uncertainty; leave resource |
| Class error / stall past threshold | continue other classes; process exit non-zero (fail loud) |
| systemd on non-zero | failure recorded in journal; next tick retries by schedule; does not flip `control.mutations` |

**Proof.**

- `grep -E 'GPU_INSTANCE_ID|gpu-lifecycle|reaper' infra/oci/cloud-init.yaml` exits 1 (template gone).
- Host: `systemctl list-units --all | grep -i reaper` still empty (was never live).
- Two reclaim firings log per-class count+bytes for each **enabled** class; commits-beyond-base sandboxes untouched.
- OPS-2 dispatch proof as in Verification Strategy.
- Rollback **rehearsed once inside this slice** `[RLSE-08]`:
  1. Set `control.mutations: disabled` (emergency stop).
  2. `systemctl disable --now <apply-unit> <reclaim-unit>`; remove unit files; `daemon-reload`.
  3. Cloud-init reaper restore from git is **template-only** and does **not** restore a running actuator (no-op on host). Say so in handoff.
  4. Re-enable units only after rehearsal observation recorded.

### Slice 5: Dispose stopped A10s — smoke first, then burst

**Goal.** Free scarce slots in assessment risk order `[OPS-16]`. Names appear only in plan/handoff/config, not generic modules `[rg-009]`.

**Depends on.** Slice 2 (`oci` CLI + operator principal). Package inventory agreement preferred for post-terminate used-count check.

#### 5a — `acx-gpu-smoke` (rank #1; hand-created; not terraform-managed)

1. Capture boot volume → custom image (record capture command and work request id in handoff).
2. Wait until image lifecycle state is `AVAILABLE`; record **image OCID durably** in handoff file before any terminate `[FLOW-05]`.
3. **Restore rehearsal** `[CARD-06]` `[CARD-15]`: launch from that image into a **cheap non-A10** shape; confirm boot (SSH or cloud-init complete); terminate the rehearsal instance via operator principal.
4. **Resume rule** `[RES-19]` `[API-02]`: if re-run finds existing verified image OCID for this target in handoff, skip capture; go to terminate.
5. Terminate `acx-gpu-smoke` via **operator principal** (not timer).
6. Provider + inventory: AD-2 `gpu-a10-count` used decreased — **or** handoff records keep + slot cost (1 AD-2 slot).

#### 5b — `acx-gpu-burst` (rank #7; operator call)

Same procedure as 5a (capture → AVAILABLE → durable OCID → restore rehearsal → terminate), targeting AD-1. **Alternative:** operator records **keep** with ongoing slot cost (1 of 1 in AD-1) in handoff; success criteria then require that record, not free slot.

**Do not** use an A10 throwaway for credential proofs (Slice 2).

### Slice 6: Cost / occupancy telemetry (local consumption)

**Goal.** Burst true price visible from estate CLI output once upstream emits it.

**Depends on.** Precondition package for field emission; runbook text can land earlier.

**Changes.** This repo documents operator runbook fields only (GPU-hours, host-hours, slot-hold including stopped). No new package code here.

**Proof.** One completed VLM burst (or dry-run sample line from `estate` output) shows slot-hold duration including stopped time in handoff; line quoted.

---

## Consolidated Checklist

### Context and Ownership

- [ ] Open assessment, disk audit, OPS-1, OPS-2, and `infra/oci/gpu_lifecycle/reaper.py`; handoff lists each path with mtime or commit.
- [ ] `test -f docs/workbay/upstream-requests/2026-08-04-workbay-estate-governance/README.md` exits 0; handoff states this is the sole package channel.
- [ ] `test -f config/estate.yaml` exits 0; handoff notes it is pre-landed; remaining work is tags + loader wiring.
- [ ] Handoff states two-repo split, emergency stop as set `control.mutations: disabled`, and credential boundary.

### Checklist for Precondition: Upstream package

- [ ] Upstream request documents inventory, slot ledger (STOPPED counts), policy load, tag lifecycle, reclaimers, CLI.
- [ ] On T0: `estate inventory` and `estate plan` invoke successfully (exit 0).
- [ ] Until install succeeds: Slice 3, Slice 4 mutate/cutover, and automated terminate remain blocked; Slice 1 tags/policy and Slice 2 IAM layout allowed.

### Checklist for Slice 1: Tags, policy, mutation gate

- [ ] `terraform -chdir=infra/oci plan -no-color` shows tier + `scale_to_zero` on every managed instance; no unexpected destroys.
- [ ] Provider instance list enumerated; hand-created set (at least `acx-gpu-smoke`) tagged out of band; after package install, `estate inventory` count equals managed count + hand-created set.
- [ ] `config/estate.yaml` contains every required key from the binding contract; `estate policy-check` (or equivalent) exits non-zero on malformed, missing-key, unknown-key, and absent-file fixtures.
- [ ] Plan with `control.mutations: disabled` emits empty action set (action count 0 in plan output).
- [ ] Tag selector selects `acx-gpu-burst` by tag alone with no instance id on the command line; newly tagged instance appears without code change.
- [ ] T0 OCID absent from stop/terminate candidate set in plan output.
- [ ] Handoff emergency stop line is exactly: set `control.mutations: disabled`.

### Checklist for Slice 2: Credentials

- [ ] `which oci` on `acx-backend` prints a path.
- [ ] Same run: timer principal `instance get` on `acx-gpu-burst` OCID succeeds; `instance terminate` on same OCID fails with authorization error naming terminate (log attached); neither failure mode is CLI-missing.
- [ ] If non-A10 throwaway used instead: OCID recorded, stop positive + terminate negative run, throwaway terminated by operator principal, provider shows throwaway gone.
- [ ] `sudo -u gate test ! -r <estate-cred-file>` exits 0.
- [ ] IAM policy text in handoff includes tag condition excluding tier T0; timer principal has no terminate verb.
- [ ] Rollback rehearsed once: cred file removed, auth fails, cred file restored from operator secret store.

### Checklist for Slice 3: Report-only observation

- [ ] Depends-on satisfied: package installed; Slice 1 tags complete; Slice 2 CLI present.
- [ ] Report-only unit installed; `control.observation.mode: report_only`; `started_on` ISO date recorded; `max_duration_days` set.
- [ ] Hand-audit log attached: full instance list per run; every decision matches auditor; **at least one non-empty candidate set**.
- [ ] Run with `control.mutations: disabled` emits zero mutating actions.
- [ ] Rollback rehearsed once: `systemctl disable --now` report-only unit; unit files removed; host still has no live reaper (no-op cloud-init path).

### Checklist for Slice 4: Live supervisor, reclaim, OPS-2, dead template

- [ ] Slice 3 hand-audit criterion satisfied before editing `infra/oci/cloud-init.yaml` or enabling live apply.
- [ ] `grep -E 'GPU_INSTANCE_ID|acx-gpu-idle-reaper' infra/oci/cloud-init.yaml` exits 1.
- [ ] Apply defaults dry-run; mutate requires explicit flag; `control.mutations: enabled` necessary but not sufficient without per-class `enabled:` and `observation.mode: live`.
- [ ] Reclaim timer root-owned; enabled classes are exactly: `marker_lane_sandboxes`, `unmarked_lane_sandboxes`, `scratch_clones`, `docker_build_cache`, `container_images`; deferred remain `enabled: false`: `journal`, `apt_cache`, `uv_cache`, `grok_logs`.
- [ ] `container_images` params include `protected_tags: [dev, latest, staging]`, `keep_count: 5` (or justifying comment), dual-tag drop (SHA + rollback), skip running-container refs.
- [ ] Two firings: journal shows per-class count+bytes for each enabled class; fail-injected class does not halt others; process exit non-zero; next tick still scheduled `[rg-007]`.
- [ ] Dispatch→script resolution named in handoff (or Open Question still open — then no fork removal).
- [ ] One dispatch: sandbox under intended `AGENT_ROOT` has `.workbay-lane-sandbox`; no unmarked sibling directory created in that dispatch.
- [ ] Host-fork removal only after redirect proof — or fallback B recorded (`AGENT_ROOT` isolation + `MAX_LANES` align).
- [ ] Sandbox census re-run; dated counts in handoff only (not success criteria).
- [ ] If `infra/oci/gpu_lifecycle/` removed: `scripts/test_vlm3_gpu_lifecycle.py` and `scripts/test_vlm3_decision_memo.py` updated or removed in same change; memo string no longer requires `python -m infra.oci.gpu_lifecycle`.
- [ ] Rollback rehearsed once: set `control.mutations: disabled`; disable --now apply+reclaim units; remove unit files; handoff states cloud-init reaper restore is host no-op.

### Checklist for Slice 5a: `acx-gpu-smoke` disposition

- [ ] Image capture command and work-request id in handoff; image state `AVAILABLE`; **image OCID recorded before terminate**.
- [ ] Restore rehearsal: launch from image on non-A10 shape, boot confirmed, rehearsal instance terminated.
- [ ] Re-run with existing verified OCID skips capture (resume path exercised or dry-logged).
- [ ] Terminate via operator principal (not timer).
- [ ] Provider + inventory agree AD-2 usage dropped — **or** handoff records keep + slot cost (1 AD-2 slot).
- [ ] Instance name used only in plan/handoff/config, not generic modules.

### Checklist for Slice 5b: `acx-gpu-burst` disposition

- [ ] Same capture → AVAILABLE → durable OCID → restore rehearsal → terminate sequence, **or** keep decision with AD-1 slot cost in handoff.
- [ ] Terminate via operator principal only.
- [ ] Provider + inventory agree AD-1 usage dropped if terminated.
- [ ] Instance name used only in plan/handoff/config, not generic modules.

### Checklist for Slice 6: Telemetry consumption

- [ ] Runbook lists fields: GPU-hours, host-hours, slot-hold including stopped.
- [ ] One sample burst/handoff line quotes slot-hold including stopped time.

### Review Readiness

- [ ] No provider-mutating path without dry-run default and a recorded live dry-run log.
- [ ] Evidence-gate tests use fixtures that would be destroyed if gates were absent (exit non-zero or skip logged when gate holds).
- [ ] Negative IAM terminate log (specific auth error) and positive control from same run attached; `gate` credential-read denial attached.
- [ ] Hand-audit log attached before cloud-init template deletion review.
- [ ] Interim slot gap stated: no automated checker in this repo; operator procedure and refusal string recorded.
- [ ] Handoff states two-repo split, emergency stop as set `control.mutations: disabled` in `config/estate.yaml`, and host-level rollback steps actually rehearsed.

### Success Criteria

- [ ] Every instance in estate inventory (managed + enumerated hand-created) is inside tag-driven policy scope; inventory count equals managed + hand-created set.
- [ ] Tag-selecting supervisor on T0 is the production stop path under `control.mutations` + observation mode; dead-template reaper block removed from cloud-init; no claim of cutover from a live actuator.
- [ ] Tag selector selects by tag alone with no instance id supplied; generic modules under `infra/oci/` gain no instance-specific identifiers `[rg-009]`.
- [ ] Estate inventory per-AD used matches provider limit usage (invariant, not the 2026-08-04 ratios).
- [ ] Enabled reclaim classes bound residue across two timer firings without deleting commits-beyond-base sandboxes; deferred classes remain explicitly `enabled: false`.
- [ ] Timer principal cannot terminate (auth error naming terminate); `gate` cannot read estate credentials.
- [ ] `acx-gpu-smoke` disposed with free AD-2 slot, or keep decision with slot cost recorded.
- [ ] `acx-gpu-burst` disposed with free AD-1 slot, or keep decision with slot cost recorded.
- [ ] OPS-1 deleted only when dual-tag image reclaim + enabled class criteria are met, with deferred classes listed if criterion narrowed; OPS-2 deleted only when host dispatch proof (marker + no unmarked sibling) is met by shipped mechanism.
- [ ] `slots.free_trigger` raises operator blocker only; no automated slot-freeing action exists for the scheduled principal.

## Stretch Goals

- [ ] Boot-volume→custom-image automation for T2 as routine path (Slice 5 remains manual until then).
- [ ] Slot-aware launch gating in orchestrator dispatch (replaces interim operator procedure) — upstream request follow-on.
- [ ] Host cgroup caps for `acx-*` containers (N3); out of estate ownership but residual risk.
- [ ] Enable deferred reclaim classes (`journal`, `apt_cache`, `uv_cache`, `grok_logs`) after residual-risk sign-off.

## Open Questions

- What exact env var, make target, or compose path resolves which `remote_agent.sh` dispatch uses on `acx-backend` under `~gate`? Must be identified before host-fork removal; do not invent a name.
- Exact OCI IAM policy statement identifiers / dynamic-group names for the stop-only principal (create in estate; record in handoff — not invented here), including the tag condition that excludes T0.
- Report-only window: is the committed `max_duration_days: 7` right, or does burst cadence require longer?
- Preferred `acx-gpu-burst` path: terminate after image + restore rehearsal, or keep with permanent AD-1 slot cost?
- Systemd unit names and install path conventions on `acx-backend` (new vs existing ops patterns).
- Whether local tree `infra/oci/gpu_lifecycle/` is deleted outright once upstream is live, or kept briefly until pinning tests and memo string are migrated — either way, `scripts/test_vlm3_gpu_lifecycle.py` and `scripts/test_vlm3_decision_memo.py` must move in the same change.
- If `acx-backend` (T0, supervisor host) is wedged, what is the second-exit path for stop/reclaim? Design excludes T0 from the candidate set but does not provide an independent supervisor host `[CARD-16]`.
