# Upstream request: workbay-estate — a third application for machine governance

**Requested by:** context-alt-text-monorepo · **Date:** 2026-08-04
**Status:** proposed
**Blocks:** OCIGOV-1 (this repo's estate-governance task) slices that consume
the package.

## Summary

Add a third workbay application, **estate**, sibling to handoff (task state) and
orchestrator (work dispatch). Estate owns **machines**: provider inventory,
capacity-slot accounting, tag-driven instance lifecycle, and scheduled
reclamation. It cannot live in handoff or orchestrator — those govern task state
and work-on-a-host; nothing today owns the set of hosts or provider slots.
Shipping this package unblocks consumer-repo wiring (policy file, tags, timer
deployment) that cannot be written against an absent surface.

This is a **build** request, not a migrate request. No lifecycle actuator is
running on any host. The package is greenfield mechanism; consumer repos will
supply policy and deployment afterward.

## Motivation

Measured 2026-08-04 on estate host `acx-backend` (observations, not invariants).
Volatile census figures belong in the consumer's implementation-time re-run;
the request states the structural gaps.

| ID | Observation |
| --- | --- |
| N1 | A STOPPED GPU instance still consumes its AD's `gpu-a10-count`. Region-wide, only two free A10 slots were available at measurement. The scarce unit is slots, not dollars. Nothing in workbay accounts for that unit. Stop does not free a slot; only terminate does. |
| N2 | **No lifecycle actuator is deployed anywhere.** Verified 2026-08-04 on `acx-backend`: no `oci` CLI, no `acx-gpu*` systemd timer or unit, no `/etc/acx`. The design that exists in-repo was never deployed and could not have worked if it had been: (1) OCID-pinned — consumer `infra/oci/cloud-init.yaml` (existing) passes `--instance-id ${GPU_INSTANCE_ID}` and `infra/oci/gpu_lifecycle/reaper.py` (existing) makes that argument required, so coverage is at most one instance and aborts without one; (2) the host has no `oci` CLI, so `OciCliStopActuator` could never actuate; (3) `infra/oci/main.tf` (existing) carries `scale_to_zero=true` on a GPU instance and nothing reads that tag. Hand-created instances (e.g. `acx-gpu-smoke`) are invisible to any selector. There is nothing to dual-run against and nothing to decommission. |
| N3 | All 10 `acx-*` containers run uncapped (`HostConfig.Memory = 0`, `NanoCpus = 0`). Production shares an uncapped kernel with disposable lanes. |
| N4 | Disk pressure on `acx-backend` is agent-lane residue under a principal that cannot reclaim it. The cited audit records **99 G used / 94 G free**, with **12 GB** in `~gate/grok-sandbox` (of which **8.8 GB is unmarked** and invisible to every existing reaper-sweep) plus **6.1 GB** of scratch clones. Every reclaimer is dispatch-triggered inside consumer `scripts/remote_agent.sh` (existing; current upstream, writes `.workbay-lane-sandbox`, `MAX_LANES` default 20), so collection stops when garbage peaks. No account has a crontab. The lane account has no sudo and no docker. **Invariant:** no principal holds both the authority to reclaim and a schedule to do it on. `[COST-12]` `[CARD-11]` |

These are symptoms of one missing owner. Patching them inside consumer scripts
reproduces split ownership. The package belongs upstream so any consumer repo
can supply policy without reimplementing mechanism.

**Terminology.**

| Term | Meaning |
| --- | --- |
| **Estate** | the set of machines under governance. Use this word, never "tenancy", in success criteria and ops language. |
| **Slot** | one unit of a per-availability-domain service limit. A stopped instance still holds its slot. |
| **Tier** | a governance class (T0 never touched, T1…, T2 disposable) carried as an instance tag. |
| **Supervisor** | the scheduled process that plans and actuates. Holds the reservation lease. |
| **Reclaimer** | the component that frees disk by class. |
| **Actuator** | the thin layer that performs one provider call. Separate from the decision function. |
| **Reaper-sweep** | reserved for the *legacy* dispatch-triggered paths only. Never use "sweep" for new work — use *reclaimer*. |
| **Reservation** | Time-bounded claim on a slot held across provider launch latency. |

## Why a third application, not a feature of orchestrator

Upstream `host_resources.py` (existing;
`packages/mcp-workbay-orchestrator/.../orchestration/host_resources.py`, out
of bounds to edit from this consumer) already governs **admission of work onto
one host**: `probe_host`, `load_host_memory_policy`, `evaluate_admission`,
`acquire_heavy_slot`, `acquire_backend_local_slot`, `count_held_heavy_slots`,
`crash_breaker_width_cap`, `record_admission_telemetry`. That surface answers
"may this job run here?" It does not answer "what machines exist, which slots
do they hold, and may we create another?"

| Concern | Owner today | Coupling type `[REF-13]` |
| --- | --- | --- |
| Work → one host | orchestrator / `host_resources.py` (existing) | affinity (work needs host resources) |
| Host set, slots, lifecycle | **none** | — |
| Task state | handoff | temporal (workflow sequence) |

Folding machine governance into orchestrator would couple two independent
failure domains and two cognitive ownership boundaries `[TEAM-05]`. A wedged
dispatch path must not disable slot accounting; a broken inventory probe must
not block work admission on a healthy host. Estate is therefore a peer
application, not a module of either existing one.

## Proposed surface

Shape mirrors hostgov: **probe → policy → decision → actuation → telemetry**.

| Module (proposed) | Responsibility | Key symbols (proposed unless noted) |
| --- | --- | --- |
| `estate/inventory.py` (proposed) | Enumerate provider resources; paginated, bounded by `inventory.max_items` | `probe_estate()` (proposed) → instances + boot volumes + limits per AD; `truncated` flag |
| `estate/slots.py` (proposed) | Slot ledger; STOPPED counts as occupied; concurrent reserve; uncertain state | `SlotLedger` (proposed), `reserve()` (proposed), `release()` (proposed), `reconcile()` (proposed) |
| `estate/policy.py` (proposed) | Load and structurally validate consumer policy; all C-3 keys required | `load_estate_policy(root)` (proposed) — raises on absent, malformed, missing required key, unknown key, or duplicate override |
| `estate/lifecycle.py` (proposed) | Tag-driven selector + idle/fence decision (port decision shape from consumer `infra/oci/gpu_lifecycle/reaper.py` (existing)) | selector on tags only (no instance name/id) `[rg-009]`; refuse-to-act under uncertainty when load is missing, same semantics as existing `_BUSY_LOAD` in that reaper |
| `estate/reclaim/` (proposed) | One reclaimer module per garbage class; evidence-gated; timer-driven | class modules; shared stall-bound runner `[rg-007]` |
| `estate/cli.py` (proposed) | Operator / supervisor surface | `estate inventory \| plan \| apply \| reclaim`; mutating subcommands default dry-run |
| `estate/telemetry.py` (proposed) | Per-class removed count + bytes; slot occupancy; cost estimate | emit on every apply/reclaim run |
| Provider adapter (proposed) | OCI (and future clouds) behind a port | stop / terminate / list / limits; decision never calls SDK directly |

Reuse, do not reimplement, the decision-function properties already proven in
consumer `infra/oci/gpu_lifecycle/reaper.py` (existing): refuse-to-act under
uncertainty when load is missing (`_BUSY_LOAD = JobLoadSnapshot(queue_depth=1,
in_flight=1)`), re-sample load after fence delay, separate decision from
actuation (`OciCliStopActuator`). The never-deployed design was OCID-pinned and
self-hosted on a host with no CLI; the package places the supervisor
off-subject and tag-driven. Logic shape stays; deployment topology is new.

Lane reclaimers consume the existing marker contract from consumer
`scripts/remote_agent.sh` (existing; current upstream implementation, writes
`.workbay-lane-sandbox`, reads `AGENT_ROOT` / `SANDBOX_TTL_SEC` / `MAX_LANES`)
without changing marker semantics. A directory without the marker is never
deleted by the marker-gated path. Unmarked residue on a host is a separate
reclaim class (`unmarked_lane_sandboxes`), not a rewrite of the marker contract.

## Contracts

**Provider port** (proposed interface; OCI is one adapter, not the design)
`[CARD-16]`:

| Operation (proposed) | Required behaviour |
| --- | --- |
| `list_instances(page_token?)` | Paginated; returns instance id, state, AD, shape, tags |
| `list_boot_volumes(page_token?)` | Paginated |
| `get_service_limits(resource, ad)` | Used + available for the scarce resource (e.g. `gpu-a10-count`) |
| `stop(instance_id)` | Idempotent; safe to retry `[RES-19]` `[API-02]` |
| `terminate(instance_id)` | Distinct authority from stop; not held by the default timer principal `[CARD-10]` `[CARD-15]` |
| `launch(...)` | Returns provider-side acceptance or limit rejection |

Adapters must not invent contract metadata the provider did not supply
`[rg-015]`. Missing fields surface as probe errors, not fabricated defaults.

**Policy contract** (consumer-supplied `estate.yaml`; exact key names — no
synonyms). Mechanism only in the package; policy only in the consumer file.
Every key below is required at load unless marked optional. Absent file,
malformed file, missing required key, unknown key, or duplicate override →
process refuses to start, exits non-zero, mutates nothing `[rg-008]`.

| Key | Type / values | Role |
| --- | --- | --- |
| `control.mutations` | `disabled` \| `enabled` (required; safe value is `disabled`) | Master mutation gate. `disabled` means **no mutating action may run, ever, for any class.** `enabled` is necessary but never sufficient: each action class carries its own `enabled:` and observation mode must also permit it. Emergency-stop instruction: **set `control.mutations: disabled`**. |
| `control.observation.mode` | `null` \| `report_only` \| `live` (required key; `null` = window not started) | When `report_only`, the supervisor plans and emits what it would do; it does not actuate. When `live`, actuation may proceed only if `control.mutations: enabled` and the class is enabled. |
| `control.observation.max_duration_days` | integer (required) | Relative duration of the report-only window. Never an absolute `expires_on`. |
| `control.observation.started_on` | ISO date \| `null` (required key) | Anchor for the relative window. **Paired with `mode`:** the loader rejects (`mode` non-null, `started_on` null) — the window would have no clock — and rejects (`mode` null, `started_on` non-null). Both are set in one operator edit. |
| `inventory.max_items` | integer (required; no silent default) | Hard item cap for `probe_estate` enumeration. |
| `slots.reservation_lease_ttl_seconds` | integer (required) | Lease over **one** reservation record, covering the whole launch window: acquired before the provider launch call, released only by an observed terminal outcome. Expiry moves the record to `uncertain` — it does **not** free the slot and the lease is not re-acquirable while uncertain. |
| `slots.free_floor` | integer | Free-slot headroom. Predicate: refuse an act when `free_slots_after_act < free_floor`. |
| `slots.free_trigger` | integer | Threshold at which free-slot pressure raises an **operator blocker**. Predicate: `free_slots_now <= free_trigger`. Must **not** name an automated action that frees a slot: stop does not free a slot; terminate is forbidden to the scheduled principal. |
| `slots.launch_min_free` | integer | Launch **pre-check**, evaluated before the provider call: refuse when `(free_slots_before_launch - 1) < launch_min_free`. Pre- and post-check readings differ by exactly one slot, which is the entire margin at two free slots region-wide. |
| `slots.resource_name` | string | Provider service-limit name for the scarce resource (e.g. `gpu-a10-count`). |
| `slots.reconcile.every_pass` | boolean (required) | Whether reconciliation runs before planning on every supervisor pass. |
| `slots.reconcile.provider_count_is_authoritative` | boolean (required) | On ledger/provider disagreement the provider count wins. Reconciliation is the **only** path that clears an `uncertain` reservation; drift raises an operator blocker and is never silently repaired. |
| `untagged_instance_posture` | tier name | Posture applied to instances that lack a governance tier tag. |
| `never_automate` | list of action names | Actions the supervisor must never take automatically. |
| `version` | integer (required) | Policy schema version; loader refuses a version it does not implement. |
| `tags.tier_key` / `tags.scale_to_zero_key` / `tags.scale_to_zero_value` | string (required) | Tag keys and the exact scale-to-zero match value the selector reads. Never instance names or OCIDs `[rg-009]`. |
| `tiers.<T>.description` | string | Human label for the tier. |
| `tiers.<T>.idle_ttl_seconds` | integer \| `null` | Per-tier idle TTL before stop is considered. `null` = idle TTL not applicable; the tier is never selected for lifecycle stop. |
| `tiers.<T>.allow_stop` | boolean | Whether stop is permitted for tier T (code-level check is defence in depth; see T0 structural refusal below). |
| `tiers.<T>.allow_terminate` | boolean | Whether terminate is permitted for tier T. |
| `tiers.<T>.allow_scale_to_zero` | boolean | Whether the scale-to-zero tag is honoured for tier T. |
| `lifecycle.fence_delay_seconds` | integer (required) | Re-sample delay before acting on an idle decision. |
| `lifecycle.fail_safe_on_unreadable_load` | `busy` (required) | Posture when the load snapshot is missing or unreadable: treat as busy, never stop blind. |
| `lifecycle.stop.enabled` / `lifecycle.terminate.enabled` | boolean (required; safe value `false`) | Per-action gates, additional to `control.mutations` and the observation mode. |
| `reclaim.steady_state_always_runs` | boolean (required) | Enabled classes run their age/count gates on every timer firing regardless of free disk. A reclaimer gated only on disk pressure never runs on a host with headroom, which makes every reclaim proof unsatisfiable. |
| `reclaim.free_disk_trigger_pct` / `reclaim.free_disk_floor_pct` | integer percent (required) | Pressure escalation as a fraction of the volume, so the values do not go stale when the disk is resized `[COST-12]`. Hysteresis: the loader rejects `floor_pct <= trigger_pct`. |
| `reclaim.max_targets_per_class_per_pass` | integer (required) | Per-class enumeration budget. A single global cap consumed in declaration order starves trailing classes `[RES-01]` `[PERF-07]`. |
| `reclaim.max_targets_per_pass` | integer (required) | Hard ceiling on the sum across classes. |
| `reclaim.class_visit_order` | `rotating` (required) | Classes are visited starting at `pass_number mod class_count`, so no class is structurally last. |
| `reclaim.enumeration_cap_is_error` | boolean (required) | Hitting either cap is fail loud: non-zero exit, no silent truncation `[CARD-07]`. One class hitting its cap must not halt the others `[rg-007]`. |
| `reclaim.classes.<name>.enabled` | boolean | Per-class enable. All nine classes must be declared; enabling is staged per class. |
| `reclaim.classes.<name>.params` | map | Per-class parameters (retention counts, paths, protected tags, etc.). **Every** class parameter lives inside this map; a parameter written as a sibling of `enabled:` is an unknown key and refuses the load. |
| `credentials.oci_config_env` / `credentials.oci_profile_env` | string (required) | Environment-variable **names** only; no credential material in the file `[WEB-16]` `[PG-09]`. |
| `overrides` | list (required; may be empty) | Per-resource overrides — the only place a display name may appear. Duplicate match targets are a load error, not last-wins `[PROV-08]`. |

Canonical reclaim class names (all nine must appear in policy):

```
marker_lane_sandboxes      unmarked_lane_sandboxes    container_images
scratch_clones             docker_build_cache         journal
apt_cache                  uv_cache                   grok_logs
```

**Actuation authority split** `[CARD-10]` `[CARD-04]`:

| Action | Principal class | Default |
| --- | --- | --- |
| inventory / plan / dry-run apply | read | supervisor timer OK |
| stop | read + stop | supervisor timer OK, subject to IAM tag condition and policy gates |
| terminate | read + terminate | operator-invoked; withheld from timer principal |
| reclaim (local disk) | host root or equivalent, not lane-execution account | supervisor timer OK |

Terminate authority and lane-execution identity must not share a trust boundary.
A second credential held by the same principal is not dual control `[CARD-04]`.

**T0 refusal is structural, not a policy field** `[CARD-10]` `[SEC-04]`. Bind
the stop principal's IAM policy to a tag condition that excludes tier T0 **at
the provider**, so the refusal survives any policy-file edit or bad merge. The
code-level check that refuses T0 is defence in depth and must be described as
such in package docs; it is not the primary control.

## Consistency model for the slot ledger

**Decision:** lease-file serialization with the same flock discipline as
upstream `acquire_heavy_slot` / `acquire_backend_local_slot` (existing symbols
on `host_resources.py`), not advisory optimistic check. With only a handful of
free GPU slots region-wide, a lost-update on reserve is the failure the ledger
exists to prevent `[DATA-18]`.

**Supported topology (v1 constraint):** single-supervisor deployment only. One
supervisor process holds the reservation lease medium for the estate. Running a
second supervisor against the same estate without a shared lease medium is
unsupported; the failure mode is double-grant of a free slot (two concurrent
launches into free count 1). Multi-supervisor requires a shared lease medium;
that is Open Question 1, not a silent assumption.

| Scenario | Behaviour |
| --- | --- |
| Two concurrent `reserve()` calls for the same AD/resource | Flock on a per-(AD, resource) lease path; second waiter observes the first's reservation or provider reconcile result. Only one proceeds while free count permits. |
| Reservation held across launch latency | `reserve()` takes a time-bounded lease (`slots.reservation_lease_ttl_seconds`; not hardcoded). Lease records claimant id, AD, resource, expiry. The lease **must cover the whole launch window** and be renewed while launch is in progress. |
| Launch succeeds | `reconcile()` against provider inventory; lease released; STOPPED/RUNNING instance now occupies the slot in the ledger. |
| Launch fails **definitively** (provider rejects, typed error) | Caller or reclaim path calls `release()`; lease expiry is the backstop so a crashed claimant cannot pin a slot forever after a *definitive* failure `[RES-19]`. |
| Launch fails **ambiguously** (timeout, connection reset, unknown provider state) | Reservation moves to **uncertain**. Only provider reconciliation may clear uncertain. **Never auto-release** an ambiguous failure — the slot may already have been consumed provider-side `[DATA-18]` `[RES-01]`. |
| Lease expires **mid-launch** | Expiry during a launch is itself **uncertain**, not free. A second supervisor must not be granted the same slot while the first launch is still unresolved. |
| Process crash mid-reserve (no launch started) | Next `reserve()` / `reconcile()` treats a lease past TTL with no in-flight launch as free after re-reading provider limits. |
| Provider usage disagrees with the ledger | **Provider count is authoritative.** The ledger is corrected toward the provider on every reconcile `[DATA-19]`. |

**Slot pressure semantics:** stop does **not** free a slot. Only terminate does,
and terminate is forbidden to the scheduled principal. Therefore
`slots.free_trigger` raises an operator blocker; it must not name or invoke an
automated action that frees a slot.

**Provider limits remain the hard ceiling.** A race past the lease layer still
faces the provider's own limit rejection. The ledger's job is to refuse under
uncertainty *before* burning launch latency, not to replace the provider.

**Required test:** two concurrent `reserve()` calls against a ledger fixture
with free count 1; exactly one succeeds, the other raises a typed capacity
error; no silent double-grant. Additional required tests: ambiguous launch
failure leaves reservation uncertain (not free); mid-launch lease expiry leaves
reservation uncertain; reconcile corrects ledger toward provider when they
disagree.

## Bounded enumeration

`probe_estate()` (proposed) must paginate every list API to completion **or**
until the hard item cap `inventory.max_items`, whichever comes first.

| Rule | Value |
| --- | --- |
| Pagination | Follow provider page tokens until exhausted |
| Item cap | Policy key `inventory.max_items` (required; no silent default) `[rg-008]` |
| At cap | Return a truncated inventory **and** set `truncated=true` on the result; CLI exits non-zero (**fail loud**); apply/reclaim refuse to act on a truncated inventory `[CARD-07]` `[CARD-12]` |
| Silent short list | Forbidden — a truncated set that looks complete is a safety bug (reads as "nothing to do" when the system is blind) |

Reclaimers and the slot ledger iterate only a complete, non-truncated probe
result. Under truncation, destructive paths refuse-to-act under uncertainty.

## Safety posture

Two axes — do not conflate them. Fixed phrases only:

| Axis | Under uncertainty | Precedent |
| --- | --- | --- |
| **Destructive action** | *Refuse-to-act under uncertainty* — never free a resource you cannot prove idle, unreferenced, and in scope; never delete a sandbox that holds commits beyond base; never launch when the ledger or probe is incomplete or truncated | `reaper.py` (existing) `_BUSY_LOAD` busy-when-unknown; marker-gated reclaimer never deletes unmarked dirs |
| **Process exit status** | *Fail loud* — a failed pass exits non-zero; systemd marks the unit failed; the timer keeps its schedule; the next pass re-evaluates from scratch. One class failing must not halt the others `[CARD-07]` `[rg-007]` | per-target no-progress counters; one target's failure does not halt the others |

| Action class | Policy |
| --- | --- |
| stop | Routine when gates permit; dry-run default; refuse-to-act if load sample is missing or busy; T0 excluded by provider IAM (structural) plus code defence-in-depth |
| terminate | Distinct authority; never automatic from the timer principal `[CARD-15]` |
| reclaim with evidence of live work (e.g. commits beyond synthetic base) | Never automatic |
| reclaimer error on one target | Leave that target; continue remaining targets; exit non-zero past stall threshold |
| broken / truncated slot ledger | Refuse launch; never launch blind |
| `control.mutations: disabled` | No mutating action of any class, ever |
| `control.observation.mode: report_only` | Plan and report only; no actuation even if class `enabled:` is true |

## Configuration

Load-time structural validation only `[rg-008]`:

- File **absent** → refuse to start, exit non-zero, mutate nothing.
- File present but **malformed**, or **missing any required key** → same.
- **Unknown key** → load error. Never ignored; a typo in a safety field must not
  silently disable that field.
- **Duplicate overrides** targeting the same resource → load error, not
  last-wins.
- No silent defaults for any required key.

The hostgov precedent — a top-level key that should be nested, silently
ignored — is the anti-pattern. The estate loader **rejects**, not warns.

**Precedence** (highest wins) `[AGT-20]`:

1. Explicit CLI flags (operator, this invocation)
2. Environment overrides (deployment, this host)
3. `estate.yaml` on disk (reviewed artifact for the estate) `[PROV-08]`
4. Detected provider/host facts (never overridden downward into fiction)

**Detect what you can; configure only what you cannot** `[AGT-19]`: instance
state, AD, shape, service-limit usage, and tags come from the provider probe.
Idle TTLs, tier membership rules, reclaim class definitions, retention counts,
`slots.reservation_lease_ttl_seconds`, `inventory.max_items`,
`control.mutations`, and `control.observation.*` come from policy — they are
preference, not measurement.

Policy keys off **tags**, never instance names or ids `[rg-009]`.

## Acceptance criteria

Each criterion is an invariant, independently checkable and able to go red.
None pin a snapshot count from a single measurement date. Each is an executable
assertion against the package under test.

### Config and control plane

1. `load_estate_policy` (proposed) raises and the process exits non-zero when the
   policy file is absent; mutates nothing.
2. `load_estate_policy` raises on malformed YAML / missing any required key
   listed in the Policy contract table, and never returns an empty permissive
   default `[rg-008]`.
3. A nested-vs-top-level key mistake in policy is rejected at load (no silent
   ignore).
4. An unknown key in policy is a load error (not ignored). A class parameter
   written as a sibling of `enabled:` instead of inside `params:` is an unknown
   key and fails this criterion.
5. Duplicate overrides targeting the same resource are a load error (not
   last-wins).
5a. A key of the **wrong type** (string where an integer is required, list where
    a map is required) is a load error naming the key and both types.
5b. A value **outside its domain** — negative TTL or count, percent outside
    0–100, tier name not in `tiers`, enum value not in the declared set,
    `reclaim.free_disk_floor_pct <= reclaim.free_disk_trigger_pct` — is a load
    error naming the key and the permitted domain.
6. When `control.mutations` is `disabled`, every mutating CLI path
   (`apply`, `reclaim`, stop/terminate actuators) performs zero mutations and
   exits with a typed "mutations disabled" outcome.
7. When `control.observation.mode` is `report_only`, plan output is produced and
   zero provider mutations occur, even if class-level `enabled:` is true and
   `control.mutations` is `enabled`.
8. `control.observation.mode` and `control.observation.started_on` are validated
   as a pair: (`mode` non-null, `started_on` null) is a load error, and
   (`mode` null, `started_on` non-null) is a load error. `max_duration_days` is
   required in all cases. An absolute `expires_on` is rejected as an
   unknown/unsupported key.
9. `inventory.max_items` is required at load; omitting it is a load error (no
   silent default). A `probe_estate` run against an estate with more items than
   the cap returns `truncated=true` and exits non-zero rather than a short list.
10. `slots.reservation_lease_ttl_seconds` is required at load; omitting it is a
    load error (no silent default). A reservation whose lease has expired is
    reported as `uncertain` and a second `reserve()` for the same AD is refused
    while it remains so.
10a. `untagged_instance_posture` is required at load. An instance carrying no
     tier tag, or a tier tag whose value is not declared in `tiers`, is
     evaluated under that posture; a test fixture with a missing tag and one
     with a garbage tag both resolve to it and neither is stopped.
11. Policy declaring fewer or more than the nine canonical reclaim class names,
    or renaming one, is a load error.
12. Each of the nine reclaim classes carries its own `enabled:`; a class with
    `enabled: false` is never actuated.

### Inventory and slots

13. Inventory's per-AD used count for a scarce resource equals the provider's own
    reported limit usage for that resource and AD on the same probe, whatever
    the values are.
14. A STOPPED instance is counted as occupying its AD slot in the ledger.
15. Two concurrent `reserve()` (proposed) calls against free count 1 yield
    exactly one grant and one typed capacity error.
16. A reservation that outlives its lease TTL **without** a successful launch and
    **without** an in-flight/uncertain launch is treated as free after
    reconcile; no permanent pin.
17. An ambiguous launch failure (timeout / connection reset / unknown provider
    state) moves the reservation to **uncertain**; subsequent `reserve()` does
    not treat that slot as free until provider reconcile clears it.
18. Lease expiry while a launch is in progress leaves the reservation
    **uncertain**, not free; a second `reserve()` against free count 1 does not
    double-grant.
19. When provider usage disagrees with the ledger, `reconcile()` (proposed)
    corrects the ledger toward the provider count `[DATA-19]`.
20. `probe_estate` (proposed) either returns a complete enumeration or a result
    with `truncated=true` and non-zero CLI exit; apply/reclaim refuse truncated
    input.
21. Feeding apply/reclaim a result with `truncated=true` performs zero mutations
    and exits non-zero.

### Lifecycle and reclaim

22. Tag selector includes any instance with the configured lifecycle tag
    regardless of name or who created it; no hardcoded instance id in generic
    modules `[rg-009]`.
23. Idle/fence decision refuses-to-act (busy) when load is missing or probe
    fails (same semantics as existing `_BUSY_LOAD` in
    `infra/oci/gpu_lifecycle/reaper.py`).
24. A reclaimer whose one target errors still processes remaining targets and
    exits non-zero past the stall threshold `[rg-007]`.
25. Marker-gated sandbox reclaimer never selects a directory lacking
    `.workbay-lane-sandbox`, and never selects a fixture holding commits beyond
    synthetic base.
26. CLI mutating subcommands default to dry-run; an explicit flag is required to
    actuate.
27. Package has no import dependency on handoff or on `host_resources.py`
    (existing); `host_resources.py` gains no import from estate.
28. Stop and terminate are distinct actuator methods with distinct authority
    requirements; the default timer principal cannot invoke terminate.
29. `slots.free_trigger` breach emits an operator blocker and does not invoke
    stop or terminate.
30. Negative credential test for terminate asserts the **specific authorization
    error** from the provider and is paired in the same run with a positive
    control that a permitted read/list call succeeds (so a missing CLI cannot
    green the negative path alone).

## Non-goals

- Not a job scheduler or dispatch engine.
- Not a cost optimizer or reserved-instance recommender (telemetry may *report*
  cost; it does not act on price).
- Does not import from or into handoff.
- Does not replace `host_resources.py` (existing) or host-level admission
  (`probe_host`, `evaluate_admission`, slot acquire helpers remain orchestrator).
- Does not own consumer Terraform, cloud-init, or host systemd units — those
  stay in the consuming repo.
- Does not define image-generation product policy or GPU-as-product-centre
  architecture.
- Does not migrate or dual-run against a live reaper — none is deployed; there
  is nothing to agree with for N days and no dual-actuator cutover.
- Does not decommission a running unit as part of package work; consumer
  cleanup of never-deployed cloud-init reaper blocks is dead-template cleanup
  with no runtime effect on any booted host.

## What this repo will do once the package exists

`context-alt-text-monorepo` will supply an `estate.yaml` using the policy keys
above, tag managed instances in `infra/oci/` (existing), clean the never-
deployed reaper block from `infra/oci/cloud-init.yaml` (existing; dead-template
cleanup, no runtime effect), install a timer-driven supervisor under a non-lane
principal, bind stop-principal IAM to a tag condition that excludes T0, and
address host-local unmarked lane residue under the lane account on
`acx-backend` (the 8.8 GB OPS-2 residue lives in a host fork under `~gate`, not
in this repo's `scripts/remote_agent.sh`, which is already the current
marker-writing upstream). That work is tracked as OCIGOV-1 locally; this
request covers only the upstream package surface.

## Open Questions

1. **Shared lease medium for multi-supervisor deploy.** Is a local flock file on
   one T0 host sufficient for v1 (with single-supervisor as the hard supported
   topology), or must the package abstract a remote lease store before any
   second supervisor may launch?
2. **MCP surface scope.** Should estate expose an MCP tool set in v1, or is CLI
   + library sufficient until a consumer requests agent-callable inventory?
3. **Package home.** Confirm `packages/workbay-estate/` (peer of workbay
   orchestrator/system packages) vs. nesting under an existing workbay package
   namespace — maintainers own that layout call.
