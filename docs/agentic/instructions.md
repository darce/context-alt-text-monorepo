# Development Instructions

> **Cold-start document for coding agents.** Universal rules that cannot be deduced from code, configs, or linters. Domain-specific guidelines load via the routing table below.

> **On first load / cold start**: also read [BOOTSTRAP.md](BOOTSTRAP.md) for testing commands, MCP server setup, and handoff state defaults.

**Epic**: `docs/epics/v0.2.0/recognition-ux-and-ergonomics-epic.md` · **Roadmap**: `docs/roadmaps/roadmap-v4.md`

---

## Document Maintenance (ACE Self-Correction)

This document follows Autonomous Coding Engine principles for minimal, self-correcting agent instructions.

**Inclusion criteria** -- a rule belongs here only if:

1. It cannot be deduced from code, configs, linters, or static analysis
2. Violating it has caused a real failure in this project (not hypothetical)
3. It applies universally across all domains (domain-specific rules go in sub-documents)

**Self-correction protocol:**

- If a rule restates a linter check or config setting (`tsconfig`, `phpcs`, `pyproject.toml`, `eslint`), delete it -- the tool is the source of truth
- Never duplicate content between this file and linked sub-documents; use links
- Every paragraph must prevent a specific class of agent failure that has actually occurred; delete "good practice" paragraphs
- When encountering stale content (broken links, outdated naming), fix in-place
- Do not add rules that an agent can verify by running `make check`, `npm run lint`, or `composer phpstan`

---

## System Overview

```mermaid
flowchart TB
    subgraph WordPress["WordPress Plugin"]
        ReactUI["React Admin UI<br/>(Workbench, Dashboard, ConflictInbox, DeadLetterPanel)"] --> PHPLayer["PHP REST Layer<br/>(RecognitionController, ConflictController, SyncStatusController)"]
        PHPLayer --> SovereignSync["Sovereign Sync Layer<br/>(SnapshotProjector, OutboxDrain, ConflictResolutionService, SyncStateRepository)"]
        SovereignSync --> WPDB["WP Local Tables<br/>(clusters, members, outbox, conflicts, sync_state)"]
    end
    subgraph Backend["Recognition Service (FastAPI)"]
        API["FastAPI Routers<br/>(snapshot, curation sync, topology)"] --> Services["Domain Services"]
    end
    PHPLayer -->|"HTTP + API Key"| API
    API -->|"Snapshot pull"| SovereignSync
    SovereignSync -->|"Outbox push"| API
    Services --> Database["PostgreSQL + pgvector"]
```

**Full diagram:** [diagrams/system-overview.mmd](diagrams/system-overview.mmd)

---

## Role Selection

Choose your domain to load targeted context. **Always load the testing guide** alongside your role guidelines — we practice TDD.

| Role                          | Context Map                                | Guidelines                                                               | Testing Guide                                              | Key Entry Points                      |
| ----------------------------- | ------------------------------------------ | ------------------------------------------------------------------------ | ---------------------------------------------------------- | ------------------------------------- |
| **Backend (Python)**          | [maps/backend.md](maps/backend.md)         | [rules/backend-python-guidelines.md](rules/backend-python-guidelines.md) | [rules/testing-python.md](rules/testing-python.md)         | `apps/prototype-description-service/` |
| **Frontend (React/TS)**       | [maps/frontend.md](maps/frontend.md)       | [rules/frontend-guidelines.md](rules/frontend-guidelines.md)             | [rules/testing-typescript.md](rules/testing-typescript.md) | `apps/prototype-wp-alt-context/js/`   |
| **PHP Plugin**                | [maps/php-plugin.md](maps/php-plugin.md)   | [rules/backend-php-guidelines.md](rules/backend-php-guidelines.md)       | [rules/testing-php.md](rules/testing-php.md)               | `apps/prototype-wp-alt-context/src/`  |
| **Cross-Service Integration** | [maps/integration.md](maps/integration.md) | [contracts/](contracts/)                                                 | [rules/testing-principles.md](rules/testing-principles.md) | `docs/agentic/contracts/`             |

### Additional Routing

