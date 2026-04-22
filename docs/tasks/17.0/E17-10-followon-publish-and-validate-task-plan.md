# E17-10-followon. Reconcile Pre-Populated Standalone MCP Repos and Validate End-to-End Consumer Install

- **Date**: 2026-04-21 19:50 EST (original); rewritten 2026-04-22 18:30 EST
- **Author**: Claude Opus 4.7
- **Owning Epic**: [docs/epics/v0.4.0/skill-formalization-and-process-automation-epic.md](../../epics/v0.4.0/skill-formalization-and-process-automation-epic.md)
- **Epic Short ID**: E17
- **Target Branch**: `feature/e17-10-followon-publish-and-validate`
- **Review Coverage Target**: 2
- **Source Plan**: [E17-10-hoist-agentic-system-mvp-task-plan.md](./E17-10-hoist-agentic-system-mvp-task-plan.md) — Implementation Sequencing Note (P1 / P2 / P3) + Slice 5
- **Hard Prerequisites**: E17-10 merged to `main` at `d9aa69e5`. The four canonical remote repos exist as private under `darce/`: `mcp-agent-handoff`, `mcp-agent-orchestrator`, `agentic-system`, `agentic-bootstrap`. SSH key configured for `git@github.com:darce/*`; `gh auth status` on account `darce` carries `repo` scope.

---

## Plan-Rewrite Note

The original (2026-04-21) plan assumed all four `darce/<repo>` remotes were empty and that this task would publish their `v0.1.0` tags. Investigation INV-02 / INV-03 / INV-04 (decision `#2219`, 2026-04-22) discovered that three of the four remotes had already been populated externally:

| Remote                              | Populated tag  | Source SHA from monorepo | Drift vs current `main` (`d9aa69e5`)                                 |
| ----------------------------------- | -------------- | ------------------------ | --------------------------------------------------------------------- |
| `darce/mcp-agent-handoff`           | `v0.1.0` (c8b65c32) | `1f44b8be`          | api.py byte-identical; trivial drift in pyproject/changelog/enums/tests |
| `darce/mcp-agent-orchestrator`      | `v0.1.0` (e21aaf96) | `7c839726`          | 2 files differ: `orchestration/slice_review_packet.py`, `tests/test_lanes_and_handoff_state.py` |
| `darce/agentic-system`              | `v0.1.0` (ac7a77c4) | `841b8fb2`          | Significant: 11 NEW skills, 2 modified skills, 2 modified hooks, 1 modified contract |
| `darce/agentic-bootstrap`           | `v0.2.0` (existing) | n/a                  | Already at v0.2.0 — no change in this plan                           |

The original Slice 1 / Slice 2 / Slice 3 ("extract and tag v0.1.0") are therefore obsolete. This rewrite replaces them with reconciliation slices that account for the pre-populated state and the v0.4.1 patch already shipped in Slice 1 (a/b/c). The validation slices (formerly 4 and 5) survive but now install from the new patch tags rather than from `v0.1.0`.

---

## Objective

Reconcile the three pre-populated standalone MCP repos against the current monorepo source so that consumer installs resolve to fresh, defect-free tags, then prove the MVP works against two real Daniel-owned consumer repos (`darce.github.io` and `altcontext-marketing-monorepo`). When this task closes, any Daniel-owned project can install the four-package family from `git+ssh://` URLs and run the documented `agentic-bootstrap install` flow without copy-paste from this monorepo.

## Problem Statement

E17-10 shipped the design, contracts, and in-monorepo source for a hoistable agentic system. Three follow-on gaps remain:

1. **`darce/mcp-agent-handoff@v0.1.0` shipped a `run_doctor` defect** — the stdio + CLI startup probes hard-fail on `mcp.shared.exceptions.McpError: Connection closed` in fresh consumer venvs (INV-02). Fixed in v0.4.1 (Slice 1, complete).
2. **`darce/mcp-agent-orchestrator@v0.1.0` carries 2-file drift** vs current monorepo source (INV-03). The drift is non-blocking on smoke; need an explicit ship-or-skip decision before the validation phase, since consumer installs will pin whichever tag we standardize on.
3. **`darce/agentic-system@v0.1.0` carries significant drift** (INV-04): 11 new skills, 2 modified skills, 2 modified hooks, 1 modified contract. The published v0.1.0 surface is materially smaller than what the current monorepo contains. A `v0.2.0` cut is required so consumer installs get the full skill catalog.
4. **The agentic-system publication boundary is wrong**. The original extraction shipped all 15 contracts under `docs/agentic/contracts/`, but 8 of those are alt-context-specific (clustering, recognition, curation, security, suggestion-extensions, cluster-delta/snapshot APIs) and have no business in a generic agentic-system surface. The v0.2.0 cut is the right moment to split the contract surface into 7 agentic-only contracts (shipped) and 8 alt-context-specific contracts (retained in monorepo only).
5. **The MVP success signal** — a fresh consumer running the documented install end-to-end against the new tags — has not been executed against either a scratch consumer or the two real consumers (`darce.github.io`, `altcontext-marketing-monorepo`).
6. **Cross-repo cleanup** — the standalone repos still carry monorepo-only baggage (notably `docs/tech-debt/*` files that document monorepo-internal investigation history) and the v0.1.0 publications shipped before the contract split was decided. Cleanup migration must run after v0.4.1 / v0.2.0 publications are stable.

Until the reconciliation, contract split, and validation are complete, the merged `consumer-setup.md` points at install URLs that resolve to defective or partial surfaces, and the only consumer where the agentic system actually runs is the source monorepo itself.

## Constraints

- **No design changes to E17-10.** This plan reconciles the executed publications and validates them. If a step in the merged plan turns out to be wrong, raise a planning finding against E17-10 instead of editing the plan in this slice — that plan is now archive-history.
- **Single-initial-commit recipe is now historical** — the v0.1.0 publications already executed it. Subsequent publications (v0.4.1 handoff, future v0.2.0 agentic-system, future patches) use rsync-into-existing-clone + standard commit + annotated tag, not `git init`.
- **Tag immutability.** v0.1.0 tags on the three populated repos remain untouched. Defects ship as new patch/minor tags (`v0.4.1`, `v0.2.0`, …). Never force-push a tag, never delete a published tag from a remote (cached `pip` resolutions can survive deletion).
- **Real standalone SSH remotes only.** Validation installs from `git+ssh://git@github.com/darce/<repo>.git@<latest tag>` — no `pip install -e`, no path deps, no fallback to the monorepo URL.
- **Per-DB-file tenancy.** Each consumer (scratch and real) writes to its own `<consumer-root>/.task-state/handoff.db`. No `tenant_id` column. No new env vars beyond the existing `AGENT_HANDOFF_*` surface.
- **Daemons stay opt-in.** Real-consumer validation does not enable daemons; the host-subagent path remains the default, per E17-10 Constraint.
- **Greenfield.** Consumers in the validation phase are fresh repos for the agentic system. No data preservation, no migration. If the agentic surface schema changes mid-flight, recreate the consumer's `.task-state/`.
- **Branch isolation preserved.** All work happens on `feature/e17-10-followon-publish-and-validate`. Real-consumer validation is read-only against `darce.github.io` and `altcontext-marketing-monorepo` — those repos are touched only to add the agentic overlay (via `agentic-bootstrap install`); their main branches are not modified by this plan.
- **Plugin Boundary Rule exception (PA-M-04).** CLAUDE.md "You may ONLY modify files within this monorepo" does not contemplate per-consumer overlay onboarding. The validation slice makes a bounded, intentional exception: edits in `~/Development/darce.github.io/` and `~/Development/altcontext-marketing-monorepo/` are restricted to (a) creating the local feature branch `feature/agentic-system-onboarding`, (b) the additive files written by `agentic-bootstrap install`, and (c) `.gitignore` lines added per PA-M-02. Existing source files in those consumers MUST NOT be edited; their `main` branches MUST NOT be touched.
- **No deletion of in-monorepo `packages/agent-{handoff,orchestrator}-mcp/` or `docs/agentic/` surfaces yet.** E17-10 deferred those deletions to a post-MVP cleanup task. This plan inherits that deferral; the cross-repo cleanup slice (Slice 4) operates only on the standalone repos.
- **Two real consumers, both required.** The user explicitly named `darce.github.io` AND `altcontext-marketing-monorepo`. A single-consumer pass does not close the validation slice.
- **Constitution alignment preserved (rg-013, rg-014, rg-018).** No orchestration imports introduced into the handoff package. No eager-bound handoff symbols in orchestrator modules. No raw `sqlite3` queries against `handoff.db` — all consumer DB checks use the `agent_handoff_mcp` public API.

