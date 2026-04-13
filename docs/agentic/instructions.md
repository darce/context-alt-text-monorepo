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

| Role                            | Context Map                                                                  | Guidelines                                                               | Testing Guide                                              | Tech Stack (ctx7)                                                          | Key Entry Points                      |
| ------------------------------- | ---------------------------------------------------------------------------- | ------------------------------------------------------------------------ | ---------------------------------------------------------- | -------------------------------------------------------------------------- | ------------------------------------- |
| **Backend (Python)**            | [maps/backend.md](maps/backend.md)                                           | [rules/backend-python-guidelines.md](rules/backend-python-guidelines.md) | [rules/testing-python.md](rules/testing-python.md)         | [maps/tech-stack.md#backend-python](maps/tech-stack.md#backend-python)     | `apps/prototype-description-service/` |
| **Frontend (React/TS)**         | [maps/frontend.md](maps/frontend.md)                                         | [rules/frontend-guidelines.md](rules/frontend-guidelines.md)             | [rules/testing-typescript.md](rules/testing-typescript.md) | [maps/tech-stack.md#frontend-reactts](maps/tech-stack.md#frontend-reactts) | `apps/prototype-wp-alt-context/js/`   |
| **PHP Plugin**                  | [maps/php-plugin.md](maps/php-plugin.md)                                     | [rules/backend-php-guidelines.md](rules/backend-php-guidelines.md)       | [rules/testing-php.md](rules/testing-php.md)               | [maps/tech-stack.md#php-plugin](maps/tech-stack.md#php-plugin)             | `apps/prototype-wp-alt-context/src/`  |
| **Cross-Service Integration**   | [maps/integration.md](maps/integration.md)                                   | [contracts/](contracts/)                                                 | [rules/testing-principles.md](rules/testing-principles.md) | [maps/tech-stack.md#orchestration](maps/tech-stack.md#orchestration)       | `docs/agentic/contracts/`             |
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
| Branch review                          | [rules/branch-review-guide.md](rules/branch-review-guide.md)                                                                                        |
| Planning document review               | [rules/planning-review-guide.md](rules/planning-review-guide.md)                                                                                    |
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

## Agent Startup Protocol

Run at every session start (cold start, mid-task re-entry, lane inherit).

1. Apply the **[MCP Loading Protocol](rules/mcp-loading-protocol.md)** before any MCP read. Read [`maps/mcp-tool-routing.yaml`](maps/mcp-tool-routing.yaml) and surface only servers whose triggers match the current prompt + task scope. `agent-handoff-mcp` always loaded; others (`agent-orchestrator-mcp`, `context7`, `computer-use`) on-demand. Harness-agnostic.
2. Query MCP handoff state. Routine check: `get_handoff_state(sections="identity")` (cheapest read — returns `active` + `limits`). Hot-state load: full `get_handoff_state(task_ref="<task>")`. On `oversize_response` warning (~20 KB/~5 k tokens), narrow with `sections=...`, `detail="summary"`, lower `top_n_*`, or `fields=...` per [token-efficient-usage.md](../../packages/agent-handoff-mcp/docs/guides/token-efficient-usage.md).
3. In a lane: run `make lane-inbox` to pick up routed findings, blockers, and dispatch messages before editing.
4. Load role routing from the Role Selection table. Read the linked context map, guidelines, and testing guide.
5. Check open findings: `review_findings(review={"operation":"list","status":"open"})`.
6. Verify contracts. If the task touches a service/schema/MCP boundary, confirm the owning contract in [contracts/](contracts/). Missing contract → scaffold one per [development-workflow.md](rules/development-workflow.md) before proceeding.
7. Decide `ctx7` need. Upstream library/framework behavior → apply ctx7 entry criteria below. (Loading Protocol decides whether to _load_ the server; entry criteria decide whether to _call_ it.)
8. Ensure the work has an MCP task. Task plan optional; handoff state not. Wrong active task → switch or initialize before editing.

Cold start vs. mid-task re-entry:

- Cold start: initialize handoff state if none exists, then continue in order.
- Mid-task re-entry: load hot state, then use `search_handoff` for prior slice summaries or older findings. Do not replay full task history.

If MCP handoff is unavailable:

- `DASHBOARD.md` = stale human-readable fallback; `CURRENT_TASK.md` = machine-readable state.
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

If `agent-handoff-mcp` has been extracted into its standalone `darce/mcp-agent-handoff` repository, treat that repo as external and out of bounds unless the workspace is opened there directly.

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
- Edit `[sr-NNN]` rules in `docs/agentic/constitution.md`; do not maintain an independent copy here.

### Cross-Branch Regression Guards

- Canonical rule source: [constitution.md](constitution.md#cross-branch-regression-guards).
- Edit `[rg-NNN]` guards in `docs/agentic/constitution.md`; do not maintain an independent copy here.

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

Reserve terminal for operations with no native-tool equivalent: test execution, `make` targets, `pyenv` commands, `git commit`/`push`/`rebase`.

**Codex agents** (OpenAI Codex harness, `codex exec`, `codex-subagent-bridge`) run in sandboxed Linux containers with terminal + filesystem + MCP only. They do not have VS Code extension tools. Terminal equivalents and output discipline for Codex: [playbooks/codex-custom-mcp-playbook.md](playbooks/codex-custom-mcp-playbook.md#tool-discipline).

**Terminal output discipline** (both environments, when terminal is required):

- Pipe through `tail -n 30`, `head -n 50`, or `grep -E '<pattern>'` for unbounded output.
- **Test runs (MANDATORY):** Capture with `tee` to `/tmp/`, then `read_file` the capture. Do NOT rely on terminal output alone.
  - Python (apps): `cd <app-dir> && pyenv exec python -m pytest <path> -q 2>&1 | tee /tmp/pytest_<suite>.txt`
  - Python (in-monorepo packages): **always use the Makefile target**, never direct `pytest`. `cd packages/agent-handoff-mcp && make test-handoff 2>&1 | tee /tmp/pytest_handoff.txt` (or `make test-orchestrator`). The Makefile sets `PYTHONPATH` to the current worktree's `src/`; direct `pytest` resolves to whichever editable install is registered env-wide. Both `tests/conftest.py` enforce this with a `pytest_sessionstart` guard. See [rules/testing-python.md § In-Monorepo Package Test Invocation](rules/testing-python.md#in-monorepo-package-test-invocation-mandatory).
  - Vitest: `cd <app-dir> && npx vitest run <path> 2>&1 | tee /tmp/vitest_<suite>.txt`
  - PHP: `cd <app-dir> && vendor/bin/phpunit <path> 2>&1 | tee /tmp/phpunit_<suite>.txt`
  - Then: `read_file("/tmp/pytest_<suite>.txt")`. Never `cat` in terminal. If output is truncated/polluted, just `read_file` the capture.
- Excess output → redirect to `/tmp/<name>.txt` and `read_file` (VS Code) or `sed -n` (Codex); do not re-run.
- **Background terminals lack pyenv virtualenv activation.** Use foreground terminal for Python tests. Stale scrollback → `tee /tmp/` pattern.
- **Use env vars**, not hardcoded paths. Prefer `${workspaceFolder}`, `${env:HOME}`, `${PYENV_ROOT:-$HOME/.pyenv}`, `${REPO_ROOT:-$PWD}`.
- **Package-test Python harness workaround.** For `agent-orchestrator-mcp` / `agent-handoff-mcp`, do not invoke IDE Python environment setup. Pin `${env:HOME}/.pyenv/versions/description-service/bin/python`; run from foreground terminal with `PYENV_VERSION=description-service`. If IDE shows `Configuring a Python Environment`, stop and ask the user to run the terminal command.

### Task Document Rules

- Consolidate all checklists at the **bottom** of task documents. No scattered `- [ ]` items. No time estimates.
- Planning docs must stay internally consistent (current state vs checklist vs success criteria vs ADR terms).
- Record every planning-review finding in MCP handoff before presenting it in chat.
- Do not log findings, `finding_id`s, or fix-status notes into task plans. MCP handoff is the canonical store; `DASHBOARD.md` and `CURRENT_TASK.md` are generated mirrors.
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
- `CURRENT_TASK.md` must expose the latest decision separately from the recent-decisions list.
- **Warm** (on demand): recent worker reports, lane activity, active artifacts, nearby plan-cursor history.
- **Cold** (targeted search only): archived findings, superseded plan cursors, verbose logs, large artifacts.

`task_ref` granularity:

- One `task_ref` per reviewable feature or task-plan stream — not per commit, not per epic.
- Epic-level `task_ref` for planning/coordination only. Switch to implementation task when coding starts.
- Stay on same `task_ref` while objective and review packet are "the same work."
- Switch when the objective changes or `CURRENT_TASK.md` would show the wrong latest decision.
- Do not create a new `task_ref` per micro-slice. Multiple `slice_complete_*` decisions under one task until done.

Loading rules:

- Do not replay full history. Use `search_handoff` for older records.
- Do not re-read full state after a write just to confirm. Trust the write confirmation.
- Resume: hot state first, expand to warm/cold only if the slice requires it.

Canonical handoff runtime:

- `agent-handoff-mcp` exclusively. Legacy `scripts/mcp/unified_server.py` is deprecated (repo-intel-only); retirement tracked in [unified-server-retirement.md](../tasks/tech-debt/unified-server-retirement.md).
- Install reference: [contracts/agent-handoff-mcp.md](contracts/agent-handoff-mcp.md). After E13 extraction, canonical external source is `darce/mcp-agent-handoff` (private git+ssh).

Primary binary shape:

- `agent-handoff-mcp --workspace-root <repo> serve-stdio`
- `agent-handoff-mcp --workspace-root <repo> doctor`
- `agent-handoff-mcp --workspace-root <repo> state`
- `agent-handoff-mcp --workspace-root <repo> task <task_ref>`
- `agent-handoff-mcp --workspace-root <repo> switch <task_ref>`

## ctx7 Entry Criteria

Use `ctx7` when implementation depends on upstream library/framework behavior that may have drifted.

Use when:

- code depends on an upstream API (FastAPI, SQLAlchemy, Radix UI, WordPress hooks, React, MCP SDK, etc.)
- verifying version-specific behavior, migration guidance, or deprecation details
- confirming the current API surface for a dependency in [maps/tech-stack.md](maps/tech-stack.md)

Do not use for:

- repo-local rules, contracts, task plans, handoff state, or architecture decisions
- facts owned by [instructions.md](instructions.md), [contracts/](contracts/), or [maps/tech-stack.md](maps/tech-stack.md)
- broad context when a targeted local document answers the question

Fallback and caching:

- Unavailable → use [maps/tech-stack.md](maps/tech-stack.md) as static manifest; note `ctx7` gap in handoff when it affects confidence.
- Before a new lookup, search recent handoff decisions for the package name or prior query to reuse existing answers.
- When a lookup changes an implementation decision, record in handoff:
  - `ctx7 library id: /org/project[/version]`
  - `ctx7 query: <targeted question>`
  - `ctx7 impact: <what changed in implementation or review scope>`
- Cache the pointer and decision impact, not a prose dump of upstream docs.

## Periodic Health Reviews

Full checklists and pattern definitions: [playbooks/ace-pruning-playbook.md](playbooks/ace-pruning-playbook.md).

Key gates (every slice):

1. Every file-changing slice must end with a `slice_complete_*` decision. Format: [templates/slice-complete-template.md](templates/slice-complete-template.md). Enforced at write time.
2. Call `generate_current_task_md(task_ref=<active-task-ref>)` after recording.
3. Do not leave `CURRENT_TASK.md` stale. Record the missing decision before handoff if needed.
4. Update singleton state via `set_handoff_state(..., expected_revision=<current>, actor={ ... })`.
5. Include `Handoff updated: yes` in the response.

Write-tool targeting rule:

- Write tools default to the active task when `task_ref` is omitted. In cross-task workflows, pass `task_ref` explicitly.
- `record_event`: pass `task_ref` inside the `event` payload. `switch_task(task_ref)` to change tasks; `set_handoff_state(...)` for in-place updates.

During-work discipline:

- Record blockers immediately: `record_event(event={event_kind: "blocker", task_ref: ..., actor: {...}, ...})`.
- Record verification: `record_event(event={event_kind: "test_result", ...})`. Keep `result` concise.
- Record findings: `review_findings(review={operation: "record", ...})` for 1-2; `batch_record` for 3+ (atomic write, single `CURRENT_TASK.md` flush).
- **Findings live in handoff, not in task plans.** The `scripts/hooks/guard-task-plan-findings.py` hook rejects 3+ consecutive finding-style bullets in task plans. Same scanner runs via `make lint-task-plans`. Reference findings by ID (`see AOMCP-3-BR-04 in handoff`), never by pasting.
- **Regenerate `CURRENT_TASK.md`** after every state-changing operation (`record_event`, `review_findings(operation="update"|"batch_record")`).
- Validate review state with `get_review_findings_summary(...)` and `review_findings(review={"operation":"list", ...})`, not direct `sqlite3`.

Read discipline:

- Do not query `.task-state/handoff.db` directly when MCP tools are available.
- `get_handoff_state` for active-task snapshot, `get_review_findings_summary` for counts, `review_findings(operation="list")` for detailed verification.
- `finding_id` (e.g. `"H-OCI-28"`) for single-finding lookup. Optional `task_ref` on list/summary to query non-active tasks without switching.
- Do **not** use legacy `scripts/mcp/unified_server.py`. Only supported surface: `agent-handoff-mcp` per [contracts/agent-handoff-mcp.md](contracts/agent-handoff-mcp.md). Removal tracked in [unified-server-retirement.md](../tasks/tech-debt/unified-server-retirement.md).

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
- Non-archived, non-active tasks default to `active` in the CURRENT_TASK.md dashboard. This is a rendering fallback, not stored state. To clear orphaned tasks, archive them and set status to `done`.

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
5. Record findings in MCP handoff. Use `review_findings(review={"operation":"record", ...}, actor={ ... }, task_ref=...)` for 1-2 findings; use `review_findings(review={"operation":"batch_record", findings=[...], ...}, actor={ ... }, task_ref=...)` for 3 or more (atomic write, single `CURRENT_TASK.md` flush, per-item results).
6. Produce the markdown report using the template.
7. Call `record_event(event={event_kind: "decision", actor: {...}, ...})` summarizing the review + `generate_current_task_md(...)`.

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
