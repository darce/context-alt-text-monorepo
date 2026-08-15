# `acx-backend` host disk audit + reclaim, 2026-08-12

**Task:** `MAINT-oci-disk-hygiene-20260812` · **Host:** `acx-backend.tail1a44b8.ts.net` (aarch64, 4 vCPU, 23 GB RAM, 193 GB root)
**Predecessor:** [`acx-backend-host-disk-audit-2026-08-04.md`](acx-backend-host-disk-audit-2026-08-04.md) · **Tech debt:** [`OPS-1`](../tech-debt/OPS-1-vm-host-retention-hygiene.md)

**OPS-1's documented trigger fired.** That item said to pick it up when free space on `/`
drops below ~40 GB. It reached **31 GB free (85% used)** — down from the 94 GB the
2026-08-04 audit recorded, i.e. **63 GB consumed in eight days.**

## Origin: GitHub Actions minutes exhaustion

This audit started from an unrelated alert — the `darce` account hit 100% of its 2,000
included Actions minutes — and the two turned out to share a root cause: **agent lane
sprawl with no scheduled reaper.**

Actions burn is **not** in this repo (9 runs, ~5 min all month). It is
`darce/agentic-protocol-monorepo`'s `tests` workflow:

| Metric | Value |
| --- | --- |
| Runs since Aug 1 | 111 |
| Conclusion | **111 failure, 0 success** |
| Jobs per run | 11 parallel |
| `workbay-bootstrap` job | ~16 min/run (7 serial `pip install -e`, cache key `**/pyproject.toml` rarely hits) |

`16 min × 111 ≈ 1,700 min` from that one job, plus ~10 min/run of per-job minute
rounding across the other ten. That is the entire budget, spent on a 100%-red workflow.
Live failures: `format` (ruff drift), `workbay-protocol` (`ModuleNotFoundError: fastmcp`),
`mcp-workbay-orchestrator` (editable-origin vs cwd mismatch).

Migration options are recorded in "Follow-ups" below.

## Reclaim executed

`163 G used / 31 G free (85%)` → **`143 G used / 51 G free (74%)`. 20 GB reclaimed.**
Services verified `active` and `prod_health=200` after every stage.

| Item | Freed | Basis |
| --- | --- | --- |
| Docker build cache | 4.7 G | zero active records; regenerates |
| Docker images >21d unused | 5.3 G | 39 images → 8 — **see regression below** |
| grok session transcripts >14 d | 4.1 G | 22,273 files; 5.1 G of recent retained |
| `swift-6.0.3` toolchain | 2.5 G | unreferenced by any profile/PATH; re-downloadable |
| `uv cache prune` (gate + ubuntu) | 3.3 G | unused entries only; live venvs untouched |
| `lane-distil-*` sandboxes ×10 | 1.2 G | verified `ahead=0 dirty=0`; unmarked ⇒ unreapable class |
| gate `.grok/logs` (incl. 0.6 G `hooks.log`) | 0.6 G | rotated |

Deliberately retained: `ComfyUI` 9.8 G, `vlm2b/models` 2.8 G (VLM bake-off),
`data/open-images` 2.2 G (bake-off inputs).

Two of those were re-checked on 2026-08-15. `ComfyUI` is a **live service** — pid
2161461, `python main.py --listen 127.0.0.1 --port 8188 --cpu`, up since Jul 28, bound
on `127.0.0.1:8188`; do not reclaim it. `vlm2b` is **not** active: models and logs are
dated Jul 7, `bench.sh` Aug 4, no llama/vlm/qwen process is running, and no shell script
or systemd unit references it. Its 2.8 G (`Qwen3VL-4B-Instruct-Q4_K_M.gguf` +
`mmproj-Qwen3VL-4B-Instruct-Q8_0.gguf`) is reclaimable and re-downloadable.

**`vlm2b` deleted 2026-08-15** on operator instruction (`54 G → 57 G` free, 71%).
`models/` 2.8 G and `bin/` 31 M (a local llama.cpp aarch64 build) are gone; both are
rebuildable or re-downloadable. `logs/` and `bench.sh` — the bake-off measurement record
— were archived first to `/home/ubuntu/vlm2b-bench-logs.tgz` (16 K) and kept.