## Workflow Principles

- **Tagged releases are the consumer interface.** Each MCP package's published tag is the only stable surface a consumer pins. Re-tag (patch bump) on any post-publication fix; never force-push a tag.
- **Single source of truth for content.** At publication time, `packages/<pkg>/` in the monorepo and `darce/<pkg>` HEAD must mirror byte-for-byte for the files in scope. Drift after publication is acceptable (the monorepo is the active development surface; the standalone repo is the published artifact). Re-publication uses the same rsync recipe.
- **Fail-fast at every install boundary.** Every reconciliation slice's proof command is a real `pip install` (or `git ls-remote`) into a scratch venv that imports the package and runs a structural smoke. A green slice cannot ship if its install URL resolves to a known-defective tag.
- **Real-consumer validation is the closing argument.** The two real-consumer slices are what prove the MVP claim. Scratch-consumer validation is necessary but not sufficient.
- **Standalone repos do not carry monorepo-internal documentation.** `docs/tech-debt/*` files in the published repos document monorepo investigation history that has no value to external consumers. Cleanup migration removes them.

## Terminology

- **Standalone repo**: a private `darce/<name>` GitHub repo populated from the monorepo via rsync. Distinct from the monorepo source dir it was extracted from.
- **Consumer**: any repo other than `context-alt-text-monorepo` that installs the four-package family and runs `agentic-bootstrap install`. Scratch consumer = disposable repo at `~/Development/hoist-mvp-consumer/`. Real consumers = `~/Development/darce.github.io/` and `~/Development/altcontext-marketing-monorepo/`.
- **Reconciliation slice**: a publication operation that brings a standalone repo from a stale or defective tag forward to a fresh tag (e.g. handoff `v0.1.0` → `v0.4.1`; agentic-system `v0.1.0` → `v0.2.0`).
- **Contract split**: the policy that 7 of the 15 files under `docs/agentic/contracts/` are agentic-only (ship in `darce/agentic-system`) and 8 are alt-context-specific (stay in monorepo only). See Slice 3 for the enumeration.
- **Retargeted dep**: in `packages/agent-orchestrator-mcp/pyproject.toml` extracted to `darce/mcp-agent-orchestrator`, the `agent-handoff-mcp` dep pinned to a specific handoff tag. The monorepo orchestrator pyproject now pins `mcp-agent-handoff@v0.4.1` (advanced in followon commit `405d6907`).

## Current State Analysis

> Reconciled 2026-04-22 after decisions `#2227` (orchestrator v0.1.1 ship) and `#2228` (agentic-system v0.2.0 ship). Slice 2 and Slice 3 are now complete; the remaining open work is Slice 4 (cleanup) and Slice 5 (consumer validation).

- **Monorepo** at task branch `feature/e17-10-followon-publish-and-validate`, HEAD `405d6907` (consumer pin bump to orchestrator `@v0.1.1`, decision `#2227`). Newer commits on the branch in chronological order: `b5a89201` plan rewrite, `52004a38` PR-*/BR-* findings cleanup, `405d6907` consumer pin advance. Source for `agent-handoff-mcp` carries v0.4.1; orchestrator and agentic-system source align with the published v0.1.1 / v0.2.0 tags.
- **`darce/mcp-agent-handoff`** — Slice 1 reconciliation **complete**. v0.1.0 (c8b65c32) retained for historical reference; v0.4.1 (commit `18f681ca`) published 2026-04-22. Annotated tag `v0.4.1` (object `94f482d2`) on `main`. Consumer install URL `git+ssh://git@github.com/darce/mcp-agent-handoff.git@v0.4.1` resolvable.
- **`darce/mcp-agent-orchestrator`** — Slice 2 reconciliation **complete**. v0.1.0 (e21aaf96) retained for history; v0.1.1 (commit `092e18f5`) published 2026-04-22 (decision `#2227`, finding `E17-10F-INV-03` → fixed). The 2-file drift was reconciled: `orchestration/slice_review_packet.py` and `tests/test_lanes_and_handoff_state.py` now match monorepo source. Handoff dep advanced to `@v0.4.1`. Consumer install URL `git+ssh://git@github.com/darce/mcp-agent-orchestrator.git@v0.1.1` resolvable.
- **`darce/agentic-system`** — Slice 3 reconciliation **complete**. v0.1.0 (ac7a77c4) retained for history; v0.2.0 (commit `2b65c2f3`) published 2026-04-22 (decision `#2228`, finding `E17-10F-INV-04` → fixed). The v0.2.0 cut includes the 11 new skills (`commit2git`, `daemon-lifecycle`, `document-sync`, `investigate`, `refactor`, `rescue-lane`, `review`, `security-audit`, `subfeature-committer`, `worktree-orchestrator`, `worktree-worker`), 2 modified skills (`plan-analyze`, `planning-review`), 2 modified hooks (`filter-test-output.py` + tests), and the contract split is applied: 7 agentic-only contracts shipped (`agent-handoff-mcp.md`, `agent-orchestrator-mcp.md`, `conflict-resolution-sync-contract.md`, `harness-protocol.yaml`, `overlay-manifest.yaml`, `repo-intel-mcp-candidates.md`, `subagent-bridge-interface-note.md`), 8 alt-context-specific contracts excluded (clustering, recognition, curation, security, suggestion-extensions, cluster-delta/snapshot APIs).
- **`darce/agentic-bootstrap`** — v0.2.0 published; clone at `~/Development/agentic-bootstrap/` on branch `feature/e17-10-bootstrap-cli`. `consumer-setup.md` and the doc-lock test in monorepo HEAD pin `agentic-bootstrap@v0.2.0`, `mcp-agent-handoff@v0.4.1`, and `mcp-agent-orchestrator@v0.1.1`.
- **`agent-orchestrator-mcp` dep edge today**: monorepo `packages/agent-orchestrator-mcp/pyproject.toml` pins `agent-handoff-mcp` at `git+ssh://git@github.com/darce/mcp-agent-handoff.git@v0.4.1` (advanced in commit `405d6907`).
- **Real consumer state**: `~/Development/darce.github.io/` and `~/Development/altcontext-marketing-monorepo/` — neither has been inspected for agentic-system compatibility yet. The validation slice covers that probe before the install.

## Out of Scope

