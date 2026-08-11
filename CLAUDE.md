# Development Instructions

> **Cold-start dispatcher for coding agents.** Full protocol: [docs/workbay/instructions.md](docs/workbay/instructions.md).

**Active epics**: `docs/epics/v0.4.0/public-demo-launch-readiness-epic.md` (E15) · `docs/epics/v0.3.1/self-hosting-epic.md` (E14)

---

## Agent Startup Protocol

On every session (cold start, mid-task re-entry, lane inherit):

0. **Identify the task first.** Before `make context` or any MCP read that resolves the active task by cwd, decide which task owns this scope:
   - **Existing feature-branch task (resumption):** proceed to step 1 from inside the task's `target_worktree_path`.
    - **Ad-hoc / new work on `main` (e.g. `/branch-review`, audits, patches):** run `make maint-start TASK=MAINT-<slug>-<YYYYMMDD> OBJECTIVE="..."` FIRST. It registers the task against the repo root so later reads do not depend on cwd-only resolution. (`SLUG=` is the repo-local wrapper's signature; the shipped `Makefile.d/lifecycle.mk` overrides that target and requires `TASK=`.)
   - **Ambiguous errors on startup** (`Ambiguous active task. Known task_refs: ...`) mean step 0 was skipped: either create/select the task_ref and pass it explicitly, or archive stale MAINT-* rows in one shot with `make maint-archive-stale` (add `MAINT_ARCHIVE_ARGS="--yes"` to skip the interactive prompt). `make context` also exits `2` (distinct from infra error `1`) on this ambiguity and prints the same hint.
1. **Run `make context`** in a standalone shell call. It verifies branch/worktree alignment and prints a small startup summary (active task identity, open findings count, role-routing reminder). Do not batch it with MCP loading or other startup commands. If you see a drift warning, `cd` to the canonical path before continuing.
2. **Apply the [MCP Loading Protocol](docs/workbay/rules/mcp-loading-protocol.md)** before fetching state. Read [`docs/workbay/maps/mcp-tool-routing.yaml`](docs/workbay/maps/mcp-tool-routing.yaml) and surface only the MCP servers whose triggers match the current prompt / task scope. `workbay-handoff-mcp` is always loaded; `workbay-orchestrator-mcp` and `computer-use` are on-demand. Concretely on Claude Code: `ToolSearch select:mcp__<server>__*` to surface a deferred server when its triggers fire.
3. **If in a lane, run `make lane-inbox`.** Pick up routed findings and dispatch messages before editing.
4. **Load role routing below.** Use the Role Selection table that `make context` points you at.
5. **Verify boundaries only when relevant.** Check contracts for schema/service/MCP boundary changes.
6. **Ensure the work has the right MCP task.** Planning artifacts still require branch isolation from the first file edit — run `make task-start TASK=<id> OBJECTIVE="..."` before writing scope notes, assessments, specs, ADRs, or task plans so the branch + worktree + MCP target exist up front.

If MCP tool calls unavailable (ToolSearch returns nothing for `mcp__workbay-handoff-mcp__*`), or if you need a query the MCP tools don't directly expose: **use the Python API via Bash as the primary fallback.**

For Python-API fallback writes (`record_event`, `review_findings`, `set_handoff_state`, `update_task_status`, `close_slice`), always run them from the owning worktree with an explicit `cd <target_worktree_path> && ...` prefix and pass `task_ref='<task-ref>'` in the write call. The provenance guard rejects fallback writes that omit the explicit worktree `cd` or the explicit task ref because the Bash tool path otherwise cannot validate branch/SHA attribution before the write lands.

> **Canonical source:** [`docs/workbay/contracts/harness-protocol.yaml`](docs/workbay/contracts/harness-protocol.yaml) `python_api_fallback.required_exports` is the authoritative list of package-root symbols every harness must keep importable. The example below is a practical superset used in this repo; the contract defines the minimum surface. If the two drift, fix the contract first, then re-sync both harness docs (CLAUDE.md and `.github/copilot-instructions.md`).

Always import from the package root — never from submodules (`.config`, `.decisions`, `.core` are internal):

```python
from pathlib import Path
from workbay_handoff_mcp import (
    RuntimeConfig, configure_runtime,          # setup (call configure_runtime first)
    get_handoff_state, search_handoff,          # read state
    record_event, record_decision,              # write decisions
    review_findings, list_review_findings,      # findings CRUD
    list_review_runs, record_review_run,        # review runs
    set_handoff_state, update_task_status,      # task lifecycle
    get_verified_tests, generate_dashboard_md,  # queries and rendering
)
configure_runtime(RuntimeConfig.for_repo(Path(".")))
```

When the missing surface is specifically review-run writes, prefer the repo-local wrapper over ad-hoc snippets: `make handoff-review-run TASK_REF=<task-ref> MODE=<branch|planning|release_audit> SUBJECT=<path-or-.> SUBJECT_KIND=<task_plan|epic|branch|adr|roadmap|other> VERDICT=<pass|pass_with_findings|fail|conditional_pass> DECISION=<decision-id> SESSION=<session> RUN_ID=<run-id>`. The target records the review run through the Python API fallback and refreshes `DASHBOARD.txt` plus `CURRENT_TASK.json`.

Never use raw `sqlite3` to query `handoff.db` directly; the schema is internal and will break. `DASHBOARD.txt` is a last-resort stale read only when the Python package itself is also unavailable. `CURRENT_TASK.json` = optional task-scoped export only if an explicit render wrote it; do not assume it exists or is current. Record a blocker when Claude Code MCP tool access does not restore after session restart. **Stop implementation work until at least the Python API is available.**

---

## Role Selection

| Role                            | Context Map                                                    | Guidelines                                                                            | Testing Guide                                                           | Tech Stack                                                                              | Key Entry Points                      |
| ------------------------------- | -------------------------------------------------------------- | ------------------------------------------------------------------------------------- | ----------------------------------------------------------------------- | --------------------------------------------------------------------------------------- | ------------------------------------- |
| **Backend (Python)**            | [maps/backend.md](docs/workbay/maps/backend.md)                | [rules/backend-python-guidelines.md](docs/workbay/rules/backend-python-guidelines.md) | [rules/testing-python.md](docs/workbay/rules/testing-python.md)         | [maps/tech-stack.md#backend-python](docs/workbay/maps/tech-stack.md#backend-python)     | `apps/prototype-description-service/` |
| **Frontend (React/TS)**         | [maps/frontend.md](docs/workbay/maps/frontend.md)              | [rules/frontend-guidelines.md](docs/workbay/rules/frontend-guidelines.md)             | [rules/testing-typescript.md](docs/workbay/rules/testing-typescript.md) | [maps/tech-stack.md#frontend-reactts](docs/workbay/maps/tech-stack.md#frontend-reactts) | `apps/prototype-wp-alt-context/js/`   |
| **PHP Plugin**                  | [maps/php-plugin.md](docs/workbay/maps/php-plugin.md)          | [rules/backend-php-guidelines.md](docs/workbay/rules/backend-php-guidelines.md)       | [rules/testing-php.md](docs/workbay/rules/testing-php.md)               | [maps/tech-stack.md#php-plugin](docs/workbay/maps/tech-stack.md#php-plugin)             | `apps/prototype-wp-alt-context/src/`  |
| **Cross-Service Integration**   | [maps/integration.md](docs/workbay/maps/integration.md)        | [contracts/](docs/workbay/contracts/)                                                 | [rules/testing-principles.md](docs/workbay/rules/testing-principles.md) | [maps/tech-stack.md#orchestration](docs/workbay/maps/tech-stack.md#orchestration)       | `docs/workbay/contracts/`             |
| **Infrastructure / Deployment** | [self-hosting-epic.md](docs/epics/v0.3.1/self-hosting-epic.md) | [development-workflow.md](docs/workbay/rules/development-workflow.md)                 | [testing-principles.md](docs/workbay/rules/testing-principles.md)       | [maps/tech-stack.md#orchestration](docs/workbay/maps/tech-stack.md#orchestration)       | `infra/oci/`                          |

Additional routing: see [docs/workbay/instructions.md](docs/workbay/instructions.md#additional-routing).

---

## Critical Rules

### Output Brevity Rule

> **Extremely concise user reports. Sacrifice grammar for concision. Strip filler. State the result, not the journey.** Verbosity degrades reasoning accuracy ([Hakim 2025](https://arxiv.org/html/2604.00025v1)).

- Chat: one sentence per update. ≤2 sentence summary. No preamble.
- Handoff: decision first. ≤1,500 chars. Cut recaps.
- Findings: one paragraph — evidence + impact.
- Code comments: default zero. WHY only.
- Removable without info loss? Remove it. Lists over paragraphs.
- Planning docs need completeness — still cut filler.

Full surface table: [instructions.md § Output Brevity](docs/workbay/instructions.md#output-brevity-mandatory).

### Pre-Merge Gate Rule

> **No feature branch merges to `main` without a passing `handoff_close_check(enforce=True)`.**

Every merge to `main` requires: (1) at least one review pass with findings recorded in MCP, (2) zero open findings on the task ref, (3) fresh `test_result` evidence tied to the current HEAD SHA, (4) `handoff_close_check(enforce=True)` passes, and (5) a slice-complete decision recorded. The check is enforced by the handoff DB; bypassing it via `enforce=False` defeats the gate. Open findings must be `fixed` or explicitly `deferred`/`wontfix` with rationale — never skipped.
See [development-workflow.md § Pre-Merge Gate](docs/workbay/rules/development-workflow.md#pre-merge-gate-mandatory) for the full pre-merge sequence and recovery steps.

### Branch Isolation Rule

> **Code files must NOT be edited on the `main` branch.**

A `PreToolUse` hook enforces this in both harnesses: VS Code runs `.github/hooks/guard-main-branch.py` via `.github/hooks/terminal-guard.json`, and Claude Code runs `scripts/hooks/guard-main-branch.sh` via `.claude/settings.json`. Protected code files and planning docs are blocked on `main`. Create a feature branch (`git checkout -b feature/<task-id>-<slug>`) before any planning or code edit. Only explicitly permitted operator docs/config surfaces remain allowed on `main`.

**Worktree rule:** The root worktree stays on `main`. Always. Never check out `main` in a linked worktree. After merging a feature branch, return the root to `main` and delete the merged branch.

**Worktree naming convention** (mandatory for new tasks): `<repo-parent>/context-alt-text-monorepo-<lowercase-task-id>` paired with branch `feature/<lowercase-task-id>`. Examples: task `AHMCP-9` → worktree `context-alt-text-monorepo-ahmcp-9` on branch `feature/ahmcp-9`. The `make task-start TASK=<id>` helper enforces this convention and registers `target_worktree_path` on the active handoff state in one shot. The `make task-finish TASK=<id>` helper performs the post-merge teardown (worktree remove + branch delete + MCP archive).

**Main-branch maintenance-task rule** (mandatory): before any permitted file edit on `main` (docs, Makefiles, configs, scripts), verify an active handoff task is registered. For ad-hoc patches use the maintenance-task pattern: `set_handoff_state(task_ref='MAINT-<slug>', objective='Describe the main-branch patch', status='in_progress')`. Unregistered permitted edits trigger a warning from the main-branch hook.

**Context discipline for multi-agent flows:** Run `make context` at the start of every session to verify your shell is on the right `target_worktree_path` and `target_branch`. The `set_handoff_state` and `record_decision` write paths emit `context_drift` warnings (non-fatal) when actor branch or cwd diverges from the active task target — read those warnings and fix the drift before recording further events.

See [development-workflow.md](docs/workbay/rules/development-workflow.md#branch-isolation-protocol-mandatory) for isolation tiers, worktree recovery, and rationale.

### Plugin Boundary Rule

> **You may ONLY modify files within this monorepo.**

Allowed: `apps/prototype-wp-alt-context/`, `apps/prototype-description-service/`, `packages/` (only package directories present in this checkout), `docs/`, `scripts/`.
Treat the standalone `darce/mcp-workbay-handoff` repo as out of bounds unless the workspace is opened there directly. `workbay-handoff-mcp` no longer lives in this monorepo checkout.
Never modify WordPress core, LocalWP config, `~/Local Sites/`, or system config files.

### Greenfield Policy

This project has NO production users and NO existing data to preserve.

- No data migrations. Schema changes go directly in `001_identity_schema.py`.
- Clean rewrites over backward-compatibility shims. Delete-over-flag.

### Commit SHA Provenance Discipline

> **Pass full 40-character SHAs from `git rev-parse` to every handoff `commit_sha` field. Never type SHA suffixes from memory.**

Whenever a handoff write accepts a `commit_sha` (`record_event(actor=...)`, `set_handoff_state(actor=...)`, `close_slice(actor=...)`, `update_review_finding(verified_commit_sha=...)`, `handoff_close_check(current_commit_sha=...)`, etc.), pass the canonical 40-character SHA from `git rev-parse <abbrev>` or `git rev-parse HEAD`. Never type the suffix from memory after seeing a 7-char abbreviation in `git commit` output.

**Enforcement:** The MCP write path validates every `commit_sha` against the active git repo via `git rev-parse --verify <sha>^{commit}` and rejects fabricated SHAs with an `InvalidCommitShaError`. Abbreviated SHAs (4–40 hex chars) that resolve uniquely are auto-expanded to the full 40-char form before storage, so callers may pass `bb24ee59` and the audit trail records `bb24ee5945273ebc4663b6d264023d9542823310`. Validation is bypassed in test sessions via `AGENT_HANDOFF_SKIP_SHA_VALIDATION=1` (set automatically by both packages' `tests/conftest.py`); production callers always run with validation enabled.

See [docs/workbay/rules/testing-python.md § Commit SHA Provenance Discipline](docs/workbay/rules/testing-python.md#commit-sha-provenance-discipline-mandatory) for the full rationale and the AHMCP-10/AHMCP-11 audit-trail bug that motivated the enforcement.

### MCP Write Branch Enforcement

> **MCP write operations are blocked when the actor branch does not match the active task's `target_branch`.** Switch to the canonical worktree before recording decisions, findings, or test results.

When `AGENT_HANDOFF_ENFORCE_BRANCH=1` is set, `record_event`, `review_findings`, `close_slice`, `set_handoff_state`, and other write paths raise `BranchMismatchError` if the caller's git branch diverges from the active task's `target_branch`. Writes to tasks targeting `main` or `master` are exempt. Default (env var unset): current warning-only behaviour preserved.

**Enforcement:** Set `export AGENT_HANDOFF_ENFORCE_BRANCH=1` in the dev shell. Tests bypass via `AGENT_HANDOFF_SKIP_BRANCH_ENFORCEMENT=1` (set automatically by both packages' `tests/conftest.py`). The error response names the expected branch and worktree path so the agent can self-correct.

See [docs/workbay/rules/development-workflow.md § Branch Isolation](docs/workbay/rules/development-workflow.md#branch-isolation-protocol-mandatory) for the full rationale.

### Review Findings Placement

> **Review findings live in workbay-handoff-mcp, not in task plans. Never paste a finding list into a markdown file.**

Review findings are recorded with `review_findings(review={"operation":"record"|"batch_record", ...})` and read back with `review_findings(review={"operation":"list"|"get"})`. Pasting them inline into a task plan duplicates the source of truth, escapes the pre-merge gate (`handoff_close_check` only audits MCP-stored findings), and silently rots the moment a finding is updated, deferred, or fixed. If a task plan needs to reference findings, link to them by ID (`see AOMCP-3-BR-04 in handoff`) instead of duplicating their bodies.

**Status tracking belongs in the DB, not the plan.** Do not mirror finding status into task-plan checklists — no `(E17-6-BR-08 closed)` / `(BR-09 fixed)` / `(deferred)` trailers, no Slice checklist items whose completion is keyed to a finding. The task-plan checklist describes work; finding status is queried live via `review_findings(review={"operation":"list","status":"open","task_ref":"<task>"})` or read from `DASHBOARD.txt`. A plan that tracks finding status will drift the instant a finding is reopened, deferred, or re-classified in the DB.

**Enforcement:** A `PreToolUse` hook in both harnesses (`scripts/hooks/guard-task-plan-findings.py`) scans the content of every Edit/Write to a task plan markdown file (`docs/tasks/**`, `docs/epics/**`, `packages/*/docs/tasks/**`, or any `*task-plan*.md`). Three or more consecutive bulleted lines that open with a finding-style identifier (e.g. `- AOMCP-3-BR-04: ...`, `- **H-1**: ...`, `- E15-7-BR-02 — ...`) are rejected with an actionable error naming the MCP tools the agent should use instead. The same scanner is wired into `make check-all` via `make lint-task-plans`, so CI catches drift even if a local hook is bypassed. The script also exposes a `--scan-staged` mode for opt-in `git pre-commit` integration.

See [docs/workbay/rules/branch-review-guide.md § Review Findings Placement](docs/workbay/rules/branch-review-guide.md#review-findings-placement-mandatory) for the full rationale and the AHMCP-14 incident that motivated the enforcement.

### Bounded Handoff Reads

> **Routine `get_handoff_state` calls must use the bounded-read levers — never call it with `detail="full"` and high `top_n_*` values for an identity check.**

The handoff response envelope appends an `oversize_response: ...` advisory warning to `payload["warnings"]` whenever the serialised payload exceeds ~20 KB (~5,000 tokens). The warning is purely advisory — the response is still returned in full so callers are not silently truncated — but it names the bounded-read levers to adopt on the next call (`sections`, `detail`, the `top_n_*` caps, `fields`).

See the installed `workbay-handoff-mcp` package documentation for the full set of bounded-read levers and example call patterns.

### MCP Handoff (MANDATORY)

- Every code change must be logged with a `record_event(event={event_kind: "decision", actor: {...}, ...})` entry before review or completion.
- After recording the decision, notify the user that the handoff has been updated (e.g. "Handoff updated: decision `<id>` recorded."). This notification is mandatory — a response that makes code changes without both recording and notifying is incomplete.
- A task response is incomplete if MCP handoff was not updated.
- When a task is finished, set status to `done` via `update_task_status(task_ref=..., status="done")` before or after archiving. `close_slice` keeps status `in_progress` — it does not close the task. `archive_task_state` preserves whatever status the task had; archiving while `in_progress` leaves the dashboard permanently stale.
- Slice completion format (enforced at write time): [docs/workbay/templates/slice-complete-template.md](docs/workbay/templates/slice-complete-template.md).
- After every state-changing handoff operation (`record_event`, `review_findings(operation="update")`, `review_findings(operation="batch_record")`, `review_runs(operation="record")`, `set_handoff_state`, `update_task_status`), call `render_handoff(kind='dashboard')`. DASHBOARD.txt is the operator-facing cross-task view and must stay current. Call `render_handoff(kind='current_task', task_ref=<ref>)` only on-demand for task-specific agent handoffs; agents with live MCP access should use `get_handoff_state`/`load_session` instead.
- When logging **3 or more review findings** in a single review pass, use `review_findings(review={"operation":"batch_record", ...})` instead of repeated `review_findings(review={"operation":"record", ...})` calls — one atomic write, one DB flush, per-item results returned.
- If a write is blocked with `handoff provenance drift`, switch to the task's `target_worktree_path` and retry there. For Bash Python-API fallback writes, the command must begin with `cd <target_worktree_path> &&` and include `task_ref='<task-ref>'` so the guard can validate the target worktree.
- Full handoff protocol: [docs/workbay/instructions.md](docs/workbay/instructions.md#mcp-handoff-contract-mandatory).

### Git Commit Rules

- **NEVER add `Co-Authored-By` trailers or any AI/model attribution to git commit messages.** This is a mandatory, permanent rule. Violations require history rewrite.

### Short Rules

Derived copy from the canonical source: [docs/workbay/constitution.md](docs/workbay/constitution.md#short-rules). Edit rules there first, then sync this injected surface in the same slice.

- [sr-001] helpful=2 harmful=0 :: Do not relax compliance/lint scripts to silence violations. Fix the offending code.
- [sr-002] helpful=1 harmful=0 :: Every `composer`/`npm` gate script must succeed on invocation, not just be defined.
- [sr-003] helpful=1 harmful=0 :: **npm** for Node.js (not pnpm). **Composer** for PHP.
- [sr-004] helpful=2 harmful=0 :: When editing CSS/SCSS, use existing design tokens (`--acx-*` custom properties) for colors, typography, elevation, radius, and font-weight instead of raw literals. If a needed token does not exist, add it to the shared token surface first. Specifically: `--acx-color-*` or `--acx-gray-*` for colors (no hex literals); `--acx-text-*` for font sizes; `--acx-shadow-*` for box-shadows; `--acx-radius-*` for border-radius; `--acx-font-weight-*` for font weights. Status indicators must pair color with an icon; do not rely on color alone.
- [sr-005] helpful=2 harmful=0 :: In TypeScript, use assertion helpers (`asserts value is ...`) for internal invariants and unreachable branches instead of `console.assert` or non-null assertions on API data. Do not use assertion helpers for request/input validation; validate boundary data explicitly.
- [sr-006] helpful=1 harmful=0 :: In Python, use `assert` only for narrow internal invariants during development and tests. Do not use `assert` for request validation, external data checks, or behavior that must always execute in production; raise explicit exceptions or HTTP errors instead.
- [sr-007] helpful=2 harmful=0 :: Centralize domain status values as enums or `as const` objects (TypeScript), PHP backed enums, or Python `StrEnum`/`IntEnum`. Do not scatter magic string comparisons (`=== 'completed'`, `=== 'clustering'`) across files; import from a single canonical definition and use exhaustive switches where applicable.
- [sr-008] helpful=1 harmful=0 :: When a hook, function, or constructor takes more than 8 destructured parameters, group them into 2-3 cohesive typed objects (e.g., state, actions, mutations). This prevents the "parameter slippery slope" that compounds with each new feature.
- [sr-009] helpful=1 harmful=0 :: PHP controller methods that run transactions must use a shared `run_transactional(callable)` wrapper instead of inlining START TRANSACTION / COMMIT / ROLLBACK boilerplate.
- [sr-010] helpful=1 harmful=0 :: For a full local-only development reset of both databases, use `make reset-local WP_PATH="<wordpress>/app/public" CONFIRM_LOCAL_RESET="RESET"` from the repo root. `WP_PATH` must point to the WordPress directory containing `wp-load.php` (for LocalWP here, typically `${LOCAL_WP_ROOT:-$HOME/Development/wp-context-alt-text}/app/public`). Never use this against non-local environments.

### Cross-Branch Regression Guards

Derived copy from the canonical source: [docs/workbay/constitution.md](docs/workbay/constitution.md#cross-branch-regression-guards). Edit guards there first, then sync this injected surface in the same slice.

- [rg-001] helpful=1 harmful=0 :: No type-shim masking. New import? Update `package.json`/`composer.json` and verify with a real build.
- [rg-002] helpful=1 harmful=0 :: Preserve atomic write paths. Do not split a backend atomic operation into multiple frontend mutations.
- [rg-003] helpful=1 harmful=0 :: Primary controls reachable from zero state. Never gate primary actions behind non-zero selection.
- [rg-004] helpful=1 harmful=0 :: Role semantics match behavior. Controlled dialogs must wire `onOpenChange`.
- [rg-005] helpful=1 harmful=0 :: Schema/contract parity. Validate SQL column names against real schema before merge.
- [rg-006] helpful=1 harmful=0 :: Documented commands must run as written. Broken copy-paste syntax is a bug.
- [rg-007] helpful=1 harmful=0 :: Long-running loops: bounded stall detection. Daemon/loop code that processes multiple independent units must track per-unit no-progress cycles and exit non-zero after a bounded threshold. A single unit's failure must not halt processing of other units in the same cycle.
- [rg-008] helpful=1 harmful=0 :: Config files: validate at load time. JSON/YAML config consumed by multiple modules must be structurally validated at load time. Fail fast on missing or malformed required keys instead of silently returning empty defaults.
- [rg-009] helpful=1 harmful=0 :: No task-specific logic in generic modules. If a generic utility contains `if task_ref == "some-task"` or hardcoded domain strings for a specific task, extract that logic to a config-driven policy module or the task's manifest. It becomes dead code once the task is done.
- [rg-010] helpful=1 harmful=0 :: IDE tool output may be stale after external writes. Editor-integrated `read_file` and `grep_search` tools read from the IDE's in-memory file model, not from disk. After git operations (rebase, cherry-pick, merge, worktree intake) or edits by other agents/terminals, the model can lag behind the filesystem. When a review finding seems surprising, cross-check with a terminal command (`grep -n`, `wc -l`, `sed -n`) before recording it. This caused an entire review cycle of false positives against `scripts/mcp/orchestrator_daemon.py` (IDE showed ~700 lines, disk had 850).
- [rg-013] helpful=1 harmful=0 :: `workbay_handoff_mcp/core.py` must remain pure handoff-state CRUD. No orchestration imports, no subprocess calls, no lock management. Scope: the standalone `workbay-handoff-mcp` package available to the active workspace. Enforce during code review.
- [rg-014] helpful=1 harmful=0 :: `workbay_orchestrator_mcp` modules must use late-binding imports (function-level) for `workbay_handoff_mcp` symbols to preserve the clean split seam and avoid load-time coupling. Scope: the standalone `workbay-orchestrator-mcp` package available to the active workspace.
- [rg-015] helpful=1 harmful=0 :: Boundary adapters must not invent contract metadata. When a controller/client/adapter wraps or normalizes remote payloads, every envelope field (`limit`, `offset`, `total`, `data_source`, status/projection metadata) must come from the request, the upstream payload, or an explicitly documented fallback. Never fabricate pagination or provenance metadata from convenience guesses like `count(payload)` unless the contract explicitly defines that derivation. If the upstream shape violates the expected contract, return an explicit error instead of silently supporting both shapes.
- [rg-016] helpful=0 harmful=0 :: PHP runtime autoload parity must match tests. New runtime classes added under `apps/prototype-wp-alt-context/src/` with WordPress-style filenames (`class-*.php`, `interface-*.php`) are not PSR-4 autoloadable via Composer by default. When a new class is introduced in this naming scheme, either add the explicit `require_once` from the owning runtime entrypoint or use a PSR-4-compliant filename, and verify with a real runtime-style check such as `php -r "require 'vendor/autoload.php'; var_export(class_exists('AltContext\\\\Foo\\\\Bar'));"`
- [rg-017] helpful=1 harmful=0 :: Never force-remove a dirty linked worktree without triaging every uncommitted file. Uncommitted edits in a linked worktree are local to that worktree and do not exist in the root or on any branch. `git worktree remove --force` on a dirty worktree permanently discards those edits. Before removing: run `git -C <path> status --short`; if dirty files exist, commit task-owned changes on the branch, move cross-task bleed to the root worktree, and confirm redundant files against main. If >5 dirty files or multiple task refs are present, stop and ask the user. See [development-workflow.md § Dirty Worktree Teardown](docs/workbay/rules/development-workflow.md#dirty-worktree-teardown-mandatory).
- [rg-018] helpful=2 harmful=0 :: Never query `handoff.db` directly via `sqlite3`. Always use the `workbay_handoff_mcp` Python API. When Claude Code MCP tools are unavailable (ToolSearch returns nothing for `mcp__workbay-handoff-mcp__*`), call `from workbay_handoff_mcp import RuntimeConfig, configure_runtime, get_handoff_state, search_handoff, ...` via Bash — the Python API is the same abstraction layer as the MCP tools and is always available as a package. Raw `sqlite3` queries bypass schema validation, use internal table names that change across versions, and caused repeated errors in practice. Read-only schema introspection during a bug investigation is the only exception.

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

**Branch review**: route matching requests through the `branch-review` skill first (`.claude/skills/branch-review/SKILL.md` or `/branch-review`). Use [rules/branch-review-guide.md](docs/workbay/rules/branch-review-guide.md) as the detailed checklist/reference surface behind the skill, not as a separate ad-hoc entry point.

**Planning review**: route matching requests through the `planning-review` skill first (`.claude/skills/planning-review/SKILL.md` or `/planning-review`). Use [rules/planning-review-guide.md](docs/workbay/rules/planning-review-guide.md) as the detailed checklist/reference surface behind the skill, and use `plan-analyze` as the required pre-review triage step.

Do NOT perform ad-hoc reviews. Both guides enforce structured, MCP-visible output.
