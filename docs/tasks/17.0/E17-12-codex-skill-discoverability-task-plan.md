# E17-12. Codex Harness $-Skill Discoverability

- **Date**: 2026-04-18
- **Author**: Codex
- **Owning Epic**: [docs/epics/v0.4.0/skill-formalization-and-process-automation-epic.md](../../epics/v0.4.0/skill-formalization-and-process-automation-epic.md)
- **Epic Short ID**: E17
- **Target Branch**: `feature/e17-12` (branch created during scope migration from `main`; planning review runs on the feature branch per the updated planning-docs-on-feature-branch guidance)
- **Review Coverage Target**: 2
- **Hard Prerequisites**: E17-4 and E17-7 have merged to `main` (verified 2026-04-18: `config/agent-workflows/portable_commands.json`, `scripts/generate_agent_workflows.py`, the Codex router blocks in `docs/agentic/instructions.md` and `CLAUDE.md`, and the generated Claude/Copilot adapters are on `main`). E17-12 is epic-derived follow-up work filed after the E17 phase mapping (E17-1..E17-7 across Phases 1-4) was frozen; it corrects E17-4 / E17-7 docs and closes the harness-discoverability gap those slices surfaced. Update the owning epic's phase list under a new "Phase 5 — Harness Discoverability Follow-up" heading as part of Slice 3 docs reconciliation.

---

## Objective

Close the Codex harness discoverability gap: ship the smallest repo-committed registration path that makes `$-prefix` skills under `.claude/skills/` resolve in the Codex harness for any fresh clone, without modifying the Codex product and without mutating per-user machine config. If the discovery slice confirms no repo-only registration path exists, retire the gap-closing promise explicitly in the docs rather than softening it.

## Problem Statement

The 2026-04-18 assessment (`packages/agent-handoff-mcp/docs/assessments/codex-harness-slash-tools-and-skill-discovery-investigation-2026-04-18.md`) showed that E17-4 / E17-7 shipped Codex parity at the **instruction-routing** layer only:

1. The canonical manifest `config/agent-workflows/portable_commands.json` + generated Codex router prose in `docs/agentic/instructions.md` and `CLAUDE.md` teach a model to **interpret** `/branch-review` text.
2. There is no Codex-side artifact that registers repo-local `.claude/skills/` as a skill root.
3. `.codex/config.toml` registers MCP servers and hooks but declares no skill roots.
4. The checked-in protocol fixture at `packages/codex-subagent-bridge/tests/fixtures/codex_app_server_protocol.v2.schemas.json` shows Codex supports `skills/list` (with `perCwdExtraUserRoots`), `skills/config/write` (`{enabled, path}`), and `SkillsChangedNotification`, but the repo never calls those.

Result in practice: `$branch-review` does not resolve in Codex, and `/branch-review` depends on instruction-prose routing that is weaker than native discovery.

The user's intake decision (handoff ledger id 1963, task_ref `E17-12`) chose: pursue **$-prefix skill resolvability** + **reproducible for any fresh clone**, with a **time-boxed discovery** slice first.

## Constraints

- All changes live in this monorepo. No patches to the Codex binary/app-server.
- No mutation of per-user machine config (`~/.codex/`, global user profile, shell rc files) as part of normal workflow. Any bootstrap step must be repo-committed and reproducible on a fresh clone.
- `config/agent-workflows/portable_commands.json` remains the only command/skill registry. Any Codex-side artifact that ships is generated from the manifest by `scripts/generate_agent_workflows.py`.
- No expansion to other harnesses (Cursor, Zed, JetBrains). Claude and VS Code/Copilot parity is already shipped and out of scope here.
- No `/`-prefix slash-command UI parity in Codex is a success criterion. Only `$`-prefix skill resolution is pursued. If the discovery slice shows slash-UI registration is available at zero extra cost, it may be evaluated separately but is not a gate for this task.
- `agent-handoff-mcp` and `agent-orchestrator-mcp` wiring under `.codex/config.toml` is orthogonal and stays untouched.
- Planning review must pass on `main` before `make task-start` creates the feature branch + worktree.

## Current State Analysis

