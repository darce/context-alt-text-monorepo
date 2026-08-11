# Development Instructions

> **Cold-start document for coding agents.** Universal rules that cannot be deduced from code, configs, or linters. Domain-specific guidelines load via the routing table below.
> **On first load / cold start**: also read [BOOTSTRAP.md](BOOTSTRAP.md) for testing commands, MCP server setup, and handoff state defaults.

**Active epics**: [../epics/v0.4.0/public-demo-launch-readiness-epic.md](../epics/v0.4.0/public-demo-launch-readiness-epic.md) (E15) · [../epics/v0.3.1/self-hosting-epic.md](../epics/v0.3.1/self-hosting-epic.md) (E14)

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

| Role                            | Context Map                                                                  | Guidelines                                                               | Testing Guide                                              | Tech Stack                                                          | Key Entry Points                      |
| ------------------------------- | ---------------------------------------------------------------------------- | ------------------------------------------------------------------------ | ---------------------------------------------------------- | -------------------------------------------------------------------------- | ------------------------------------- |
| **Backend (Python)**            | [maps/backend.md](maps/backend.md)                                           | [rules/backend-python-guidelines.md](rules/backend-python-guidelines.md) | [rules/testing-python.md](rules/testing-python.md)         | [maps/tech-stack.md#backend-python](maps/tech-stack.md#backend-python)     | `apps/prototype-description-service/` |
| **Frontend (React/TS)**         | [maps/frontend.md](maps/frontend.md)                                         | [rules/frontend-guidelines.md](rules/frontend-guidelines.md)             | [rules/testing-typescript.md](rules/testing-typescript.md) | [maps/tech-stack.md#frontend-reactts](maps/tech-stack.md#frontend-reactts) | `apps/prototype-wp-alt-context/js/`   |
| **PHP Plugin**                  | [maps/php-plugin.md](maps/php-plugin.md)                                     | [rules/backend-php-guidelines.md](rules/backend-php-guidelines.md)       | [rules/testing-php.md](rules/testing-php.md)               | [maps/tech-stack.md#php-plugin](maps/tech-stack.md#php-plugin)             | `apps/prototype-wp-alt-context/src/`  |
| **Cross-Service Integration**   | [maps/integration.md](maps/integration.md)                                   | [contracts/](contracts/)                                                 | [rules/testing-principles.md](rules/testing-principles.md) | [maps/tech-stack.md#orchestration](maps/tech-stack.md#orchestration)       | `docs/workbay/contracts/`             |
| **Infrastructure / Deployment** | [../epics/v0.3.1/self-hosting-epic.md](../epics/v0.3.1/self-hosting-epic.md) | [rules/development-workflow.md](rules/development-workflow.md)           | [rules/testing-principles.md](rules/testing-principles.md) | [maps/tech-stack.md#orchestration](maps/tech-stack.md#orchestration)       | `../../infra/oci/`                    |

### Additional Routing

| Working on...                          | Load                                                                                                                                                |
| -------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Full lifecycle navigation**          | [lifecycle-map.md](lifecycle-map.md) — stage map with Makefile targets, skills, MCP tools, exit gates (P1–I7)                                       |
| Writing tests (any language)           | [rules/testing-principles.md](rules/testing-principles.md) + language-specific guide                                                                |
| React/TypeScript tests (Vitest)        | [rules/testing-typescript.md](rules/testing-typescript.md)                                                                                          |
| Python tests (pytest)                  | [rules/testing-python.md](rules/testing-python.md)                                                                                                  |
| PHP tests (PHPUnit)                    | [rules/testing-php.md](rules/testing-php.md)                                                                                                        |
| Workflow, commits, scaffolding         | [rules/development-workflow.md](rules/development-workflow.md)                                                                                      |
| Epic/task lifecycle, planning pipeline | [rules/development-workflow.md](rules/development-workflow.md) + [rules/planning-pipeline.md](rules/planning-pipeline.md)                           |
| Branch lifecycle / task teardown       | [../../.claude/skills/branch-lifecycle/SKILL.md](../../.claude/skills/branch-lifecycle/SKILL.md) + `make task-start TASK=<task-ref> OBJECTIVE="..."` / `make task-finish TASK=<task-ref>` |
| Session handoff / task switching       | [../../.claude/skills/handoff-lifecycle/SKILL.md](../../.claude/skills/handoff-lifecycle/SKILL.md) + `make context` / `load_session` / `switch_task` |
| New feature / epic intake              | [../../.claude/skills/scope/SKILL.md](../../.claude/skills/scope/SKILL.md)                                                                         |
| Starting an implementation slice       | [../../.claude/skills/tdd/SKILL.md](../../.claude/skills/tdd/SKILL.md) + `make slice-start TASK=<task-ref> TEST_CMD="<command>"`                   |
| Decomposing feature work into slices   | [../../.claude/skills/incremental-implementation/SKILL.md](../../.claude/skills/incremental-implementation/SKILL.md) + `make slice-commit TASK=<task-ref> MSG="..."` |
| Branch review                          | [../../.claude/skills/branch-review/SKILL.md](../../.claude/skills/branch-review/SKILL.md) + `make review-run` for lane/local working-tree review; use direct `main...HEAD` diff scope for committed feature-branch audit |
| Planning document review               | [../../.claude/skills/planning-review/SKILL.md](../../.claude/skills/planning-review/SKILL.md) + `make plan-review DOC=<path>`                    |
| Planning document analysis             | [../../.claude/skills/plan-analyze/SKILL.md](../../.claude/skills/plan-analyze/SKILL.md) + `make plan-analyze DOC=<path>`                         |
| Anchoring a review to a decision ID    | [rules/development-workflow.md § Decision-ID Review Anchoring](rules/development-workflow.md#decision-id-review-anchoring)                          |
| Component architecture patterns        | [rules/component-architecture-patterns.md](rules/component-architecture-patterns.md)                                                                |
| Radix UI / accessibility primitives    | [rules/RADIX_UI_COMPONENT_GUIDE.md](rules/RADIX_UI_COMPONENT_GUIDE.md)                                                                              |
| Roster auto-resolve current behavior   | [maps/php-plugin.md](maps/php-plugin.md)                                                                                                            |
| Deferred roster pending-review mode    | [../deferred-features/roster-pending-references.md](../deferred-features/roster-pending-references.md)                                              |
| Deferred embedding search roadmap      | [../deferred-features/embedding-search-optimizations.md](../deferred-features/embedding-search-optimizations.md)                                    |
| Detection vs identification boundary   | [maps/integration.md](maps/integration.md)                                                                                                          |
| Face/Identity nomenclature (ADR)       | [adrs/ADR-001-face-identity-nomenclature.md](adrs/ADR-001-face-identity-nomenclature.md)                                                            |
| MCP tooling / testing commands         | [BOOTSTRAP.md](BOOTSTRAP.md)                                                                                                                        |
| MCP server loading at session start    | [rules/mcp-loading-protocol.md](rules/mcp-loading-protocol.md) + [maps/mcp-tool-routing.yaml](maps/mcp-tool-routing.yaml)                           |
| Codex custom MCP attachment            | [playbooks/codex-custom-mcp-playbook.md](playbooks/codex-custom-mcp-playbook.md)                                                                    |
| Lane decomposition / orchestration     | [playbooks/worktree-codex-playbook.md](playbooks/worktree-codex-playbook.md) + [playbooks/lane-scoped-context.md](playbooks/lane-scoped-context.md) |

### Portable Command Router

<!-- BEGIN GENERATED: codex-command-router -->
<!-- GENERATED by scripts/generate_agent_workflows.py; do not edit by hand. -->

If a user prompt begins with a registered `/command_id`, treat that prefix as a portable workflow command routed through `config/agent-workflows/portable_commands.json`.

Current managed ids: `/scope`, `/refactor`, `/auto-fix`, `/branch-lifecycle`, `/branch-review`, `/handoff-lifecycle`, `/investigate`, `/incremental-implementation`, `/plan-analyze`, `/planning-review`, `/review-parallel`, `/tdd`, `/offload`, `/workbay`, `/ux-map`.

Routing rules:

- Strip the leading `/command_id` token before normal intent analysis.
- Load the mapped skill from the manifest and use its `makefile_target` as the primary entry point when one exists.
- Interpret the remainder of the user message using the manifest-defined argument names.
- If generated adapters drift from the manifest, run `make generate-agent-workflows`; `make check-agent-workflows` verifies Claude, VS Code, and Codex outputs together.

Command map:

- `/scope` (guide) -> skill `scope` -> `(in-session intake; no standalone make target)`
- `/refactor` (guide) -> skill `refactor` -> `(in-session advisory skill; no standalone make target)`
- `/auto-fix` (write) -> skill `auto-fix` -> `(in-session bounded-loop skill; no standalone make target)`
- `/branch-lifecycle` (write) -> skill `branch-lifecycle` -> `make task-start TASK=<task-ref> OBJECTIVE="..."`
- `/branch-review` (verify) -> skill `branch-review` -> `make review-run`
- `/handoff-lifecycle` (guide) -> skill `handoff-lifecycle` -> `make context`
- `/investigate` (write) -> skill `investigate` -> `(in-session root-cause skill; no standalone make target)`
- `/incremental-implementation` (write) -> skill `incremental-implementation` -> `make slice-start TASK=<task-ref> TEST_CMD="<command>"`
- `/plan-analyze` (verify) -> skill `plan-analyze` -> `make plan-analyze DOC=<path>`
- `/planning-review` (verify) -> skill `planning-review` -> `make plan-review DOC=<path>`
- `/review-parallel` (verify) -> skill `review-parallel` -> `(in-session coordinator skill; no standalone make target)`
- `/tdd` (write) -> skill `tdd` -> `make slice-start TASK=<task-ref> TEST_CMD="<command>"`
- `/offload` (write) -> skill `offload` -> `(in-session cross-harness offload skill; no standalone make target)`
- `/workbay` (guide) -> skill `workbay` -> `(in-session harness control; no standalone make target)`
- `/ux-map` (guide) -> skill `ux-map` -> `(in-session advisory skill; no standalone make target)`

<!-- END GENERATED: codex-command-router -->

## Codex Parity

The repo ships portable invocation surfaces to Codex from the shared workflow manifest and plugin tree; neither requires per-user config mutation.

**`$skill` resolution** — Codex skills are materialized through the workbay plugin tree under `.workbay/generated/plugins/workbay-system/`. Drift is gated by `make check-agent-workflows`, which checks the generated prompt/router adapters against the shared manifest. See [../../docs/assessments/e17-12-codex-skill-registration-discovery-2026-04-18.md](../assessments/e17-12-codex-skill-registration-discovery-2026-04-18.md) for the protocol-surface evidence behind the original static-discovery path.

**`/command` resolution** — the Codex harness has no native slash-command registry, so `/branch-review`, `/planning-review`, etc. are routed by model reading of the generator-owned router block above (BEGIN/END marker-delimited). The same block is mirrored into `CLAUDE.md`. Manual edits inside the markers are overwritten by the next `make generate-agent-workflows` run.

**Deliberately not shipped**: native UI-level `/command` chips in the Codex harness. The Codex app-server advertises no capability bit for extra slash-command roots, and the only per-session register surface (`skills/list perCwdExtraUserRoots`) is per-call and does not persist. That surface is documented for diagnostic tooling only and is not wired into any hook or config. See the discovery report linked above for the full static-config + `perCwdExtraUserRoots` + `skills/config/write` sweep.

## Agent Startup Protocol

Run at every session start (cold start, mid-task re-entry, lane inherit).

1. Identify or start the task. Existing feature-branch work continues from its `target_worktree_path`; ad-hoc main-branch docs/config work should start with `make maint-start TASK=MAINT-<slug>-<YYYYMMDD> OBJECTIVE="..."` before any cwd-resolving MCP read.
2. Run `make context` as a standalone command. It verifies branch/worktree alignment and prints the active task identity, open findings count, and a role-routing reminder. On `Ambiguous active task`, run `make maint-archive-stale` and retry.
3. Apply the **[MCP Loading Protocol](rules/mcp-loading-protocol.md)** before additional MCP reads. Read [`maps/mcp-tool-routing.yaml`](maps/mcp-tool-routing.yaml) and surface only servers whose triggers match the current prompt + task scope.
4. In a lane: run `make lane-inbox` to pick up routed findings, blockers, and dispatch messages before editing.
5. Load role routing from the Role Selection table. Read the linked context map, guidelines, and testing guide for the surface you are about to change.
6. Check open findings when you need the detailed list behind the `make context` count: `review_findings(review={"operation":"list","status":"open"})`.
7. Verify boundaries only when relevant. If the task touches a service/schema/MCP boundary, confirm the owning contract in [contracts/](contracts/).
8. Ensure the work has an MCP task before editing. Task plan optional; handoff state not. Wrong active task → switch or initialize before editing.

Cold start vs. mid-task re-entry:

- Cold start: initialize handoff state if none exists, then continue in order.
- Mid-task re-entry: load hot state, then use `search_handoff` for prior slice summaries or older findings. Do not replay full task history.

If MCP handoff is unavailable:

- `DASHBOARD.txt` = stale human-readable fallback; `CURRENT_TASK.json` = optional task-scoped export only if an explicit render wrote it; do not assume it exists or is current.
- Treat missing MCP as a blocker; record/report when access returns.

---

## Critical Rules

These rules are **universal** and apply to every task regardless of domain.

### Output Brevity (MANDATORY)

> **Default to terse output. Strip filler, hedging, and elaboration. State the result, not the journey.**

Verbosity degrades accuracy on reasoning tasks — models talk themselves into wrong answers. Brevity constraints cut output ~60-75% while improving correctness. Reference: [Hakim 2025](https://arxiv.org/html/2604.00025v1).

| Surface | Standard |
|---------|----------|
| Chat | One sentence per update. ≤2 sentence summary. No preamble. |
| Handoff rationale | Decision first. ≤1,500 chars. Cut recaps. |
| Review findings | One paragraph: evidence + impact. |
| Slice decisions | Template sections only. No padding. |
| Code comments | Default zero. One line max, WHY only. |
| Commit messages | Outcome in subject. Body only when diff doesn't explain why. |

Planning docs, contracts, and error messages need completeness — but still cut filler.

**Heuristics:** Sentence removable without information loss? Remove it. Paragraph restates the diff? Delete it. Opens with "I" + verb? Lead with the finding. Rationale recaps the problem? Cut the recap. Lists over paragraphs.

### Plugin Boundary Rule

> **You may ONLY modify files within this monorepo.**

**Allowed paths:**

- `apps/prototype-wp-alt-context/`
- `apps/prototype-description-service/`
- `packages/` (only the package directories present in this checkout)
- `docs/`
- `scripts/`

If `workbay-handoff-mcp` has been extracted into its standalone `darce/mcp-workbay-handoff` repository, treat that repo as external and out of bounds unless the workspace is opened there directly.

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

- Canonical rule source: [constitution.md](constitution.md#short-rules).
- Edit `[sr-NNN]` rules in `docs/workbay/constitution.md`; do not maintain an independent copy here.

### Cross-Branch Regression Guards

- Canonical rule source: [constitution.md](constitution.md#cross-branch-regression-guards).
- Edit `[rg-NNN]` guards in `docs/workbay/constitution.md`; do not maintain an independent copy here.

### Tool Selection Discipline

> **Enforcement layer**: `.github/copilot-instructions.md` (auto-injected into VS Code Copilot sessions), `.github/hooks/terminal-guard.py` (intercepts `run_in_terminal`), `.github/hooks/guard-main-branch.py` (blocks code edits on `main`). Claude Code parallel hook: `.claude/settings.json`.

Two environments, different tool surfaces. Use the native tool for the environment; wrong-tool calls waste tokens.

**VS Code agents** (GitHub Copilot, Copilot Chat, VS Code extensions) have native tools that bypass the terminal entirely:

| Task                            | Use this                                              | Not this                            |
| ------------------------------- | ----------------------------------------------------- | ----------------------------------- |
| List changed files / read diffs | `get_changed_files` (VS Code SCM)                     | `git diff` in terminal              |
| Read file contents              | `read_file`                                           | `cat` / `sed -n` in terminal        |
| Search code                     | `grep_search` / `semantic_search` / `search_subagent` | `grep -rn` in terminal              |
| Lint / type errors              | `get_errors`                                          | `npm run lint` / `mypy` in terminal |
| Multi-file exploration          | `Explore` subagent                                    | Sequential terminal commands        |

Reserve terminal for operations with no native-tool equivalent: test execution, `make` targets, `uv`/`uvx` commands, `git commit`/`push`/`rebase`.

**Codex agents** (OpenAI Codex harness, `codex exec`, `codex-subagent-bridge`) run in sandboxed Linux containers with terminal + filesystem + MCP only. They do not have VS Code extension tools. Terminal equivalents and output discipline for Codex: [playbooks/codex-custom-mcp-playbook.md](playbooks/codex-custom-mcp-playbook.md#tool-discipline).

**Terminal output discipline** (both environments, when terminal is required):

- Pipe through `tail -n 30`, `head -n 50`, or `grep -E '<pattern>'` for unbounded output.
- **Test runs (MANDATORY):** Capture to `/tmp/`, then `read_file` the capture. Do NOT rely on terminal output alone.
  - Python (apps): `cd <app-dir> && VIRTUAL_ENV= uv run --locked --extra dev python -m pytest <path> -q > /tmp/pytest_<suite>.txt 2>&1`
  - Python (external MCP package verification): create a scratch venv, install the reviewed PyPI releases, then run CLI/import smoke from that environment. Example: `python3 -m venv /tmp/e17-13-external-mcp && /tmp/e17-13-external-mcp/bin/pip install --quiet "mcp-workbay-handoff==0.2.0" "mcp-workbay-orchestrator==0.2.0" > /tmp/pytest_external_mcp.txt 2>&1 && /tmp/e17-13-external-mcp/bin/mcp-workbay-handoff --workspace-root . doctor >> /tmp/pytest_external_mcp.txt 2>&1 && /tmp/e17-13-external-mcp/bin/mcp-workbay-orchestrator --workspace-root . --help >> /tmp/pytest_external_mcp.txt 2>&1`. Do not use `make test-handoff` or `make test-orchestrator` for this cleanup verification path.
  - Vitest in VS Code agent chat: `cd <app-dir> && npm run test:agent -- <path> > /tmp/vitest_<suite>.txt 2>&1`, then inspect the captured output because the wrapper returns control to chat even for RED tests. Use normal `npm run test -- <path>` only outside the agent chat workflow when failing exit codes can propagate safely.
  - PHP: `cd <app-dir> && vendor/bin/phpunit <path> > /tmp/phpunit_<suite>.txt 2>&1`
  - Then: `read_file("/tmp/pytest_<suite>.txt")`. Never `cat` in terminal. If output is truncated/polluted, just `read_file` the capture.
- Excess output → redirect to `/tmp/<name>.txt` and `read_file` (VS Code) or `sed -n` (Codex); do not re-run.
- **Foreground terminals for Python app tests.** Background sessions can drift from the description-service project's uv-managed `.venv`. Use the foreground terminal for app test runs.
- **Use env vars**, not hardcoded paths. Prefer `${workspaceFolder}`, `${env:HOME}`, and `${REPO_ROOT:-$PWD}`.
- **Package-test Python harness workaround.** For `workbay-orchestrator-mcp` / `workbay-handoff-mcp`, do not invoke IDE Python environment setup. Use pinned `uvx --from "mcp-workbay-handoff==0.2.0" python3`, `uvx --from "mcp-workbay-orchestrator==0.2.0" python3`, or scratch-venv binaries from the foreground terminal. If IDE shows `Configuring a Python Environment`, stop and ask the user to run the terminal command.

### Task Document Rules

- Consolidate all checklists at the **bottom** of task documents. No scattered `- [ ]` items. No time estimates.
- Planning docs must stay internally consistent (current state vs checklist vs success criteria vs ADR terms).
- Record every planning-review finding in MCP handoff before presenting it in chat.
- Do not log findings, `finding_id`s, or fix-status notes into task plans. MCP handoff is the canonical store; `DASHBOARD.txt` and `CURRENT_TASK.json` are generated mirrors.
- Reference code locations by **function/target name**, not line numbers.
- Pseudocode functions and CLI commands in plans must map to an existing API/import or be marked "new, to be created."
- Validate enum values and status strings in plans against the actual API/schema.
- Do not list a file in "Functions to Change" unless it requires modification. Verification-only → mark as such.
- Live MCP tool schema is authoritative over examples or templates. Prefer the minimal valid payload.
- MCP write fails validation from stale docs → retry with minimal live-valid payload and update the stale guidance.

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
- Task plan titles: `<EpicShortID>-<N>. <Title>` for epic-owned plans, or a documented package/project-local task id such as `AHMCP-2. ...` when the work is not owned by a monorepo epic
- Slice-complete decisions: `<author_tag>_slice_complete_<work_ref>_<slug>` (e.g., `cdx_slice_complete_E12-1_gate_validation`)

When creating or reviewing planning artifacts, load the correct template or review guide per the [context routing table](rules/development-workflow.md#context-routing-for-reviews).

Planning artifact pipeline:

- Start with an assessment when the problem surface still needs code-verified framing.
- Write a spec before implementation task plans when the change affects a contract, output surface, or multi-slice design.
- Insert an ADR only when a spec item is blocked on a design gate.
- Create implementation task plans only after the upstream assessment/spec/ADR gates are reviewed.

Full pipeline documentation with stage definitions, exit gates, and exemplars: [rules/planning-pipeline.md](rules/planning-pipeline.md).

### Branch-Per-Task Convention

Each task plan declares a **target branch** in its metadata. When starting implementation:

1. Create the branch from `main`: `git checkout -b <target_branch> main`
2. Activate the MCP task: `switch_task(task_ref="...", objective="...")`
3. Verify the current worktree and branch actually belong to that task before editing. If the active branch does not match the task's branch, switch first instead of carrying changes across tasks.
4. Commit modified files on the branch that owns the task. Do not leave one task's code changes stranded on another task's branch.
5. On completion, request review and merge the task branch back to `main` via PR; do not continue piling unrelated follow-up work onto the merged branch.

If you inherit dirty code changes on `main`, stop and isolate them before starting new implementation work. Move them to the correct feature branch or stash them only long enough to recover a clean starting point; do not normalize ongoing code edits on `main`.

For normal task switching, always **commit before switching** branches; do not use stash as the routine handoff mechanism. WIP commits are visible, referenceable, and squashable. See [rules/planning-pipeline.md](rules/planning-pipeline.md#safe-branch-switching) for the full switching procedure.

### MCP Handoff Contract (MANDATORY)

Multiple concurrent agents share state through MCP handoff tools.

- Every code change → log a decision entry before review or completion. Summarize what changed and how it was verified.

## Selective Handoff Loading

Tiered memory. Load only what the current slice needs.

- **Hot** (always at startup): objective, open findings, open blockers, latest verification, latest 3 decisions.
- When `CURRENT_TASK.json` is rendered explicitly, it should expose the latest decision separately from the recent-decisions list.
- **Warm** (on demand): recent worker reports, lane activity, active artifacts, nearby plan-cursor history.
- **Cold** (targeted search only): archived findings, superseded plan cursors, verbose logs, large artifacts.

`task_ref` granularity:

- One `task_ref` per reviewable feature or task-plan stream — not per commit, not per epic.
- Epic-level `task_ref` for planning/coordination only. Switch to implementation task when coding starts.
- Stay on same `task_ref` while objective and review packet are "the same work."
- Switch when the objective changes or the active task would otherwise surface the wrong latest decision in task-scoped handoff state.
- Do not create a new `task_ref` per micro-slice. Multiple `slice_complete_*` decisions under one task until done.

Loading rules:

- Do not replay full history. Use `search_handoff` for older records.
- Do not re-read full state after a write just to confirm. Trust the write confirmation.
- Resume: hot state first, expand to warm/cold only if the slice requires it.

Canonical handoff runtime:

- `workbay-handoff-mcp` exclusively.
- Install reference: [contracts/workbay-handoff-mcp.md](contracts/workbay-handoff-mcp.md). After E13 extraction, canonical external source is `darce/mcp-workbay-handoff` (private git+ssh).

Primary binary shape:

- `mcp-workbay-handoff --workspace-root <repo> serve-stdio`
- `mcp-workbay-handoff --workspace-root <repo> doctor`
- `mcp-workbay-handoff --workspace-root <repo> state`
- `mcp-workbay-handoff --workspace-root <repo> task <task_ref>`
- `mcp-workbay-handoff --workspace-root <repo> switch <task_ref>`

## Periodic Health Reviews

Full checklists and pattern definitions: [playbooks/ace-pruning-playbook.md](playbooks/ace-pruning-playbook.md).

Key gates (every slice):

1. Every file-changing slice must end with a `slice_complete_*` decision. Format: [templates/slice-complete-template.md](templates/slice-complete-template.md). Enforced at write time.
2. Call `render_handoff(kind='dashboard')` after recording — DASHBOARD.txt is the operator-facing view and must stay current.
3. Do not leave DASHBOARD.txt stale. Record the missing decision before handoff if needed.
4. Update singleton state via `set_handoff_state(..., expected_revision=<current>, actor={ ... })`.
5. Include `Handoff updated: yes` in the response.

View regeneration policy:

- **After every state-changing operation** (`record_event`, `review_findings`, `review_runs`, `set_handoff_state`, `update_task_status`): call `render_handoff(kind='dashboard')`. This keeps the cross-task operator view current — NEEDS ATTENTION, ALL TASKS, OPEN FINDINGS.
- **On-demand only**: call `render_handoff(kind='current_task', task_ref=<ref>)` when a specific task's machine-readable JSON snapshot is needed (e.g., before handing off to another agent on the same task, or when producing a task-scoped report). Agents with live MCP access do not need this in the hot path — use `get_handoff_state` or `load_session` instead.
- `close_slice` and `archive_task_state` regenerate both views atomically server-side; no extra call needed after those.

Write-tool targeting rule:

- Write tools default to the active task when `task_ref` is omitted. In cross-task workflows, pass `task_ref` explicitly.
- `record_event`: pass `task_ref` inside the `event` payload. `switch_task(task_ref)` to change tasks; `set_handoff_state(...)` for in-place updates.

During-work discipline:

- Record blockers immediately: `record_event(event={event_kind: "blocker", task_ref: ..., actor: {...}, ...})`.
- Record verification: `record_event(event={event_kind: "test_result", ...})`. Keep `result` concise.
- Record findings: `review_findings(review={operation: "record", ...})` for 1-2; `batch_record` for 3+ (atomic write, single DB flush).
- **Findings live in handoff, not in task plans.** The `scripts/hooks/guard-task-plan-findings.py` hook rejects 3+ consecutive finding-style bullets in task plans. Same scanner runs via `make lint-task-plans`. Reference findings by ID (`see AOMCP-3-BR-04 in handoff`), never by pasting.
- **Regenerate DASHBOARD.txt** after every state-changing operation (`record_event`, `review_findings(operation="update"|"batch_record")`).
- Validate review state with `get_review_findings_summary(...)` and `review_findings(review={"operation":"list", ...})`, not direct `sqlite3`.

Read discipline:

- Do not query `.task-state/handoff.db` directly when MCP tools are available.
- `get_handoff_state` for active-task snapshot, `get_review_findings_summary` for counts, `review_findings(operation="list")` for detailed verification.
- `finding_id` (e.g. `"H-OCI-28"`) for single-finding lookup. Optional `task_ref` on list/summary to query non-active tasks without switching.
- Only supported handoff surface: `workbay-handoff-mcp` per [contracts/workbay-handoff-mcp.md](contracts/workbay-handoff-mcp.md).

State integrity invariants:

- Import/restore payloads are untrusted. Validate shape before writes; malformed → `ok: false`.
- Write provenance is immutable once set. Status updates may fill missing fields but must not overwrite recorded provenance.
- **Commit SHA provenance (MANDATORY):** Pass the **canonical 40-character SHA** from `git rev-parse HEAD` to every `commit_sha` field. Never type from memory. The write path validates via `git rev-parse --verify <sha>^{commit}` and rejects fabricated SHAs (`InvalidCommitShaError`). Abbreviated SHAs that resolve uniquely are auto-expanded. Validation bypassed in tests via `AGENT_HANDOFF_SKIP_SHA_VALIDATION=1`. See [rules/testing-python.md § Commit SHA Provenance Discipline](rules/testing-python.md#commit-sha-provenance-discipline-mandatory).

Failure policy:

- If MCP handoff tools are unavailable, stop normal implementation work.
- Record/report the blocker, and include: `Handoff updated: no (tool unavailable)`.

- Use `templates/CURRENT_TASK.template.md` only as fallback when MCP handoff is unavailable.

Completion gate:

- A task response is incomplete if MCP handoff was not updated.

Task lifecycle:

- When a task is finished (all slices complete, success criteria met), set its status to `done` via `update_task_status(task_ref=..., status="done")` before or after archiving.
- `close_slice` keeps the task `in_progress` by design — it does not close the task.
- `archive_task_state` snapshots the current task state into archive storage but preserves whatever status the task had at archive time. If you archive while still `in_progress`, the dashboard will permanently show `in_progress` for that task.
- Correct close sequence: `update_task_status(task_ref=..., status="done")` then `archive_task_state(task_ref=...)`. The reverse order also works: archive first, then `update_task_status` updates the archived snapshot.
- Non-archived, non-active tasks default to `active` in task-scoped current-task renders. This is a rendering fallback, not stored state. To clear orphaned tasks, archive them and set status to `done`.

### Multi-Agent Worktree Orchestration (MANDATORY for delegated implementation)

Use this pattern when a user explicitly asks for parallel agents/worktrees, or when the task naturally splits into independent backend/frontend/PHP lanes with clear contracts.

For all operational commands, recipes, decomposition rules, domain guardrails, worker communication, merge procedures, and automated orchestration via Codex subagents, see:

- [playbooks/worktree-codex-playbook.md](playbooks/worktree-codex-playbook.md) -- decomposition rules, domain guardrails, worker recipes, merge procedures
- [playbooks/lane-scoped-context.md](playbooks/lane-scoped-context.md) -- lane-scoped context construction and prompt budgets

Summary: orchestrator stays on root branch; workers own `codex/*` branches with bounded path scope; lane manifest lives in `config/lane-orchestration/<task-ref>.json`; use `make lane-refresh` to propagate orchestrator changes; dirty worktrees are not valid handoff artifacts.

### Branch Review Trigger (MANDATORY)

When a user request matches any of these patterns, route it through the [../../.claude/skills/branch-review/SKILL.md](../../.claude/skills/branch-review/SKILL.md) skill (or `/branch-review`) before starting the review:

- "review" + ("implementation" | "code" | "changes" | "branch" | "PR" | "diff")
- "audit" + ("branch" | "code")
- "propose improvements" | "flag gaps" | "flag bugs"
- Any request to evaluate uncommitted or branch-scoped changes for quality

**Procedure:**

1. Read the `branch-review` skill and use `make review-run` when the workflow is agent-assisted.
2. Use `rules/branch-review-guide.md` as the detailed checklist/report reference behind the skill.
3. Read the relevant stack guide(s) based on files in the diff.
4. Walk the common checklist + stack-specific checklist, citing files and lines.
5. Classify each finding using the defined categories (ANTIPATTERN / DEAD_CODE / COMPLEXITY / GAP) and severities (HIGH / MEDIUM / LOW).
6. Record findings in MCP handoff. Use `review_findings(review={"operation":"record", ...}, actor={ ... }, task_ref=...)` for 1-2 findings; use `review_findings(review={"operation":"batch_record", findings=[...], ...}, actor={ ... }, task_ref=...)` for 3 or more (atomic write, single post-write dashboard refresh, per-item results).
7. Produce the markdown report using the template.
8. Call `record_event(event={event_kind: "decision", actor: {...}, ...})` summarizing the review, then `render_handoff(kind='dashboard')`. Call `render_handoff(kind='current_task', ...)` only if a task-scoped machine snapshot is explicitly needed.

**Do NOT** perform ad-hoc reviews. The guide exists to ensure consistent, structured, cross-agent-visible output.

### Planning Document Review Rule (MANDATORY)

When a user asks to review a task plan, epic, roadmap, ADR, or other planning document:

1. Review the document against the current codebase and adjacent planning docs.
2. Record each finding in MCP handoff before presenting it.
3. Focus findings on obsolete assumptions, implementation gaps, contradictory scope, contract mismatches, rollout/test gaps, and unnecessary complexity.
4. Treat the recorded handoff finding as the canonical review artifact even if no separate report file is requested.

Branch review guidance is code-change specific. Planning-document reviews still require handoff recording, but should use planning-specific judgment rather than forcing the branch-diff checklist onto docs.

### Planning Review Trigger (MANDATORY)

When a user request matches any of these patterns, route it through the [../../.claude/skills/planning-review/SKILL.md](../../.claude/skills/planning-review/SKILL.md) skill (or `/planning-review`) before starting the review:

- "review" + ("task plan" | "epic" | "roadmap" | "ADR" | "planning document")
- "flag issues" | "flag gaps" | "flag obsolete assumptions" on a doc under `docs/`
- "audit" + ("plan" | "epic" | "roadmap")
- Any request to evaluate implementation realism, dependencies, or checklist consistency in planning docs

Procedure:

1. Run `plan-analyze` first (`make plan-analyze DOC=<path>` or `/plan-analyze`) so pre-review triage is recorded before formal review.
2. Read the `planning-review` skill and use `make plan-review DOC=<path>` when the workflow is agent-assisted.
3. Use `rules/planning-review-guide.md` as the detailed checklist/reference behind the skill.
4. Review the document against the current codebase and adjacent planning/contracts.
5. Record each finding in MCP handoff before presenting it.
6. Cite both the planning-doc lines and the current code/contract lines that justify the finding.
7. If asked to patch the document, resolve the recorded findings and then update their status.

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

> Templates and file organization are discoverable from `docs/workbay/templates/`. Formatting rules are in linter configs (`tsconfig`, `phpcs.xml`, `pyproject.toml`, `prettier`).

- **`.mmd` files: raw Mermaid syntax only -- NO code fences**
- `.md` files: use fenced code blocks
- Maximum 12 classes per diagram
- Use language-agnostic types: `string`, `int`, `bool`, `array<T>`
- **ASCII only** in documentation. No emoji.
- **Internationalization**: all user-facing strings through `__()`, `_x()`, `_n()` with text domain `alt-context`.
