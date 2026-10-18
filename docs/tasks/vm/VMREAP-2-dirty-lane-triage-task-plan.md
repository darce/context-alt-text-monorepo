# VMREAP-2. Deterministic dirty-lane triage in `reap-lane.sh`

**Epic**: E14 self-hosting (VM hygiene) · **Parent**: VMREAP-1 (landed `8cee604d`)
**Branch**: `feature/vmreap-2` · **Worktree**: `context-alt-text-monorepo-vmreap-2`

## Problem

The first M-16 sweep on `acx-backend` skipped ~30 lanes as `dirty working tree`
with no further detail. Triaging them took five operator round-trips of ad-hoc
shell (`git status --porcelain | cut -c1-2 | sort | uniq -c`, per-file lists,
diff sampling). The outcome was fully mechanical:

| Bucket | Lanes | Evidence | Verdict |
| --- | --- | --- | --- |
| lock-only | 76 | only `uv.lock` modified (version bump), `pyproject.toml` clean | regenerable, should not block |
| untracked-scratch | 12 | identical `??` cluster (`sis*`, `wr-probe*`, `ut-*.txt`, `src`) | peer review output, keep guarded, report once |
| tracked-edits | ~10 | distinct modified `packages/**` sources | genuine peer work, keep guarded |

Bespoke inference over the same evidence every week is the wrong layer. The
reaper already has the status output; it should classify and report.

## Scope

1. `has_blocking_dirty` classifies non-ignorable entries into
   `lock-only`, `untracked-scratch`, `tracked-edits` and exposes counts plus the
   first few tracked paths.
2. `lock-only` (every non-ignorable entry is a *modified* tracked `uv.lock` and
   no `pyproject.toml` is dirty) is not blocking. Deleted or added lock files,
   or any dirty `pyproject.toml`, stay `tracked-edits`.
3. Every dirty skip names its category:
   `SKIP <lane>: dirty working tree (untracked-scratch: 5 paths)` /
   `SKIP <lane>: dirty working tree (tracked-edits: 3 tracked, 2 untracked; e.g. a b c)`.
4. End-of-run `REAP TRIAGE` block (only when at least one dirty skip or
   lock-only lane was seen): one counts line, one line per non-empty category
   listing lanes, and one `shared_untracked` line naming untracked paths present
   in two or more skipped lanes so a peer review cluster is reported once.

Out of scope: any new force flag, changing archive semantics, touching peer
lanes. RES-07 and rg-017 hold: `untracked-scratch` and `tracked-edits` remain
guarded.

## Counter-case considered

An operator who ran `uv lock --upgrade` deliberately and did not commit loses
that regeneration when the lane is reaped. Accepted: the lock is a derived
artifact of a clean `pyproject.toml`, `uv lock` recreates it, and the archived
refs keep the committed state. If `pyproject.toml` is dirty the lane still
blocks, which is the case where the lock carries intent.

## Slices

- S1 red: `scripts/vm/tests/test_reap_lane.sh` cases for lock-only reap,
  lock+pyproject block, deleted lock block, untracked-scratch reason,
  tracked-edits reason with paths, `REAP TRIAGE` block with shared cluster,
  and no triage block on a clean sweep.
- S2 green: classifier, `skip_dirty` helper, triage accumulators and printer in
  `scripts/vm/reap-lane.sh` (bash 3.2, no associative arrays).
- S3 gate: remote gate run, adversarial review, close check, merge `--no-ff`.

## DAG

```
S1-red ──> S2-green ──> S3-gate(remote gate ∥ review-slice) ──> merge ──> operator reinstall (cron installer, idempotent)
```

## Verification

- `bash scripts/vm/tests/test_reap_lane.sh` (macOS: 6 flock skips expected)
- `bash scripts/vm/tests/test_install_reap_cron.sh`
- `bash scripts/remote_gate.sh run` from the worktree
- Operator: `bash ~/bin/reap-lane.sh --archive-to ~/lane-archive.git --all ~/grok-sandbox` dry run as `gate`, confirm the triage block matches the manual inventory above.
