# Development Instructions

> **Cold-start document for coding agents.** Universal rules that cannot be deduced from code, configs, or linters. Domain-specific guidelines load via the routing table below.

> **On first load / cold start**: also read [BOOTSTRAP.md](BOOTSTRAP.md) for testing commands, MCP server setup, and handoff state defaults.

**Epic**: `docs/epics/v0.2.0/remaining-sync-workbench-and-retention-epic.md` · **Roadmap**: `docs/roadmaps/roadmap-v4.md`

---

## Document Maintenance (ACE Playbook Evolution)

Rules in this file use `[sr-NNN]` / `[rg-NNN]` evidence counters (`helpful` / `harmful`). Full curation rules, reflection triggers, pruning workflow, and evidence thresholds: [playbooks/ace-pruning-playbook.md](playbooks/ace-pruning-playbook.md).

- ACE actively reads this file today for rule evidence and total line count.
- ACE does not yet auto-enforce section ownership, duplication, or a hard size budget. Treat the pruning playbook as the authoritative maintenance path until those gates exist.
- `helpful=0 harmful>=2` = pruning candidate. `helpful>=3 harmful=0` = confirmed keeper.
- New rules require a real failure reference. Delta updates only; never rewrite a section from scratch.
- Run `make ace-reflect TASK=<task-ref>` after reviews to apply pending counter updates.

---

## Architecture Routing

This file is a dispatcher, not the architecture source of truth.

- System overview: [diagrams/system-overview.mmd](diagrams/system-overview.mmd)
- Domain maps: [maps/backend.md](maps/backend.md), [maps/frontend.md](maps/frontend.md), [maps/php-plugin.md](maps/php-plugin.md), [maps/integration.md](maps/integration.md)
- Boundary contracts: [contracts/](contracts/)

## Role Selection

Choose your domain to load targeted context. Always load the matching testing guide alongside the domain guidance.

