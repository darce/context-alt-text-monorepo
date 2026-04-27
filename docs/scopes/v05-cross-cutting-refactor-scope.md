# Scope — v0.5.0 Cross-Cutting Refactor

**Source assessment**: [`docs/assessments/wp-alt-context-cross-cutting-assessment.md`](../assessments/wp-alt-context-cross-cutting-assessment.md)
**Target horizon**: v0.5.0 architectural refactor (post-E15 public demo)
**Proposed epic**: E16 (placeholder — to be allocated when epic doc lands)
**Source task**: `SCOPE-v05-cross-cutting-20260427`

---

## 1. Intake (recorded)

Answered via `/scope` intake on 2026-04-27:

| Question | Answer |
|---|---|
| MVP slice | **Whole assessment, sequenced into phases.** All four lenses (REL/DDIA/LAT/RUI) in scope. Output is a phased rollout. |
| Horizon | **v0.5.0 architectural refactor.** Post-E15 demo. Larger refactor budget; allows breaker-store unification, job-state consolidation, UI primitive consolidation. |
| Done signals | Scope note + renamed assessment + candidate task stubs + epic linkage. All four. |
| Rename target | `wp-alt-context-cross-cutting-assessment.md` (most neutral; matches the four-lens framing). |

---

## 2. MVP scope

A v0.5.0 epic that lands the assessment's eight top priorities across **three sequenced phases**, each gated on a concrete completion signal. Phases are ordered to (a) front-load the changes that unblock or simplify later ones, and (b) put user-facing UX changes after the structural fixes that they depend on.

### Phase A — Boundaries & guardrails (REL-URS, REL-FF, DDIA-SI)
Fix unbounded iteration and missing caps before doing anything else. These are the cheapest, highest-leverage changes; later phases assume bounded inputs.

### Phase B — Stability & data unification (REL-CB, REL-BT, DDIA-DD, DDIA-IDP, REL-SS)
Lift breaker state to a single store; move retry sleeps off the request thread; promote reset-projection as the documented rebuild path; add steady-state purges.

### Phase C — UX & SPA consolidation (RUI-ES, RUI-LS, RUI-EL, LAT-OP)
Three shared UI primitives, atomic hook updates with canonical job state, replace `"Unknown"` fallback wall with empty/error/skeleton primitives, accessibility (icon+color pairing).

---

## 3. Success criteria

Per phase, in order:

**Phase A done when**:
- Every controller boundary listed in §3.1 (RX-3, RX-4) and §3.2 (DB-1, DB-3, DB-5) of the assessment has a typed `MAX_*` cap and surfaces `limit`/`total`/`truncated` in the response envelope.
- `MULTIPART_MAX_IMAGES` remains the single canonical owner of the multipart cap; `maxMediaPerBatch` (FE-7) is either removed or renamed.
- A composite-index migration (DB-4) ships for the dashboard's hottest queries.

**Phase B done when**:
- Circuit breaker state is read from a single store by both the proxy controller (RX-2) and the sync surfaces (SY-2). One wedged backend opens one breaker.
- The retry/backoff loop (RX-1) no longer holds a PHP-FPM worker idle: either client-side backoff via `Retry-After`, or async queue worker.
- `class-reset-projection-command.php` is documented as the materialized-view rebuild path; runbook entry exists.
- `acx_sync_conflicts` and transient breaker rows have explicit retention horizons.

**Phase C done when**:
- `EmptyState`, `Skeleton`, `ErrorState` exist in `js/components/ui/` and are adopted by Dashboard, Roster, Workbench, Settings.
- `useRecognitionJobHistory` and `useJobStateMachine*` collapse to a single reducer keyed by a canonical state enum (per sr-007).
- The `"Unknown"` fallback wall on the Dashboard is replaced.
- Status indicators pair color with icon (per sr-004).

---

## 4. Not-Doing

Out-of-scope for this epic, even if relevant to the assessment:

- **Recognition algorithm changes.** `literature/extracted/recognition/` is orthogonal; fairness/loss-function work belongs to the recognition service, out of plugin boundary.
- **Asyncio adoption** in PHP/JS surfaces. The Hattingh book applies to the recognition service, which is out-of-repo per the Plugin Boundary Rule.
- **Code-level micro-refactoring catalog** (Fowler/Beck). Belongs in per-task-plan slices, not as a standalone v0.5.0 deliverable.
- **Net-new features.** No new admin pages, no new endpoints. Refactor only.
- **Backward-compat shims for schema reshapes.** Per the repo's Greenfield Policy there is no production data to preserve; clean rewrites are preferred over compat shims. Migrations may reshape tables directly. Document a compatibility constraint only when a specific surface needs it (e.g. the recognition service wire contract — see next item).
- **Recognition service contract changes.** Any change to the wire contract is a separate cross-repo coordination, not v0.5.0 scope.
- **Performance benchmarking infrastructure.** Phase B references p95/p99 (LAT-TL) but does not build telemetry; reuse existing `class-telemetry.php`.
- **Multisite hardening.** Mentioned in `wp-plugin-literature-digest.md`; not v0.5.0.

---

## 5. Assumptions

Recorded explicitly (do not silently fill these):

