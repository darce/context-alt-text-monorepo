# Public MVP UX/UI Polish Roadmap (2026-07-04)

> **Status**: Roadmap seed (pre-epic) — decompose into an epic (proposed short ID **E20**) before execution.
> **Task**: ROADMAP-REALIGN · `feature/roadmap-realign`
> **Grounding**: [workbench-ui-refactor-assessment-2026-07-04.md](../assessments/current/workbench-ui-refactor-assessment-2026-07-04.md) (WBUX-1) + [roster-dashboard-workbench-ux-assessment-2026-07-04.md](../assessments/current/roster-dashboard-workbench-ux-assessment-2026-07-04.md) (WBUX-2); epic/roadmap/tech-debt realignment audit (handoff task `ROADMAP-REALIGN`).
> **Goal**: take the public demo (`demo.altcontext.com`, partially launched via E15-29) from "functionally live" to a **polished public MVP** — UX/UI/design quality a first-time visitor reads as a finished product.
> **Hard constraint (unchanged from WBUX-1/2)**: data sovereignty — cluster/person/findings display stays offline-capable from the local WP projection; compute stays remote; no backend contract changes required by any phase here.

---

## 1. Why a realignment

The planning surfaces have drifted from reality. This roadmap re-baselines them and sequences the WBUX-1/2 backlog by visitor-facing impact.

| Surface | Documented state | Actual state (handoff DB + git, 2026-07-04) |
| --- | --- | --- |
| E18/REFA epic (`docs/epics/v0.4.1/wp-alt-context-structural-refactor-epic.md`) | "not-started, all 5 phases" | **REFA-1..10 landed** (handoff rows done, June 7–11; umbrella plan closed, 110 findings disposed). Only deferred remainder: TS component splits (REFA-TS-DEBT-01), profiled perf items |
| E15 epic Phases 3/4/6 | many unchecked items (E15-28 slices, E15-22 gate, E15-13/15/16/17 staged) | E15-28, E15-22, E15-23, E15-13 done; E15-15/16 done via E15-20; **E15-17 slices 1–2 landed, 3–4 open**; E15-24/25/26/31 done. Open: **E15-29 execution mid-flight** (`feature/e15-29` unmerged, all slices unchecked), `codex/e15-31-review-fixes` unmerged |
| `roadmap-v4.md` | header `Status: Active` | Epics A–C 100% delivered; archival. Its "UX polish" content is superseded by WBUX-1/2 |
| Dashboard UX assessment 2026-05-05 | Draft, unowned | Superseded by WBUX-2 §4 (which re-endorses F4/F5/F6 and adds cull/keep dispositions) |
| Roster workflow assessment 2026-05-05 | spec drafted, slices pending | Partially delivered (E15-13 queues, E15-17 slices 1–2); remainder absorbed into WBUX-2 §1–3 |

Realignment actions are Phase R below; the polish work itself is Phases 0–5.

## 2. Scope

**In**: WordPress admin product surfaces — Workbench, Roster, Dashboard, plus the cross-surface status/link/design-token systems. All slices consume existing endpoints and `data_source` markers (rg-015).
**Out**: backend/service work (E16 themes A–D), description-service product surface (E19, tracked in [context-aware-image-description-roadmap-2026-06-13.md](context-aware-image-description-roadmap-2026-06-13.md)), SaaS operations, marketing/landing page (operations plan P1 item, separate repo). E19-3's review/history UI will consume the design system built in Phase 2 — sequence E19-3 after it.

## 3. Guiding heuristics (impact model)

Impact ranking below weighs: (a) **first-impression surface area** — what every demo visitor sees in the first two minutes (dashboard landing, status strips, the scan→review loop); (b) **cost asymmetry** — deletion and consolidation before construction (Fowler: Remove Dead Code is the cheapest refactoring); (c) **preparatory refactoring order** — token/status foundations before visual re-grouping so re-baselining happens once; (d) **repo rules as hard gates** — sr-004 (icon+color+word status), sr-007 (centralized status enums), sr-008 (grouped params/context), rg-002 (atomic writes), rg-003 (zero-state reachability), rg-015 (no invented metadata); (e) **codebase-map limits** — 300-line components, complexity hotspots already measured in WBUX-1 §1 (`useClusterSaveAction` 32, `buildMilestones` 26, `WorkbenchContextValue` ~70 fields, `_workbench.scss` 1,161 lines).

