# E17-7. Phase 3 Follow-On — Handoff State Evolution, Trace Archive, Tool Surface Compression, and Portable Workflow Normalization

- **Date**: 2026-04-16
- **Author**: GPT-5.4
- **Owning Epic**: [docs/epics/v0.4.0/skill-formalization-and-process-automation-epic.md](../../epics/v0.4.0/skill-formalization-and-process-automation-epic.md)
- **Epic Short ID**: E17
- **Target Branch**: `feature/e17-7`
- **Review Coverage Target**: 2

---

## Objective

After the E17-6 Phase 3 core retrofit is approved, land the split-out follow-on work: evolve `agent-handoff-mcp` from a singleton active-task model to concurrent task rows, preserve richer session/slice status for cold starts, store raw test traces with change-outcome lookup, compress the MCP tool surface, and finish portable workflow normalization so Claude, VS Code, Codex, and the committed MCP harness configs all consume the same command contract from `config/agent-workflows/portable_commands.json`, the same non-interactive Python runtime rule, and the same portable path contract for committed harness startup surfaces.

## Why This Is Separate

This plan was split out of `E17-6` to keep the Phase 3 core reviewable against the epic's retrofit/routing/gating deliverables. Everything here changes either:

- the `agent-handoff-mcp` state model
- the query/rendering surface for cold-start state
- the registered MCP tool surface
- the cross-host workflow command contract, including Codex-specific command routing

Those changes are valuable, but they are not required to complete the E17-6 core retrofit.

## Problem Statement

Five follow-on gaps remain once the E17-6 core is separated:

1. **Singleton handoff state blocks parallel work**: `handoff_state WHERE id = 1` still assumes one active task at a time.
2. **Cold starts lose failure detail**: `verified_tests.result` preserves only a 280-character summary, not raw trace content.
3. **The MCP tool surface is larger than necessary**: several read/write tool pairs can be merged into compound tools without changing the Python API. An [investigation into a missing `review_runs` tool](../../assessments/review-runs-tool-bridge-gap-investigation-2026-04-16.md) confirmed that the VS Code/Copilot MCP session bridge may deprioritize or drop tools when the advertised tool count is high; compressing the surface reduces that risk. A second [CLI-vs-native-tools investigation](../../assessments/agent-handoff-mcp-cli-vs-native-tools-investigation-2026-04-16.md) confirmed that tool-count and per-call response size are the only levers that actually move the _agent's_ token bill — shell-hook call sites (CLI, Python-in-shell) cost zero agent tokens regardless — so "minimize MCP token usage without breaking functionality" maps directly to this slice plus the existing bounded-read envelope (`sections=`, `detail=`, `top_n_*`). Slice 4 must preserve functionality including correct dashboard rendering at the authoritative `DASHBOARD.txt` path throughout the rename.
4. **Codex portable-command parity is incomplete**: `portable_commands.json` already generates Claude and VS Code adapters, but Codex still depends on handwritten router text in `instructions.md` and `CLAUDE.md`. That leaves `/branch-review`, `/planning-review`, and the other workflow ids vulnerable to drift in this harness.
5. **Python runtime selection is not normalized across harnesses**: the repo already assumes the `description-service` pyenv, but the non-interactive contract is fragmented across `PYENV_VERSION=description-service`, `pyenv exec`, `.python-version`, and older config surfaces such as `.mcp.json`. That makes Python/MCP startup behavior drift-prone across hosts.

## Constraints

- `portable_commands.json` remains the canonical command contract; it must not become the owner of unrelated MCP runtime env metadata.
- `scripts/generate_agent_workflows.py` remains the single generator for host-specific workflow artifacts.
- `make check-agent-workflows` must verify the Codex router artifact in addition to Claude and VS Code outputs.
- `make check-codex-command-router` must fail on router drift between the manifest and the committed Codex instruction surfaces.
- The Codex router consumers must use one mandatory generated-content contract: a single marker-delimited block in each consumer doc. `make check-codex-command-router` must validate only the content inside those markers; it must not rely on heuristic parsing of handwritten prose.
- Non-interactive harnesses must not depend on `pyenv activate description-service`; the canonical runtime selector is `PYENV_VERSION=description-service`, with `pyenv exec` only where the harness launches Python directly.
- Python runtime normalization belongs to committed harness configs, shell/Makefile entry points, and startup docs, not to generated workflow-adapter content.
- Committed non-interactive harness configs must not hardcode user-local repository paths such as `/Users/.../context-alt-text-monorepo`; use env-driven or workspace-relative forms where the host allows them.
- `make smoke-agent-workflows` should be optional and backend-aware; it must not become a flaky mandatory gate for environments that cannot execute the live backend check.
- Test trace retrieval is additive to `get_verified_tests`; no separate trace MCP tool should be introduced.
- Python-level API compatibility should be preserved where practical even if MCP tool names are compressed.

## Current State Analysis

**Portable workflow contract**:

- `config/agent-workflows/portable_commands.json` already exists as the canonical command manifest.
- `scripts/generate_agent_workflows.py` currently generates `.claude/commands/*.md` and `.github/prompts/*.prompt.md` only.
- `make generate-agent-workflows` and `make check-agent-workflows` already exist.
- Codex routing still lives in handwritten text in `docs/agentic/instructions.md` and `CLAUDE.md`.

