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

## Motivation

Measured 2026-08-04 on tenancy host `acx-backend` (observations, not invariants):

| ID | Observation |
| --- | --- |
| N1 | A STOPPED GPU instance still consumes its AD's `gpu-a10-count`. Region-wide, only two free A10 slots were available at measurement. The scarce unit is slots, not dollars. Nothing in workbay accounts for that unit. |
| N2 | GPU lifecycle is name-pinned and self-hosted: `infra/oci/cloud-init.yaml` runs the reaper on the instance it is meant to stop with `--instance-id ${GPU_INSTANCE_ID}`. Hand-created instances get no reaper; a wedged OS cannot stop itself. The always-on box has no `oci` CLI. Tag `scale_to_zero=true` exists on one instance and nothing reads it. |
| N3 | All 10 `acx-*` containers run uncapped (`HostConfig.Memory = 0`, `NanoCpus = 0`). Production shares an uncapped kernel with disposable lanes. |
| N4 | ~50 GB of ~92 GB used on `acx-backend` is agent-lane residue. Every reclaimer is dispatch-triggered inside `remote_agent.sh`, so collection stops when garbage peaks. No principal has both authority and a schedule. |

These are symptoms of one missing owner. Patching them inside consumer scripts
reproduces split ownership. The package belongs upstream so any consumer repo
can supply policy without reimplementing mechanism.

**Terminology.** **Reclaimer** is the noun for the component that frees a
resource under evidence gates. "Reaper" and "sweep" are legacy names for the
same role (existing `reaper.py` decision function; dispatch-time sandbox sweep
in `remote_agent.sh`). Other terms:

| Term | Meaning |
| --- | --- |
| Estate | Provider resources (instances, boot volumes, images, service-limit slots) across all ADs in one tenancy |
| Slot | One unit of a provider service limit in one AD; consumed by RUNNING **and** STOPPED instances |
| Tier | Lifetime class — `T0` durable, `T1` working, `T2` ephemeral; drives blast-radius policy |
| Actuator | Component that changes provider state (start / stop / terminate) |
| Reservation | Time-bounded claim on a slot held across provider launch latency |

## Why a third application, not a feature of orchestrator

Upstream `host_resources.py` already governs **admission of work onto one host**:
`probe_host`, `load_host_memory_policy`, `evaluate_admission`,
`acquire_heavy_slot`, `acquire_backend_local_slot`, `count_held_heavy_slots`,
`crash_breaker_width_cap`, `record_admission_telemetry`, CLI at
`hostgov_cli.py`. That surface answers "may this job run here?" It does not
answer "what machines exist, which slots do they hold, and may we create
another?"

| Concern | Owner today | Coupling type `[REF-13]` |
| --- | --- | --- |
| Work → one host | orchestrator / `host_resources.py` | affinity (work needs host resources) |
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
| `estate/inventory.py` | Enumerate provider resources; paginated, bounded | `probe_estate()` → instances + boot volumes + limits per AD |
| `estate/slots.py` | Slot ledger; STOPPED counts as occupied; concurrent reserve | `SlotLedger`, `reserve()`, `release()`, `reconcile()` |
| `estate/policy.py` | Load and structurally validate consumer policy | `load_estate_policy(root)` — raises on malformed |
| `estate/lifecycle.py` | Tag-driven selector + idle/fence decision (port from consumer `reaper.py`) | selector on tags only (no instance name/id) `[rg-009]`; fail-safe-to-busy as in existing `_BUSY_LOAD` |
| `estate/reclaim/` | One reclaimer module per garbage class; evidence-gated; timer-driven | class modules; shared stall-bound runner `[rg-007]` |
| `estate/cli.py` | Operator surface | `estate inventory \| plan \| apply \| reclaim`; `--dry-run` default |
| `estate/telemetry.py` | Per-class removed count + bytes; slot occupancy; cost estimate | emit on every apply/reclaim run |
| Provider adapter | OCI (and future clouds) behind a port | stop/terminate/list/limits; decision never calls SDK directly |

Reuse, do not reimplement, the decision-function properties already proven in
consumer `infra/oci/gpu_lifecycle/reaper.py`: fail-safe to busy
(`_BUSY_LOAD = JobLoadSnapshot(queue_depth=1, in_flight=1)`), re-sample load
after fence delay, separate decision from actuation
(`OciCliStopActuator`). Deployment moves off-box; logic shape stays.

Lane reclaimers consume the existing marker contract from upstream
`remote_agent.sh` (`.workbay-lane-sandbox`, `AGENT_ROOT`, `SANDBOX_TTL_SEC`)
without changing marker semantics. A directory without the marker is never
deleted by the marker-gated path.