## 4. Phases (impact-ordered)

### Phase 0 — Finish the launch (gating, not polish)

Polish is unverifiable against a half-launched demo; every later phase's evidence capture assumes a live URL.

- Complete E15-29 slices 0–4: URL/DNS cutover off the `sslip.io` interim, 100-image clustering seed deployed, walkthrough + clustering acceptance gate (≥1 multi-image cluster), sovereignty kill-API proof; merge `feature/e15-29` through the pre-merge gate.
- Land or disposition `codex/e15-31-review-fixes` (admin console review fixes) — an unmerged review-fix branch is drift risk against every later slice.
- Exit: demo URL public over valid TLS, E15 Phase 3 marked live, both stray branches resolved.

**Impact**: absolute — nothing ships publicly without it. **Effort**: execution of an already-built kit.

### Phase 1 — Status truth & dead-weight deletion (highest polish-per-effort)

First-impression honesty: kill the jargon soup and the panels that promise features that don't exist. Mostly deletion and consolidation.

- **P1-A · Status view-model consolidation** (WBUX-1 S1). One `SyncPresentation` derived from `resolveEffectiveSyncHealth`; one status strip; delete the 8-branch `SyncStatusIndicator`, 3 of 4 job-status surfaces, and translate sync-internals vocabulary at the boundary ("Topology backlog…" → "n changes waiting to sync"). Unblocks every visual phase; fixes WBUX-1 §2.2 wholesale.
- **P1-B · Dashboard cull pass** (WBUX-2 S9). Delete Batch Operations panel; state-aware OrientationCard (`people_count === 0` gate); demote DescribePanel from hero to disclosure; give Library Coverage its missing CTA (→ Workbench `status=missing`); humanize Recent Activity rows; delete the dead `before_grid` branch. The dashboard is the admin landing page — highest visitor exposure per line changed.
- **P1-C · Kill the Confirm tab** (WBUX-1 S3). Delete the unfulfilled "Compare before/after" promise; pipeline auto-sequencing already true in the state machine; manual re-cluster + job history + Conflict/Dead-letter overlays move to an "Advanced: jobs & recovery" drawer with `?overlay=`/`?tab=` shims (e2e specs depend on them).

**Impact**: every visitor, first two minutes. **Effort**: low — net-negative LOC except the view-model.

### Phase 2 — Design-token foundation (preparatory; do before any visual re-grouping)

WBUX-1 S5 + the open remainder of `refactoring-ui-evaluation.md`. One re-baseline of visual-regression snapshots, then Phases 3–5 diff cleanly against it.

- Real type ramp (12/14/16/18/20/24/30px — headings finally exist; kill the 0.68–1.0rem "snap map"); 9-shade grey + primary ramps behind existing semantic aliases; 5-level elevation scale (`--acx-shadow-1..5`); purge the 80+ raw hex literals (67 in `_identity-cluster-list.scss`); spacing dedupe (8/10/12 near-duplicates).
- sr-004 sweep: every status pill gains icon+word (generalize the JobTimeline ✓●○✕ pattern as the sitewide status vocabulary).
- Extend `workbench-tokenization.test.ts` to all component sheets; split `_workbench.scss` (1,161 lines) per component.
- Closes: `refactoring-ui-evaluation.md` (archive on completion), REFA-3's remaining scope beyond `_workbench.scss`.

**Impact**: indirect but multiplicative — every later screen inherits it; visual re-baseline paid once. **Effort**: pure CSS slice, mechanical, visual-regression-gated.

### Phase 3 — Review flow unification (the core demo loop)

The scan→review→confirm loop is the demo's story. Make it one surface, one primary CTA per state.