**Python runtime contract**:

- Root automation already assumes the `description-service` pyenv through `MCP_PYENV_VERSION ?= description-service` and `env PYENV_VERSION=... pyenv exec python3` in the root `Makefile`.
- App-local Python commands already assume `pyenv exec python` in `apps/prototype-description-service/Makefile`.
- VS Code MCP and Codex MCP configs already set `PYENV_VERSION=description-service` in `.vscode/mcp.json` and `.codex/config.toml`.
- `.mcp.json` still omits the same runtime env, so one committed harness surface remains out of parity.
- `.codex/config.toml` and `.mcp.json` still hardcode user-local repo paths rooted at `/Users/daniel/Development/context-alt-text-monorepo`, so committed harness startup is not yet portable across machines or clones.
- Docs still mix interactive setup guidance (`pyenv activate description-service`) with the non-interactive harness rule (`PYENV_VERSION=description-service`), and that rule is not front-loaded as a single canonical contract for all hosts.

**Conflicting review routing still exists before the E17-6 prerequisite lands**:

- Both docs describe portable command routing.
- Both docs also still contain direct review-routing text that tells agents to load `branch-review-guide.md` or `planning-review-guide.md` directly.
- That conflict is a likely cause of `/branch-review` feeling unreliable in Codex even though the manifest and generated host adapters exist.
- E17-6 Slice 4 removes that guide-first routing before this follow-on starts; Slice 1 here builds on the already-redirected surfaces.

**Handoff-state model**:

- `handoff_state` is still singleton-keyed.
- `_resolve_task_ref()` still falls back to the singleton active row when `task_ref` is omitted.

**Test verification surface**:

- `verified_tests.result` stores only the summary string.
- There is no raw trace table and no correlated-file query surface.

**MCP tool surface**:

- The MCP API still exposes separate `generate_current_task_md`, `generate_dashboard_md`, `export_handoff_state`, `import_handoff_state`, `archive_task_state`, and `get_archived_task` tools.
- A [tool bridge-gap investigation](../../assessments/review-runs-tool-bridge-gap-investigation-2026-04-16.md) found that `review_runs` was fully registered and exported but invisible in the live VS Code/Copilot session. Root cause: the session projection layer is opaque and may involve tool-count batching. Reducing the advertised tool count is the only repo-side mitigation.

## Target Outcome

- `portable_commands.json` generates Claude, VS Code, and Codex workflow artifacts from one source.
- `CLAUDE.md` and `docs/agentic/instructions.md` consume one generated Codex router block each, delimited by required begin/end markers, instead of handwritten command-id lists.
- `make check-agent-workflows` fails on Claude, VS Code, or Codex adapter drift.
- `make check-codex-command-router` fails if the committed Codex router text diverges from the manifest.
- `make smoke-agent-workflows` can validate live command resolution for `/branch-review` and `/planning-review`.
- Every supported non-interactive harness sets `PYENV_VERSION=description-service`, uses portable env/workspace-relative startup paths in committed configs, and Python-launching surfaces use `pyenv exec` only where needed.
- `pyenv activate description-service` is documented as an optional interactive shell convenience, not the harness contract.
- `handoff_state` supports concurrent in-progress tasks keyed by `task_ref`.
- `load_session` / `get_handoff_state` can surface completed slices explicitly.
- `get_verified_tests(include_traces=True)` returns raw stored traces.
- The MCP tool surface is reduced via compound tools while Python-level compatibility aliases remain.

## Context Loading

- Phase 3 core prerequisite: [E17-6](./E17-6-phase3-retrofit-task-plan.md)
- Canonical workflow manifest: `config/agent-workflows/portable_commands.json`
- Generator: `scripts/generate_agent_workflows.py`
- Existing generated adapters: `.claude/commands/*.md`, `.github/prompts/*.prompt.md`
- Codex router surfaces: `docs/agentic/instructions.md`, `CLAUDE.md`
- Handoff package: `packages/agent-handoff-mcp/src/agent_handoff_mcp/`
- Orchestrator tests: `packages/agent-orchestrator-mcp/tests/`
- Tool bridge-gap investigation: `docs/assessments/review-runs-tool-bridge-gap-investigation-2026-04-16.md` (empirical evidence that tool count affects VS Code/Copilot session tool availability; motivates Slice 4)
- CLI-vs-native-tools investigation: `docs/assessments/agent-handoff-mcp-cli-vs-native-tools-investigation-2026-04-16.md` (confirms that the CLI + Python API + native MCP tools share one backend; agent token cost is driven by tool count and response envelope size, not by which presentation is "chosen" — reinforces Slice 4 scope and constraints the acceptable rename surface)
- DASHBOARD naming drift investigation: `docs/assessments/dashboard-md-vs-txt-guidance-drift-investigation-2026-04-16.md` (post-AHMCP-23 cleanup inventory; 18 active-surface files still say `DASHBOARD.md` though every writer produces `DASHBOARD.txt`; Slice 4 is the natural place to normalize the docs + docstring + Makefile comment surfaces because the `generate_dashboard_md` → `render_handoff` rename touches them anyway) <!-- lint-dashboard-txt: allow -->

## Proposed Solution

