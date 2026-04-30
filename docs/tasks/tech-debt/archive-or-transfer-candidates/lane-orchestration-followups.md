# Tech Debt: Lane Orchestration Follow-Ups

> **Created:** 2026-04-08
> **Source:** Lane orchestration improvements slice on `feature/lane-orchestration-improvements`
> **Status:** Open
> **Priority:** Low (background cleanup)

This file tracks loose ends from the lane orchestration improvements landed in
decision `cdx_slice_complete_LANE-ORCH_initial_5_slices` (decision id pending).
None of these block merges or releases on their own; they accumulate friction
over time and should be triaged in the next quiet cycle.

---

## 1. Session-bleed working-tree stash

**Where:** `git stash@{0}` on `main`, labeled
`session-bleed accumulated working-tree at codex/e15-7-plan-fixes pre-merge stash 2026-04-08`.

**What:** Approximately 17 modified files plus 4 untracked files that
accumulated in the root worktree across multiple prior sessions and tasks
(BUG-401 auth fix, AHMCP-8 task plan, planning doc edits, hook tweaks, test
mods). The files were stashed before the merge train so the root worktree
could be checked out to `main` cleanly.

**Why it is debt:** The stash contains a mix of work from multiple unrelated
tasks. Each modified file needs to be triaged into the right destination:
some are already obsolete (overlapped by merged commits), some belong on a
new feature branch, some are hook/doc edits that can land on `main` directly.

**Triage procedure:**

```bash
# Inspect contents
git stash show -p stash@{0} | less
git stash show --stat stash@{0}

# Selectively recover files known to belong somewhere
git checkout stash@{0} -- path/to/file1 path/to/file2

# Or apply everything for triage (may conflict with new main; resolve manually)
git stash apply stash@{0}

# Or drop if all content is obsolete or already-merged
git stash drop stash@{0}
```

**Do NOT auto-pop:** the files predate `main` HEAD `db95a4e8`. Several of them
will conflict with the local-sync, AOMCP-1, and E15-7 work that has since
landed.

**Acceptance:** the stash entry is either dropped or the unique work has been
re-committed against `main`.

---

## 2. Long-lived stale feature branches

**Where:** Three branches in `refs/heads/` that pre-date the current line of
development by 100+ commits each. None has a linked worktree.

| Branch | Commits ahead of main | Last activity | Notes |
|---|---|---|---|
| `feature/edit-clusters` | 289 | older | Looks like an early cluster-editing prototype |
| `feature/face-detection-foundation` | 162 | older | Face detection scaffolding from before the recognition service rewrite |
| `feature/hybrid-roster` | 205 | older | Hybrid roster experiment |

**Why it is debt:** As more feature work comes down the pipeline, these
unmaintained refs make `git branch -a`, `git log --all`, and tab-completion
noisier. They are also prime candidates for accidental rebase / merge
conflicts because their fork points are very old.

**Recommended disposition:**

1. **Archive as tags first** (preserves history without keeping a movable ref):
   ```bash
   git tag archive/edit-clusters feature/edit-clusters
   git tag archive/face-detection-foundation feature/face-detection-foundation
   git tag archive/hybrid-roster feature/hybrid-roster
   ```

2. **Then delete the branch refs:**
   ```bash
   git branch -D feature/edit-clusters feature/face-detection-foundation feature/hybrid-roster
   ```

3. **Push the tags to origin** (so other clones can still find them):
   ```bash
   git push origin archive/edit-clusters archive/face-detection-foundation archive/hybrid-roster
   git push origin --delete feature/edit-clusters feature/face-detection-foundation feature/hybrid-roster
   ```

**Acceptance:** the three feature branches are converted to `archive/*` tags
and the original refs are deleted both locally and on origin. If any of the
branches is later determined to contain work that should land on `main`,
recover it from the tag and cherry-pick the relevant commits.

---

## 3. Pre-existing v2-envelope mirroring test failure

**Where:** `packages/agent-handoff-mcp/tests/test_handoff_state.py::test_v2_envelope_no_legacy_mirroring`