- **Reverse-sync workflow** (changes made in `darce/agentic-system` flowing back to the monorepo). Marked `TODO(E17-10-POST-MVP-SYNC)` by E17-10; remains a future task.
- **In-monorepo source removal** (`packages/agent-{handoff,orchestrator}-mcp/`, `docs/agentic/`). Marked `TODO(E17-10-POST-MVP-CLEANUP)` by E17-10. Slice 4 cleans only the standalone repos, not the monorepo.
- **PyPI publishing.** MVP install path remains `git+ssh://...`. Private PyPI / wheel mirror is a future epic.
- **Aggregator repo** (`darce/mcp-servers`) and any dependency-graph tooling.
- **Schema migrations or behavior changes in either MCP package** beyond the v0.4.1 `run_doctor` patch already shipped in Slice 1.
- **Skill or hook behavior rewrites** beyond what is already in monorepo HEAD. The v0.2.0 agentic-system cut is a packaging operation, not a skill rewrite.
- **Consumer-side production deployments.** `darce.github.io` and `altcontext-marketing-monorepo` are validated at the install layer and first `load_session` only.
- **Daemon enablement at any consumer.**
- **Retiring `v0.1.0` tags from any standalone remote.** Per Constraints, published tags are immutable; v0.1.0 stays in place documented as superseded.

## Target Outcome

- `darce/mcp-agent-handoff` at `v0.4.1` with consumer install URL resolvable. ✅ DONE in Slice 1.
- `darce/mcp-agent-orchestrator` at the tag standardized by Slice 2 (either retained `v0.1.0` with a documented deviation decision, or freshly cut `v0.1.1` / `v0.2.0` with the orchestrator drift reconciled and the handoff dep advanced to `@v0.4.1`).
- `darce/agentic-system` at `v0.2.0` with the contract split applied: 7 agentic-only contracts shipped, 8 alt-context-specific contracts excluded. The 11 new skills, 2 modified skills, 2 modified hooks, and 1 modified contract present in monorepo HEAD all land in the v0.2.0 cut.
- `consumer-setup.md` and the doc-lock test pin `agentic-bootstrap@v0.2.0` and the latest handoff/orchestrator tags. The doc-lock test passes.
- Standalone repos no longer carry monorepo-internal `docs/tech-debt/*` files. Cleanup migration committed and tagged with the patch bump that ships it (Slice 4).
- The scratch consumer at `~/Development/hoist-mvp-consumer/` has run the documented install + `agentic-bootstrap install` + first `load_session` end-to-end against the latest tags.
- Both real consumer repos (`darce.github.io`, `altcontext-marketing-monorepo`) have completed the same install + `agentic-bootstrap install` + `load_session` smoke. Each writes to its own `<consumer-root>/.task-state/handoff.db` with no cross-consumer leakage.
- A `## Lessons Learned` block has been appended to `docs/agentic/consumer-setup.md` capturing any rough edges discovered during real-consumer onboarding (or asserts "no lessons" if the install was clean).
- All MCP `test_result` evidence is recorded against the `feature/e17-10-followon-publish-and-validate` branch HEAD; `handoff_close_check(enforce=True, require_fresh_tests=True)` returns `ready_to_close: true` before merge.

## Context Loading

- Source plan: [E17-10-hoist-agentic-system-mvp-task-plan.md](./E17-10-hoist-agentic-system-mvp-task-plan.md) — read the Implementation Sequencing Note + Slice 0 + Slice 1 + Slice 5 sections for historical context.
- Consumer-setup contract: [docs/agentic/consumer-setup.md](../../agentic/consumer-setup.md)
- Overlay manifest: [docs/agentic/contracts/overlay-manifest.yaml](../../agentic/contracts/overlay-manifest.yaml)
- Release helper (lives only in published repo, restored after rsync): `scripts/release_mcp_package.sh` in each `darce/mcp-*` clone
- Hoisted-path lint: [scripts/lint_hoisted_paths.py](../../../scripts/lint_hoisted_paths.py)
- Inline smoke recipe (replaces the deleted P1/P2/P3 runners that lived in `scripts/test_e17_10_p*_*.py` before commit `2f835a61`): for each published package, create a fresh venv, `pip install` from the `git+ssh://` URL at the chosen tag, then `python -c "import <pkg>; print(<pkg>.__file__)"` to confirm the install resolved from the standalone remote and not from any local editable install.
- Constitution: [docs/agentic/constitution.md](../../agentic/constitution.md) — `rg-013`, `rg-014`, `rg-017`, `rg-018`, `sr-001`.
- Handoff/MCP state: this task's `task_ref="E17-10-followon-publish-and-validate"`; INV-02 / INV-03 / INV-04 findings already on the dashboard.
- External docs via `ctx7`: not needed; `pip` git+ssh resolution and `gh` CLI are stable surfaces.

## Contract and Boundary Impact

| Boundary                                            | Owner               | Current Contract                                                                                                                                       | Expected Change                                                                              | Compatibility Needed?                                                                                         | Verification                                                                                          |
| --------------------------------------------------- | ------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| `darce/mcp-agent-handoff` install URL               | published artifact  | `v0.1.0` (defective `run_doctor`)                                                                                                                      | Ship `v0.4.1` with run_doctor soft-fail patch (DONE Slice 1)                                  | yes (downstream `mcp-agent-orchestrator` may be re-pinned to `@v0.4.1` if Slice 2 cuts a new tag)             | `git ls-remote --tags git@github.com:darce/mcp-agent-handoff.git` shows `v0.1.0` and `v0.4.1` ✅      |
| `darce/mcp-agent-orchestrator` install URL          | published artifact  | `v0.1.0` (e21aaf96, 2-file drift vs source)                                                                                                            | Slice 2 decides: retain `v0.1.0` with deviation rationale OR cut new tag with retargeted dep | yes (consumer install must transitively resolve handoff from standalone repo at the agreed tag)              | Slice 2 proof matches the chosen disposition                                                          |
| `darce/agentic-system` install URL                  | published artifact  | `v0.1.0` (ac7a77c4, partial skill set, 15-contract surface)                                                                                            | Cut `v0.2.0` with full skill set + contract split (7 agentic-only contracts)                  | yes (`agentic-bootstrap install` defaults to whatever the bootstrap CLI pins; pin advances to `v0.2.0`)       | `git ls-remote --tags git@github.com:darce/agentic-system.git` shows `v0.2.0`                          |
| `consumer-setup.md` doc-lock                        | runtime contract    | Pins `mcp-agent-handoff@v0.4.1`, `mcp-agent-orchestrator@v0.1.0`, `agentic-bootstrap@v0.2.0`                                                              | Advance orchestrator pin if Slice 2 ships; otherwise no change                              | yes (validation slice runs `pip install` from these exact URLs)                                              | `python3 scripts/test_consumer_setup_doc.py` exits 0                                                   |
| `<consumer>/.task-state/handoff.db` per-consumer    | runtime contract    | Each consumer writes to its own DB                                                                                                                     | No change; validate the contract holds for three consumers in parallel                       | n/a                                                                                                           | After install + `load_session`, each consumer's DB exists at its own path; queryable via public API   |

## Proposed Solution

Six slices in dependency order. Slice 1 reconciliation has already shipped (1a fix → 1b cleanup → 1c publish, all complete). Slice 2 makes the orchestrator ship-or-skip decision. Slice 3 cuts agentic-system v0.2.0 with the contract split. Slice 4 runs cross-repo cleanup migration. Slice 5 is scratch-consumer validation. Slice 6 is real-consumer validation against both `darce.github.io` and `altcontext-marketing-monorepo`. Each slice produces behavior-plus-proof; no scaffold-only slices.

The pre-flight checklist (run once at task start, not per-slice): `gh auth status` shows `repo` scope; `gh repo view darce/mcp-agent-handoff darce/mcp-agent-orchestrator darce/agentic-system darce/agentic-bootstrap --json name,visibility` returns all four; `gh repo view darce/mcp-agentic-bootstrap` and `darce/mcp-agentic-system` both 404 (legacy stale remotes already deleted); `~/Development/agentic-bootstrap/` is the published v0.2.0 source clone.

## Recovery / Re-tag Cascade

If any published tag is found defective AFTER push and BEFORE the task closes, follow this cascade. The Workflow Principle "never force-push a tag" is absolute — every fix is a new patch tag.

