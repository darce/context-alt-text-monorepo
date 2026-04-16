# E17-6. Phase 3 Retrofit — Skill Anatomy Completion, Harness Protocol Contract, Routing Redirect, and Planning Gate Wiring

- **Date**: 2026-04-14
- **Author**: Claude Sonnet 4.6
- **Owning Epic**: [docs/epics/v0.4.0/skill-formalization-and-process-automation-epic.md](../../epics/v0.4.0/skill-formalization-and-process-automation-epic.md)
- **Epic Short ID**: E17
- **Target Branch**: `feature/e17-6`
- **Review Coverage Target**: 2

---

## Objective

Retrofit the 11 non-compliant skills to the anatomy template, add a headless `make check-skills` validator that enforces anatomy compliance in CI, establish a canonical `harness-protocol.yaml` contract that defines cold-start steps, hook event matchers, and Python API fallback surface as a single source of truth for all agent harnesses (eliminating cross-harness drift), redirect `CLAUDE.md` and `instructions.md` triggers to skills as primary entry points (removing inline prose that duplicates skill content), and wire `plan-analyze` as a required precheck before `make plan-review` can proceed. When this task is complete, every skill passes `make check-skills`, both harness surfaces are verifiably in sync via `make check-harness-sync`, agents are routed to skills rather than bulk guide loading, and the planning pipeline has a machine-enforced pre-review analysis gate.

## Problem Statement

Phase 1 and Phase 2 of E17 created anatomy-compliant skills for the eight core workflows (tdd, incremental-implementation, scope, branch-lifecycle, handoff-lifecycle, branch-review, planning-review, plan-analyze). Three early legacy skills (commit2git, review, investigate) received partial Phase 1 retrofits (process content updates) but were not brought to full anatomy compliance — they still lack `tdd_gate`, `context_budget`, `makefile_target`, and `mcp_tools` frontmatter fields. Eleven pre-E17 skills require full or partial anatomy retrofit:

- **No frontmatter**: refactor, security-audit, document-sync
- **Partial frontmatter — Phase 1 retrofits** (missing tdd_gate, context_budget, makefile_target, mcp_tools): commit2git, investigate, review
- **Partial frontmatter** (missing mode, tdd_gate, context_budget, makefile_target, mcp_tools): daemon-lifecycle, worktree-orchestrator, worktree-worker, rescue-lane, subfeature-committer

Four structural gaps remain from the Phase 3 scope:

1. **No anatomy enforcement**: There is no `make check-skills` target. Whether a skill is anatomy-compliant is checked manually. Any new skill can ship without required frontmatter.
2. **Cross-harness protocol drift**: Cold-start steps, hook event matchers, and Python API fallback guidance are duplicated in prose across `CLAUDE.md`, `.github/copilot-instructions.md`, `.claude/settings.json`, and `.github/hooks/terminal-guard.json`. There is no canonical source. Drift is already observed: `.claude/settings.json` has a PostToolUse `regenerate-task-views.sh` hook for 5 MCP tool matchers; `.github/hooks/terminal-guard.json` does not have it at all. Claude agents guessed at 4 wrong Python API import paths because the fallback guidance used `...` instead of naming the importable surface. The `mcp-tool-routing.yaml` pattern (one canonical YAML → harnesses read it) proves the approach works; hook matchers and cold-start steps need the same treatment.
3. **Routing is still guide-first**: `CLAUDE.md` Key Triggers and `instructions.md` role routing still point agents at `branch-review-guide.md` and `planning-review-guide.md` as primary execution surfaces. Agents load 250+ lines of guide when the 150-line skills cover the executable path. The context bloat problem the skills were built to solve remains in the routing surface.
4. **No planning gate**: `make plan-review` does not verify that a `plan-analyze` run has been recorded for the target document. The skill prompts agents to run plan-analyze first, but nothing enforces it.

## Constraints

- `make check-skills` must be headless and CI-safe (no agent, no MCP, no network). Exit 0 on all-pass, non-zero on any failure.
- The wiring check in `make check-skills` uses a hardcoded known-tools registry (derived from `docs/agentic/maps/mcp-tool-routing.yaml`) rather than live MCP introspection — no runtime dependency on a running MCP server.
- Skill body edits (adding rationalizations, red flags, convergence criteria) must preserve existing process content. The retrofit adds anatomy sections; it does not rewrite the skill's core process.
- CLAUDE.md and instructions.md edits remove prose that duplicates skill content. Prose that provides rationale, edge cases, or context not covered by the skill is kept.
- The planning exit gate warns rather than hard-blocks on the first rollout. Hard enforcement (exit non-zero) is opt-in via `PLAN_ANALYZE_REQUIRED=1`. See Constraints note on slice 4.
- No new MCP tools (per epic constraint). The plan-analyze precheck queries existing MCP review findings via the Python API.
- No changes to skill execution logic or MCP handoff protocol.
- `harness-protocol.yaml` is the canonical source for cross-harness protocol. Harness-specific surfaces (`.claude/settings.json`, `.github/hooks/terminal-guard.json`, `CLAUDE.md`, `.github/copilot-instructions.md`) are consumers, not sources. The YAML defines what must be true; the validator checks that it is.
- `make check-harness-sync` must be headless and CI-safe. It parses the YAML contract and the two harness hook files, compares hook event matchers, and exits non-zero on drift. No MCP or network dependency.
- Harness-specific prose (Copilot's tool-selection decision tree, Claude's `ToolSearch` syntax, IDE workarounds) stays in the harness-specific instruction files. The protocol contract covers only the shared behavioral surface: cold-start steps, hook event matchers, Python API fallback imports, and branch isolation policy.

## Terminology

- **Anatomy retrofit**: adding the required frontmatter fields (name, description, mode, tdd_gate, context_budget, makefile_target, mcp_tools) and required section headers (Overview, Trigger, Core Process, Red Flags, Convergence Criteria) to a legacy skill that predates the anatomy template.
- **Known-tools registry**: a hardcoded list of MCP tool names derived from `docs/agentic/maps/mcp-tool-routing.yaml`, embedded in the `check-skills` script and used to validate `mcp_tools` frontmatter values without a live MCP connection.
- **Wiring check**: the `check-skills` validator step that confirms each skill's declared `makefile_target` appears as a target in the root `Makefile` (or `mk/` includes) and each `mcp_tools` entry appears in the known-tools registry.
- **Reference appendix**: a guide labelled explicitly as reference documentation (not the execution surface) once a discrete execution skill covers its executable path. Agents are directed to the skill; the guide is linked for rationale and edge cases.
- **Planning exit gate**: a precheck step in `make plan-review` that verifies at least one `plan-analyze` review run with recorded findings exists for the target document before the planning-review skill proceeds.
- **Harness protocol contract**: a YAML file (`docs/agentic/contracts/harness-protocol.yaml`) that declares the canonical cold-start steps, hook event matchers, Python API fallback surface, and branch isolation policy shared by all agent harnesses. Harness-specific settings files are validated against this contract by `make check-harness-sync`.
- **Harness projection**: the process of deriving harness-specific hook definitions (`.claude/settings.json`, `.github/hooks/terminal-guard.json`) and instruction sections (`CLAUDE.md`, `.github/copilot-instructions.md`) from the canonical protocol contract. Deterministic for hook matchers; prose for harness-specific capabilities.

## Current State Analysis

**Skills directory**: `.claude/skills/` contains 19 skill directories. 8 are anatomy-compliant (full frontmatter + section headers). 11 are not:

| Skill | Frontmatter state | Missing |
|---|---|---|
| refactor | none | all fields + all sections |
| security-audit | none | all fields + all sections |
| document-sync | none | all fields + all sections |
| commit2git | partial (name, description) | tdd_gate, context_budget, makefile_target, mcp_tools |
| investigate | partial (name, description) | tdd_gate, context_budget, makefile_target, mcp_tools |
| review | partial (name, description) | tdd_gate, context_budget, makefile_target, mcp_tools |
| daemon-lifecycle | partial (name, description, argument-hint) | mode, tdd_gate, context_budget, makefile_target, mcp_tools; section headers |
| worktree-orchestrator | partial (name, description) | mode, tdd_gate, context_budget, makefile_target, mcp_tools; section headers |
| worktree-worker | partial (name, description) | mode, tdd_gate, context_budget, makefile_target, mcp_tools; section headers |
| rescue-lane | partial (name, description, disable-model-invocation) | mode, tdd_gate, context_budget, makefile_target, mcp_tools; section headers |
| subfeature-committer | partial (name, description, disable-model-invocation) | mode, tdd_gate, context_budget, makefile_target, mcp_tools; section headers |

**Makefile**: No `check-skills` target exists. `make check-all` runs lint, tests, hooks validation, task-plan lint, and worktree audit (E17-4), but not skill anatomy validation.

**CLAUDE.md**: The Key Triggers section points agents at `branch-review-guide.md` and `planning-review-guide.md` by file path. The Role Selection table does not reference skills. The Branch Review and Planning Review trigger descriptions do not mention the `/branch-review` or `/planning-review` slash commands or their skill files.

**instructions.md**: The Additional Routing section (below the Role Selection table) already references some skills by slash command. The Role Selection table itself references guides as primary execution surfaces. Slice 3 needs to redirect the Role Selection table entries and add missing skill references, but the Additional Routing section requires less work than a full rewrite. Planning pipeline routing (Assessment → Spec → Task Plan) does not reference the `plan-analyze` skill as a required pre-step.

**`mk/handoff.mk` plan-review target**: prints the skill name and expected output but performs no precheck. An agent can run `make plan-review` on a document with no prior `plan-analyze` findings.

**Cross-harness hook drift**: Both harnesses now have 4 PreToolUse blocks and 5 PostToolUse blocks. The `regenerate-task-views.sh` PostToolUse hook (dashboard refresh after state-changing MCP writes) is present in both `.claude/settings.json` and `.github/hooks/terminal-guard.json`. One gap remains: `.claude/settings.json` has `validate-mcp-dict-params.py` as a PreToolUse hook on `record_event|review_findings|review_runs` matchers, but `.github/hooks/terminal-guard.json` lacks this hook. No validator exists to detect this drift or prevent future divergence.

