# E17-10-followon. Publish Standalone MCP Repos and Validate End-to-End Consumer Install

- **Date**: 2026-04-21 19:50 EST
- **Author**: Claude Opus 4.7
- **Owning Epic**: [docs/epics/v0.4.0/skill-formalization-and-process-automation-epic.md](../../epics/v0.4.0/skill-formalization-and-process-automation-epic.md)
- **Epic Short ID**: E17
- **Target Branch**: `feature/e17-10-followon-publish-and-validate`
- **Review Coverage Target**: 2
- **Source Plan**: [E17-10-hoist-agentic-system-mvp-task-plan.md](./E17-10-hoist-agentic-system-mvp-task-plan.md) — Implementation Sequencing Note (P1 / P2 / P3) + Slice 5
- **Hard Prerequisites**: E17-10 merged to `main` at `d9aa69e5`. The four canonical remote repos exist as private under `darce/`: `mcp-agent-handoff`, `mcp-agent-orchestrator`, `agentic-system`, `agentic-bootstrap`. Stale `darce/mcp-agentic-bootstrap` and `darce/mcp-agentic-system` remotes are deleted. Local sibling dir `~/Development/agentic-bootstrap/` is the renamed clone of `darce/agentic-bootstrap` and already published at `v0.2.0`. `gh auth status` on account `darce` carries `repo` scope (`delete_repo` not needed for this plan since cleanup already landed). SSH key configured for `git@github.com:darce/*`.

---

## Objective

Execute the four sub-slices E17-10's merge intentionally deferred (P1 + P2 + P3 standalone-repo extraction and `v0.1.0` tagging, then Slice 5 end-to-end validation), then prove the MVP works against two real Daniel-owned consumer repos (`darce.github.io` and `altcontext-marketing-monorepo`). When this task closes, any Daniel-owned project can install the four-package family from `git+ssh://` URLs and run the documented `agentic-bootstrap install` flow without copy-paste from this monorepo.

## Problem Statement

E17-10 shipped the design, contracts, and in-monorepo code for a hoistable agentic system, but four sub-slices remained unfinished at merge:

1. `darce/mcp-agent-handoff` is an empty private repo. The Slice 1 success-signal install (`pip install "git+ssh://...mcp-agent-handoff.git@v0.1.0"`) cannot resolve.
2. `darce/mcp-agent-orchestrator` is an empty private repo with no `agent-handoff-mcp` dep retargeting. Transitive resolution from a packaged orchestrator install would fall back to `packages/agent-handoff-mcp` (path dep), defeating the standalone-repo contract.
3. `darce/agentic-system` is an empty private repo. The bootstrap CLI has nothing to clone into `<consumer-root>/.agentic/remote/`.
4. The MVP success signal (a fresh consumer running the documented install end-to-end) was never executed against either a synthetic consumer or a real one.

Until all four are addressed, the merged consumer-setup doc points at install URLs that 404 on resolve, and the only consumer where the agentic system actually runs is the source monorepo itself. The hoist is not provably hoisted.

## Constraints

- **No design changes to E17-10.** This plan executes the existing Implementation Sequencing Note (P1 + P2 + P3 + Slice 5). If a step in the merged plan turns out to be wrong, raise a planning finding against E17-10 instead of editing the plan in this slice — the plan is now archive-history. New decisions land in this follow-on plan.
- **Single-initial-commit recipe per E17-10 Slice 0.** Each extraction repo gets one commit (`rsync --archive --delete <paths> <target>/`, then `git init && git add -A && git commit`). `git subtree split` is rejected for the same reason E17-10 rejected it: it preserves multi-commit history, which conflicts with the single-initial-commit constraint.
- **Real standalone SSH remotes only.** Slice 4 (validation) installs from `git+ssh://git@github.com/darce/<repo>.git@v0.1.0` for `mcp-agent-handoff` and `mcp-agent-orchestrator`, and `git+ssh://git@github.com/darce/agentic-bootstrap.git@v0.2.0` for the bootstrap CLI (the bootstrap is already published at v0.2.0; consumer-setup.md and the doc-lock test still pin v0.1.0 and MUST be reconciled to v0.2.0 in Slice 4 pre-flight). No fallback to the monorepo URL, no `pip install -e`, no path deps.
- **Per-DB-file tenancy.** Each consumer (synthetic and real) writes to its own `<consumer-root>/.task-state/handoff.db`. No `tenant_id` column. No new env vars beyond the existing `AGENT_HANDOFF_*` surface.
- **Daemons stay opt-in.** Real-consumer validation does not enable daemons; the host-subagent path remains the default, per E17-10 Constraint.
- **Greenfield.** Consumers in Slice 5 are fresh repos for the agentic system. No data preservation, no migration. If the agentic surface schema changes mid-flight, recreate the consumer's `.task-state/`.
- **Branch isolation preserved.** All work happens on `feature/e17-10-followon-publish-and-validate`. Real-consumer validation in Slice 5 is read-only against `darce.github.io` and `altcontext-marketing-monorepo` — those repos are touched only to add the agentic overlay (via `agentic-bootstrap install`); their main branches are not modified by this plan.
- **No deletion of in-monorepo `packages/agent-{handoff,orchestrator}-mcp/` or `docs/agentic/` surfaces.** E17-10 explicitly deferred those deletions to a post-MVP cleanup task. This plan inherits that deferral.
- **Two real consumers, both required.** The user explicitly named `darce.github.io` AND `altcontext-marketing-monorepo`. A single-consumer pass does not close Slice 5.
- **Constitution alignment preserved (rg-013, rg-014).** Extraction must not introduce orchestration imports into the handoff package or eager-bind handoff symbols in orchestrator modules. The single-initial-commit extraction copies current state; this plan does not refactor either package.

## Workflow Principles

- **Tagged releases are the consumer interface.** Each MCP package's `v0.1.0` tag is the only stable surface a consumer pins. Re-tag (`v0.1.1`) on any post-extraction fix; never force-push a tag.
- **Single source of truth for content.** During the lifetime of this plan, `packages/agent-handoff-mcp/` in the monorepo and `darce/mcp-agent-handoff` HEAD must mirror byte-for-byte at extraction time. Drift after extraction is acceptable (the monorepo is the active development surface; the standalone repo is the published artifact). Re-extraction at re-tag time uses the same recipe.
- **Fail-fast at every install boundary.** Each slice's proof command is a real `pip install` into a scratch venv that imports the package and runs a structural smoke. A green slice cannot ship if its install URL still 404s or its import raises.
- **Real-consumer validation is the closing argument.** Slice 5 is what proves the MVP claim. Synthetic-consumer validation (Slice 4) is necessary but not sufficient.

