# Roster page — consolidated open work (2026-07-23)

> **Advisory consolidation note only** — not a plan baseline, not MCP-tracked scope, not a task plan.  
> Status rows are read from each cited doc’s own text (or code presence where noted). No finding-id bullet lists.

## IA contract recap

E21-10 fixed the cross-surface model in one sentence: **Workbench decides, Roster curates [people], Dashboard orients, History audits & applies** (bracketed interpolation from E21-9's "Roster curates people"; E21-10's own sentence omits the word). E21-9 made Roster **person-first single-surface** — `ROSTER_SURFACE` in `js/admin/pages/roster/rosterRoute.ts`, Clusters tab retired — so cluster triage lives only on Workbench’s review queue (`rq=` flows, person-commit on the card). That MECE split (NAV-05) is why a cluster-inspection atlas must not re-home on Roster: putting an overview scatter of `cluster_id` topology next to person curation re-opens the dual-home E21-9 closed.

Operational consequence for FIR-9 and later roster work: Roster owns person records, Needs-assignment rails, and scrub/workspace flows; Workbench owns merges, labels, and ordered review. Cross-surface jumps go through `js/admin/navigation/appLinks.ts` only (`toRoster`, `toWorkbench`, `APP_LINK_PARAMS`) — never a second hash grammar.

## Open / planned roster items

Each path was checked present in this sandbox. Status is the doc’s own checklist/epic row language, or a one-line code-presence note when the plan lags the tree.

| Item | Doc (verified present) | Status (from doc / tree) |
| --- | --- | --- |
| **E15-13** roster curation loop | `docs/tasks/15.0/E15-13-roster-curation-loop-task-plan.md` | **Planned** — launch-epic Phase 6 row: “Planned — E15-13” (`docs/epics/v0.4.0/public-demo-launch-readiness-epic.md`) |
| **E15-17** person-review scrub workspace | `docs/tasks/15.0/E15-17-roster-person-review-scrub-workspace-task-plan.md` | **Planned** — epic: after E15-13 projection + queue contracts land |
| **E21-12** roster zero-state | `docs/tasks/21.0/E21-12-roster-zero-state-task-plan.md` | **Landed per plan** — Slice 1–2 checklists and Success Criteria all checked (not open work). NAV-08 / rg-003 first-run reachability baseline. |
| **UXP-3** suggestion projection | `docs/tasks/uxp/UXP-3-roster-suggestion-projection-task-plan.md` | **Landed per plan** — consolidated checklist / Success Criteria checked; E21-5 plan also cites UXP-3 merged on `main` |
| **E21-10** link contract | `docs/tasks/21.0/E21-10-cross-surface-link-contract-task-plan.md` | **Landed in tree** — `js/admin/navigation/appLinks.ts` (builders + `APP_LINK_PARAMS`); plan checklist may lag merge bookkeeping |
| **E21-9** Clusters-tab retirement (context) | `docs/tasks/21.0/E21-9-roster-clusters-tab-retirement-task-plan.md` | **Landed in tree** — `ROSTER_SURFACE`, `NeedsAssignmentSection`; enforces person-first Roster |
| **MAINT-e21-5 postmerge** deferred follow-ups | Cited from `docs/tasks/15.0/E15-37-sovereign-read-path-task-plan.md` (no standalone plan under `docs/`) | **Handoff-tracked** on archived `MAINT-e21-5-postmerge-review-20260718`. That note names **five** open findings: GROK-01 / S5-03 (`resolveMergeSurvivor.ts`), S5-02 (`useLiveReviewTarget.ts`), CFR-02 / S4-04 (PHP curation/envelope). Bodies stay in handoff — not duplicated here. |
| **E21-5 VoiceOver AT protocol** (adjacent) | `docs/tech-debt/e21-5-voiceover-at-protocol.md` | **Deferred** tech debt (manual AT pass; optional BR-84 test hardening). Not roster-page scope; listed only as adjacent operator gate. |

Related specs (background, not duplicate tasks):

- `docs/specs/recognition-roster-curation-loop-spec.md`
- `docs/specs/roster-management-person-review-scrub-ui-spec.md`

## How FIR-9’s atlas serves Roster without living there

