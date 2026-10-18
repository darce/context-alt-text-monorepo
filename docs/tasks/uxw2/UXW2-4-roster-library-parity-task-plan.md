# UXW2-4. Roster/Library parity — persons as single label authority; retire needs-assignment rail; legible review panel

**Wave**: UX/UI wave 2 (orchestration task `MAINT-uxui-wave2-orch-20260818`, decision 5678) · **Date**: 2026-08-18 · **Author**: Claude (Fable 5)
**Target Branch**: `feature/uxw2-4` · **Worktree**: `context-alt-text-monorepo-uxw2-4` · **Baseline**: main @442d99f93
**Review Coverage Target**: 2 (adversarial `/review-parallel`: 1 local Claude + remote grok-4.6 + kimi-k3 reviewers, canon-cited)
**Diagnosis**: session scratchpad `diag/REPORT_A.md` (root causes with file:line evidence); prior art digest `diag/PRIOR_ART.md`
**Depends on**: UXW2-1 (URL-write discipline for `panel=`/`cluster=`) · **Blocks**: none

## Objective

Every human label the Library shows is a Roster person; deleting a person returns its faces to the review queue; the Roster no longer duplicates the workbench queue with a face-less rail; opening Review from the queue is legible (back affordance, URL-persisted, announced) and speaks plain language.

## Problem Statement (root cause, verified against main @442d99f93)

A1: Roster = `acx_persons` (`class-roster-entry-projection-repository.php:37`), Library = `COALESCE(p.name,c.label)` (`class-identity-members-read-repository.php:180-235`); label-without-person via snapshot merger (`class-cluster-snapshot-merger.php:90-140`), proxy/merge relabel (`class-cluster-label-service.php:74-83`, `class-cluster-merge-service.php:105-130`), and `delete_person` (`class-api.php` ~L800: clears person_id, keeps label, sets is_user_confirmed=1 → invisible to top-unlabeled and the rail). A2/A3: `NeedsAssignmentSection.tsx` renders no image and reads `/recognition/clusters?limit=20` (all clusters, updated_at DESC, client `isUnlabeledCluster`) vs queue `/clusters/top-unlabeled`; Roster copy still says cluster/identities/"projected instances". A4: `ScanTabContent.tsx:40-260` swaps ReviewQueue for `ClusterReviewPanel` via React-only `ClusterPanelContext` mode — not in URL, only an X to return.

## Decisions (canon defaults recorded in decision 5678 — not re-litigated here)

- `acx_persons` is the ONLY human-label authority; delete clears label + un-confirms; label writes always bind a person; media-identities read stops falling back to raw human labels ([DATA-14], [ARCH-02], [HAI-17]).
- Retire the Roster rail → CTA into the workbench queue (E21-10: Workbench decides face groups, Roster curates people) ([NAV-05], [HAI-01]); `?cluster=` drawer shim kept.
- Review panel: visible Back, `panel=review&cluster=<id>` in hash, `role=status` ([NAV-11], [NAV-07], [COG-01], [A11Y-21]).

## Constraints

- PHP + FE, no python contract change. Contract docs: curation-sync/cluster-snapshot invariant "human label ⇒ bound person"; clustering-api documents `top-unlabeled` as the single needs-assignment predicate.
- Backfill idempotent + bounded ([rg-007]); transactions via `run_transactional` ([sr-009]); rg-015 no invented counts on the CTA.
- Findings live in workbay-handoff by ID only; this plan tracks work, not finding status.
- No `Co-Authored-By` trailers. Full SHAs in handoff writes. Slice = one user-visible path, RED test first (`/tdd`).

## Slices

### Slice 1 — `fix(api): UXW2-4 delete_person returns faces to the review queue` (RED `PersonCrudTest.php`)
### Slice 2 — `fix(sovereign): UXW2-4 label writes always bind a person` (merge-service, snapshot merger backfill, label-service proxy branch; RED per service test) + bounded one-shot backfill entry point
### Slice 3 — `fix(sovereign): UXW2-4 media identities read no longer falls back to raw human labels` (`list_for_media_ids`; contract invariant)
### Slice 4 — `fix(roster): UXW2-4 retire needs-assignment rail, link to workbench queue` (`RosterPage.tsx`, drop `useRecognitionClusters`, delete `NeedsAssignmentSection` if unreferenced; RED RosterPage test)
### Slice 5 — `fix(roster): UXW2-4 plain-language wording` (Roster-owned files; `docs/ux-maps/roster-people.md` vocabulary; banned-vocabulary renders PersonWorkspacePanel + drawer)
### Slice 6 — `fix(workbench): UXW2-4 review panel is legible: back affordance + URL + status` (`ScanTabContent.tsx`, `ClusterPanelContext.tsx`, `ClusterReviewPanel.tsx`, `appLinks.ts` `panel=`; RED real-router test)

## Verification

`composer test` + `npm test`/lint/typecheck green; RED→GREEN per slice; manual: label a face in Library → appears in Roster; delete the person → face back in queue; Roster shows CTA not rail; queue Review → URL has `panel=review`, Back returns.

## Prior art

E21-9 dec 2888/2889/2886 (Clusters tab retired, rail, drawer); E21-10 appLinks contract; FIR-9 dec 3240 NAV-05; E21-21-BR-01 (roster thumbs via sovereign mapper); E19-4A-S3-BR-01 / E20-FUSION (naming requires roster_id); E15-17 sovereign read path.

## Open questions

Bulk merge/dismiss reachability (E21-9 Q1) moves to the workbench queue in a follow-up task; not added here.
