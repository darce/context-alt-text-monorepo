# Scope — WBTRUST: Workbench review-queue trust, curation flow and control placement

**Planning task:** `WBTRUST-0` (branch `feature/wbtrust-0`, base `372a6413a7ae0eb71baa3566716546684bac5a58`, 2026-10-15)
**Implementation tasks:** `WBTRUST-1` … `WBTRUST-8` — one task plan each under `docs/tasks/v0.5.0/`.
**Trigger:** operator walk-through of the `fir` LocalWP site (`http://localhost:10028`, workbench route `#/workbench`, attachment edit `post.php?post=107`, 81/85/89/106/107/113/114) plus its browser console.
**Heuristics:** Heuristics canon **v0.26.2**. IDs below were looked up in the pinned copy, not recalled. Tufte corpus = VIZ family; Microinteractions = INT/PERC; grid layout = LAY.
**Prior art:** FIR report `benchmarks/reports/fir-embeddings-dims-detectors-qa-20260723.html` (v13); `docs/scopes/uxp-net-1-429-fanout-scope.md` (shipped partly; storm persists); `docs/tasks/v0.5.0/GPUFLOW-3-…-task-plan.md` (unified status, name weaving); `docs/epics/v0.5.0/gpu-operator-control-and-named-captions-epic.md` (E23: operator GPU control lives in Settings); `docs/ux-maps/workbench-review-queue.md` and `apps/prototype-wp-alt-context/docs/ux-maps/workbench-2pane.uxmap.json` (source of truth; `render_ux_maps.py --check` reports all 11 maps current at the base SHA).
**Semantic prior art:** handoff ledger searched with `find_related_prior_work` (embeddings verified) plus lexical `search_handoff`; results are folded in under "Prior art (semantic)" below. Cited by ID only; query the ledger for status.
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

These are the planner's 2026-10-15 pre-activation source/site observations. Step 0's later supplied receipts supersede the old served-build and unknown-run premises; historical source defaults are not current rollout instructions.