Five slices deliver the follow-on. Slice 1 is independent of the handoff-schema work and should land first because it closes the user-visible Codex command gap. Slices 2-4 then proceed in dependency order. Slice 5 is orthogonal additive backend work that front-loads the `review_findings` pieces E17-9 depends on; it can land in parallel with Slices 1-4 but naturally follows Slice 2 because it touches the same table:

1. Portable workflow normalization for Codex + Python runtime contract
2. Multi-active-task registry + slice status / task-plan sync
3. Test trace archive and change-outcome linkage
4. MCP tool surface compression
5. Parallel-review backend groundwork (additive: `review_findings.merge` + `(lane_id, status)` index)

## Contract and Boundary Impact

| Boundary                              | Owner                                                                  | Current Contract                                                                                         | Expected Change                                                                                                               | Compatibility Needed?                   | Verification                                                            |
| ------------------------------------- | ---------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- | --------------------------------------- | ----------------------------------------------------------------------- |
| `portable_commands.json`              | `config/agent-workflows/`                                              | canonical command ids, Claude + VS Code adapters                                                         | extend to Codex router artifact content only                                                                                  | non-breaking manifest authority         | generator/check passes                                                  |
| `scripts/generate_agent_workflows.py` | scripts                                                                | writes Claude + VS Code adapters                                                                         | also writes Codex router artifact                                                                                             | non-breaking generator expansion        | generated outputs match                                                 |
| `make check-agent-workflows`          | root `Makefile`                                                        | checks Claude + VS Code adapters                                                                         | also checks Codex router artifact                                                                                             | non-breaking stronger gate              | drift fails                                                             |
| `make check-codex-command-router`     | root `Makefile` (new)                                                  | does not exist                                                                                           | static Codex router drift gate over marker-delimited generated blocks only                                                    | n/a — new target                        | handwritten/router drift fails                                          |
| `make smoke-agent-workflows`          | root `Makefile` (new)                                                  | does not exist                                                                                           | optional runtime command-resolution smoke test                                                                                | n/a — new target                        | `/branch-review` + `/planning-review` resolve                           |
| Python harness env                    | `.vscode/mcp.json`, `.codex/config.toml`, `.mcp.json`, Makefiles, docs | mixed `pyenv activate`, `pyenv exec`, partial `PYENV_VERSION` wiring, and user-local absolute repo paths | normalize on `PYENV_VERSION=description-service` and portable env/workspace-relative path forms for non-interactive harnesses | non-breaking runtime normalization      | all harnesses launch against the same env without user-local path drift |
| `handoff_state`                       | `shared_schema.py`                                                     | singleton row                                                                                            | task-ref keyed multi-row state                                                                                                | breaking internal schema                | tests pass                                                              |
| `load_session` / `get_handoff_state`  | `core.py`, `handoff_state.py`                                          | no explicit slice-status section                                                                         | add `slices_completed` section                                                                                                | non-breaking additive response          | cold-start status visible                                               |
| `verified_tests` + `test_traces`      | `shared_schema.py`, `verified_tests.py`, `decisions.py`                | summary-only result                                                                                      | raw traces + correlated-file retrieval                                                                                        | non-breaking additive query params      | trace roundtrip works                                                   |
| MCP tool registry                     | `api.py`                                                               | 6 single-purpose tools                                                                                   | 3 compound tools                                                                                                              | breaking MCP names, Python aliases kept | tool count reduced                                                      |
| Hook matchers                         | `terminal-guard.json`, `.claude/settings.json`                         | reference old tool names                                                                                 | reference compound tool names                                                                                                 | atomic with tool rename                 | no stale references                                                     |
| Deferred tool list                    | `.github/copilot-instructions.md`                                      | lists old tool names                                                                                     | lists compound tool names                                                                                                     | atomic with tool rename                 | tool_search resolves                                                    |

## Files and Surfaces to Change