| Working on...                        | Load                                                                                 |
| ------------------------------------ | ------------------------------------------------------------------------------------ |
| Writing tests (any language)         | [rules/testing-principles.md](rules/testing-principles.md) + language-specific guide |
| React/TypeScript tests (Vitest)      | [rules/testing-typescript.md](rules/testing-typescript.md)                           |
| Python tests (pytest)                | [rules/testing-python.md](rules/testing-python.md)                                   |
| PHP tests (PHPUnit)                  | [rules/testing-php.md](rules/testing-php.md)                                         |
| Workflow, commits, scaffolding       | [rules/development-workflow.md](rules/development-workflow.md)                       |
| Branch review                        | [rules/branch-review-guide.md](rules/branch-review-guide.md)                         |
| Planning document review             | [rules/planning-review-guide.md](rules/planning-review-guide.md)                     |
| Component architecture patterns      | [rules/component-architecture-patterns.md](rules/component-architecture-patterns.md) |
| Radix UI / accessibility primitives  | [rules/RADIX_UI_COMPONENT_GUIDE.md](rules/RADIX_UI_COMPONENT_GUIDE.md)               |
| Roster auto-resolve vs pending       | [rules/roster_auto_resolve_behavior.md](rules/roster_auto_resolve_behavior.md)       |
| Embedding search evolution           | [rules/search_optimizations.md](rules/search_optimizations.md)                       |
| Detection vs identification boundary | [rules/why-identify-endpoint-exists.md](rules/why-identify-endpoint-exists.md)       |
| Face/Identity nomenclature (ADR)     | [ADR-001-face-identity-nomenclature.md](ADR-001-face-identity-nomenclature.md)       |
| MCP tooling / testing commands       | [BOOTSTRAP.md](BOOTSTRAP.md)                                                         |
| **Antigravity Agents (`/` cmds)**    | **See `.agent/workflows/` for environment-specific fallbacks and orchestration.**    |

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

- Do not relax compliance/lint scripts to silence violations. Fix the offending code.
- Every `composer`/`npm` gate script must succeed on invocation, not just be defined.
- **npm** for Node.js (not pnpm). **Composer** for PHP.
- When editing CSS/SCSS, use existing design tokens or `--acx-*` CSS custom properties for colors instead of raw hex literals. If a needed color token does not exist, add it to the shared token surface first.
- In TypeScript, use assertion helpers (`asserts value is ...`) for internal invariants and unreachable branches instead of `console.assert` or non-null assertions on API data. Do not use assertion helpers for request/input validation; validate boundary data explicitly.
- In Python, use `assert` only for narrow internal invariants during development and tests. Do not use `assert` for request validation, external data checks, or behavior that must always execute in production; raise explicit exceptions or HTTP errors instead.
- For a full local-only development reset of both databases, use `make reset-local WP_PATH="<wordpress>/app/public" CONFIRM_LOCAL_RESET="RESET"` from the repo root. `WP_PATH` must point to the WordPress directory containing `wp-load.php` (for LocalWP here, typically `/Users/daniel/Development/wp-context-alt-text/app/public`). Never use this against non-local environments.

### Cross-Branch Regression Guards

Hard guardrails from real failures in this project:

1. **No type-shim masking.** New import? Update `package.json`/`composer.json` and verify with a real build.
2. **Preserve atomic write paths.** Do not split a backend atomic operation into multiple frontend mutations.
3. **Primary controls reachable from zero state.** Never gate primary actions behind non-zero selection.
4. **Role semantics match behavior.** Controlled dialogs must wire `onOpenChange`.
5. **Schema/contract parity.** Validate SQL column names against real schema before merge.
6. **Documented commands must run as written.** Broken copy-paste syntax is a bug.

### Task Document Rules

- Consolidate all checklists at the **bottom** of task documents. No scattered `- [ ]` items. No time estimates.
- Planning docs must stay internally consistent (current state vs checklist vs success criteria vs ADR terms).
- When reviewing task plans, epics, roadmaps, ADRs, or other planning documents for gaps, bugs, obsolete assumptions, or unnecessary complexity, record every finding in MCP handoff before presenting it in chat.

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

