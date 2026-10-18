# Agentic Constitution

Canonical authoring source for the repo's `[sr-NNN]` short rules and `[rg-NNN]` regression guards.

- Edit rules here first.
- Sync the derived injection copy in `CLAUDE.md` in the same slice.
- `docs/workbay/instructions.md` should reference this file by path instead of carrying its own rule copy.

## Short Rules

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
- [sr-010] helpful=1 harmful=0 :: For a full local-only development reset of both databases, use `make reset-local WP_PATH="<wordpress>/app/public" CONFIRM_LOCAL_RESET="RESET"` from the repo root. `WP_PATH` must point to the WordPress directory containing `wp-load.php` (for LocalWP here, typically `${LOCAL_WP_ROOT:-$HOME/Development/wp-context-alt-text}/app/public`). Never use this against non-local environments.
- [sr-011] helpful=0 harmful=0 :: `ruff`/`mypy` (and `eslint`/`prettier`/`phpcs`) violations never block a merge. Record each as a `low` finding prefixed `lint(<tool>):`, defer it with `resolution_notes="lint-only; fix in next wave <task-ref>/<lane-id>"` before the gate, list it in the next wave's brief, and close it `fixed` there. One deferral only; never silence the tool ([sr-001]) and never skip the finding.

## Cross-Branch Regression Guards

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
- [rg-013] helpful=1 harmful=0 :: **`workbay_handoff_mcp/core.py` must remain pure handoff-state CRUD.** No orchestration imports, no subprocess calls, no lock management. Scope: the standalone `workbay-handoff-mcp` package available to the active workspace. Enforce during code review.
- [rg-014] helpful=1 harmful=0 :: **`workbay_orchestrator_mcp` modules must use late-binding imports** (function-level) for `workbay_handoff_mcp` symbols to preserve the clean split seam and avoid load-time coupling. Scope: the standalone `workbay-orchestrator-mcp` package available to the active workspace.
- [rg-015] helpful=1 harmful=0 :: **Boundary adapters must not invent contract metadata.** When a controller/client/adapter wraps or normalizes remote payloads, every envelope field (`limit`, `offset`, `total`, `data_source`, status/projection metadata) must come from the request, the upstream payload, or an explicitly documented fallback. Never fabricate pagination or provenance metadata from convenience guesses like `count(payload)` unless the contract explicitly defines that derivation. If the upstream shape violates the expected contract, return an explicit error instead of silently supporting both shapes.
- [rg-016] helpful=0 harmful=0 :: **PHP runtime autoload parity must match tests.** New runtime classes added under `apps/prototype-wp-alt-context/src/` with WordPress-style filenames (`class-*.php`, `interface-*.php`) are not PSR-4 autoloadable via Composer by default. When a new class is introduced in this naming scheme, either add the explicit `require_once` from the owning runtime entrypoint or use a PSR-4-compliant filename, and verify with a real runtime-style check such as `php -r "require 'vendor/autoload.php'; var_export(class_exists('AltContext\\\\Foo\\\\Bar'));"`
- [rg-017] helpful=1 harmful=0 :: **Never force-remove a dirty linked worktree without triaging every uncommitted file.** Uncommitted edits in a linked worktree are local to that worktree and do not exist in the root or on any branch. `git worktree remove --force` on a dirty worktree permanently discards those edits. Before removing: run `git -C <path> status --short`; if dirty files exist, commit task-owned changes on the branch, move cross-task bleed to the root worktree, and confirm redundant files against main. If >5 dirty files or multiple task refs are present, stop and ask the user. See [development-workflow.md § Dirty Worktree Teardown](rules/development-workflow.md#dirty-worktree-teardown-mandatory).
- [rg-018] helpful=2 harmful=0 :: **Never query `handoff.db` directly via `sqlite3`. Always use the `workbay_handoff_mcp` Python API.** When Claude Code MCP tools are unavailable (ToolSearch returns nothing for `mcp__workbay-handoff-mcp__*`), call `from workbay_handoff_mcp import RuntimeConfig, configure_runtime, get_handoff_state, search_handoff, ...` via Bash — the Python API is the same abstraction layer as the MCP tools and is always available as a package. Raw `sqlite3` queries bypass schema validation, hit internal table names that change across versions, and produced repeated errors (wrong table names, wrong column names) in practice. The only valid reason to open the DB file directly is schema introspection during a bug investigation, and even then read-only.