FIR-9 remains a **Workbench** surface. Placement is locked by decision `fir9_atlas_placement_workbench_validated_20260723` (#3240) and the plan’s **Placement rationale** section (NAV-05, VIZ-15, NAV-06). The operator’s intent (“see assignment gaps near people work”) is served by an S3 **Roster-coordination lens**, not by moving the atlas home:

1. **Person-assignment color lens** — toggle colors atlas points by named/committed (`cluster_label` set and `is_auto_label is False`) vs unlabeled/auto (`cluster_label` empty or `is_auto_label is True`). Verified fields on the cluster/member read path: `ClusterMemberResponse.cluster_label` / `is_auto_label` (`responses.py:53–54`); domain `IdentityCluster.is_auto_label` (`cluster.py:34–36`). Status encoding pairs **color + icon** (sr-004).
2. **Needs-assignment deep-links** — single-point click on an unlabeled/auto island offers “Open in Roster → Needs assignment” via `toRoster(...)` only. Any new param is added to `APP_LINK_PARAMS` (E21-10). No lasso multi-select in v1 (not in plan v2 either).
3. **VIZ-15** — atlas is OVERVIEW; workbench review queue is DETAIL. Shared cluster-color encoding + linked highlighting when both visible; otherwise deep-link into the queue (`rq=` / existing workbench builders).

Net: Roster keeps person curation; Workbench keeps cluster triage and the geometric overview. The lens accelerates hops into Needs-assignment / unassigned flows without a second cluster inspector.

## Suggested sequencing (advisory)

1. **E21-12 zero-state** — complete per plan; treat as baseline (NAV-08 / rg-003). Unblocks first-run Roster walks before heavier curation loops.
2. **Freeze E21-10 vocabulary** for any atlas→Roster params — extend `APP_LINK_PARAMS` / `toRoster` only; never a parallel codec.
3. **FIR-9 S1 → S2** — schema, batch job, dual HTTP read surfaces, disposition POST. Points payload must eventually carry `cluster_label` + `is_auto_label` for the lens.
4. **FIR-9 S3 lens** after S1/S2 — small FE concession: assignment color + Needs-assignment deep-link. Lands before the big E15 pair so operators can already jump from islands to Roster.
5. **E15-13 then E15-17** (epic order) — durable curation loop + person scrub workspace. Atlas is an **accelerant** for finding unlabeled islands (CAL-11 queue-as-action lives on those projection/queue contracts), not a substitute.
6. **MAINT-e21-5 follow-ups** — remain on the archived handoff ref; do not fold into FIR-9 or E15-13 scopes.

## What this note does *not* do

- Does not fund, accept, or re-baseline any task plan.
- Does not move FIR-9 atlas home to Roster (already rejected; see #3240).
- Does not invent CONS-* or new IA roles beyond E21-10.
- Does not paste review-finding bodies (handoff is source of truth for MAINT-e21-5 items).
- Does not sequence E15-13 implementation detail — only relative order vs FIR-9 S3 and E15-17.

## Pointers

| What | Where |
| --- | --- |
| FIR-9 plan v3 | `docs/tasks/fir/FIR-9-workbench-curation-atlas-task-plan.md` — **Placement rationale**, **Slice 3 · Roster-coordination lens** |
| Placement decision | `fir9_atlas_placement_workbench_validated_20260723` (#3240) |
| Link contract | `apps/prototype-wp-alt-context/js/admin/navigation/appLinks.ts` |
| Person-first surface | `js/admin/pages/roster/rosterRoute.ts` (`ROSTER_SURFACE`); `NeedsAssignmentSection.tsx` |
| Assignment wire fields | `ClusterMemberResponse.cluster_label` / `is_auto_label` in `recognition/interface_adapters/http/schemas/responses.py`; domain `IdentityCluster.is_auto_label` |
| Canon IDs used | NAV-05 (MECE single-home), NAV-06 (frequent task), NAV-08 (zero-state), VIZ-15 (overview+detail), CAL-11 (queue-as-action). No CONS-* citations invented. |

---

*End of advisory note. Prefer the FIR-9 and E15 task plans for implementation scope; use this file only for operator orientation across roster-adjacent work.*