### MCP Handoff Contract (MANDATORY)

You are one of multiple concurrent agents. MCP handoff tools are required for task state coordination.

Canonical handoff runtime:

- Use `agent-handoff-mcp` exclusively for handoff state.
- Do not use handoff tools or CLI subcommands from `scripts/mcp/unified_server.py`; they are deprecated and fail by design.
- The legacy unified server is now repo-intel-only.

Primary binary shape:

- `agent-handoff-mcp --workspace-root <repo> serve-stdio`
- `agent-handoff-mcp --workspace-root <repo> doctor`
- `agent-handoff-mcp --workspace-root <repo> state`
- `agent-handoff-mcp --workspace-root <repo> task <task_ref>`

Before any code exploration:

1. Call `get_handoff_state(task_ref="<task>")`.
2. If no active state exists, call `set_handoff_state(...)` to initialize it.
3. Do not use manual edits to `CURRENT_TASK.md` for state tracking.

During work:

1. Record non-trivial decisions with `record_decision(..., actor={ agent?, branch?, commit_sha? })`.
2. Add/update/complete task steps with `update_next_actions(..., actor={ ... })`.
3. Record blockers immediately with `report_blocker(..., actor={ ... })`.
4. Record verification commands with `record_test_result(..., actor={ ... })`.
5. Record/code-review findings with `record_review_finding(..., details={ line_start?, line_end?, fix? }, actor={ ... })`.
6. Update finding status with `update_review_finding(..., actor={ ... })`.
7. Validate review state using `get_review_findings_summary(...)` and `list_review_findings(...)` (not direct `sqlite3` queries).

Write-tool targeting rule:

- Write tools target the **active task only**.
- To write against a different task, switch active state first via `set_handoff_state(...)`.

Before final response:

1. Mark completed/skipped actions via `update_next_actions(...)`.
2. Update singleton state via `set_handoff_state(..., expected_revision=<current>, actor={ ... })`.
3. Regenerate `CURRENT_TASK.md` using `generate_current_task_md(...)`.
4. Include a one-line status marker in the response: `Handoff updated: yes`.

Read discipline:

- Do not query `.task-state/handoff.db` directly when MCP tools are available.
- Use `get_handoff_state` for active-task snapshot, `get_review_findings_summary` for counts, and `list_review_findings`/`get_review_finding` for detailed review verification.
- `get_review_finding` accepts either `finding_db_id` (integer PK) or `finding_id` (human-readable string like `"H-OCI-28"`). Prefer `finding_id` when referencing findings from review output.
- Do **not** use legacy `scripts/mcp/unified_server.py` handoff tools or CLI subcommands. The only supported handoff surface is the packaged `agent-handoff-mcp` binary described in [contracts/agent-handoff-mcp.md](contracts/agent-handoff-mcp.md).

State integrity invariants:

- Treat import/restore payloads as untrusted input. Validate payload shape and required object types before writes; malformed payloads must return `ok: false` (never silent success/no-op).
- Preserve write provenance on mutable records (for example review findings): creation metadata (`agent`, `branch`, `commit_sha`) is immutable once set; status updates may fill missing fields but must not overwrite recorded provenance.

Failure policy:

- If MCP handoff tools are unavailable, stop normal implementation work.
- Record/report the blocker, and include: `Handoff updated: no (tool unavailable)`.
- **Antigravity Agents ONLY**: Use predefined terminal commands in `.agent/workflows/` (e.g., `make task`, `make dashboard`) to query/orchestrate task state if native MCP tools are unconfigured. These CLI-style fallbacks exist only for MCP-constrained environments. Do not attempt raw SQLite writes.
- Use `templates/CURRENT_TASK.template.md` only as fallback when MCP handoff is unavailable.

Completion gate:

- A task response is incomplete if MCP handoff was not updated.

### Multi-Agent Worktree Orchestration (MANDATORY for delegated implementation)

Use this pattern when a user explicitly asks for parallel agents/worktrees, or when the task naturally splits into independent backend/frontend/PHP lanes with clear contracts.