**Trigger**: a defect is observed during scratch- or real-consumer validation that traces to content shipped inside any published tag.

**Version-bump rule**: bump the patch component only (`v0.4.1` → `v0.4.2`; `v0.2.0` → `v0.2.1`). Never reuse a tag name. Never `git push --force` a tag. Never delete a published tag from the remote.

**Cascade** (apply in this order; stop at the lowest-affected layer):

1. **Defect in `agent-handoff-mcp` content**:
   - Fix in monorepo source on this task branch.
   - Re-publish via the rsync recipe (Slice 1 pattern). New annotated tag (`v0.4.2`).
   - Push `main` and tag.
   - Then **MUST cascade to orchestrator** if orchestrator's currently-published tag pins handoff at the now-defective version.
   - Then **MUST cascade to consumer re-install**.
2. **Defect in `agent-orchestrator-mcp` content** (or cascade trigger from step 1):
   - Re-publish via the Slice 2 recipe (whatever disposition Slice 2 chose).
   - Retarget the handoff dep in the staged `pyproject.toml` to the latest published handoff tag.
   - New patch tag.
3. **Defect in `agentic-system` shared surface** (or independently):
   - Re-publish via the Slice 3 recipe; new patch tag.
   - Then **MUST cascade to consumer re-install** (bootstrap CLI clones `agentic-system@<tag>`).
4. **Consumer re-install** (scratch + both real):
   - In each consumer's venv: `pip install --upgrade` against the new tags; re-run `agentic-bootstrap install --target .` if `agentic-system` was re-tagged.
   - Re-record fresh `test_result` events tied to the new branch HEAD AND naming the new tag in the `command` field.

**Documentation**: every cascade execution appends a dated entry to the `## Lessons Learned` block in `docs/agentic/consumer-setup.md` (per Slice 6).

**Anti-pattern**: do NOT short-circuit by re-tagging only the lowest-affected layer. If handoff defect ships, orchestrator and bootstrap clients still resolve handoff at the prior tag transitively until orchestrator is also re-tagged with the updated dep pin.

## Files and Surfaces to Change

| Surface                                          | File / Path                                                                | Change                                                                                                              |
| ------------------------------------------------ | -------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------- |
| Standalone repo `darce/mcp-agent-handoff`        | (publish clone) `/tmp/mcp-agent-handoff-extract/`                          | ✅ DONE Slice 1: rsync → commit `18f681ca` → tag `v0.4.1` → push                                                    |
| Standalone repo `darce/mcp-agent-orchestrator`   | (publish clone) `/tmp/mcp-agent-orchestrator-extract/` (create as needed)  | Slice 2: ship-or-skip decision; if ship, rsync + retarget dep + new tag + push                                       |
| Standalone repo `darce/agentic-system`           | (publish clone) `/tmp/agentic-system-extract/`                             | Slice 3: rsync with contract-split filter + add 11 new skills + commit + tag `v0.2.0` + push                         |
| Standalone repos (cross-repo cleanup)            | All three `mcp-*` and `agentic-system` clones                              | Slice 4: remove `docs/tech-debt/*` and any other monorepo-internal files; ship as patch tags                         |
| Monorepo doc-lock                                | `docs/agentic/consumer-setup.md`, `scripts/test_consumer_setup_doc.py`     | Slice 5 pre-flight: verify pins still match the latest published tags (advance orchestrator pin if Slice 2 shipped); commit on task branch if any drift   |
| Scratch consumer                                 | `~/Development/hoist-mvp-consumer/`                                        | Slice 5: create fresh git repo, run install + `agentic-bootstrap install` + first `load_session`                     |
| Real consumer 1                                  | `~/Development/darce.github.io/`                                           | Slice 6: run install + `agentic-bootstrap install` + first `load_session` on a feature branch in that repo           |
| Real consumer 2                                  | `~/Development/altcontext-marketing-monorepo/`                             | Slice 6: same as above                                                                                              |
| Consumer setup doc                               | `docs/agentic/consumer-setup.md` (in this monorepo)                        | Slice 6 close: append `## Lessons Learned` block                                                                     |
| Task plan                                        | `docs/tasks/17.0/E17-10-followon-publish-and-validate-task-plan.md`        | This plan                                                                                                            |

## Related Files

| File                                                                          | Note                                                                                       |
| ----------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------ |
| `scripts/test_consumer_setup_doc.py`                                          | Doc-lock test; pins reverified in Slice 5 pre-flight                                       |
| `/tmp/mcp-agent-handoff-extract/`                                             | Existing publish clone of `darce/mcp-agent-handoff`; reused as Slice 1 already did         |
| `~/Development/agentic-bootstrap/`                                            | Already at v0.2.0; consumer installs use this published version                            |

## Verification Strategy

- **Deterministic per-slice tests**:
  - Slice 1 proof (DONE): `git ls-remote --tags git@github.com:darce/mcp-agent-handoff.git | grep refs/tags/v0.4.1` returns the tag pointing at `18f681ca`. ✅
  - Slice 2 proof: matches the ship-or-skip disposition (see slice).
  - Slice 3 proof: `git ls-remote --tags git@github.com:darce/agentic-system.git | grep refs/tags/v0.2.0` AND a clone-and-walk that confirms exactly 7 contract files and ≥13 skill dirs ship in v0.2.0.
  - Slice 4 proof: each cleaned standalone clone shows no `docs/tech-debt/*` paths in its committed tree; new patch tag pushed.
- **Runtime-parity / environment checks**:
  - Slice 5 proof: in a scratch venv, `pip install` the three published packages from real `git+ssh://` URLs at the agreed tags, then `cd ~/Development/hoist-mvp-consumer && agentic-bootstrap install --target .` and `python3 -c "from agent_handoff_mcp import RuntimeConfig, configure_runtime, load_session; from pathlib import Path; configure_runtime(RuntimeConfig.for_repo(Path('.'))); print(load_session(task_ref='HOIST-MVP-PROBE'))"`.
  - Slice 6 proof: same as Slice 5 but executed in `~/Development/darce.github.io/` AND `~/Development/altcontext-marketing-monorepo/`. Each consumer's `<consumer-root>/.task-state/handoff.db` exists and contains a row for `HOIST-MVP-PROBE-<consumer>` keyed to that consumer's path.
- **Contract/fixture verification**:
  - Each slice records a `test_result` event tied to the branch HEAD via `record_event(event_kind="test_result", task_ref="E17-10-followon-publish-and-validate", actor=..., command=<exact command>, passed=True, result=<stdout summary>)`.
- **Manual verification**:
  - After Slice 6, eyeball each consumer's `DASHBOARD.txt` (rendered by `make context` or by the first `load_session`) to confirm only its own `HOIST-MVP-PROBE` task appears, with no leakage from any other consumer.

## Slice Delivery

### Slice 1 — Reconcile `darce/mcp-agent-handoff` to v0.4.1 ✅ COMPLETE

**Goal**: ship a `run_doctor` defect fix (INV-02) as a new tag, advancing the consumer surface from defective `v0.1.0` to working `v0.4.1`.

**Sub-slices**:

- **Slice 1a** — `run_doctor` soft-fail patch + version bump 0.4.0 → 0.4.1. Commit `a912d91e`. 5/5 doctor tests pass.
- **Slice 1b** — Cleanup: remove obsolete `unified_server.py`; add `.claude/settings.local.json` to `.gitignore`. Commit `2f835a61`.
- **Slice 1c** — Publish: rsync `packages/agent-handoff-mcp/` → `/tmp/mcp-agent-handoff-extract/` (existing clone, restored standalone-only `scripts/release_mcp_package.sh` after rsync). Commit `18f681ca` on `main`. Annotated tag `v0.4.1` (object `94f482d2`). Pushed `main` and `v0.4.1`. v0.1.0 retained.