**Cross-harness instruction drift**: `CLAUDE.md` § Agent Startup Protocol defines 9 cold-start steps. `.github/copilot-instructions.md` § Agent Cold-Start Orientation defines 4 steps (recently added but not yet verified against CLAUDE.md for completeness). The Python API fallback section was duplicated in both files with slightly different content. No canonical source governs the shared behavioral protocol.

## Target Outcome

- `make check-skills` exits 0 on a clean `.claude/skills/` run and non-zero with a named failure list on any anatomy violation. Integrated into `make check-all`.
- All 19 skills in `.claude/skills/` pass `make check-skills`.
- A cold-start agent reading `CLAUDE.md` Key Triggers is routed to a named skill and slash command — not to a guide file — for every major workflow trigger.
- `branch-review-guide.md` and `planning-review-guide.md` carry an explicit "Reference Appendix" label at the top.
- `docs/agentic/contracts/harness-protocol.yaml` defines canonical cold-start steps, hook event matchers (with MCP tool names), Python API fallback imports, and branch isolation policy.
- `make check-harness-sync` exits 0 when both harness hook files match the protocol contract; exits non-zero and names every drifted hook on mismatch. Integrated into `make check-all`.
- Running `make plan-review DOC=<path>` without a prior `plan-analyze` run (or with `PLAN_ANALYZE_REQUIRED=1`) prints a warning/block naming the missing analysis run.

## Context Loading

- Anatomy template: `docs/agentic/templates/SKILL_ANATOMY.template.md`
- MCP tool routing: `docs/agentic/maps/mcp-tool-routing.yaml`
- Existing anatomy-compliant skill for reference: `.claude/skills/branch-review/SKILL.md`
- Routing surfaces to change: `CLAUDE.md` § Key Triggers, `docs/agentic/instructions.md` § Role Routing
- Planning entry point: `mk/handoff.mk` plan-review and plan-analyze targets
- Planning pipeline rules: `docs/agentic/rules/planning-pipeline.md`
- Review guides: `docs/agentic/rules/branch-review-guide.md`, `docs/agentic/rules/planning-review-guide.md`
- Harness hook surfaces: `.claude/settings.json`, `.github/hooks/terminal-guard.json`
- Harness instruction surfaces: `CLAUDE.md` § Agent Startup Protocol, `.github/copilot-instructions.md`
- Existing canonical YAML pattern: `docs/agentic/maps/mcp-tool-routing.yaml` (proves the one-YAML-many-consumers model)
- Python API surface: `packages/agent-handoff-mcp/src/agent_handoff_mcp/__init__.py` (`__all__` list)

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
|---|---|---|---|---|---|
| `make check-skills` | `scripts/check_skills.py` (new) | Does not exist | New headless validator; exit 0 on pass, non-zero on failure | n/a — new target | `make check-skills` exits 0 after retrofit |
| `make check-all` | root `Makefile` | Runs lint, tests, hooks, task-plan lint, worktree-audit | Add `check-skills` step | non-breaking — additive | `make check-all` completes without regression |
| `make plan-review` | `mk/handoff.mk` | Prints skill + checklist info; no precheck | Prints plan-analyze gate status; warns if analysis run absent | non-breaking — warning only on default; block on opt-in | `make plan-review DOC=... PLAN_ANALYZE_REQUIRED=1` blocks when no analysis run exists |
| `CLAUDE.md` | root `CLAUDE.md` | Key Triggers reference guides by path | Redirect to skill slash commands; remove duplicate inline prose | non-breaking for agents — new routing is clearer | Agent cold-start routes to skill, not guide |
| `docs/agentic/instructions.md` | docs | Role routing table references guides | Add skill as primary entry point; guide becomes reference link | non-breaking — additive | Manual review |
| `branch-review-guide.md` | docs | Primary execution surface | Add "Reference Appendix" header | non-breaking — additive | File header present after slice |
| `planning-review-guide.md` | docs | Primary execution surface | Add "Reference Appendix" header | non-breaking — additive | File header present after slice |
| `harness-protocol.yaml` | `docs/agentic/contracts/` (new) | Does not exist | New canonical contract for cross-harness protocol | n/a — new file | `make check-harness-sync` exits 0 |
| `make check-harness-sync` | `scripts/check_harness_sync.py` (new) | Does not exist | New validator; compares hook files against protocol contract | n/a — new target | Exits non-zero on intentional drift |
| `.claude/settings.json` | `.claude/` | Claude Code hooks | Validated against protocol contract; add `guard-format-clean` PreToolUse hook on `close_slice\|handoff_close_check` | non-breaking — additive hook | `make check-harness-sync` passes; unformatted code blocks `close_slice` |
| `.github/hooks/terminal-guard.json` | `.github/hooks/` | VS Code/Copilot hooks | Add missing hooks to reach protocol parity incl. `guard-format-clean`; validated against contract | non-breaking — additive | `make check-harness-sync` passes |
| `guard-format-clean.sh` | `scripts/hooks/` (new) | Does not exist | PreToolUse hook: runs formatters in check mode on branch-changed files; blocks `close_slice`/`handoff_close_check` if unformatted | n/a — new script | Unformatted file on branch → hook blocks; `make format-all` → hook passes |
| `sync-task-plan-checkboxes.sh` | `scripts/hooks/` (new) | Does not exist | PostToolUse hook: auto-checks task plan checkboxes after `close_slice`; warning-only on no match | n/a — new script | `close_slice` → matching checklist items become `[x]`; no match → warning, exit 0 |
| `make context` | `scripts/context.sh` | Branch/worktree drift check | Add stale-checkbox drift warning comparing slice-complete decisions vs unchecked task plan boxes | non-breaking — additive warning | Stale plan prints warning; synced plan is silent |
| `load_session` | `core.py` | Returns session state without slice-completion status | Add `slices_completed` section listing all slice-complete decisions with labels and timestamps | non-breaking — additive section in existing response | Cold-start `load_session` shows 3 closed slices |
| `handoff_state` schema | `shared_schema.py` | Singleton `id = 1` active task row | Re-key by `task_ref`; support N concurrent in_progress rows | breaking schema change (greenfield — no migration needed) | `make test-handoff` passes; two agents resolve independently |
| `_resolve_task_ref()` | `shared_primitives.py` | Returns `task_ref` from singleton `WHERE id = 1` when not passed explicitly; 31 callers | Evolve to add cwd-based worktree matching; raises `AmbiguousActiveTaskError` when >1 active and no cwd match | non-breaking for callers passing explicit `task_ref`; behavior change for `task_ref=None` callers | Unit tests for cwd match, single-active fallback, ambiguous error |
| `switch_task` | `import_export.py` | Archives previous task on switch | Sets `activated_at` without archiving | breaking behavior change (intentional — eliminates eviction) | `switch_task("B")` leaves task A in_progress |
| `generate_dashboard_md` | `dashboard_rendering.py` | Renders one active task | Renders all in_progress tasks | non-breaking — additive rendering | Dashboard contains both task refs |
| `test_traces` table | `shared_schema.py` (new) | Does not exist | New append-only table for raw test stdout/stderr keyed to `verified_tests.id` | n/a — new table | `make test-handoff` passes; `get_verified_tests(include_traces=True)` returns stored content |
| `record_test_result` | `decisions.py` | Stores 280-char summary in `result` | Accept optional `traces` list; store raw content in `test_traces` | non-breaking — additive optional field | Existing callers without `traces` produce identical rows |
| `get_verified_tests` | `verified_tests.py` | Queries test rows with task/branch/pass filters | Add `include_traces`, `correlated_file`, `correlation_window_minutes` optional params | non-breaking — all new params have defaults preserving existing behavior | Existing callers get identical response; new params enable trace/correlation queries |
| `generate_current_task_md` + `generate_dashboard_md` | `api.py` | 2 separate MCP tools | Merge into `generate_md(target="dashboard"\|"current_task")`. Rename dashboard output to DASHBOARD.txt in tool name/description (already .txt on disk). | breaking MCP tool name — callers must update to `generate_md` | `generate_md(target="dashboard")` and `generate_md(target="current_task")` produce identical output to predecessors |
| `export_handoff_state` + `import_handoff_state` | `api.py` | 2 separate MCP tools | Merge into `handoff_transfer(operation="export"\|"import")` | breaking MCP tool name — callers must update to `handoff_transfer` | `handoff_transfer(operation="export")` produces identical output; import round-trips correctly |
| `archive_task_state` + `get_archived_task` | `api.py` | 2 separate MCP tools | Merge into `task_archive(operation="archive"\|"get")` | breaking MCP tool name — callers must update to `task_archive` | `task_archive(operation="archive")` and `task_archive(operation="get")` produce identical output to predecessors |

## Proposed Solution

Eight slices deliver Phase 3. Slices 1 and 2 are independent and can be implemented in either order. Slice 3 (harness protocol contract) is independent of Slices 1–2 but must precede Slice 4 (routing redirect), because the routing redirect should derive shared cold-start and fallback content from the canonical protocol rather than duplicating it in prose. Slice 5 (planning gate) is independent.

**Scope extension — Slices 6, 7, and 8**: These three slices extend beyond the original E17-6 / Phase 3 scope defined in the epic. The epic's Phase 3 deliverables are limited to skill retrofit, `check-skills`, harness protocol contract, routing redirects, and planning gate wiring. Slices 6, 7, and 8 add `agent-handoff-mcp` schema and API work (multi-active-task registry, test trace archive, tool surface compression) that is architecturally upstream of the Phase 3 doc/tooling changes and was included here to co-locate the full agent-workflow improvement set. The epic should be amended (or a follow-on task series created, e.g., E17-7/E17-8/E17-9) to formally authorize this scope before implementation of these slices begins. Until that authorization is recorded, Slices 6, 7, and 8 are included as a scope-extension proposal only and must not be started without explicit epic or ADR approval. Slices 1–5 are fully within the original E17-6 scope and may proceed independently.