## Contracts

**Provider port** (proposed interface; OCI is one adapter, not the design)
`[CARD-16]`:

| Operation | Required behaviour |
| --- | --- |
| `list_instances(page_token?)` | Paginated; returns instance id, state, AD, shape, tags |
| `list_boot_volumes(page_token?)` | Paginated |
| `get_service_limits(resource, ad)` | Used + available for the scarce resource (e.g. `gpu-a10-count`) |
| `stop(instance_id)` | Idempotent; safe to retry `[RES-19]` `[API-02]` |
| `terminate(instance_id)` | Distinct authority from stop; not held by the default timer principal `[CARD-10]` `[CARD-15]` |
| `launch(...)` | Returns provider-side acceptance or limit rejection |

Adapters must not invent contract metadata the provider did not supply
`[rg-015]`. Missing fields surface as probe errors, not fabricated defaults.

**Policy contract** (consumer-supplied `estate.yaml`): tiers, per-tier idle TTL,
reclaim classes, retention counts, tag selectors. Mechanism only in the package;
policy only in the consumer file.

**Actuation authority split** `[CARD-10]` `[CARD-04]`:

| Action | Principal class | Default |
| --- | --- | --- |
| inventory / plan / dry-run apply | read | timer OK |
| stop | read + stop | timer OK |
| terminate | read + terminate | operator-invoked; withheld from timer |
| reclaim (local disk) | host root or equivalent, not lane-execution account | timer OK |

Terminate authority and lane-execution identity must not share a trust boundary.

## Consistency model for the slot ledger

**Decision:** lease-file serialization with the same flock discipline as
upstream `acquire_heavy_slot` / `acquire_backend_local_slot`, not advisory
optimistic check. With only a handful of free GPU slots region-wide, a
lost-update on reserve is the failure the ledger exists to prevent
`[DATA-18]`.

| Scenario | Behaviour |
| --- | --- |
| Two concurrent `reserve()` calls for the same AD/resource | Flock on a per-(AD, resource) lease path; second waiter observes the first's reservation or provider reconcile result. Only one proceeds while free count permits. |
| Reservation held across launch latency | `reserve()` takes a time-bounded lease (TTL configured in policy; not hardcoded). Lease records claimant id, AD, resource, expiry. Launch proceeds while lease is held. |
| Launch succeeds | `reconcile()` against provider inventory; lease released; STOPPED/RUNNING instance now occupies the slot in the ledger. |
| Launch fails or times out after reserve | Caller or reclaim path calls `release()`; lease expiry is the backstop so a crashed claimant cannot pin a slot forever `[RES-19]`. |
| Process crash mid-reserve | Next `reserve()` / `reconcile()` treats expired leases as free after re-reading provider limits. |

**Cost of this choice:** a local filesystem (or equivalent single-writer store)
must be reachable by all estate supervisors that may launch into the same
tenancy. Multi-host concurrent launchers need a shared lease medium; until that
exists, document single-supervisor deployment as the supported topology.

**Provider limits remain the hard ceiling.** A race past the lease layer still
faces the provider's own limit rejection. The ledger's job is to fail closed
*before* burning launch latency, not to replace the provider.

**Required test:** two concurrent `reserve()` calls against a ledger fixture
with free count 1; exactly one succeeds, the other raises a typed capacity
error; no silent double-grant.

## Bounded enumeration

`probe_estate()` (proposed) must paginate every list API to completion **or**
until a hard page/item cap, whichever comes first.

| Rule | Value |
| --- | --- |
| Pagination | Follow provider page tokens until exhausted |
| Item cap | Policy key `inventory.max_items` (required; no silent default) `[rg-008]` |
| At cap | Return a truncated inventory **and** set `truncated=true` on the result; CLI exits non-zero; apply/reclaim refuse to act on a truncated inventory `[CARD-07]` |
| Silent short list | Forbidden — a truncated set that looks complete is a safety bug |

Reclaimers and the slot ledger iterate only a complete, non-truncated probe
result. Under truncation, destructive paths fail closed.

## Safety posture

Two axes — do not conflate them:

| Axis | Under uncertainty | Precedent |
| --- | --- | --- |
| **Destructive action** | Fail **closed** — never free a resource you cannot prove idle; never delete a sandbox that holds commits beyond base; never launch when the ledger or probe is incomplete | `reaper.py` `_BUSY_LOAD` fail-safe-to-busy; marker-gated sweep never deletes unmarked dirs |
| **Process exit status** | Fail **loud** — partial reclaim/apply still exits non-zero past stall threshold so timers and operators cannot miss it `[CARD-07]` `[rg-007]` | per-target no-progress counters; one target's failure does not halt the others |