Decomposition rules for the orchestrating agent:

1. Keep the orchestrator in the current repo root/branch. Worker agents implement in sibling Git worktrees on `codex/*` branches.
2. Split work only along stable seams: path ownership, API contract ownership, or test ownership. Do not delegate two workers to the same file set unless the user explicitly accepts merge churn.
3. Give each worker lane a bounded brief: objective, owned paths, required contracts/docs, required tests, explicit non-goals, and merge readiness criteria.
4. Keep shared plan/checklist truth centralized. The orchestrator owns final checklist updates, MCP review triage, cross-lane decisions, and merge order unless a worker is explicitly assigned one documentation block.
5. Prefer lanes that can be verified independently. Good seams in this repo are backend domain/schema, backend HTTP, WordPress proxy, frontend UI, and orchestrator-root review dispatch.
6. Treat workflow tooling as orchestrator-owned. When the root `Makefile`, lane helper scripts, or worker playbook changes, propagate them into worker lanes with `make lane-refresh` instead of hand-copying files.

Worktree setup and switching:

```bash
git worktree add ../context-alt-text-monorepo-<lane> -b codex/<task>-<lane>
git worktree list
cd ../context-alt-text-monorepo-<lane>
git status -sb
```

Preferred operator entrypoint:

```bash
make lane-open TASK=phase-5-retention-export-and-audit-controls LANE=frontend
```

That target creates or refreshes the worktree lane registration, prints the ready-to-paste worker brief, polls the lane inbox, and opens an interactive subshell in the worktree by default. Use `ENTER_SHELL=0` if you want setup without switching into the worker shell. Use `make lane-inbox`, `make lane-refresh`, `make lane-handoff`, and `make lane-reset` for the common follow-on operations.

- Create worktrees as siblings of the main repo, not nested inside it.
- Use lane names that match ownership (`backend-domain`, `backend-http`, `wp-proxy`, `frontend`).
- The orchestrator may inspect any lane without switching shells by using `git -C /abs/path/to/worktree status -sb` and `git -C /abs/path/to/worktree diff --stat`.
- If local dependency directories must be shared into a worker worktree, keep them ignored via local exclude config so they never appear in review or staging output.

Required domain boundaries per default Phase 5 lane split:

- `backend-domain`: only `apps/prototype-description-service/db/**`, `apps/prototype-description-service/recognition/domain/**`, `apps/prototype-description-service/recognition/infrastructure/**`, `apps/prototype-description-service/recognition/tests/unit/**`, `apps/prototype-description-service/scripts/reset_dev_db.sh`, and the active task plan when backend review findings require checklist or verification updates
- `backend-http`: only `apps/prototype-description-service/recognition/interface_adapters/http/**`
- `wp-proxy`: only `apps/prototype-wp-alt-context/src/**` and `apps/prototype-wp-alt-context/tests/Unit/**`
- `frontend`: only `apps/prototype-wp-alt-context/js/**`
- Shared docs/contracts/checklists remain orchestrator-owned unless a worker is explicitly assigned one documentation block

Domain guardrails for worker lanes:

1. Workers may edit only files inside their lane's owned paths.
2. If a required fix falls outside the lane's owned paths, record a blocker or lane message for the orchestrator instead of editing another domain.
3. Workers must not "helpfully" patch sibling-lane files, shared contracts, or checklist truth unless explicitly assigned.
4. Before handoff, workers should verify changed files with `git diff --name-only` from their worktree and confirm the list stays inside lane scope.
5. Orchestrators should reject or selectively intake any out-of-scope file changes during merge review.
6. Merge-ready worker handoff must be commit-based. Dirty worktrees are not a valid handoff artifact; commit or stash lane work before reporting it.
7. If a lane needs to catch up with orchestrator changes, use `make lane-refresh` instead of copying files across worktrees.
8. `make lane-refresh` now updates worker lanes from committed orchestrator branch state only. If root workflow tooling is still uncommitted, commit it on the orchestrator branch before refreshing workers.

How a worker self-queries its own lane and scope:

1. Assume lane identity is discoverable from MCP, not only from chat memory.
2. Query the shared handoff state and lane registry before doing substantive work:

```bash
agent-handoff-mcp --workspace-root <current-worktree> --state-dir <orchestrator>/.task-state --current-task-path <orchestrator>/CURRENT_TASK.md --exports-dir <orchestrator>/.task-state/exports state
agent-handoff-mcp --workspace-root <current-worktree> --state-dir <orchestrator>/.task-state --current-task-path <orchestrator>/CURRENT_TASK.md --exports-dir <orchestrator>/.task-state/exports lane-list --status all
agent-handoff-mcp --workspace-root <current-worktree> --state-dir <orchestrator>/.task-state --current-task-path <orchestrator>/CURRENT_TASK.md --exports-dir <orchestrator>/.task-state/exports lane-activity --lane-id <lane>
```

3. Use the returned `lane_id`, `branch`, `worktree_path`, notes, messages, and recent reports as the worker's source of truth for the current slice.
4. Preferred polling command: run `make lane-inbox` from the worker worktree. It shows open orchestrator-to-worker dispatch messages first, then the latest worker report, then lane activity and git status.
5. Preferred prompt bridge: run `make lane-prompt` to turn the current lane inbox into a concise actionable worker prompt. This is the stable interface for launching fresh worker sessions from MCP state.
6. If no lane exists for the current worktree, the orchestrator should create one with `lane-upsert` before implementation continues.
7. Workers should include `actor.lane_id` on MCP writes whenever possible so decisions, tests, blockers, actions, and findings remain attributable to the lane.

How workers communicate with the orchestrator:

1. Assume Codex sessions do **not** talk directly to one another. The canonical shared channels are MCP handoff state, Git branch/worktree state, and generated `CURRENT_TASK.md`.
2. Orchestrators should assign work with `make lane-dispatch TASK=<task> LANE=<lane> MESSAGE="..." [SUBJECT="..."]`. This records an open `orchestrator_to_worker` lane message and refreshes `CURRENT_TASK.md`.
3. Workers should poll `make lane-inbox`, not `CURRENT_TASK.md`, as their actionable inbox. `CURRENT_TASK.md` is a human-readable mirror only.
4. Agents performing review should do it from the orchestrator root, record findings in MCP handoff, and let the orchestrator route them with `make handoff-dispatch` so the owning worker lane sees both the dispatch message and the lane-stamped findings. The same command also stamps routeable open blockers and pending next actions onto their owning lanes.
5. At worker start, record a decision noting lane ownership and actor metadata (`agent`, `branch`, `commit_sha` when available). If the orchestrator assigned next actions, do not rewrite sibling lanes.
6. During work, record blockers, targeted test results, and review findings in MCP as they occur. Workers should report lane-local facts only; the orchestrator synthesizes cross-lane conclusions.
7. Before handing work back, record one decision summarizing:
   - files changed
   - tests run
   - assumptions made
   - blockers or follow-ups
   - whether the lane is merge-ready
8. Preferred worker command: run `make lane-handoff` from the worktree root (or any app Makefile -- they auto-forward all `lane-*` targets to root via a pattern rule). It verifies lane scope, stages the lane-owned paths, creates a default commit whose subject begins with the lane name, shows lane status, and then submits the merge-ready report using inferred `TASK`, `LANE`, and default `SESSION` values.
9. Worker handoff should be message-first. When a lane is merge-ready, `lane-handoff` now auto-sends an open `worker_to_orchestrator` lane message even if no explicit `MESSAGE` was passed.
10. When a lane needs further guidance, submit a worker report with `STATUS=blocked` and a summary or blocker text that explains the ask. This blocked guidance path is allowed even when no lane commits exist yet, which is the correct behavior for read-only sandboxes or environment failures. The worker report path auto-sends an open `worker_to_orchestrator` message for that guidance request.
11. When a slice is done but the overall task is not, update the lane status to `review`, submit a `lane-report --merge-ready`, and let the orchestrator intake it. Do **not** mark the whole task `done`.
12. Workers do not close the overall implementation task unless they are explicitly acting as the orchestrator. They close only their assigned actions/findings.
13. When a worker receives review work through MCP, the open lane message is the assignment and the lane-stamped open review findings are the actionable checklist. Fix or disposition those findings in-lane before handing work back.

