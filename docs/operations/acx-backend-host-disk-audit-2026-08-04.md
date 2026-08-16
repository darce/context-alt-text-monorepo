# Audit: `acx-backend` host disk, Docker, and shared-host hygiene (2026-08-04)

> **Scope.** Read-only audit of the always-on `acx-backend` VM
> (`VM.Standard.A1.Flex`, 4 OCPU / 24 GB, ARM, `us-ashburn-1`) — where the
> disk is going, what has a reaper, and what does not. Triggered by a capacity
> question, not an incident. Nothing was deleted during the audit; one prune
> was run by the operator mid-audit and is called out below.
>
> **Companion docs.** [`docs/runbooks/oci-instance-state-and-cost.md`](../runbooks/oci-instance-state-and-cost.md)
> (is it running / am I billed) · [`docs/runbooks/remote-test-gate.md`](../runbooks/remote-test-gate.md)
> (the gate account on this same host).

## How to reproduce these numbers

The host has two relevant accounts, and **which one you use decides what you
can see**:

| Account | Groups | sudo | Docker |
| --- | --- | --- | --- |
| `gate` (uid 1002) | `gate`, `users` | **password required** | no (`/var/lib/docker` is `drwx--x--- root:root`) |
| `ubuntu` (uid 1001) | `adm`, `sudo`, `lxd`, **`docker`** | **passwordless** | yes |

As `gate`, ~61 GB of the used space is simply invisible — `du` silently skips
`/var/lib/docker` and `/home/ubuntu`, and `journalctl --disk-usage` reports only
the *user* journal (58 M) rather than the real 3.9 G. Audit from `ubuntu`:

```bash
ssh ubuntu@acx-backend.tail1a44b8.ts.net 'sudo du -xh -d1 / | sort -h; docker system df'
```

`sudo` over `ssh` without a TTY fails with *"a terminal is required to read the
password"*; that is a red herring here — `ubuntu` needs no password at all.
(If you ever do need an interactive prompt, `ssh -t` allocates the TTY.)

## Snapshot

Full accounting of the root filesystem (193 G total). The middle column is the
first probe at 17:04 UTC; the right column is after the operator ran
`docker builder prune -af` mid-audit.

| Area | 17:04 UTC | 18:00 UTC | Owner |
| --- | --- | --- | --- |
| **Total used / free** | 108 G / 86 G | **99 G / 94 G** | — |
| `/home/ubuntu` | 39 G | 39 G | alt-context work |
| `/home/gate` | 30 G | 30 G | workbay remote lanes |
| `/var/lib/docker` (`overlay2`) | 23 G | **15 G** (14 G) | alt-context stack |
| `/tmp` | 5.1 G | 5.1 G | mixed `gate` + `ubuntu` |
| `/var/log/journal` | 3.9 G | 3.9 G | system |
| `/usr` | 3.5 G | 3.5 G | system |
| `/opt` (`acx-backend` 2.5 G) | 2.8 G | 2.8 G | alt-context |
| `/var/cache` (apt 446 M) | 481 M | 481 M | system |

Memory at the same time: 23 974 MB total, ~7.5 GB in use, **16.5 GB available**,
load 0.20 / 0.37 / 0.27. The resident set is the real service — 3 ×
`recognition.worker.scan_worker` (~2.7 GB), `dockerd` (755 M), ComfyUI
(`main.py --cpu`, 532 M), `uvicorn api.main` (249 M), and a wide pool of *idle*
postgres backends (~150–185 MB RSS each). **RAM is not a problem on this box;
4 OCPU is the scarce resource.**

## Docker

```
TYPE            TOTAL   ACTIVE   SIZE       RECLAIMABLE
Images          41      7        13.45GB    11.19GB (83%)
Containers      13      13       136MB      0B
Local Volumes   7       5        65.2MB     4.4kB
Build Cache     0       0        0B         0B        <- was 41 records / 8.399GB
```

### Images — 41 unique IDs behind 67 tags, 0 dangling

Every build lands **two** tags: the 40-hex git SHA *and* a
`rollback-<image-id>` alias — 33 SHA tags + 23 rollback tags + 11
semantic/third-party. Two consequences:

1. **Nothing is ever dangling**, so plain `docker image prune` is a guaranteed
   no-op. Only `-a` touches these images.
2. There is **no retention policy at all**. Tags go back 3 months.

Only three tags are in service:

| Tag | Image ID | Age | Used by |
| --- | --- | --- | --- |
| `:dev` | `119696b08933` (1.72 GB) | 2 weeks | `acx-dev-api-1`, `acx-dev-worker-1` |
| `:latest` | `069e12c0e5d6` (1.72 GB) | 3 weeks | `acx-prod-api-1`, `acx-prod-worker-1` |
| `:staging` | `90d169d6b616` (1.24 GB) | **3 months** | `acx-staging-api-1`, `acx-staging-worker-1` |

**Staging is pinned to a 3-month-old image and `acx-staging-worker-1` has been
up 3 months** — that environment has not been redeployed this quarter. Worth
confirming that is intentional.

**The reclaimable figure is misleading.** `system df` advertises 11.19 GB, but
the unused tags share a base layer that `:dev` / `:latest` / `:staging` pin in
place. Summing the *unique* layer size across all 34 unused image rows gives
**~2.29 GB**, and ~2.2 GB of that sits in three images:

| Unused image | Shared | **Unique** |
| --- | --- | --- |
| `acx-backend:rollback-c13e28fc` (3 mo) | 144 MB | **1.10 GB** |
| `acx-backend:74b4ec400bc6b39519a361725b6eb3ca25b9d600` (4 wk) | 381 MB | **901 MB** |
| `wordpress:cli-2.11-php8.3` (16 mo, unused) | 0 B | **185 MB** |

The remaining 31 unused tags total roughly **80 MB combined** (1–4 MB unique
each). So a blanket `docker image prune -a --filter until=…` destroys the whole
rollback history to reclaim ~80 MB, while deleting three specific images
reclaims 2.2 GB. Also unused: `acx-scene-verify:test` (local test build),
`busybox:latest`, and `acx-backend:sha-test` — a leftover test tag aliasing a
3-month-old image.

### Containers — 13, all running, 0 B reclaimable

Four compose projects (`acx-prod`, `acx-staging`, `acx-dev`, `acx-demo`) plus
`acx-backend` (caddy). No stopped containers. Writable layers total 136 MB;
largest are `acx-prod-worker-1` 44.4 MB, `acx-staging-worker-1` 42.8 MB,
`acx-prod-api-1` 41.1 MB — in-container writes that only clear on recreate.