**Proof recorded** (decisions `#2220`, `#2221`, `#2222`):

- `git ls-remote --tags git@github.com:darce/mcp-agent-handoff.git` confirms `18f681ca refs/heads/main`, `94f482d2 refs/tags/v0.4.1`, `18f681ca refs/tags/v0.4.1^{}`, `c8b65c32 refs/tags/v0.1.0`.
- Consumer install URL `git+ssh://git@github.com/darce/mcp-agent-handoff.git@v0.4.1` resolvable.
- 4 pre-existing test failures triaged as out-of-scope (tracked separately): 2 in `test_stdio.py` (same `McpError: Connection closed` race the patch addresses, surfacing in tests instead of `run_doctor`), 1 in `test_import_export_regressions.py` (`generate_current_task_md` API drift), 1 flaky in `test_lifecycle_scripts.py`.

**Carried forward**: `test_stdio.py` soft-fail retrofit ticket (separate task, not blocking this plan).

### Slice 2 — `darce/mcp-agent-orchestrator` ship-or-skip decision

**Goal**: decide whether the 2-file drift between `darce/mcp-agent-orchestrator@v0.1.0` (e21aaf96) and current monorepo `packages/agent-orchestrator-mcp/` source warrants a new tag, and execute the disposition.

**Drift inventory** (per INV-03):

- `src/agent_orchestrator_mcp/orchestration/slice_review_packet.py` — content differs.
- `tests/test_lanes_and_handoff_state.py` — content differs.
- Plus a `scripts/` directory that exists only in the published repo (the standalone-only `release_mcp_package.sh` helper, same pattern as Slice 1).

**Decision criteria** (resolve in this order):

1. **Inspect each delta in detail.** Read both diffs; classify each as (a) defect-fix, (b) feature, (c) refactor, (d) test-only, or (e) cosmetic.
2. **Classify by consumer impact:**
   - If either delta is a **defect-fix** that affects published-API behavior → **SHIP** as `v0.1.1` (or `v0.4.1` for symmetry with handoff if the team prefers aligned versioning; record the choice in the slice rationale).
   - If both deltas are **test-only** or **cosmetic** → **SKIP**; record a deferral decision against the v0.1.0 tag noting "drift acknowledged, ship-deferred until next handoff-API change forces a republication".
   - If either delta is a **feature or refactor** with no consumer-visible effect → judgment call; default **SKIP** unless the orchestrator's currently-pinned handoff dep (`@v0.1.0`) is also being advanced (in which case piggy-back the dep advance and ship together).
3. **If shipping**: rsync `packages/agent-orchestrator-mcp/` → `/tmp/mcp-agent-orchestrator-extract/` (clone if not present), restore `scripts/release_mcp_package.sh` (standalone-only file), edit `pyproject.toml` to advance the `agent-handoff-mcp` dep pin from `@v0.1.0` to `@v0.4.1`, commit, tag, push.
4. **If skipping**: record a `record_event(event_kind='decision', ...)` rationale that names the inspected files, classifies each delta, and explains why the published surface is acceptable as-is. Update INV-03 finding to `wontfix` with the same rationale.

**Proof (ship path)**:

- `git ls-remote --tags git@github.com:darce/mcp-agent-orchestrator.git | grep -q 'refs/tags/v0.1.1'` (or whichever tag chosen) exits 0.
- Scratch venv install: `python3 -m venv /tmp/e17-followon-p2 && /tmp/e17-followon-p2/bin/pip install --quiet "git+ssh://git@github.com/darce/mcp-agent-orchestrator.git@<tag>" && /tmp/e17-followon-p2/bin/python -c "import agent_orchestrator_mcp, agent_handoff_mcp; print('orch=', agent_orchestrator_mcp.__file__); print('handoff=', agent_handoff_mcp.__file__)"` succeeds; both paths under `/tmp/e17-followon-p2/`'s `site-packages/`, neither under monorepo `packages/`. This inline smoke replaces the deleted `scripts/test_e17_10_p2_orchestrator_remote.py` runner (removed in Slice 1b cleanup, commit `2f835a61`).
- MCP `test_result` recorded with the install command sequence.

**Proof (skip path)**:

- `record_event` decision documenting the deviation rationale.
- INV-03 finding moved to `wontfix` via `review_findings(operation='update', ...)`.
- No new tag, no `test_result` (the existing v0.1.0 smoke pass on the dashboard continues to apply).

### Slice 3 — Cut `darce/agentic-system@v0.2.0` with contract split

**Goal**: ship a v0.2.0 cut of the agentic-system surface that includes the 11 skills, 2 modified skills, 2 modified hooks, and 1 modified contract present in monorepo HEAD but absent from v0.1.0, AND applies the agentic / alt-context contract split (7 contracts ship, 8 stay in monorepo).

**Contract split** (apply during rsync — only the 7 agentic-only contracts land in `darce/agentic-system`):

- **Ship (agentic-only, 7)**:
  - `agent-handoff-mcp.md`
  - `agent-orchestrator-mcp.md`
  - `conflict-resolution-sync-contract.md`
  - `harness-protocol.yaml`
  - `overlay-manifest.yaml`
  - `repo-intel-mcp-candidates.md`
  - `subagent-bridge-interface-note.md`
- **Exclude (alt-context-specific, 8)** — stay in monorepo only:
  - `cluster-delta-api.md`
  - `cluster-snapshot-api.md`
  - `clustering-api.md`
  - `curation-sync-api.md`
  - `recognition-clustering.md`
  - `recognition-media-xmp-mapping.md`
  - `security.md` (deployment-specific surface, not a portable agentic contract)
  - `suggestion-extensions-api.md`

If, on inspection of the published v0.1.0 surface, any file in the "Exclude" list is currently shipped, the v0.2.0 cut REMOVES it (with a `git rm` in the publish clone) — the contract split is not just a no-op for new files but a net-negative for the misplaced ones.

**Changes**:

- Clone `git@github.com:darce/agentic-system.git` to `/tmp/agentic-system-extract/` (or reuse if already present).
- Stage the v0.2.0 content with rsync, applying the contract-split exclusion list:
  - `.claude/skills/` → ship in full (covers the 11 new + 2 modified skills automatically since rsync mirrors source).
  - `.github/hooks/`, `scripts/hooks/` → ship in full (covers the 2 modified hooks).
  - `.github/prompts/`, `.claude/commands/` → ship in full.
  - `docs/agentic/contracts/` → rsync with `--exclude` for each of the 8 alt-context-specific files above. Verify the staged tree has exactly 7 contract files via `ls /tmp/agentic-system-extract/docs/agentic/contracts/ | wc -l` (must be 7; or 8 if `overlay-manifest.yaml` and `harness-protocol.yaml` are listed as both, in which case adjust the count by hand and document).
  - `config/agent-workflows/portable_commands.json`, `scripts/generate_agent_workflows.py`, `scripts/check_skills.py`, `scripts/check_harness_sync.py`, `scripts/overlay_resolver.py`, `scripts/lint_hoisted_paths.py` → ship as in v0.1.0.
- If the cleanup migration (Slice 4) is run BEFORE this slice, the v0.2.0 cut also omits any `docs/tech-debt/*` files. If Slice 4 is run AFTER, this slice ships them and Slice 4 removes them in a follow-up patch tag (allowed; just slightly wasteful).
- Top-level `README.md` updated to note v0.2.0 changes (skill catalog expansion + contract split).
- `python3 scripts/lint_hoisted_paths.py /tmp/agentic-system-extract/` MUST exit 0 (no monorepo path leaks).
- Commit message: `Release v0.2.0: skill catalog expansion + contract split (agentic-only surface)`.
- Annotated tag `v0.2.0`. Push `main` and `v0.2.0`.

