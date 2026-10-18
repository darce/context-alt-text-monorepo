---
name: refactor-wp-alt-context
scope: project
description: Repo-tuned refactoring playbook for apps/prototype-wp-alt-context (WordPress
  plugin — PHP src/, React/TS js/, REST boundary to the Python recognition service).
  Use when refactoring, untangling, extracting, deduplicating, or restructuring PHP
  controllers/repositories/sync code, TS pages/hooks/api modules, or SCSS/design tokens
  in this app — i.e. "clean up", "extract", "this class is too big", "split this hook",
  "reduce conditionals", "harden the proxy client", "tidy the panel". NOT for new features
  (use incremental-implementation) and NOT for code outside this app.
mode: execution
context_budget: 200
makefile_target: null
mcp_tools:
- get_handoff_state
- record_event
- review_findings
tdd_gate: false
---

## Global Instructions

- when reporting information back to user, be extremely concise. sacrifice grammar for the sake of concision

# Refactor: prototype-wp-alt-context

## Overview

Behavior-preserving restructure of PHP + TS + SCSS in `apps/prototype-wp-alt-context` (WordPress plugin: PHP `src/`, React/TS `js/`, REST boundary to the Python recognition service). Books distilled under `literature/extracted/refactoring/distilled/` (local-only; gitignored). Cite the named technique on apply. No behavior change; small verified slices; MCP-recorded.

## Trigger

Use-when:
- "clean up" / "extract" / "this class is too big" / "split this hook" / "reduce conditionals" / "harden the proxy client" / "tidy the panel".
- Untangling, deduplicating, restructuring PHP controllers/repositories/sync code, TS pages/hooks/api modules, or SCSS/design tokens in this app.

Do NOT use:
- New features → `incremental-implementation`.
- Branch diff review → `branch-review`.
- Bug hunt / root-cause → `investigate`.
- Python recognition service refactor → `refactor-description-service`.

## Goal

Evidence-backed, smell-named, behavior-preserving refactor of this app, applied in small reversible slices that each pass gates, with the named technique cited from a distilled doc and the decision recorded in MCP. Tests prove behavior unchanged.

## Canonical Policy

Standard gates apply unchanged and are **not restated here** — branch isolation (code edits hook-blocked on `main`; `make task-start` first, MAINT-* ref for ad-hoc), MCP handoff after changes, pre-merge `handoff_close_check(enforce=True)`, greenfield (no migrations; delete-over-flag), and never relax a lint/compliance script (sr-001). Canonical text: [instructions.md](../../../docs/workbay/instructions.md), [constitution.md](../../../docs/workbay/constitution.md). This skill adds only the **refactor-specific** discipline:

- **Two Hats (Fowler Ch2).** Refactor hat XOR feature hat — never both in one commit. No behavior change.
- **Safety net first (Fowler Ch4).** No green tests covering the target → write a *characterization test* (capture current output, even if "wrong") before touching. Substitute Algorithm (Ch7) = capture old behavior, swap impl, diff.
- **Small reversible steps.** Compile/test after each; red + cause unclear → revert to last green, smaller step.
- **Format before lint.** `make format-all` (or `cd apps/prototype-wp-alt-context && npm run format:fix` / `composer cs-fix`) — never hand-fix what the formatter fixes.

Constitution `[sr/rg]` rules that constrain moves (rule text lives in `constitution.md`; only the app anchor is here):

| Rule | App anchor |
|---|---|
| sr-004 | SCSS → `--acx-*` tokens (`js/admin/styles/tokens/_*.scss`); status = color **+ icon**. |
| sr-005 | TS assertion helpers for internal invariants only; boundary/API data validated explicitly. |
| sr-007 | Status values centralized at `js/admin/api/recognition/types/dataSource.ts` (`DATA_SOURCE`,`PROJECTION_STATUS`). |
| sr-008 | >8 destructured params → `{state}`/`{actions}`/`{mutations}`. |
| sr-009 | PHP transactions via `run_transactional(callable)`. |
| rg-003 | Primary controls reachable from zero state. |
| rg-004 | Controlled Radix dialogs wire `onOpenChange`. |
| rg-015 | Adapters never fabricate envelope metadata (`limit`,`total`,`data_source`). |
| rg-016 | New PHP `class-*.php`/`interface-*.php` not PSR-4 autoloaded — add `require_once` + verify `php -r "...class_exists(...)"`. |