## Regression: OPS-1's documented trap was tripped

OPS-1 warned in writing that `docker image prune -a --filter until=<age>` is the wrong
automation and that the correct policy is **count-based on the `rollback-*` aliases**.
A `--filter until=504h` prune was run anyway. Outcome:

- **Rollback tag history collapsed from 23+ tags to 2** (`rollback-069e12c0e5d6`,
  `rollback-119696b08933`).
- It reclaimed 5.3 GB rather than OPS-1's predicted ~80 MB, because the image tree had
  grown a base generation since Aug 4 — the *magnitude* estimate aged out, but the
  *policy* judgement in OPS-1 was correct and should have been followed.
- Prune also **untagged `:latest` and `:dev`** while their containers kept running. No
  layer was lost (both survived under their `rollback-*` aliases), but the compose files
  reference those tags, so a `compose up` would have forced a re-pull. Restored by
  re-tagging from local image IDs — `:latest` → `069e12c0e5d6`, `:dev` → `119696b08933`
  — confirmed identical to the IDs the running containers already use.

**Unverified:** whether OCIR still holds the deleted `rollback-*` tags.
`docker manifest inspect` failed against `iad.ocir.io` (auth or absent — not
distinguished). Root has OCIR credentials in `/root/.docker/config.json`.
**Do not assume local rollback history is recoverable until this is confirmed.**

## Reaper coverage map

The offload-lane reaper **is implemented and correct** — `scripts/remote_agent.sh`,
tagged `[RES-07]`:

| Sweep | Knob | Default | Gate |
| --- | --- | --- | --- |
| EXIT trap (fast path) | — | always | this dispatch's transients |
| Per-dispatch transients | `DISPATCH_TTL_SEC` | 86400 (24 h) | age; backstop when trap misses |
| Per-lane sandboxes | `SANDBOX_TTL_SEC` | 172800 (48 h) | marker `.workbay-lane-sandbox` + live-lease + lane-lock |
| Warm venv LRU | `MAX_LANE_VENVS` | 24 | count cap |

Two other reapers exist and **do not touch host disk**: `ShallowSandbox.__exit__`
(`secure_sandbox.py:427`, local temp clone) and `lane_reclaim.py` (plan 0181), whose
docstring states it *"is a pure predicate: it never deletes directories."*
`make task-reap` operates on handoff DB rows.

Three structural gaps — all confirmed on-host, all consistent with the 2026-08-04
audit's "Structural note":

1. **Dispatch-triggered only.** Verified: zero crontabs for `root` / `ubuntu` / `gate`;
   only stock Ubuntu timers. No dispatch ⇒ no sweep, indefinitely.
2. **Unmarked directories are never reaped.** The sweep `continue`s on absent marker
   (`remote_agent.sh:1238`). 10 of 114 sandboxes had no `.workbay-lane-sandbox` and
   would have persisted forever — this is the `lane-distil-*` class cleaned by hand above.
3. **`/home/ubuntu` is outside `AGENT_ROOT` entirely.** ~17 GB of hand-rolled
   `lane-*` / `rev-*` / `fx*` clones that no reaper covers.

At audit time `grok-sandbox` (32 G) and gate's `.cache/uv` (20 G) were **correctly not
reclaimable**: all 104 marked sandboxes were <48 h old (the Aug 11–12 p0194 / VLM-6 /
OL01 burst) and the uv cache is hardlinked by their live venvs. Both collapse on their
own — but only if a dispatch fires to trigger the sweep.

## Held back at audit time, then deleted 2026-08-15: lane branches (~17 GB)

At audit time `/home/ubuntu`'s 13 lane clones were **not** deleted. Every branch was
local-only:

```
rev-rv1 fix/wi2   rev-rv2 fix/wg3   rev-rv3 fix/wf4   rev-rv4 fix/we5
lane-hx1 fix/wi1  lane-hx2 fix/we6  lane-gx1 fix/gx1  lane-gx2 fix/cx1
lane-gx3 fix/cx2  lane-gx4 fix/cx3  lane-gx5 fix/cx4  lane-gx6 fix/gx6
int-vlm6 integ/fx-wave
```

