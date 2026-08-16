# Tech Debt: OPS-1 `acx-backend` host retention hygiene (TRIGGERED — no longer deferred)

**Status:** triggered 2026-08-12 · **Owner:** operator (root timer) + backend (retention policy) · **Origin:** host disk audit, 2026-08-04 — [`docs/operations/acx-backend-host-disk-audit-2026-08-04.md`](../operations/acx-backend-host-disk-audit-2026-08-04.md) findings F3, F4, F5, F7

> **2026-08-12 — the trigger below fired.** Free space hit **31 GB** (threshold: ~40 GB),
> 63 GB consumed in eight days. A hand reclaim recovered 20 GB; see
> [`acx-backend-host-disk-audit-2026-08-12.md`](../operations/acx-backend-host-disk-audit-2026-08-12.md)
> (task `MAINT-oci-disk-hygiene-20260812`).
>
> **The trap documented below was tripped during that reclaim.** An age-based
> `docker image prune -a --filter until=504h` was run despite this item warning against
> exactly that, collapsing rollback tag history from 23+ tags to 2 and transiently
> untagging `:latest` / `:dev`. Tags were restored from local image IDs; whether OCIR
> still holds the deleted `rollback-*` tags is **unverified**. Acceptance criteria 1 and 2
> are now overdue rather than deferred.

## What was deferred

A **root-owned scheduled hygiene job** on the always-on `acx-backend` VM, plus
the retention *policy* it would enforce. Today there is none, so four classes of
data grow without bound and are only ever reclaimed by hand:

1. **Docker build cache** — had reached 8.399 GB with *zero active records*
   before it was pruned during the audit. It will grow back.
2. **Docker images** — 41 unique IDs behind 67 tags, **0 dangling**, going back
   3 months. Every build lands two tags (the 40-hex git SHA *and* a
   `rollback-<image-id>` alias), so nothing is ever dangling and plain
   `docker image prune` is a guaranteed no-op.
3. **`/home/ubuntu` (39 GB)** — `vlm2b` 12 G, `.cache` 6.0 G, `ComfyUI` 4.4 G,
   `.grok` 2.9 G, plus **6.1 GB of lane/review scratch clones** (`fx31`, `fx30`,
   `cvup1-rev3`, `flock30`, `planreview13`, `planreview12`). No reaper.
4. **One-time root reclaims** — `journalctl --vacuum-size=512M` (~3.4 G, and
   set `SystemMaxUse=512M`; journald currently sits at its 4 G *default cap*,
   so this is a reclaim, not a leak fix) and `apt clean` (446 M).

## Why it's safe to defer

- **Not capacity-constrained.** After the audit's build-cache prune the box is
  at 99 GB used / **94 GB free** of 193 GB. Nothing is close to full.
- **The dangerous classes are already bounded.** Container logs are capped
  (`daemon.json`: `json-file`, `max-size 10m`, `max-file 3`); `/tmp` is reaped
  by `systemd-tmpfiles-clean.timer` per `D /tmp 1777 root root 30d`; journald is
  at its default ceiling. No unbounded writer threatens the root filesystem.
- **The prune that mattered most was zero-risk and is already done**
  (`docker builder prune -af`, ~9 GB, no container impact).
- Getting the *policy* wrong is worse than deferring it — see the trap below.

## The trap this item exists to avoid

The obvious automation is wrong. `docker image prune -a --filter until=336h`
looks like the fix, but:

- `system df` advertises **11.19 GB reclaimable**; the true figure is
  **~2.29 GB**, because the unused tags share a base layer that `:dev`,
  `:latest`, and `:staging` pin in place.
- **~2.2 GB of that 2.29 GB is in three images** —
  `acx-backend:rollback-c13e28fc` (1.10 GB unique),
  `acx-backend:74b4ec400bc6…` (901 MB unique), and
  `wordpress:cli-2.11-php8.3` (185 MB unique).
- The other **31 unused tags total ~80 MB combined** (1–4 MB unique each).

So an age-based blanket prune destroys the entire rollback tag history to
reclaim about 80 MB. The correct policy is **count-based on the rollback
aliases**.

## Trigger to pick up

Any of:

- free space on `/` drops below ~40 GB (currently 94 GB), or
- a deploy needs the rollback tag list to be navigable rather than 23 entries
  deep, or
- the next time someone has to hand-run a prune to make room — that is the
  second occurrence and the signal to automate.

## Acceptance criteria

1. A root-owned `systemd` timer on `acx-backend` (daily) that runs, idempotently
   and fail-open:
   - `docker builder prune -af`;
   - the image retention rule below;
   - `journalctl --vacuum-size=512M` and `apt clean`;
   - `uv cache prune` and a TTL sweep of `~/.grok/{sessions,logs}` for **both**
     `gate` and `ubuntu`.
   It must be a *timer*, not a hook on deploy or lane dispatch — see
   "Structural note" in the audit: every existing reaper on this host is
   dispatch-triggered and therefore stops when traffic stops, and `gate` has no
   crontab and no usable `sudo`.
2. **Image retention is count-based:** keep the newest *N* (suggest 5)
   `rollback-*` tags and drop older ones; retire a whole superseded base
   generation once no tag in it is in service. Never delete an image referenced
   by a running container, and never delete `:dev` / `:latest` / `:staging`.
3. `SystemMaxUse=512M` set in `/etc/systemd/journald.conf`.
4. The timer logs what it removed (count + bytes per class). A silent sweep
   reads as "nothing to do" when it is actually broken.
5. Re-run the audit commands and confirm the classes above are bounded across
   two consecutive timer firings.

## Also parked here (adjacent, low)

- **Three duplicate model caches** (audit F5): `dev-models`, `prod-models`,
  `staging-models` under `/opt/acx-backend/data` are 601 MB each holding the
  same `insightface` + `matplotlib` caches — ~1.2 GB of duplication a single
  shared read-only bind mount would collapse. File counts differ (8 / 8 / 7), so
  confirm content equality before merging them.
- **Two orphan volumes** `prod_caddy_config` + `prod_caddy_data` (92 KB total)
  left behind when the compose project `prod` was renamed to
  `acx-backend` / `acx-prod`. Cosmetic, but the fingerprint of an uncleaned
  rename.
- **Staging drift** (audit, Images section): `:staging` still resolves to a
  3-month-old image and `acx-staging-worker-1` has been up 3 months. Confirm
  that is intentional rather than a stalled deploy.