- **A1**. v0.4.0 public demo has shipped or is feature-complete before Phase A starts. This work is post-E15.
- **A2**. The recognition service exposes (or will expose) `Retry-After` on 503; Phase B's caller-side fail-fast depends on it. If not, fall back to a queue-worker design.
- **A3**. `class-recognition-proxy-policy.php` (RX-5) is the canonical policy object and remains the place to declare per-policy SLOs. Phase B extends it; does not replace.
- **A4**. The `acx_sync_outbox` table is the canonical write-side contract for sync (per the assessment's read of SY-3); Phase B's idempotency audit assumes outbox rows carry a stable idempotency key.
- **A5**. No production data exists (per the project's Greenfield Policy). Migrations may be ordered freely; no backfill window.

---

## 6. Candidate task stubs

Pre-task-plan stubs. Each becomes a feature-branch task once the epic is opened.

### Phase A
- **E16-1 — Bounded iteration caps across REST + repos + lifecycle migration + contracts**
  Surface: `apps/prototype-wp-alt-context/src/api/`, `apps/prototype-wp-alt-context/src/sovereign/repositories/`, `apps/prototype-wp-alt-context/src/support/class-life-cycle-manager.php` (owns DB-5: `migrate_legacy_roster_data`), and the owning contract surfaces under `docs/agentic/contracts/` (e.g. `cluster-snapshot-api.md`, `clustering-api.md`, `curation-sync-api.md`) and `packages/shared-contracts/`. Acceptance: every site listed in RX-3 / RX-4 / DB-1 / DB-3 / DB-5 has a typed `MAX_*` cap and surfaces the `limit` / `total` / `truncated` triple in its response envelope; the matching contract/schema documents are updated in the same slice (per the planning-review checklist's same-slice contract rule); tests cover the cap boundary, including DB-5's activation-time legacy migration.
- **E16-2 — `maxMediaPerBatch` knob disambiguation**
  Surface: `js/admin/api/config.ts`, `js/admin/api/recognition/scanApi.ts`. Acceptance: knob removed or renamed; `MULTIPART_MAX_IMAGES=5` remains the single canonical owner.
- **E16-3 — Composite indexes for hot UI queries**
  Surface: `src/support/class-life-cycle-manager.php` (dbDelta). Acceptance: `(tenant_id, status, updated_at DESC)` (and equivalents) on the dashboard's read paths; query plan verified.

### Phase B
- **E16-4 — Unify circuit-breaker store across proxy + sync**
  Surface: `src/api/class-abstract-recognition-proxy-controller.php`, `src/sovereign/sync/`. Acceptance: one breaker per backend base URL; both surfaces consult the same state.
- **E16-5 — Move retry sleeps off the request thread**
  Surface: `src/api/class-abstract-recognition-proxy-controller.php` retry loop. Acceptance: no `usleep()` on the controller hot path; either client-side backoff or queue worker.
- **E16-6 — Reset-projection as documented rebuild path**
  Surface: `src/cli/class-reset-projection-command.php`, `src/sovereign/sync/class-snapshot-projector.php`. Acceptance: command docblock declares it the materialized-view rebuild; runbook entry in `apps/prototype-wp-alt-context/docs/`.
- **E16-7 — Steady-state purges**
  Surface: `src/sovereign/repositories/class-conflict-repository.php`, transient breaker storage. Acceptance: explicit retention horizon per accumulating table; cron-driven purge with metrics.

### Phase C
- **E16-8 — Shared UI primitives (`EmptyState`, `Skeleton`, `ErrorState`)**
  Surface: `js/components/ui/`. Acceptance: three primitives ship with stories/tests; adopted on Dashboard, Roster, Workbench, Settings.
- **E16-9 — Canonical job-state reducer**
  Surface: `js/admin/hooks/useRecognitionJobHistory.ts`, `useJobStateMachine*`. Acceptance: single reducer + state enum (per sr-007); one mutation per network event.
- **E16-10 — Status-indicator color+icon pairing**
  Surface: `js/components/ui/`, page-level adopters. Acceptance: every status surface pairs color (token) with an icon (per sr-004); a11y check passes.

---

## 7. Phase gates

Promotion criteria between phases:

- **A → B**: Phase A merged; no new unbounded-iteration findings on a fresh `branch-review` of the touched surfaces. (The envelope-cap contract update is required *inside* E16-1's acceptance, not deferred to this gate — see §6.)
- **B → C**: Phase B merged; breaker-state unification verified by an integration test that wedges the backend and observes one breaker, not two; reset-projection runbook exercised at least once.
- **C → done**: Phase C merged; the `"Unknown"` fallback wall is gone; canonical job-state reducer powers Dashboard + Workbench.

---

## 8. Epic linkage

This scope note is the **pre-epic artifact**. The epic itself (proposed E16) should:

- Reference this note as `Source scope` in its frontmatter.
- Name itself something like `v0.5.0 Cross-Cutting Refactor — Stability, Data, UX`.
- Allocate the 10 candidate tasks above as its task surface; do not invent new ones during epic drafting (changes go through a follow-on `/scope` pass).
- Be linked from the active-epics list in `CLAUDE.md` once allocated.

**Task-plan creation is gated on epic allocation.** Per the planning pipeline's traceability rule, `/incremental-implementation` for E16-1..E16-10 must not run until the E16 epic doc lands and links this scope note. The epic-allocation step is itself the first deliverable and should be sized as a small planning slice — epic doc draft, links to this scope and the assessment, and an `Active epics` update in `CLAUDE.md`. Skipping that step would leave the resulting task plans without the spec/epic traceability the planning-review checklist requires.

---

## 9. References

- Assessment: [`docs/assessments/wp-alt-context-cross-cutting-assessment.md`](../assessments/wp-alt-context-cross-cutting-assessment.md)
- Companion (WP-canonical patterns): [`literature/extracted/wp/wp-plugin-literature-digest.md`](../../literature/extracted/wp/wp-plugin-literature-digest.md)
- Active epic landscape: [`CLAUDE.md`](../../CLAUDE.md) (E15 v0.4.0, E14 v0.3.1)
- Project rules: sr-004 (tokens), sr-007 (canonical enums), sr-008 (parameter slippery slope) — see `CLAUDE.md`.