1. **Percent without reference.** `identity-clusters/SuggestionCards.tsx` renders `matchPercent` unconditionally. With no representative thumbnail it falls to `SuggestionFacePlaceholder`, so "100 % match" sits beside "No image" and Yes stays enabled. Nothing server-side withholds a similarity when the reference set is empty. The shipped stored-face gate (DUX-L8-RV-02) is keyed to `identityCount > 1`, so a single-face candidate (card 1) never reaches it: that is the exact gap, not a missing gate.
2. **The stored-face gate is unsatisfiable.** `storedFaceReviewGate.ts` blocks Yes for any `identityCount > 1` regardless of score until "Show stored faces" is opened, but the opened list renders a real image only for position 1; positions 2..N render the text "Stored face N of M — Image unavailable". The same predicate (`isStoredFaceApprovalBlocked`) also gates selection/bulk commit. HAI-17 asks that every reference be *presented*, not that approval be blocked (FORM-09: do not force-block an ordinary recoverable action). IDREBIND-1-W3-05 deliberately made the toggle satisfy the gate in place (`aria-expanded`/`aria-controls`); `WBTRUST-1` replaces the toggle-as-gate, it does not reintroduce a separate navigation step.
3. **Low-confidence suggestions are surfaced by default.** The service creates pending suggestions down to the low-confidence floor `suggestion_floor − low_confidence_band_width` = 0.35 − 0.05 = **0.30** (`recognition/application/settings/clustering.py`, applied in `suggestions/refresh_service.py`); the review queue lists them without a client filter (`GET /suggestions?limit=25&offset=0`), and `ReviewQueue.tsx` only *flags* those below `LOW_CONFIDENCE_THRESHOLD` (0.6) rather than hiding them, so a 34 % candidate is shown. (`min_confidence=0` in `api/recognition/identityQueriesApi.ts` applies to the separate naming-picker call `suggestions/name`, not to the queue.) The stored face it is compared with is an `acx-smoke-wrong_person-…` fixture (a test image inside a real person's cluster).
4. **Same-pixel matches look like identity evidence.** The "100 %" candidate in card 2 is `acx-smoke-wrong_person-dc6bef8f62de.jpg`, which is also the first stored face of Bea Burke in card 5, and the Ellyn Heald cluster holds visually identical crops (media 11/86, 6/27/28, 9/26). *Hypothesis, not yet proven:* these are duplicate uploads of one file whose faces get distinct identity rows and cosine ≈ 1.0. A score of ~1.0 between two rows of the same photo says nothing about identity. `WBTRUST-1` slice 1 proves or refutes this with image hashes before any code changes.
5. **Cluster review panel has no accept path.** `ClusterReviewPanel.tsx` is a pure child (`{clusterId, onClose}`) rendering one × per face (`removeClusterMember` → `clusters/reassign`, one POST per face, confirm dialog each). The sibling `ClusterLabelingPanel.tsx` names a group but its grid is read-only. The shipped UX map (`docs/ux-maps/workbench-review-queue.md`) records "inspect… remove… return" as the intended job, so the gap is by design, not a regression.
6. **Naming picker leaks the data model.** `NameFaceControl.tsx` `sourceBadgeLabel()` prints "Person" for roster options and "Group" for labeled-cluster options. `buildNamingOptions.ts` already dedupes person-preferred by name; the duplicate "Ellyn Heald" rows come from `selectClusterSuggestions` in `useClusterSuggestions.ts`, which puts identity-projection rows (source `cluster`) ahead of naming options and never lets a person row suppress a same-named group row. "Could not load name suggestions" is `useClusterSuggestionsLoader` `isError` — the identity-batch or roster-candidates query, i.e. the 429 path.
7. **"Not saved" is probably a failed refetch (to be proven).** Save mutations call `invalidateQueries()` on success (`useClusterMutations.ts`, `useClusterLabelMutations.ts`); the refetch hits the same rate limit. PHP has two paths: proxy-to-service when no local projection exists, local `$wpdb->update` + `touch_local_curation_marker` when it does (`src/api/services/class-cluster-label-service.php`); `GET media-identities` reads the local projection once it has rows. Which path the fir site takes, and whether media chips read the updated label, is unverified. Two facts from prior art change the odds: (a) the backend `person_updated`/`person_created` operations are no-op acknowledgements by contract (`docs/workbay/contracts/curation-sync-api.md`), so a rename is durable only through the WP-side cluster-label enqueue; (b) that enqueue (`Api::update_person()` → `enqueue_bound_cluster_label_updates`, with `PersonRenameReplayTest.php`) is on `main` but absent from the PHP the :10028 site serves (see Step 0). "Not saved" may therefore be a stale deployment, not a defect on `main`.
8. **429 storm persists after UXP-NET-1/UXP-2.** Part of the per-surface budget already landed on `main` after the served build was cut (optional-read budgets in `useClusterSuggestions`, `useClusterMutations.failedReadBudget`, `ReviewQueue.closestPendingBudget`, `ClusterLabelingPanel.hangingClosestBudget`, `useClusterRosterCandidates`); re-measure on current `main` before spending slices (Step 0). Limiter: 60 rpm per API key, burst 10 (`recognition/config/security.py`). Candidate drivers, each to be confirmed by a request-budget test: (a) job polling at 1.5 s per job (`hooks/useRecognitionHooks.ts` `getJobRefetchInterval`, one poller per id in `useMultiScanStatus`) — 20 jobs ≈ 800 req/min against 60; (b) per-identity single-id suggestion queries re-fetched when `suggestions.all` is invalidated (`useJobStateMachineEffects.ts`, `invalidateSuggestionProjection`) even though a 100-id batch route exists; (c) additional pollers (`useDescribeRunProgress`, `useRetentionStatus`, `useMediaIdentities`, `useGpuServiceStatus`, `useSyncStatus`, `useGpuControl`); (d) invalidation bursts after assign/confirm and scan success.
9. **GPU controls and disclosures are everywhere.** Canonical home is `pages/settings/GpuControlCard.tsx` (E23). The workbench adds: footer GPU-cost `<p data-testid="acx-bulk-describe-gpu-cost">`, recognition-policy `<p>`, `BulkDescribeProgress` warming copy, `ActivityStatusStrip` warming/timeout copy, `GpuTierStatus.tsx` (no mount found outside its own file — verify and delete if dead), toasts (`useGpuStateToasts`). The Describe button, a frequent command, shares a footer row with configuration prose (INT-13, NAV-06).
10. **Pagination is footer-only; Details opens a distant region.** `MediaSelection.tsx` renders `MediaSelectionPagination` once, in `acx-media-selection__footer` below the table. `ActivityStatusStrip` "Details" calls `setAdvancedOpen(true)`; `AdvancedDrawer` is an inline disclosure mounted after the two-pane layout in `WorkbenchPage.tsx`, with a second trigger of its own — so activation moves focus to a region outside the strip's pane.
11. **Attachment overlay is a duplicate figure with centered chips.** `attachment-edit/AttachmentFacesApp.tsx` renders its own `<figure><img/><FaceOverlayLayer/></figure>` inside the compat-field `#acx-attachment-faces`, not over WordPress's `#media-head-<id>` image. `components/ui/FaceOverlayLayer.tsx` centers each chip on the bbox centre (`translate(-50%,-50%)`), so the label sits on the face.
12. **"Wrong descriptions" are not model output.** All five reported captions are verbatim entries of `_FIXTURE_POOL` in `scene/application/seeded_adapter.py` ("A plate of food on a wooden table.", "A building exterior seen from the street.", "A close-up of a small object on a neutral background."; "…standing outdoors near greenery." is "A person standing outdoors near greenery." after name substitution). Config: `config/env/manifest.d/22-service-fir.toml` gives `svc-fir` the example `seeded`, while the shared dev value is `gpu_qwen30b` and the unset fallback is `florence_small` (`api/main.py`, `scene/config/settings.py:80`; the `get_description_adapter` docstring still says seeded is default). The same symptom was found on the public demo (DEMOLIVE-1-BR-01) and carried to DEBTFIX-1 (DADJ-10161), which made `florence_small` the default and limited the live-demo manifest to Florence and GPU profiles with the intent "fail closed rather than publish fixture text". So the fir service is running `seeded` through an explicit env value or a stale process, not through the code default; fir is a dev site, so the fix is provenance visibility plus a refusal to present fixture text as a draft, not a new default. Neither adapter, model nor tier reaches the draft cell (`QueueDraftCell.tsx`, `MediaAltSuggest.tsx` show only "Drafted by AI — review before saving."). *Unverified:* the live `adapter`/`model_id`/`tier` on media 85/89/107/113/114; `WBTRUST-7` slice 1 reads them.
13. **Second face in #81 (not a regression, an open measurement).** The FIR face path (YuNet) has a published WIDER-hard weakness, and its serving cutoff is strict: `RECOGNITION_FACE_SCORE_THRESHOLD` resolves in `recognition/config/settings.py` to `DEFAULT_SCORE_THRESHOLD = 0.9` (`recognition/infrastructure/face_pipeline/_common.py`; 0.3 there is the NMS threshold, not the score cutoff). Open GTMSMOKE-1 finding 18547 (`GTMSMOKE-FIR-DETECT-CONFIDENCE`) measured clear operator-selected faces scoring .853/.862/.890 natively and being rejected at 0.9, with higher scores at a larger input scale — so "second face scored below the cutoff" is the leading hypothesis for #81, not a given; the Golden-150 recall comparison is withdrawn as evidence (GT is 98.4 % the comparator's own output); D-01 "is detection the bottleneck?" is unresolved; T-14 union adjudication is the cheap kill path. Demo/prod use InsightFace; in-house FIR is dev-only. The measurement design already exists (FIRDV-2 S3a: independent exhaustive ground truth, one-to-one spatial matching, recall at a calibration-frozen FPPI policy, misses/false-positive overlays, zero-output accounting); `WBTRUST-8` reuses it, and published detection recall against `roster_only` manifests is refused by the harness (FIR-11-S2R3-07), so it is never cited. FIR-DETECTOR-r1/r2 (scale-retry, floor, projection) are already on `main`. GTMSMOKE-1 recorded a `RECOGNITION_FACE_SCORE_THRESHOLD=.85` selection in the native API and worker env (decision 16759): the effective cutoff on any stack is 0.9 by default or .85 under that override, and either hides a face scoring below it. Finding 18547 belongs to the ACTIVE GTMSMOKE-1 task: `WBTRUST-8` supplies #81 as evidence for it and neither edits nor closes it; where threshold work lands is the operator's call. Ground truth for any recall number must carry independent human lineage (the detector never sees the labeller's proposals; FIRDV-2 S3a refuses otherwise). *Unverified:* which profile, threshold and input scale served :10028.

## Step 0 — baseline freshness (applies to every plan)

**Current supplied coordinator receipts (2026-10-15, decisions 17052/17053):** baseline `372a6413a7ae0eb71baa3566716546684bac5a58` was approved and activated at 22:01Z. The authenticated smoke receipt records **7 HTTP checks PASS** (admin/REST/served artifact only), zero mutating requests, zero description tasks and zero GPU actuation. This is not browser, rename-persistence or fresh GPU-output proof; those remain **UNRUN**. These are supplied receipts, not executions by this documentation lane.

The supplied full-run receipt identifies `019c6776-d511-4531-8294-20dc99dabd7b`: **100/100 seeded / seeded-fixtures**, 97 fresh generated results, 3 cache hits, 54 naming-applied and 46 no-confirmed-identities. That resolves the former unknown five-item provenance premise without proving a model-backed run. Unavailable runtime fields remain UNKNOWN. An idle, stopped metered GPU is expected and says nothing about prior activation. Florence Small is retired for live, development and production use; never restore it. Qwen is the operating baseline, with the exact supported/configured/served model still requiring verification and explicit failure when unavailable.

**Historical observation before activation:**

R1–R14 were observed on a build that is **not current `main`**. The :10028 site's plugin directory is a symlink into the operator's release store (`~/.local/share/altcontext/plugin-releases/`): base release `0.0.36-73db482d` (commit `73db482d4`, 2026-10-11, 397 commits behind `main` at the base SHA) plus a JS-only overlay (`…-fir-status1-a88861f897bc-js`, the `admin-WgZWXGPO.js` bundle in the console log; built before the UI7 work). The PHP in both has no `enqueue_bound_cluster_label_updates`. Plugin `Version: 0.0.36` is identical on `main`, so `?ver=0.0.36` cannot tell builds apart. The Python description service and recognition service versions behind :10028 are unverified.

Consequences:

- Every plan's first slice consumes the approved baseline receipt and checks fingerprints/freshness read-only (served artifact/release and relevant service binding/configuration, with unavailable fields UNKNOWN) before attributing a defect to current source. Offline current-source checks may proceed independently; this is not another approval gate.
- A defect that does not reproduce on current `main` is closed as "stale deployment" with evidence, not patched.
- Request a new operator deployment only for an evidenced fingerprint/configuration mismatch requiring one; do not request duplicate approval or wait globally for the already activated baseline. This lane performs no deployment or configuration mutation.
- Rows R9/R10, R13 and R14 were candidates to shrink after activation; fresh reproduction, browser persistence and GPU output remain separate evidence requirements.

## Prior art (semantic)

Queried with `find_related_prior_work` (embeddings verified) and lexical `search_handoff`; findings and decisions are referenced by ID, status lives in the ledger.

| Area | Prior art | Effect on this scope |
| --- | --- | --- |
| Review queue gate | DUX-L8-RV-02 (gate on `identityCount>1`), IDREBIND-1-W3-05 (toggle satisfies gate in place; "Open face group" separate), E21-14-R3-GOLDENS-01 (zero-member clusters still queued) | `WBTRUST-1` builds on the shared `isStoredFaceApprovalBlocked`; plans the zero-member queue entry as a visible repair/filter case |
| Similarity percent | decision 10706 (percent passes the confidence-theater check only as measured cosine against a *named fixed threshold*) | Binding: the percent is always rendered next to its threshold as distance-to-gate; weak state = colour + icon + the word "weak" (sr-004) |
| Label invalidation | IDREBIND-1-W3-01 (`invalidateLabelSurfaces` helper), UXW2-3-R1-02 (roster-loading/error gates commit), E21-5-BR-37 (stale show-all member list fixed) | `WBTRUST-3/4` extend the helper, not replace it; R4's stale list is not the E21-5 bug |
| Rename durability | decision 16666 (GTMSMOKE-1: `person_updated` ACK is a no-op; durable path is the WP cluster-label enqueue), `PersonRenameReplayTest.php` (RED→GREEN on `main`), contract `curation-sync-api.md` | `WBTRUST-3` S1 checks freshness against the activated 372a6413 baseline, then verifies durability; PHP edits stay conditional |
| Parallel FIR-UI work on `main` | NameFaceControl none-abstention, `useClusterRosterCandidates`, optional-read budgets (`useClusterSuggestions`, `useClusterMutations`, `ReviewQueue`, `ClusterLabelingPanel`), `PersonCommitControl.busyCandidates`, identity-suggestion transport tests | Base work for `WBTRUST-3/4`; do not rebuild. GTMSMOKE-1 remains ACTIVE: reuse prior art read-only; do not edit/close its finding 18547 |
| 429 / polling | UXP-NET-1 scope, FEBT-1 (http 429/503 → cooldown), UXW2-1 (shared write-through buffer), DEMOLAND-1 (`timeoutMs` never aborted an unsettled fetch), E21-20 (name-suggestion query not refetched by retry handlers), E21-18 (live region re-announced every SSE tick) | `WBTRUST-4` reuses the cooldown and buffer; asserts the retry handlers refetch the name query |
| GPU controls | decision 11085 (ISSUEDAG-1: no blanket new GPU control; hardcoded price/ETA copy must be configured and provenance-backed; total completed ≠ CPU drafts), decision 11113, `gpu-operator-control` map, E23 | `WBTRUST-5` moves/trims workbench copy; Settings stays the control home |
| Descriptions | DEMOLIVE-1-BR-01 → DADJ-10161 (seeded captions on the demo; default fixed to `florence_small`), anti-hallucination and description-quality scopes | Historical default only; Small is retired, never restored. Supplied full100 receipt proves seeded fixtures; `WBTRUST-7` exposes provenance, refuses fixtures and verifies the supported Qwen profile |
| Detection | decision 12793 (FIRDV-2 S3a design; Golden-150 validity withdrawn), FIR-11-S2R3-07 (`roster_only` recall refused), decision 16759 (`.85` threshold), GTMSMOKE-1 finding 18547 (0.9 cutoff rejects .85–.89 faces; open) | `WBTRUST-8` reuses the design, records the effective cutoff and scale, and feeds #81 to that finding |

Older scope docs skimmed for fit (headers and decisions, 2026-05…07):

- `workbench-clustering-ui-latency-refresh-scope.md` — the monotonic-progress and projection-refresh contract for "Analyze selected media"; `WBTRUST-4` must not break it.
- `roster-person-binding-scope.md` — an empty `wp_acx_persons` roster with confirmed cluster labels is a known state, and production name injection reads the cluster label, not the roster. This is why "Person" vs "Group" exists; `WBTRUST-3` hides the distinction in the UI but keeps both sources.
- `description-quality-track-scope.md`, `anti-hallucination-caption-generation-scope.md` — caption *quality* tracks. Out of scope here; `WBTRUST-7` changes provenance and routing only.
- `cpu-gpu-lane-control-plane.md`, `gpu-detailed-tier-oci-bursty-scope.md` — backend GPU serving and the privacy-first tier decision; they define what is automated/backend and therefore what `WBTRUST-5` should not surface as workbench configuration.

## MVP scope

Eight tasks, delivered in the waves below. Task-plan ownership is subject to the shared-surface handoffs below; logical independence alone does not authorize concurrent shared-file edits.

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

1. **No percentage without its evidence.** A match score renders only next to the reference image(s) it was computed against. Zero resolvable references → "Can't verify — reference image unavailable", no score, no approve (HAI-01, HAI-08, CAL-02, CAL-11). Where a score is shown it stays a measured percentage (operator order: percent, not normalized) rendered next to the named threshold it is judged against, as distance-to-gate and never a standalone truth score (decision 10706); a weak state pairs colour with an icon and the word "weak" (sr-004).
2. **Present evidence, don't gate on a toggle.** Reference faces are shown by default as a strip of real thumbnails (cap 6, "+N" opens the rest). Approve is enabled whenever ≥ 1 reference thumbnail is on screen. Low-band cards add a visible caution, not a lock (HAI-17, HAI-21, FORM-09, HAI-13).
3. **Frequent command first, configuration elsewhere.** The workbench carries the action and a one-line state; thresholds, leases, start/stop live in Settings (E23). Info is a popover or disclosure, not a new modal (INT-13, NAV-06, COG-07, INT-28).
4. **Every list that is long gets controls at both ends** (accepted operator requirement; NAV-21, *Bound lists for return trips*, `lexicons/interaction-ux.md#nav-21`, supports bounded navigation, not the two-control placement itself) and every control sits next to what it acts on (PERC-01, *Proximity binds meaning*, `lexicons/interaction-ux.md#perc-01`).
5. **Label outside the mark.** Overlay labels never sit on the subject (accepted operator requirement, not a universal VIZ-12 rule).
6. **Failures are named, not mimicked.** A rate-limit wait shows one status line, not N card errors; a fixture caption is labeled as a fixture (PERC-07, HAI-05, PROV-01).
7. **Measure before changing recall.** No detector or threshold change ships without an adjudicated set (accepted scope requirement; EVAL-16 concerns upstream misses in end-to-end identification and EVAL-19 concerns FPIR denominator dilution, not a generic provenance gate).

### Delivery order

```
Wave A (disjoint owned slices):    WBTRUST-4  WBTRUST-5  WBTRUST-6  WBTRUST-7  WBTRUST-8(measure)
Wave B (after WBTRUST-4):           WBTRUST-1  WBTRUST-3
Wave C (after WBTRUST-1 and -3):    WBTRUST-2
```

Step 0 is a read-only fingerprint/freshness check against the already approved, activated baseline; it is not a global Wave A redeploy/approval wait. Wave A offline current-source checks can advance independently. `WBTRUST-1/3` consume the actual `WBTRUST-4` budget/cooldown primitive. `WBTRUST-2` consumes `WBTRUST-3`'s settled naming control and follows `WBTRUST-1` because both touch `ReviewQueue.tsx`.

**Shared-surface ownership (binding over older task-plan lists):**

- `WBTRUST-4` alone owns request admission/cooldown-state production and its tests, including the state/countdown contract from `cooldownRemainingMs` and the existing `runAfterCooldown` primitive. It supplies that interface without editing `ActivityStatusStrip.tsx` or its rendering/layout tests.
- `WBTRUST-5` alone owns activity-strip interactivity/layout and its tests during Wave A. It supplies the final strip surface/copy without adding cooldown rendering. After both -4 and -5 finish, one later integration owner alone consumes -4's state contract and adds the single cooldown status line to -5's settled strip, with rendering checks. There are no contemporaneous strip writers.
- `apps/prototype-wp-alt-context/docs/ux-maps/describe-gpu-tier.uxmap.json` and its rendered `describe-gpu-tier.md` have **one later integration owner**, after `WBTRUST-5` and `WBTRUST-7` supply final control/provenance copy. Neither Wave A lane edits that shared pair. JSON remains the SSOT; the integration owner updates it and regenerates/checks the Markdown once. Reuse the existing maps/ASCII; no duplicate map system.
- Other shared-map writes (including `workbench-2pane` in later -1/-2) follow the same exclusive-file custody rule. Logical Wave A independence is not a measured simultaneous-admission capacity (GRPH-31, *Critical-path schedule the task DAG*, supplied canon v0.26.2 `lexicons/graph-theory.md#grph-31`).

**Executor (operator order 2026-10-15):** implementation and grunt work run on `claude-remote` `claude-haiku-5-5`, effort `xhigh`; each slice is briefed separately (1–3 files). If that write-enabled harness is denied or unavailable, record a blocker and ask the operator; do not fall back silently.

Preserve the review loop: first Haiku xhigh dispatch, Sol HIGH standard adjudication, then LOUD odd Opus / even Sol xhigh. This documentation author does not dispatch or merge. Actual main landing requires a fresh Sol xhigh R2 after the five disjoint documentation revisions join.

## Success criteria

1. A suggestion card never shows a percent without ≥ 1 rendered reference thumbnail; the contract test fails on the old behavior.
2. Opening the fir workbench with 31 suggestions: card 1/2/5 states are respectively "Can't verify", approvable with all stored faces visible, and absent (below the default floor) or visibly cautioned.
3. From a 47-face group the operator excludes mismatches and accepts the rest with one primary action. Counts are per entry context: pending suggestion ⇒ K reassigns + 1 existing confirm commit (including K=0 ⇒ 1 commit); unnamed group ⇒ K reassigns + 1 existing name commit (including K=0); named group with no suggestion ⇒ K reassigns + 0 commits, then close (including K=0 ⇒ zero writes and close). No new server commit or verified-membership flag. Run reassigns in order and stop on the first failure; do not confirm/name/close as success after a failed exclusion. Request-count acceptance covers each context and K=0 as well as K>0.
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

Everything above marked "verified" was read in the checkout at the base SHA. Items marked *hypothesis* or *unverified* each have a first-slice step that settles them. No browser was available to the planner, so interaction claims come from the operator's DOM snippets plus code. The "Step 0" release facts were read from the release store and the site's plugin symlink (read-only) and by counting `enqueue_bound_cluster_label_updates` in the served PHP. The `acx-smoke-*` fixture generator was not found in this repository; purging those fixtures from the fir tenant is an operator action. `make plan-analyze` was unavailable (no live `plan-draft` command id), so structure was checked by hand against the task-plan section list.

That paragraph describes the original planning pass, not execution in this adjudication lane. Current baseline/full100 facts above are supplied coordinator receipts; this lane performs offline documentation checks only. Product task completion, runtime/E2E, browser rename persistence and new GPU output remain UNRUN. FIRBENCH-1's private DB/corpus/model-cache/benchmark paths remain reserved and canon v0.26.2 is read-only.
