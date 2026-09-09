# R9 remote-exec rescue — inventory only

Copied 2026-08-19 from gitignored `.task-state/remote-exec-*` into this worktree so a **local agent** can review. Do not treat coordinator harvest (decision `grok_vlm6_review_r9_pass_with_findings` / review_run `vlm6-review-r9-20260818`) as the review.

Subject commit: `84ef6832b60330d72be1d69e1870a8d5f546d541` on `feature/vlm-6`.
Worktree: `/Users/daniel/Development/context-alt-text-monorepo-vlm-6`.

## Packets

| Dir | Lane | Remote-exec source | What it is |
| --- | --- | --- | --- |
| `fx/` | `vlm6-fx` | `remote-exec-feature-vlm-6-s2hsdnx5` | Implement turn. `commit_landed` on the subject SHA. Includes `turn.patch` + `selfverify.json`. |
| `r9q1/` | `vlm6-r9q1` | `remote-exec-feature-vlm-6-r9q1-vtb_grw4` | Remote review: sealed-split / UnicodeDecodeError lens. `stopReason=Cancelled`. |
| `r9q2/` | `vlm6-r9q2` | `remote-exec-feature-vlm-6-r9q2-z7tbrji6` | Remote review: `--check` artifact lens. `stopReason=Cancelled`. |
| `r9q3/` | `vlm6-r9q3` | `remote-exec-feature-vlm-6-r9q3-oe6a_z3j` | Remote review: sibling unguarded-I/O lens. `stopReason=Cancelled`. |

Each dir has: `brief.md`, `result.json`, `result-text.md` (extracted `text`+`thought`), `spec.json`, `offload-pass.json`, `worker.status.json`, `debug.log`. `fx/` also has `turn.patch` and `selfverify.json`.

## How to review

1. `git show 84ef6832b` in this worktree.
2. Read `fx/turn.patch` + `fx/selfverify.json` against the tree.
3. Read each `r9q*/result-text.md` (then `debug.log` for TEST-15 traces).
4. Record findings yourself. Do not reuse coordinator-harvested RV9-* rows as authority.

Sources remain at `context-alt-text-monorepo/.task-state/` until that dir is GC'd.