Slice 6 (multi-active-task registry) is independent of Slices 1–5 — it changes the `agent-handoff-mcp` state model while the other slices change docs, scripts, and Makefile targets — and can be implemented in parallel once authorized. Slice 7 (test trace archive) depends on Slice 6's schema work being complete but is otherwise independent; it extends the `verified_tests` surface with raw trace storage and change-outcome linkage. Slice 8 (tool surface compression) is independent of Slices 1–7 and can be implemented at any point once authorized; it merges 6 single-purpose tools into 3 compound tools, reducing the MCP surface from 22 to 19 registered tools.

## Files and Surfaces to Change

| Surface | File | Change |
|---|---|---|
| Skill retrofit | `.claude/skills/refactor/SKILL.md` | Add full frontmatter + section headers |
| Skill retrofit | `.claude/skills/security-audit/SKILL.md` | Add full frontmatter + section headers |
| Skill retrofit | `.claude/skills/document-sync/SKILL.md` | Add full frontmatter + section headers |
| Skill retrofit | `.claude/skills/daemon-lifecycle/SKILL.md` | Add missing frontmatter fields + section headers |
| Skill retrofit | `.claude/skills/worktree-orchestrator/SKILL.md` | Add missing frontmatter fields + section headers |
| Skill retrofit | `.claude/skills/worktree-worker/SKILL.md` | Add missing frontmatter fields + section headers |
| Skill retrofit | `.claude/skills/rescue-lane/SKILL.md` | Add missing frontmatter fields + section headers |
| Skill retrofit | `.claude/skills/subfeature-committer/SKILL.md` | Add missing frontmatter fields + section headers |
| Check script | `scripts/check_skills.py` | New: validate frontmatter fields + section headers + wiring |
| Makefile target | `mk/handoff.mk` or root `Makefile` | Add `check-skills` target; wire into `check-all` |
| Harness protocol | `docs/agentic/contracts/harness-protocol.yaml` | New: canonical cold-start steps, hook event matchers, Python API surface, branch isolation policy |
| Harness sync script | `scripts/check_harness_sync.py` | New: validate `.claude/settings.json` and `.github/hooks/terminal-guard.json` against protocol contract |
| Makefile target | root `Makefile` | Add `check-harness-sync` target; wire into `check-all` |
| Hook parity fix | `.github/hooks/terminal-guard.json` | Add missing PreToolUse hook `validate-mcp-dict-params` to match protocol contract; add `guard-format-clean` PreToolUse hook |
| Format guard hook | `scripts/hooks/guard-format-clean.sh` | New: check-mode formatter on branch-changed files; blocks `close_slice`/`handoff_close_check` if unformatted |
| Format guard hook | `.claude/settings.json` | Add PreToolUse hook entry for `guard-format-clean.sh` on `close_slice\|handoff_close_check` matchers |
| Checkbox sync hook | `scripts/hooks/sync-task-plan-checkboxes.sh` | New: PostToolUse hook on `close_slice`; auto-checks matching task plan checklist items |
| Checkbox sync hook | `.claude/settings.json` | Add PostToolUse hook entry for `sync-task-plan-checkboxes.sh` on `close_slice` matcher |
| Checkbox sync hook | `.github/hooks/terminal-guard.json` | Add PostToolUse hook entry for `sync-task-plan-checkboxes.sh` on `close_slice` matcher |
| Context drift check | `scripts/context.sh` (or equivalent) | Add stale-checkbox warning comparing slice-complete decisions vs task plan checkboxes |
| Slice status section | `packages/agent-handoff-mcp/src/agent_handoff_mcp/core.py` | Add `slices_completed` section to `load_session` response |
| Slice status section | `packages/agent-handoff-mcp/src/agent_handoff_mcp/handoff_state.py` | Support `sections="slices_completed"` in `get_handoff_state` |
| Routing surface | `CLAUDE.md` | Redirect Key Triggers to skills; remove inline prose duplicating skill content; derive Python API fallback from protocol contract |
| Routing surface | `docs/agentic/instructions.md` | Redirect role routing table to skills as primary entry points |
| Reference label | `docs/agentic/rules/branch-review-guide.md` | Add "Reference Appendix" header block at top |
| Reference label | `docs/agentic/rules/planning-review-guide.md` | Add "Reference Appendix" header block at top |
| Planning gate | `mk/handoff.mk` plan-review target | Add plan-analyze precheck via Python query |
| Planning gate script | `scripts/check_plan_analyze.py` | New: query MCP review findings for analysis-mode run on target document |
| Planning pipeline doc | `docs/agentic/rules/planning-pipeline.md` | Add: plan-analyze is required before plan-review; document gate semantics |
| Schema (Slice 6) | `packages/agent-handoff-mcp/src/agent_handoff_mcp/shared_schema.py` | Re-key `handoff_state` by `task_ref`; drop `CHECK (id = 1)` singleton; add `activated_at` |
| Centralized resolver | `packages/agent-handoff-mcp/src/agent_handoff_mcp/shared_primitives.py` | Evolve `_resolve_task_ref` to add cwd-based worktree matching (captures 31 callers) |
| State functions | `packages/agent-handoff-mcp/src/agent_handoff_mcp/handoff_state.py` | Replace `WHERE id = 1` with task_ref-keyed queries (6 hits) |
| Write context | `packages/agent-handoff-mcp/src/agent_handoff_mcp/shared_write_context.py` | Update `collect_target_context_warnings()`, `_detect_git_write_context()` (2 hits) |
| Import/export | `packages/agent-handoff-mcp/src/agent_handoff_mcp/import_export.py` | Remove archive-on-switch; update DELETE/INSERT/UPDATE paths (10 hits) |
| Core | `packages/agent-handoff-mcp/src/agent_handoff_mcp/core.py` | Update `load_session`, `close_slice` (2 hits) |
| Decisions | `packages/agent-handoff-mcp/src/agent_handoff_mcp/decisions.py` | Update `_check_active_revision`, `_maybe_refresh_sha_from_active`, `update_task_status` (3 hits) |
| Review findings | `packages/agent-handoff-mcp/src/agent_handoff_mcp/review_findings.py` | Update `_check_active_revision`, `_resolve_handoff_status`, `repair_provenance` (4 hits) |
| API | `packages/agent-handoff-mcp/src/agent_handoff_mcp/api.py` | Update `update_task_status` (1 hit) |
| Current task rendering | `packages/agent-handoff-mcp/src/agent_handoff_mcp/current_task_rendering.py` | Update `_get_handoff_dashboard_view`, `_collect_task_snapshot` (3 hits) |
| Dashboard | `packages/agent-handoff-mcp/src/agent_handoff_mcp/dashboard_rendering.py` | Render N active tasks instead of one (2 hits) |
| Orchestrator tests | `packages/agent-orchestrator-mcp/tests/test_lanes_and_handoff_state.py`, `test_ace_metrics.py` | Update singleton fixtures to task_ref-keyed inserts (2 hits) |
| Schema (Slice 7) | `packages/agent-handoff-mcp/src/agent_handoff_mcp/shared_schema.py` | New `test_traces` table; schema version migration |
| Test trace storage | `packages/agent-handoff-mcp/src/agent_handoff_mcp/verified_tests.py` | Extend `get_verified_tests` with `include_traces`, `correlated_file`, `correlation_window_minutes` params |
| Test result recording | `packages/agent-handoff-mcp/src/agent_handoff_mcp/decisions.py` | Extend `record_test_result` to accept optional `traces` list |
| API surface | `packages/agent-handoff-mcp/src/agent_handoff_mcp/api.py` | Update `get_verified_tests` tool description and parameter schema for new optional params |
| Tool compression (Slice 8) | `packages/agent-handoff-mcp/src/agent_handoff_mcp/api.py` | Replace 6 ToolEntry registrations with 3 compound tools: `generate_md`, `handoff_transfer`, `task_archive` |
| Tool descriptions (Slice 8) | `packages/agent-handoff-mcp/src/agent_handoff_mcp/api.py` | Replace 6 TOOL_DESCRIPTIONS entries with 3; update `close_slice` description to reference `generate_md` |
| Handler functions (Slice 8) | `packages/agent-handoff-mcp/src/agent_handoff_mcp/api.py` | New compound handler functions with `operation`/`target` discriminators dispatching to existing implementations |
| Public exports (Slice 8) | `packages/agent-handoff-mcp/src/agent_handoff_mcp/__init__.py` | Replace `generate_dashboard_md` export with `generate_md`; add backward-compat aliases |
| Contract (Slice 8) | `docs/agentic/contracts/agent-handoff-mcp.md` | Update tool table: remove 6 rows, add 3 compound rows; correct tool-count prose to 19 |
| Hook matchers (Slice 8) | `.claude/settings.json`, `.github/hooks/terminal-guard.json` | Update PostToolUse hook matchers that reference `generate_dashboard_md` to `generate_md` |
| Instruction surfaces (Slice 8) | `CLAUDE.md`, `docs/agentic/instructions.md` | Update `generate_dashboard_md()` references to `generate_md(target="dashboard")` |
| Orchestrator integration (Slice 8) | `packages/agent-orchestrator-mcp/src/` | Update any `generate_dashboard_md` or `generate_current_task_md` imports/calls |

## Related Files

| File | Note |
|---|---|
| `docs/agentic/templates/SKILL_ANATOMY.template.md` | Reference for required frontmatter fields and section structure |
| `docs/agentic/maps/mcp-tool-routing.yaml` | Source for known-tools registry in check-skills wiring check |
| `.claude/skills/branch-review/SKILL.md` | Reference anatomy-compliant skill for retrofit comparison |
| `docs/agentic/constitution.md` | Loaded by plan-analyze; referenced in planning gate |
| `docs/agentic/maps/mcp-tool-routing.yaml` | Existing canonical-YAML-to-harness pattern; model for harness-protocol.yaml |
| `.claude/settings.json` | Claude Code hooks; consumer of harness protocol contract |
| `.github/hooks/terminal-guard.json` | VS Code/Copilot hooks; consumer of harness protocol contract |
| `.github/copilot-instructions.md` | Copilot instruction surface; consumer of harness protocol contract |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/__init__.py` | Authoritative `__all__` list for Python API imports |
| Meta-Harness paper | Lee et al., "Meta-Harness: End-to-End Optimization of Model Harnesses", arXiv:2603.28052v1, 2026 — raw execution traces outperform summaries by 15 points for causal debugging |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/verified_tests.py` | Test result queries — extend with trace/correlated-file params |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/touched_files.py` | File-touch ledger — joined for change-outcome linkage |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/shared_primitives.py` | `_summarize_test_result` — context for why raw traces are needed (280-char truncation) |
| `packages/agent-orchestrator-mcp/tests/test_ace_metrics.py` | Orchestrator test fixture with singleton insert — needs update |

