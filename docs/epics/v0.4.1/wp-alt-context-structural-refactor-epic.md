# E18. WP Alt-Context Plugin Structural Refactor (v0.4.1)

> **Epic Short ID**: REFA
>
> - **Date**: 2026-06-07
> - **Author**: Claude (claude-opus-4-8)
>
> Derived from the scratch ROI note `docs/tasks/tech-debt/wp-alt-context-initial-refactoring-plan.md`.
> Quantitative claims re-verified against `main` HEAD `0a955f1c` (2026-06-07).

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
- **Transaction integrity (sr-009 + rg-002).** Transactions are inlined today (`$wpdb->query('START TRANSACTION'|…)`); no `run_transactional` helper exists. Preserve exact boundaries; wrapper adoption is deferred.
- **Repo rules.** sr-004 (tokens), sr-008 (param objects), rg-005 (schema parity), rg-015 (recognition-proxy resilience seam), rg-016 (autoload parity for new `class-*.php`).
- **Greenfield but incremental.** No prod data/migrations; god-class splits are cross-cutting, so still one verified step at a time.

## Terminology

- **God Class / Large Class**: too many responsibilities; measured by LOC + declared-method count + distinct route/operation clusters (Fowler Ch3).
- **Characterization test**: pins current behavior before a refactor; here a `WP_REST_Request` via `rest_do_request()` serialized to a committed golden JSON fixture, asserted byte-equal pre/post.
- **Composition root**: controller keeps routing + parsing, delegates logic to injected services (mirror `class-recognition-controller.php`).
- **Epic short id / task refs**: this epic's short id is `REFA`; its task plans/tasks are `REFA-1` … `REFA-7`.

## Current State

Verified against `main` HEAD `0a955f1c` (2026-06-07):

| Target | LOC | Decl. methods | REST routes | Safety net |
|---|---|---|---|---|
| `src/api/class-cluster-mutations-controller.php` | 1257 | 21 | 11 | partial (`ClusterMutationsControllerDualWriteTest`) |
| `src/sovereign/repositories/class-clusters-repository.php` | 1164 | 34 | — | yes |
| `src/api/class-analysis-jobs-controller.php` | 1144 | 35 | 8 | yes (+ transport) |
| `src/sovereign/repositories/class-identity-members-repository.php` | 1045 | 28 | — | yes |
| `js/admin/styles/components/_workbench.scss` | 1159 | — | — | Playwright axe a11y (LocalWP); **no visual snapshot baseline yet** |
| `src/sovereign/sync/class-split-topology-command-drain.php` | 799 | 21 | — | yes (REFA-6) |
| `src/api/class-clusters-controller.php` | 770 | 23 | 5 | yes (REFA-7, Phase 5) |
| `src/sovereign/sync/class-outbox-drain.php` | 680 | 24 | — | yes (REFA-6) |

Calibration: 0 `switch` smell (1 in analysis-jobs) — God Class is the dominant smell, not Repeated Switches; `run_transactional` does not exist; 10 `.tsx` exceed the 300-line limit (deferred, finding `REFA-TS-DEBT-01`). All eight Current State targets are now assigned to a child task: the read-only `class-clusters-controller.php` (5 GET routes, no inline transactions, no SSE) is REFA-7 under Phase 5 — it was the lone orphan and is the read sibling to REFA-1's mutations controller.

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

### Phase 1: Cluster domain -- not-started

> **Status**: not-started
> **Task plans**: `docs/tasks/tech-debt/REFA-1-cluster-mutations-controller-task-plan.md` (drafted); `REFA-2` (clusters repository, scope below)

**Goal**: Decompose the highest-ROI, mutation-critical cluster controller + repository.

Deliverables:
- REFA-1: cluster-mutations controller → composition root + per-operation services covering all 11 cluster-mutation routes, characterization safety net first.
- REFA-2: clusters repository split read/query vs. curation-reset/delete-with-members; N+1 audit; rg-005 schema-parity test.

Exit criteria:
- Both controllers/repos shrink to focused units; all existing + new tests green; `acx/v1` responses byte-identical.

### Phase 2: Stylesheet token debt -- not-started