- **P3-A · Unified review queue** (WBUX-1 S2 as amended by WBUX-2 S2′). Card-at-a-time queue with filter chips replacing the 4-queue `SuggestionReviewPanel` stack; promote the E15-23 `nextAction` driver from scroll-helper to queue driver; per-item optimistic accept/reject with undo (rg-002-safe: single atomic backend calls); bulk accept becomes a disclosure. **Primary naming = person-commit** via the roster drawer's creatable combobox on the review card; label-only rename demoted to tertiary. E15-13 queue projections (singleton / hard-example / needs-confirmation) render as chips; hard-examples chip carries an explicit "coming soon" state until its review contract lands.
- **P3-B · Media step compaction** (WBUX-1 S4). CTA co-located with the table; table collapses to a summary bar during review; single paginator; receives the dashboard's `status=missing` deep link.
- **P3-C · Offline hardening** (WBUX-1 S7). Fail-fast disabled compute actions when the breaker is open (Nygard); unify per-panel `EmptyStateWarning` variants under the P1-A connectivity model; explicit read-only chip during projection catch-up. Sovereignty invariants table in WBUX-1 §5 is the acceptance contract.

**Impact**: the demo's central interaction; converts "pile of panels" into a legible pipeline. **Effort**: medium — largest construction phase, lands on Phase 1–2 foundations.

### Phase 4 — Roster person-first completion & cross-surface contract

"Workbench decides, Roster curates, Dashboard orients" (WBUX-2 §3).

- **P4-A · Finish E15-17 slices 3–4** (face scrubber; cluster drawer → "Open person review"). Prerequisite for the tab deletion; do not fork its landed design (scrubber action matrix, conservative similarity copy).
- **P4-B · Retire Roster ▸ Clusters as a management tab** (WBUX-2 S8). Clusters remain evidence-in-person-workspace + Workbench queue items; unique ops relocate (person-commit → review card, drag-fix → scrubber, sensitive rescan → Advanced drawer, bulk merge/dismiss → Workbench disclosure made atomic server-side or explicitly progressive — rg-002). Restore always-visible person list + `Add Person` (fixes the standing rg-003 violation); `?cluster=` deep links resolve into the owning person's workspace.
- **P4-C · Cross-surface link contract** (WBUX-2 S10). All CTAs adopt the E15-17 route vocabulary (`?person=` `?queue=` `?face=`); redirect shims for `?tab=clusters` and `?overlay=`; every Workbench person-touching confirm emits "View <name> →". Dashboard GuidanceCard CTAs retarget to the same vocabulary. Decide Retention discoverability (menu item vs dashboard footer link) — currently route-only.