## Verification Strategy

- Deterministic tests:
  - `python scripts/check_skills.py` exits 0 after all 11 skills are retrofitted
  - `make check-skills` exits 0; included in `make check-all` without breaking existing steps
  - `make check-skills` exits non-zero when a skill is missing a required field (manual: temporarily remove a field, verify failure, restore)
  - `make check-harness-sync` exits 0 after hook parity fix; exits non-zero on intentional hook removal
  - `make check-harness-sync --check-api-surface` validates Python API imports against live `__all__`
- Runtime-parity checks:
  - `make plan-review DOC=<path>` with no prior `plan-analyze` findings → prints gate warning; with `PLAN_ANALYZE_REQUIRED=1` → exits non-zero
  - `make plan-review DOC=<path>` after a recorded `plan-analyze` run → gate is silent
- Concurrent-task tests (Slice 6):
  - Two `set_handoff_state` calls for different task_refs both succeed; both rows have `status = 'in_progress'`
  - `resolve_active_task()` from worktree A's cwd returns task A; from worktree B returns task B; from unmatched cwd raises `AmbiguousActiveTaskError`
  - `switch_task("B")` does not archive task A
  - `generate_dashboard_md()` with two active tasks renders both in the active section
  - `make test-handoff` passes with no regressions
- Test trace archive tests (Slice 7):
  - `record_test_result(traces=[...])` → `get_verified_tests(include_traces=True)` returns raw content verbatim (not 280-char truncated)
  - `record_test_result()` without `traces` → `get_verified_tests(include_traces=True)` returns empty `traces` array (backward compat)
  - `get_verified_tests()` without new params → identical response shape to pre-slice (backward compat)
  - With `TRACE_RETENTION_PER_COMMAND` overridden to 3: 5 trace-bearing test results for same command → only newest 3 retain traces (bounded retention)
  - `get_verified_tests(correlated_file=<path>)` returns failing tests temporally correlated with file edits; excludes passing tests; excludes edits outside temporal window
  - `get_verified_tests(correlated_file=<path>, correlation_window_minutes=180)` expands the window to include longer test cycles
  - `make test-handoff` passes with no regressions after `test_traces` table migration
- Tool surface compression tests (Slice 8):
  - `generate_md(target="dashboard")` produces identical output to `generate_dashboard_md()`
  - `generate_md(target="current_task", task_ref="X")` produces identical output to `generate_current_task_md(task_ref="X")`
  - `handoff_transfer(operation="export"|"import")` round-trips correctly
  - `task_archive(operation="archive"|"get")` round-trips correctly
  - `from agent_handoff_mcp import generate_dashboard_md` still resolves (backward-compat alias)
  - `len(build_handoff_mcp().tools)` == 19
  - `make test-handoff` and `make test-orchestrator` pass with zero regressions
- Manual verification:
  - Cold-start read of `CLAUDE.md` Key Triggers → routing points to skill and slash command, not guide file path
  - Open `branch-review-guide.md` → "Reference Appendix" header visible at top
  - Open `planning-review-guide.md` → "Reference Appendix" header visible at top
  - Two terminal sessions in different worktrees: `make context` reports correct task identity in each

## Slice Delivery

### Slice 1: Skill Retrofit

**Goal**: All 11 non-compliant skills pass the anatomy checklist after this slice. `make check-skills` (from Slice 2) exits 0 across all 19 skills.

Changes — for each of the 11 skills (8 legacy + 3 Phase 1 partial retrofits):

- Add or complete frontmatter: `name`, `description`, `mode` (advisory or execution), `tdd_gate` (true or false), `context_budget` (line count), `makefile_target` (null if no Makefile entry), `mcp_tools` (list of MCP tool names the skill composes, empty list if none).
- Ensure these section headers exist in the body: `## Overview`, `## Trigger`, `## Core Process`, `## Red Flags`, `## Convergence Criteria`. Add stubs where absent; do not rewrite existing content.
- Add `## Common Rationalizations` where the skill is complex enough to have known rationalization failure modes (at minimum: refactor, worktree-orchestrator, worktree-worker, daemon-lifecycle).

Anatomy values by skill (to be confirmed against current body content during implementation):

| Skill | mode | tdd_gate | makefile_target | mcp_tools |
|---|---|---|---|---|
| refactor | advisory | false | null | [] |
| security-audit | advisory | false | null | [] |
| document-sync | advisory | false | null | [] |
| commit2git | advisory | false | null | [] |
| investigate | advisory | false | null | [] |
| review | advisory | false | null | [mcp__agent-handoff-mcp__review_findings, mcp__agent-handoff-mcp__review_runs] |
| daemon-lifecycle | execution | false | mcp-start | mcp__agent-orchestrator-mcp__manage_orchestrator, mcp__agent-orchestrator-mcp__manage_worker |
| worktree-orchestrator | execution | false | null | mcp__agent-orchestrator-mcp__manage_worktree_lane, mcp__agent-orchestrator-mcp__dispatch_lane_work, mcp__agent-handoff-mcp__record_event |
| worktree-worker | execution | true | null | mcp__agent-handoff-mcp__record_event, mcp__agent-handoff-mcp__close_slice, mcp__agent-orchestrator-mcp__worker_reports |
| rescue-lane | execution | false | null | mcp__agent-handoff-mcp__record_event |
| subfeature-committer | advisory | false | null | [] |

> **Implementation note**: confirm current body content before setting mode and mcp_tools — the table above is a best-estimate from the current SKILL.md headers. Do not invent tool usage that the skill body does not describe.

Proof:

- Each of the 11 retrofitted skills' frontmatter renders without YAML parse errors (`python -c "import yaml; yaml.safe_load(open('.claude/skills/<name>/SKILL.md').read().split('---')[1])"`)
- All required section headers present in each file (`grep -l "## Convergence Criteria" .claude/skills/*/SKILL.md` returns all 19 paths)
- Phase 1 retrofits (commit2git, investigate, review) gain `tdd_gate`, `context_budget`, `makefile_target`, `mcp_tools` without losing their existing process content

### Slice 2: `make check-skills` Validator

**Goal**: Headless CI-safe validator that enforces anatomy compliance across all skills in `.claude/skills/`. Integrated into `make check-all`.

Changes:

- New `scripts/check_skills.py`:
  - Discovers all `SKILL.md` files under `.claude/skills/` recursively.
  - For each skill, validates:
    1. **Frontmatter fields**: `name`, `description`, `mode`, `tdd_gate`, `context_budget`, `makefile_target`, `mcp_tools` are all present (values may be null/empty but keys must exist).
    2. **`mode` value**: must be `advisory` or `execution`.
    3. **`tdd_gate` value**: must be boolean.
    4. **Section headers**: `## Overview`, `## Trigger`, `## Core Process`, `## Red Flags`, `## Convergence Criteria` all appear in the body.
    5. **Wiring check — `makefile_target`**: if non-null, the declared target appears in the root `Makefile` or any `mk/*.mk` include (grep check; no Makefile parsing).
    6. **Wiring check — `mcp_tools`**: each tool name in the list appears in the known-tools registry (hardcoded dict derived from `docs/agentic/maps/mcp-tool-routing.yaml` at script authoring time; the script documents where the registry was sourced and when it was last updated).
  - Outputs: one line per failure with skill name, check type, and detail. Exits 0 on all-pass; exits 1 on any failure.
  - Flag `--fix-missing-sections` (optional): adds stub section headers to skills missing them, for use during the retrofit pass only.
- New `check-skills` target in `mk/handoff.mk`:
  - `python scripts/check_skills.py`
- Add `check-skills` step to `check-all` in root `Makefile`.

Proof:

- `make check-skills` exits 0 after Slice 1 (all skills retrofitted).
- Temporarily remove `## Convergence Criteria` from one skill → `make check-skills` exits 1 and names the skill; restore the header → exits 0 again.
- Temporarily add an unknown tool name to one skill's `mcp_tools` → wiring check fails with the tool name and skill named; remove it → exits 0.
- `make check-all` completes without regression on other steps.

### Slice 3: Harness Protocol Contract + Sync Validator

**Goal**: Establish a canonical YAML contract for cross-harness agent behavior and a headless validator that detects drift between the contract and each harness's hook/instruction surface.

Changes:

- New `docs/agentic/contracts/harness-protocol.yaml`:
  - `cold_start.steps[]`: ordered list of session-start steps (id, description, tool/command, required flag). Canonical source for what both CLAUDE.md § Agent Startup Protocol and `.github/copilot-instructions.md` § Agent Cold-Start Orientation must cover.
  - `hooks.post_tool_use{}` and `hooks.pre_tool_use{}`: each hook block declares a stable id, description, script path, and a list of MCP tool base names (e.g. `record_event`, `review_findings`) that trigger it. The validator expands these base names to the full matcher patterns (both `mcp_altcontext-mc_*` legacy and `mcp__agent-handoff-mcp__*` current) and checks that each harness hook file contains a matching entry.
  - `python_api.package`, `python_api.setup`, `python_api.imports{}` (categorized: setup, read, write, findings, runs, rendering), `python_api.anti_patterns[]`: canonical reference for the Python API fallback surface. Derived from `agent_handoff_mcp.__all__` at authoring time; the validator can optionally cross-check against the live `__all__` list.
  - `branch_isolation.protected_branches[]`, `branch_isolation.code_paths[]`, `branch_isolation.allowed_on_main[]`: canonical policy consumed by both guard-main-branch implementations.