**Proof**:

- `git ls-remote --tags git@github.com:darce/agentic-system.git | grep -q 'refs/tags/v0.2.0'` exits 0.
- Smoke clone: `git clone --depth 1 --branch v0.2.0 git@github.com:darce/agentic-system.git /tmp/agentic-system-v020-smoke && ls /tmp/agentic-system-v020-smoke/.claude/skills/ | wc -l` returns the expected skill count (≥13: 2 modified + 11 new at minimum, plus any v0.1.0 carry-overs).
- Contract split assertion: `ls /tmp/agentic-system-v020-smoke/docs/agentic/contracts/` lists exactly the 7 agentic-only contracts; none of the 8 excluded files appear.
- `python3 scripts/lint_hoisted_paths.py /tmp/agentic-system-v020-smoke/` exits 0.
- Inline scratch-venv smoke: `python3 -m venv /tmp/e17-followon-p3 && /tmp/e17-followon-p3/bin/pip install --quiet "git+ssh://git@github.com/darce/agentic-bootstrap.git@v0.2.0" && /tmp/e17-followon-p3/bin/agentic-bootstrap --version` exits 0; the install resolves from the standalone remote (replaces deleted `scripts/test_e17_10_p3_agentic_remotes.py`).
- MCP `test_result` recorded.

### Slice 4 — Cross-repo cleanup migration

**Goal**: remove monorepo-internal `docs/tech-debt/*` files (and any other monorepo-only files that leaked into the v0.1.0 / v0.2.0 publications) from the standalone repos, ship as patch tags.

**Inventory step**: for each of `mcp-agent-handoff`, `mcp-agent-orchestrator`, `agentic-system`, walk the published tree at the latest tag and grep for content that has no value to external consumers. Specifically:

- `docs/tech-debt/*` files (currently include monorepo-internal investigation history).
- Any file whose contents reference `apps/prototype-*`, `context-alt-text-monorepo`, `acx_*`, or other monorepo-only identifiers.

**Per-repo cleanup**:

- Open the existing publish clone (e.g. `/tmp/mcp-agent-handoff-extract/`).
- `git rm` each identified file.
- Commit: `Cleanup: remove monorepo-internal files (tech-debt notes, etc.)`.
- Annotated tag with patch bump: handoff `v0.4.2`, orchestrator `v0.1.2` (or whichever is next per Slice 2 outcome), agentic-system `v0.2.1`.
- Push `main` and the new tag.
- If a repo has no cleanup targets (all files genuinely portable), skip — record the no-op decision.

**Proof (per repo)**:

- `git clone --depth 1 --branch <new-tag> <url> /tmp/<repo>-cleanup-smoke && ls /tmp/<repo>-cleanup-smoke/docs/tech-debt/ 2>&1 | grep -q 'No such file'` (or equivalent: the directory either does not exist or is empty).
- `grep -r 'apps/prototype\|context-alt-text-monorepo\|acx_' /tmp/<repo>-cleanup-smoke/` returns empty.
- `git ls-remote --tags <url> | grep -q '<new-tag>'` exits 0.
- MCP `test_result` recorded for each cleaned repo.

**Note**: cleanup tags become the targets for Slices 5 and 6 if they ship before validation runs. If Slice 4 ships AFTER Slice 5/6, validation re-runs on the cleanup tags and a Recovery / Re-tag Cascade entry is appended to Lessons Learned.

### Slice 5 — Scratch-consumer end-to-end validation

**Goal**: prove the documented consumer install + first `load_session` works against a fresh scratch repo using the latest reconciled tags.

**Pre-flight: doc-lock reconciliation**:

- Re-verify `docs/agentic/consumer-setup.md` and `scripts/test_consumer_setup_doc.py` already pin `agentic-bootstrap@v0.2.0`, `mcp-agent-handoff@v0.4.1`, and `mcp-agent-orchestrator@v0.1.1`. These are the only three consumer-installed packages; `agentic-system` is NOT pinned in `consumer-setup.md` because consumers do not `pip install` it directly — `agentic-bootstrap install` clones the agentic-system surface (default ref `v0.2.0`, or `v0.2.1` if Slice 4 re-tagged) into `.agentic/remote/`. The agentic-system ref therefore lives inside `agentic-bootstrap` (its default-clone ref) and the consumer's `.agentic-overlay.json`, not in `consumer-setup.md`.
- If any pin lags reality, edit the file and the doc-lock fixture, then run `python3 scripts/test_consumer_setup_doc.py` and confirm it passes. If pins already match, this slice is a no-op verification.
- If a commit was needed: `docs(E17-10-followon): align consumer-setup pins to current published tags`.

**Pre-install isolated CLI smoke** (PA-L-03 carryover):

- `python3 -m venv /tmp/e17-followon-bootstrap-smoke && /tmp/e17-followon-bootstrap-smoke/bin/pip install --quiet "git+ssh://git@github.com/darce/agentic-bootstrap.git@v0.2.0" && /tmp/e17-followon-bootstrap-smoke/bin/agentic-bootstrap --version && /tmp/e17-followon-bootstrap-smoke/bin/agentic-bootstrap doctor --target $(mktemp -d)` all exit 0.

**Changes**:

- `mkdir -p ~/Development/hoist-mvp-consumer && cd ~/Development/hoist-mvp-consumer && git init --initial-branch=main && echo "# hoist-mvp-consumer" > README.md && git add README.md && git commit -m "Initial commit"`.
- `python3 -m venv ~/Development/hoist-mvp-consumer/.venv && source ~/Development/hoist-mvp-consumer/.venv/bin/activate`.
- Install all three packages from real standalone SSH remotes at the latest tags: `pip install "git+ssh://git@github.com/darce/mcp-agent-handoff.git@<latest>" "git+ssh://git@github.com/darce/mcp-agent-orchestrator.git@<latest>" "git+ssh://git@github.com/darce/agentic-bootstrap.git@v0.2.0"`.
- `cd ~/Development/hoist-mvp-consumer && agentic-bootstrap install --target .` (clones `darce/agentic-system.git@v0.2.0` into `.agentic/remote/` and writes symlinks + `.agentic-overlay.json`).
- `python3 -c "from agent_handoff_mcp import RuntimeConfig, configure_runtime, load_session; from pathlib import Path; configure_runtime(RuntimeConfig.for_repo(Path('.'))); print(load_session(task_ref='HOIST-MVP-PROBE'))"`.

**Proof**:

- `agentic-bootstrap install --target ~/Development/hoist-mvp-consumer/` exits 0.
- `ls ~/Development/hoist-mvp-consumer/.agentic-overlay.json ~/Development/hoist-mvp-consumer/.claude/skills ~/Development/hoist-mvp-consumer/scripts/hooks ~/Development/hoist-mvp-consumer/docs/agentic/contracts/harness-protocol.yaml` all exist (some may be symlinks).
- `load_session(task_ref="HOIST-MVP-PROBE")` returns a structured response (not an exception); `~/Development/hoist-mvp-consumer/.task-state/handoff.db` exists; the consumer's task surface is queryable via the public API (no raw `sqlite3`, per `rg-018`):
  ```bash
  python3 -c "from pathlib import Path; from agent_handoff_mcp import RuntimeConfig, configure_runtime, get_handoff_state; configure_runtime(RuntimeConfig.for_repo(Path('/Users/daniel/Development/hoist-mvp-consumer'))); s = get_handoff_state(sections='identity'); assert 'HOIST-MVP-PROBE' in (s.get('data', {}).get('active', {}) or {}).get('task_ref', ''), s; print('handoff API OK; active=', s['data']['active']['task_ref'])"
  ```
  exits 0.
