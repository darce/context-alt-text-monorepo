# Assessment: organizing the OCI footprint for six workloads (2026-08-04)

> **Question.** How should the remote OCI estate be organized so it can carry
> (1) bursty VLM GPU work, (2) ACX production, (3) the WordPress demo,
> (4) remote lane execution, (5) WAN2.2 diffusion experiments, and
> (6) future MoE local-LLM inference for tightly-scoped boilerplate codegen —
> with the stated main gaps being **reaping completed lanes** and
> **reclaiming disk**.
>
> **Companions.** [`acx-backend-host-disk-audit-2026-08-04.md`](acx-backend-host-disk-audit-2026-08-04.md)
> (where the disk went) · [`OPS-1`](../tech-debt/OPS-1-vm-host-retention-hygiene.md)
> (deferred retention timer) · [`OPS-2`](../tech-debt/OPS-2-vendored-remote-agent-fork.md)
> (the sandbox leak) · [`oci-instance-state-and-cost.md`](../runbooks/oci-instance-state-and-cost.md)
> (billing) · [local-AI roadmap](../roadmaps/local-ai-managed-default-roadmap-2026-07-31.md)
> (why GPU is burst, not the product).

## Verdict

**Do not add machines to solve this.** The A1 box is loaded at 0.09–0.66 on
4 OCPU with 16 GB RAM free — capacity is not the constraint `[ARCH-09]`. The
constraints are **blast radius** (production shares an uncapped kernel with
disposable lane sandboxes) and **lifetime** (nothing on this host has both the
authority and the schedule to reap). Organize by **lifetime and blast radius**,
not by workload type.

The two named gaps are one defect: **no principal on the host can reap.**
`gate` has no `sudo` and no crontab; `ubuntu` has no crontab; `root` has no
crontab. Every reaper that exists is *dispatch-triggered* — it runs as a side
effect of a lane pass, so it stops exactly when a burst ends and the garbage
peaks.

## Measured state (2026-08-04 21:30 UTC)

**Host** — `acx-backend`, `VM.Standard.A1.Flex`, 4 OCPU / 23.4 GB ARM,
`us-ashburn-1` AD-3, up 90 days. Root fs 193 GB: **92 G used / 101 G free**.
Load 0.09 / 0.34 / 0.66. RAM 7 G used, **16 G available**.

**What the 92 GB actually is** — roughly **half the disk is agent lane residue**:

| Owner | Class | Size | Reaped? |
| --- | --- | --- | --- |
| `gate` | `grok-sandbox` — 316 dirs (**68 marked / 248 unmarked**) | 12 G | marked only |
| `gate` | `.cache` / `.grok` / `.npm` | 9.6 / 4.5 / 0.3 G | **no** |
| `ubuntu` | **127 scratch dirs** (`fir7-*`, `wbux5-*`, `planreview*`, `rev*`, `fx*`, …) | **12.4 G** | **no** |
| `ubuntu` | `.cache` / `.grok` / `.cursor-server` / `.npm` | 7.3 / 2.9 / 0.66 / 0.5 G | **no** |
| — | **agent residue subtotal** | **≈ 50 G** | — |
| services | `/var/lib/docker` | 25 G | no policy |
| services | `/opt/acx-backend` (bind-mount state) | 2.8 G | n/a |
| research | `vlm2b/models` (VLM weights, on a CPU-only box) | 12 G | no |
| research | `ComfyUI` (`models/` is **156 KB** — empty) | 4.4 G | no |

**Services** — 12 containers, 4 compose projects (`acx-prod`, `acx-staging`,
`acx-dev`, `acx-demo`) plus `acx-backend` (caddy). Caddy fronts
`api.` / `staging.api.` / `dev.api.altcontext.com` and the demo WP.

**GPU** — both A10s `STOPPED`. Boot volumes: 400 G (AD-1, `acx-gpu-burst`),
400 G (AD-2, `acx-gpu-smoke-20260728-0218`), 200 G (AD-3, `acx-backend`).

## Five findings that decide the layout

### N1 — A stopped A10 still consumes its AD's service limit

This is the finding that reframes the GPU question. Per-AD `gpu-a10-count`:

| AD | limit | used | available |
| --- | --- | --- | --- |
| AD-1 | 1 | **1** (`acx-gpu-burst`, STOPPED) | **0** |
| AD-2 | 2 | **1** (`acx-gpu-smoke`, STOPPED) | 1 |
| AD-3 | 1 | 0 | 1 |