> **Status**: not-started
> **Task plans**: `REFA-3` (scope below) — parallel, any time

**Goal**: Tokenize `_workbench.scss`.

Deliverables:
- REFA-3: tokenize all five sr-004 families in `_workbench.scss` — color (11 hex), radius, font-size (35, `--acx-text-*`), font-weight (13), shadow (1) — defining the missing/dangling token families in `js/admin/styles/tokens/` first. Token-surface ownership spans all consumers: defining `--acx-radius-*`/`--acx-text-*` also corrects `_media-selection.scss` (+6 dangling refs), which REFA-3 must verify. Spacing `px` map to `--acx-space-*`; `1px` borders and component layout widths are out of sr-004 scope (kept raw with rationale or an explicit new family). Scope authority is the REFA-3 task plan.

Exit criteria:
- Zero raw sr-004-governed literals (color, radius, font-size, font-weight, shadow); spacing on `--acx-space-*`. `npm run build` + `lint` green; `npm run a11y:localwp` green. Visual matches a **re-reviewed baseline** that incorporates the intended radius/font corrections (defining the dangling `--acx-radius-*`/`--acx-text-*` tokens changes rendering at the 18 previously-unstyled sites — this is a deliberate, reviewed correction, not "unchanged"). A `toHaveScreenshot` baseline is established as the durable guard.

### Phase 3: Job lifecycle + members repository -- not-started

> **Status**: not-started
> **Task plans**: `REFA-4`, `REFA-5` (scope below)

**Goal**: Untangle analysis-jobs lifecycle and split the identity-members repository.

Deliverables:
- REFA-4: analysis-jobs controller → Extract Class + Split Phase (fetch/transform/persist); preserve transport seam.
- REFA-5: identity-members repository Extract Class (structure only; perf deferred).

Exit criteria:
- Transport + repository tests green; behavior unchanged.

### Phase 4: Sync drains -- not-started

> **Status**: not-started
> **Task plans**: `REFA-6` (scope below)

**Goal**: Simplify the two drains.

Deliverables:
- REFA-6: `split-topology-command-drain` + `outbox-drain` → Split Loop + Extract Function; preserve append-only semantics + inline transactions.

Exit criteria:
- Drain tests green; enqueue/drain meaning unchanged.

### Phase 5: Cluster read controller -- not-started

> **Status**: not-started
> **Task plans**: `docs/tasks/tech-debt/REFA-7-clusters-controller-task-plan.md` (drafted)

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

## Phase 1: Cluster domain -- not-started

- [ ] REFA-1 merged (cluster-mutations controller → composition root + services).
- [ ] REFA-2 merged (clusters repository split + N+1 audit + schema-parity test).

## Phase 2: Stylesheet token debt -- not-started

- [ ] REFA-3 merged (`_workbench.scss` tokenized across all 5 sr-004 families; dangling `--acx-radius-*`/`--acx-text-*` defined; radius/font corrections re-baselined; `toHaveScreenshot` guard added; `_media-selection.scss` consumers verified).

## Phase 3: Job lifecycle + members repository -- not-started

- [ ] REFA-4 merged (analysis-jobs Extract Class + Split Phase).
- [ ] REFA-5 merged (identity-members repository Extract Class, structure only).

## Phase 4: Sync drains -- not-started

- [ ] REFA-6 merged (drains Split Loop + Extract Function).

## Phase 5: Cluster read controller -- not-started

- [ ] REFA-7 merged (`class-clusters-controller.php` → composition root + read/projection-sync/envelope services; dual-path read seam + sync side effects + facade preserved).

## Deferred (Post-v0.4.1)

- [ ] TS component splits — 10 oversized `.tsx` (finding `REFA-TS-DEBT-01`); dedicated pass.
- [ ] `run_transactional(callable)` extraction + adoption across inline-transaction sites (repo-wide sr-009 debt).
- [ ] Repository perf items (e.g. `delete_orphan_rows()` LEFT JOIN cost) — separate profiled task.
- [ ] Delete superseded scratch note `wp-alt-context-initial-refactoring-plan.md` (finding `REFA-PA-07`).