- **`.codex/config.toml`** registers MCP servers (`context7`, `altcontext-mcp`, `altcontext-orchestrator-mcp`) and `codex_hooks = true`. No skill roots, no command registry.
- **`.claude/skills/`** contains multiple skill directories (including `branch-review`, `planning-review`, `scope`, `tdd`, `auto-fix`, etc.; the exact count is not load-bearing — any count drift is acceptable as long as the generator iterates over manifest entries rather than directory listings). No Codex-side wiring points at this directory.
- **`config/agent-workflows/portable_commands.json`** version 1; 10 commands declared.
- **`scripts/generate_agent_workflows.py`** renders three outputs: Claude command files under `.claude/commands/`, VS Code/Copilot prompts under `.github/prompts/`, and Codex router prose injected between `<!-- BEGIN/END GENERATED: codex-command-router -->` marker blocks in `docs/agentic/instructions.md` and `CLAUDE.md`. Generator has no Codex skill-registration code path.
- **Codex app-server protocol (fixture)** exposes: `skills/list` with `cwds`, `forceReload`, `perCwdExtraUserRoots`; `skills/config/write` with `{enabled: bool, path: str}`; `SkillsChangedNotification` for local skill file changes. The live Codex binary's handling of these requests from a repo-committed bootstrap is not yet confirmed in this workspace.
- **`make check-agent-workflows`** verifies Claude, Copilot, and Codex router outputs match the manifest. No Codex skill-root output is checked because none is generated.

## Out of Scope

- Codex binary / app-server modifications.
- Per-user machine config mutation (`~/.codex/`, global profile, shell rc).
- Cursor, Zed, JetBrains, or other harnesses beyond Claude + VS Code/Copilot + Codex.
- Re-architecture of `portable_commands.json` (schema stays as-is).
- Native `/command` UI parity in Codex (only `$skill` resolution is in scope).
- Truth-in-advertising-only outcome (docs reconciliation must either describe shipped gap-closing behavior or explicitly retire the promise; not merely soften existing claims).
- Graduating the E17-4 warning-only main-branch edit guard (separate task).
- Bootstrap that writes to a path outside the repo.

## Target Outcome

- `$branch-review` resolves in the Codex harness against `.claude/skills/branch-review/` on a fresh clone of this repo, without the operator editing any file outside the cloned tree.
- At least one additional `$skill` (e.g. `$planning-review`, `$tdd`, `$auto-fix`) resolves the same way, to confirm the registration is generic across all manifest entries. `$auto-fix` is the canonical regression case: the 2026-04-18 user report `"/auto-fix isn't a recognized command here. Some commands only work in the Claude Code terminal."` exposed the gap by hitting a non-Claude-Code harness with a valid manifest-declared skill and getting a not-recognized error. If the implementation slice ships, `$auto-fix` must pass the fresh-clone probe alongside `$branch-review`.
- `docs/tasks/17.0/E17-4-workflow-integrity-task-plan.md`, `docs/tasks/17.0/E17-7-handoff-evolution-and-portable-workflow-task-plan.md`, and `docs/agentic/instructions.md` accurately describe Codex parity — no overstated "UI-level discoverability" claims that the shipped code does not support.
- `config/agent-workflows/portable_commands.json` remains the single registry; any Codex-side artifact is generated by `scripts/generate_agent_workflows.py` with a new render function, not handwritten.
- `make check-agent-workflows` extends to verify the new Codex skill-registration output (or its intentional absence if Slice 1 shows no repo-only path exists).
- If the discovery slice confirms no repo-only path exists, `docs/agentic/instructions.md` and the two upstream task plans are updated to describe that limitation explicitly and retire the UI-parity promise.

## Context Loading