Both instances are STOPPED and both still hold a slot. **AD-1 is fully
consumed by a box that is not running.** Two consequences:

1. **The scarce GPU resource is slots, not dollars.** There are exactly **two
   free A10 slots** in the only subscribed region, and A10 capacity in Ashburn
   has already produced an Oracle SR
   ([`incidents/oracle-sr-a10-capacity-2026-07-16.md`](../../infra/oci/incidents/oracle-sr-a10-capacity-2026-07-16.md)).
   VLM burst and WAN2.2 cannot both be long-lived-stopped instances *and* leave
   headroom.
2. **During the 173 h the smoke instance ran** (per the audit's adjacent
   observation), it held AD-2. Combined with AD-1's stopped burst instance, the
   estate was one AD from having no A10 slot at all.

### N2 — The GPU reaper is name-pinned and self-hosted, so it has no second exit

`infra/oci/cloud-init.yaml:44` bakes the instance identity into the unit:

```
ExecStart=… -m infra.oci.gpu_lifecycle … --instance-id ${GPU_INSTANCE_ID}
```

and `infra/oci/main.tf:270` sets `scale_to_zero = "true"` on **one** instance.
So the reaper (a) covers exactly one named box, and (b) **runs on the box it is
supposed to stop**. A hand-created instance gets no reaper at all — which is
precisely the 173 h incident — and a wedged OS cannot reap itself `[CARD-16]`.
There is **no `oci` CLI installed on `acx-backend`**, so the always-on host
cannot act as the external supervisor even though it is the obvious place.

Instance-name pinning in a generic lifecycle module is also a direct `[rg-009]`
violation: the policy should key off the `scale_to_zero` **tag**, not a name.

### N3 — Production has no cgroup limits and shares the kernel with lanes

Every `acx-*` backend container runs `Memory=0`, `NanoCpus=0` — no bound at
all. Only the demo is capped (WP 2 GB / 1 CPU, MariaDB 1 GB / 0.5 CPU).

On a 4-OCPU box that *also* hosts remote lane execution, an idle ComfyUI, and
12 GB of VLM weights, `acx-prod-api-1` is protected from a runaway lane fleet
by nothing but luck. This is the blast-radius argument `[CARD-10]`, and it is
the *only* real argument for separating workloads here — capacity is not
scarce, isolation is.

### N4 — The lane leak is a split-brain, and it moves in both directions

`~gate/grok-sandbox` currently holds **68 marked / 248 unmarked** (316 total).
The audit measured **46 / 312** (358) this morning: the marker-gated sweep is
working on what it can see, and 42 directories were reclaimed during the day —
but the unmarked class remains the majority and is **structurally unreapable**
because this repo's vendored `remote_agent.sh` fork writes no marker
([`OPS-2`](../tech-debt/OPS-2-vendored-remote-agent-fork.md)).

**`OPS-1` under-counts the `ubuntu` side.** Its finding F4 names six scratch
clones at 6.1 GB. The real figure is **127 directories at 12.4 GB**, spanning
2026-07-19 → 2026-08-01, and they are **not** under any sandbox root — they are
`grok` CLI session working directories in `$HOME`. No existing or proposed
sweep addresses them. This is a **third** leak class, distinct from OPS-1 F4
and OPS-2 F6.

### N5 — The two GPU-shaped workloads parked on this CPU box are both finished or empty

**ComfyUI** — `python main.py --cpu` is running right now on `127.0.0.1:8188`
with `models/` holding **156 KB**; every model subdirectory is empty. An idle
husk holding ~530 MB RSS and a process slot on the scarce 4-OCPU resource.

**`vlm2b` (12 G)** — a **completed and harvested** bake-off, not current or
planned work. Weights written 2026-07-07, **last read 2026-07-09** (26 days
idle). Task VLM-2B, llama.cpp b9893 on A1 aarch64; the decision memo and
per-model reports are committed under `docs/tasks/vlm/`. The 12 GB is three
candidates, each weights + vision projector:

| Candidate | Weights | mmproj | Total | Outcome |
| --- | --- | --- | --- | --- |
| MiniCPM-V-4.5 | 4.7 G | **1.1 G (f16, unquantized)** | **5.8 G** | **disqualified** |
| CapRL-Qwen3VL-4B | 2.6 G | 433 M (Q8_0) | 3.0 G | runner-up |
| Qwen3-VL-4B-Instruct | 2.4 G | 433 M (Q8_0) | 2.8 G | **winner** |