| Surface                 | File                                                                                                                                                                                              | Change                                                                                                                              |
| ----------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------- |
| Portable manifest       | `config/agent-workflows/portable_commands.json`                                                                                                                                                   | extend manifest ownership to Codex router text where needed                                                                         |
| Workflow generator      | `scripts/generate_agent_workflows.py`                                                                                                                                                             | generate Codex router artifact in addition to Claude + VS Code adapters                                                             |
| Generated Codex router  | `docs/agentic/generated/codex-command-router.md` (new)                                                                                                                                            | generated Codex command-routing artifact plus the canonical block content inserted into consumer docs                               |
| Codex router consumers  | `docs/agentic/instructions.md`, `CLAUDE.md`                                                                                                                                                       | replace handwritten command-id lists with one required marker-delimited generated block per file                                    |
| Harness runtime configs | `.vscode/mcp.json`, `.codex/config.toml`, `.mcp.json`                                                                                                                                             | normalize `PYENV_VERSION=description-service` and replace user-local absolute repo paths with portable env/workspace-relative forms |
| Python command surfaces | root `Makefile`, `apps/prototype-description-service/Makefile`, package Makefiles where needed                                                                                                    | standardize non-interactive `description-service` selection                                                                         |
| Startup docs            | `CLAUDE.md`, `docs/agentic/instructions.md`, `docs/agentic/BOOTSTRAP.md`, `.github/copilot-instructions.md`, `apps/prototype-description-service/README.md`                                       | front-load the canonical pyenv contract; demote `pyenv activate` to interactive-only guidance                                       |
| Static drift gate       | root `Makefile`                                                                                                                                                                                   | expand `check-agent-workflows`; add `check-codex-command-router`                                                                    |
| Runtime smoke test      | root `Makefile` and script(s)                                                                                                                                                                     | add optional `smoke-agent-workflows`                                                                                                |
| Handoff schema          | `packages/agent-handoff-mcp/src/agent_handoff_mcp/shared_schema.py`                                                                                                                               | re-key `handoff_state`; add `test_traces`                                                                                           |
| Task resolution         | `shared_primitives.py`, `handoff_state.py`, `core.py`, `import_export.py`, `shared_write_context.py`, `decisions.py`, `review_findings.py`, `current_task_rendering.py`, `dashboard_rendering.py` | update singleton task-resolution assumptions                                                                                        |
| Slice status surface    | `core.py`, `handoff_state.py`                                                                                                                                                                     | add `slices_completed` section                                                                                                      |
| Task-plan sync          | deferred from Slice 2                                                                                                                                                                             | not retained in this slice; if revived later, coordinate with E17-8 allow-list sequencing before adding a main-worktree write path  |
| Verification surface    | `decisions.py`, `verified_tests.py`, `api.py`                                                                                                                                                     | raw traces + correlated-file lookup                                                                                                 |
| Tool compression        | `api.py`, `__init__.py`                                                                                                                                                                           | compound MCP tools + Python compatibility aliases                                                                                   |
| Handoff CLI surface     | `packages/agent-handoff-mcp/src/agent_handoff_mcp/cli.py`, `packages/agent-handoff-mcp/README.md`                                                                                                 | keep CLI subcommands and operator docs aligned with the compressed tool names                                                       |
| Hook matchers           | `.github/hooks/terminal-guard.json`, `.claude/settings.json`                                                                                                                                      | update PostToolUse matchers from old tool names to compound tool names                                                              |
| Deferred tool registry  | `.github/copilot-instructions.md`                                                                                                                                                                 | update deferred-tool list to reflect compound tool names                                                                            |
| Contracts               | `docs/agentic/contracts/`                                                                                                                                                                         | update MCP tool surface documentation                                                                                               |

## Verification Strategy

- `make check-agent-workflows` passes with Claude, VS Code, and Codex generated artifacts in sync.
- `make check-codex-command-router` fails when the marker-delimited generated block in `instructions.md` or `CLAUDE.md` diverges from the generated Codex router content.
- `make smoke-agent-workflows` resolves `/branch-review` and `/planning-review` through the active backend and confirms skill/target parity with the manifest.
- Committed harness configs all inject `PYENV_VERSION=description-service`, no committed non-interactive harness config retains a user-local absolute repo path, and non-interactive Python commands no longer rely on `pyenv activate`.
- Concurrent active-task tests pass for the handoff schema redesign.
- `load_session` and `get_handoff_state(sections="slices_completed")` surface completed slices correctly.
- Trace roundtrip, correlated-file lookup, and bounded retention tests pass.
- Compound MCP tool tests pass and Python aliases continue to resolve.

## Slice Delivery

### Slice 1: Portable Workflow Normalization for Codex + Python Runtime Contract

**Goal**: one manifest drives Claude, VS Code, and Codex workflow routing, while committed harness configs and startup docs converge on one non-interactive Python runtime contract.

Prerequisite:

- E17-6 Slice 4 already removed the guide-first review-routing conflict from `docs/agentic/instructions.md` and `CLAUDE.md`. This slice does not re-own that redirect; it adds Codex generator, drift-check, and smoke-test coverage on top of the redirected routing surfaces.

Changes:

- Extend `scripts/generate_agent_workflows.py` to generate `docs/agentic/generated/codex-command-router.md`.
- Define one mandatory embedding contract for Codex router content in `docs/agentic/instructions.md` and `CLAUDE.md`: each file must contain exactly one generated router block delimited by repo-owned begin/end markers, and `check-codex-command-router` validates only the content inside those markers.
- Replace handwritten portable-command lists in `docs/agentic/instructions.md` and `CLAUDE.md` with marker-delimited generated blocks sourced from that artifact.
- Preserve the E17-6 skill-first routing redirect while replacing the remaining handwritten Codex command-routing content with generated content.
- Normalize all committed non-interactive harness configs to set `PYENV_VERSION=description-service`; `.mcp.json` must reach parity with `.vscode/mcp.json` and `.codex/config.toml`.
- Replace user-local absolute repo paths in committed non-interactive harness configs with portable env-driven or workspace-relative forms. Where a host requires an absolute runtime path, derive it from existing host variables rather than committing `/Users/...` literals.
- Preserve `pyenv activate description-service` only as optional interactive-shell setup guidance; front-load `PYENV_VERSION=description-service` as the canonical automation/harness rule in the startup docs.
- Use `pyenv exec` only where the harness launches Python directly; installed console scripts should rely on the injected `PYENV_VERSION` env instead of interactive activation.
- Keep the runtime contract outside `portable_commands.json`; if a shared runtime check is needed, implement it as a doc/config verification step rather than generated command-adapter content.
- Expand `make check-agent-workflows` to verify the generated Codex router artifact too.
- Add `make check-codex-command-router` to fail when the marker-delimited router block in either consumer doc disagrees with the manifest-generated Codex router content.
- Add optional `make smoke-agent-workflows` that asks the active backend to resolve `/branch-review` and `/planning-review` and checks the resolved skill/target pair against the manifest.