**Impact**: high for return visitors/curation depth; removes the duplicated-with-worse-semantics surface (WBUX-2 §2 capability matrix). **Effort**: medium; strictly after P3-A (queue must exist before the tab's ops relocate).

### Phase 5 — Structural enablers (parallelizable, behavior-preserving)

Code health that keeps Phases 1–4 cheap and future feature work possible; no visible UI change.

- **P5-A · Workbench context decomposition** (WBUX-1 S6). ~70-field `WorkbenchContextValue` → 4 per-concern providers behind selector hooks (sr-008); `ScanActionPanel`'s 14 props → one `ScanRunViewModel`.
- **P5-B · Phase→presentation strategy map** (sr-007). One enum+record module replaces the four phase switches (`buildStatusText` 24, `buildMilestones` 26, `formatJobPhase`, indicator branches) — ends shotgun surgery on pipeline phases.
- **P5-C · Oversized-component splits** (REFA-TS-DEBT-01: 10 oversized `.tsx` against the 300-line map limit), prioritized to files Phases 1–4 touch anyway.

**Impact**: developer velocity + regression resistance; invisible to visitors. **Effort**: medium, fully parallel behind unchanged behavior after P1-A.

### Phase R — Planning-surface realignment (do alongside Phase 0)

Cheap, prevents the next agent cold-start from re-deriving this audit.

- Mark E18/REFA epic closed (Phases 1–5 landed; carry REFA-TS-DEBT-01 → P5-C, perf items → `current-debt.md`).
- Sync E15 epic checkboxes to handoff reality; mark Phase 3 live when E15-29 merges.
- `roadmap-v4.md` header → `Status: Historical` (content delivered); reconcile its unchecked Success Criteria rollup.
- Move `alt-context-dashboard-ux-assessment-2026-05-05.md` and `recognition-roster-suggestion-workflow-assessment-2026-05-05.md` to `docs/assessments/archive/` with "superseded by WBUX-1/2" pointers.
- Add `roadmap-saas-operations.md` to the README index and rename its internal "Epic E16" label (ID collision with the real E16).

## 5. Dependency graph

```
Phase 0 (launch) ──────────────┐
Phase R (realign) ─ parallel ──┤
                               ▼
P1-A status model ──▶ P3-A review queue ──▶ P4-B roster tab retire ──▶ P4-C links
   │                        ▲                      ▲
   ├──▶ P1-C confirm-tab    │                      │
   ├──▶ P3-C offline        │                P4-A E15-17 s3–4 (start anytime)
Phase 2 tokens ─────────────┘  (before any visual re-grouping; one re-baseline)
P1-B dashboard cull (start anytime; CTA retargeting waits on P4-C vocabulary)
Phase 5 structural (parallel after P1-A)
```

## 6. Verification strategy

- Existing harnesses are the gate: `workbench-axe.spec.ts` (a11y), `workbench-visual.spec.ts` (re-baseline once at Phase 2, then every phase diffs), `workbench-evidence.spec.ts` + walkthrough runbook (capture against the live demo URL per phase), `workbench-tokenization.test.ts` (extended in Phase 2), unit suites per component.
- URL-param compat (`?tab=`, `?overlay=`, `?cluster=`) keeps shims until e2e specs migrate — spec migration is part of P4-C's exit, not an afterthought.
- Every phase merges through the standard pre-merge gate (`handoff_close_check(enforce=True)`); findings live in handoff, referenced by ID only.

## 7. Epic decomposition candidates

| ID | Phase | Title | Depends on |
| --- | --- | --- | --- |
| E20-1 | 1 | Sync status view-model + single strip | — |
| E20-2 | 1 | Dashboard cull pass | — |
| E20-3 | 1 | Confirm tab removal + Advanced drawer | E20-1 |
| E20-4 | 2 | Design-token system (type/grey/elevation) + sr-004 sweep | — |
| E20-5 | 3 | Unified review queue + person-commit | E20-1, E20-4 |
| E20-6 | 3 | Media step compaction | E20-4 |
| E20-7 | 3 | Offline fail-fast + read-only mode | E20-1 |
| E20-8 | 4 | E15-17 slices 3–4 completion (adopt or re-home) | — |
| E20-9 | 4 | Roster Clusters-tab retirement, person-first roster | E20-5, E20-8 |
| E20-10 | 4 | Cross-surface link contract + shim/spec migration | E20-9 |
| E20-11 | 5 | Workbench context decomposition + phase strategy map | E20-1 |

Phase 0 stays under E15 (E15-29 + follow-on DNS cutover task); Phase R runs as MAINT-scoped doc slices.

## 8. Success criteria

- [ ] Demo live on `demo.altcontext.com` with the E15-29 clustering acceptance gate met (Phase 0).
- [ ] One status surface per page; zero sync-internal jargon strings user-visible; sr-004 pass on all status indicators.
- [ ] One primary CTA per screen state on the Workbench; review queue is card-at-a-time with person-commit naming.
- [ ] Roster: person list + `Add Person` reachable from zero state (rg-003); no Clusters management tab; all cross-surface links use `?person=/?queue=/?face=`.
- [ ] Token families complete (type/grey/primary/elevation/radius/weight); zero raw hex in component sheets; tokenization test covers all sheets.
- [ ] Offline invariants (WBUX-1 §5 table) verified by the kill-API walkthrough on the live demo.
- [ ] Planning surfaces re-baselined (Phase R) — no epic/roadmap doc contradicts handoff state.