Frontend hard limits (frontend-guidelines): 300 lines/component, 5 `useState`, 3 `useEffect`, 10 props. Extract when JSX >50 lines, pattern 2+ times, nesting >2, or 6+ `useState`.

## Core Process

Ordered refactor loop — Two Hats on (refactor only, no behavior change):

1. **Identify** one smell (catalog below). Scope to the active task; resist drive-by sprawl.
2. **Verify coverage.** Run the suite. Target uncovered → write a characterization test (capture current behavior) first.
3. **Small reversible change.** One named technique (playbook below). Remove temps before extracting (Fowler Ch1). Don't batch unrelated moves.
4. **Run gates** (from app dir, `cd apps/prototype-wp-alt-context`):
   - TS: `npm run test` (or `test:agent`) · `npm run typecheck` · `npm run lint`
   - PHP: `composer test` (PHPUnit) · `composer phpstan` · `composer cs-check`
   - Format first: `npm run format:fix` / `composer cs-fix` (or root `make format-all`).
   - SCSS/full: root `make check-all` before review-ready.
   - Autoload changed PHP class? `composer dump-autoload` + `php -r "...class_exists(...)"` (rg-016).
5. **Record handoff.** `record_event(decision, commit_sha=<full 40-char rev-parse>)` → `render_handoff(kind='dashboard')` → notify user.
6. **Next smell.** Test-code-commit cycle, many per hour.

At slice end: review pass + findings in MCP (never inline in a plan — Review Findings Placement rule), then `handoff_close_check(enforce=True)`.

### Smell catalog tuned to this app

Largest files (Phase A scan) are the prime hunting grounds.

#### PHP — `src/api/` and `src/sovereign/`

- **Large Class / God controller.** `class-cluster-mutations-controller.php`, `class-analysis-jobs-controller.php` (large), `class-clusters-controller.php`. Sign: one class registers many routes AND holds label/merge/split/dismiss/reassign logic. → **Extract Class** (Fowler Ch7) by responsibility cluster; route registration stays, handlers move to collaborators. `RecognitionController` is already the composition-root pattern — push handler logic toward focused services, not back into it.
- **Large Class — repositories.** `class-clusters-repository.php` (large), `class-identity-members-repository.php`, `class-sync-state-repository.php`. Sign: CRUD + curation reset + delete-with-members + count derivation in one file. → **Extract Class** for cohesive method+field subsets (Modern SE Ch10: "and" in the description = SoC violation).
- **Long Function + Repeated Switches.** Mutation handlers branch on operation/conflict_code. Same switch in controller, drain, and `ConflictResolutionService`. → **Decompose Conditional** then **Replace Conditional with Polymorphism** (Fowler Ch10) — or for source/operation dispatch, a map (see playbook). `class-split-topology-command-drain.php` and `class-outbox-drain.php` are loop+conditional sprawl: **Split Loop** + **Extract Function**.
- **Transaction Script → domain.** Inline SQL + business rule + conflict bookkeeping in one method = Modern SE `add_to_cart1` antipattern. → push accidental complexity (persistence) behind the repository; keep handler at one abstraction level (Modern SE Ch11 Ports & Adapters; Fowler Split Phase). All mutation paths must route transactions through `run_transactional` (sr-009) and refresh `SyncStateRepository` metrics (backend-php rule).
- **N+1 in loops.** `foreach ($rows) { $repo->list_for_cluster($uuid) }`. → batch `WHERE col IN (...)` (backend-php § Avoid N+1). Release It §9.7/§9.9 reinforces: chatty calls compound.
- **Schema-key drift.** SQL column names vs `class-life-cycle-manager.php`. HIGH-severity. Confirm columns before editing SQL; add a test that fails on a non-existent key (backend-php § Schema-Key Parity; rg-005).
- **Primitive Obsession / Mysterious Name.** Stringly-typed status/source/conflict_code passed around. → `ProbeOutcome`-style const class (already exists: `src/api/class-probe-outcome.php`) or **Replace Primitive with Object** (Fowler Ch7).

#### TS/React — `js/admin/`