Two reasons it is this large: nearly half (5.8 G) belongs to the *disqualified*
candidate, and MiniCPM's projector shipped as **f16** where the other two ship
Q8_0 at 433 MB. **8.8 GB — the disqualified and losing candidates — is
reclaimable with no loss**; the reports are already in the repo.

### N5b — Measured CPU inference throughput kills the "MoE on `acx-backend`" option

The `vlm2b` logs are the only real inference benchmark this host has, and they
are unambiguous. A **4 B dense Q4_K_M** model on 3 threads:

| Model | Prompt eval | Generation |
| --- | --- | --- |
| Qwen3-VL-4B-Instruct | 137 ms/tok (**7.3 tok/s**) | 227 ms/tok (**4.4 tok/s**) |
| CapRL-Qwen3VL-4B | 137 ms/tok (7.3 tok/s) | 219 ms/tok (4.6 tok/s) |
| MiniCPM-V-4.5 | 285 ms/tok (3.5 tok/s) | 256 ms/tok (3.9 tok/s) |

At 137 ms/token of prompt eval, a 2 000-token codegen prompt costs **~4.5
minutes before the first output token**, and generation runs at ~4 tok/s. A
30B-A3B MoE has comparable *active* parameters but far heavier memory-bandwidth
pressure on ARM, so it will not beat these numbers meaningfully.

**Correction to the placement table below:** MoE codegen on `acx-backend` is not
"slow but usable" — at these rates it is unusable for interactive boilerplate
generation. Treat CPU-local MoE as **rejected on measured evidence**
`[ARCH-09]`, not as a capped T1 option. If local codegen is wanted, it belongs
on T2 (GPU) or on the laptop; if it is wanted *cheaply*, the honest answer is a
hosted API. This is exactly the "quantify load before scaling" test — the
measurement already exists and says no.

## The organizing principle: three tiers by lifetime

| Tier | Lifetime | Blast radius rule | Workloads |
| --- | --- | --- | --- |
| **T0 — Durable** | forever; uptime matters | nothing uncapped, nothing experimental | **ACX production**, **WordPress demo**, caddy, the retention timer |
| **T1 — Working** | days; disposable | hard cgroup caps; may be killed to protect T0 | **remote lane execution**, dev + staging |
| **T2 — Ephemeral GPU** | hours; instance-scoped | own instance, external reaper, image-not-instance persistence | **VLM burst**, **WAN2.2 diffusion** |

The rule that makes this work: **T2 never persists as a stopped instance, and
T1 never runs uncapped next to T0.**

### Placement

| Workload | Tier | Where | Change from today |
| --- | --- | --- | --- |
| ACX production | T0 | `acx-backend` | **add cgroup floors** so T1 cannot starve it |
| WordPress demo | T0 | `acx-backend` | none — already capped correctly |
| Remote lane execution | T1 | `acx-backend`, `gate` | cap CPU/mem; retire the fork (OPS-2 route A) |
| dev / staging | T1 | `acx-backend` | cap; confirm 3-month `:staging` pin is intentional |
| VLM bursty GPU | T2 | ephemeral A10 | **external** tag-driven reaper; custom image, terminate not stop |
| WAN2.2 diffusion | T2 | ephemeral A10, **separate image** | move off `acx-backend` entirely; kill the CPU ComfyUI |
| MoE codegen | **T2 or off-estate** | not `acx-backend` | **rejected on CPU** — see N5b |

### On the MoE codegen workload specifically

The measurement already exists (N5b) and it settles the question: **4.4 tok/s
generation and 137 ms/token prompt eval** on this host for a 4 B Q4 model.
Interactive boilerplate codegen needs a fast first token; a 2 000-token prompt
here costs ~4.5 minutes before generation starts. CPU-local MoE on
`acx-backend` is **rejected on evidence**, not deferred on judgement `[ARCH-09]`.

Remaining options, in order of honesty about cost:

1. **Hosted API** — no infra, no reaping, no slot contention. Correct default
   for "tightly scoped boilerplate" unless the point is sovereignty.
2. **T2 on a GPU instance** — fast, but consumes one of the two remaining A10
   slots (N1) and needs the same reaper work as VLM and WAN2.2.
3. **The laptop** — free, already has the RAM, no shared-host blast radius.

Do **not** buy a second A1 for it. Tenancy A1 headroom exists (246 cores /
1642 GB available in AD-3), but only the first 4 OCPU / 24 GB is Always Free,
and a second box would reproduce the same throughput ceiling that just failed.