All returned `on_origin=0` with 98–221 commits ahead, against an `origin/main` current
as of 2026-08-11 — real divergence, not a stale ref. Per **rg-017** deletion at this
scale required triage and operator sign-off, so the audit deferred it.

### 2026-08-15 addendum — deleted after containment check

The operator removed all 13 clones on 2026-08-15 (free space `31 G → 54 G`, 73%). The
`on_origin=0` reading was against `origin/main`; it did not test containment in the
integration branch, which is where this work had actually landed. Re-checked afterwards:

- **12 of 13 tips verified contained.** Each lane HEAD (`48c10e6a e7d2ad51 b52f37f8
  e4b1f8d9 edf40bec aa0e4229 79d50cd6 44849df3 f731e430 b4b45a8d ec13279e 445412bb`)
  passes `git merge-base --is-ancestor <tip> 79d50cd6` **and** `... feature/vlm-6` on the
  laptop. `79d50cd6` is `int-vlm6`'s `integ/fx-wave`, fetched as `vm/fx-wave`. No commits
  lost.
- **The 12 branch *names* are gone.** Only `vm/fx-wave` and `vm/integ/fx-wave` exist as
  refs. The commits survive; `fix/wi2`-style names do not, and are not recoverable.
- **`fix/gx6` (lane-gx6) is unverified.** Its tip was never recorded and the clone is
  gone. It was a docs-only lane (`brief-gx6.md`: fix six unresolvable SHA citations
  surfaced by `scripts/check_lane_report_shas.py` after gx5 closed the HTML-comment
  loophole). `check_lane_report_shas.py` still reports **5 unresolved SHAs** in
  `.s2a/vlm6-r9a-report.md` on `feature/vlm-6`, so that work did **not** land. It is
  minutes of docs editing to redo — see follow-up 7.

Deleting before pushing was the wrong order and only escaped data loss because the
integration branch had already absorbed the work. Push, or verify containment against
the branch the work merges into, before the next teardown.

## Follow-ups

1. **Confirm OCIR rollback-tag recoverability** (blocks closing the regression above).
2. **Root-owned systemd timer** — OPS-1 acceptance criterion 1, now overdue. Must be a
   timer, not a dispatch hook, for gap 1. Should log count + bytes per class. Gate it on
   the *reapable* bytes it can identify, not on free space: a bare free-space threshold
   is a cause alarm, and it misfired here (of the 31 G-free reading, 52 G sat in
   `grok-sandbox` + gate's `uv` cache that would have collapsed on their own).
3. **Count-based image retention** — keep newest N (suggest 5) `rollback-*`; never touch
   `:dev` / `:latest` / `:staging` or an image a container references. OPS-1 criterion 2.
4. **Unmarked-directory fallback** in `remote_agent.sh` — age-gate on directory mtime
   when the marker is absent, or backfill markers on creation (gap 2).
5. **Reaper for `/home/ubuntu` lanes** or migrate them under `AGENT_ROOT` (gap 3).
6. **GitHub Actions**: fix the four `tests` failures, collapse the 11-job matrix to 2–3
   to kill per-job rounding, then either move to a self-hosted ARM64 runner on this host
   (zero billed minutes) or retire the workflow in favour of the existing remote gate —
   see [`remote-test-gate.md`](../runbooks/remote-test-gate.md). If a self-hosted runner
   is used: run it as a dedicated unprivileged user (this host runs prod), cap
   concurrency against 4 vCPUs, and **never** attach one to the public `darce/workbay`
   repo, where fork PRs would execute arbitrary code here.
7. **Redo the lost `fix/gx6` docs fix** — resolve the 5 SHA citations
   `scripts/check_lane_report_shas.py` still flags in `.s2a/vlm6-r9a-report.md` on
   `feature/vlm-6` (`2253cd7 4893e79 dc4c4cd 653e46e b2f76f2`), per the addendum above.
8. **Push or verify containment before teardown.** No lane clone is removed until its
   tip is either on a remote or proven an ancestor of the branch it integrates into.
   `on_origin=0` against `origin/main` is not that proof.