**One exception — see [F1](#f1).** `lane_b_pg_test` belongs to no compose
project (`Labels=map[]`, `RestartPolicy=no`): hand-started with `docker run` on
2026-07-31T06:40:35Z, still up. Its last log line is **2026-07-31 06:59** — no
activity in 4 days. 56.7 MB RAM, 0.00 % CPU, 63 MB anonymous volume, and it
publishes **`0.0.0.0:55432`**.

### Volumes — 65.2 MB total; the durable state is *not* here

| Volume | Size | Used by |
| --- | --- | --- |
| `1837800ff3b5…` (anonymous) | 63 MB | `lane_b_pg_test` |
| `acx-prod_acx_blobs` | 252 K | prod api + worker |
| `acx-backend_caddy_data` / `_config` | 216 K / 16 K | caddy |
| `acx-dev_acx_blobs` | 12 K | dev api + worker |
| `prod_caddy_data` / `_config` | 76 K / 16 K | **UNUSED** |

The two dangling volumes are orphans of a retired compose project literally
named `prod`, superseded by `acx-backend` / `acx-prod`. 92 KB, so cosmetic —
but they are the fingerprint of a project rename that was never cleaned up.

**A docker-only audit misses the actual state**, which lives in bind mounts
under `/opt/acx-backend/data` (2.4 GB) and is excluded from `docker system df`:

| Path | Size |
| --- | --- |
| `dev-models` / `prod-models` / `staging-models` | **601 MB each** (`insightface` + `matplotlib` caches; 8 / 8 / 7 files) |
| `demo-wpdata` | 178 MB |
| `demo-dbdata` | 174 MB |
| `prod-pgdata` | 150 MB |
| `dev-pgdata` / `staging-pgdata` | 70 MB / 69 MB |
| **`prod-pgdat`** | 4 K — empty, see [F2](#f2) |

## Findings

Ordered by what I would act on first, not by size.

### F1 — `lane_b_pg_test`: leaked test fixture publishing postgres on `0.0.0.0`
**Severity: posture** · **Owner: alt-context**

A hand-started `pgvector/pgvector:pg17` container, idle 4 days, with
`--restart no` and no compose ownership, binding **`0.0.0.0:55432`** rather than
`127.0.0.1`. Space (63 MB volume + 56 MB RAM) is the least interesting part; an
unowned test database reachable on every interface of a host that also serves
prod is the finding. Nothing will ever reap it — there is no owner.

```bash
docker rm -f lane_b_pg_test && docker volume prune -f
```

Follow-up: whatever harness starts `lane_b_*` fixtures should bind
`127.0.0.1:` and set a teardown trap, so an interrupted run cannot leave a
listener behind.

### F2 — `prod-pgdat`: a typo'd bind-mount path that is a latent data hazard
**Severity: latent** · **Owner: alt-context**

`/opt/acx-backend/data/prod-pgdat` — empty, `root:root`, created
2026-04-22 02:02, referenced by **no** container (`prod-pgdata` is the real
one, 150 MB). Harmless today. But a compose file that ever points a postgres
service at this path gets a **silently initialized empty database** instead of
a failure. Delete it so it cannot be re-hit:

```bash
sudo rmdir /opt/acx-backend/data/prod-pgdat
```

Worth a grep of the compose files for `pgdat` to confirm no variant survives.

### F3 — no image/build-cache retention policy
**Severity: medium (recurring)** · **Owner: alt-context**

The build cache had reached **8.399 GB with zero active records** before it was
pruned during this audit; it will grow back. Images accumulate two tags per
build with no expiry. The retention rule this repo needs is **count-based on
the rollback aliases**, not age-based on all images:

- keep the newest *N* (suggest 5) `rollback-*` tags, drop older ones;
- retire a whole superseded base generation once no tag in it is in service;
- `docker builder prune -af` on a schedule (it reclaimed ~9 GB here at zero
  risk — no active cache records, no container impact).

Tracked as [`docs/tech-debt/OPS-1-vm-host-retention-hygiene.md`](../tech-debt/OPS-1-vm-host-retention-hygiene.md).

### F4 — `/home/ubuntu` (39 GB) is the largest consumer and nothing reaps it
**Severity: medium** · **Owner: alt-context**

| Path | Size |
| --- | --- |
| `vlm2b` | 12 G |
| `.cache` | 6.0 G |
| `ComfyUI` | 4.4 G |
| `.grok` | 2.9 G (a second grok session store, separate from `gate`'s) |
| `data` | 2.2 G |
| `fx31` / `fx30` / `cvup1-rev3` / `flock30` / `planreview13` / `planreview12` | **6.1 G combined** |
| `.cursor-server` / `.npm` | 659 M / 514 M |

The six scratch/worktree clones (6.1 GB) are the reapable part if those tasks
are closed. `~/.grok` and `~/.cache` here are the same classes that the workbay
lane reaper handles under `~gate` — with no equivalent on the `ubuntu` side.

### F5 — three duplicate 601 MB model caches
**Severity: low** · **Owner: alt-context**

`dev-models`, `prod-models`, `staging-models` are 601 MB each and hold the same
`insightface` + `matplotlib` caches (8 / 8 / 7 files — near-identical, not
byte-identical). Roughly **1.2 GB is duplication** that a single shared
read-only bind mount would collapse. Verify content equality before merging;
the file-count difference means they have drifted.

### F6 — 8.8 GB of workbay lane sandboxes that no reaper can ever see
**Severity: medium (recurring)** · **Owner: this repo**

`~gate/grok-sandbox` holds 358 directories / 12 GB. Split by whether the
workbay marker-gated sweep can see them:

| Class | Count | Size | Reaped? |
| --- | --- | --- | --- |
| Marked (`.workbay-lane-sandbox` present) | 46 | ~3 G | yes — 48 h TTL, **0 past due** |
| **Unmarked** | **312** | **8.8 GB** | **never** |

Cause: this repo carries an **untracked, vendored fork** of
`scripts/remote_agent.sh` (dated 2026-07-22) that writes into the *same*
`AGENT_ROOT=grok-sandbox` as workbay but never writes the
`.workbay-lane-sandbox` marker and has no sandbox TTL logic. The workbay sweep
is deliberately marker-gated (so it can never delete an operator directory), so
these are invisible to it permanently. Attribution is unambiguous — the
unmarked directories carry this repo's branch names (`feature-fir-7-…`,
`feature-fir-9-…`, `feature-cvup-1-…`, `colour-c1-…`, `feature-wbux-5-…`, plus
a `HEAD-…`), at 600–900 MB each.

The same fork also defaults `MAX_LANES=3` while workbay now defaults to 20 on a
shared scope namespace — a cap split-brain. Full detail and fix options:
[`docs/tech-debt/OPS-2-vendored-remote-agent-fork.md`](../tech-debt/OPS-2-vendored-remote-agent-fork.md).

### F7 — journal and apt cache: one-time reclaim, needs root
**Severity: low** · **Owner: system**

`/etc/systemd/journald.conf` sets **nothing**, so journald is at its default
ceiling — `min(10 % of fs, 4 G)` — and `/var/log/journal` is sitting at exactly
3.9 G. **This is capped, not leaking.** Reclaimable once:

```bash
sudo journalctl --vacuum-size=512M     # ~3.4 G; then set SystemMaxUse=512M
sudo apt clean                         # 446 M
```

### F8 — repo artifact: a mangled `scp` target committed to the working tree
**Severity: trivial** · **Owner: this repo**

The repo root contains an untracked directory literally named
`ubuntu@acx-backend.tail1a44b8.ts.netanes/` (holding `wx01`, `wx02`, `wx03`,
created 2026-07-30 12:12) — an `scp`/`rsync` invocation missing the `:` after
the host, so the remote target became a local path. Safe to delete after
checking the three `wx*` directories are not the only copy of something.

## What is already correct — do not "fix" these

Verified working; changing them would be a regression:

- **Container logs are bounded.** `/etc/docker/daemon.json` sets
  `json-file` with `max-size 10m`, `max-file 3`.
- **`/tmp` *is* reaped.** `systemd-tmpfiles-clean.timer` is active and
  `/usr/lib/tmpfiles.d/tmp.conf` says `D /tmp 1777 root root 30d`. That is why
  2 004 entries older than 7 days survive — the horizon is 30 days, not 7. The
  1.4 GB currently older than 10 days (`phpstan` 1.8 G, `atlas-umap-probe`
  503 M, `codex-help-probe` 426 M, `node-compile-cache` 327 M, `wb-test-venv`
  323 M, `codex-bin` 305 M) clears on its own around 2026-08-21…27.
- **journald is capped** at its 4 G default (F7 is a one-time reclaim, not a
  leak).
- **The workbay lane reapers are healthy** on everything they can see: 46
  marked sandboxes with none past the 48 h TTL, 33 lane venvs against a cap of
  32 with no half-pairs (33 venvs / 33 sync stamps), dispatch transients under
  the 24 h TTL, and 0 leaked lane refs.

## Structural note

Every reaper on this host is either **dispatch-triggered** (the workbay ones —
they run as a side effect of a lane pass, so they stop when lane traffic stops)
or **absent** (docker images, `/home/ubuntu`, the `ubuntu` account's caches).
`gate` has **no crontab** and no usable `sudo`, so it cannot own host-wide
hygiene even in principle.

The gap is a single **root-owned `systemd` timer** — it needs root, and it must
run whether or not lanes dispatch. See
[`OPS-1`](../tech-debt/OPS-1-vm-host-retention-hygiene.md).

## Cleanup executed 2026-08-04 (~18:30 UTC)

The block below was run. Result: **100 GB → 93 GB used, 100 GB free** (from
108 GB used at the start of the audit).

| Action | Reclaimed | Verified |
| --- | --- | --- |
| `docker builder prune -af` | **~9 GB** | build cache 0 records |
| `docker rmi` ×3 (F3 top offenders) | **2.19 GB** | images 41 → 38 IDs, 13.45 → 11.26 GB — matches the ~2.2 GB unique-layer prediction exactly |
| `docker rm -f lane_b_pg_test` + `volume prune -f` (F1) | 64.95 MB | containers 13 → 12, volumes 7 → 6 (65.2 MB → 253 kB), `0.0.0.0:55432` closed |
| `sudo rmdir …/prod-pgdat` (F2) | — | typo dir gone |
| `sudo journalctl --vacuum-size=512M` (F7) | **3.4 GB** | journal 3.9 G → 481 M |
| `sudo apt clean` (F7) | 446 MB | `/var/cache/apt` 40 K |

Service verification after: **12/12 containers running, 0 unhealthy, 0
restarting**, caddy answering (`308` → HTTPS redirect, expected). No image
removed was referenced by a container; `:dev`, `:latest`, `:staging` untouched.

**Deliberately not done:**

- **197 of the 312 unmarked sandboxes (F6) hold a commit beyond the synthetic
  base** — census run 2026-08-04. Each may be the only copy of lane work that
  died before harvest, so none were touched. 115 are base-only and safe to
  reclaim via the marker-backfill route in
  [`OPS-2`](../tech-debt/OPS-2-vendored-remote-agent-fork.md).
- `/home/ubuntu` scratch clones (F4, 6.1 GB) — needs the owner's call on whether
  those tasks are closed.
- Duplicate model caches (F5, ~1.2 GB) — needs a content-equality check first;
  the file counts differ.
- `~gate/.npm` + `~gate/.cache/pip` (817 MB) — trivially safe, still pending.

## Ready-to-run reference

The commands as run, for the next time.

```bash
H=ubuntu@acx-backend.tail1a44b8.ts.net

# 2.2 GB from three images — leaves the rollback tag history intact
ssh $H 'docker rmi \
  iad.ocir.io/idu2kqqe2jxy/acx-backend:rollback-c13e28fc \
  iad.ocir.io/idu2kqqe2jxy/acx-backend:74b4ec400bc6b39519a361725b6eb3ca25b9d600 \
  wordpress:cli-2.11-php8.3'

# F1 — leaked fixture, 63 MB + closes 0.0.0.0:55432
ssh $H 'docker rm -f lane_b_pg_test && docker volume prune -f'

# F2 — remove the typo trap
ssh $H 'sudo rmdir /opt/acx-backend/data/prod-pgdat'

# F7 — ~3.8 GB one-time
ssh $H 'sudo journalctl --vacuum-size=512M && sudo apt clean'

# recurring, zero risk (schedule it — see OPS-1)
ssh $H 'docker builder prune -af'
```

Total realistically available: **~10 GB immediately** (images + journal + apt +
fixture), plus **8.8 GB** once F6 is resolved, plus **6.1 GB** if the
`/home/ubuntu` scratch clones in F4 are closed out. The box currently has 94 GB
free, so none of this is urgent — but only the workbay-side items are
self-limiting today.

## Adjacent observation: a second A10 was running unreaped

Not part of the disk audit, but found while answering the billing question the
same day, and it contradicts the *"anything else non-terminated in the tenancy
is unexpected — investigate"* line in
[`oci-instance-state-and-cost.md`](../runbooks/oci-instance-state-and-cost.md).

On 2026-08-04 the tenancy held **two** `VM.GPU.A10.1` instances in
`us-ashburn-1` (the only subscribed region):

- `acx-gpu-burst` — `STOPPED`, behaving as the runbook describes.
- `acx-gpu-smoke-20260728-0218` (`role=gpu-smoke-ephemeral`, `owner=wanlora`) —
  **`RUNNING` for 173 h** since 2026-07-28. Nothing reaped it despite the
  "ephemeral" role tag; `scale_to_zero` is absent on smoke instances. It was
  stopped between 07:43 and 07:56 UTC on 2026-08-04.

The lesson for the runbook: `scale_to_zero` automation on the *burst* instance
creates a false impression that GPU spend is self-limiting. Hand-created
smoke/one-off instances have no reaper. Answer GPU-billing questions from the
**full instance list plus Cost Analysis**, never from one named instance — and
note that a `STOPPED` A10 still bills its 400 GB boot volume.