How the orchestrator should monitor and delegate:

1. Create or reuse the active MCP task before opening worker lanes.
2. Record lane assignments in MCP decisions/next actions with the owning branch and worktree path.
3. Dispatch worker instructions through lane messages with `make lane-dispatch ...`; do not rely on chat memory alone.
4. Poll worker handoff messages from the orchestrator root with `make handoff-inbox TASK=<task-ref>`. That inbox is the canonical place to see merge-ready handoffs and worker guidance requests across lanes.
5. Perform code reviews from the orchestrator root, log findings into MCP handoff, then run `make handoff-dispatch TASK=<task-ref>` so routeable open findings, blockers, and next actions are routed to the correct worker lanes.
6. Review each worker branch against [rules/branch-review-guide.md](rules/branch-review-guide.md) before intake.
7. Merge lanes in dependency order: schema/domain before HTTP, backend contract before WordPress proxy, proxy before frontend, then run cross-lane integration checks in the orchestrator root.
8. After each accepted lane, regenerate `CURRENT_TASK.md` so the next worker sees current state without reading every branch diff.
9. Keep the orchestrator root clean. If `git status` is dirty, do not intake. Stash or commit root-local work first.
10. If a lane becomes stale, refresh the whole lane with `make lane-refresh` instead of manually copying individual files into the worktree.

How to merge worker worktree changes into the current branch:

Preferred whole-slice intake:

```bash
git -C ../context-alt-text-monorepo-<lane> log --oneline --decorate -n 5
git cherry-pick <worker-commit-sha>
```

Preferred automated intake from the orchestrator root:

```bash
make lane-commits TASK=phase-5-retention-export-and-audit-controls LANE=backend-domain
make lane-intake TASK=phase-5-retention-export-and-audit-controls LANE=backend-domain
```

- `make lane-commits` previews the commits on the lane branch that are not yet on the current orchestrator branch.
- `make lane-intake` prints the latest merge-ready worker report, stages the intake in a scratch worktree, runs lane-local verification there, and only fast-forwards the orchestrator branch if the scratch intake is clean.
- Conflicts during `lane-intake` must leave the orchestrator root untouched. Resolve them in the lane after `make lane-refresh`, not by hand in the orchestrator branch.
- Use `DRY_RUN=1` on `make lane-intake` to preview the exact scratch-intake flow before applying it.
- Run these only from the orchestrator root, never from a worker worktree.

Worktree maintenance helpers:

```bash
make lane-refresh TASK=phase-5-retention-export-and-audit-controls LANE=backend-http
make lane-clean TASK=phase-5-retention-export-and-audit-controls LANE=backend-http
```

- `make lane-refresh` syncs a worker lane against the current orchestrator branch. If the lane has no unique commits, it hard-resets to orchestrator `HEAD`; otherwise it rebases the lane commits onto orchestrator `HEAD`. Dirty lane state is auto-stashed before refresh and auto-popped afterward; if the pop conflicts, the stash is preserved and a warning is printed. It does not copy live files from the orchestrator working tree into the lane.
- If you change lane workflow docs or helper tooling in the orchestrator root, commit those changes on the orchestrator branch first, then run `make lane-refresh TASK=<task> LANE=<lane>` so workers pick them up cleanly through git.
- `make lane-refresh` refuses to run when orchestrator workflow tooling is locally dirty. That is intentional: worker lanes should stay clean and should not inherit uncommitted root tooling edits.
- `make lane-clean` removes legacy copied tooling drift (Makefiles, templates, helper scripts) from a worker lane without touching lane-owned product files.
- `make lane-commit` still ignores those tooling paths during its out-of-scope guard so older lane refreshes do not block product commits.
- `make lane-inbox` is the worker polling command. It reads open `orchestrator_to_worker` lane messages from MCP, then shows the latest worker report, recent lane activity, and git status.
- `make lane-prompt` renders the actionable lane inbox as a deterministic worker prompt. Use it when starting or re-starting a worker session from current MCP state.
- `make lane-run` launches a fresh `codex exec` in the lane worktree using that generated prompt. It now expects a structured final handoff payload from the worker and auto-submits either `make lane-handoff` or a blocked `make lane-report` based on that result. This is the robust automation path because it avoids trying to inject text into an already-running interactive session and avoids hand-copying blocked-report text.
- `make handoff-inbox` is the orchestrator polling command. It reads open `worker_to_orchestrator` lane messages from MCP and the latest merge-ready or blocked worker reports across lanes.
- `make lane-dispatch` is the orchestrator assignment command. It writes an open lane message for a specific worker lane and regenerates `CURRENT_TASK.md` so the dispatch is mirrored for humans.
- `make handoff-dispatch` is the orchestrator handoff-routing command. It reads open handoff review findings, blockers, and next actions from the root, stamps any routeable unassigned items onto the owning lane, and sends lane messages so the correct worktree sees the queue in `make lane-inbox`.
- `make review-dispatch` remains as a compatibility alias when older docs or sessions still refer to the review-only name.

