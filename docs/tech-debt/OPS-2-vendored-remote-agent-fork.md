# Tech Debt: OPS-2 vendored `remote_agent.sh` fork on the shared VM (deferred)

**Status:** deferred · **Owner:** this repo (the fork is ours) · **Origin:** host disk audit, 2026-08-04 — [`docs/operations/acx-backend-host-disk-audit-2026-08-04.md`](../operations/acx-backend-host-disk-audit-2026-08-04.md) finding F6

## What was deferred

Reconciling this repo's **untracked, vendored copy** of
`scripts/remote_agent.sh` (dated 2026-07-22 22:29, no git history) with the
upstream workbay version that now runs on the *same* VM under the *same*
sandbox root.

Three divergences, in order of consequence:

### 1. It leaks sandboxes that no reaper can ever see — 8.8 GB and growing

Both copies default to `AGENT_ROOT=grok-sandbox`, so both write into
`~gate/grok-sandbox` on `acx-backend`. Upstream writes a
`.workbay-lane-sandbox` marker file into every sandbox it creates and its sweep
is **marker-gated** — deliberately, so it can never delete an operator
directory it did not make. Our fork writes no marker and has no sandbox TTL
logic at all, so its sandboxes are invisible to that sweep **permanently**.

Measured 2026-08-04:

| Class | Count | Size | Reaped? |
| --- | --- | --- | --- |
| Marked (upstream) | 46 | ~3 G | yes — 48 h TTL, **0 past due** |
| **Unmarked (ours)** | **312** | **8.8 GB** | **never** |

Attribution is unambiguous: the unmarked directories carry this repo's branch
names — `feature-fir-7-…`, `feature-fir-9-…`, `feature-cvup-1-…`,
`colour-c1-…`, `feature-wbux-5-…`, plus a `HEAD-…` — at 600–900 MB each. They
span every age bucket from 0 to 8 days, so this is an active leak, not a
historical backlog that will drain.

### 2. Cap split-brain on a shared scope namespace

Our fork defaults `MAX_LANES=3`; upstream now defaults to **20**. Both count the
same `grok-lane-*` systemd scopes on the same host. So whenever upstream is
running ≥ 3 lanes, **every dispatch from this repo defers with exit 75** even
though the VM has capacity. The failure is graceful (a retryable defer, not a
crash) which is exactly why it can go unnoticed as "the remote gate is slow".

### 3. Missing hardening

The fork predates the current lane lease / lock / mem-floor work. It has no
`SANDBOX_TTL_SEC` and no `DISPATCH_TTL_SEC`; assume it is missing other
same-branch-collision and backpressure fixes too until diffed.

## Why it's safe to defer

- **The leak is bounded in practice and the box is not full** — 8.8 GB on a
  filesystem with 94 GB free.
- **The cap split-brain fails safe.** Exit 75 is a retryable defer; no work is
  lost or corrupted, dispatches just wait.
- **Nothing is silently wrong with results.** The fork produces correct patches;
  what it fails to do is clean up after itself and share the host fairly.
- The fork is untracked, so it is not drifting further with every commit — it is
  frozen at 2026-07-22.

## Trigger to pick up

Any of:

- the next time a remote dispatch from this repo defers unexpectedly (that is
  symptom #2, and it will look like an unrelated outage), or
- `~gate/grok-sandbox` passes ~15 GB, or
- upstream `remote_agent.sh` gains a fix this repo needs — at which point
  re-vendoring a second time is strictly worse than resolving the fork.

## Acceptance criteria

Pick **one** of two resolutions and record which:

**(A) Retire the fork (preferred).** Dispatch this repo's lanes through the
upstream `remote_agent.sh` from `agentic-protocol-monorepo`, so marker writing,
the 48 h sandbox TTL, the lane lease/lock, and one shared lane cap all come for
free. Delete `scripts/remote_agent.sh` from this repo. Verify a dispatch
produces a sandbox that *does* contain `.workbay-lane-sandbox`.

**(B) Isolate it.** If the fork must stay, set
`WORKBAY_REMOTE_AGENT_ROOT=grok-sandbox-altcontext` so its leak is confined to
one truncatable directory, and align `MAX_LANES` with upstream so the two
consumers do not starve each other on the shared scope namespace. Document that
its root has no reaper.

**Either way, reclaim the existing 8.8 GB safely.** Do not blanket
`rm -rf` — the sandbox is the only copy of any lane work that died before
harvest. The census below was run on 2026-08-04 and shows why this matters:

| Class | Count | Action |
| --- | --- | --- |
| Base commit only (nothing to lose) | **115** | safe to reclaim |
| **Commits beyond the base** (2, one with 3) | **197** | **hold** — may be unharvested lane output |

The 197 include whole review fleets (`review-libsyn1-l1…l6`, `review-ct8-r1…r3`,
`toc-g1…g5`, `lane-remap-*`). A commit in the sandbox means the lane *did* work;
whether the patch was fetched back to the host is not knowable from the sandbox
alone. Treat them as evidence until each is matched against a harvested patch.

Two acceptable routes for the 115:

1. **Marker backfill (preferred):** write `.workbay-lane-sandbox` with an old
   mtime into each unmarked directory whose sandbox git tree holds *only* the
   synthetic base commit, then let the existing, tested 48 h sweep reclaim them
   — this keeps the live-lease and lane-lock fail-safes in the deletion path.
2. **Manual, after checking for unharvested commits:**

   ```bash
   ssh gate@acx-backend.tail1a44b8.ts.net '
     for d in ~/grok-sandbox/*/; do
       [ -f "$d/.workbay-lane-sandbox" ] && continue
       n=$(git -C "$d" rev-list --count HEAD 2>/dev/null || echo 0)
       [ "$n" -gt 1 ] && echo "$n  $d"
     done'
   ```

   Anything printed has commits beyond the sandbox base and must be harvested
   or consciously abandoned first. Only the silent ones are safe to remove.

## Also parked here (adjacent, trivial)

- The repo root holds an untracked directory literally named
  `ubuntu@acx-backend.tail1a44b8.ts.netanes/` (contains `wx01`, `wx02`, `wx03`;
  created 2026-07-30 12:12) — an `scp`/`rsync` invocation missing the `:` after
  the host, so the remote target became a local path. Delete after confirming
  the three `wx*` directories are not the only copy of something.