## Closing the two named gaps

### Gap A — reaping: one root-owned timer, four classes

`OPS-1` already specifies this correctly; the changes below are **additive
corrections** from this investigation. A `systemd` **timer** (not a dispatch
hook — that is the structural defect) running as root, daily:

1. `docker builder prune -af` — zero risk, ~9 GB last time.
2. Image retention **count-based on `rollback-*` aliases**, keep newest 5.
   Age-based pruning destroys the rollback history to reclaim ~80 MB (OPS-1
   documents this trap).
3. `journalctl --vacuum-size=512M` + set `SystemMaxUse=512M`; `apt clean`.
4. `uv cache prune`; TTL sweep of `~/.grok/{sessions,logs}` for **both** accounts.
5. **NEW — `~ubuntu` scratch sweep (N4).** 127 dirs / 12.4 GB that no existing
   or proposed sweep covers. Must be **marker-and-TTL gated the same way the
   workbay sweep is**, never a glob on `$HOME` — an unguarded sweep there would
   eat `src/`, `data/`, `work/`, `lane-archive/` `[CARD-15]`.

Design constraints the timer must honour:

- **Log what was removed, per class, count + bytes.** A silent sweep reads as
  "nothing to do" when it is broken `[CARD-07]`, and OPS-1 AC#4 already says so.
- **Bounded, fail-open per class.** One class failing must not abort the
  others, and the run must exit non-zero after a bounded no-progress threshold
  `[rg-007]`.
- **Retention policy in a validated config file**, not inline constants
  `[rg-008]`.
- **Never delete an unmarked sandbox holding commits beyond the synthetic base.**
  197 of the unmarked directories do; they may be the only copy of unharvested
  lane output. Marker-backfill the 115 base-only ones and let the tested 48 h
  sweep take them `[CARD-15]`, same discipline as `[rg-017]`.

### Gap B — disk and cost reclamation

Ordered by value per unit of risk.

| # | Action | Reclaims | Risk |
| --- | --- | --- | --- |
| 1 | **Terminate** `acx-gpu-smoke-20260728-0218` (capture an image first if its state matters) | 400 GB billed boot volume **+ an AD-2 A10 slot** | low — it is a smoke box |
| 2 | Stop + remove the CPU ComfyUI; delete `~/ComfyUI` (models dir is empty) | 4.4 G + ~530 MB RAM + a process slot | low — N5 |
| 3 | Marker-backfill the 115 base-only sandboxes; let the 48 h sweep run | ~3–4 G | low — tested path |
| 4 | Sweep `~ubuntu` scratch older than 14 d, **excluding** `src/ data/ work/ lane-archive/ bin/ oi-venv/` | up to 12.4 G | medium — needs the marker/TTL gate first |
| 5 | `~gate/.cache` + `~ubuntu/.cache` prune (`uv cache prune`, pip, npm) | up to ~10 G | low |
| 6 | Delete the **disqualified + losing** `vlm2b` candidates (MiniCPM 5.8 G, CapRL 3.0 G) | **8.8 G** | low — bake-off closed, reports committed (N5) |
| 6b | Decide the 2.8 G winner (Qwen3-VL-4B): keep as a warm re-serve, or drop — it is re-downloadable | 2.8 G | operator call |
| 7 | Decide `acx-gpu-burst`'s 400 GB boot volume: keep as warm-start, or terminate to a custom image | 400 GB billed | **operator call** — trades restart latency for spend |

Items 1 and 7 are the only ones that touch money; everything else is host disk
the box does not currently need (101 GB free). **None of this is urgent** —
it is worth doing because items 3–5 recur, not because the box is full.

### Also fix while in there

- **`/opt/acx-backend` holds 9 `Caddyfile.bak.*` and 9
  `docker-compose.caddy.yml.bak.*` files.** The edge config of the production
  host is being edited in place with ad-hoc backups instead of being version
  controlled. Small, but it is the routing layer for `api.altcontext.com`.
- Confirm the 3-month-old `:staging` image pin is deliberate, not a stalled
  deploy.

## Canon verification

Checked against `~/Development/heuristics-canon-research` (1147 rules,
11 lexicons) and the reasoning cards. Every ID below was read, not recalled.