- **Large component / too many hooks.** `WorkbenchContext.tsx` (at the useState/useEffect limit), `IdentityClusterItem.tsx` (multiple modal `useState` + derived booleans), `DeadLetterPanel.tsx`, `SuggestionReviewPanel.tsx`, `Panels.tsx`, `SyncStatusIndicator.tsx`. → **Extract Function/Component** + **Extract Hook** (move data-fetching `useState`+`useEffect` clusters into `js/admin/hooks/`; panel hooks stay local per frontend-guidelines).
- **Wordy / nested conditionals.** `IdentityClusterItem.tsx` derived flags (`canEdit`,`canMutate`,`canSearchForMatch`) gating JSX. Already partly good (named bools — Refactoring TS Ch3). Where deeper: **Guard Clauses** (Refactoring TS Ch4 / Fowler Replace Nested Conditional with Guard Clauses).
- **Flag args / behavior-switching options.** Functions taking booleans that branch. → **Remove Flag Argument** / named wrappers (Refactoring TS Ch6; Fowler Ch11).
- **Status-string switches.** `SyncHealth` union (`offline|stale|queued|conflicts|failures|healthy`) + transient overrides. Branch chains on it. → discriminated unions + **Replace Conditional with map / Strategy** (Refactoring TS Ch5; see playbook). Keep canonical values centralized (sr-007).
- **Null-check pyramids on API data.** Roster confidence priority chain (`record.match.similarity` → … → `topCandidate.confidence`), optional projection fields. → **Null Object / Special Case** + normalize once in the API layer (Refactoring TS Ch2; frontend-guidelines #14 "normalize once").
- **Prop drilling / data clumps.** Cluster + edit-state + mutation callbacks threaded through panels. → **Introduce Parameter Object** grouping (sr-008): `{state}`,`{actions}`,`{mutations}`.
- **Boundary leakage.** `fetchApi` or transport in page/hook layers. → all HTTP through `js/admin/api/recognition/*` modules (frontend-guidelines #8/#10); centralize React Query keys in a `queryKeys` factory (#4); complete barrel exports (#13).

#### SCSS / UI — `js/admin/styles/`

- **Raw literals.** Hex/px/shadow/radius/weight literals in `components/_*.scss`. → swap to `--acx-*` tokens (sr-004; Refactoring UI "define shades/scale up front").
- **Color-only status.** Sync/health badges. → pair with icon (sr-004; Refactoring UI "don't rely on color alone").
- **Ambiguous hierarchy/spacing.** Weak primary/secondary distinction; equal group spacing. → token-driven weight/contrast + spacing scale (Refactoring UI Hierarchy / Layout & Spacing). `!important` → raise specificity by nesting under `.acx-` (frontend-guidelines #6).

### Technique playbook (high-ROI moves here)

#### PHP-side

- **Encapsulate** record/collection access before moving widely-used data (Fowler Ch6/7).
- **Extract Class** from god controllers/repos by cohesive field+method subset; verify autoload (rg-016) and `php -l`.
- **Replace Conditional with Polymorphism** for repeated source/operation/conflict_code switches (Fowler Ch10). When a stateless dispatch is enough, a keyed handler map beats a class hierarchy.
- **Split Phase** to separate fetch/transform/persist in drains and projectors (Fowler Ch6; Modern SE essential-vs-accidental).
- **Transaction Script → domain**: thin handler → repository/service; route via `run_transactional` (sr-009); keep metrics refresh on every mutation path.
- **Introduce Parameter Object** for repeated `(cluster_uuid, tenant_id, version, ...)` clumps.

#### TS/React-side

- **Null Object / Special Case** for absent projection / unknown states; normalize at the API boundary (Refactoring TS Ch2; frontend #14).
- **Discriminated unions over flag args**; **Remove Flag Argument** → named wrappers (Refactoring TS Ch5/6).
- **Extract Hook** — lift fetch `useState`+`useEffect` to `hooks/`; reduces component to render + handlers (frontend extract-when rules).
- **Replace conditional with map** — `const strategies = { healthy: ..., stale: ..., conflicts: ... }; strategies[health]()` for `SyncHealth`/outcome dispatch (Refactoring TS Ch5/7).
- **Props grouping** into state/actions/mutations objects (sr-008).
- **Value Object** for stringly-typed domain primitives validated once (Refactoring TS Ch5).

#### UI-token-side (map every change to a token)

- Hex → `--acx-color-*`/`--acx-gray-*`; px font → `--acx-text-*`; shadow → `--acx-shadow-*`; radius → `--acx-radius-*`; weight → `--acx-font-weight-*` (sr-004). Token missing → add to `styles/tokens/_*.scss` first.
- Emphasize-by-de-emphasizing; status = color+icon; use elevation system for dialogs/dropdowns; fewer borders (shadow/bg/spacing instead) — Refactoring UI.

#### Boundary-side (recognition REST client + acx/v1 contract)

- **Resilience already lives in** `class-abstract-recognition-proxy-controller.php` (circuit breaker via transient, failure key, per-class timeouts) + `class-recognition-proxy-policy.php` (timeout/retry/circuit per request class: ui_read 2s+circuit, mutation 60s, background_sync 30s). Refactoring a proxy call: preserve **Timeouts + Circuit Breaker + Fail Fast** (Release It Ch5). Never an un-timed `wp_remote_request`. Open circuit surfaces a distinct error the UI can degrade on — not a generic failure.
- **Graceful degradation / Sovereign read model.** UI derives from local projection tables; degrade gracefully when projection unavailable, **no fallback to live backend reads** (frontend-guidelines § Sovereign Read Model, ADR-003). Release It SLA-Inversion: per-feature degradation; don't let the slow recognition service drag a local-only read down.
- **Bound result sets** at the caller (Release It §4.11 / §9.7): LIMIT + tenant scope; never `SELECT *` an unbounded projection.
- **Perceived latency** (Latency Ch1.3: 0.1s immediate / 1s instant / 10s slow; Ch2.2 fanout amplifies tail). Cache reads at the REST boundary — cache-aside / TTL / negative-caching / materialized view (Latency Ch6) via WP transients. Cache key space finite + invalidated (Release It Steady State §5.4). Tail stays backend-tied on a miss unless miss cost is also cut.
- **acx/v1 schema evolution** (DDIA Ch4). Servers (recognition) update first → **backward-compat requests, forward-compat responses**: old plugin code **ignores unknown response fields**, doesn't choke. "Data outlives code" — projection rows / append-only outbox payloads in original encoding; preserve unknown fields on rewrite; don't reuse/renumber field meaning. Outbox payloads append-only post-enqueue (backend-php rule) — refactor must not rewrite enqueued semantics. Only genuinely-applicable DDIA slice.

## Common Rationalizations

- "No tests, but I'll be careful." → No safety net = mutation, not refactoring (Fowler Ch2/4). Characterization test first, or stop.
- "A big rewrite is faster." → Greenfield rewrite applies to whole modules (`001_identity_schema.py`, delete-over-flag), NOT cross-cutting slices. Cross-cutting change goes one verified step at a time.
- "Hex literal is quicker than a token." → sr-004 violation. Use `--acx-*`; add the token to `styles/tokens/_*.scss` first if missing.
- "It's just a rename, skip the gates." → Renames of PHP `class-*.php`/`interface-*.php` break PSR-4/autoload parity (rg-016). `composer dump-autoload` + `class_exists` verify; don't skip.
- "I'll fix this unrelated smell while I'm here." → Drive-by sprawl. Out of scope → leave it (litter-pick only if trivial + same file).
- "Add the abstraction now for future flexibility." → Speculative generality (YAGNI; Fowler Ch3). Refactor toward the change you have.

## Red Flags

Stop conditions — when NOT to refactor:

- **No tests + no time to add them.** No safety net = mutation, not refactoring (Fowler Ch2/4). Stop; record a blocker or add the test.
- **Out of task scope.** Unrelated to the objective → leave it. Don't expand blast radius.
- **Would break acx/v1 consumers.** Changing response shape, removing/renumbering a field, or altering an append-only outbox payload other code/recognition depends on. Expand-contract (DDIA Ch4) under a real feature task, not a silent refactor.
- **Greenfield says rewrite.** No prod users / no data → clean rewrite in `001_identity_schema.py` or delete-over-flag beats a backward-compat shim. No data migrations.
- **Speculative generality.** No abstraction "for the future" (YAGNI; Fowler Ch3).
- **Atomic write paths.** Don't split a backend atomic op into multiple frontend mutations (rg-002).

In-flight warning signs (course-correct now):

- Test red and fix is >1 step back → revert to last green, re-slice smaller.
- acx/v1 contract change creeping into a "refactor" → feature hat on; stop, re-scope.
- Edits landing on the `main` path (absolute repo-root paths bypass the branch hook) → confirm you're writing into `target_worktree_path`.
- Finding lists pasted into a task plan → Review Findings Placement violation; record via `review_findings`.

## Recovery

- **Broken mid-refactor.** Revert to the last green commit; re-slice smaller; re-run gates.
- **Provenance / context drift warning on a handoff write.** `cd` to the canonical `target_worktree_path` (Bash Python-API fallback writes must begin `cd <target_worktree_path> &&` and pass `task_ref=`).
- **Gate fails.** Run `make format-all` (or `npm run format:fix` / `composer cs-fix`) first, then hand-fix the remainder. Never relax the gate (sr-001).
- **Smell needs feature work to fix.** Don't smuggle it into the refactor. Record a finding via `review_findings(review={"operation":"record",...})` and defer.

## Convergence Criteria

Done when:
- Gates green at HEAD (TS test/typecheck/lint, PHP test/phpstan/cs-check, `make check-all`).
- Behavior unchanged — tests prove it (characterization/existing suite green).
- Decision recorded via `record_event` + user notified.
- No unrelated diff hunks (refactor hat only; one logical move per slice).
- Distilled-doc citation in the decision rationale (technique → its book/chapter).

## See Also

Source map — book → distilled doc → sections used → applicability. All paths under `literature/extracted/refactoring/distilled/` (local-only reference: `literature/` is gitignored and absent on fresh clones/CI — the skill is self-contained without it; consult the docs when present).

| Book | Doc | Sections used here | Applicability |
|---|---|---|---|
| Refactoring (Fowler/Beck) | `refactoring-fowler-beck.md` | Ch3 smells (Large Class, Long Fn, Repeated Switches, Data Clumps, Primitive Obsession); Ch6/7 Extract Fn/Class, Encapsulate; Ch10 conditionals & polymorphism; Two Hats; Ch4 tests | **HIGH** — core catalog, PHP + TS |
| Refactoring TypeScript | `refactoring-typescript.md` | Ch2 Null/Special Case; Ch3 wordy conditionals; Ch4 guard clauses; Ch5 enums/value objects/strategy map; Ch6 flag-arg removal & data objects; Ch7 method extraction | **HIGH** — js/ components, hooks, api |
| Refactoring UI | `refactoring-ui.md` | Hierarchy; Layout & Spacing; Color (define shades up front, not color-alone); Depth/elevation; Use fewer borders | **HIGH** — js/admin/styles + `--acx-*` tokens |
| Modern Software Engineering | `modern-software-engineering.md` | Ch10 cohesion (essential vs accidental, "and"=SoC); Ch11 SoC + Ports & Adapters + DI; Ch12 abstraction; Ch13 coupling; testability | **MEDIUM** — where to draw seams |
| Release It! | `release-it.md` | Ch4 Integration Points / Cascading / SLA Inversion / Unbounded Result Sets; Ch5 Timeouts, Circuit Breaker, Fail Fast, Steady State | **MEDIUM** — recognition REST client only |
| Latency | `latency-reduce-delay-in-software-systems.md` | Ch1.3 perception thresholds; Ch2.2 tail/fanout; Ch6 caching (cache-aside, TTL, negative cache, materialized views) | **MEDIUM/LOW** — WP/REST cache only |
| Designing Data-Intensive Apps | `designing-data-intensive-applications.md` | Ch4 Encoding & Evolution only (backward/forward compat, ignore-unknown-fields, servers-first, data-outlives-code) | **LOW** — acx/v1 + outbox discipline |
| Using Asyncio in Python | `using-asyncio-in-python.md` | — | **NONE** — Python server concurrency; no surface in this JS/TS + PHP plugin |

Related skills: `branch-review` (branch diff) · `investigate` (bug hunt) · `tdd` (test-first / safety-net) · `refactor-description-service` (Python recognition service).