Selective file intake when a worker branch contains extra churn:

```bash
git checkout codex/<task>-<lane> -- path/to/file1 path/to/file2
git status -sb
```

- Prefer `git cherry-pick` for coherent reviewed commits.
- Use `git checkout <branch> -- <paths>` only when intentionally taking a subset of a lane.
- Never copy files by hand between worktrees.
- After intake, run the lane's required tests from the orchestrator root, then update MCP decisions/actions/findings and regenerate `CURRENT_TASK.md`.

How `agent-handoff-mcp` helps this process today:

- It provides the single active task, next-action queue, blocker log, decision log, review findings, and test history across independent sessions.
- It makes worker reports queryable without opening each worktree first.
- It lets the orchestrator verify that review findings are actually closed before merge.
- It keeps `CURRENT_TASK.md` as a generated summary for humans and newly opened agent sessions, including a mirrored lane-dispatch section. Workers should still poll MCP via `make lane-inbox` for actionable assignments.

Recommended Codex skills for this workflow:

- `worktree-orchestrator`: decompose a plan into lanes, create worker briefs, assign merge order, and prepare integration checks.
- `worktree-worker`: self-query lane scope, implement only the delegated slice, and hand the lane back with a merge-ready report.
- `commit2git`: split the current dirty branch into completed sub-feature commits and prefix commit subjects with the worktree name when operating from a linked worktree.
- Merge intake remains orchestrator-owned and is executed through the review/merge steps above plus `scripts/worktree-lane`.

Repo-owned skill sources and templates:

- skill sources live under [docs/agentic/skills/](skills/)
- brief/report templates live under [docs/agentic/templates/](templates/)
- `scripts/worktree-lane` is the supported helper for creating lanes, rendering briefs, self-querying lane scope, and submitting worker reports/messages
- the root [Makefile](../Makefile) provides task-aware wrappers that enumerate the supported lanes and their default scope/tests

Operational note:

- Repo-owned skills are versioned here so they can be reviewed and evolved with the codebase.
- If you want auto-discoverable Codex skills in `$CODEX_HOME/skills`, install or symlink these repo-owned skill folders there manually; do not maintain a second divergent copy.

Current `agent-handoff-mcp` capabilities that support this workflow:

- worktree lane records with `lane_id`, `worktree_path`, `branch`, `owner_agent`, and `status`
- worker reports that link changed files, test commands, blockers, and merge readiness to a specific lane
- lane-scoped activity queries so the orchestrator can inspect one worker lane without sifting the full task history
- explicit lane messages for orchestrator-to-worker and worker-to-orchestrator communication when sessions cannot chat directly

Still-useful future `agent-handoff-mcp` improvements:

- a first-class orchestrator brief artifact so worker prompts can be generated and tracked without manual copy/paste
- lane-scoped dashboard rollups and close-check rules for tasks that intentionally stay split across multiple long-lived worktrees

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
5. Call `record_review_finding(..., details={ line_start?, line_end?, fix? }, actor={ ... })` for each finding.
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
