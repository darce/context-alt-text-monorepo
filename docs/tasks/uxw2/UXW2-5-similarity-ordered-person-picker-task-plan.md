# UXW2-5. Similarity-ordered person picker — server-ranked roster candidates with live-settings bands

**Wave**: UX/UI wave 2 (orchestration task `MAINT-uxui-wave2-orch-20260818`, decision 5678) · **Date**: 2026-08-18 · **Author**: Claude (Fable 5)
**Target Branch**: `feature/uxw2-5` · **Worktree**: `context-alt-text-monorepo-uxw2-5` · **Baseline**: main @442d99f93
**Review Coverage Target**: 2 (adversarial `/review-parallel`: 1 local Claude + remote grok-4.6 + kimi-k3 reviewers, canon-cited)
**Diagnosis**: session scratchpad `diag/REPORT_C.md` (root causes with file:line evidence); prior art digest `diag/PRIOR_ART.md`
**Depends on**: UXW2-3 Slice 1 (NameFaceControl) for the FE slice · **Blocks**: none

## Objective

"Choose or create a person" lists roster people ranked by similarity to the faces under review, with a server-computed band (Strong / Possible) derived from live recognition settings; no raw percentages; "no strong match" is a designed state; the number is understood to be dynamic.

## Problem Statement (root cause, verified against main @442d99f93)

C1: `PersonCommitControl.tsx:84-89,186-189` uses `listRosterEntries` (alphabetical, `class-roster-entry-projection-repository.php:37`); no cluster→roster-person similarity API exists (closest: `search.py find_all_matches`, `label_inference.py` top-1). Backend thresholds `similarity_threshold=0.55, suggestion_floor=0.35, suggestion_ceiling=0.55` are legacy uncalibrated (FIR-6 S4 not landed); four divergent FE band scales (`ClusterEditForm.tsx:12` 0.7, `reviewQueueDriver.ts:118` 0.45, `similarityCopy.ts` 0.9/0.75/0.6, `ReviewQueue.tsx:124` 0.6); `similarity_threshold` in roster payload is always None (dead branch). Similarity IS dynamic (`refresh_service.py:382-503` rewrites when Δ>0.01; capped diverse representative sets).

## Decisions (canon defaults recorded in decision 5678 — not re-litigated here)

- New python `GET /recognition/clusters/{id}/roster-candidates?top_k` → `{model_id, embedding_model, computed_at, reference_face_count, thresholds, candidates:[{roster_entry_id|person_uuid, name, similarity, band, quality_flag}]}`; band computed server-side from live `face_suggestion_floor/ceiling`; same-`embedding_model` guard ([PROV-06], [DRIFT-03], [CAL-02]).
- PHP passthrough `acx/v1/recognition/clusters/{id}/roster-candidates`; FE shows "Suggested for these faces" in server order with band label + icon (no %), then "All people" alphabetical; single `bandFor(similarity, thresholds)`; delete the four FE constants ([HAI-08], [MEAS-05], [A11Y-04/06/21]).
- Raw % / calibrated probability deferred until FIR-6 S4 calibration lands ([CAL-03]).

## Constraints

- Python + PHP + FE. Contract: `docs/workbay/contracts/recognition-clustering.md` + `packages/shared-contracts` schema if response schemas live there. Never re-sort client-side (UXP-3 D2). rg-015 no invented totals.
- Findings live in workbay-handoff by ID only; this plan tracks work, not finding status.
- No `Co-Authored-By` trailers. Full SHAs in handoff writes. Slice = one user-visible path, RED test first (`/tdd`).

## Slices

### Slice 1 — `feat(recognition): UXW2-5 GET /recognition/clusters/{cluster_id}/roster-candidates` (RED unit: band from settings, same-model guard, empty roster, top_k bound; API test)
### Slice 2 — `feat(api): UXW2-5 PHP passthrough` (RED unit with stubbed proxy; map to `roster_entry_id`)
### Slice 3 — `feat(workbench): UXW2-5 picker ordered by server rank with band labels` (`PersonCommitControl`/`NameFaceControl`, `queryKeys.roster.candidates`, `bandFor`, delete FE constants; RED: server order preserved, unknown state, accname contains band)

## Verification

pytest targeted dirs + `composer test` + `npm test` green; RED→GREEN per slice; manual: open a review card → suggested people ordered, band label shown, no %; empty → "No strong match — choose or create".

## Prior art

FIR-5/FIR-11 identification-threshold canon; FIR-6 calibration plan (S4 not landed); E19-4A #2026 (match_confidence vs detection_confidence drift); CVUP-1 #6635/#6571; UXP-3 D2 (server order); E20-FUSION #2574 (match by id, never label equality).

## Open questions

Occlusion `quality_flag` beyond `low_quality` waits for EMB-11 spatial support (FIR program).