- New `scripts/check_harness_sync.py`:
  - Parses `harness-protocol.yaml`.
  - Parses `.claude/settings.json` and `.github/hooks/terminal-guard.json`.
  - For each hook defined in the protocol, verifies both harness files contain a matching entry with equivalent MCP tool matchers. Reports missing hooks, extra hooks, and matcher drift by name.
  - Optionally (`--check-api-surface`): imports `agent_handoff_mcp`, compares `__all__` against `python_api.imports` in the contract, reports additions/removals.
  - Exits 0 on full sync; exits 1 on any drift with a named failure list.
- New `check-harness-sync` target in root `Makefile`, wired into `check-all`.
- Fix existing drift: add the missing `regenerate-task-views.sh` PostToolUse hook and `validate-mcp-dict-params.py` PreToolUse hook to `.github/hooks/terminal-guard.json` with matchers matching `.claude/settings.json`.
- New `scripts/hooks/guard-format-clean.sh`:
  - Runs formatters in check mode across changed files: `ruff format --check` + `ruff check --diff` on Python, `npm run format:check` on TS/JS (if applicable to the current worktree), `composer cs-check` on PHP (if applicable).
  - Scopes to files changed on the current branch vs `main` (`git diff --name-only main...HEAD`) to avoid checking unrelated code.
  - Exits 0 if all changed files are already formatted. Exits non-zero with an actionable message: "Unformatted code detected. Run `make format-all` before closing this slice."
  - Does not modify files — check-only. The agent must run `make format-all` explicitly so the formatting diff is visible and committed.
- New PreToolUse hook in both harness surfaces (`.claude/settings.json`, `.github/hooks/terminal-guard.json`):
  - Matcher: `close_slice|handoff_close_check` (both legacy `mcp_altcontext-mc_*` and current `mcp__agent-handoff-mcp__*` prefixes).
  - Command: `bash "$CLAUDE_PROJECT_DIR/scripts/hooks/guard-format-clean.sh"`.
  - Effect: agents cannot close a slice or pass the pre-merge gate with unformatted code. The hook blocks the MCP call and directs the agent to run `make format-all` first.
- Hook entry added to `harness-protocol.yaml` under `hooks.pre_tool_use{}` with id `guard-format-clean`, script path, and MCP tool base names `[close_slice, handoff_close_check]`.
- New `scripts/hooks/sync-task-plan-checkboxes.sh`:
  - PostToolUse hook on `close_slice`. Fires after a successful `close_slice` call.
  - Reads the task plan path from the active handoff state's `target_task_plan_path` field (or derives it from the task ref via the conventional path `docs/tasks/<epic>/<task-ref>-*-task-plan.md` or `packages/*/docs/tasks/<task-ref>-*-task-plan.md`).
  - Parses the `close_slice` decision id to extract the slice slug (everything after `_slice_complete_<work_ref>_`).
  - Searches the task plan for a `### Checklist for Slice` section whose heading fuzzy-matches the slug (case-insensitive, hyphen/underscore normalized).
  - Converts all `- [ ]` items under the matched section header to `- [x]`.
  - If no matching section is found, prints a warning ("Could not find checklist section for slice '<slug>' in <path>") but does not fail — the hook exits 0 regardless to avoid blocking `close_slice`.
  - Does not commit the checkbox changes — they appear as unstaged edits for the agent to include in the next commit.
- New PostToolUse hook in both harness surfaces (`.claude/settings.json`, `.github/hooks/terminal-guard.json`):
  - Matcher: `close_slice` (both legacy and current prefixes).
  - Command: `bash "$CLAUDE_PROJECT_DIR/scripts/hooks/sync-task-plan-checkboxes.sh"`.
  - Effect: after every successful slice close, the corresponding task plan checkboxes are automatically checked. Cold-start agents reading the task plan see accurate checkbox state reflecting MCP truth.
- Hook entry added to `harness-protocol.yaml` under `hooks.post_tool_use{}` with id `sync-task-plan-checkboxes`, script path, and MCP tool base name `[close_slice]`.
- Extend `make context` (`scripts/context.sh` or equivalent):
  - After the existing branch/worktree drift check, query the count of `*_slice_complete_*` decisions for the active task via the Python API.
  - Parse the active task plan for unchecked `- [ ]` items under `### Checklist for Slice` sections.
  - If slice-complete decisions exist but corresponding checkboxes are unchecked, print a warning: `"⚠ <N> slice-complete decisions recorded but task plan checkboxes are stale. Run scripts/hooks/sync-task-plan-checkboxes.sh to update."`
  - Warning only — does not block. Helps cold-start agents detect stale plans before wasting a cycle.

Proof:

- `make check-harness-sync` exits 0 after adding missing hooks to `terminal-guard.json`.
- Temporarily remove a PostToolUse hook from `terminal-guard.json` → `make check-harness-sync` exits 1 and names the missing hook; restore → exits 0.
- Introduce an unformatted Python file on the branch → `close_slice` is blocked by the hook with "Run `make format-all`" message. Run `make format-all` → `close_slice` proceeds.
- `close_slice` with a matching task plan checklist section → corresponding `- [ ]` items are converted to `- [x]` in the task plan file. Unstaged changes visible in `git diff`.
- `close_slice` with no matching checklist section → warning printed, hook exits 0, `close_slice` succeeds.
- `make context` on a task with 2 recorded slice-complete decisions and 0 checked boxes → prints stale-checkbox warning with the sync command.
- `make context` on a task with matching decisions and checkboxes → no warning.
- `make check-all` completes without regression.

### Slice 4: CLAUDE.md + instructions.md Routing Redirect

**Goal**: Key Triggers and role routing in both documents point agents to skills as the primary execution entry point. Inline prose that duplicates skill content is removed. Both review guides are labelled as reference appendices. The Python API fallback and cold-start protocol sections in both `CLAUDE.md` and `.github/copilot-instructions.md` reference `harness-protocol.yaml` as the canonical source rather than maintaining independent prose copies.

Changes:

- `CLAUDE.md` § Key Triggers:
  - Replace the current file-path references to `branch-review-guide.md` and `planning-review-guide.md` with skill and slash-command references (e.g. "run `/branch-review` skill" → `.claude/skills/branch-review/SKILL.md`, Makefile entry: `make review-run`).
  - Remove inline prose that restates the skill's Core Process or check sequence (any block that would cause an agent to follow CLAUDE.md steps instead of the skill).
  - Keep: trigger conditions (what patterns invoke the skill), the mandatory gate notes, and cross-references to guides "for rationale and edge cases."
- `docs/agentic/instructions.md` § Role Routing table:
  - Add a "Primary skill" column (or equivalent note) pointing to the relevant `.claude/skills/<name>/SKILL.md` for branch review and planning review rows.
  - Note that guides are reference appendices, not execution surfaces.
- `docs/agentic/rules/branch-review-guide.md`:
  - Add at top (before any existing content):
    ```
    > **Reference Appendix** — This guide is the rationale and edge-case reference for the branch review process. The executable entry point is the [`branch-review` skill](./../../../.claude/skills/branch-review/SKILL.md) via `make review-run`. Agents should load the skill, not this guide, unless they need rationale for a specific judgment call.
    ```
- `docs/agentic/rules/planning-review-guide.md`: same treatment with `planning-review` skill and `make plan-review`.

Proof:

- Open `CLAUDE.md` Key Triggers → no mention of guide file paths as primary instructions; skill paths and slash commands present.
- Open `branch-review-guide.md` → "Reference Appendix" block visible as the first content element.
- Manual agent cold-start check: reading CLAUDE.md, an agent sees `make review-run` → `.claude/skills/branch-review/SKILL.md` without needing to load the 250-line guide.

### Slice 5: Planning Pipeline Exit Gate

**Goal**: `make plan-review` verifies that a `plan-analyze` run with recorded findings exists for the target document before the agent proceeds. Warning by default; hard block with `PLAN_ANALYZE_REQUIRED=1`.