## Terminology

- **Standalone repo**: a private `darce/<name>` GitHub repo whose `main` is populated by the single-initial-commit extraction recipe. Distinct from the monorepo source dir it was extracted from.
- **Consumer**: any repo other than `context-alt-text-monorepo` that installs the four-package family and runs `agentic-bootstrap install`. Synthetic consumer = scratch repo at `~/Development/hoist-mvp-consumer/`. Real consumers = `~/Development/darce.github.io/` and `~/Development/altcontext-marketing-monorepo/`.
- **Extraction repo**: the local clone of a `darce/<name>` repo at `~/Development/<name>/` used as the staging area for the single initial commit. After Slice 3 lands, these clones can be deleted; before then they hold the in-flight extraction.
- **Retargeted dep**: in `packages/agent-orchestrator-mcp/pyproject.toml` extracted to `darce/mcp-agent-orchestrator`, the `agent-handoff-mcp` dep is rewritten from a path dep or floating `git+ssh://...mcp-agent-handoff.git` URL to the tagged form `git+ssh://git@github.com/darce/mcp-agent-handoff.git@v0.1.0`.

## Current State Analysis

- **Monorepo** at `main` HEAD `d9aa69e5` carries the merged E17-10 implementation: `packages/agent-handoff-mcp/` + `packages/agent-orchestrator-mcp/` with publish-ready `pyproject.toml` and `[tool.hoisted]` tables, `CHANGELOG.md` files, `scripts/release_mcp_package.sh` (in each package directory), `docs/agentic/` shared surface, [docs/agentic/contracts/overlay-manifest.yaml](../../agentic/contracts/overlay-manifest.yaml), [docs/agentic/consumer-setup.md](../../agentic/consumer-setup.md), and [scripts/overlay_resolver.py](../../../scripts/overlay_resolver.py) + [scripts/lint_hoisted_paths.py](../../../scripts/lint_hoisted_paths.py).
- **Remote repos**:
  - `darce/mcp-agent-handoff` — exists, EMPTY (no commits, no tags).
  - `darce/mcp-agent-orchestrator` — exists, EMPTY.
  - `darce/agentic-system` — exists, EMPTY.
  - `darce/agentic-bootstrap` — exists, populated; tag `v0.2.0` published; clone at `~/Development/agentic-bootstrap/` is on branch `feature/e17-10-bootstrap-cli`.
- **Stale remotes deleted (precondition met)**: `darce/mcp-agentic-bootstrap` and `darce/mcp-agentic-system` both 404 on `gh repo view`.
- **Local sibling dirs**: `~/Development/agentic-bootstrap/` (populated, the published v0.2.0 source); `~/Development/mcp-agent-handoff/` (empty placeholder); `~/Development/mcp-agent-orchestrator/` (empty placeholder); no `~/Development/agentic-system/` yet.
- **`agent-orchestrator-mcp` dep edge today**: `packages/agent-orchestrator-mcp/pyproject.toml` pins `agent-handoff-mcp` at `git+ssh://git@github.com/darce/mcp-agent-handoff.git` (floating, no `@v0.1.0`). Extraction must retarget this to `@v0.1.0` before Slice 2 tags.
- **Real consumer state**: `~/Development/darce.github.io/` and `~/Development/altcontext-marketing-monorepo/` — neither has been inspected for agentic-system compatibility yet. Slice 5 covers that probe before the install.

## Out of Scope

- **Reverse-sync workflow** (changes made in `darce/agentic-system` flowing back to the monorepo). E17-10 marked this `TODO(E17-10-POST-MVP-SYNC)`; it remains a future task. One-way flow (monorepo → standalone) is what Slice 5 proves.
- **Post-MVP cleanup**: removing the in-monorepo `packages/agent-{handoff,orchestrator}-mcp/` source trees and `docs/agentic/` shared surface. E17-10 marked this `TODO(E17-10-POST-MVP-CLEANUP)`. Doing it inside this plan would invalidate the rsync source paths mid-flight.
- **PyPI publishing.** MVP install path remains `git+ssh://...`. Private PyPI / wheel mirror is a future epic.
- **Aggregator repo** (`darce/mcp-servers`) and any dependency-graph tooling. Out of scope for MVP.
- **Schema migrations or behavior changes in either MCP package.** This plan is pure repo-extraction + validation; no source files in `packages/agent-{handoff,orchestrator}-mcp/src/` change.
- **Skill or hook rewrites.** Shared agentic surface is extracted as-is.
- **Consumer-side production deployments.** `darce.github.io` and `altcontext-marketing-monorepo` are validated at the install layer and first `load_session` only. End-to-end agentic workflows in those consumers are out of scope; that is consumer-side adoption work.
- **Daemon enablement at any consumer.** Default `orchestrator.daemons.enabled: false` is exercised; opt-in flow is documented but not validated end-to-end here.

## Target Outcome

- All four `darce/<repo>` standalone remotes carry their `v0.1.0` tag (or `v0.2.0` for `agentic-bootstrap` already), with `git ls-remote --tags` proof in MCP `test_result`.
- The synthetic scratch consumer at `~/Development/hoist-mvp-consumer/` has run `pip install "git+ssh://git@github.com/darce/mcp-agent-handoff.git@v0.1.0"`, the same for `mcp-agent-orchestrator` and `agentic-bootstrap`, then `agentic-bootstrap install --target .` against the real `darce/agentic-system.git@v0.1.0` clone, and a `load_session(task_ref="HOIST-MVP-PROBE")` returns a structured response writing to `<consumer-root>/.task-state/handoff.db`.
- Both real consumer repos (`darce.github.io`, `altcontext-marketing-monorepo`) have completed the same install + `agentic-bootstrap install` + `load_session` smoke. Each writes to its own `<consumer-root>/.task-state/handoff.db` with no cross-consumer leakage.
- A `## Lessons Learned` block has been appended to [docs/agentic/consumer-setup.md](../../agentic/consumer-setup.md) capturing any rough edges discovered during real-consumer onboarding (or asserts "no lessons" if the install was clean).
- All MCP `test_result` evidence is recorded against the `feature/e17-10-followon-publish-and-validate` branch HEAD; `handoff_close_check(enforce=True, require_fresh_tests=True)` returns `ready_to_close: true` before merge.

