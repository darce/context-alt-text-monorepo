# Initial Refactoring Plan — `apps/prototype-wp-alt-context`

**Task ref:** `MAINT-wp-alt-context-refactor-plan-20260607`
**Scope:** Behavior-preserving restructure of the WordPress plugin (PHP `src/`, React/TS `js/`, SCSS). No behavior change; small verified slices; MCP-recorded; each technique cited from `literature/extracted/refactoring/distilled/`.
**Companion docs:** `refactoring-evaluation.md`, `refactoring-typescript-evaluation.md`, `refactoring-ui-evaluation.md` (book-level evaluations, 2026-04-30). This doc is the *actionable priority + slice sequence* derived from a fresh 2026-06-07 scan.

---

## TL;DR — what to refactor first

Ranked by ROI (impact × safety × low blast radius):

> **Note — the Methods column in the 2026-06-07 table below is unreliable.** It listed clusters-repository 60, analysis-jobs 54, identity-members 55; even the contemporaneous epic disagreed (~20 methods each). **Do not author follow-up plans from this column.** Re-verify with `grep -c 'public function'` and `wc -l` against current sources. Epic `docs/epics/v0.4.1/wp-alt-context-structural-refactor-epic.md` + that recount is the source of truth. This companion is already flagged for deletion (epic REFA-PA-07).
>
> **2026-09-09 recount** (this checkout): cluster-mutations 509 LOC / 21 public methods; clusters-repo 168 / 23; analysis-jobs 280 / 15; identity-members 138 / 15; clusters-controller 253 / 14; split-topology-command-drain 1025 / 3 (still inlines START TRANSACTION); outbox-drain 652 / 14 (no in-file transactions); `_workbench.scss` 1425 LOC, 66 `px`, 0 hex. All eight original targets were decomposed (see Closure); do not restart REFA-1..8 from the historical table.

| Rank | Target | LOC (2026-06-07, historical) | Methods (2026-06-07, **unreliable**) | Safety net | Smell | First move |
|---|---|---|---|---|---|---|
| **1** | `src/api/class-cluster-mutations-controller.php` | 1257 | 51 (unreliable; epic had 21) | partial (`ClusterMutationsControllerDualWriteTest`) | God controller, 11 routes + label/merge/split/dismiss/reassign | Extract Class per operation cluster |
| **2** | `src/sovereign/repositories/class-clusters-repository.php` | 1164 | 60 (unreliable; epic had 34; now 23) | yes (`ClustersRepositoryTest` + `...MutationTest`) | God repository, CRUD + curation reset + delete-with-members + count derivation | Extract Class by cohesive method+field subset |
| **3** | `src/api/class-analysis-jobs-controller.php` | 1144 | 54 (unreliable; epic had 35; now 15) | yes (`AnalysisJobsControllerTest` + transport) | God controller, 8 routes | Extract Class; Split Phase on job lifecycle |
| **4** | `src/sovereign/repositories/class-identity-members-repository.php` | 1045 | 55 (unreliable; epic had 28; now 15) | yes (`IdentityMembersRepositoryTest`) | God repository | Extract Class; batch N+1 audit |
| **5** | `js/admin/styles/components/_workbench.scss` | 1159 | — | visual/Playwright a11y | Raw literals: 11 hex, 80 px, 0 `!important` | Token swap to `--acx-*` (sr-004) |
| 6 | `src/sovereign/sync/class-split-topology-command-drain.php` | 799 | 44 (unreliable; now 3 public / 1025 LOC) | yes (`SplitTopologyCommandDrainTest`) | Loop+conditional sprawl | Split Loop + Extract Function |
| 7 | `src/api/class-clusters-controller.php` | 770 | — | yes (`ClustersControllerTest`) | God controller | Extract Class |
| 8 | `src/sovereign/sync/class-outbox-drain.php` | 680 | — | yes (`OutboxDrainTest`) | Loop+conditional sprawl | Split Loop |

**Do not start with #1.** REFA-1..8 already landed (see Closure). The table above is a 2026-06-07 scan record, not a queue. Remaining work is **REFA-9** (`run_transactional` on split-topology's leftover inline transaction) and the epic's Deferred list (TS splits, optional spacing-token follow-up, delete this companion per REFA-PA-07). Do not restart cluster-mutations / god-controller decomposition.

---

## Calibration — fresh scan vs skill assumptions (2026-06-07)

The `refactor-wp-alt-context` skill catalog is partly stale. Verified against current `main`:

1. **"Repeated Switches" smell is essentially absent.** `grep` across the top-5 PHP targets: **0 `switch` statements** (one `switch` total in analysis-jobs, no `match`/`case` density). Do **not** plan "Replace Conditional with Polymorphism" / keyed-dispatch-map work as a primary move — there is little to replace. The dominant PHP smell is **God Class** (Large Class, Fowler Ch3): 51–60 methods per file.
2. **Top PHP targets already have a safety net.** Every rank-1..8 target has a PHPUnit test except none are fully uncovered — `SplitTopologyCommandDrainTest` exists (skill claimed it didn't). Cluster-mutations controller is only *partially* covered (dual-write path only) → **add characterization tests for the un-covered handlers before extracting** (Fowler Ch4/Ch7).
3. **TS/React is lower priority than the skill implies.** `WorkbenchContext.tsx` = 4 `useState` / 3 `useEffect` (under the 5/3 limit). `IdentityClusterItem.tsx` = 3 `useState` / 2 `useEffect`. Both *within* frontend hard limits. No TS file is over the 300-line component limit except via colocated tests. **TS refactor is opportunistic, not urgent.** Defer to a later pass.
4. **SCSS token debt is real and isolated.** `_workbench.scss` (1159 LOC) has 80 px + 11 hex literals (sr-004 violations) but 0 `!important` — clean specificity, just untokenized values. Good first SCSS slice because it is mechanical and visually verifiable.

---

## Gates (mandatory, every slice)

Two Hats: refactor hat XOR feature hat — never both in one commit (Fowler Ch2).

1. **Branch isolation.** `make task-start TASK=<id> OBJECTIVE="..."` → edit only in `target_worktree_path`. Code edits on `main` are hook-blocked. Each slice below is its own task ref (e.g. `REFA-1`).
2. **Safety net first.** Target handler uncovered → write a **characterization test** capturing current output before touching (Fowler Ch4). Applies to cluster-mutations rank-1.
3. **Small reversible steps.** Compile/test after each. Red + cause unclear → revert to last green, smaller step.
4. **Format before lint.** `cd apps/prototype-wp-alt-context && composer cs-fix` / `npm run format:fix` (or root `make format-all`). Never hand-fix what the formatter fixes; never relax a gate (sr-001).
5. **Autoload parity (rg-016).** New PHP `class-*.php` under `src/` is NOT PSR-4 autoloaded. Add explicit `require_once` from the owning entrypoint (or PSR-4 filename) and verify: `composer dump-autoload` + `php -r "require 'vendor/autoload.php'; var_export(class_exists('AltContext\\\\…'));"` + `php -l` each new file.
6. **Per-slice gates.** PHP: `composer test` · `composer phpstan` · `composer cs-check`. TS: `npm run test` · `npm run typecheck` · `npm run lint`. SCSS/full: root `make check-all` before review-ready.
7. **Handoff.** `record_event(decision, commit_sha=<full 40-char rev-parse>)` → `render_handoff(kind='dashboard')` → notify user. Then review pass + findings in MCP (never inline) → `handoff_close_check(enforce=True)`.

---

## Constraints that bound the moves (do not violate)

- **sr-009** — all mutation paths route transactions through `run_transactional(callable)`, not inline START/COMMIT/ROLLBACK. Preserve metrics refresh (`SyncStateRepository`) on every mutation path.
- **rg-002** — do not split a backend atomic write into multiple mutations.
- **rg-005** — validate SQL column names against real schema before editing SQL (cross-check `class-life-cycle-manager.php`). Add a test that fails on a non-existent key.
- **rg-015** — boundary adapters must not fabricate envelope metadata (`limit`/`total`/`data_source`). Preserve the resilience seam in `class-abstract-recognition-proxy-controller.php` + `class-recognition-proxy-policy.php` (timeouts + circuit breaker, Release It Ch5) — never an un-timed `wp_remote_request`.
- **sr-004** — SCSS uses `--acx-*` tokens; missing token → add to `js/admin/styles/tokens/_*.scss` first. Status = color + icon, never color alone.
- **Greenfield** — no prod users/data. Prefer clean rewrite of a whole cohesive module over a backward-compat shim. No data migrations. But: cross-cutting slices still go one verified step at a time (a god-class split is cross-cutting, not greenfield rewrite territory).

---

## Slice sequence (proposed, each a separate task ref)

### REFA-1 — Decompose `class-cluster-mutations-controller.php` (rank 1)
- **Pre:** Characterization tests for un-covered handlers (label/merge/split/dismiss/reassign) — capture current REST responses + side effects.
- **Move:** Extract Class (Fowler Ch7) per operation cluster → focused services (e.g. `ClusterLabelService`, `ClusterMergeService`, `ClusterSplitService`). Route registration + request parsing stay in the controller (composition root); business logic moves to collaborators. Mirror the existing `RecognitionController` composition pattern.
- **Constraints:** sr-009 transactions; rg-002 atomic paths; verify autoload (rg-016) for each new service.
- **Done:** controller shrinks to thin dispatch; each service unit-tested; gates green.

### REFA-2 — Decompose `class-clusters-repository.php` (rank 2)
- **Move:** Extract Class by cohesive field+method subset — separate read/query surface from curation-reset and delete-with-members. "and" in the description = SoC violation (Modern SE Ch10).
- **Audit:** N+1 in `foreach` (backend-php § Avoid N+1) → batch `WHERE col IN (...)`. Schema-key parity (rg-005) before any SQL edit.

### REFA-3 — `_workbench.scss` token swap (rank 5; parallelizable, low risk)
- **Move:** 80 px → `--acx-text-*`/`--acx-spacing-*`; 11 hex → `--acx-color-*`/`--acx-gray-*`. Missing token → add to token surface first (sr-004).
- **Verify:** Playwright a11y/visual snapshot unchanged. Good "warm-up" slice — mechanical, isolated, visually checkable. Can run before/in-parallel-with REFA-1.

### REFA-4 — Decompose `class-analysis-jobs-controller.php` (rank 3)
- **Move:** Extract Class + Split Phase (Fowler Ch6) separating fetch/transform/persist in the job lifecycle. Preserve transport seam (`AnalysisJobsControllerTransportTest`).

### REFA-5 — `class-identity-members-repository.php` (rank 4)
- **Move:** Extract Class; revisit `delete_orphan_rows()` LEFT JOIN cost (already logged as debt #11 — defer perf, do structure only here).

### REFA-6+ — drains (`split-topology` 799, `outbox-drain` 680)
- **Move:** Split Loop + Extract Function (Fowler). Preserve append-only outbox payload semantics (backend-php; DDIA Ch4 — don't rewrite enqueued meaning).

**Sequencing (historical, 2026-06-07):** REFA-3 (SCSS) in parallel; REFA-1 first among PHP; REFA-2 next (cluster-domain merge churn). **2026-09-09:** that sequence is done. Author remaining work from the epic Deferred list / REFA-9 only.

---

## Out of scope / red flags (do NOT do under this plan)

- **No acx/v1 contract changes.** Changing response shape, removing/renumbering a field, or altering an append-only outbox payload = feature hat. Expand-contract under a real feature task (DDIA Ch4), not a silent refactor.
- **No speculative abstraction** (YAGNI; Fowler Ch3). Refactor toward the change you have, not a future one.
- **No drive-by sprawl.** One logical move per slice; unrelated smell → leave it or record a finding via `review_findings` and defer.
- **TS hook/component extraction** — deferred (all within limits today); revisit if a component crosses 300 LOC or 5 `useState`/3 `useEffect`.
- **Perf items** (#4, #5, #11 in `current-debt.md`) — structure-only here; perf is a separate profiled task.

---

## Convergence

Done when: gates green at HEAD (TS + PHP + `make check-all`); behavior unchanged (char/existing tests prove it); each slice's decision recorded via `record_event` + user notified; no unrelated diff hunks; distilled-doc citation in each decision rationale.

---

## Closure (2026-06-11)

**Status: CLOSED.** All eight ranked targets landed on `main` as REFA-1..8 (REFA-6 covered ranks 6+8; REFA-8 was an emergent fixture-drift slice; REFA-7B was a post-merge review fix). Every slice was characterization-backed, gated through `handoff_close_check(enforce=True)`, and merged behavior-preserving. All 110 review findings across the nine task refs are disposed (integrated/resolved/wontfix/deferred); zero open.

Deferral ledger at closure — every deferred finding now has a live owner:

| Finding | Item | Owner |
|---|---|---|
| REFA-1 210 (high) | sr-009 `run_transactional` migration (11 inline transaction sites) | `current-debt.md` #25 → REFA-9 task plan |
| REFA-1 213 + REFA-4 423 (low) | sr-007 shared status enums | `current-debt.md` #26 |
| REFA-3 287 (high) | deterministic workbench visual baseline (needs seeded fixtures) | debt #12 / E15-6 Playwright harness plan |
| REFA-5 453 (medium) | perf: per-member INSERT loop + LEFT JOIN orphan scan | debt #11 (profiled perf follow-up) |
| REFA-4 424, REFA-6 470, REFA-7 766, REFA-8 746 (low) | shallow per-service tests; split-loop micro-cost; harness split; commit-prefix cosmetics | accepted as-is, no action |

Out-of-scope by design and excluded from this closure: E15-26 (boundary resilience) and E15-27 (scan-pipeline reliability) own the drain-seam and progress-envelope follow-ons; cross-stack Python/TS items from `refactoring-evaluation.md` (H1 repository split, H3/H5 value objects) were never in this plan's WP-plugin scope and remain tracked in that evaluation's triage checklist.