**What:** The test asserts that the v2 response envelope no longer mirrors
fields from `data` to the top level (e.g. `active`, `limits`, `findings_open`).
The current implementation still mirrors these fields, so the test fails.

**Why it is debt:** This is pre-existing — it was failing before the lane
orchestration improvements slice, and the lane orchestration changes do not
touch the envelope wrapper. It is documented here so it does not get blamed on
the wrong slice in the future.

**Recommended fix:** Either (a) trim the legacy mirroring from `_envelope()`
in `_shared.py` and update the few in-process callers that still read top-level
keys, or (b) update the test to allow the mirrored shape until a deliberate
v3 envelope cleanup. Option (a) is the cleaner finish-line for the AHMCP-7
envelope optimization slice.

**Acceptance:** the test is either green at HEAD or explicitly marked
`@pytest.mark.skip(reason="...")` with a follow-up task ref.

---

## 4. Placeholder worktrees with no active work

**Where:** Three linked worktrees that exist but have 0 commits ahead of
`main` and no uncommitted work as of 2026-04-08.

| Worktree | Branch | Notes |
|---|---|---|
| `context-alt-text-monorepo-ahmcp-mem0` | `feature/ahmcp-mem0-feature-candidates` | Scratch space for mem0 feature exploration |
| `context-alt-text-monorepo-branch-isolation` | `feature/branch-isolation-guardrails` | Branch isolation hook work; guardrails are already in main |
| `context-alt-text-monorepo-e16-planning` | `feature/e16-sync-completion-retention-hardening` | E16 epic planning workspace |

**Why it is debt:** They consume disk space and add noise to `git worktree
list`. If they are intentional planning surfaces, they should be documented
in the relevant task plan or epic file and given a clear lifecycle.
Otherwise, they should be removed.

**Recommended disposition:** for each worktree, either (a) commit a stub
docs file that explains the planning intent and check it in, or (b) remove
the worktree:

```bash
git worktree remove /Users/daniel/Development/context-alt-text-monorepo-ahmcp-mem0
git worktree remove /Users/daniel/Development/context-alt-text-monorepo-branch-isolation
git worktree remove /Users/daniel/Development/context-alt-text-monorepo-e16-planning
git worktree prune
git branch -d feature/ahmcp-mem0-feature-candidates feature/branch-isolation-guardrails feature/e16-sync-completion-retention-hardening
```

**Acceptance:** each worktree is either committed-and-documented or
removed-and-its-branch-deleted. No more "0-ahead clean placeholder" entries
in `git worktree list`.

---

## Cross-references

- Lane orchestration improvements slice: `feature/lane-orchestration-improvements`
- Worktree dev path proposal: see decision `cdx_slice_complete_INVEST-LOCAL-SYNC_merge_train_to_main_db95a4e8`
- Branch isolation rule: [CLAUDE.md § Branch Isolation Rule](../../../CLAUDE.md#branch-isolation-rule)
- Pre-merge gate: [development-workflow.md § Pre-Merge Gate](../../agentic/rules/development-workflow.md#pre-merge-gate-mandatory)

## Consolidated Triage Checklist (2026-04-30)

**Disposition:** Transfer/archive candidate; this is agentic workflow/MCP process debt, not app tech debt.
**Evaluation basis:** Current `main` agentic workflow surfaces and external MCP package ownership.

- [ ] Inspect the historical session-bleed stash and either recover unique work or drop obsolete content.
- [ ] Verify whether the three stale feature branches still exist; archive them as `archive/*` tags before deleting live branch refs if they do.
- [ ] Re-check the v2 envelope mirroring failure against the current external MCP package scope; move it to the owning external repo or `/Users/daniel/Development/agentic-protocol-monorepo/docs` if still relevant.
- [x] Placeholder worktrees named in this document were not present in the current `git worktree list` output; treat that item as resolved unless they reappear.
- [ ] Archive this monorepo copy once the stash/branch cleanup is resolved and any MCP-envelope item is transferred to the agentic protocol surface.