## Context Loading

- Source plan: [E17-10-hoist-agentic-system-mvp-task-plan.md](./E17-10-hoist-agentic-system-mvp-task-plan.md) — read the Implementation Sequencing Note + Slice 0 + Slice 1 + Slice 5 sections.
- Consumer-setup contract: [docs/agentic/consumer-setup.md](../../agentic/consumer-setup.md)
- Overlay manifest: [docs/agentic/contracts/overlay-manifest.yaml](../../agentic/contracts/overlay-manifest.yaml)
- Release scripts: [packages/agent-handoff-mcp/scripts/release_mcp_package.sh](../../../packages/agent-handoff-mcp/scripts/release_mcp_package.sh) (if present per E17-10 Slice 1), [packages/agent-orchestrator-mcp/scripts/release_mcp_package.sh](../../../packages/agent-orchestrator-mcp/scripts/release_mcp_package.sh)
- Hoisted-path lint: [scripts/lint_hoisted_paths.py](../../../scripts/lint_hoisted_paths.py)
- E17-10 remote-smoke scripts (re-used as proof in this plan):
  - [scripts/test_e17_10_p1_handoff_remote.py](../../../scripts/test_e17_10_p1_handoff_remote.py)
  - [scripts/test_e17_10_p2_orchestrator_remote.py](../../../scripts/test_e17_10_p2_orchestrator_remote.py)
  - [scripts/test_e17_10_p3_agentic_remotes.py](../../../scripts/test_e17_10_p3_agentic_remotes.py)
- Constitution: [docs/agentic/constitution.md](../../agentic/constitution.md) — re-read `rg-013`, `rg-014`, `rg-017` (dirty-worktree teardown), `sr-001` (no relaxing compliance scripts).
- Handoff/MCP state: this task's `task_ref="E17-10-followon-publish-and-validate"`; no findings inherited.
- External docs via `ctx7`: not needed; `pip` git+ssh resolution and `gh` CLI are stable surfaces and well-understood.

## Contract and Boundary Impact

| Boundary                                            | Owner               | Current Contract                                                                                                                                       | Expected Change                                                                              | Compatibility Needed?                                                                                         | Verification                                                                                          |
| --------------------------------------------------- | ------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| `darce/mcp-agent-handoff` install URL               | published artifact  | E17-10 `[tool.hoisted]` table: `git+ssh://git@github.com/darce/mcp-agent-handoff.git@v<tag>`                                                            | Populate `main` and tag `v0.1.0` so the URL resolves                                         | yes (downstream `mcp-agent-orchestrator` pins it)                                                             | `git ls-remote --tags git@github.com:darce/mcp-agent-handoff.git` shows `refs/tags/v0.1.0`            |
| `darce/mcp-agent-orchestrator` install URL          | published artifact  | E17-10 `[tool.hoisted]` table; orchestrator currently pins handoff at floating `git+ssh://...mcp-agent-handoff.git`                                    | Populate `main` with retargeted dep `@v0.1.0`, tag `v0.1.0`                                  | yes (consumer install must transitively resolve handoff from standalone repo, not from `packages/`)           | `pip install "git+ssh://...mcp-agent-orchestrator.git@v0.1.0"` into scratch venv resolves both packages |
| `darce/agentic-system` install URL                  | published artifact  | E17-10 Slice 0 spec: `git+ssh://git@github.com/darce/agentic-system.git@v0.1.0` clone target for `agentic-bootstrap install`                           | Populate `main` from monorepo shared surface, tag `v0.1.0`                                   | yes (`agentic-bootstrap install` defaults to this URL+tag)                                                    | `agentic-bootstrap install --target <scratch>` succeeds end-to-end                                    |
| `<consumer>/.task-state/handoff.db` per-consumer    | runtime contract    | E17-10 Slice 1: each consumer writes to its own `<consumer-root>/.task-state/handoff.db`                                                              | No change; validate the contract holds for three consumers in parallel                       | n/a                                                                                                           | After install + `load_session`, each consumer's DB exists at its own path with the expected schema    |

## Proposed Solution