- Assessment: [`packages/agent-handoff-mcp/docs/assessments/codex-harness-slash-tools-and-skill-discovery-investigation-2026-04-18.md`](../../../packages/agent-handoff-mcp/docs/assessments/codex-harness-slash-tools-and-skill-discovery-investigation-2026-04-18.md)
- Scope: [`docs/scopes/e17-12-codex-skill-discoverability-scope.md`](../../scopes/e17-12-codex-skill-discoverability-scope.md)
- Codex protocol fixture: `packages/codex-subagent-bridge/tests/fixtures/codex_app_server_protocol.v2.schemas.json` — definitions `SkillsListParams`, `SkillsConfigWriteParams`, `SkillsChangedNotification`, and request entries `skills/list` and `skills/config/write`. Reference definitions by name; line numbers drift with every fixture regeneration.
- Current Codex config: `.codex/config.toml`
- Canonical manifest: `config/agent-workflows/portable_commands.json`
- Generator: `scripts/generate_agent_workflows.py` — Codex router rendering via `_render_codex_router_body`; router consumers declared in `CODEX_ROUTER_CONSUMERS`. Reference by symbol name; line numbers drift.
- Generated router blocks: `docs/agentic/generated/codex-command-router.md` and the marker-delimited blocks in `docs/agentic/instructions.md` + `CLAUDE.md`
- Upstream plans: [`docs/tasks/17.0/E17-4-workflow-integrity-task-plan.md`](E17-4-workflow-integrity-task-plan.md), [`docs/tasks/17.0/E17-7-handoff-evolution-and-portable-workflow-task-plan.md`](E17-7-handoff-evolution-and-portable-workflow-task-plan.md)
- Skills directory: `.claude/skills/`
- Codex subagent bridge: `packages/codex-subagent-bridge/`
- Harness contract: `docs/agentic/contracts/harness-protocol.yaml`

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility | Verification |
|---|---|---|---|---|---|
| `.codex/config.toml` | `.codex/` | MCP + hooks only | add skill-root declaration **only if** Slice 1 confirms Codex reads it; otherwise unchanged | additive if present | Slice 1 discovery report |
| Codex skill bootstrap (new, conditional) | `.codex/bootstrap/` or `scripts/codex/` | does not exist | new repo-committed bootstrap artifact (generated) that Codex consumes without per-user config mutation | new artifact | `$branch-review` resolves on fresh clone |
| `scripts/generate_agent_workflows.py` | `scripts/` | renders Claude + Copilot + Codex router | add `_render_codex_skill_registration` (conditional on Slice 1 outcome) | additive | `make generate-agent-workflows` produces the new artifact; `--check` detects drift |
| `make check-agent-workflows` | root `Makefile` | checks Claude + Copilot + Codex router | extend to check the new Codex skill artifact, or assert its documented absence | additive | CI green after slices land |
| `docs/agentic/instructions.md` | `docs/agentic/` | router prose + command list | accurate Codex parity description (either gap closed or limitation retired) | content edit | planning-review Slice 3 |
| `docs/tasks/17.0/E17-4-...md`, `docs/tasks/17.0/E17-7-...md` | `docs/tasks/17.0/` | overstated UI-parity wording | corrected to match shipped behavior | content edit | planning-review Slice 3 |
| `docs/agentic/contracts/harness-protocol.yaml` | `docs/agentic/contracts/` | harness protocol spec | document the Codex skill-registration surface (if shipped) or the retirement decision (if not) | additive | `make check-harness-sync` passes |
| `portable_commands.json` | `config/agent-workflows/` | v1 manifest | **unchanged** — schema not re-architected | no change | manifest diff is zero |
| `scripts/check-task-context.py` (Slice 0) | `scripts/` | silent-exit on `ok=false` error envelope | surface error to stderr; extract `_interpret_handoff_envelope` pure helper | behavior-preserving for success path | regression test in `scripts/test_check_task_context.py` |
| `agent_handoff_mcp` envelope consumer contract (Slice 0) | `scripts/` | caller must render `ok=false` envelopes diagnostically | Slice 0 tightens the consumer-side contract; no upstream API change | additive / consumer-only | pytest suite under `scripts/` |

## Proposed Solution