**Gate semantics**: `plan-analyze` is a pre-review triage step. Its outputs are recorded as review runs with `review_mode="planning"` and a session name following the convention `plan-analyze-<doc-slug>-<date>`. (Note: `"analysis"` is not a valid `review_mode` enum value; valid values are `branch`, `release_audit`, and `planning`.) The gate checks for at least one review run whose `review_mode` is `"planning"` and whose `session` starts with `plan-analyze` for the target document — it does not verify finding resolution (that is the planning-review skill's job). A full planning-review run (review_mode="planning", session prefix `plan-review-*`) satisfies its own gate separately.

Changes:

- New `scripts/check_plan_analyze.py`:
  - Accepts `--doc <path>` and `--task-ref <ref>` as arguments.
  - Queries `review_runs(review={"operation":"list", "review_mode":"planning", "subject_path":<doc>, "task_ref":<ref>})` via the `agent_handoff_mcp` Python API. Note: `review_mode="analysis"` is not a valid enum value — valid values are `branch`, `release_audit`, `planning`. `plan-analyze` records runs with `review_mode="planning"`.
  - Filters the returned runs to those whose `session` field starts with `plan-analyze`. This discriminates plan-analyze runs from full planning-review runs against the same document. Session naming convention: `plan-analyze-<doc-slug>-<date>`.
  - Exits 0 if at least one matching run is found; exits 1 on API/infrastructure errors (import failure, DB unavailable); exits 2 if the gate is not met — no matching plan-analyze run for the document.
  - Prints: "plan-analyze gate: PASS (N runs for <doc>)" or "plan-analyze gate: MISSING — run `make plan-analyze DOC=<doc>` before plan-review."
- Extend `plan-review` target in `mk/handoff.mk`:
  - After the DOC/file existence checks, run `python scripts/check_plan_analyze.py --doc $(DOC) --task-ref $(TASK)`.
  - If script exits 2 and `PLAN_ANALYZE_REQUIRED` is not set: print the gate warning and continue (print the existing plan-review info block as before).
  - If script exits 2 and `PLAN_ANALYZE_REQUIRED=1`: exit 1 before printing the plan-review info block.
  - TASK parameter defaults to the active task inferred from MCP identity if not provided (script handles the fallback).
- `docs/agentic/rules/planning-pipeline.md`:
  - Add under the Assessment → Spec and Spec → Task Plan transitions: "Before running `make plan-review`, the reviewing agent must run `make plan-analyze DOC=<path>` and ensure analysis findings are recorded in MCP. `make plan-review` checks for this and warns (or blocks with `PLAN_ANALYZE_REQUIRED=1`) when the gate is unmet."

Proof:

- `make plan-review DOC=<any plan without prior analysis run>` → prints gate warning, then proceeds to print the plan-review info block.
- `make plan-review DOC=<same plan> PLAN_ANALYZE_REQUIRED=1` → exits 1 before printing the plan-review block.
- Record a `plan-analyze` review run for the document via `review_runs(operation="record", review_mode="planning", session="plan-analyze-<slug>-<date>", subject_path=<doc>)` → `make plan-review DOC=<that doc>` → gate passes silently.
- `make plan-review DOC=<doc> TASK=E17-6` (explicit task ref) → check runs against the named task's findings.

### Slice 6: Multi-Active-Task Registry (Parallel Agent Support) — Scope Extension; Epic Authorization Required

**Goal**: Replace the singleton `handoff_state WHERE id = 1` row with a task-ref-keyed registry so that multiple agents can work concurrently in separate worktrees without evicting each other's active task.

**Problem**: The current `handoff_state` table enforces `CHECK (id = 1)` — exactly one active task at any moment. When agent B calls `switch_task` or `set_handoff_state` for a new task, agent A's task is archived out of the active slot. Agent A then sees `active: null` on its next `load_session` call and loses provenance resolution, decision recording, and pre-merge gate access. Git worktree isolation is sound; the collision is in the shared MCP state layer.

**Collision surface** — 34 `WHERE id = 1` occurrences across 10 source files:

| File | Hits | Functions |
|---|---|---|
| `handoff_state.py` | 6 | `set_handoff_state` (INSERT/UPDATE/SELECT), `get_handoff_state` (SELECT) |
| `import_export.py` | 10 | `_import_handoff_state_rows`, `archive_task_state` (DELETE), `_update_task_status_impl`, `switch_task` (SELECT/UPDATE) |
| `core.py` | 2 | `load_session`, `close_slice` |
| `shared_write_context.py` | 2 | `collect_target_context_warnings`, `_detect_git_write_context` |
| `shared_primitives.py` | 1 | `_resolve_task_ref` — **the existing centralized resolver used by 31 call sites across 7 files** |
| `decisions.py` | 3 | `_check_active_revision`, `_maybe_refresh_sha_from_active`, `update_task_status` |
| `review_findings.py` | 4 | `_check_active_revision`, `_resolve_handoff_status`, `repair_provenance` |
| `api.py` | 1 | `update_task_status` |
| `current_task_rendering.py` | 3 | `_get_handoff_dashboard_view` (2 SQL refs), `_collect_task_snapshot` |
| `dashboard_rendering.py` | 2 | `_render_cross_task_findings`, `generate_dashboard_md` |

Additionally: `verified_tests.py` (2 callers of `_resolve_task_ref`), `_shared.py` (1 re-export of `_resolve_task_ref`).

**Architectural decision**: Option A (row-level multi-tenancy) was chosen over Option B (orchestrator lane lookup) because Option B would violate `[rg-013]` — handoff-mcp must remain pure CRUD with no orchestration imports.

Changes:

- **Schema** (`shared_schema.py`): Drop `CHECK (id = 1)` singleton constraint. Re-key `handoff_state` by `task_ref TEXT PRIMARY KEY`. Multiple rows with `status = 'in_progress'` can coexist. Add `activated_at TIMESTAMP` for ordering.
- **Centralized resolver** (`shared_primitives.py`): Evolve `_resolve_task_ref(conn, task_ref)` to add cwd-based worktree matching when `task_ref` is None. Resolution order: (1) explicit `task_ref` (as-is), (2) match cwd against `target_worktree_path`, (3) if root worktree and exactly one `in_progress` row, return it, (4) raise `AmbiguousActiveTaskError`.
- **`get_handoff_state`** (`handoff_state.py`): Replace `WHERE id = 1` with `WHERE task_ref = ?` using resolved task_ref.
- **`set_handoff_state`** (`handoff_state.py`): `INSERT OR REPLACE` keyed by `task_ref`. Creating a new task no longer evicts the previous one.
- **`switch_task`** (`import_export.py`): Remove archive-on-switch. Sets `activated_at = now()` on target row.
- **`archive_task_state`** (`import_export.py`): DELETE changes from `WHERE id = 1` to `WHERE task_ref = ?`.
- **`load_session`** (`core.py`): Use `_resolve_task_ref()` for `task_ref=None` path. Add a `slices_completed` section to the response that extracts all `*_slice_complete_*` decision rows for the resolved task, returning `[{"decision_id": <id>, "decision": "<full_id>", "slice_label": "<extracted_label>", "created_at": "<timestamp>", "agent": "<agent>"}]` sorted by `created_at`. Cold-start agents see which slices are done without reading the task plan. The section is included by default in `load_session` (no opt-in needed) and is also available via `get_handoff_state(sections="slices_completed")`.
- **`generate_dashboard_md`** (`dashboard_rendering.py`): Render all `in_progress` tasks in "Active Tasks" section.
- **Orchestrator tests**: Update 2 singleton fixtures to task_ref-keyed inserts.

Test plan:

- **Unit: cwd-based resolution** — two `in_progress` rows with different `target_worktree_path`. Assert correct resolution per mocked cwd. Assert `AmbiguousActiveTaskError` from unmatched cwd.
- **Unit: concurrent active tasks** — insert two tasks, assert both `in_progress`, assert independent `get_handoff_state` access.
- **Unit: switch_task no longer archives** — `switch_task("B")`, assert task A still `in_progress`.
- **Unit: dashboard renders N active** — two in_progress tasks, both appear in dashboard.
- **Unit: optimistic concurrency preserved** — concurrent `set_handoff_state` with same revision → second fails.
- **Regression: single-task workflow** — one active task, root worktree, no explicit `task_ref` → works identically.
- **Unit: slices_completed section** — record 3 slice-complete decisions for a task → `load_session()` response includes `slices_completed` array with 3 entries, each containing `decision_id`, `decision`, `slice_label`, `created_at`, `agent`. Non-slice decisions are excluded.
- **Unit: slices_completed empty** — task with decisions but no slice-complete decisions → `slices_completed` is an empty array (not omitted).
- **Unit: slices_completed via get_handoff_state** — `get_handoff_state(sections="slices_completed")` returns the same array as `load_session`.
- **Integration: `make test-handoff`** and **`make test-orchestrator`** pass.

Proof:

- Two agents in separate worktrees can both call `load_session()` without `task_ref` and each resolves to their own task.
- `set_handoff_state(task_ref="TASK-B")` does not archive or evict TASK-A.
- Cold-start `load_session()` on a task with 3 closed slices → `slices_completed` shows all 3 with labels and timestamps.
- `make test-handoff` and `make test-orchestrator` pass with zero regressions.

### Slice 7: Test Trace Archive and Change-Outcome Linkage — Scope Extension; Epic Authorization Required

**Goal**: Store raw test output alongside the existing pass/fail ledger so that cold-start agents can inspect *why* a prior test failed — not just *that* it failed — and correlate failures with specific file changes.

**Motivation**: The Meta-Harness paper (Lee et al., arXiv:2603.28052, 2026) demonstrates that raw execution traces produce a 15-point accuracy gain over score-only or LLM-summarized feedback in harness optimization loops (50.0% vs 34.6%/34.9%). The current `verified_tests` table truncates test output to 280 characters via `_summarize_test_result()`, destroying the diagnostic detail that enables causal reasoning about regressions. AHMCP-31's `touched_files` table records *what* changed but nothing connects changes to test outcomes. This slice closes both gaps.

**Design principles** (derived from Meta-Harness findings):
- **Store raw traces, not summaries.** The ablation is decisive: summaries provide nearly zero benefit. Store full stdout/stderr.
- **Enable selective retrieval.** The trace archive will exceed any context window. Agents query by test id or file path, not bulk ingestion.
- **Support causal attribution.** Link file changes to test outcomes so agents can answer "which edits correlated with this regression?"
- **Do not auto-summarize.** No LLM compression step on storage. The agent decides what to inspect at query time.
- **Store generously, render sparingly.** Traces live in local SQLite — storage is effectively free. The context-window constraint is handled at query time via selective retrieval, not at write time via aggressive pruning. Dashboard and `CURRENT_TASK.md` rendering surfaces show only the most recent few results with 280-char summaries; the full trace archive remains available for targeted agent queries.

**Constraint**: No new MCP tool definitions. Both new query capabilities are delivered as additive optional parameters on the existing `get_verified_tests` tool. The `test_traces` table and the `traces` write-path extension on `record_event(event_kind="test_result")` are schema/write additions that don't increase tool count. Tool count stays at 22 (before Slice 8 compression).

Changes:

- **Schema** (`shared_schema.py`): New `test_traces` table:
  ```sql
  CREATE TABLE IF NOT EXISTS test_traces (
      id            INTEGER PRIMARY KEY AUTOINCREMENT,
      test_id       INTEGER NOT NULL REFERENCES verified_tests(id),
      trace_kind    TEXT NOT NULL CHECK (trace_kind IN ('stdout', 'stderr', 'combined')),
      content       TEXT NOT NULL,
      created_at    TEXT NOT NULL DEFAULT (datetime('now'))
  );
  CREATE INDEX IF NOT EXISTS idx_test_traces_test_id ON test_traces(test_id);
  ```
  Schema migration v4→v5 (or v5→v6 if Slice 6 increments). `_HANDOFF_REQUIRED_TABLES` updated with `"test_traces"`.
- **`record_test_result`** (`decisions.py`): Accept optional `traces: list[dict] | None` parameter. Each dict has `kind` (stdout/stderr/combined) and `content` (raw string). After the existing `verified_tests` INSERT, if traces are provided, INSERT each into `test_traces` with the new `test_id`. No change to `_summarize_test_result` — the 280-char summary remains in `verified_tests.result` for backward-compatible dashboard rendering; raw content lives in `test_traces`.
- **`record_event` MCP surface** (`api.py`): Extend `test_result` event schema to accept optional `traces` list. Passed through to `record_test_result`.
- **`get_verified_tests` extended** (`verified_tests.py`): Add 4 optional parameters to the existing tool:
  - `include_traces: bool = False` — when true, each returned test row includes a `traces` array with `[{"id", "trace_kind", "content", "created_at"}]` from the `test_traces` table. Default false preserves existing behavior.
  - `correlated_file: str | None = None` — when set, joins `verified_tests` with `touched_files` on `task_ref` and temporal proximity (test `verified_at` within `correlation_window_minutes` after `touched_at`). Implicitly filters to `passed=False`. Returns failure rows with additional `file_path`, `change_kind`, and `touched_at` fields from the join.
  - `correlation_window_minutes: int = 60` — temporal window for the `correlated_file` join. Default 60 minutes covers typical TDD cycles (edit → test within minutes) while excluding cross-session noise. Only used when `correlated_file` is set.
  - `exclude_never_passed: bool = True` — when `correlated_file` is set, exclude tests that have *never* passed for the same `command` + `task_ref` combination. A test that has never passed is likely a TDD red-phase stub (written before implementation exists); its failure trace is "function doesn't exist," not a regression signal. A test that *previously* passed and now fails is a regression worth surfacing. Derived at query time from existing `verified_tests` rows (`EXISTS (SELECT 1 FROM verified_tests v2 WHERE v2.command = v.command AND v2.task_ref = v.task_ref AND v2.passed = 1)`). Default true filters TDD noise; set false to include all failures.
- **Bounded retention** (`verified_tests.py`): On each `record_test_result` INSERT that includes traces, prune `test_traces` rows for the same `command` + `task_ref` combination beyond the newest N runs (default `TRACE_RETENTION_PER_COMMAND = 200`). The cap is a safeguard against unbounded DB growth from long-lived tasks with high-frequency test loops, not a context-window concern — traces are stored locally in SQLite and retrieved selectively. 50 runs per command preserves enough history for multi-session regression archaeology while preventing a single runaway test command from bloating `handoff.db`. Older traces are deleted; the `verified_tests` summary row remains.
- **Public API** (`__init__.py`): No new exports needed — `get_verified_tests` already exported.
- **MCP tool registry** (`api.py`): Update `get_verified_tests` tool description and parameter schema to document the 4 new optional parameters. No new tool registration.
- **Contract** (`docs/agentic/contracts/agent-handoff-mcp.md`): Update `get_verified_tests` tool-table row to note trace inclusion and correlated-file query modes. Add contract note documenting the temporal-proximity join semantics.

Test plan:

- **Unit: trace roundtrip** — `record_test_result(traces=[{"kind": "stdout", "content": "<raw>"}])` → `get_verified_tests(include_traces=True)` returns the raw content verbatim alongside the test row.
- **Unit: backward compat** — `record_test_result()` without `traces` → `get_verified_tests(include_traces=True)` returns empty `traces` array. `get_verified_tests()` without `include_traces` returns identical shape to pre-slice. Existing callers unaffected.
- **Unit: bounded retention** — set `TRACE_RETENTION_PER_COMMAND = 3` (test override), record 5 test results with traces for the same command → only the newest 3 have traces; oldest 2 have `verified_tests` rows but no `test_traces` rows.
- **Unit: correlated file** — record 2 file touches then 1 failing test within the temporal window → `get_verified_tests(correlated_file="src/foo.py")` returns the failure linked to the touched file. Record a passing test → not returned.
- **Unit: correlation temporal boundary** — touch a file, then record a failing test 2 hours later → not linked (outside default 60-minute window). Set `correlation_window_minutes=180` → linked.
- **Unit: exclude never-passed (TDD noise)** — record 3 failing test results for command `pytest tests/test_new.py` with no prior passing result → `get_verified_tests(correlated_file="src/foo.py")` excludes them (default `exclude_never_passed=True`). Then record 1 passing result followed by 1 failing result for the same command → the regression failure is returned. Set `exclude_never_passed=False` → all failures returned including the never-passed ones.
- **Integration: `make test-handoff`** — all existing tests pass; no regressions from schema migration.

Proof:

- `get_verified_tests(include_traces=True)` returns full stdout/stderr for a recorded test; content is not truncated to 280 chars.
- `get_verified_tests(correlated_file="src/foo.py")` returns failed test runs temporally correlated with edits to that file.
- `record_test_result` without `traces` produces identical behavior to the pre-slice implementation.
- `get_verified_tests` without new parameters produces identical response shape.
- Trace retention is bounded: only the 200 most recent trace sets per command per task are kept (configurable via `TRACE_RETENTION_PER_COMMAND`).
- MCP tool count remains at 22 — no new tool registrations (before Slice 8 compression).
- `make test-handoff` passes with zero regressions.

### Slice 8: MCP Tool Surface Compression — Scope Extension; Epic Authorization Required

**Goal**: Reduce the registered MCP tool count from 22 to 19 by merging 6 single-purpose tools into 3 compound tools using the discriminated-union pattern already established by `record_event`, `review_findings`, `review_runs`, `next_actions`, and `artifacts`. Also complete the `DASHBOARD.md` → `DASHBOARD.txt` rename in the tool naming surface (the file on disk is already `.txt`; the function and tool names still say `_md`).

**Motivation**: Every registered MCP tool consumes agent context window at session start (tool descriptions are injected into the system prompt). 22 tools with full parameter schemas is a significant context cost. Tools that operate on the same domain entity and share provenance/lifecycle semantics are natural compound candidates. The greenfield policy permits breaking tool-name changes since no external consumers exist.

**Design principle**: Compound tools use a single discriminator parameter (`operation` for read/write pairs, `target` for render variants). Each operation's parameter set is a discriminated union — same pattern as `review_findings(operation="record"|"batch_record"|"update"|"list")`. Existing Python API functions remain unchanged; only the MCP tool registration layer changes.

Changes:

- **`generate_md(target="dashboard"|"current_task")`** (`api.py`): New compound handler replacing `generate_dashboard_md` and `generate_current_task_md`.
  - `target="dashboard"`: dispatches to `dashboard_rendering.generate_dashboard_md()`. Accepts `write_file: bool = True`. Description references DASHBOARD.txt (not .md).
  - `target="current_task"`: dispatches to `current_task_rendering.generate_current_task_md()`. Accepts `task_ref`, `write_file`.
  - Tool description: "Generate markdown output files. Set target='dashboard' for DASHBOARD.txt (human-scoped observatory) or target='current_task' for CURRENT_TASK.md (machine-readable task snapshot)."
  - The underlying Python functions `generate_dashboard_md()` and `generate_current_task_md()` keep their current names internally; only the MCP tool name changes.
  - Update `close_slice` description to reference `generate_md` instead of the old names.
  - Update `CLAUDE.md` handoff protocol: `generate_dashboard_md()` → `generate_md(target="dashboard")`.

- **`handoff_transfer(operation="export"|"import")`** (`api.py`): New compound handler replacing `export_handoff_state` and `import_handoff_state`.
  - `operation="export"`: accepts `task_ref`, `output_path`, `no_markdown`. Dispatches to `export_handoff_state()`.
  - `operation="import"`: accepts `input_path`, `mode`, `set_active`, `allow_destructive_clear`. Dispatches to `import_handoff_state()`.
  - Tool description: "Export or import task handoff state snapshots. Set operation='export' for portable JSON output or operation='import' to load a snapshot into the local database."

- **`task_archive(operation="archive"|"get")`** (`api.py`): New compound handler replacing `archive_task_state` and `get_archived_task`.
  - `operation="archive"`: accepts `task_ref`, `notes`, `clear_active_if_matches`, `prune_working_rows`, `allow_destructive_clear`. Dispatches to `archive_task_state()`.
  - `operation="get"`: accepts `task_ref` (required), `include_snapshot`. Dispatches to `get_archived_task()`.
  - Tool description: "Archive completed task state or retrieve an archived task snapshot. Set operation='archive' to move task to archive storage or operation='get' to inspect a previously archived task."

- **Backward-compat aliases** (`__init__.py`): Keep `generate_dashboard_md` and `generate_current_task_md` as Python-level aliases pointing to the original implementations. The Python API is unchanged; only the MCP tool surface is compressed. Scripts, hooks, and `CLAUDE.md` references to `generate_dashboard_md()` as a Python call remain valid.

- **Hook matchers**: PostToolUse hooks in `.claude/settings.json` and `.github/hooks/terminal-guard.json` that match on `generate_dashboard_md` or `generate_current_task_md` must update to match `generate_md`. The `regenerate-task-views.sh` hook matcher list must replace the old tool names.

- **Contract update** (`docs/agentic/contracts/agent-handoff-mcp.md`): Remove 6 tool-table rows (`generate_current_task_md`, `generate_dashboard_md`, `export_handoff_state`, `import_handoff_state`, `archive_task_state`, `get_archived_task`). Add 3 compound rows (`generate_md`, `handoff_transfer`, `task_archive`). Update preamble tool-count from "22-tool" to "19-tool".

- **Orchestrator integration**: Update `packages/agent-orchestrator-mcp/` callers that import or call `generate_dashboard_md` or `generate_current_task_md` — these remain valid Python API calls (backward-compat aliases), but any MCP tool invocations via the orchestrator's MCP client must use the new names.

- **Instruction surfaces**: Update `CLAUDE.md` MCP Handoff section and `docs/agentic/instructions.md` to reference `generate_md(target="dashboard")` instead of `generate_dashboard_md()` for MCP tool calls. Python API call references keep the old names (aliases).

Test plan:

- **Unit: generate_md dispatch** — `generate_md(target="dashboard")` produces identical output to `generate_dashboard_md()`. `generate_md(target="current_task", task_ref="X")` produces identical output to `generate_current_task_md(task_ref="X")`.
- **Unit: handoff_transfer dispatch** — `handoff_transfer(operation="export", task_ref="X")` produces identical JSON to `export_handoff_state(task_ref="X")`. `handoff_transfer(operation="import", input_path=<path>)` round-trips correctly.
- **Unit: task_archive dispatch** — `task_archive(operation="archive", task_ref="X")` produces identical result to `archive_task_state(task_ref="X")`. `task_archive(operation="get", task_ref="X")` returns identical snapshot.
- **Unit: backward-compat aliases** — `from agent_handoff_mcp import generate_dashboard_md` still works and calls the correct implementation.
- **Unit: tool count** — `len(build_handoff_mcp().tools)` == 19.
- **Integration: `make test-handoff`** — all existing tests pass (they use Python API, not MCP tool names).
- **Integration: `make test-orchestrator`** — orchestrator tests pass after any MCP client call updates.

Proof:

- MCP tool count is 19 (down from 22).
- All 3 compound tools produce identical output to their predecessors.
- Python API backward-compat aliases resolve correctly.
- Hook matchers updated in both harness surfaces.
- `docs/agentic/contracts/agent-handoff-mcp.md` preamble says "19-tool" and matches actual count.
- `make test-handoff` and `make test-orchestrator` pass with zero regressions.

---

## Consolidated Checklist

### Context and Ownership

- [ ] Verify current anatomy compliance count: 8 compliant, 11 non-compliant (including 3 Phase 1 partial retrofits)
- [ ] Confirm `SKILL_ANATOMY.template.md` is the authoritative reference for required fields and sections

### Checklist for Slice 1: Skill Retrofit

- [ ] All 11 non-compliant skills have full frontmatter (name, description, mode, tdd_gate, context_budget, makefile_target, mcp_tools)
- [ ] All 11 skills have required section headers (Overview, Trigger, Core Process, Red Flags, Convergence Criteria)
- [ ] Phase 1 retrofits (commit2git, investigate, review) gain missing fields without losing existing process content
- [ ] Common Rationalizations added to complex skills (refactor, worktree-orchestrator, worktree-worker, daemon-lifecycle)
- [ ] Frontmatter YAML parses without error for all 19 skills

### Checklist for Slice 2: `make check-skills` Validator

- [ ] `scripts/check_skills.py` validates frontmatter fields, mode value, tdd_gate boolean, section headers, makefile_target wiring, mcp_tools wiring
- [ ] `make check-skills` exits 0 after Slice 1 retrofit
- [ ] `make check-skills` exits 1 on intentional anatomy violation (manual regression check)
- [ ] `check-skills` added to `make check-all` without breaking existing steps

### Checklist for Slice 3: Harness Protocol Contract + Sync Validator

- [ ] `docs/agentic/contracts/harness-protocol.yaml` defines cold-start steps, hook event matchers, Python API imports, branch isolation policy
- [ ] `scripts/check_harness_sync.py` validates both harness hook files against the protocol contract
- [ ] `.github/hooks/terminal-guard.json` updated with missing hooks (regenerate-task-views, validate-mcp-dict-params)
- [ ] `scripts/hooks/guard-format-clean.sh` runs formatters in check mode on branch-changed files; exits non-zero on unformatted code
- [ ] PreToolUse hook on `close_slice|handoff_close_check` wired in both `.claude/settings.json` and `.github/hooks/terminal-guard.json`
- [ ] `harness-protocol.yaml` includes `guard-format-clean` hook entry with tool base names `[close_slice, handoff_close_check]`
- [ ] `make check-harness-sync` exits 0; wired into `make check-all`
- [ ] `make check-harness-sync` exits 1 on intentional drift (manual regression check)
- [ ] `scripts/hooks/sync-task-plan-checkboxes.sh` auto-checks matching task plan checklist items after `close_slice`; warns on no match; exits 0 always
- [ ] PostToolUse hook on `close_slice` wired in both `.claude/settings.json` and `.github/hooks/terminal-guard.json`
- [ ] `harness-protocol.yaml` includes `sync-task-plan-checkboxes` hook entry with tool base name `[close_slice]`
- [ ] `make context` prints stale-checkbox warning when slice-complete decisions exist but checkboxes are unchecked; silent when in sync

### Checklist for Slice 4: Routing Redirect

- [ ] `CLAUDE.md` Key Triggers point to skills and slash commands, not guide file paths
- [ ] `CLAUDE.md` and `.github/copilot-instructions.md` Python API fallback sections reference `harness-protocol.yaml` as canonical source
- [ ] `instructions.md` Role Selection table references skills as primary entry points; Additional Routing section updated where needed
- [ ] `branch-review-guide.md` carries "Reference Appendix" header
- [ ] `planning-review-guide.md` carries "Reference Appendix" header

### Checklist for Slice 5: Planning Pipeline Exit Gate

- [ ] `scripts/check_plan_analyze.py` queries review_runs for plan-analyze sessions via Python API
- [ ] Exit codes: 0 (pass), 1 (infrastructure error), 2 (gate unmet)
- [ ] `make plan-review` prints warning when gate unmet; blocks with `PLAN_ANALYZE_REQUIRED=1`
- [ ] `planning-pipeline.md` documents the gate requirement

### Checklist for Slice 6: Multi-Active-Task Registry

- [ ] `handoff_state` re-keyed by `task_ref TEXT PRIMARY KEY`; `CHECK (id = 1)` constraint removed
- [ ] `_resolve_task_ref` evolved with cwd-based worktree matching and `AmbiguousActiveTaskError`
- [ ] All 34 `WHERE id = 1` occurrences updated across 10 source files
- [ ] `set_handoff_state` creates new task rows without evicting existing ones
- [ ] `switch_task` no longer archives the previous task
- [ ] `generate_dashboard_md` renders all `in_progress` tasks
- [ ] Orchestrator test fixtures updated to task_ref-keyed inserts
- [ ] `load_session` response includes `slices_completed` section listing all slice-complete decisions with labels and timestamps
- [ ] `get_handoff_state(sections="slices_completed")` returns the same slice-status array
- [ ] `slices_completed` is empty array (not omitted) when no slice-complete decisions exist
- [ ] `make test-handoff` and `make test-orchestrator` pass with zero regressions

### Checklist for Slice 7: Test Trace Archive and Change-Outcome Linkage

- [ ] `test_traces` table added to `shared_schema.py` with schema migration
- [ ] `record_test_result` extended with optional `traces` parameter; `record_event` MCP surface updated
- [ ] `get_verified_tests` extended with `include_traces`, `correlated_file`, `correlation_window_minutes`, `exclude_never_passed` optional params (no new MCP tool)
- [ ] Bounded retention: oldest traces beyond `TRACE_RETENTION_PER_COMMAND` (default 200) pruned on insert
- [ ] `docs/agentic/contracts/agent-handoff-mcp.md` `get_verified_tests` row updated with new parameter documentation
- [ ] Unit tests: trace roundtrip, backward compat (both write and read paths), bounded retention, correlated file, temporal boundary, exclude-never-passed TDD noise filter
- [ ] `make test-handoff` passes with zero regressions

### Checklist for Slice 8: MCP Tool Surface Compression

- [ ] `generate_md(target="dashboard"|"current_task")` compound tool replaces `generate_dashboard_md` + `generate_current_task_md`; dashboard target references DASHBOARD.txt
- [ ] `handoff_transfer(operation="export"|"import")` compound tool replaces `export_handoff_state` + `import_handoff_state`
- [ ] `task_archive(operation="archive"|"get")` compound tool replaces `archive_task_state` + `get_archived_task`
- [ ] `len(build_handoff_mcp().tools)` == 19
- [ ] Backward-compat Python aliases preserved in `__init__.py` (`generate_dashboard_md`, `generate_current_task_md`)
- [ ] Hook matchers updated in `.claude/settings.json` and `.github/hooks/terminal-guard.json`
- [ ] `docs/agentic/contracts/agent-handoff-mcp.md` updated: 6 rows removed, 3 compound rows added, preamble says "19-tool"
- [ ] `CLAUDE.md` and `instructions.md` references updated to `generate_md(target="dashboard")`
- [ ] `make test-handoff` and `make test-orchestrator` pass with zero regressions

## Review Readiness

- [ ] `make check-all` green after each slice
- [ ] No changes to skill execution logic or MCP handoff protocol
- [ ] No new MCP tool definitions across any slice. Slice 7 delivers new capabilities via additive optional parameters on `get_verified_tests`. Slice 8 reduces tool count from 22 to 19.

## Success Criteria

- [ ] `make check-skills` exits 0 across all 19 skills after retrofit
- [ ] All 11 non-compliant skills pass full anatomy validation (frontmatter + sections + wiring)
- [ ] `docs/agentic/contracts/harness-protocol.yaml` is the single source of truth for cold-start steps, hook matchers, Python API fallback surface, and branch isolation policy
- [ ] `make check-harness-sync` exits 0 — both harness hook files match the protocol contract with no missing or drifted hooks
- [ ] Cold-start agent reading `CLAUDE.md` is routed to named skill and slash command for every major workflow trigger
- [ ] Both review guides carry "Reference Appendix" label
- [ ] `make plan-review` warns (or blocks with opt-in) when no prior plan-analyze run exists for the target document
- [ ] `get_verified_tests(include_traces=True)` returns raw test output for any recent failure — content is not truncated to 280 chars
- [ ] `get_verified_tests(correlated_file=<path>)` correlates failed test runs with file edits via temporal proximity, enabling causal-attribution queries without manual `git log` reconstruction
- [ ] MCP tool count unchanged at 22 after Slice 7 — all capabilities delivered via additive parameters on existing tools
- [ ] MCP tool count reduced to 19 after Slice 8 — 3 compound tools replace 6 single-purpose tools
- [ ] `make test-handoff` passes after the schema change with zero regressions
- [ ] `make check-all` completes without regression (including both `check-skills` and `check-harness-sync`)
