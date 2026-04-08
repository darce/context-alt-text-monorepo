# Development Instructions

> **Cold-start dispatcher for coding agents.** Full protocol: [docs/agentic/instructions.md](docs/agentic/instructions.md).

**Active epics**: `docs/epics/v0.4.0/public-demo-launch-readiness-epic.md` (E15) · `docs/epics/v0.3.1/self-hosting-epic.md` (E14)

---

## Agent Startup Protocol

On every session (cold start, mid-task re-entry, lane inherit):

1. **Run `make context`** to verify your shell is in the right worktree on the right branch. The script reads `target_worktree_path` and `target_branch` from the active task and exits non-zero on drift. **Do not record any handoff state from a drifted shell.** If you see a drift warning, `cd` to the canonical path before continuing.
2. Query MCP handoff state: `get_handoff_state(sections="identity")` for routine task checks; full `get_handoff_state(task_ref="<task>")` only for hot-state load.
3. If in a lane, run `make lane-inbox` to pick up routed findings and dispatch messages.
4. Load role routing below; read the linked context map, guidelines, and testing guide.
5. Check open findings: `review_findings(review={"operation":"list","status":"open"})`.
6. Verify contract surface before writing code ([contracts/](docs/agentic/contracts/)).
7. Decide whether `ctx7` is needed (upstream library behavior; see ctx7 criteria in instructions.md).
8. Ensure the work has an MCP task. If no active task fits, initialize one with `make task-start TASK=<id> OBJECTIVE="..."` (single command: creates feature branch + linked worktree + MCP task with `target_worktree_path` populated).
9. If starting a task plan, create its target branch from `main` and activate via `switch_task`. See [planning pipeline](docs/agentic/rules/planning-pipeline.md) for the full workflow.

If MCP unavailable: read `CURRENT_TASK.md` as stale fallback. Record blocker when access returns. **Stop implementation work until MCP is available.**

---

## Role Selection