Four slices deliver the work. Slice 0 is a small prerequisite bugfix uncovered during branch setup (the silent-exit path in `check-task-context.py` defeats the discovery slice's dependence on `make context`). Slice 1 is a time-boxed discovery probe that gates the implementation branch. Slice 2 is conditional: it only runs if Slice 1 confirms a repo-only path exists. Slice 3 runs unconditionally and reconciles the docs to match shipped behavior either way.

0. **Slice 0 — `check-task-context.py` silent-exit fix.** When `get_handoff_state(sections='identity')` returns `{ok: false, data: {error: "..."}}` (e.g. two active tasks resolving to the same workspace path), `_load_active_state()` at `scripts/check-task-context.py:166-171` falls through to `return None` without printing, and `main()` exits 1 with empty stdout/stderr. Surface the error envelope to stderr and add a regression test covering the branch. This slice lands first so Slice 1's discovery probe can depend on `make context` being diagnostic-loud.

1. **Slice 1 — Discovery probe (time-boxed).** Drive the live Codex app-server from this workspace and determine which of these paths, if any, register `.claude/skills/` as a discoverable skill root without per-user config mutation:
   - (a) a static declaration in `.codex/config.toml` (or a sibling repo-committed file) that Codex reads at session start
   - (b) a repo-committed bootstrap artifact that the Codex harness reads declaratively (e.g. `.codex/skills.toml`, `.codex/skills/*/SKILL.md`, or a manifest file)
   - (c) a session-time RPC (`skills/list` with `perCwdExtraUserRoots`, or `skills/config/write` with `enabled=true, path=<repo>/.claude/skills/<slug>`) that can be invoked from a repo-committed wrapper without mutating user config
   - (d) no repo-only path exists; UI-level discoverability in Codex is infeasible from within the repo alone
2. **Slice 2 — Conditional implementation (only if Slice 1 yields an (a)/(b)/(c) answer).** Ship the smallest repo-committed registration artifact that makes `$branch-review` resolve on a fresh clone. Generate the artifact from `portable_commands.json` via a new `_render_codex_skill_registration` function in `scripts/generate_agent_workflows.py`. Extend `make check-agent-workflows` to verify the artifact matches the manifest.
3. **Slice 3 — Docs reconciliation (unconditional).** Reconcile `docs/tasks/17.0/E17-4-...md`, `docs/tasks/17.0/E17-7-...md`, and `docs/agentic/instructions.md` so shipped claims match shipped behavior. If Slice 2 shipped, document the new registration path and its generation. If Slice 2 did not ship, explicitly retire the UI-parity promise: describe Codex routing as instruction-level only and name the protocol surface (`skills/config/write`, `perCwdExtraUserRoots`) as a non-goal for the repo.

## Files and Surfaces to Change

| Surface | File | Change |
|---|---|---|
| Discovery report (new) | `docs/assessments/e17-12-codex-skill-registration-discovery-2026-04-18.md` | Slice 1 output: probe methodology, live Codex responses to `skills/list` / `skills/config/write`, chosen branch, rationale |
| Intake decision record | handoff ledger id 1963 (`e17-12_scope_intake_codex_skill_discoverability`) | referenced, not rewritten |
| Slice-1 decision record (new) | handoff ledger | `e17-12_slice1_discovery_outcome` decision capturing (a)/(b)/(c)/(d) result |
| Generator | `scripts/generate_agent_workflows.py` | add `_render_codex_skill_registration(manifest)` + wire into `_parse_args` and the render loop (conditional on Slice 2) |
| Codex registration artifact (new, conditional) | path determined by Slice 1 — e.g. `.codex/skills.toml`, `.codex/bootstrap/skills.json`, or equivalent | generated from manifest; committed (conditional on Slice 2) |
| Codex config | `.codex/config.toml` | add skill-root declaration only if Slice 1 confirms the static-declaration path (conditional on Slice 2) |
| CI gate | root `Makefile` | extend `check-agent-workflows` target to verify the new artifact matches the manifest, or assert the artifact's documented absence |
| Harness contract | `docs/agentic/contracts/harness-protocol.yaml` | document the Codex skill-registration surface (path, generation, verification) or the retirement decision, under a new subsection |
| E17-4 task plan | `docs/tasks/17.0/E17-4-workflow-integrity-task-plan.md` | correct any overstated "UI-level parity" wording; reference E17-12 outcome |
| E17-7 task plan | `docs/tasks/17.0/E17-7-handoff-evolution-and-portable-workflow-task-plan.md` | correct overstated claims; reference E17-12 outcome |
| Canonical instructions | `docs/agentic/instructions.md` | Codex parity section reflects shipped behavior (description + limitation, as applicable) |
| CLAUDE.md router block | `CLAUDE.md` | no changes beyond generator regeneration if the router output changes |
| Planning review record | handoff ledger | `e17-12_planning_review_outcome` recorded before `make task-start` |
| Slice 0 script | `scripts/check-task-context.py` | surface `ok=false` error envelope via new `_interpret_handoff_envelope` pure helper; refactor `_load_active_state` to delegate |
| Slice 0 regression test | `scripts/test_check_task_context.py` | new file — covers happy path, error envelope (ambiguous active task), ok=false without message, non-dict payload, missing `active` key |

## Verification Strategy

Slice 1 (Discovery):

- A probe script (throwaway, not committed) successfully connects to the live Codex app-server from this workspace and records responses to: `skills/list` (with and without `perCwdExtraUserRoots`), `skills/config/write` (for an in-repo `.claude/skills/branch-review` SKILL.md path). The probe's output is summarized in the discovery report; raw transcripts are attached to the handoff ledger as a decision trace.
- The discovery report names the chosen branch (a/b/c/d) with evidence and decides whether Slice 2 runs.
- Slice 1 decision recorded as `e17-12_slice1_discovery_outcome` in the handoff ledger with the full rationale and a `changed_files` list naming the discovery report.

Slice 2 (Conditional implementation):

- After `make generate-agent-workflows`, the new Codex skill-registration artifact exists at the path chosen in Slice 1 and contains entries generated verbatim from the manifest.
- On a fresh clone (`git clone ... && cd ... && pip install -e packages/agent-handoff-mcp && pip install -e packages/agent-orchestrator-mcp`), launching the Codex harness resolves `$branch-review` to `.claude/skills/branch-review/SKILL.md` without the operator editing any file outside the cloned tree.
- At least one additional `$skill` (e.g. `$planning-review`) resolves the same way.
- `make check-agent-workflows` detects drift between the manifest and the generated Codex skill-registration artifact (simulated by hand-editing the artifact and running the check).
- Deleting the generated artifact causes `make check-agent-workflows --check` to fail with a named remediation.

Slice 3 (Docs reconciliation):

- The three docs surfaces (`E17-4`, `E17-7`, `instructions.md`) contain no wording that promises UI-level discoverability beyond what ships.
- A reader of `docs/agentic/instructions.md` alone can correctly predict the Codex harness's behavior when they type `$branch-review` or `/branch-review`.
- If Slice 2 did not ship, the retirement statement explicitly names the protocol surfaces that were investigated and explains why repo-only registration is infeasible, referencing the Slice 1 discovery report.
- `make check-harness-sync` still passes after the harness-protocol.yaml edits.
- `make check-all` stays green.

## Slice Delivery

### Slice 0: `check-task-context.py` Silent-Exit Fix

**Goal**: when the active-task identity query returns an error envelope (e.g. ambiguous workspace path resolution), surface the error loudly instead of exiting 1 with no output. The discovery slice's instrumentation depends on `make context` being diagnostic-loud.

**Why here, not deferred**: hit during the E17-12 branch setup. Two active tasks (E17-12 and MAINT-RESTORE-E17-12-SCOPE-*) both resolved to the same workspace path; `get_handoff_state(sections='identity')` returned `{ok: false, data: {error: "Ambiguous active task..."}}`. `_load_active_state()` fell through to `return None` without printing, and `main()` exited 1 with empty stdout and stderr. The bug blocks any agent from diagnosing the problem when they next encounter it. Fixing it inside this task keeps the branch singular; deferring to a sibling task would require a second feature branch + review cycle for a five-line change.

Changes:

- `scripts/check-task-context.py`: in `_load_active_state()` (currently `scripts/check-task-context.py:147-171`), add a branch that detects the error envelope (`parsed.get("ok") is False`, or `isinstance(data, dict) and "error" in data`) and prints the underlying error message to stderr before returning `None`. Emit a remediation hint when the error mentions "Ambiguous active task" (suggest archiving the extra task).
- `scripts/test_check_task_context.py` (new): pytest module that stubs `agent_handoff_mcp.handoff_state.get_handoff_state` with three fixtures — happy path with `active`, error envelope with `ok=false`, and malformed JSON — and asserts the script's stdout/stderr match expectations plus the exit code.
- No changes to `agent_handoff_mcp` itself; the error envelope is the authoritative producer's contract and the consumer just needs to respect it.

Proof:

- Reproducer: registering two active tasks that resolve to the same workspace path and running `scripts/check-task-context.py` now prints the ambiguity error to stderr (with the matching `task_refs` list) and exits 1. Before the fix, exit 1 with zero output.
- `scripts/test_check_task_context.py` passes; at least one test case covers the `{ok: false, data: {error: ...}}` branch and at least one covers the happy path.
- `make context` from any worktree prints either the alignment table or a named error — never empty output.

**Gate**: Slice 0 committed before Slice 1 begins. Recorded as `e17-12_slice0_check_task_context_loud` in the handoff ledger.

### Slice 1: Codex Skill-Registration Discovery Probe (Time-Boxed)

**Goal**: empirically determine whether any repo-only registration path makes `.claude/skills/` resolvable in the Codex harness without mutating per-user config. Output decides whether Slice 2 ships.

**Time box**: 1 agent-day of investigation, capped by the Slice-1 decision record deadline. If no path is confirmed by end of day, the default outcome is (d) and Slice 2 is skipped.

Changes:

- Create a throwaway probe script (not committed) that drives the local Codex app-server from this workspace. For each of the three candidate paths (static declaration, repo-committed bootstrap, session-time RPC), the script records:
  - exact wire-level request/response for `skills/list` and `skills/config/write`
  - whether `perCwdExtraUserRoots` accepts a repo-relative path resolved against the current cwd
  - whether the Codex harness process requires a restart after registration
  - whether `SkillsChangedNotification` fires when `.claude/skills/<slug>/SKILL.md` is edited
- If path (a) appears plausible, test by adding a temporary skill-root block to a throwaway copy of `.codex/config.toml` and measuring whether the harness picks it up.
- If path (c) appears plausible, test by invoking `skills/config/write` with an absolute path derived from `$PWD/.claude/skills/<slug>/SKILL.md` and measuring whether the call succeeds without the operator first invoking any interactive UI.
- Write `docs/assessments/e17-12-codex-skill-registration-discovery-2026-04-18.md` capturing: methodology, raw transcripts (redacted of absolute machine paths), observed behavior per path, and the chosen outcome (a/b/c/d). Keep the file under 400 lines; link to raw transcripts stored in the handoff ledger trace.
- Record the Slice-1 decision `e17-12_slice1_discovery_outcome` with rationale ≤ 1500 chars and `changed_files=["docs/assessments/e17-12-codex-skill-registration-discovery-2026-04-18.md"]`.

Proof:

- The discovery report exists and names one of (a), (b), (c), (d).
- For a live-confirmed (a)/(b)/(c) outcome, the probe evidence shows the Codex harness resolving a test skill without per-user config mutation.
- For a (d) outcome, the probe evidence shows why each tested path requires user-scope mutation, a Codex product change, or an interactive step.
- The handoff ledger contains the Slice-1 decision with the chosen outcome and a pointer to the discovery report.

**Gate**: outcome (a), (b), or (c) advances to Slice 2 on a feature branch. Outcome (d) skips Slice 2 and proceeds directly to Slice 3 on `main` (docs reconciliation only, no feature branch needed).

### Slice 2: Manifest-Generated Codex Skill Registration (Conditional on Slice 1)

**Goal**: ship the smallest repo-committed artifact that makes `$branch-review` resolve on a fresh clone, generated from `portable_commands.json` so the manifest stays the single source.

**Precondition**: Slice 1 outcome is (a), (b), or (c).

Changes:

- Extend `scripts/generate_agent_workflows.py` with:
  - `_render_codex_skill_registration(manifest: dict) -> str` that serializes the skill-root block in the format Slice 1 identified (TOML fragment, JSON manifest, or equivalent)
  - a new `--codex-skill-out` CLI argument that writes the generated artifact to its target path
  - wiring into the existing `--check` mode so drift between the manifest and the generated file is caught in CI
- Commit the generated artifact at the path Slice 1 identified. The generator must be idempotent: `make generate-agent-workflows` twice produces identical output.
- If Slice 1 outcome is (a), edit `.codex/config.toml` to include the generated skill-root block verbatim (generator overwrites the delimited block; operator-authored sections of `.codex/config.toml` are preserved via BEGIN/END markers analogous to the Codex router block markers).
- If Slice 1 outcome is (b), the generated artifact is a new file under `.codex/` (e.g. `.codex/skills.json` or `.codex/skills.toml`) committed to the repo.
- If Slice 1 outcome is (c), add a `scripts/codex/bootstrap_skills.py` (or equivalent) invoked by the Codex session start hook (registered via `.codex/hooks.json`) that calls `skills/config/write` for each manifest entry against `$PWD/.claude/skills/<slug>/SKILL.md`. The script must refuse to run if it would write to a path outside the repo.
- Extend root `Makefile` `check-agent-workflows` target to call the generator in `--check` mode for the new Codex skill artifact.
- Extend `docs/agentic/contracts/harness-protocol.yaml` with a new `codex.skill_registration` subsection documenting the path, the generator function, the verification command, and the `$skill` resolution semantics.

Proof:

- `make generate-agent-workflows` twice produces a zero-diff result.
- Hand-editing the generated Codex skill artifact and running `make check-agent-workflows` fails with a named diff against the manifest.
- On a fresh clone (tested via `git clone` into a scratch directory + `pip install -e packages/agent-handoff-mcp && pip install -e packages/agent-orchestrator-mcp`), launching Codex resolves `$branch-review` to `.claude/skills/branch-review/SKILL.md`.
- `$planning-review` resolves on the same fresh clone, confirming the artifact is generic across all manifest entries.
- For outcome (c), the bootstrap script exits non-zero when pointed at a path outside the repo.
- `make check-harness-sync` passes after the `harness-protocol.yaml` additions.

### Slice 3: Docs Reconciliation (Unconditional)

**Goal**: every docs surface describing Codex parity matches shipped behavior — no overstated UI claims and no unstated gap.

Changes:

- `docs/tasks/17.0/E17-4-workflow-integrity-task-plan.md`: review for "UI-level parity" or "first-class slash command" phrasing; correct to "instruction-level routing via the generated router prose, with `$skill` resolution delivered by E17-12" (if Slice 2 shipped) or "instruction-level routing only; `$skill` resolution in Codex is not provided by the repo" (if Slice 2 did not ship).
- `docs/tasks/17.0/E17-7-handoff-evolution-and-portable-workflow-task-plan.md`: same review; same correction.
- `docs/agentic/instructions.md`: update the Codex parity section (not the generated router block, which is generator-owned) to describe the shipped Codex behavior exactly. Include:
  - what `$skill` resolution requires (Slice 2 artifact path + generation command, or the retirement statement)
  - what `/command` resolution requires (model reads the generated router block)
  - what the repo deliberately does **not** provide (native `/command` UI chips in Codex)
- If Slice 2 did not ship: add a short "Why not" block to `docs/agentic/instructions.md` naming the Codex protocol surfaces investigated (`skills/list`, `skills/config/write`, `perCwdExtraUserRoots`) and why repo-only registration is infeasible, with a pointer to the Slice 1 discovery report.
- Regenerate the Codex router block in `docs/agentic/instructions.md` and `CLAUDE.md` via `make generate-agent-workflows` to confirm the unchanged router content still matches the manifest (no drift introduced by the manual edits).

Proof:

- Grep for "native slash", "first-class slash", "UI-level parity", and "discoverable slash" across the three updated surfaces returns zero hits that contradict shipped behavior.
- A reader of only `docs/agentic/instructions.md` can correctly predict the Codex harness's behavior on `$branch-review` and `/branch-review`.
- `make check-agent-workflows` passes (router blocks unchanged after manual edits).
- `make check-all` stays green.
- The E17-12 retrospective decision (`e17-12_slice3_docs_reconciled`) is recorded with `changed_files` naming the three edited surfaces.

---

## Consolidated Checklist

### Context and Ownership

- [ ] E17-4 + E17-7 merged to `main` (verified 2026-04-18)
- [ ] Scope note exists at `docs/scopes/e17-12-codex-skill-discoverability-scope.md`
- [ ] Intake decision `e17-12_scope_intake_codex_skill_discoverability` (handoff ledger id 1963) references this task plan
- [ ] Planning review passed (`make plan-review DOC=docs/tasks/17.0/E17-12-codex-skill-discoverability-task-plan.md`)
- [x] Feature branch `feature/e17-12` and worktree created during scope migration from `main` (planning docs moved to the branch per updated planning-docs-on-feature-branch guidance); planning review runs on the feature branch rather than gating `make task-start`

### Checklist for Slice 0: check-task-context.py Silent-Exit Fix

- [ ] `_load_active_state()` in `scripts/check-task-context.py` surfaces the error envelope to stderr before returning None
- [ ] `scripts/test_check_task_context.py` exists with a regression test covering the `{ok: false, data: {error: ...}}` branch
- [ ] Regression test covers at least: happy-path identity envelope, error envelope, and malformed JSON
- [ ] `make context` run after the fix from any worktree never returns silent exit 1; output always includes either alignment table or named error
- [ ] Slice-0 decision `e17-12_slice0_check_task_context_loud` recorded in handoff ledger

### Checklist for Slice 1: Discovery Probe

- [ ] Probe script drives live Codex app-server for `skills/list` and `skills/config/write` from this workspace
- [ ] Probe tests all three candidate paths (static config, repo-committed bootstrap, session-time RPC)
- [ ] Probe records `SkillsChangedNotification` behavior on `.claude/skills/**/SKILL.md` edits
- [ ] Discovery report `docs/assessments/e17-12-codex-skill-registration-discovery-2026-04-18.md` exists and is ≤ 400 lines
- [ ] Discovery report names one of (a), (b), (c), (d) as the chosen outcome with evidence
- [ ] Slice-1 decision `e17-12_slice1_discovery_outcome` recorded in handoff ledger
- [ ] Slice-1 decision rationale ≤ 1500 chars and names the chosen outcome verbatim
- [ ] Probe script is not committed to the repo
- [ ] Raw transcripts attached to the handoff ledger decision trace (redacted of absolute machine paths)
- [ ] If outcome is (d), Slice 2 is skipped and the plan advances directly to Slice 3 on `main`

### Checklist for Slice 2: Manifest-Generated Codex Skill Registration (Conditional)

- [ ] Precondition: Slice 1 outcome is (a), (b), or (c); otherwise skip this entire checklist
- [ ] `scripts/generate_agent_workflows.py` exposes `_render_codex_skill_registration` + `--codex-skill-out` CLI flag
- [ ] Generated artifact lives at the path Slice 1 identified (e.g. `.codex/config.toml` marker block, `.codex/skills.toml`, `.codex/skills.json`, or a bootstrap script)
- [ ] `make generate-agent-workflows` is idempotent (two runs → zero diff)
- [ ] `make check-agent-workflows` catches manual drift between manifest and generated Codex artifact
- [ ] `$branch-review` resolves in Codex on a fresh clone of the repo without per-user config mutation
- [ ] `$planning-review` (or another manifest-listed skill) resolves on the same fresh clone
- [ ] For outcome (c), the bootstrap script refuses to write to a path outside the repo
- [ ] `docs/agentic/contracts/harness-protocol.yaml` gains a `codex.skill_registration` subsection documenting the shipped path
- [ ] `make check-harness-sync` passes
- [ ] Manifest `config/agent-workflows/portable_commands.json` is not modified (single source preserved)

### Checklist for Slice 3: Docs Reconciliation (Unconditional)

- [ ] `docs/tasks/17.0/E17-4-workflow-integrity-task-plan.md` reviewed; overstated UI-parity wording corrected
- [ ] `docs/tasks/17.0/E17-7-handoff-evolution-and-portable-workflow-task-plan.md` reviewed; overstated wording corrected
- [ ] `docs/agentic/instructions.md` Codex parity section describes shipped `$skill` + `/command` behavior exactly
- [ ] If Slice 2 did not ship, `instructions.md` includes a "Why not" retirement block naming investigated Codex protocol surfaces
- [ ] Grep for "native slash", "first-class slash", "UI-level parity", "discoverable slash" across the three surfaces returns no claim that contradicts shipped behavior
- [ ] `make generate-agent-workflows` run after manual edits; router blocks in `instructions.md` and `CLAUDE.md` unchanged (no drift)
- [ ] `make check-agent-workflows` passes
- [ ] `make check-all` stays green
- [ ] Slice-3 decision `e17-12_slice3_docs_reconciled` recorded in handoff ledger with `changed_files` naming the three edited surfaces

## Review Readiness

- [ ] Planning review passed on `main` before any feature branch was created
- [ ] Review findings recorded in handoff MCP, not inline in this plan
- [ ] `make check-all` stays green after each slice
- [ ] No changes to `config/agent-workflows/portable_commands.json` schema
- [ ] No changes to other harness adapters (Claude, Copilot) introduced as side effects
- [ ] No Codex product patches; no per-user machine config mutation

## Success Criteria

- [ ] Slice 1 discovery probe ran against the live Codex app-server from this workspace and recorded an outcome
- [ ] If Slice 1 outcome is (a), (b), or (c): `$branch-review` resolves in Codex on a fresh clone of this repo without per-user Codex config edits, and at least one other manifest-listed skill resolves the same way
- [ ] If Slice 1 outcome is (d): `docs/agentic/instructions.md` explicitly retires the UI-parity promise and names the protocol surfaces that were investigated
- [ ] `config/agent-workflows/portable_commands.json` remains the only command/skill registry; any Codex-side artifact is generated from it
- [ ] `make check-agent-workflows` extends to cover the Codex skill-registration artifact (or verifies its documented absence)
- [ ] `docs/tasks/17.0/E17-4-*`, `docs/tasks/17.0/E17-7-*`, and `docs/agentic/instructions.md` no longer contain claims that contradict shipped Codex behavior
- [ ] `docs/agentic/contracts/harness-protocol.yaml` documents the Codex skill-registration surface or the retirement decision

## Coordination Note

**E17-4 and E17-7 interaction**: this task does not invalidate the E17-4 / E17-7 deliveries. It adds a missing layer (`$skill` resolution) and corrects their docs so the combined shipped surface is accurately described. The upstream task plans stay in the archive unchanged; only the parts of their living task-plan surfaces that still appear in `main` get reconciled to match shipped behavior.

**No cross-task sequencing dependency**: this plan does not block on any other E17 task and is not blocked by one. It can begin as soon as planning review passes.