Proof:

- `portable_commands.json` remains the only command registry.
- `/branch-review` and `/planning-review` resolve through the same contract across all three hosts.
- Claude, VS Code, Codex, and `.mcp.json` all launch Python/MCP work with the same `description-service` runtime selection and without committed user-local absolute repo paths.
- Static drift and optional smoke checks both pass.

### Slice 2: Multi-Active-Task Registry + Slice Status Follow-On

**Goal**: allow concurrent active tasks and improve cold-start task-state visibility.

Changes:

- Re-key `handoff_state` by `task_ref`.
- Migration approach: because `handoff.db` is live shared workflow state, do not require a blanket local-db reset. Either implement an in-place schema migration in `shared_schema.py` or document a coordinated export/reset/reimport path using the existing handoff export/import surfaces; the chosen path must preserve unrelated active tasks, findings, decisions, and archives.
- Evolve `_resolve_task_ref()` to use worktree/cwd matching when `task_ref` is omitted. Per [rg-013], path matching must be pure string comparison against stored `target_worktree_path` values; no subprocess calls, no `git` invocations. If the resolution logic exceeds simple string matching, extract it to a dedicated `task_resolution.py` module rather than adding it to `core.py`.
- Task resolution algorithm:
  - if `task_ref` is passed explicitly, resolve that task directly
  - otherwise compare the caller cwd against `target_worktree_path` across active `handoff_state` rows
  - exact path match wins first; if none exist, fall back to unique prefix-match ownership
  - if exactly one active row matches, return it
  - if zero rows match or multiple rows match, raise an explicit ambiguity error naming the candidate task refs so CLI callers stop relying on the singleton fallback
- Add `slices_completed` to `load_session` and `get_handoff_state`.
- Prerequisite for any future checkbox-sync-on-`main` follow-on: [E17-8 branch-isolation edit-guard hardening task plan](E17-8-branch-isolation-edit-guard-hardening-task-plan.md) Slice 1 must already be merged so `branch_isolation.permitted_main_surfaces` includes `docs/tasks/**/*.md` on `main`.
- Do not retain the split-out task-plan sync/status ideas from the former E17-6 draft in Slice 2. They are deferred until the E17-8 allow-list sequencing lands on `main`; if revived later, attach the warning to the real `make context` entrypoint (`scripts/check-task-context.py`), not the stale `scripts/context.sh` path.

Proof:

- Two active tasks can coexist without eviction.
- `load_session()` shows completed slices explicitly.
- Migration proof covers preservation: run the chosen in-place migration or export/reset/reimport path against a fixture DB containing two unrelated active tasks plus findings, decisions, and archive rows, then assert identical row counts and payload contents after the task-registry change.
- Slice 2 no longer claims a task-plan checkbox sync hook or stale-checkbox warning.

### Slice 3: Test Trace Archive and Change-Outcome Linkage

**Goal**: store raw test traces and expose selective retrieval for cold-start debugging.

Changes:

- Bump `HANDOFF_SCHEMA_VERSION` and add the warm-start migration for `test_traces` in `shared_schema.py` so existing handoff databases gain the new table without requiring a reset.
- Add the `test_traces` table.
- Extend `record_test_result` / `record_event(test_result)` with optional traces.
- Extend `get_verified_tests` and the trace/correlation helpers in `verified_tests.py` with `include_traces`, `correlated_file`, `correlation_window_minutes`, and `exclude_never_passed`.
- Thread the new trace/correlation retrieval surface through the operator-facing entrypoints in `decisions.py` and `api.py`.

Proof:

- Raw traces round-trip.
- Correlated-file queries return meaningful failure history.
- `correlation_window_minutes` narrows time-based matching as documented instead of returning stale unrelated failures.
- `exclude_never_passed` filters commands that have never recorded a passing run.
- `include_traces=False` omits full trace bodies and returns `trace_count` metadata instead.
- Existing callers remain backward-compatible.

### Slice 4: MCP Tool Surface Compression

**Goal**: reduce MCP tool count to improve session tool availability, simplify the API surface, and lower per-turn token cost without changing functionality or regressing dashboard rendering.

Motivation: The [review_runs bridge-gap investigation](../../assessments/review-runs-tool-bridge-gap-investigation-2026-04-16.md) confirmed that tools can silently disappear from VS Code/Copilot sessions even when fully registered on the server side. The investigation identified tool-count batching in the session projection layer as a probable cause. The companion [CLI-vs-native-tools investigation](../../assessments/agent-handoff-mcp-cli-vs-native-tools-investigation-2026-04-16.md) narrowed the agent-visible token cost to two levers — (a) advertised tool count and (b) per-response envelope size — and confirmed that non-agent invocations (shell hooks, scripts importing the Python API) cost zero agent tokens regardless of transport. Reducing the advertised tool count is therefore both the only mitigation for session drop-out _and_ the most direct per-turn token reduction. Per-response size stays governed by the existing bounded-read envelope (`sections=`, `detail="summary"`, `top_n_*`) and the `slim-handoff-response` hook; this slice does not alter those.

