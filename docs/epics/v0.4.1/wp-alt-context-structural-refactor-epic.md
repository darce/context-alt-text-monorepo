# E18. WP Alt-Context Plugin Structural Refactor (v0.4.1)

> **Epic Short ID**: REFA
>
> - **Date**: 2026-06-07
> - **Author**: Claude (claude-opus-4-8)
>
> Derived from the scratch ROI note `docs/tasks/tech-debt/wp-alt-context-initial-refactoring-plan.md`.
> Historical 2026-06-07 scan was `main` HEAD `0a955f1c`. **Re-verified 2026-09-09** against this checkout's plugin sources. Treat the companion's Methods column as historical and unreliable (it listed clusters-repository 60 vs the 2026-06-07 epic's 34 vs **23 public methods / 168 LOC now**). Prefer this table + a fresh `grep -c 'public function'` / `wc -l` at authoring time. REFA-1..8 already landed (companion Closure 2026-06-11); remaining drain/transaction work is REFA-9, not a restart of REFA-1..8.

## Objective

Make the WP Alt-Context plugin core maintainable — thin composition-root controllers, responsibility-split repositories, Split-Loop drains, and a fully tokenized workbench stylesheet — **without changing observable behavior**, so near-term feature work (E14/E15) edits small focused units instead of god classes.

## Problem Statement

Seven PHP files are ≥680 LOC (top two over 1,150) with 21–35 declared methods each, each mixing route registration, request parsing, business logic, transaction control, and persistence. `_workbench.scss` (1,159 LOC) violates sr-004 across all five governed families — 11 hex, raw radii (`999px`/`50%`/`4-10px`), **35 raw `font-size`**, **13 raw `font-weight`**, **1 raw `box-shadow`**, plus spacing `px` (the "83 px" figure counts only `px`, so it omits the rem font-sizes, weights, and shadow). Worse, `--acx-radius-*`/`--acx-text-*` are referenced but defined nowhere (18 dangling `var()`), so those sites render unstyled today. Change risk is concentrated, unit isolation is impossible, and the `acx/v1` surface is hard to reason about — every edit risks the whole controller/repository.

## UX Vision

Developer/operator experience after the epic: editing one cluster operation touches one small service, not a 1,257-line controller; a repository read change cannot regress a mutation path; PR reviews are scoped to a single responsibility; the workbench renders identically but its styles are token-driven and themeable.

## Constraints

- **Behavior-preserving only.** No `acx/v1` response-shape change, no field rename/renumber, no outbox-payload semantic change (rg-002, DDIA Ch4). Contract changes are a separate feature epic.
- **Two Hats (Fowler Ch2).** Refactor XOR feature per commit.
- **Per-task pre-merge gate.** Each child task (`REFA-1` … `REFA-6`) passes its own `handoff_close_check(enforce=True)` before merge.
- **Transaction integrity (sr-009 + rg-002).** `run_transactional` **now exists** (`src/support/trait-runs-transactional.php`) and is used by the extracted cluster mutation services. Do **not** assume a global "preserve inline transactions" rule: verify per file. 2026-09-09: `class-split-topology-command-drain.php` still inlines `START TRANSACTION`/`COMMIT`/`ROLLBACK` around apply_created_clusters / apply_member_rows / finalize_snapshot (~L771–798). `class-outbox-drain.php` has **zero** in-file `START TRANSACTION`/`COMMIT`. `class-clusters-repository.php` has zero in-file transactions. Wrapper adoption for remaining inline sites is REFA-9.
- **Repo rules.** sr-004 (tokens), sr-008 (param objects), rg-005 (schema parity), rg-015 (recognition-proxy resilience seam), rg-016 (autoload parity for new `class-*.php`).
- **Greenfield but incremental.** No prod data/migrations; god-class splits are cross-cutting, so still one verified step at a time.

## Terminology

- **God Class / Large Class**: too many responsibilities; measured by LOC + declared-method count + distinct route/operation clusters (Fowler Ch3).
- **Characterization test**: pins current behavior before a refactor; here a `WP_REST_Request` via `rest_do_request()` serialized to a committed golden JSON fixture, asserted byte-equal pre/post.
- **Composition root**: controller keeps routing + parsing, delegates logic to injected services (mirror `class-recognition-controller.php`).
- **Epic short id / task refs**: this epic's short id is `REFA`; its task plans/tasks are `REFA-1` … `REFA-7`.

## Current State

**2026-06-07 baseline** (pre-REFA, `0a955f1c`) is historical. Do not author REFA-3..6 follow-ups from those numbers — the companion Methods column was inflated vs even that baseline (analysis-jobs 54 vs 35; identity-members 55 vs 28).

**Re-verified 2026-09-09** (`public function` count includes constructors; LOC = `wc -l`):

| Target | LOC now | public methods now | 2026-06-07 epic | Companion Methods (unreliable) | Inline txn now | Safety net note |
|---|---|---|---|---|---|---|
| `src/api/class-cluster-mutations-controller.php` | 509 | 21 | 1257 / 21 | 51 | none (moved to services + `run_transactional`) | partial at epic time; REFA-1 landed |
| `src/sovereign/repositories/class-clusters-repository.php` | 168 | 23 | 1164 / 34 | 60 | **none** | REFA-2 landed; "yes = a suite exists" overstated mutation/delete coverage at epic time (`delete_cluster_with_members` had no direct test) |
| `src/api/class-analysis-jobs-controller.php` | 280 | 15 | 1144 / 35 | 54 | none | REFA-4 landed; treat historical "yes" as partial |
| `src/sovereign/repositories/class-identity-members-repository.php` | 138 | 15 | 1045 / 28 | 55 | none | REFA-5 landed; treat historical "yes" as partial |
| `js/admin/styles/components/_workbench.scss` | 1425 | — | 1159; "83 px" | "80 px" | n/a | 2026-09-09: **66** `\d+px` literals, **0** hex, 38 `font-size`, 18 `font-weight`, 1 `box-shadow`. Re-count at any further token slice; the 80 vs 83 disagreement is obsolete. |
| `src/sovereign/sync/class-split-topology-command-drain.php` | 1025 | 3 | 799 / 21 | 44 | **yes** — one `START TRANSACTION` at ~L771 with ROLLBACK/COMMIT | grew after REFA-6; remaining inline txn is REFA-9/drain follow-up |
| `src/api/class-clusters-controller.php` | 253 | 14 | 770 / 23 | — | none | REFA-7 landed |
| `src/sovereign/sync/class-outbox-drain.php` | 652 | 14 | 680 / 24 | — | **none** | REFA-6 landed; do not plan "preserve inline transactions" here |

Calibration: God Class was the 2026-06-07 smell; the eight targets are decomposed. `run_transactional` exists and is in use on cluster mutation services. 10 `.tsx` over 300 lines remain deferred (`REFA-TS-DEBT-01`). REFA-1 has merged, so the live REFA-2 merge-churn gate is closed; any new clusters-repo work still sequences after whatever PHP REFA task is live.

**px/hex done-criterion for a future token pass:** zero raw sr-004-governed literals (color, radius, font-size, font-weight, shadow). Count them at slice start with a script, not from this table.

## Applied Concepts from Sources

| Source | Concept | Epic application |
|---|---|---|
| `docs/tasks/tech-debt/refactoring-evaluation.md` (Fowler) | Extract Class, Split Phase, Split Loop, Large Class | primary PHP moves per target |
| `docs/tasks/tech-debt/refactoring-ui-evaluation.md` | design-token system | `_workbench.scss` token swap (sr-004) |
| `docs/tasks/tech-debt/refactoring-typescript-evaluation.md` | component decomposition | deferred TS pass (`REFA-TS-DEBT-01`) |
| Release It Ch5 | timeouts + circuit breaker | preserve recognition-proxy resilience seam (rg-015) |
| DDIA Ch4 | append-only/expand-contract | preserve outbox payload semantics (rg-002) |

## Git Workflow Assessment

Each target is its own child task ref + feature branch + PR, reviewed and merged independently. `REFA-3` (SCSS) is path-independent and may run any time in parallel; PHP child tasks share `src/` and run sequentially to minimize merge churn. This epic doc is the coordinator; no code lands on an epic branch.

## Target Architecture

Controllers reduce to thin composition roots (route registration + request parsing) delegating to focused services under `src/api/services/` (`AltContext\Api\Services\`). Repositories split by cohesive field+method subset, separating read/query from mutation/curation. Drains read as `Split Loop` + extracted functions with preserved append-only semantics. `_workbench.scss` uses only `--acx-*` tokens. Behavior is proven unchanged by characterization (golden JSON) + existing tests before any structure moves.

### Design Decisions

| Decision | Rationale |
|---|---|
| Composition root + services (not god controller) | isolates each operation; mirrors existing `class-recognition-controller.php` |
| One target = one child task/PR | per-task pre-merge gate; small reversible review surface; matches isolation rules |
| Promote to epic (not single mega task plan) | 6 independently-merged PRs is epic-shaped; per-target task plans fit `TASK_PLAN.template` |
| Defer `run_transactional` + TS splits | keep refactor behavior-preserving and bounded; lower-blast-radius debt later |

### Data Model

Process/evidence model (not product schema):

- **Source of truth**: each child task's checked-in task plan + this epic.
- **Evidence flow**: per-target golden-JSON fixtures (REST parity) + existing PHPUnit suites + `make check-all`, tied to each child task's HEAD via `record_event(test_result)`.
- **Gate**: per child task `handoff_close_check(enforce=True)` with zero open findings before merge.

## Phased Delivery

### Phase 1: Cluster domain -- landed (REFA-1, REFA-2)

> **Status**: landed on `main` (companion Closure 2026-06-11)
> **Task plans**: `docs/tasks/tech-debt/REFA-1-cluster-mutations-controller-task-plan.md`; `docs/tasks/tech-debt/REFA-2-clusters-repository-task-plan.md`

**Goal**: Decompose the highest-ROI, mutation-critical cluster controller + repository.

Deliverables:
- REFA-1: cluster-mutations controller → composition root + per-operation services covering all 11 cluster-mutation routes, characterization safety net first.
- REFA-2: clusters repository split read/query vs. curation-reset/delete-with-members; N+1 audit; rg-005 schema-parity test.

Exit criteria:
- Both controllers/repos shrink to focused units; all existing + new tests green; `acx/v1` responses byte-identical.

### Phase 2: Stylesheet token debt -- landed (REFA-3); residual literals remain

> **Status**: REFA-3 landed; 2026-09-09 still shows 66 px / 38 font-size / 18 font-weight / 1 box-shadow in `_workbench.scss` (file grew 1159→1425 LOC). Further tokenization is a new slice, not a restart of REFA-3's original "80 vs 83 px" count.
> **Task plans**: `docs/tasks/tech-debt/REFA-3-workbench-scss-tokenization-task-plan.md`

**Goal**: Tokenize `_workbench.scss`.

Deliverables:
- REFA-3: tokenize all five sr-004 families in `_workbench.scss` — color (11 hex), radius, font-size (35, `--acx-text-*`), font-weight (13), shadow (1) — defining the missing/dangling token families in `js/admin/styles/tokens/` first. Token-surface ownership spans all consumers: defining `--acx-radius-*`/`--acx-text-*` also corrects `_media-selection.scss` (+6 dangling refs), which REFA-3 must verify. Spacing `px` map to `--acx-space-*`; `1px` borders and component layout widths are out of sr-004 scope (kept raw with rationale or an explicit new family). Scope authority is the REFA-3 task plan.

Exit criteria:
- Zero raw sr-004-governed literals (color, radius, font-size, font-weight, shadow); spacing on `--acx-space-*`. `npm run build` + `lint` green; `npm run a11y:localwp` green. Visual matches a **re-reviewed baseline** that incorporates the intended radius/font corrections (defining the dangling `--acx-radius-*`/`--acx-text-*` tokens changes rendering at the 18 previously-unstyled sites — this is a deliberate, reviewed correction, not "unchanged"). A `toHaveScreenshot` baseline is established as the durable guard.

### Phase 3: Job lifecycle + members repository -- landed (REFA-4, REFA-5)

> **Status**: landed on `main` (companion Closure 2026-06-11)
> **Task plans**: `docs/tasks/tech-debt/REFA-4-analysis-jobs-controller-task-plan.md`; `docs/tasks/tech-debt/REFA-5-identity-members-repository-task-plan.md`

**Goal**: Untangle analysis-jobs lifecycle and split the identity-members repository.

Deliverables:
- REFA-4: analysis-jobs controller → Extract Class + Split Phase (fetch/transform/persist); preserve transport seam.
- REFA-5: identity-members repository Extract Class (structure only; perf deferred).

Exit criteria:
- Transport + repository tests green; behavior unchanged.

### Phase 4: Sync drains -- landed (REFA-6); split-topology still has one inline transaction

> **Status**: REFA-6 landed. 2026-09-09 per-file check: split-topology-command-drain still inlines START/COMMIT/ROLLBACK; outbox-drain does not. Remaining wrapper work is REFA-9, not a second REFA-6.
> **Task plans**: `docs/tasks/tech-debt/REFA-6-sync-drains-task-plan.md`; `docs/tasks/tech-debt/REFA-9-run-transactional-task-plan.md`

**Goal**: Simplify the two drains.

Deliverables:
- REFA-6: `split-topology-command-drain` + `outbox-drain` → Split Loop + Extract Function; preserve append-only semantics. Inline transactions: **verify per file** (2026-09-09: split-topology still inlines START/COMMIT/ROLLBACK; outbox-drain has none). Do not copy a global "preserve inline transactions" constraint onto outbox-drain.

Exit criteria:
- Drain tests green; enqueue/drain meaning unchanged.

### Phase 5: Cluster read controller -- landed (REFA-7)

> **Status**: landed on `main` (companion Closure 2026-06-11)
> **Task plans**: `docs/tasks/tech-debt/REFA-7-clusters-controller-task-plan.md`

**Goal**: Decompose the read-only cluster controller — the last unassigned Current State target and the read sibling to REFA-1's mutations controller.

Deliverables:
- REFA-7: `class-clusters-controller.php` (5 GET routes, no inline transactions, no SSE) → thin composition root + `ClusterReadService` / `ClusterProjectionSyncService` / `ClusterResponseEnvelopeService`; preserve the dual local-projection/backend-proxy read seam, the bootstrap/targeted-sync side effects, the `perform_bootstrap_sync` WP-action callback, and the facade delegation + public repo getters.

Exit criteria:
- All 5 `acx/v1` routes byte-identical on both branches; sync side effects + facade unchanged; controller reduced to composition root.

> **Sequencing**: REFA-7 shares `src/api/`, `src/api/services/`, the facade, and the `services/` autoload block with merged REFA-1/REFA-2/REFA-4 and pending REFA-5 — runs sequentially with REFA-5 (no concurrent live PHP REFA task).

## External Dependencies

| Dependency | Owner | Status | Blocks |
|---|---|---|---|
| Distilled refactoring literature (`MAINT-refactor-lit-distill-20260607`) | docs | In progress | nothing — citations use the existing `refactoring-*.md` evaluations until distilled docs land |

## Code Anchors

| Layer | File | Note |
|---|---|---|
| controller pattern | `src/api/class-recognition-controller.php` | composition-root mirror |
| autoload | `src/api/class-api.php` | controller/drain registrar — rg-016 `require_once` owner |
| resilience seam | `src/api/class-abstract-recognition-proxy-controller.php`, `src/api/class-recognition-proxy-policy.php` | rg-015 — do not regress |
| schema | `src/support/class-life-cycle-manager.php` | rg-005 schema-key cross-check |
| targets | the eight files in Current State | refactor subjects |

---

# Consolidated Checklist

## Phase 1: Cluster domain -- landed

- [x] REFA-1 merged (cluster-mutations controller → composition root + services).
- [x] REFA-2 merged (clusters repository split + N+1 audit + schema-parity test).

## Phase 2: Stylesheet token debt -- landed (residuals remain; re-count at next slice)

- [x] REFA-3 merged (`_workbench.scss` tokenized across all 5 sr-004 families; dangling `--acx-radius-*`/`--acx-text-*` defined; radius/font corrections re-baselined; `toHaveScreenshot` guard added; `_media-selection.scss` consumers verified). Residual raw literals: see Current State 2026-09-09 recount.

## Phase 3: Job lifecycle + members repository -- landed

- [x] REFA-4 merged (analysis-jobs Extract Class + Split Phase).
- [x] REFA-5 merged (identity-members repository Extract Class, structure only).

## Phase 4: Sync drains -- landed (split-topology inline txn remains)

- [x] REFA-6 merged (drains Split Loop + Extract Function).

## Phase 5: Cluster read controller -- landed

- [x] REFA-7 merged (`class-clusters-controller.php` → composition root + read/projection-sync/envelope services; dual-path read seam + sync side effects + facade preserved).

## Deferred (Post-v0.4.1)

- [ ] TS component splits — 10 oversized `.tsx` (finding `REFA-TS-DEBT-01`); dedicated pass.
- [ ] `run_transactional(callable)` adoption across **remaining** inline-transaction sites (REFA-9). Helper exists; cluster mutation services already use it. 2026-09-09 leftover: split-topology-command-drain inlines START/COMMIT/ROLLBACK; outbox-drain has none.
- [ ] Repository perf items (e.g. `delete_orphan_rows()` LEFT JOIN cost) — separate profiled task.
- [ ] Delete superseded scratch note `wp-alt-context-initial-refactoring-plan.md` (finding `REFA-PA-07`).