| Role                            | Context Map                                                    | Guidelines                                                                            | Testing Guide                                                           | Tech Stack                                                                              | Key Entry Points                      |
| ------------------------------- | -------------------------------------------------------------- | ------------------------------------------------------------------------------------- | ----------------------------------------------------------------------- | --------------------------------------------------------------------------------------- | ------------------------------------- |
| **Backend (Python)**            | [maps/backend.md](docs/agentic/maps/backend.md)                | [rules/backend-python-guidelines.md](docs/agentic/rules/backend-python-guidelines.md) | [rules/testing-python.md](docs/agentic/rules/testing-python.md)         | [maps/tech-stack.md#backend-python](docs/agentic/maps/tech-stack.md#backend-python)     | `apps/prototype-description-service/` |
| **Frontend (React/TS)**         | [maps/frontend.md](docs/agentic/maps/frontend.md)              | [rules/frontend-guidelines.md](docs/agentic/rules/frontend-guidelines.md)             | [rules/testing-typescript.md](docs/agentic/rules/testing-typescript.md) | [maps/tech-stack.md#frontend-reactts](docs/agentic/maps/tech-stack.md#frontend-reactts) | `apps/prototype-wp-alt-context/js/`   |
| **PHP Plugin**                  | [maps/php-plugin.md](docs/agentic/maps/php-plugin.md)          | [rules/backend-php-guidelines.md](docs/agentic/rules/backend-php-guidelines.md)       | [rules/testing-php.md](docs/agentic/rules/testing-php.md)               | [maps/tech-stack.md#php-plugin](docs/agentic/maps/tech-stack.md#php-plugin)             | `apps/prototype-wp-alt-context/src/`  |
| **Cross-Service Integration**   | [maps/integration.md](docs/agentic/maps/integration.md)        | [contracts/](docs/agentic/contracts/)                                                 | [rules/testing-principles.md](docs/agentic/rules/testing-principles.md) | [maps/tech-stack.md#orchestration](docs/agentic/maps/tech-stack.md#orchestration)       | `docs/agentic/contracts/`             |
| **Infrastructure / Deployment** | [self-hosting-epic.md](docs/epics/v0.3.1/self-hosting-epic.md) | [development-workflow.md](docs/agentic/rules/development-workflow.md)                 | [testing-principles.md](docs/agentic/rules/testing-principles.md)       | [maps/tech-stack.md#orchestration](docs/agentic/maps/tech-stack.md#orchestration)       | `infra/oci/`                          |

Additional routing: see [docs/agentic/instructions.md](docs/agentic/instructions.md#additional-routing).

---

## Critical Rules

### Pre-Merge Gate Rule

> **No feature branch merges to `main` without a passing `handoff_close_check(enforce=True)`.**

Every merge to `main` requires: (1) at least one review pass with findings recorded in MCP, (2) zero open findings on the task ref, (3) fresh `test_result` evidence tied to the current HEAD SHA, (4) `handoff_close_check(enforce=True)` passes, and (5) a slice-complete decision recorded. The check is enforced by the handoff DB; bypassing it via `enforce=False` defeats the gate. Open findings must be `fixed` or explicitly `deferred`/`wontfix` with rationale — never skipped.
See [development-workflow.md § Pre-Merge Gate](docs/agentic/rules/development-workflow.md#pre-merge-gate-mandatory) for the full pre-merge sequence and recovery steps.

### Branch Isolation Rule

> **Code files must NOT be edited on the `main` branch.**

A `PreToolUse` hook enforces this in both harnesses: VS Code runs `.github/hooks/guard-main-branch.py` via `.github/hooks/terminal-guard.json`, and Claude Code runs `scripts/hooks/guard-main-branch.sh` via `.claude/settings.json`. Code-file edits under `apps/` or `packages/` are blocked on `main`. Create a feature branch (`git checkout -b feature/<task-id>-<slug>`) before any code edit. Docs, configs, and planning artifacts are allowed on `main`.

**Worktree rule:** The root worktree stays on `main`. Always. Never check out `main` in a linked worktree. After merging a feature branch, return the root to `main` and delete the merged branch.

**Worktree naming convention** (mandatory for new tasks): `<repo-parent>/context-alt-text-monorepo-<lowercase-task-id>` paired with branch `feature/<lowercase-task-id>`. Examples: task `AHMCP-9` → worktree `context-alt-text-monorepo-ahmcp-9` on branch `feature/ahmcp-9`. The `make task-start TASK=<id>` helper enforces this convention and registers `target_worktree_path` on the active handoff state in one shot. The `make task-finish TASK=<id>` helper performs the post-merge teardown (worktree remove + branch delete + MCP archive).

**Context discipline for multi-agent flows:** Run `make context` at the start of every session to verify your shell is on the right `target_worktree_path` and `target_branch`. The `set_handoff_state` and `record_decision` write paths emit `context_drift` warnings (non-fatal) when actor branch or cwd diverges from the active task target — read those warnings and fix the drift before recording further events.

See [development-workflow.md](docs/agentic/rules/development-workflow.md#branch-isolation-protocol-mandatory) for isolation tiers, worktree recovery, and rationale.

### Plugin Boundary Rule

> **You may ONLY modify files within this monorepo.**

Allowed: `apps/prototype-wp-alt-context/`, `apps/prototype-description-service/`, `packages/` (only package directories present in this checkout), `docs/`, `scripts/`.
Treat the standalone `darce/mcp-agent-handoff` repo as out of bounds unless the workspace is opened there directly. `agent-handoff-mcp` no longer lives in this monorepo checkout.
Never modify WordPress core, LocalWP config, `~/Local Sites/`, or system config files.

### Greenfield Policy

This project has NO production users and NO existing data to preserve.

- No data migrations. Schema changes go directly in `001_identity_schema.py`.
- Clean rewrites over backward-compatibility shims. Delete-over-flag.

### MCP Handoff (MANDATORY)

- Every code change must be logged with a `record_event(event={event_kind: "decision", actor: {...}, ...})` entry before review or completion.
- After recording the decision, notify the user that the handoff has been updated (e.g. "Handoff updated: decision `<id>` recorded."). This notification is mandatory — a response that makes code changes without both recording and notifying is incomplete.
- A task response is incomplete if MCP handoff was not updated.
- When a task is finished, set status to `done` via `update_task_status(task_ref=..., status="done")` before or after archiving. `close_slice` keeps status `in_progress` — it does not close the task. `archive_task_state` preserves whatever status the task had; archiving while `in_progress` leaves the dashboard permanently stale.
- Slice completion format (enforced at write time): [docs/agentic/templates/slice-complete-template.md](docs/agentic/templates/slice-complete-template.md).
- After every state-changing handoff operation (`record_event`, `review_findings(operation="update")`, `review_findings(operation="batch_record")`), call `generate_current_task_md(task_ref=<active-task-ref>)`.
- When logging **3 or more review findings** in a single review pass, use `review_findings(review={"operation":"batch_record", ...})` instead of repeated `review_findings(review={"operation":"record", ...})` calls — one atomic write, one `CURRENT_TASK.md` flush, per-item results returned.
- Full handoff protocol: [docs/agentic/instructions.md](docs/agentic/instructions.md#mcp-handoff-contract-mandatory).

### Git Commit Rules

- **NEVER add `Co-Authored-By` trailers or any AI/model attribution to git commit messages.** This is a mandatory, permanent rule. Violations require history rewrite.

### Short Rules

- [sr-001] helpful=2 harmful=0 :: Do not relax compliance/lint scripts to silence violations. Fix the offending code.
- [sr-002] helpful=1 harmful=0 :: Every `composer`/`npm` gate script must succeed on invocation, not just be defined.
- [sr-003] helpful=1 harmful=0 :: **npm** for Node.js (not pnpm). **Composer** for PHP.
- [sr-004] helpful=2 harmful=0 :: CSS/SCSS: use `--acx-*` design tokens. No hex literals. Status indicators must pair color with an icon.
- [sr-005] helpful=2 harmful=0 :: TypeScript: use assertion helpers (`asserts value is ...`) for internal invariants. Not for request/input validation.
- [sr-006] helpful=1 harmful=0 :: Python: `assert` only for narrow internal invariants. Raise explicit exceptions for request validation and production behavior.
- [sr-007] helpful=2 harmful=0 :: Centralize domain status values as enums or `as const`. No scattered magic string comparisons.
- [sr-008] helpful=1 harmful=0 :: More than 8 destructured parameters? Group into 2-3 cohesive typed objects.
- [sr-009] helpful=1 harmful=0 :: PHP transaction methods must use a shared `run_transactional(callable)` wrapper.
- [sr-010] helpful=1 harmful=0 :: Local reset: `make reset-local WP_PATH="<wordpress>/app/public" CONFIRM_LOCAL_RESET="RESET"`. Never against non-local environments.

### Cross-Branch Regression Guards

- [rg-001] helpful=1 harmful=0 :: No type-shim masking. New import? Update `package.json`/`composer.json` and verify with a real build.
- [rg-002] helpful=1 harmful=0 :: Preserve atomic write paths. Do not split a backend atomic operation into multiple frontend mutations.
- [rg-003] helpful=1 harmful=0 :: Primary controls reachable from zero state. Never gate primary actions behind non-zero selection.
- [rg-004] helpful=1 harmful=0 :: Role semantics match behavior. Controlled dialogs must wire `onOpenChange`.
- [rg-005] helpful=1 harmful=0 :: Schema/contract parity. Validate SQL column names against real schema before merge.
- [rg-006] helpful=1 harmful=0 :: Documented commands must run as written. Broken copy-paste syntax is a bug.
- [rg-007] helpful=1 harmful=0 :: Long-running loops: bounded stall detection. A single unit's failure must not halt other units.
- [rg-008] helpful=1 harmful=0 :: Config files: validate at load time. Fail fast on missing or malformed required keys.
- [rg-009] helpful=1 harmful=0 :: No task-specific logic in generic modules. Extract to config-driven policy or the task's manifest.
- [rg-010] helpful=1 harmful=0 :: IDE tool output may be stale after external writes (git rebase, worktree ops). Cross-check with terminal before recording a finding.
- [rg-013] helpful=1 harmful=0 :: `core.py` must remain pure handoff-state CRUD. No orchestration imports, no subprocess calls, no lock management. Scope: the active `agent-handoff-mcp` checkout, whether that is the transitional in-repo copy during extraction work or the standalone checkout opened directly.
- [rg-014] helpful=1 harmful=0 :: Orchestration modules must use late-binding imports (function-level) for `agent_handoff_mcp` symbols.
- [rg-015] helpful=1 harmful=0 :: Boundary adapters must not invent contract metadata. Every envelope field must come from the request, upstream payload, or an explicitly documented fallback.
- [rg-016] helpful=0 harmful=0 :: PHP runtime autoload parity must match tests. Verify with `php -r "require 'vendor/autoload.php'; var_export(class_exists(...));"`.

---

## Naming Conventions

| Surface                        | Prefix        | Example                          |
| ------------------------------ | ------------- | -------------------------------- |
| WordPress options/meta         | `acx_*`       | `acx_persons`, `acx_version`     |
| PHP constants (plugin-defined) | `ACX_*`       | `ACX_PLUGIN_FILE`, `ACX_VERSION` |
| PHP constants (deployment)     | `ACX_*`       | `ACX_RECOGNITION_URL`            |
| REST API namespace             | `acx/v1/`     |                                  |
| PHP namespace                  | `AltContext\` |                                  |
| Text domain / slug             | `alt-context` |                                  |
| Filter hooks                   | `acx_*`       | `acx_recognition_base_url`       |

> The `cat_*` and `alt_context_*` prefixes are **legacy**. Update to `acx_*` on encounter.

Epic titles: `E<number>. <Title>` · Task plans: `<EpicShortID>-<N>. <Title>` · Slice decisions: `<author_tag>_slice_complete_<work_ref>_<slug>`

---

## Key Triggers

**Branch review**: load [rules/branch-review-guide.md](docs/agentic/rules/branch-review-guide.md) when request matches: "review" + (implementation|code|changes|branch|PR|diff), "audit" + (branch|code), "propose improvements", "flag gaps/bugs".

**Planning review**: load [rules/planning-review-guide.md](docs/agentic/rules/planning-review-guide.md) when request matches: "review" + (task plan|epic|roadmap|ADR|planning document), "flag issues/gaps/obsolete assumptions" on a `docs/` file, "audit" + (plan|epic|roadmap).

Do NOT perform ad-hoc reviews. Both guides enforce structured, MCP-visible output.