| Role                          | Context Map                                | Guidelines                                                               | Testing Guide                                              | Tech Stack (ctx7)                                                          | Key Entry Points                      |
| ----------------------------- | ------------------------------------------ | ------------------------------------------------------------------------ | ---------------------------------------------------------- | -------------------------------------------------------------------------- | ------------------------------------- |
| **Backend (Python)**          | [maps/backend.md](maps/backend.md)         | [rules/backend-python-guidelines.md](rules/backend-python-guidelines.md) | [rules/testing-python.md](rules/testing-python.md)         | [maps/tech-stack.md#backend-python](maps/tech-stack.md#backend-python)     | `apps/prototype-description-service/` |
| **Frontend (React/TS)**       | [maps/frontend.md](maps/frontend.md)       | [rules/frontend-guidelines.md](rules/frontend-guidelines.md)             | [rules/testing-typescript.md](rules/testing-typescript.md) | [maps/tech-stack.md#frontend-reactts](maps/tech-stack.md#frontend-reactts) | `apps/prototype-wp-alt-context/js/`   |
| **PHP Plugin**                | [maps/php-plugin.md](maps/php-plugin.md)   | [rules/backend-php-guidelines.md](rules/backend-php-guidelines.md)       | [rules/testing-php.md](rules/testing-php.md)               | [maps/tech-stack.md#php-plugin](maps/tech-stack.md#php-plugin)             | `apps/prototype-wp-alt-context/src/`  |
| **Cross-Service Integration** | [maps/integration.md](maps/integration.md) | [contracts/](contracts/)                                                 | [rules/testing-principles.md](rules/testing-principles.md) | [maps/tech-stack.md#orchestration](maps/tech-stack.md#orchestration)       | `docs/agentic/contracts/`             |

### Additional Routing

| Working on...                        | Load                                                                                                                                                |
| ------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| Writing tests (any language)         | [rules/testing-principles.md](rules/testing-principles.md) + language-specific guide                                                                |
| React/TypeScript tests (Vitest)      | [rules/testing-typescript.md](rules/testing-typescript.md)                                                                                          |
| Python tests (pytest)                | [rules/testing-python.md](rules/testing-python.md)                                                                                                  |
| PHP tests (PHPUnit)                  | [rules/testing-php.md](rules/testing-php.md)                                                                                                        |
| Workflow, commits, scaffolding       | [rules/development-workflow.md](rules/development-workflow.md)                                                                                      |
| Branch review                        | [rules/branch-review-guide.md](rules/branch-review-guide.md)                                                                                        |
| Planning document review             | [rules/planning-review-guide.md](rules/planning-review-guide.md)                                                                                    |
| Component architecture patterns      | [rules/component-architecture-patterns.md](rules/component-architecture-patterns.md)                                                                |
| Radix UI / accessibility primitives  | [rules/RADIX_UI_COMPONENT_GUIDE.md](rules/RADIX_UI_COMPONENT_GUIDE.md)                                                                              |
| Roster auto-resolve current behavior | [maps/php-plugin.md](maps/php-plugin.md)                                                                                                            |
| Deferred roster pending-review mode  | [../deferred-features/roster-pending-references.md](../deferred-features/roster-pending-references.md)                                              |
| Deferred embedding search roadmap    | [../deferred-features/embedding-search-optimizations.md](../deferred-features/embedding-search-optimizations.md)                                    |
| Detection vs identification boundary | [maps/integration.md](maps/integration.md)                                                                                                          |
| Face/Identity nomenclature (ADR)     | [adrs/ADR-001-face-identity-nomenclature.md](adrs/ADR-001-face-identity-nomenclature.md)                                                            |
| MCP tooling / testing commands       | [BOOTSTRAP.md](BOOTSTRAP.md)                                                                                                                        |
| Codex custom MCP attachment          | [playbooks/codex-custom-mcp-playbook.md](playbooks/codex-custom-mcp-playbook.md)                                                                    |
| Lane decomposition / orchestration   | [playbooks/worktree-codex-playbook.md](playbooks/worktree-codex-playbook.md) + [playbooks/lane-scoped-context.md](playbooks/lane-scoped-context.md) |

## Agent Startup Protocol

Use this checklist at session start, whether you are entering from a cold start, resuming a task mid-slice, or inheriting a lane from another agent.

1. Query MCP handoff state first. Load the current task objective, open blockers, latest verification, and latest decisions with `get_handoff_state(task_ref="<task>")`.
2. If you are working in a lane, load the lane inbox before editing. Use `make lane-inbox`, lane activity MCP reads, or the equivalent lane-status helper to pick up routed findings, blockers, and dispatch messages.
3. Load role routing next. Choose the domain from the Role Selection table and read the linked context map, guidelines, and testing guide before touching code.
4. Check open findings before proposing or repeating a fix. Use `list_review_findings(status="open")` so you do not re-raise known issues or miss already-assigned follow-up work.
5. Verify the contract surface before implementation. If the task touches a service, language, schema, or MCP boundary, confirm the owning contract exists in [contracts/](contracts/) and load it before writing code. If no contract exists for the boundary, follow the Cross-Boundary Change Protocol in [rules/development-workflow.md](rules/development-workflow.md) to scaffold one before proceeding.
6. Decide whether `ctx7` is needed. If the slice depends on upstream library or framework behavior, apply the `ctx7` entry criteria below before relying on memory or stale local notes.
7. Ensure the work has an MCP task, even if there is no `docs/tasks/` plan. A task plan is optional; handoff state is not. If the current change does not fit the active task, switch to or initialize an ad hoc task before editing so the slice can be logged and reviewed.

Cold start vs. mid-task re-entry:

- Cold start: if no handoff state exists yet, initialize it, then continue through the checklist in order.
- Mid-task re-entry: after loading hot state, use targeted `search_handoff` queries to recover prior slice summaries, earlier decisions, or older findings relevant to the current change. Do not replay the full task history into prompt context.

If MCP handoff is unavailable:

- Read `CURRENT_TASK.md` only as a stale human-readable fallback.
- Treat the missing MCP path as a blocker and record or report that unavailability as soon as MCP access returns.

---

## Critical Rules

These rules are **universal** and apply to every task regardless of domain.

### Plugin Boundary Rule

> **You may ONLY modify files within this monorepo.**

**Allowed paths:**

- `apps/prototype-wp-alt-context/`
- `apps/prototype-description-service/`
- `packages/`
- `docs/`
- `scripts/`

**Never modify:**

- WordPress core files (`wp-config.php`, `.htaccess`, etc.)
- LocalWP configuration
- Files in `~/Local Sites/` or any WordPress installation directory
- System configuration files

If a task seems to require external changes, STOP and propose an alternative within plugin boundaries.

### Greenfield Policy

> [!IMPORTANT]
> This is a **greenfield project** with NO production users and NO existing data that must be preserved.

- **No Data Migrations**: Storage surfaces (database tables, options, caches) are disposable.
- **Baseline Only**: Schema changes directly in the baseline migration file (`apps/prototype-description-service/db/migrations/versions/001_identity_schema.py`).
- **Clean Rewrites > backward-compatibility shims. Delete-over-flag.**

### Short Rules

<!-- ACE playbook: each rule is a strategy bullet with evidence counters.
     helpful = times this rule prevented a real failure
     harmful = times this rule caused unnecessary friction or was wrong
     Rules with helpful=0 harmful>=2 are pruning candidates.
     Worker daemon auto-detects rule references in findings and logs them to
     .task-state/ace_reflect_log.jsonl. Run 'make ace-reflect TASK=<ref>' to apply. -->

- [sr-001] helpful=2 harmful=0 :: Do not relax compliance/lint scripts to silence violations. Fix the offending code.
- [sr-002] helpful=1 harmful=0 :: Every `composer`/`npm` gate script must succeed on invocation, not just be defined.
- [sr-003] helpful=1 harmful=0 :: **npm** for Node.js (not pnpm). **Composer** for PHP.
- [sr-004] helpful=2 harmful=0 :: When editing CSS/SCSS, use existing design tokens (`--acx-*` custom properties) for colors, typography, elevation, radius, and font-weight instead of raw literals. If a needed token does not exist, add it to the shared token surface first. Specifically: `--acx-color-*` or `--acx-gray-*` for colors (no hex literals); `--acx-text-*` for font sizes; `--acx-shadow-*` for box-shadows; `--acx-radius-*` for border-radius; `--acx-font-weight-*` for font weights. Status indicators must pair color with an icon; do not rely on color alone.
- [sr-005] helpful=2 harmful=0 :: In TypeScript, use assertion helpers (`asserts value is ...`) for internal invariants and unreachable branches instead of `console.assert` or non-null assertions on API data. Do not use assertion helpers for request/input validation; validate boundary data explicitly.
- [sr-006] helpful=1 harmful=0 :: In Python, use `assert` only for narrow internal invariants during development and tests. Do not use `assert` for request validation, external data checks, or behavior that must always execute in production; raise explicit exceptions or HTTP errors instead.
- [sr-007] helpful=2 harmful=0 :: Centralize domain status values as enums or `as const` objects (TypeScript), PHP backed enums, or Python `StrEnum`/`IntEnum`. Do not scatter magic string comparisons (`=== 'completed'`, `=== 'clustering'`) across files; import from a single canonical definition and use exhaustive switches where applicable.
- [sr-008] helpful=1 harmful=0 :: When a hook, function, or constructor takes more than 8 destructured parameters, group them into 2-3 cohesive typed objects (e.g., state, actions, mutations). This prevents the "parameter slippery slope" that compounds with each new feature.
- [sr-009] helpful=1 harmful=0 :: PHP controller methods that run transactions must use a shared `run_transactional(callable)` wrapper instead of inlining START TRANSACTION / COMMIT / ROLLBACK boilerplate.
- [sr-010] helpful=1 harmful=0 :: For a full local-only development reset of both databases, use `make reset-local WP_PATH="<wordpress>/app/public" CONFIRM_LOCAL_RESET="RESET"` from the repo root. `WP_PATH` must point to the WordPress directory containing `wp-load.php` (for LocalWP here, typically `/Users/daniel/Development/wp-context-alt-text/app/public`). Never use this against non-local environments.

### Cross-Branch Regression Guards

<!-- ACE playbook: regression guards from real failures in this project.
     helpful = times this guard caught a regression before merge
     harmful = times this guard caused unnecessary friction or false positive
     Rules with helpful=0 harmful>=2 are pruning candidates. -->

- [rg-001] helpful=1 harmful=0 :: **No type-shim masking.** New import? Update `package.json`/`composer.json` and verify with a real build.
- [rg-002] helpful=1 harmful=0 :: **Preserve atomic write paths.** Do not split a backend atomic operation into multiple frontend mutations.
- [rg-003] helpful=1 harmful=0 :: **Primary controls reachable from zero state.** Never gate primary actions behind non-zero selection.
- [rg-004] helpful=1 harmful=0 :: **Role semantics match behavior.** Controlled dialogs must wire `onOpenChange`.
- [rg-005] helpful=1 harmful=0 :: **Schema/contract parity.** Validate SQL column names against real schema before merge.
- [rg-006] helpful=1 harmful=0 :: **Documented commands must run as written.** Broken copy-paste syntax is a bug.
- [rg-007] helpful=1 harmful=0 :: **Long-running loops: bounded stall detection.** Daemon/loop code that processes multiple independent units must track per-unit no-progress cycles and exit non-zero after a bounded threshold. A single unit's failure must not halt processing of other units in the same cycle.
- [rg-008] helpful=1 harmful=0 :: **Config files: validate at load time.** JSON/YAML config consumed by multiple modules must be structurally validated at load time. Fail fast on missing or malformed required keys instead of silently returning empty defaults.
- [rg-009] helpful=1 harmful=0 :: **No task-specific logic in generic modules.** If a generic utility contains `if task_ref == "some-task"` or hardcoded domain strings for a specific task, extract that logic to a config-driven policy module or the task's manifest. It becomes dead code once the task is done.
- [rg-010] helpful=1 harmful=0 :: **IDE tool output may be stale after external writes.** Editor-integrated `read_file` and `grep_search` tools read from the IDE's in-memory file model, not from disk. After git operations (rebase, cherry-pick, merge, worktree intake) or edits by other agents/terminals, the model can lag behind the filesystem. When a review finding seems surprising, cross-check with a terminal command (`grep -n`, `wc -l`, `sed -n`) before recording it. This caused an entire review cycle of false positives against `scripts/mcp/orchestrator_daemon.py` (IDE showed ~700 lines, disk had 850).
- [rg-013] helpful=1 harmful=0 :: **`agent_handoff_mcp/core.py` must remain pure handoff-state CRUD.** No orchestration imports, no subprocess calls, no lock management. Scope: `packages/agent-handoff-mcp/`. Enforce during code review.
- [rg-014] helpful=1 harmful=0 :: **`agent_orchestrator_mcp` modules must use late-binding imports** (function-level) for `agent_handoff_mcp` symbols to preserve the clean split seam and avoid load-time coupling. Scope: `packages/agent-orchestrator-mcp/`.
- [rg-015] helpful=1 harmful=0 :: **Boundary adapters must not invent contract metadata.** When a controller/client/adapter wraps or normalizes remote payloads, every envelope field (`limit`, `offset`, `total`, `data_source`, status/projection metadata) must come from the request, the upstream payload, or an explicitly documented fallback. Never fabricate pagination or provenance metadata from convenience guesses like `count(payload)` unless the contract explicitly defines that derivation. If the upstream shape violates the expected contract, return an explicit error instead of silently supporting both shapes.
- [rg-016] helpful=0 harmful=0 :: **PHP runtime autoload parity must match tests.** New runtime classes added under `apps/prototype-wp-alt-context/src/` with WordPress-style filenames (`class-*.php`, `interface-*.php`) are not PSR-4 autoloadable via Composer by default. When a new class is introduced in this naming scheme, either add the explicit `require_once` from the owning runtime entrypoint or use a PSR-4-compliant filename, and verify with a real runtime-style check such as `php -r "require 'vendor/autoload.php'; var_export(class_exists('AltContext\\\\Foo\\\\Bar'));"`

### Tool Selection Discipline

> **Enforcement layer**: `.github/copilot-instructions.md` contains the mandatory decision tree and is auto-injected into every VS Code Copilot session. `.github/hooks/terminal-guard.py` intercepts `run_in_terminal` calls at the PreToolUse hook and asks for confirmation when a native tool equivalent exists.

Agents in this project run in two environments with different tool surfaces. Using the wrong tool for the environment wastes tokens and causes retries. This section exists because repeated terminal-output bloat (16 KB+ of stale scrollback per command) caused entire review sessions to choke on scope discovery that native tools could have resolved in one call.

**VS Code agents** (GitHub Copilot, Copilot Chat, VS Code extensions) have native tools that bypass the terminal entirely:

| Task                            | Use this                                              | Not this                            |
| ------------------------------- | ----------------------------------------------------- | ----------------------------------- |
| List changed files / read diffs | `get_changed_files` (VS Code SCM)                     | `git diff` in terminal              |
| Read file contents              | `read_file`                                           | `cat` / `sed -n` in terminal        |
| Search code                     | `grep_search` / `semantic_search` / `search_subagent` | `grep -rn` in terminal              |
| Lint / type errors              | `get_errors`                                          | `npm run lint` / `mypy` in terminal |
| Multi-file exploration          | `Explore` subagent                                    | Sequential terminal commands        |

Reserve terminal for operations with no native-tool equivalent: test execution, `make` targets, `pyenv` commands, `git commit`/`push`/`rebase`.

**Codex agents** (OpenAI Codex harness, `codex exec`, `codex-subagent-bridge`) run in sandboxed Linux containers with terminal + filesystem + MCP only. They do not have VS Code extension tools. Terminal equivalents and output discipline for Codex: [playbooks/codex-custom-mcp-playbook.md](playbooks/codex-custom-mcp-playbook.md#tool-discipline).

**Terminal output discipline** (both environments, when terminal is required):

- Always pipe through `tail -n 30`, `head -n 50`, or `grep -E '<pattern>'` for commands that may produce unbounded output.
- **Test runs (MANDATORY pattern):** Always use `tee` to capture output to a deterministic `/tmp/` path, then read the file with `read_file`. This avoids stale-scrollback pollution entirely. Do NOT rely on terminal output alone for test results.
  - Python: `cd <app-dir> && pyenv exec python -m pytest <path> -q 2>&1 | tee /tmp/pytest_<suite>.txt`
  - Vitest: `cd <app-dir> && npx vitest run <path> 2>&1 | tee /tmp/vitest_<suite>.txt`
  - PHP: `cd <app-dir> && vendor/bin/phpunit <path> 2>&1 | tee /tmp/phpunit_<suite>.txt`
  - Then immediately: `read_file("/tmp/pytest_<suite>.txt")` to get clean output. Never `cat` the file in terminal.
  - If initial terminal output looks truncated or polluted, skip re-running; just `read_file` the `/tmp/` capture.
- If output exceeds expectations, redirect to `/tmp/<descriptive-name>.txt` and read with `read_file` (VS Code) or `sed -n` (Codex); do not re-run the command.
- Long-lived terminal sessions accumulate scrollback. A new `run_in_terminal` call in a polluted session can return 16 KB+ of stale output from prior commands. Prefer short, filtered commands over long pipelines.
- **Background terminals lack pyenv virtualenv activation.** Only use the foreground terminal (or a terminal where `pyenv activate` has been run) for Python test commands. If the foreground session has stale scrollback, the `tee /tmp/` pattern above solves it without needing a new terminal.

### Task Document Rules

- Consolidate all checklists at the **bottom** of task documents. No scattered `- [ ]` items. No time estimates.
- Planning docs must stay internally consistent (current state vs checklist vs success criteria vs ADR terms).
- When reviewing task plans, epics, roadmaps, ADRs, or other planning documents for gaps, bugs, obsolete assumptions, or unnecessary complexity, record every finding in MCP handoff before presenting it in chat.
- Do not log branch-review or plan-review findings, `finding_id`s, or fix-status notes into task plans. MCP handoff is the canonical store for review results, and `CURRENT_TASK.md` is the generated human-readable mirror when review state needs to be surfaced.
- Reference code locations by **function/target name**, not line numbers. Line numbers go stale; names survive refactors.
- Every pseudocode function or CLI command in a plan must map to an existing API/import or be explicitly marked as "new, to be created." Unresolved pseudocode references cause implementation ambiguity.
- Validate enum values, status strings, and filter parameters used in plans against the actual API or schema. Using a status value that the API rejects (e.g., `done` when valid values are `planned/active/blocked/review/merged/closed`) is a plan bug.
- Do not list a file in "Functions to Change" unless it actually requires modification. If a file only needs verification (no code changes), mark it as verification-only.
- For MCP write tools, the live tool schema is authoritative over examples, templates, or prior-session memory. Prefer the minimal valid payload for common writes instead of copying rich historical examples with optional fields.
- If an MCP write fails validation because a documented example or template drifted from the live signature, retry once with the minimal live-valid payload and update the stale guidance surface in the same slice.

### Naming Convention: acx\_\* / ACX\_\* Prefix

| Surface                        | Prefix        | Example                          |
| ------------------------------ | ------------- | -------------------------------- |
| WordPress options/meta         | `acx_*`       | `acx_persons`, `acx_version`     |
| PHP constants (plugin-defined) | `ACX_*`       | `ACX_PLUGIN_FILE`, `ACX_VERSION` |
| PHP constants (deployment)     | `ACX_*`       | `ACX_RECOGNITION_URL`            |
| REST API namespace             | `acx/v1/`     |                                  |
| PHP namespace                  | `AltContext\` |                                  |
| Text domain / slug             | `alt-context` |                                  |
| Filter hooks                   | `acx_*`       | `acx_recognition_base_url`       |

> [!WARNING]
> The `cat_*` and `alt_context_*` prefixes are **legacy**. If encountered in code or documentation, update them to `acx_*`.

### Epic, Task, and Decision Naming

New epics, task plans, and handoff decisions follow the compact reference scheme defined in [development-workflow.md](rules/development-workflow.md#epic-task-and-decision-naming):

- Epic titles: `E<number>. <Title>`
- Task plan titles: `<EpicShortID>-<N>. <Title>` (e.g., `E12-1. Naming Spec`)
- Slice-complete decisions: `<author_tag>_slice_complete_<work_ref>_<slug>` (e.g., `cdx_slice_complete_E12-1_gate_validation`)

When creating or reviewing planning artifacts, load the correct template or review guide per the [context routing table](rules/development-workflow.md#context-routing-for-reviews).

### MCP Handoff Contract (MANDATORY)

You are one of multiple concurrent agents. MCP handoff tools are required for task state coordination.

- Every code change must be logged to MCP handoff with a decision entry before review or completion. The decision must summarize what changed and how it was verified so handoff remains the canonical review trail.

## Selective Handoff Loading

Treat handoff state as a tiered memory system. Load only what is needed for the current slice.

- Hot state: always load at startup. This includes the current objective, open findings, open blockers, latest verification, and latest 3 decisions.
- `CURRENT_TASK.md` must expose the latest decision separately from the recent-decisions list so a resuming agent can see the last handoff at a glance.
- Warm state: load on demand when the current slice needs it. This includes recent worker reports, recent lane activity, active artifacts tied to the current slice, and nearby plan-cursor history.
- Cold state: retrieve only through targeted search. This includes archived findings, superseded plan cursors, verbose logs, and large artifacts.

`task_ref` granularity:

- Default to one `task_ref` per reviewable feature or task-plan implementation stream, not one per commit and not one for an entire multi-feature epic.
- Use an epic-level `task_ref` for planning, decomposition, and cross-task coordination only. When implementation starts for a distinct task plan or feature stream, switch into that implementation task.
- Stay on the same `task_ref` while the objective, acceptance criteria, and review packet are still obviously "the same work."
- Switch `task_ref` when the active objective changes, when a separate review packet would be required, or when leaving the current task active would make `CURRENT_TASK.md` show the wrong latest decision for the work you are doing.
- Do not create a new `task_ref` for every micro-slice inside the same task plan. Record multiple `slice_complete_*` decisions under the same implementation task until that task is actually done.

Loading rules:

- Do not replay full handoff history into prompt context. Use `search_handoff` or targeted artifact lookup for older records.
- After recording a decision, finding, blocker, or test result, do not immediately re-read the full task state just to confirm it. Trust the write confirmation unless a later step needs fresh state.
- When resuming a task, start with hot state, then expand to warm or cold state only if the active slice cannot be completed from the smaller working set.

Canonical handoff runtime:

- Use `agent-handoff-mcp` exclusively for handoff state.
- Do not use handoff tools or CLI subcommands from `scripts/mcp/unified_server.py`; they are deprecated and fail by design.
- The legacy unified server is now repo-intel-only.

Primary binary shape:

- `agent-handoff-mcp --workspace-root <repo> serve-stdio`
- `agent-handoff-mcp --workspace-root <repo> doctor`
- `agent-handoff-mcp --workspace-root <repo> state`
- `agent-handoff-mcp --workspace-root <repo> task <task_ref>`
- `agent-handoff-mcp --workspace-root <repo> switch <task_ref>`

## ctx7 Entry Criteria

Use `ctx7` for current upstream documentation when implementation depends on library or framework behavior that may have drifted since the repo docs were written.

Use `ctx7` when:

- modifying code that depends on an upstream framework or library API such as FastAPI, SQLAlchemy, Radix UI, WordPress hooks, React, or MCP SDK behavior
- verifying version-specific behavior, migration guidance, or deprecation details that are not stable enough to trust from memory
- confirming the current supported API surface for a dependency named in [maps/tech-stack.md](maps/tech-stack.md)

Do not use `ctx7` for:

- repo-local rules, contracts, task plans, handoff state, or architecture decisions
- facts already owned by repo documents such as [instructions.md](instructions.md), [contracts/](contracts/), or [maps/tech-stack.md](maps/tech-stack.md)
- broad context assignment when a targeted local document answers the question

Fallback and caching:

- If `ctx7` is unavailable, use [maps/tech-stack.md](maps/tech-stack.md) as the static version manifest and note the `ctx7` gap in handoff when it materially affects confidence.
- Before issuing a new `ctx7` lookup for a dependency, search recent handoff decisions for the package name, resolved library id, or prior query so you can reuse an existing answer when it is still relevant.
- When a `ctx7` lookup materially changes an implementation decision, record the resolved library id and the query in the handoff decision so later agents do not spend tokens rediscovering the same upstream detail.
- Use this cache format inside the decision rationale when relevant:
  - `ctx7 library id: /org/project[/version]`
  - `ctx7 query: <targeted question>`
  - `ctx7 impact: <what changed in implementation or review scope>`
- Do not bulk-copy upstream docs into repo documents just because a `ctx7` lookup was used. Cache the pointer and the decision impact, not a prose dump of the source.

## Periodic Health Reviews

Full during-work and end-of-slice checklists, healthy/unhealthy pattern definitions, and memory health review: [playbooks/ace-pruning-playbook.md](playbooks/ace-pruning-playbook.md).

Key gates (always active, every slice):

1. Every slice that changes files must end with a structured `slice_complete_*` decision. Format: [templates/slice-complete-template.md](templates/slice-complete-template.md). The format is enforced at write time.
2. After recording, call `generate_current_task_md(task_ref=<active-task-ref>)`. Always pass the currently active task's ref.
3. Do not leave `CURRENT_TASK.md` pointing at a stale slice. If the latest decision does not describe the files changed this turn, record the missing decision before handoff.
4. Update singleton state via `set_handoff_state(..., expected_revision=<current>, actor={ ... })`.
5. Include a one-line status marker in the response: `Handoff updated: yes`.

Write-tool targeting rule:

- Most write tools accept optional `task_ref`. When omitted, they target the active task.
- In concurrent, cross-task, or review-audit workflows, pass `task_ref` explicitly on writes.
- `record_decision`, `record_test_result`, `report_blocker`, and `update_next_actions` all support explicit `task_ref`.
- To switch tasks, use `switch_task(task_ref)`. For in-place updates to the current task, use `set_handoff_state(...)`.

During-work discipline (abbreviated):

- Record blockers immediately: `report_blocker(..., actor={ ... })`.
- Record verification: `record_test_result(..., actor={ ... })`. Keep `result` as a concise proof line.
- Record findings: `record_review_finding(..., details={ line_start?, line_end?, fix? }, actor={ ... })`. When logging **3 or more findings** in a single review pass, use `batch_record_review_findings` instead — one atomic write, one `CURRENT_TASK.md` flush, per-item results returned.
- Validate review state with `get_review_findings_summary(...)` and `list_review_findings(...)`, not direct `sqlite3`.

Read discipline:

- Do not query `.task-state/handoff.db` directly when MCP tools are available.
- Use `get_handoff_state` for active-task snapshot, `get_review_findings_summary` (on `agent-orchestrator-mcp`) for counts, and `list_review_findings` for detailed review verification.
- `list_review_findings(finding_id=...)` accepts either `finding_id` (human-readable string like `"H-OCI-28"`) for a single-finding lookup. Prefer `finding_id` when referencing findings from review output.
- `list_review_findings` and `get_review_findings_summary` accept an optional `task_ref` to query findings on a non-active task. Use this instead of switching active state when verifying findings across multiple tasks.
- Do **not** use legacy `scripts/mcp/unified_server.py` handoff tools or CLI subcommands. The only supported handoff surface is the packaged `agent-handoff-mcp` binary described in [contracts/agent-handoff-mcp.md](contracts/agent-handoff-mcp.md).

State integrity invariants:

- Treat import/restore payloads as untrusted input. Validate payload shape and required object types before writes; malformed payloads must return `ok: false` (never silent success/no-op).
- Preserve write provenance on mutable records (for example review findings): creation metadata (`agent`, `branch`, `commit_sha`) is immutable once set; status updates may fill missing fields but must not overwrite recorded provenance.

Failure policy:

- If MCP handoff tools are unavailable, stop normal implementation work.
- Record/report the blocker, and include: `Handoff updated: no (tool unavailable)`.

- Use `templates/CURRENT_TASK.template.md` only as fallback when MCP handoff is unavailable.

Completion gate:

- A task response is incomplete if MCP handoff was not updated.

### Multi-Agent Worktree Orchestration (MANDATORY for delegated implementation)

Use this pattern when a user explicitly asks for parallel agents/worktrees, or when the task naturally splits into independent backend/frontend/PHP lanes with clear contracts.

For all operational commands, recipes, decomposition rules, domain guardrails, worker communication, merge procedures, and automated orchestration via Codex subagents, see:

- [playbooks/worktree-codex-playbook.md](playbooks/worktree-codex-playbook.md) -- decomposition rules, domain guardrails, worker recipes, merge procedures
- [playbooks/lane-scoped-context.md](playbooks/lane-scoped-context.md) -- lane-scoped context construction and prompt budgets

Summary: orchestrator stays on root branch; workers own `codex/*` branches with bounded path scope; lane manifest lives in `config/lane-orchestration/<task-ref>.json`; use `make lane-refresh` to propagate orchestrator changes; dirty worktrees are not valid handoff artifacts.

### Branch Review Trigger (MANDATORY)

When a user request matches any of these patterns, **load and follow** [rules/branch-review-guide.md](rules/branch-review-guide.md) before starting the review:

- "review" + ("implementation" | "code" | "changes" | "branch" | "PR" | "diff")
- "audit" + ("branch" | "code")
- "propose improvements" | "flag gaps" | "flag bugs"
- Any request to evaluate uncommitted or branch-scoped changes for quality

**Procedure:**

1. Read `rules/branch-review-guide.md` (process + checklist + report template).
2. Read the relevant stack guide(s) based on files in the diff.
3. Walk the common checklist + stack-specific checklist, citing files and lines.
4. Classify each finding using the defined categories (ANTIPATTERN / DEAD_CODE / COMPLEXITY / GAP) and severities (HIGH / MEDIUM / LOW).
5. Record findings in MCP handoff. Use `record_review_finding(...)` for 1–2 findings; use `batch_record_review_findings(findings=[...], actor={ ... }, task_ref=...)` for 3 or more (atomic write, single `CURRENT_TASK.md` flush, per-item results).
6. Produce the markdown report using the template.
7. Call `record_decision(..., actor={ ... })` summarizing the review + `generate_current_task_md(...)`.

**Do NOT** perform ad-hoc reviews. The guide exists to ensure consistent, structured, cross-agent-visible output.

### Planning Document Review Rule (MANDATORY)

When a user asks to review a task plan, epic, roadmap, ADR, or other planning document:

1. Review the document against the current codebase and adjacent planning docs.
2. Record each finding in MCP handoff before presenting it.
3. Focus findings on obsolete assumptions, implementation gaps, contradictory scope, contract mismatches, rollout/test gaps, and unnecessary complexity.
4. Treat the recorded handoff finding as the canonical review artifact even if no separate report file is requested.

Branch review guidance is code-change specific. Planning-document reviews still require handoff recording, but should use planning-specific judgment rather than forcing the branch-diff checklist onto docs.

### Planning Review Trigger (MANDATORY)

When a user request matches any of these patterns, **load and follow** [rules/planning-review-guide.md](rules/planning-review-guide.md) before starting the review:

- "review" + ("task plan" | "epic" | "roadmap" | "ADR" | "planning document")
- "flag issues" | "flag gaps" | "flag obsolete assumptions" on a doc under `docs/`
- "audit" + ("plan" | "epic" | "roadmap")
- Any request to evaluate implementation realism, dependencies, or checklist consistency in planning docs

Procedure:

1. Read `rules/planning-review-guide.md`.
2. Review the document against the current codebase and adjacent planning/contracts.
3. Record each finding in MCP handoff before presenting it.
4. Cite both the planning-doc lines and the current code/contract lines that justify the finding.
5. If asked to patch the document, resolve the recorded findings and then update their status.

Do not use the branch review guide as a substitute for planning reviews.

---

## Core Engineering Principles

Brief summaries of mandatory principles. Full details with code examples are in the linked domain guides.

### 1. Test-Driven Development

**Red -> Green -> Refactor** for every meaningful change. Do NOT write tests just to verify you wrote the code you wrote. Full details: [rules/testing-principles.md](rules/testing-principles.md) + your language-specific guide ([TypeScript](rules/testing-typescript.md), [Python](rules/testing-python.md), [PHP](rules/testing-php.md))

### 2. Scaffolding First (MANDATORY)

Before writing any implementation or tests, scaffold all interfaces and contracts. Full details: [rules/development-workflow.md](rules/development-workflow.md#scaffolding-first-mandatory)

### 3. User Consent for Remote Operations

Never call remote recognition services or sync operations without explicit user action. Provide immediate feedback on success/failure.

### 4. No Fabricated Data

Never fabricate benchmark numbers, latency claims, or metrics. If data is unavailable, return an explicit empty state or error.

### 5. No False Claims of Bug Fixes

Never claim a bug is fixed without verifying in production/staging logs. A unit test passing does NOT prove a bug is fixed in production.

### 6. Curation-First Precedence

User curation decisions are ground truth. Never use time-based heuristics to override them. The correct gate is always a **data delta**: did the underlying evidence change since the user's decision? If yes, surface as a new proposal. If no, respect the decision indefinitely.

### 7. User-Recoverable Remote Flows

Remote-dependent UI states must remain recoverable when automation fails or stalls.

- Stale/offline states MUST expose at least one explicit user-triggered recovery action (for example, `Sync now`).
- Auto-retry logic (visibility/focus/interval) MUST be bounded per stale cycle and must re-arm only on explicit state transitions.
- Interactive recognition API calls MUST use explicit timeout budgets via a shared timeout helper; do not leave outlier calls unbounded.

---

## Documentation Conventions

> Templates and file organization are discoverable from `docs/agentic/templates/`. Formatting rules are in linter configs (`tsconfig`, `phpcs.xml`, `pyproject.toml`, `prettier`).

- **`.mmd` files: raw Mermaid syntax only -- NO code fences**
- `.md` files: use fenced code blocks
- Maximum 12 classes per diagram
- Use language-agnostic types: `string`, `int`, `bool`, `array<T>`
- **ASCII only** in documentation. No emoji.
- **Internationalization**: all user-facing strings through `__()`, `_x()`, `_n()` with text domain `alt-context`.
