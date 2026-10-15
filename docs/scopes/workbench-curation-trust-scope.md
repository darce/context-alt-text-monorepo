# Scope — WBTRUST: Workbench review-queue trust, curation flow and control placement

**Planning task:** `WBTRUST-0` (branch `feature/wbtrust-0`, base `372a6413a7ae0eb71baa3566716546684bac5a58`, 2026-10-15)
**Implementation tasks:** `WBTRUST-1` … `WBTRUST-8` — one task plan each under `docs/tasks/v0.5.0/`.
**Trigger:** operator walk-through of the `fir` LocalWP site (`http://localhost:10028`, workbench route `#/workbench`, attachment edit `post.php?post=107`, 81/85/89/106/107/113/114) plus its browser console.
**Heuristics:** Heuristics canon **v0.26.2**. IDs below were looked up in the pinned copy, not recalled. Tufte corpus = VIZ family; Microinteractions = INT/PERC; grid layout = LAY.
**Prior art:** FIR report `benchmarks/reports/fir-embeddings-dims-detectors-qa-20260723.html` (v13); `docs/scopes/uxp-net-1-429-fanout-scope.md` (shipped partly; storm persists); `docs/tasks/v0.5.0/GPUFLOW-3-…-task-plan.md` (unified status, name weaving); `docs/epics/v0.5.0/gpu-operator-control-and-named-captions-epic.md` (E23: operator GPU control lives in Settings); `docs/ux-maps/workbench-review-queue.md` and `apps/prototype-wp-alt-context/docs/ux-maps/workbench-2pane.uxmap.json` (source of truth; `render_ux_maps.py --check` reports all 11 maps current at the base SHA).
**Evaluation:** `docs/assessments/current/workbench-curation-trust-uxmap-evaluation-2026-10-15.md` (issue → evidence → canon rule → severity → owning task).
**Epic registration:** none yet. This document is the umbrella; whether it becomes an epic (E26) is an operator decision. Plans name `WBTRUST` as their short ID until then.

All frontend paths are relative to `apps/prototype-wp-alt-context/js/admin/` unless they start with `apps/`, `docs/`, `config/` or `scripts/`. Service paths are relative to `apps/prototype-description-service/`.

## Why this exists

The operator cannot trust what the review queue says and cannot finish the work it asks for. Five symptoms share three causes:

| Cause | Symptoms it produces |
| --- | --- |
| **The UI shows a score without the evidence behind it** (or with a gate that cannot be satisfied) | 100 % match beside "No image"; 100 % match with a disabled Yes; 34 % suggestion shown at all; Group/Person duplicates in the name picker |
| **Curation surfaces dead-end** (inspect-only panels, controls far from the thing they act on) | cluster panel has only ×; no accept path; pagination only at the bottom; GPU controls scattered; Details button goes nowhere useful; overlay chip covers the face and floats away from the image |
| **Hidden failures read as "not saved" or "wrong"** | 429 storm turns post-save refetches into errors; seeded fixture captions presented as AI drafts; detector misses a face without a signal |

## Operator reports (R1–R14, verbatim intent)