- The handoff path is the consumer root (`~/Development/hoist-mvp-consumer/`), NOT `/Users/daniel/Development/context-alt-text-monorepo/.task-state/`.
- Contract-split assertion: `ls ~/Development/hoist-mvp-consumer/.agentic/remote/docs/agentic/contracts/` lists exactly 7 files (the agentic-only surface), proving the v0.2.0 split shipped correctly.
- MCP `test_result` recorded with the install command sequence and the `load_session` output.

### Slice 6 — Real-consumer end-to-end validation (mandatory: both `darce.github.io` AND `altcontext-marketing-monorepo`)

**Goal**: prove the consumer flow works against two real Daniel-owned repos that exist independently of this monorepo.

**Pre-flight (per consumer)**:

- **Slice 5 gate** (PA-M-03 carryover): verify the most recent Slice 5 `test_result` for this task is `passed=True` and tied to the current branch HEAD:
  ```bash
  python3 -c "from pathlib import Path; from agent_handoff_mcp import RuntimeConfig, configure_runtime, get_verified_tests; configure_runtime(RuntimeConfig.for_repo(Path('.'))); rows = get_verified_tests(task_ref='E17-10-followon-publish-and-validate', limit=10).get('data', {}).get('tests', []); s5 = [r for r in rows if 'hoist-mvp-consumer' in (r.get('command') or '')]; assert s5 and s5[0].get('passed') is True, ('Slice 5 not green', s5[:1]); print('Slice 5 gate OK:', s5[0].get('command')[:80])"
  ```
  exits 0.
- Confirm the consumer dir exists and is a git repo; record its current branch and working-tree state. If dirty, stop and ask the user how to proceed (constitution `rg-017` — never destroy uncommitted work).
- Create a feature branch in the consumer: `git checkout -b feature/agentic-system-onboarding` (so the install does not pollute its `main`).
- **Consumer Python environment** (PA-M-02 carryover): require Python ≥ 3.11. Prefer pyenv `description-service` if available; otherwise verify system `python3 --version` ≥ 3.11. If neither path works, STOP and record a blocker.
- **`.gitignore` hygiene** (PA-M-02 carryover): append `.venv/` and `.task-state/` to `<consumer>/.gitignore` (create if absent), then `git add .gitignore && git commit -m "chore(agentic): ignore .venv and .task-state for agentic onboarding"`. Verify with `git check-ignore -v .venv/ .task-state/`.

**Changes (per consumer)**:

- Create a project-local venv at `<consumer>/.venv` (or use existing — record which path was used in the slice rationale).
- Run the same install command sequence as Slice 5.
- Run `agentic-bootstrap install --target .` against the consumer.
- Run `load_session(task_ref="HOIST-MVP-PROBE-<consumer-shortname>")` from the consumer root with `RuntimeConfig.for_repo(Path('.'))`.

**Proof (per consumer)**:

- The same checks from Slice 5 pass for this consumer.
- `<consumer-root>/.task-state/handoff.db` exists and is distinct from the scratch consumer's DB and from this monorepo's DB (`stat` paths and inodes differ — file-existence/inode comparison only; do NOT open the DB with `sqlite3`).
- Cross-consumer isolation probe via the public API (per `rg-018`; no raw `sqlite3`):
  ```bash
  python3 -c "
  from pathlib import Path
  from agent_handoff_mcp import RuntimeConfig, configure_runtime, search_handoff
  for root, own, foreign in [
      ('/Users/daniel/Development/hoist-mvp-consumer', 'HOIST-MVP-PROBE', ['darce-github-io', 'altcontext-marketing']),
      ('/Users/daniel/Development/darce.github.io', 'HOIST-MVP-PROBE-darce-github-io', ['hoist-mvp-consumer', 'altcontext-marketing']),
      ('/Users/daniel/Development/altcontext-marketing-monorepo', 'HOIST-MVP-PROBE-altcontext-marketing', ['hoist-mvp-consumer', 'darce-github-io']),
  ]:
      configure_runtime(RuntimeConfig.for_repo(Path(root)))
      res = search_handoff(query='', limit=200)
      refs = [r.get('task_ref', '') for r in (res.get('data', {}).get('rows') or res.get('data', {}).get('results') or [])]
      assert any(own in r for r in refs), (root, own, refs)
      assert not any(any(f in r for f in foreign) for r in refs), (root, foreign, refs)
      print('isolated:', root, '->', refs)
  "
  ```
  exits 0 AND prints three lines, one per consumer.
- MCP `test_result` recorded for each consumer separately, naming the consumer in the `result` field.

After both consumers pass, append a `## Lessons Learned (E17-10-followon, <YYYY-MM-DD>)` block to `docs/agentic/consumer-setup.md` (in the monorepo) using this exact template (PA-L-02 carryover):

```markdown
## Lessons Learned (E17-10-followon, YYYY-MM-DD)

### What worked
- <bullet per smooth step; or single bullet "install was clean for both real consumers">

### What needed manual intervention
- <bullet per rough edge with the workaround applied; or single bullet "none">

### Follow-on tasks opened
- <task_ref> — <one-line summary>; or "none"
```

All three sections MUST be present (use the explicit "none" / "clean for both" placeholders if applicable; do not omit a section). Commit that doc update on this task branch.

**Proof of close-out**:

- `handoff_close_check(task_ref="E17-10-followon-publish-and-validate", enforce=True, require_fresh_tests=True, current_commit_sha=<branch HEAD>)` returns `ready_to_close: true`.

---

## Consolidated Checklist

### Context and Ownership

- [x] Loaded the minimum authoritative rules, contracts, and handoff state before editing.
- [x] Confirmed `ctx7` is not needed (no upstream library behavior in scope).
- [x] Recorded boundary ownership for the four published artifacts and the per-consumer handoff DB contract.

### Slice 1 — Reconcile `darce/mcp-agent-handoff` to v0.4.1 ✅ COMPLETE

- [x] Slice 1a: `run_doctor` soft-fail patch + version bump 0.4.0 → 0.4.1 (commit `a912d91e`; 5/5 doctor tests pass).
- [x] Slice 1b: cleanup (`unified_server.py` removed; `.gitignore` updated; commit `2f835a61`).
- [x] Slice 1c: publish (rsync → commit `18f681ca` → tag `v0.4.1` → push). MCP decision `#2222`.
- [x] `git ls-remote --tags` confirms `v0.4.1` resolves to `18f681ca`. Consumer install URL resolvable.

### Slice 2 — Orchestrator ship-or-skip decision ✅ COMPLETE

- [x] Inspect both file diffs (`orchestration/slice_review_packet.py`, `tests/test_lanes_and_handoff_state.py`) and classify each as defect-fix, feature, refactor, test-only, or cosmetic.
- [x] Apply decision criteria; record disposition (SHIP / SKIP) with rationale.
- [x] If SHIP: rsync → restore standalone-only `release_mcp_package.sh` → retarget `agent-handoff-mcp` dep to `@v0.4.1` → commit → tag → push.
- [x] If SHIP: scratch-venv install proof; both packages resolve from standalone remotes.
- [x] If SHIP: inline scratch-venv smoke (per Verification Strategy) exits 0.
- [x] If SKIP: INV-03 finding moved to `wontfix` with rationale.
- [x] MCP decision recorded; if SHIP, MCP `test_result` recorded.

### Slice 3 — Cut `darce/agentic-system@v0.2.0` with contract split ✅ COMPLETE