| Claim | Rule / card | Verdict |
| --- | --- | --- |
| Don't add machines; capacity is not the constraint | `[ARCH-08]` single machine first · `[ARCH-09]` quantify load before scaling | Pass — load 0.09–0.66 / 16 G free |
| Separate for isolation, not capacity | `[ARCH-06]` everything is a trade-off | Pass — states the cost (cgroup tuning) |
| Uncapped prod beside disposable lanes is the real risk | [`least-privilege-blast-radius`](../../../heuristics-canon-research/reasoning/least-privilege-blast-radius.md) CARD-10 | Pass — N3 |
| Every sandbox/lane needs a TTL | [`feedback-bounded-waiting`](../../../heuristics-canon-research/reasoning/feedback-bounded-waiting.md) CARD-09 | Pass — unmarked sandboxes are unbounded |
| Self-reaping GPU has no second exit | [`second-exit-hostile-landlord`](../../../heuristics-canon-research/reasoning/second-exit-hostile-landlord.md) CARD-16 | Pass — N2, cut vertex |
| Reaper must log what it removed | [`fail-loudly-succeed-quietly`](../../../heuristics-canon-research/reasoning/fail-loudly-succeed-quietly.md) CARD-07 | Pass |
| Don't blanket-`rm` the 197 committed sandboxes | [`reversible-commitments`](../../../heuristics-canon-research/reasoning/reversible-commitments.md) CARD-15 · `[rg-017]` | Pass |
| Reaper must be bounded and fail per-class | `[rg-007]` | Pass |
| Retention policy validated at load | `[rg-008]` | Pass |
| Instance-name pinning belongs in config, not the module | `[rg-009]` | **Fail today** — `cloud-init.yaml:44` pins `--instance-id` |
| GPU is burst capacity, not the product centre | [local-AI roadmap §4.1](../roadmaps/local-ai-managed-default-roadmap-2026-07-31.md) · `[ARCH-08][ARCH-09]` | Pass — T2 is explicitly ephemeral |
| WAN2.2 / MoE are dev-productivity, not product | roadmap §4.2 defers local VLM + GPU fleet | Pass — placed in T1/T2, isolated from T0 |

**Method limitations, stated honestly:** the `semantic_reinjection_packet` call
returned `status: skipped, skip_reason: no_embeddings` — the task row is new and
has no embedded concepts, so no semantic reinjection informed this document.
The codemap index for this repo does not exist and `index_repository` crashed on
a file (`outcome: exit_nonzero`), so code claims here were verified by direct
read of `infra/oci/` and by live probes against the host, not via the graph.

## Sequenced actions

**Now (cheap, reversible, unblocks the rest)**

1. Terminate `acx-gpu-smoke-20260728-0218` — frees an A10 slot and 400 GB of
   billed storage (N1).
2. Kill the CPU ComfyUI and remove `~/ComfyUI` (N5).
3. Add cgroup limits to the `acx-*` compose files so T1 cannot starve T0 (N3).

**Next (closes the named gaps)**

4. Resolve `OPS-2` via route **A** — retire the vendored fork so markers, the
   48 h TTL, the lane lease, and one shared cap come for free.
5. Backfill markers on the 115 base-only sandboxes; hold the 197 with commits.
6. Build the `OPS-1` root timer, **including the new `~ubuntu` class (N4)**.

**Then (structural)**

7. Make the GPU reaper **tag-driven and external**: install the `oci` CLI on
   `acx-backend` with an instance principal, and have it stop *any* instance
   tagged `scale_to_zero=true` that is idle — instead of one box stopping
   itself by name (N2, `[rg-009]`, `[CARD-16]`).
8. Define the T2 image contract: one image per GPU workload (VLM, WAN2.2), so
   an instance is *created and terminated*, never left stopped holding a slot.
9. Version-control `/opt/acx-backend/Caddyfile` and the caddy compose file.

## What not to do

- **Do not provision a second A1 for the MoE workload before measuring.**
  `[ARCH-09]` — and the box is idle.
- **Do not run `docker image prune -a --filter until=…`.** It destroys the
  rollback history to reclaim ~80 MB (OPS-1 documents the arithmetic).
- **Do not `rm -rf ~gate/grok-sandbox/*`.** 197 directories hold commits
  beyond the base and may be unharvested lane output.
- **Do not glob-sweep `~ubuntu`.** `src/`, `data/`, `work/`, `lane-archive/`,
  `bin/`, `oi-venv/` live in the same directory as the 127 scratch dirs.
- **Do not put WAN2.2 or a VLM on `acx-backend`.** Both already have weights
  parked there (16.4 GB combined) with no GPU to use them.
- **Do not make the reaper a dispatch hook.** That is the exact defect: it
  stops when traffic stops, which is when the garbage peaks.