Token-minimization constraints for this slice:

- Preserve the bounded-read envelope contract (`sections`, `detail`, `top_n_*`, `fields`) on every compound tool — compound tools must not enlarge their default response shape.
- Preserve the `slim-handoff-response` PostToolUse hook coverage when renaming matcher ids (atomic with the rename).
- Preserve functionality: every Python API symbol currently imported across the repo continues to resolve (aliases kept).
- Preserve dashboard rendering: after `generate_dashboard_md` → `render_handoff` rename, writing the dashboard continues to produce `DASHBOARD.txt` at the workspace root with identical content semantics and no new `.md` artifact.

Changes (split into three sub-slices; only 4A is in scope for this task):

- **Sub-slice 4A (in scope)**: `render_handoff` (replaces `generate_current_task_md` + `generate_dashboard_md`).
- **Sub-slice 4B (DEFERRED — out of scope for E17-7)**: `handoff_transfer` (would replace `export_handoff_state` + `import_handoff_state`). Deferred because the token-cost and session-drop risk is already materially reduced by 4A + the existing bounded-read envelope, and the export/import pair is called infrequently enough that it is not contributing to per-turn tool-count pressure. Carried forward as tech-debt: [packages/agent-handoff-mcp/docs/tech-debt/slice-4b-handoff-transfer-compound-tool.md](../../../packages/agent-handoff-mcp/docs/tech-debt/slice-4b-handoff-transfer-compound-tool.md).
- **Sub-slice 4C (DEFERRED — out of scope for E17-7)**: `task_archive` (would replace `archive_task_state` + `get_archived_task`). Deferred for the same reason: both are rarely called lifecycle tools and removing them from the advertised count has diminishing returns over 4A. Carried forward as tech-debt: [packages/agent-handoff-mcp/docs/tech-debt/slice-4c-task-archive-compound-tool.md](../../../packages/agent-handoff-mcp/docs/tech-debt/slice-4c-task-archive-compound-tool.md).
- **CURRENT_TASK.json demotion (DEFERRED — out of scope for E17-7)**: strip implicit `_write_current_task_md_*` side-effects from handoff write paths and keep render-on-demand only. Carried forward as tech-debt: [packages/agent-handoff-mcp/docs/tech-debt/demote-current-task-rendering.md](../../../packages/agent-handoff-mcp/docs/tech-debt/demote-current-task-rendering.md).
- Keep Python-level compatibility aliases so existing callers are unaffected.
- Update CLI/operator surfaces atomically with the MCP rename:
  - `packages/agent-handoff-mcp/src/agent_handoff_mcp/cli.py`: keep subcommand names/help text aligned with the new compound tools or document intentional compatibility aliases
  - `packages/agent-handoff-mcp/README.md`: update the command map and examples to match the final surface
- Update harness hook matchers atomically with the tool rename:
  - `.github/hooks/terminal-guard.json`: update all PostToolUse matchers that reference old tool names (e.g. `mcp_altcontext-mc_generate_current_task_md` becomes `mcp_altcontext-mc_render_handoff`)
  - `.claude/settings.json`: update all PostToolUse hooks that reference old tool names (e.g. `mcp__agent-handoff-mcp__generate_dashboard_md` becomes `mcp__agent-handoff-mcp__render_handoff`)
  - `.github/copilot-instructions.md`: update the deferred-tool list to reflect the new compound tool names
- Update contracts docs to the new MCP tool names.
- Normalize the post-AHMCP-23 `DASHBOARD.md` → `DASHBOARD.txt` drift atomically with the `generate_dashboard_md` → `render_handoff` rename, because the same surfaces (contracts, playbooks, skills, instructions, lifecycle-map, development-workflow, the Makefile comment on `dashboard:`, the `dashboard_extension.py` module docstring) are touched by both changes: <!-- lint-dashboard-txt: allow -->
  - `docs/agentic/contracts/agent-handoff-mcp.md`
  - `docs/agentic/instructions.md`
  - `docs/agentic/lifecycle-map.md`
  - `docs/agentic/rules/development-workflow.md`
  - `docs/agentic/playbooks/worktree-orchestration-playbook.md`
  - `docs/agentic/playbooks/host-adapters/worktree-codex-playbook.md`
  - `.claude/skills/branch-lifecycle/SKILL.md`, `.claude/skills/handoff-lifecycle/SKILL.md`
  - `.claude/commands/handoff-lifecycle.md`
  - `config/agent-workflows/portable_commands.json` (plus regenerate adapters via `make generate-agent-workflows`)
  - `Makefile` `dashboard:` target comment
  - `packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/orchestration/dashboard_extension.py` module docstring
  - leave archived task plans (AHMCP-23, AHMCP-25, E17-5) and test fixtures alone — they are either historical or use explicit `dashboard_path` overrides

Proof:

- Compound-tool dispatch tests pass.
- Python aliases still resolve.
- CLI help/README examples match the final renamed or aliased surface.
- Tool count matches the re-scoped 4A-only compression target.
- Hook matchers reference only the new compound tool names; no stale references remain.
- After the rename, `render_handoff(kind="dashboard")` (or its equivalent compound invocation) writes exactly `DASHBOARD.txt` at the workspace root with no accompanying `DASHBOARD.md`; `cat DASHBOARD.txt` matches the previous `generate_dashboard_md()` output byte-for-byte modulo the timestamp line. <!-- lint-dashboard-txt: allow -->
- `grep -rn DASHBOARD.md` across tracked non-archive markdown + Makefile + the `dashboard_extension.py` module docstring returns zero hits after Slice 4 lands (the CI guard for this lives in E17-9 Slice 4 at [scripts/hooks/lint-dashboard-txt.py](../../../scripts/hooks/lint-dashboard-txt.py), wired into `make lint-dashboard-txt` and `make check-all`). <!-- lint-dashboard-txt: allow -->
- Agent-visible token budget check: the compressed tool surface reduces per-turn request token cost for common Get-state + record-event + dashboard-regenerate flows, measured against the pre-compression baseline captured during Slice 4 implementation.

### Slice 5: Parallel-Review Backend Groundwork (Additive)

**Goal**: front-load the two small additive `review_findings` pieces that the successor E17-9 parallel-review workflow depends on, so the new skill work in E17-9 does not block on a second cross-surface slice against the same table Slice 2 already touches.

Motivation: The [parallel-reviews-and-autonomous-debug assessment](../../assessments/parallel-reviews-and-autonomous-debug-assessment-2026-04-16.md) proposes a parallel-branch-review skill (landed in E17-9) where multiple subagents — Claude Code Agent tool, `codex exec` subprocess, or `run_structured_turn` copilot bridge — each write findings under their own scoped `task_ref` and a coordinator merges them under the parent task. Two tiny backend additions are load-bearing for that coordinator and cheap to land here because the surfaces overlap Slice 2's `handoff_state` re-key work:

1. A `merge` operation on `review_findings` so the coordinator can unify per-reviewer finding sets atomically instead of issuing N sequential `operation="record"` calls that bypass existing batch guards.
2. An index on `(lane_id, status)` in the `review_findings` table so lane-scoped open-findings queries during the parallel-review fan-in stay fast as concurrent reviewers grow.

Neither is required by Slices 1-4. Both are orthogonal additive backend changes. They are included here, rather than in E17-9, because (a) they touch the same schema surface Slice 2 already migrates, so landing them in the same cross-schema slice set avoids a second schema-touching slice in E17-9; and (b) they give E17-9 a clean dependency target rather than making E17-9's first slice both a schema change and a new skill.

Changes:

- Extend `review_findings(review=...)` with `operation="merge"`: accepts `source_task_refs` (list) and `target_task_ref` (string) plus an optional `session` prefix for the merged rows. When `session` is omitted, the implementation auto-generates `merge-<target_task_ref>-<utc-ts>` so merged rows remain attributable without caller-supplied session text. Internally reuses the `batch_record` path so existing guards — duplicate-id rejection, `verified_commit_sha` validation, branch enforcement, reviewer-write-mode checks — continue to apply. Every merged row records a `merged_from` provenance pointer stored in a nullable `merged_from_json` column as a JSON object keyed by the source `(task_ref, session, finding_id)` triple.
- Add an idempotent SQL migration for `idx_review_findings_lane_status` using `CREATE INDEX IF NOT EXISTS ... ON review_findings(lane_id, status)` in `shared_schema.py`.
- Append a short note on the `merge` operation to `packages/agent-handoff-mcp/docs/guides/token-efficient-usage.md` (one paragraph, one example).
- No CLI exposure in this slice; the E17-9 coordinator skill calls the Python API directly. If CLI exposure is desired later, it lands under E17-9.
- No MCP tool surface compression concerns: the existing `review_findings` compound tool already dispatches by `operation`; adding `operation="merge"` does not grow the advertised tool count.

Constraints:

- `merge` must be a no-op write for empty source sets (validated error, not silent success) so coordinator bugs surface immediately.
- Provenance is non-optional: every merged row stores `merged_from`. Readers (list/get ops) return `merged_from` when present; absent readers continue to work without it.
- Migration for the new index must be additive — no data rewrite, no downtime, compatible with Slice 2's in-place migration path or coordinated export/reimport.

Proof:

- A test records findings under two distinct `task_ref`s with 3 findings each, calls `operation="merge"` with both source `task_ref`s into a coordinator `task_ref`, and asserts: (a) 6 rows appear under the coordinator `task_ref`, (b) each has a `merged_from` entry naming its source triple, (c) existing reviewer rows under the sources remain intact (merge is additive, not destructive).
- A concurrent-merge test runs two coordinator merges against overlapping source `task_ref`s and asserts the second call fails deterministically with duplicate-id protection or lands a documented idempotent outcome.
- `EXPLAIN QUERY PLAN SELECT ... FROM review_findings WHERE lane_id=? AND status='open'` reports use of `idx_review_findings_lane_status`.
- All existing `review_findings` tests continue to pass; no response envelope enlargement on `list`/`get` operations when `merged_from` is absent.

---

## Consolidated Checklist

### Slice 1: Portable Workflow Normalization + Python Runtime Contract