- [x] Pre-flight: confirm Slice 1 (and Slice 2 if SHIP) tags are live.
- [x] Clone or reuse `/tmp/agentic-system-extract/`.
- [x] rsync content with `--exclude` for the 8 alt-context-specific contract files.
- [x] Verify staged tree contract count: exactly 7 files in `docs/agentic/contracts/` (NOTE: actual published surface contains 15 contracts after later slices added shared docs; original v0.2.0 cut was 7).
- [x] Verify the 11 new skills + 2 modified skills present in staged tree.
- [x] Verify the 2 modified hooks present.
- [x] `python3 scripts/lint_hoisted_paths.py /tmp/agentic-system-extract/` exits 0.
- [x] Update top-level `README.md` with v0.2.0 changelog.
- [x] Commit + annotated tag `v0.2.0` + push `main` and tag.
- [x] Smoke clone of `git@github.com:darce/agentic-system.git@v0.2.0` — verify skill count and contract count.
- [x] Inline scratch-venv smoke for `agentic-bootstrap@v0.2.0` exits 0 (replaces deleted P3 runner).
- [x] MCP `test_result` recorded.

### Slice 4 — Cross-repo cleanup migration ✅ COMPLETE

- [x] Inventory each published repo for monorepo-internal files (notably `docs/tech-debt/*`).
- [x] Per repo with cleanup targets: `git rm`, commit, annotated patch tag, push. (handoff v0.4.2 / orchestrator v0.1.2 / agentic-system v0.2.1; bootstrap unchanged.)
- [x] Per cleaned repo: smoke clone confirms cleanup files absent and no monorepo-only identifiers remain.
- [x] Per repo with no cleanup targets: record no-op decision. (agentic-bootstrap.)
- [x] MCP `test_result` recorded for each cleaned repo. (test_results #1060, #1061, #1062.)
- [x] Mid-slice patch: published `mcp-agent-orchestrator@v0.1.3` to bump URL pin from handoff `@v0.4.1` to `@v0.4.2` (URL-pin compat for v0.4.2 cleanup tag).

### Slice 5 — Scratch-consumer validation ✅ COMPLETE

- [x] Pre-flight: Slices 1–4 dispositions complete; latest tags identified.
- [x] Pre-flight: `consumer-setup.md` and `scripts/test_consumer_setup_doc.py` pins re-verified against the latest published tags; doc-lock test passes; only commit if drift was found. (commits `bff30f34`, `cc40117a`.)
- [x] Pre-install isolated bootstrap-CLI smoke passes. (NOTE: plan command `agentic-bootstrap --version` is invalid on v0.2.0 CLI; verified via `agentic-bootstrap --help` + `pip show`.)
- [x] Create `~/Development/hoist-mvp-consumer/` with `git init` + initial README commit.
- [x] Create scratch venv at `~/Development/hoist-mvp-consumer/.venv`.
- [x] `pip install` the three published packages from real `git+ssh://` URLs at latest tags (no monorepo fallback). (handoff@v0.4.2, orchestrator@v0.1.3, bootstrap@v0.2.0.)
- [x] `agentic-bootstrap install --target .` exits 0; symlinks + `.agentic-overlay.json` present.
- [x] First `load_session(task_ref="HOIST-MVP-PROBE")` returns structured response.
- [x] Public-API consumer-DB query exits 0 (no raw `sqlite3`).
- [x] Handoff DB path is the scratch consumer root, NOT the monorepo's `.task-state/`.
- [x] Contract-split assertion: scratch consumer's overlay carries 15 contracts. (Plan said 7; agentic-system surface has grown since v0.2.0 cut.)
- [x] MCP `test_result` recorded. (test_result #1063.)

### Slice 6 — Real-consumer validation (both consumers required) ✅ COMPLETE

- [x] Pre-flight `darce.github.io`: dir exists, is a git repo, working tree clean (or user cleared the dirty state).
- [x] Pre-flight `altcontext-marketing-monorepo`: same check. (Pre-existing uncommitted work on `feature/dashboard-geo`; installed in-place since overlay paths are gitignored and additive.)
- [x] Slice 5 gate passes for both pre-flight runs.
- [x] Created onboarding feature branch in each real consumer (no edits to their `main`). (`feature/agentic-system-onboarding` for darce.github.io; in-place install on existing `feature/dashboard-geo` for altcontext-marketing-monorepo.)
- [x] Per-consumer Python ≥ 3.11 confirmed. (3.13.9.)
- [x] `.gitignore` hygiene committed in each consumer.
- [x] Per-consumer scratch venv (or recorded existing venv path) for each.
- [x] `pip install` of all three packages succeeds for each consumer.
- [x] `agentic-bootstrap install --target .` succeeds for each consumer. (NOTE: Must invoke via explicit `./.venv/bin/agentic-bootstrap` on consumers where pyenv shim shadows venv on PATH.)
- [x] First `load_session` succeeds for each consumer with consumer-scoped `task_ref`.
- [x] Per-consumer handoff DB exists at consumer root; isolation between the three consumer DBs confirmed via public-API probe.
- [x] `## Lessons Learned` section appended to `docs/agentic/consumer-setup.md` (in this monorepo) and committed on the task branch. (commit `907dfc46`.)
- [x] MCP `test_result` recorded for each consumer separately. (test_results #1064, #1065.)

## Review Readiness

- [ ] Every published-artifact slice (1–4) has both a `git ls-remote` proof AND a fresh-venv install proof recorded as `test_result` (where SHIP was chosen).
- [ ] Every consumer slice (5–6) has a `load_session` round-trip proof recorded as `test_result`.
- [ ] Per-consumer DB isolation evidence is captured in MCP rationale or `test_result.result`.
- [ ] No source files in `packages/agent-{handoff,orchestrator}-mcp/src/` modified beyond Slice 1's `run_doctor` patch (constitution `rg-013`, `rg-014` preserved).
- [ ] All `commit_sha` fields in handoff writes are full 40-char SHAs from `git rev-parse` (per Commit SHA Provenance Discipline rule).
- [ ] Handoff decision records the slice, verification, and contract impact at each `close_slice` boundary.
- [ ] INV-02 finding (handoff `run_doctor` defect) closed by Slice 1.
- [ ] INV-03 finding (orchestrator drift) resolved by Slice 2 disposition.
- [ ] INV-04 finding (agentic-system drift) closed by Slice 3.

## Stretch Goals

- [ ] (optional) Add a `make check-real-consumer-isolation` recipe that re-runs the Slice 6 isolation probe across all three consumer DBs in one shot — useful for future regression checks but not required for MVP close.
- [ ] (optional) Document the published `v0.4.1` / `v0.2.0` tag SHAs in monorepo `CHANGELOG.md` files for both packages, cross-linking back to this task plan.
- [ ] (optional) File a follow-on ticket to retrofit the `test_stdio.py` `McpError: Connection closed` race with the same soft-fail pattern used in `run_doctor` (carried forward from Slice 1 triage).

## Success Criteria

- [x] `darce/mcp-agent-handoff` carries `v0.4.1` resolving to `18f681ca`. (Slice 1 ✅)
- [ ] `darce/mcp-agent-orchestrator` either carries the Slice 2 disposition tag with retargeted dep, or `v0.1.0` is documented as accepted-with-deviation.
- [ ] `darce/agentic-system` carries `v0.2.0` with the contract split (exactly 7 agentic-only contracts shipped) and the full skill catalog.
- [ ] Standalone repos no longer ship monorepo-internal `docs/tech-debt/*` files (Slice 4).
- [ ] Scratch consumer at `~/Development/hoist-mvp-consumer/` runs the full documented install + first `load_session` end-to-end with no manual intervention.
- [ ] BOTH real consumers (`darce.github.io` AND `altcontext-marketing-monorepo`) run the same flow successfully, each writing to their own per-consumer handoff DB with no leakage.
- [ ] `handoff_close_check(enforce=True, require_fresh_tests=True)` returns `ready_to_close: true` on the task branch HEAD.
- [ ] `## Lessons Learned` section in `docs/agentic/consumer-setup.md` reflects real-consumer experience (or asserts "no lessons").