| Action class | Policy |
| --- | --- |
| stop | Routine; dry-run default; fail closed if load sample is missing or busy |
| terminate | Distinct authority; never automatic from the timer principal `[CARD-15]` |
| reclaim with evidence of live work (e.g. commits beyond synthetic base) | Never automatic |
| broken sweep | Leave garbage; never delete live work |
| broken / truncated slot ledger | Refuse launch; never launch blind |

## Configuration

Load-time structural validation only `[rg-008]`. Missing or malformed required
keys raise; they must not degrade to permissive empty defaults. The hostgov
precedent — a top-level key that should be nested, silently ignored — is the
anti-pattern. The estate loader **rejects**, not warns.

**Precedence** (highest wins) `[AGT-20]`:

1. Explicit CLI flags (operator, this invocation)
2. Environment overrides (deployment, this host)
3. `estate.yaml` on disk (reviewed artifact for the estate) `[PROV-08]`
4. Detected provider/host facts (never overridden downward into fiction)

**Detect what you can; configure only what you cannot** `[AGT-19]`: instance
state, AD, shape, service-limit usage, and tags come from the provider probe.
Idle TTLs, tier membership rules, reclaim class definitions, retention counts,
lease TTL, and `inventory.max_items` come from policy — they are preference, not
measurement.

Policy keys off **tags**, never instance names or ids `[rg-009]`.

## Acceptance criteria

Each criterion is an invariant, independently checkable. None pin a snapshot
count from a single measurement date.

1. `load_estate_policy` raises on missing/malformed required keys and never
   returns an empty permissive default.
2. A nested-vs-top-level key mistake in policy is rejected at load (no silent
   ignore).
3. Inventory's per-AD used count for a scarce resource equals the provider's own
   reported limit usage for that resource and AD on the same probe, whatever
   the values are.
4. A STOPPED instance is counted as occupying its AD slot in the ledger.
5. Two concurrent `reserve()` calls against free count 1 yield exactly one
   grant and one typed capacity error.
6. A reservation that outlives its lease TTL without a successful launch is
   treated as free after reconcile; no permanent pin.
7. `probe_estate` either returns a complete enumeration or a result with
   `truncated=true` and non-zero CLI exit; apply/reclaim refuse truncated input.
8. Tag selector includes any instance with the configured lifecycle tag
   regardless of name or who created it; no hardcoded instance id in generic
   modules.
9. Idle/fence decision fail-safes to busy when load is missing or probe fails
   (same semantics as existing `_BUSY_LOAD`).
10. A reclaimer whose one target errors still processes remaining targets and
    exits non-zero past the stall threshold `[rg-007]`.
11. Marker-gated sandbox reclaimer never selects a directory lacking
    `.workbay-lane-sandbox`, and never selects a fixture holding commits beyond
    synthetic base.
12. CLI mutating subcommands default to dry-run; an explicit flag is required to
    actuate.
13. Package has no import dependency on handoff or on `host_resources.py`;
    `host_resources.py` gains no import from estate.
14. Stop and terminate are distinct actuator methods with distinct authority
    requirements.

## Non-goals

- Not a job scheduler or dispatch engine.
- Not a cost optimizer or reserved-instance recommender (telemetry may *report*
  cost; it does not act on price).
- Does not import from or into handoff.
- Does not replace `host_resources.py` or host-level admission
  (`probe_host`, `evaluate_admission`, slot acquire helpers remain orchestrator).
- Does not own consumer Terraform, cloud-init, or host systemd units — those
  stay in the consuming repo.
- Does not define image-generation product policy or GPU-as-product-centre
  architecture.

## What this repo will do once the package exists

`context-alt-text-monorepo` will supply an `estate.yaml`, tag managed instances
in `infra/oci/`, remove the name-pinned self-hosted reaper unit, install a
timer-driven supervisor under a non-lane principal, and retire the vendored
`scripts/remote_agent.sh` fork so one marker-writing implementation remains.
That work is tracked as OCIGOV-1 locally; this request covers only the upstream
package surface.

## Open Questions

1. **Shared lease medium for multi-supervisor deploy.** Is a local flock file on
   one T0 host sufficient for v1, or must the package abstract a remote lease
   store before any second supervisor may launch?
2. **MCP surface scope.** Should estate expose an MCP tool set in v1, or is CLI
   + library sufficient until a consumer requests agent-callable inventory?
3. **Package home.** Confirm `packages/workbay-estate/` (peer of workbay
   orchestrator/system packages) vs. nesting under an existing workbay package
   namespace — maintainers own that layout call.