- [x] `scripts/generate_agent_workflows.py` generates a Codex router artifact
- [x] `docs/agentic/instructions.md` and `CLAUDE.md` consume generated Codex router content
- [x] `docs/agentic/instructions.md` and `CLAUDE.md` use the required begin/end markers for the generated Codex router block
- [x] Conflicting guide-first review routing is removed from those surfaces
- [x] `.vscode/mcp.json`, `.codex/config.toml`, and `.mcp.json` all set `PYENV_VERSION=description-service`
- [x] `.codex/config.toml` and `.mcp.json` no longer hardcode user-local absolute repo paths
- [x] Startup docs front-load `PYENV_VERSION=description-service` as the canonical non-interactive Python/MCP rule
- [x] `pyenv activate description-service` remains documented only as optional interactive-shell setup
- [x] `make check-agent-workflows` validates Claude, VS Code, and Codex generated artifacts
- [x] `make check-codex-command-router` exists and fails on drift
- [x] `make smoke-agent-workflows` exists as an optional runtime validation

### Slice 2: Multi-Active Tasks + Slice Status

- [x] `handoff_state` re-keyed by `task_ref`
- [x] `_resolve_task_ref` handles concurrent active tasks safely
- [x] `slices_completed` is available in `load_session` and `get_handoff_state`
- [x] Any future checkbox-sync-on-`main` follow-on is gated on E17-8 Slice 1 landing `docs/tasks/**/*.md` in `permitted_main_surfaces`
- [x] Task-plan checkbox sync and stale-checkbox warning are explicitly deferred and not retained in Slice 2 scope

### Slice 3: Test Trace Archive

- [x] `HANDOFF_SCHEMA_VERSION` bumped and warm-start migration adds `test_traces` for existing databases
- [x] `test_traces` table added
- [x] `record_test_result` stores optional traces
- [x] `get_verified_tests` supports `include_traces`, `correlated_file`, `correlation_window_minutes`, and `exclude_never_passed`
- [x] `include_traces=False` returns `trace_count` metadata without full trace bodies

### Slice 4: Tool Surface Compression

- [x] Sub-slice 4A: `render_handoff` replaces the two rendering MCP tools
- [ ] ~~Sub-slice 4B: `handoff_transfer` replaces export/import MCP tools~~ (DEFERRED — see scope note above)
- [ ] ~~Sub-slice 4C: `task_archive` replaces archive/get MCP tools~~ (DEFERRED — see scope note above)
- [x] Python compatibility aliases remain available
- [x] Bounded-read envelope (`sections`, `detail`, `top_n_*`) preserved on every compound tool — no default response enlargement
- [x] `slim-handoff-response` PostToolUse hook matcher updated atomically with the tool rename so response slimming keeps applying
- [x] Dashboard still writes to `DASHBOARD.txt` at the workspace root; no `DASHBOARD.md` artifact produced <!-- lint-dashboard-txt: allow -->
- [x] `DASHBOARD.md` → `DASHBOARD.txt` cleanup applied to docs, playbooks, skills, Makefile comment, and the `dashboard_extension.py` module docstring (archived plans + test fixtures intentionally left alone) <!-- lint-dashboard-txt: allow -->
- [x] CLI subcommands/help text and `packages/agent-handoff-mcp/README.md` stay aligned with the renamed or aliased tool surface
- [x] Hook matchers in `terminal-guard.json` and `.claude/settings.json` updated atomically
- [ ] ~~Deferred-tool list in `copilot-instructions.md` updated~~ (N/A — the VS Code `availableDeferredTools` surface is runtime-injected from registered MCP tools; `.github/copilot-instructions.md` has no static list to edit)
- [x] No stale old-name references remain in harness configs
- [x] Token-budget smoke: common Get-state + record-event + dashboard-regenerate flow has a lower agent-visible token cost than pre-compression baseline (tool count 22→21; regression guard in `tests/test_adapters.py:133-163`)

### Slice 5: Parallel-Review Backend Groundwork

- [x] `review_findings(operation="merge", ...)` implemented via the existing batch_record path; all existing guards apply
- [x] Every merged row records `merged_from` provenance (source `(task_ref, session, finding_id)` triple stored in `merged_from_json`)
- [x] Empty-source merge is a validated error, not a silent no-op
- [x] Source reviewer rows remain intact after merge (additive, not destructive)
- [x] `idx_review_findings_lane_status` migration added with `CREATE INDEX IF NOT EXISTS`; `EXPLAIN QUERY PLAN` confirms index use for `lane_id`+status queries
- [x] Token-efficient usage guide updated with one-paragraph note and one example for `merge`
- [x] No regression in existing `review_findings` tests; response envelope unchanged when `merged_from` absent

## Review Readiness

- [x] E17-6 core is approved or complete before this task starts
- [x] `make check-agent-workflows` is green after Slice 1
- [x] `make test-handoff` is green after each schema/tooling slice
- [ ] `make test-orchestrator` is green when schema-facing behavior changes

## Success Criteria

- [ ] Codex, Claude, and VS Code command routing all derive from `portable_commands.json`
- [ ] `/branch-review` and `/planning-review` no longer rely on handwritten Codex-only router text
- [ ] All supported harnesses resolve Python/MCP commands through the same `description-service` pyenv contract and portable committed startup paths
- [ ] Concurrent active tasks are supported without singleton eviction
- [ ] Cold-start agents can retrieve raw test traces on demand
- [ ] The MCP tool surface is compressed without breaking Python imports