| Ref | Report |
| --- | --- |
| R1 | Suggestion 1/31: "Is this Nicky Ross?" shows "100 % match (1 faces)" against an avatar with `data-avatar-state="data-missing"`. "It cannot be 100 % match against no image." |
| R2 | Suggestion 2/31: "100 % match (10 faces)" with Yes disabled behind "Show stored faces first to approve." "100 % match should not be questioned… Yes is disabled." |
| R3 | Suggestion 5/31: 34 % "Low confidence" for Ellyn Heald vs Bea Burke; Yes disabled. "Wildly inaccurate." |
| R4 | "Review these faces" (Ellyn Heald, 47 faces, only ×). "No path to accept, curate, or manage… how to accept all after removing mismatches?" |
| R5 | Run ux-map on `#/workbench`; evaluate interactivity and UI against the canon (Tufte, microinteractions, aesthetics, grid, interactivity lexicons). |
| R6 | Where does the bulk-describe button belong? GPU controls "all over the place"; backend/automated settings should be modal or informative only. |
| R7 | Attachment edit (`post=107`): `#acx-attachment-faces` should overlay `#media-head-107`; the overlay label must sit outside the bbox. |
| R8 | Pagination needs to be at the top and bottom of the library table. |
| R9 | Labelling `bea-burke_57b99d594f1b` (#106): "Could not load name suggestions" + Retry; picker shows "Ellyn Heald" as Group and Person, "Bea Burke" as Person. "Why group/person?" |
| R10 | "After trying to assign identity, it does not save to media item." |
| R11 | `ellyn-heald_ellynheald_fe212728d1f4` (#81): one person detected; InsightFace detects both. |
| R12 | Activity strip meta-actions button "just scrolls up to top of page." |
| R13 | Descriptions for #113, #114, #107, #89, #85 are wildly inaccurate; the GPU Qwen model "was NOT used". |
| R14 | Console: mass `429 (Too Many Requests)` on suggestions, merge, name, `identities/suggestions` (one per identity), roster-candidates and `recognition/jobs/<uuid>` polling. |

## Root causes (verified in code unless marked)

1. **Percent without reference.** `identity-clusters/SuggestionCards.tsx` renders `matchPercent` unconditionally. With no representative thumbnail it falls to `SuggestionFacePlaceholder`, so "100 % match" sits beside "No image" and Yes stays enabled. Nothing server-side withholds a similarity when the reference set is empty.
2. **The stored-face gate is unsatisfiable.** `storedFaceReviewGate.ts` blocks Yes for any `identityCount > 1` regardless of score until "Show stored faces" is opened, but the opened list renders a real image only for position 1; positions 2..N render the text "Stored face N of M — Image unavailable". The same predicate (`isStoredFaceApprovalBlocked`) also gates selection/bulk commit. HAI-17 asks that every reference be *presented*, not that approval be blocked (FORM-09: do not force-block an ordinary recoverable action).
3. **Low-confidence suggestions are surfaced by default.** The service creates pending suggestions down to the low-confidence floor `suggestion_floor − low_confidence_band_width` = 0.35 − 0.05 = **0.30** (`recognition/application/settings/clustering.py`, applied in `suggestions/refresh_service.py`); the review queue lists them without a client filter (`GET /suggestions?limit=25&offset=0`), and `ReviewQueue.tsx` only *flags* those below `LOW_CONFIDENCE_THRESHOLD` (0.6) rather than hiding them, so a 34 % candidate is shown. (`min_confidence=0` in `api/recognition/identityQueriesApi.ts` applies to the separate naming-picker call `suggestions/name`, not to the queue.) The stored face it is compared with is an `acx-smoke-wrong_person-…` fixture (a test image inside a real person's cluster).
4. **Same-pixel matches look like identity evidence.** The "100 %" candidate in card 2 is `acx-smoke-wrong_person-dc6bef8f62de.jpg`, which is also the first stored face of Bea Burke in card 5, and the Ellyn Heald cluster holds visually identical crops (media 11/86, 6/27/28, 9/26). *Hypothesis, not yet proven:* these are duplicate uploads of one file whose faces get distinct identity rows and cosine ≈ 1.0. A score of ~1.0 between two rows of the same photo says nothing about identity. `WBTRUST-1` slice 1 proves or refutes this with image hashes before any code changes.
5. **Cluster review panel has no accept path.** `ClusterReviewPanel.tsx` is a pure child (`{clusterId, onClose}`) rendering one × per face (`removeClusterMember` → `clusters/reassign`, one POST per face, confirm dialog each). The sibling `ClusterLabelingPanel.tsx` names a group but its grid is read-only. The shipped UX map (`docs/ux-maps/workbench-review-queue.md`) records "inspect… remove… return" as the intended job, so the gap is by design, not a regression.
6. **Naming picker leaks the data model.** `NameFaceControl.tsx` `sourceBadgeLabel()` prints "Person" for roster options and "Group" for labeled-cluster options. `buildNamingOptions.ts` already dedupes person-preferred by name; the duplicate "Ellyn Heald" rows come from `selectClusterSuggestions` in `useClusterSuggestions.ts`, which puts identity-projection rows (source `cluster`) ahead of naming options and never lets a person row suppress a same-named group row. "Could not load name suggestions" is `useClusterSuggestionsLoader` `isError` — the identity-batch or roster-candidates query, i.e. the 429 path.
7. **"Not saved" is probably a failed refetch (to be proven).** Save mutations call `invalidateQueries()` on success (`useClusterMutations.ts`, `useClusterLabelMutations.ts`); the refetch hits the same rate limit. PHP has two paths: proxy-to-service when no local projection exists, local `$wpdb->update` + `touch_local_curation_marker` when it does (`src/api/services/class-cluster-label-service.php`); `GET media-identities` reads the local projection once it has rows. Which path the fir site takes, and whether media chips read the updated label, is unverified.
8. **429 storm persists after UXP-NET-1/UXP-2.** Limiter: 60 rpm per API key, burst 10 (`recognition/config/security.py`). Candidate drivers, each to be confirmed by a request-budget test: (a) job polling at 1.5 s per job (`hooks/useRecognitionHooks.ts` `getJobRefetchInterval`, one poller per id in `useMultiScanStatus`) — 20 jobs ≈ 800 req/min against 60; (b) per-identity single-id suggestion queries re-fetched when `suggestions.all` is invalidated (`useJobStateMachineEffects.ts`, `invalidateSuggestionProjection`) even though a 100-id batch route exists; (c) additional pollers (`useDescribeRunProgress`, `useRetentionStatus`, `useMediaIdentities`, `useGpuServiceStatus`, `useSyncStatus`, `useGpuControl`); (d) invalidation bursts after assign/confirm and scan success.
9. **GPU controls and disclosures are everywhere.** Canonical home is `pages/settings/GpuControlCard.tsx` (E23). The workbench adds: footer GPU-cost `<p data-testid="acx-bulk-describe-gpu-cost">`, recognition-policy `<p>`, `BulkDescribeProgress` warming copy, `ActivityStatusStrip` warming/timeout copy, `GpuTierStatus.tsx` (no mount found outside its own file — verify and delete if dead), toasts (`useGpuStateToasts`). The Describe button, a frequent command, shares a footer row with configuration prose (INT-13, NAV-06).
10. **Pagination is footer-only; Details opens a distant region.** `MediaSelection.tsx` renders `MediaSelectionPagination` once, in `acx-media-selection__footer` below the table. `ActivityStatusStrip` "Details" calls `setAdvancedOpen(true)`; `AdvancedDrawer` is an inline disclosure mounted after the two-pane layout in `WorkbenchPage.tsx`, with a second trigger of its own — so activation moves focus to a region outside the strip's pane.
11. **Attachment overlay is a duplicate figure with centered chips.** `attachment-edit/AttachmentFacesApp.tsx` renders its own `<figure><img/><FaceOverlayLayer/></figure>` inside the compat-field `#acx-attachment-faces`, not over WordPress's `#media-head-<id>` image. `components/ui/FaceOverlayLayer.tsx` centers each chip on the bbox centre (`translate(-50%,-50%)`), so the label sits on the face.
12. **"Wrong descriptions" are not model output.** All five reported captions are verbatim entries of `_FIXTURE_POOL` in `scene/application/seeded_adapter.py` ("A plate of food on a wooden table.", "A building exterior seen from the street.", "A close-up of a small object on a neutral background."; "…standing outdoors near greenery." is "A person standing outdoors near greenery." after name substitution). Config: `config/env/manifest.d/22-service-fir.toml` gives `svc-fir` the example `seeded`, while the shared dev value is `gpu_qwen30b` and the unset fallback is `florence_small` (`api/main.py`, `scene/config/settings.py:80`; the `get_description_adapter` docstring still says seeded is default). Neither adapter, model nor tier reaches the draft cell (`QueueDraftCell.tsx`, `MediaAltSuggest.tsx` show only "Drafted by AI — review before saving."). *Unverified:* the live `adapter`/`model_id`/`tier` on media 85/89/107/113/114; `WBTRUST-7` slice 1 reads them.
13. **Second face in #81 (not a regression, an open measurement).** The FIR face path (YuNet, `RECOGNITION_FACE_SCORE_THRESHOLD` default 0.30, `recognition/config/settings.py`) has a published WIDER-hard weakness; the Golden-150 recall comparison is withdrawn as evidence (GT is 98.4 % the comparator's own output); D-01 "is detection the bottleneck?" is unresolved; T-14 union adjudication is the cheap kill path. Demo/prod use InsightFace; in-house FIR is dev-only. *Unverified:* which profile served :10028.

## MVP scope

Eight tasks. Each is independently shippable and lists owned paths in its plan so lanes do not collide.

| Task | Theme | Closes |
| --- | --- | --- |
| `WBTRUST-1` | Review-queue trust: evidence strip, no percent without reference, gate redesign, low-confidence default, duplicate-pixel guard | R1, R2, R3 |
| `WBTRUST-2` | One curation surface: member grid with exclude/undo and "Accept N as {name}" | R4 |
| `WBTRUST-3` | Naming: one option per person, non-blocking suggestions, read-your-writes | R9, R10 |
| `WBTRUST-4` | Request budget: aggregate poll budget, targeted invalidation, request-count tests | R14 |
| `WBTRUST-5` | Control placement: Describe footer, GPU info surface, pagination top+bottom, Details | R6, R8, R12 |
| `WBTRUST-6` | Attachment overlay over `#media-head-<id>` with labels outside the bbox | R7 |
| `WBTRUST-7` | Description provenance: show adapter/tier, refuse seeded as a draft, route burst describe to GPU, gate naming on caption provenance | R13 |
| `WBTRUST-8` | Detection recall evidence for #81 (measure first, no product change without it) | R11 |

### Binding product decisions (apply to every plan)

1. **No percentage without its evidence.** A match score renders only next to the reference image(s) it was computed against. Zero resolvable references → "Can't verify — reference image unavailable", no score, no approve (HAI-01, HAI-08, CAL-02, CAL-11).
2. **Present evidence, don't gate on a toggle.** Reference faces are shown by default as a strip of real thumbnails (cap 6, "+N" opens the rest). Approve is enabled whenever ≥ 1 reference thumbnail is on screen. Low-band cards add a visible caution, not a lock (HAI-17, HAI-21, FORM-09, HAI-13).
3. **Frequent command first, configuration elsewhere.** The workbench carries the action and a one-line state; thresholds, leases, start/stop live in Settings (E23). Info is a popover or disclosure, not a new modal (INT-13, NAV-06, COG-07, INT-28).
4. **Every list that is long gets controls at both ends** (NAV-21) and every control sits next to what it acts on (NAV-19, PERC-01).
5. **Label outside the mark.** Overlay labels never sit on the subject (VIZ-12, PERC-01).
6. **Failures are named, not mimicked.** A rate-limit wait shows one status line, not N card errors; a fixture caption is labeled as a fixture (PERC-07, HAI-05, PROV-01).
7. **Measure before changing recall.** No detector or threshold change ships without an adjudicated set (EVAL-16, EVAL-19).

### Delivery order

```
Wave A (parallel, disjoint files):  WBTRUST-4  WBTRUST-5  WBTRUST-6  WBTRUST-7  WBTRUST-8(measure)
Wave B (after WBTRUST-4):           WBTRUST-1  WBTRUST-3
Wave C (after WBTRUST-3):           WBTRUST-2
```

`WBTRUST-4` goes first so the 429 storm stops contaminating the repro for `WBTRUST-1/3`. `WBTRUST-2` reuses the naming control that `WBTRUST-3` settles. `WBTRUST-1` and `WBTRUST-2` both touch `ReviewQueue.tsx`; they are sequential by design.

## Success criteria

1. A suggestion card never shows a percent without ≥ 1 rendered reference thumbnail; the contract test fails on the old behavior.
2. Opening the fir workbench with 31 suggestions: card 1/2/5 states are respectively "Can't verify", approvable with all stored faces visible, and absent (below the default floor) or visibly cautioned.
3. From a 47-face group the operator excludes mismatches and accepts the rest with one primary action; request count for K exclusions is exactly K reassigns + 1 commit.
4. Saving a name shows "Saved" within 1 s without any refetch succeeding, and the media row chip reflects it after reload.
5. Idle workbench with 20 active jobs issues ≤ 40 recognition-bound requests/min; a scan-complete burst issues ≤ 10; zero 429 in a 5-minute replay on the fir tenant.
6. Pagination appears above and below the library table; the footer holds the Describe action and one line of state; no GPU configuration control outside Settings.
7. Attachment edit screen shows the overlay on `#media-head-107`'s image and no label intersects any face bbox (unit-tested placement function plus browser check).
8. No draft produced by the `seeded` adapter can be applied as alt text; each draft shows adapter/model/tier; a burst describe on a ready GPU yields `final_gpu` Qwen output.
9. A written decision on #81: profile that ran, per-pipeline detections, and whether to widen the experiment.

## Not-doing

- Rate-limit tier changes or exemptions (UXP-NET-1 ruled these out; the operator decision is flagged in `WBTRUST-4`, not made).
- Changing the face detector, embedding space or thresholds on evidence from one image (`WBTRUST-8` measures only).
- Moving any operator GPU control (start/stop/auto/lease) out of Settings, or any agent GPU actuation (E23 hard constraint).
- Merging Person/Group on the server (the cluster→roster binding stays; only the UI stops exposing the distinction).
- A batch member-removal endpoint (client sequencer first; endpoint only if `WBTRUST-2` measurement shows it is needed).
- Any epic or ADR registration; any change under `~/Local Sites/` or LocalWP config.
- Data migrations (greenfield). Cleaning the `acx-smoke-*` fixtures from the fir tenant is an operator purge (clean slate), not product code.

## Follow-up

- Duplicate-pixel collapse in the member grid (×2 badge) if `WBTRUST-1` slice 1 confirms duplicates are a product-path problem and not only smoke debris.
- Server batch endpoint for job status (`GET recognition/jobs?ids=`), a contract extension if the aggregate budget in `WBTRUST-4` is not enough.
- "Detection coverage" cue on media rows (faces found vs identified) once `WBTRUST-8` decides detector direction.
- Guided browser verification of the whole walk-through once a Chrome automation tier is available (this planning pass had none).

## Verification of this document

Everything above marked "verified" was read in the checkout at the base SHA. Items marked *hypothesis* or *unverified* each have a first-slice step that settles them. No browser was available to the planner, so interaction claims come from the operator's DOM snippets plus code.