Five slices in dependency order. Slices 1-3 are extraction-and-tag operations against the three empty standalone repos (P1, P2, P3 from E17-10). Slice 4 is synthetic-consumer validation (E17-10 Slice 5 against the scratch consumer). Slice 5 is real-consumer validation (the user-mandated extension to E17-10's spec) against both `darce.github.io` and `altcontext-marketing-monorepo`. Each slice produces behavior-plus-proof; no scaffold-only slices.

The pre-flight checklist (run once at task start, not per-slice): `gh auth status` shows `repo` scope; `gh repo view darce/mcp-agent-handoff darce/mcp-agent-orchestrator darce/agentic-system darce/agentic-bootstrap --json name` returns all four; `gh repo view darce/mcp-agentic-bootstrap` and `darce/mcp-agentic-system` both 404; `~/Development/mcp-agent-handoff/`, `~/Development/mcp-agent-orchestrator/` exist as empty dirs (not git clones); local clones are created fresh by Slices 1-3.

## Recovery / Re-tag Cascade

If any extracted package's `v0.1.0` tag is found defective AFTER push and BEFORE the task closes, follow this cascade. The Workflow Principle "never force-push a tag" is absolute — every fix is a new patch tag, never a tag rewrite.

**Trigger**: a defect is observed during Slice 4 (synthetic-consumer install/import/load_session) or Slice 5 (real-consumer flow) that traces to content shipped inside `darce/mcp-agent-handoff@v0.1.0`, `darce/mcp-agent-orchestrator@v0.1.0`, or `darce/agentic-system@v0.1.0`.

**Version-bump rule**: bump the patch component only (`v0.1.0` → `v0.1.1`). Never reuse a tag name. Never `git push --force` a tag. Never delete a published tag from the remote (deleted tags can still be cached by `pip` and bootstrap clients).

**Cascade** (apply in this order; stop at the lowest-affected layer):

1. **Defect in `agent-handoff-mcp` content**:
   - Re-extract handoff using the Slice 1 recipe with the fix already applied in the monorepo `packages/agent-handoff-mcp/`.
   - New initial commit message: `"Re-extraction from context-alt-text-monorepo@<new-monorepo-sha> — agent-handoff-mcp v0.1.1"`.
   - Tag `v0.1.1`, push `main` and tag.
   - Then **MUST cascade to orchestrator** (next step), because orchestrator's published `v0.1.0` still pins handoff `@v0.1.0`.
   - Then **MUST cascade to consumer re-install**.
2. **Defect in `agent-orchestrator-mcp` content** (or cascade trigger from step 1):
   - Re-extract orchestrator using the Slice 2 recipe.
   - Retarget the handoff dep in the staged `pyproject.toml` to the latest published handoff tag (`@v0.1.1` if step 1 ran, else `@v0.1.0`).
   - New initial commit: `"Re-extraction from context-alt-text-monorepo@<sha> — agent-orchestrator-mcp v0.1.1 (handoff dep pinned at v0.1.<N>)"`.
   - Tag `v0.1.1`, push.
   - Then **MUST cascade to consumer re-install**.
3. **Defect in `agentic-system` shared surface** (or independently):
   - Re-extract using the Slice 3 recipe; tag `v0.1.1`; push.
   - Then **MUST cascade to consumer re-install** (bootstrap CLI clones `agentic-system@<tag>` per `agentic-bootstrap` config).
4. **Consumer re-install** (synthetic + both real):
   - In each consumer's venv: `pip install --upgrade "git+ssh://...mcp-agent-handoff.git@v0.1.<N>" "git+ssh://...mcp-agent-orchestrator.git@v0.1.<N>"` (and re-run `agentic-bootstrap install --target .` if `agentic-system` was re-tagged).
   - Re-run the Slice 4 / Slice 5 proof commands against the new tags.
   - Replace any prior `test_result` records: record fresh `test_result` events tied to the new branch HEAD AND naming the new tag in the `command` field.

**Documentation**: every cascade execution appends a dated entry to the new `## Lessons Learned` block in `docs/agentic/consumer-setup.md` (per Slice 5) capturing trigger, layers re-tagged, and consumer re-install duration. The cascade itself is in scope of this task; opening a new follow-on task is only required if the defect needs source-code changes inside `packages/agent-{handoff,orchestrator}-mcp/src/` (see Constraints — extraction-only scope).

**Anti-pattern**: do NOT attempt to short-circuit the cascade by re-tagging only the lowest-affected layer. If handoff defect ships, orchestrator and bootstrap clients still resolve handoff `@v0.1.0` transitively until orchestrator is also re-tagged with the updated dep pin.

## Files and Surfaces to Change

| Surface                                | File                                                                       | Change                                                                                                              |
| -------------------------------------- | -------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------- |
| Standalone repo `darce/mcp-agent-handoff`        | (extraction repo) `~/Development/mcp-agent-handoff/`                       | Initial commit from monorepo `packages/agent-handoff-mcp/`; tag `v0.1.0`; push                                       |
| Standalone repo `darce/mcp-agent-orchestrator`   | (extraction repo) `~/Development/mcp-agent-orchestrator/`                  | Initial commit from monorepo `packages/agent-orchestrator-mcp/` with `pyproject.toml` dep retargeted to `@v0.1.0`; tag `v0.1.0`; push |
| Standalone repo `darce/agentic-system`           | (extraction repo) `~/Development/agentic-system/`                          | Initial commit from monorepo shared surface (`.claude/skills/`, `.github/hooks/`, `scripts/hooks/`, `.github/prompts/`, `docs/agentic/contracts/`, `.claude/commands/`, `config/agent-workflows/portable_commands.json`, `scripts/generate_agent_workflows.py`, `scripts/check_skills.py`, `scripts/check_harness_sync.py`); tag `v0.1.0`; push |
| Synthetic consumer                      | `~/Development/hoist-mvp-consumer/`                                        | Create fresh git repo, run install + `agentic-bootstrap install` + first `load_session`                              |
| Real consumer 1                         | `~/Development/darce.github.io/`                                           | Run install + `agentic-bootstrap install` + first `load_session` on a feature branch in that repo                    |
| Real consumer 2                         | `~/Development/altcontext-marketing-monorepo/`                             | Same as above                                                                                                       |
| Consumer setup doc                      | `docs/agentic/consumer-setup.md` (in this monorepo)                        | Append `## Lessons Learned` block with real-consumer onboarding observations (or "no lessons")                       |
| Task plan                               | `docs/tasks/17.0/E17-10-followon-publish-and-validate-task-plan.md`        | This plan                                                                                                            |

## Related Files

| File                                                                | Note                                                                                                  |
| ------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| `scripts/test_e17_10_p1_handoff_remote.py`                          | Reused as Slice 1 proof; runs against the freshly-tagged remote                                       |
| `scripts/test_e17_10_p2_orchestrator_remote.py`                     | Reused as Slice 2 proof                                                                               |
| `scripts/test_e17_10_p3_agentic_remotes.py`                         | Reused as Slice 3 proof                                                                               |
| `packages/agent-handoff-mcp/scripts/release_mcp_package.sh`         | Optional helper for Slice 1 tagging if it exists in the merged tree                                   |
| `packages/agent-orchestrator-mcp/scripts/release_mcp_package.sh`    | Optional helper for Slice 2 tagging                                                                   |
| `~/Development/agentic-bootstrap/` (local clone of `darce/agentic-bootstrap`) | Already at `v0.2.0`; Slices 4+5 install from this published version                                   |

## Verification Strategy

- Deterministic per-slice tests:
  - Slice 1 proof: `git ls-remote --tags git@github.com:darce/mcp-agent-handoff.git | grep refs/tags/v0.1.0` AND `python3 scripts/test_e17_10_p1_handoff_remote.py` (the existing remote-smoke script).
  - Slice 2 proof: same pattern for `mcp-agent-orchestrator` AND `python3 scripts/test_e17_10_p2_orchestrator_remote.py`.
  - Slice 3 proof: same pattern for `agentic-system` AND `python3 scripts/test_e17_10_p3_agentic_remotes.py`.
- Runtime-parity / environment checks:
  - Slice 4 proof: in a scratch venv, `pip install "git+ssh://...mcp-agent-handoff.git@v0.1.0" "git+ssh://...mcp-agent-orchestrator.git@v0.1.0" "git+ssh://...agentic-bootstrap.git@v0.2.0"`, then `cd ~/Development/hoist-mvp-consumer && agentic-bootstrap install --target .` and `python3 -c "from agent_handoff_mcp import RuntimeConfig, configure_runtime, load_session; from pathlib import Path; configure_runtime(RuntimeConfig.for_repo(Path('.'))); print(load_session(task_ref='HOIST-MVP-PROBE'))"`.
  - Slice 5 proof: same as Slice 4 but executed in `~/Development/darce.github.io/` AND `~/Development/altcontext-marketing-monorepo/`. Each consumer's `<consumer-root>/.task-state/handoff.db` exists and contains a row for `HOIST-MVP-PROBE` keyed to that consumer's path.
- Contract/fixture verification:
  - Each slice records a `test_result` event tied to the branch HEAD via `record_event(event_kind="test_result", task_ref="E17-10-followon-publish-and-validate", actor=..., command=<exact command>, passed=True, result=<stdout summary>)`.
- Manual verification:
  - After Slice 5, eyeball each consumer's `DASHBOARD.txt` (rendered by `make context` or by the first `load_session`) to confirm only its own `HOIST-MVP-PROBE` task appears, with no leakage from any other consumer.

## Slice Delivery

### Slice 1 — P1: extract `agent-handoff-mcp` and tag `v0.1.0` on `darce/mcp-agent-handoff`

**Goal**: populate the empty `darce/mcp-agent-handoff` remote with the current monorepo `packages/agent-handoff-mcp/` content as a single initial commit, tag `v0.1.0`, and prove a fresh `pip install` resolves.

Changes:

- Use a clean staging dir (`~/Development/mcp-agent-handoff/` is already empty and not a git clone — `rm -rf` is safe). Clone the empty `darce/mcp-agent-handoff` remote there.
- `rsync --archive --delete --exclude='.git' --exclude='__pycache__' --exclude='*.pyc' --exclude='.pytest_cache' --exclude='build' --exclude='dist' --exclude='*.egg-info' /Users/daniel/Development/context-alt-text-monorepo-e17-10-followon-publish-and-validate/packages/agent-handoff-mcp/ ~/Development/mcp-agent-handoff/`.
- **Rewrite release metadata to match the tag (PR-M-01):** edit `~/Development/mcp-agent-handoff/pyproject.toml` and set `version = "0.1.0"` (the monorepo source declares `0.4.0`, which would create a tag-vs-package-metadata split). Verify `~/Development/mcp-agent-handoff/CHANGELOG.md` has a `## 0.1.0 — initial standalone release` heading at the top (add it if absent). The pre-commit grep below MUST confirm `version = "0.1.0"` in the staged `pyproject.toml`.
- Verify the staged tree contains `pyproject.toml` with `[tool.hoisted]` table pointing at the standalone-repo URL pattern AND `version = "0.1.0"`; verify `CHANGELOG.md` carries a `0.1.0` heading; verify no `apps/`, `context-alt-text-monorepo`, or other monorepo-only path literals leak into the staged tree (`grep -r --include='*.py' --include='*.toml' --include='*.md' 'context-alt-text-monorepo\|/Users/daniel\|apps/prototype' ~/Development/mcp-agent-handoff/` returns nothing).
- `cd ~/Development/mcp-agent-handoff && git add -A && git commit -m "Initial extraction from context-alt-text-monorepo@d9aa69e5 — agent-handoff-mcp v0.1.0"`.
- `git tag -a v0.1.0 -m "v0.1.0 — initial standalone release per E17-10 Slice 0/1"`.
- `git push origin main && git push origin v0.1.0`.

Proof:

- `git ls-remote --tags git@github.com:darce/mcp-agent-handoff.git | grep -q 'refs/tags/v0.1.0'` exits 0.
- `python3 -m venv /tmp/e17-followon-p1 && /tmp/e17-followon-p1/bin/pip install --quiet "git+ssh://git@github.com/darce/mcp-agent-handoff.git@v0.1.0" && /tmp/e17-followon-p1/bin/python -c "import agent_handoff_mcp; from pathlib import Path; from agent_handoff_mcp import RuntimeConfig, configure_runtime, record_event; configure_runtime(RuntimeConfig(state_dir=Path('/tmp/e17-followon-p1-state'))); print('OK', agent_handoff_mcp.__file__)"` succeeds and prints a path under `site-packages/` (NOT under `packages/`).
- `python3 scripts/test_e17_10_p1_handoff_remote.py` exits 0.
- MCP `test_result` recorded with `command="git ls-remote ... && pip install ... && import agent_handoff_mcp"`, `passed=True`.

### Slice 2 — P2: extract `agent-orchestrator-mcp` with retargeted dep and tag `v0.1.0` on `darce/mcp-agent-orchestrator`

**Goal**: populate `darce/mcp-agent-orchestrator` with monorepo `packages/agent-orchestrator-mcp/` content, retarget the `agent-handoff-mcp` dep to the freshly-tagged `@v0.1.0`, tag `v0.1.0`, and prove transitive `pip install` resolves both packages from standalone remotes.

Changes:

- Clean stage `~/Development/mcp-agent-orchestrator/`; clone the empty remote.
- `rsync --archive --delete --exclude='.git' --exclude='__pycache__' --exclude='*.pyc' --exclude='.pytest_cache' --exclude='build' --exclude='dist' --exclude='*.egg-info' .../packages/agent-orchestrator-mcp/ ~/Development/mcp-agent-orchestrator/`.
- Edit `~/Development/mcp-agent-orchestrator/pyproject.toml`: change the `agent-handoff-mcp` dep entry from its current floating form (`git+ssh://git@github.com/darce/mcp-agent-handoff.git`) to the tagged form (`git+ssh://git@github.com/darce/mcp-agent-handoff.git@v0.1.0`). Verify no path-based dep (`packages/agent-handoff-mcp`, `../agent-handoff-mcp`, `-e`) remains.
- **Rewrite release metadata to match the tag (PR-M-01):** set `version = "0.1.0"` in `~/Development/mcp-agent-orchestrator/pyproject.toml` (overrides whatever the monorepo source declared). Add or confirm a `## 0.1.0 — initial standalone release` heading in `~/Development/mcp-agent-orchestrator/CHANGELOG.md`.
- Path-leak grep as in Slice 1.
- `git add -A && git commit -m "Initial extraction from context-alt-text-monorepo@d9aa69e5 — agent-orchestrator-mcp v0.1.0 (handoff dep pinned at v0.1.0)"`.
- Tag and push as in Slice 1.

Proof:

- `git ls-remote --tags git@github.com:darce/mcp-agent-orchestrator.git | grep -q 'refs/tags/v0.1.0'` exits 0.
- `python3 -m venv /tmp/e17-followon-p2 && /tmp/e17-followon-p2/bin/pip install --quiet "git+ssh://git@github.com/darce/mcp-agent-orchestrator.git@v0.1.0" && /tmp/e17-followon-p2/bin/python -c "import agent_orchestrator_mcp, agent_handoff_mcp; print('orch=', agent_orchestrator_mcp.__file__); print('handoff=', agent_handoff_mcp.__file__)"` succeeds; both paths under `site-packages/` of `/tmp/e17-followon-p2/`, neither under `packages/` of the monorepo.
- `python3 scripts/test_e17_10_p2_orchestrator_remote.py` exits 0.
- MCP `test_result` recorded.

### Slice 3 — P3: extract shared agentic surface and tag `v0.1.0` on `darce/agentic-system`

**Goal**: populate `darce/agentic-system` with the monorepo's shared agentic surface as a single initial commit, tag `v0.1.0`, and prove the bootstrap CLI's clone target resolves.

Changes:

- Clean stage `~/Development/agentic-system/` (does not exist yet); clone the empty remote.
- `rsync --archive` each shared-surface source to its expected position in the new repo:
  - `.claude/skills/` → `.claude/skills/`
  - `.github/hooks/` → `.github/hooks/`
  - `scripts/hooks/` → `scripts/hooks/`
  - `.github/prompts/` → `.github/prompts/`
  - `docs/agentic/contracts/` → `docs/agentic/contracts/`
  - `.claude/commands/` → `.claude/commands/`
  - `config/agent-workflows/portable_commands.json` → `config/agent-workflows/portable_commands.json`
  - `scripts/generate_agent_workflows.py` → `scripts/generate_agent_workflows.py`
  - `scripts/check_skills.py` → `scripts/check_skills.py`
  - `scripts/check_harness_sync.py` → `scripts/check_harness_sync.py`
  - `scripts/overlay_resolver.py` → `scripts/overlay_resolver.py`
  - `scripts/lint_hoisted_paths.py` → `scripts/lint_hoisted_paths.py`
- Add a top-level `README.md` naming this as a private internal surface (no LICENSE, no CONTRIBUTING per E17-10's no-open-sourcing constraint).
- Run `python3 scripts/lint_hoisted_paths.py ~/Development/agentic-system/` (executed against the staged tree, not the monorepo) to fail if any monorepo-only path literal leaked through.
- `git add -A && git commit -m "Initial extraction from context-alt-text-monorepo@d9aa69e5 — agentic-system v0.1.0 (shared skills, hooks, contracts, commands)"`.
- Tag and push.

Proof:

- `git ls-remote --tags git@github.com:darce/agentic-system.git | grep -q 'refs/tags/v0.1.0'` exits 0.
- `git clone --depth 1 --branch v0.1.0 git@github.com:darce/agentic-system.git /tmp/agentic-system-smoke && ls /tmp/agentic-system-smoke/.claude/skills/ | grep -q branch-lifecycle && ls /tmp/agentic-system-smoke/docs/agentic/contracts/ | grep -q harness-protocol.yaml` exits 0.
- `python3 scripts/test_e17_10_p3_agentic_remotes.py` exits 0.
- `python3 scripts/lint_hoisted_paths.py /tmp/agentic-system-smoke/` exits 0.
- MCP `test_result` recorded.

### Slice 4 — Synthetic-consumer end-to-end validation (Slice 5 from E17-10)

**Goal**: prove the documented consumer install + first `load_session` works against a fresh scratch repo.

Changes:

- **Pre-flight: bootstrap-version reconciliation (PR-H-01).** The bootstrap CLI is already published at `v0.2.0` but `docs/agentic/consumer-setup.md`, `scripts/test_consumer_setup_doc.py`, and the E17-10 P3 remote-smoke gate still pin `@v0.1.0`. Before any install, on this task branch (in the monorepo worktree): (a) edit `docs/agentic/consumer-setup.md` to replace `agentic-bootstrap.git@v0.1.0` with `@v0.2.0` in both the install and update sections; (b) update the doc-lock fixture in `scripts/test_consumer_setup_doc.py` (lines 25 and 67) to expect `@v0.2.0`; (c) run `python3 scripts/test_consumer_setup_doc.py` and confirm it passes; (d) verify the E17-10 P3 remote-smoke gate (`scripts/test_e17_10_p3_agentic_remotes.py` if it exists, otherwise the inline assertion in the smoke script) reflects `@v0.2.0`; (e) commit the doc + test updates on this task branch with message `docs(E17-10-followon): align bootstrap pins to published v0.2.0 (PR-H-01)`.
- `mkdir -p ~/Development/hoist-mvp-consumer && cd ~/Development/hoist-mvp-consumer && git init --initial-branch=main && echo "# hoist-mvp-consumer" > README.md && git add README.md && git commit -m "Initial commit"`.
- Create scratch venv: `python3 -m venv ~/Development/hoist-mvp-consumer/.venv && source ~/Development/hoist-mvp-consumer/.venv/bin/activate`.
- Install all four packages from real standalone SSH remotes (no monorepo URL fallback): `pip install "git+ssh://git@github.com/darce/mcp-agent-handoff.git@v0.1.0" "git+ssh://git@github.com/darce/mcp-agent-orchestrator.git@v0.1.0" "git+ssh://git@github.com/darce/agentic-bootstrap.git@v0.2.0"`.
- `cd ~/Development/hoist-mvp-consumer && agentic-bootstrap install --target .` (clones `darce/agentic-system.git@v0.1.0` into `.agentic/remote/` and writes symlinks + `.agentic-overlay.json`).
- `python3 -c "from agent_handoff_mcp import RuntimeConfig, configure_runtime, load_session; from pathlib import Path; configure_runtime(RuntimeConfig.for_repo(Path('.'))); print(load_session(task_ref='HOIST-MVP-PROBE'))"`.

Proof:

- `agentic-bootstrap install --target ~/Development/hoist-mvp-consumer/` exits 0.
- `ls ~/Development/hoist-mvp-consumer/.agentic-overlay.json ~/Development/hoist-mvp-consumer/.claude/skills ~/Development/hoist-mvp-consumer/scripts/hooks ~/Development/hoist-mvp-consumer/docs/agentic/contracts/harness-protocol.yaml` all exist (some may be symlinks).
- `load_session(task_ref="HOIST-MVP-PROBE")` returns a structured response (not an exception); the file `~/Development/hoist-mvp-consumer/.task-state/handoff.db` exists; the consumer's task surface is queryable via the public API (no raw `sqlite3` reads — per `rg-018`): `python3 -c "from pathlib import Path; from agent_handoff_mcp import RuntimeConfig, configure_runtime, get_handoff_state; configure_runtime(RuntimeConfig.for_repo(Path('/Users/daniel/Development/hoist-mvp-consumer'))); s = get_handoff_state(sections='identity'); assert 'HOIST-MVP-PROBE' in (s.get('data', {}).get('active', {}) or {}).get('task_ref', ''), s; print('handoff API OK; active=', s['data']['active']['task_ref'])"` exits 0.
- The handoff path is the consumer root (`~/Development/hoist-mvp-consumer/`), NOT `/Users/daniel/Development/context-alt-text-monorepo/.task-state/`.
- MCP `test_result` recorded with the install command sequence and the `load_session` output.

### Slice 5 — Real-consumer end-to-end validation (mandatory: both `darce.github.io` AND `altcontext-marketing-monorepo`)

**Goal**: prove the consumer flow works against two real Daniel-owned repos that exist independently of this monorepo. This is the closing argument that the hoist is provably hoisted.

Changes (per consumer, run for both `~/Development/darce.github.io/` and `~/Development/altcontext-marketing-monorepo/`):

- Pre-flight: confirm the consumer dir exists and is a git repo; record its current branch and working-tree state. If dirty, stop and ask the user how to proceed (constitution `rg-017` — never destroy uncommitted work).
- Create a feature branch in the consumer (`git checkout -b feature/agentic-system-onboarding`) so the install does not pollute its `main`.
- Create a project-local venv at `<consumer>/.venv` (or use an existing one if the consumer already has Python tooling — record which path was used).
- Run the same install command sequence as Slice 4 against this consumer.
- Run `agentic-bootstrap install --target .` against this consumer.
- Run `load_session(task_ref="HOIST-MVP-PROBE-<consumer-shortname>")` from the consumer root with `RuntimeConfig.for_repo(Path('.'))`.

Proof (per consumer):

- The same four checks from Slice 4 pass for this consumer.
- `<consumer-root>/.task-state/handoff.db` exists and is distinct from the synthetic consumer's DB and from this monorepo's DB (`stat` paths and inodes differ — file-existence/inode comparison only; do NOT open the DB with `sqlite3`).
- Cross-consumer isolation probe via the public API (per `rg-018`; no raw `sqlite3`). Run this exact one-liner from any cwd; it scopes `RuntimeConfig` to each consumer in turn and asserts that each runtime sees ONLY its own probe task_ref: `python3 -c "from pathlib import Path; from agent_handoff_mcp import RuntimeConfig, configure_runtime, search_handoff; 
for root, own, foreign in [('/Users/daniel/Development/hoist-mvp-consumer', 'HOIST-MVP-PROBE', ['darce-github-io', 'altcontext-marketing']), ('/Users/daniel/Development/darce.github.io', 'HOIST-MVP-PROBE-darce-github-io', ['hoist-mvp-consumer', 'altcontext-marketing']), ('/Users/daniel/Development/altcontext-marketing-monorepo', 'HOIST-MVP-PROBE-altcontext-marketing', ['hoist-mvp-consumer', 'darce-github-io'])]:
    configure_runtime(RuntimeConfig.for_repo(Path(root)))
    res = search_handoff(query='', limit=200)
    refs = [r.get('task_ref', '') for r in (res.get('data', {}).get('rows') or res.get('data', {}).get('results') or [])]
    assert any(own in r for r in refs), (root, own, refs)
    assert not any(any(f in r for f in foreign) for r in refs), (root, foreign, refs)
    print('isolated:', root, '->', refs)"` exits 0 AND prints three lines, one per consumer, each listing only that consumer's own probe task_ref(s).
- MCP `test_result` recorded for each consumer separately, naming the consumer in the `result` field.

After both consumers pass, append a `## Lessons Learned` block to `docs/agentic/consumer-setup.md` (in the monorepo) summarizing any rough edges discovered or asserting "no lessons — install was clean for both real consumers." Commit that doc update on this task branch.

Proof of close-out:

- `handoff_close_check(task_ref="E17-10-followon-publish-and-validate", enforce=True, require_fresh_tests=True, current_commit_sha=<branch HEAD>)` returns `ready_to_close: true`.

---

## Consolidated Checklist

## Context and Ownership

- [ ] Loaded the minimum authoritative rules, contracts, and handoff state before editing.
- [ ] Confirmed `ctx7` is not needed (no upstream library behavior in scope).
- [ ] Recorded boundary ownership for the four published artifacts and the per-consumer handoff DB contract.

### Checklist for Slice 1: P1 extract `agent-handoff-mcp`

- [ ] Pre-flight: `gh repo view darce/mcp-agent-handoff` shows empty repo; `~/Development/mcp-agent-handoff/` is empty (not a git clone).
- [ ] Clone empty `darce/mcp-agent-handoff` into `~/Development/mcp-agent-handoff/`.
- [ ] `rsync --archive --delete` from monorepo `packages/agent-handoff-mcp/` excluding `.git`, build artifacts, caches.
- [ ] Path-leak grep against staged tree returns no matches for `context-alt-text-monorepo`, `/Users/daniel`, `apps/prototype`.
- [ ] Single initial commit + tag `v0.1.0` + push `main` + push `v0.1.0`.
- [ ] Scratch-venv install proof passes; `agent_handoff_mcp.__file__` resolves under `site-packages/`.
- [ ] `python3 scripts/test_e17_10_p1_handoff_remote.py` exits 0.
- [ ] MCP `test_result` recorded against branch HEAD.

### Checklist for Slice 2: P2 extract `agent-orchestrator-mcp` with retargeted dep

- [ ] Pre-flight: Slice 1 tag `v0.1.0` is live (otherwise the retargeted dep is unresolvable).
- [ ] Clone empty `darce/mcp-agent-orchestrator` into `~/Development/mcp-agent-orchestrator/`.
- [ ] `rsync --archive --delete` from monorepo `packages/agent-orchestrator-mcp/`.
- [ ] Edit `pyproject.toml` to retarget `agent-handoff-mcp` dep to `git+ssh://git@github.com/darce/mcp-agent-handoff.git@v0.1.0`.
- [ ] Verify no path-based or floating handoff dep remains (`grep -E 'agent-handoff-mcp|packages/agent-handoff' pyproject.toml`).
- [ ] Path-leak grep against staged tree.
- [ ] Single initial commit + tag `v0.1.0` + push.
- [ ] Scratch-venv transitive install proof: both packages resolve under one `site-packages/`, neither under monorepo `packages/`.
- [ ] `python3 scripts/test_e17_10_p2_orchestrator_remote.py` exits 0.
- [ ] MCP `test_result` recorded.

### Checklist for Slice 3: P3 extract shared agentic surface

- [ ] Pre-flight: `gh repo view darce/agentic-system` shows empty repo.
- [ ] Clone empty `darce/agentic-system` into `~/Development/agentic-system/`.
- [ ] `rsync --archive` each shared-surface source to its expected position in the new repo.
- [ ] Add `README.md` naming the repo as MVP-scope private (no LICENSE, no CONTRIBUTING).
- [ ] `python3 scripts/lint_hoisted_paths.py ~/Development/agentic-system/` exits 0.
- [ ] Single initial commit + tag `v0.1.0` + push.
- [ ] Smoke clone of `git@github.com:darce/agentic-system.git@v0.1.0` lists expected skill + contract files.
- [ ] `python3 scripts/test_e17_10_p3_agentic_remotes.py` exits 0.
- [ ] MCP `test_result` recorded.

### Checklist for Slice 4: synthetic-consumer validation

- [ ] Pre-flight: Slices 1-3 all green; all three `v0.1.0` tags live remotely.
- [ ] Create `~/Development/hoist-mvp-consumer/` with `git init` + initial README commit.
- [ ] Create scratch venv at `~/Development/hoist-mvp-consumer/.venv`.
- [ ] `pip install` the three published packages from real `git+ssh://` URLs (no monorepo fallback).
- [ ] `agentic-bootstrap install --target .` exits 0; symlinks + `.agentic-overlay.json` present.
- [ ] First `load_session(task_ref="HOIST-MVP-PROBE")` returns structured response.
- [ ] `~/Development/hoist-mvp-consumer/.task-state/handoff.db` exists; the consumer's task surface is queryable via `agent_handoff_mcp` public API (no raw `sqlite3` reads, per `rg-018`).
- [ ] Handoff DB path is the synthetic consumer root, NOT the monorepo's `.task-state/`.
- [ ] MCP `test_result` recorded.

### Checklist for Slice 5: real-consumer validation (both consumers required)

- [ ] Pre-flight `darce.github.io`: dir exists, is a git repo, working tree clean (or user cleared the dirty state).
- [ ] Pre-flight `altcontext-marketing-monorepo`: same check.
- [ ] Created onboarding feature branch in each real consumer (no edits to their `main`).
- [ ] Per-consumer scratch venv (or recorded existing venv path) for each.
- [ ] `pip install` of all three packages succeeds for each consumer.
- [ ] `agentic-bootstrap install --target .` succeeds for each consumer.
- [ ] First `load_session` succeeds for each consumer with consumer-scoped `task_ref`.
- [ ] Per-consumer handoff DB exists at consumer root; isolation between the three consumer DBs (synthetic + 2 real) confirmed by inode + content check.
- [ ] `## Lessons Learned` section appended to `docs/agentic/consumer-setup.md` (in this monorepo) and committed on the task branch.
- [ ] MCP `test_result` recorded for each consumer separately.

## Review Readiness

- [ ] Every published-artifact slice (1-3) has both a `git ls-remote` proof AND a fresh-venv install proof recorded as `test_result`.
- [ ] Every consumer slice (4-5) has a `load_session` round-trip proof recorded as `test_result`.
- [ ] Per-consumer DB isolation evidence is captured (paths + selected row inspection) in MCP rationale or test_result `result` field.
- [ ] No source files in `packages/agent-{handoff,orchestrator}-mcp/src/` were modified in this monorepo (constitution rg-013, rg-014 preserved by extraction-only scope).
- [ ] Handoff decision records the slice, verification, and contract impact at each `close_slice` boundary.

## Stretch Goals

- [ ] (optional) Add a `make check-real-consumer-isolation` recipe that re-runs the Slice 5 isolation probe across all three consumer DBs in one shot — useful for future regression checks but not required for MVP close.
- [ ] (optional) Document the `mcp-agent-handoff` and `mcp-agent-orchestrator` `v0.1.0` tag SHAs in `CHANGELOG.md` for both packages in the monorepo, cross-linking back to this task plan, so the historical extraction point is greppable from `main`.

## Success Criteria

- [ ] All four `darce/<repo>` standalone remotes carry `v0.1.0` tags (or `v0.2.0` for `agentic-bootstrap`); `git ls-remote --tags` proof recorded in MCP.
- [ ] Synthetic consumer at `~/Development/hoist-mvp-consumer/` runs the full documented install + first `load_session` end-to-end with no manual intervention.
- [ ] BOTH real consumers (`darce.github.io` AND `altcontext-marketing-monorepo`) run the same flow successfully, each writing to their own per-consumer handoff DB with no leakage.
- [ ] `handoff_close_check(enforce=True, require_fresh_tests=True)` returns `ready_to_close: true` on the task branch HEAD.
- [ ] `## Lessons Learned` section in `docs/agentic/consumer-setup.md` reflects real-consumer experience (or asserts "no lessons").
