# UXREC-1 workbench recovery inventory

Design preparation, 2026-10-21. **Proposed; map gate pending; no product implementation or runtime acceptance.** SSOT: existing `apps/prototype-wp-alt-context/docs/ux-maps/{workbench-operator-loop,describe-gpu-tier,workbench-identity-chips}.uxmap.json`; sibling Markdown is generated, never independently edited. No new map or confirmation tab.

Requested source: `70cb608c5cc6ee7e1081eab1cc85626ccb96bf2f`. VM checkout: history-stripped `d4760d2ba12869b0283a25c342b005e3cdc1aff1`; requested commit object is absent (`git diff --stat <requested> HEAD` exits 128). Snapshot source was read directly; exact-source parity cannot be independently certified. Initial `uv.lock` modification is unrelated and preserved. No foreign tree, runtime service, secret environment file or model was accessed.

Graph tools are not exposed in this session. Supplied indexed anchors belong to `ux-status-main-70cb608c5`; they are prior evidence, not a successful worker graph query. Native codemap packet is inherited `bad_json/unavailable`, not passed. UXREC-1 reinjection is `skipped:no_embeddings`, with zero relevant lines. Inherited MAINT verified reinjection and gte-base-en-v1.5 semantic results are prior art only. No backfill or invented nonempty packet.

## Current and target inventory

Paths below are relative to `apps/prototype-wp-alt-context/` unless prefixed otherwise. Source-fixed behavior is regression coverage, not new implementation work.

| Surface / trigger | Current source evidence | Smallest target / completion outcome |
| --- | --- | --- |
| Idle, GPU/capability unknown | `js/admin/pages/workbench/gpuStatePresentation.ts:77` promises CPU continuation in `notReportedNotice`; `useGpuStateToasts.ts:155` suppresses dormant unavailable toast when runId is null | Proposed neutral inline consequence: “GPU tier not reported. Description readiness is unconfirmed.” Preserve quiet idle; never infer CPU support, actual failure or completion from unknown GPU observation. |
| Configured service health error | `js/admin/pages/settings/GpuControlCard.tsx:324` names Description Service, cause/check time; Refresh/Retry refetches | Keep service-specific cause, checking and checked-at. Recognition configuration and generic API health are separate from description readiness. Settings recovery must not submit media or start GPU. |
| Genuine accepted run failure | `gpuStatePresentation.ts:89` onward retains timeout/poll/failure vocabulary; `js/admin/api/describeApi.ts:1498` status GET and `:1510` cancel POST | Preserve genuine errors, prior results, typed cause and supported retry. Status retry is a read; “queued” is not “succeeded.” No unsupported CPU fallback promise. |
| Warming, navigation/reload | `js/admin/hooks/describeOperationStore.ts` tenant-scoped sessionStorage and memory fallback; `useBulkDescribe.ts` resumes run_id; existing remount tests | Preserve accepted operation and cancel/read status. Return resumes the same run, never duplicate POST. Source persistence is not evidence of live warmup or final results. |
| Current attention vs audit | `js/admin/pages/workbench/DeadLetterPanel.tsx:149` defaults timelineStatus to all; `:552` supports one status per paginated query | Proposed default failed attention; pending/conflict explicit attention status choices; History explicitly exposes all/acknowledged/discarded. Keep records and pagination. Do not invent combined unresolved totals by filtering one page. |
| July failed label rows | `src/sovereign/sync/class-outbox-maintenance-service.php:1149` conditionally discards superseded exhausted label rows | DW3-UX0924-04 INTEGRATED per supplied audit, source mechanism present. Exact four July rows and eligibility remain unverified. Do not repeat old deferred status or promise erasure. |
| Repeated exact face across groups | `identity-clusters/utils.ts:111–194` groups by person_id then cluster_id, deduplicates same-face-in-media within a group and preserves identityClusterIds | Proposed evidence-only cross-group annotation; keep each original group/action scope. Same source/crop is evidence, not person equivalence or license for transitive merge. |
| Existing naming / review | `identity-clusters/IdentityClusterItem.tsx:530` uses namingReady independently of advisory loading; `ClusterReviewPanel.tsx:45` takes clusterId, removes by identity ID and pages Show all | Keep naming usable after mandatory roster ready; preserve actual review controls and mutation targets. Correction: wrapper is `IdentityClusterList.tsx:405`, not nonexistent IdentityClusters.tsx. `ClusterPreview.tsx` is noninteractive; pre-existing chip-to-workspace map is a target, not proof of live navigation. |
| Empty unlabeled | `js/admin/api/recognition/clusterApiQueries.ts:144` normalizes object with clusters array, data_source and conditional projection/count fields | Preserve exact object response; clusters=[] is valid. Bare lists and real transport/auth failures must not be disguised as empty success. |
| URL/key persistence | `js/admin/pages/settings/SettingsForm.tsx:265`, `js/admin/pages/SettingsPage.tsx:363,605` | Preserve blur/Enter commit, acknowledged stored readback and health after save; no key write while typing, no repeated credential onboarding. |
| Retention unavailable | `js/admin/pages/RetentionPage.tsx:79,165` service/cause/check time and actual busy refetch | Preserve inline recovery. Source ORM fix is inherited integrated evidence; runtime upstream500 remains unresolved. Retry success requires new service evidence, not a label change. |

Backend envelope: `apps/prototype-description-service/api/main.py:296–382` computes profile-specific description_adapter usable/reason; unavailable local dependencies/adapter and unconfigured GPU endpoint can refuse readiness. `scene/application/describe_run_worker.py:213–221,288–311` permits warmup CPU continuation only for a configured usable callable; otherwise persists typed failure. Therefore unknown GPU telemetry alone proves no CPU capability. Preserve exact API shapes and valid describe policy; no new readiness endpoint, adapter activation or threshold change is proposed.

## Screens and interaction contract

These are proposed content sketches, not captured runtime screenshots. Wide is approximately 90 text columns (two evidence/content roles); narrow is approximately 40 (one stacked column). Actual thumbnails use equal comparable cells with proportional source crops, no stretching. Source captions stay attached when stacking. Long source titles wrap; exact references are in an inspectable disclosure, not UUID-first headings. Read order follows visual order. Routine updates use the existing status line, with no repeated toast, sound or spinner after unchanged polls.

### Quiet idle / unknown service

```text
WIDE
+--------------------------------------------------------------------------------------+
| Review Queue                                          Settings                       |
| [selected image / proportional preview]  Describe selected                            |
|                                         GPU tier not reported.                       |
|                                         Description readiness is unconfirmed.         |
+--------------------------------------------------------------------------------------+
NARROW
+--------------------------------------+
| Review Queue                Settings |
| [selected image, proportional]       |
| Describe selected                    |
| GPU tier not reported.               |
| Readiness is unconfirmed.            |
+--------------------------------------+
```

Trigger: no active run and unavailable/unknown observation. Existing Describe remains the one primary action when a valid selection permits submission; this copy slice does not invent a disabled prerequisite. Settings is secondary. Tab/Enter activate real controls; static status is not focusable or an alert. On a successful status read, replace the observation without stealing focus. On read failure, remain unknown and retain selected work; manual status recovery lives in the existing service control, not a new global banner. This avoids a capability claim [HAI-05] and redundant feedback [PERC-10].

### Configured health error / actual run failure

```text
WIDE
+--------------------------------------------------------------------------------------+
| Description Service                    | Accepted run: Failed                        |
| Status unavailable; [reported cause]   | [reported run cause]; existing drafts kept   |
| Checked [actual time]                  | [Retry run]   Review existing drafts         |
| [Retry status] -> Checking...           | Retry queued is not completion.              |
+--------------------------------------------------------------------------------------+
NARROW (different states, not stacked everywhere)
+--------------------------------------+
| Description Service                  |
| [reported cause]                     |
| Checked [actual time]                |
| [Retry status]  Checking...           |
+--------------------------------------+
+--------------------------------------+
| Accepted run: Failed                 |
| [reported cause]                     |
| [Retry run]   Review existing drafts |
+--------------------------------------+
```

Health recovery and run recovery are separate screens/outcomes. Retry status invokes existing refetch, becomes busy and reports the newer checked-at/error; it never launches inference. Run retry uses the existing supported retry action only when retryable; results review is secondary and conditional on returned drafts. Retry status is the single primary recovery action in the health error sketch; retry run is the single primary in a retryable run error sketch. These are contextual target hierarchies, not a grant to edit reserved composition files. Keep focus on the initiating control, use aria-busy while pending and a polite result status; actionable failures remain inline and announced once. Success names the actual changed state. Missing configuration links Settings rather than repeating a futile start. No credential value is included. [FORM-05], [INT-19], [INT-22].

### Accepted warmup / cancel / navigation / resume

```text
WIDE
+--------------------------------------------------------------------------------------+
| Description run                        [Back to run after navigation]                |
| [observed starting/warming status]     [actual bound or unavailable observation]       |
| Existing results [count, if returned]  Cancel run    Review existing drafts            |
+--------------------------------------------------------------------------------------+
NARROW
+--------------------------------------+
| Description run                      |
| [observed state / actual bound]      |
| Existing results [reported count]    |
| Cancel run   Review existing drafts  |
| Navigation preserves accepted run.   |
+--------------------------------------+
```

Trigger: accepted run, not idle telemetry. Describe start is no longer actionable while the accepted operation is pending; cancellation is the prominent pending recovery action, review secondary if drafts exist. Escape/navigation does not silently cancel. Cancel POST acknowledgement and subsequent status determine cancellation; a failed cancel leaves the run visible with retry recovery. Tab/Enter operate Cancel, pending control has aria-busy, status updates are polite without focus movement. On remount, rehydrate the tenant run_id and resume GETs; do not replay submit. If storage is unavailable, report the actual memory-only durability limit instead of promising reload recovery. Completion offers actual draft review; retryable failure retains genuine error and prior results. [INT-10], [INT-20], [HAI-05]. Exact runtime startup/results remain unaccepted.

### Current attention / explicit history

```text
WIDE
+--------------------------------------------------------------------------------------+
| Changes: Current attention   History                                                 |
| Failed [selected]   Pending   Conflict                                                |
| Operation / target              Cause / age                 Action                   |
| [label update target]           [reported failure]           [Retry]  Discard         |
| No failed changes? Show that result; History still keeps records.                     |
+--------------------------------------------------------------------------------------+
NARROW
+--------------------------------------+
| Current attention   History          |
| Failed [v]                           |
| [operation and readable target]      |
| [cause] / [age]                      |
| [Retry]   Discard                    |
| Page [current server-filtered page]  |
+--------------------------------------+
```

Trigger: open Changes. Target defaults to failed attention; pending/conflict selected explicitly, not a fabricated combined API status. History uses the existing all/status query and retains audit records. Native buttons/select provide Tab/Enter and normal select keys; use aria-pressed for view buttons and an associated select label, not incomplete custom tabs. Switch resets the newly selected query offset; returning restores the prior view's position if feasible within panel ownership. Announce loaded count/view politely, keep focus on view control. Mutation success says queued/discarded, failure stays row-local. Existing guarded Discard is never the primary. Empty current attention must not claim all history is empty. Read-only view changes never discard or reconcile rows. [INT-19], [INT-22].

### Duplicate-face evidence / safe review

```text
WIDE
+--------------------------------------------------------------------------------------+
| Repeated source-face evidence             [Review faces]                             |
| Source photo [visible title]              Same source face appears in 2 groups        |
| [proportional crop] [proportional crop]    Evidence is not an identity merge.           |
| Group A             Group B               Details v   Show all available evidence     |
| Details: source media ref, bbox, each exact group ref and face/identity ref            |
| Displayed 2 observations / [available total]; coverage [complete or incomplete]        |
+--------------------------------------------------------------------------------------+
NARROW
+--------------------------------------+
| Repeated source-face evidence        |
| Source photo [visible title]         |
| [crop A]  [crop B]                    |
| Group A   Group B                    |
| [Review faces]   Details v           |
| Details: exact source/group/face     |
| refs, bbox and displayed/total       |
| Show all available evidence          |
+--------------------------------------+
```

A/B and counts above are illustrative fixtures, not recovered Emma group IDs. No exact corpus face/group IDs were supplied or discovered in this design lane. Product disclosure must render the actual API references verbatim for each observation; missing fields say unavailable. Do not fabricate UUIDs. The user identifies the supplied Emma crops as one person; retain that ground truth without deriving any new name from filenames, captions or image similarity.

Proposed repeated-evidence derivation is separate from unchanged grouping and action scopes. It should prefer an exact source + face correspondence if provided; bbox/source matches must describe their method and ambiguity, not claim byte-identical faces from arbitrary overlap. Different photos of the same person are identity-recall evidence, not exact-source duplicates. A camera can repeat a capture; a detector can duplicate overlapping boxes; a group can duplicate a face reference. These are distinct hypotheses. Show the mechanism and alternative account, not a single definitive diagnosis [VIZ-23].

Review opens the existing available face-review path for the selected actual group; no new merge UI or endpoint is assumed. If chip-to-panel wiring requires reserved owners, keep the disclosure-only slice and request a coordinated extension. Details uses native disclosure, aria-expanded and a meaningful accessible name; Tab/Enter opens review; close returns focus to its trigger. Member removal still targets the original identity ID, naming targets its existing editable cluster/person. Success preserves source/action correspondence; load failure retains available evidence and offers read-only retry. Disclose displayed/available totals, truncated/loading/incomplete coverage, source ordering and which representative was selected; Show all is not proof of exhaustive corpus coverage [VIZ-41]. No automatic merge, global visual dedup or transitive similarity closure [GRPH-18].

## Pinned authority and design decisions

Applied **Canon v0.26.2**, pinned local manifest `/home/gate/heuristics-canon-v0.26.2/meta/release-manifest.json`; canonical project: https://github.com/darce/heuristics-canon . No web summaries used as authority. Full triggered rows, PRINCIPLES.md and all matching Rule IDs cards were read. Matching card: `reasoning/perceived-enforced-boundaries.md` (CARD-12); its verification is applied by matching visual groups to unchanged data/action targets and refusing an unsupported automation envelope. Principle 10 sibling checks (security, architecture, team boundaries) reinforce this separation; no new auth or organization implementation is claimed. Disconfirmer: a configured tested CPU envelope could justify conditional capability copy, but GPU unknown alone cannot. Next feedback boundary: map review, then focused source tests, then separately granted runtime acceptance.

Manifest SHA256 verification passed for interaction-ux `986a319d91f00c5c96382b3b299b2dee6f23cc64d89cd50e125ddbe8f5203659`, graph-theory `23bdbc8262cbd3577e4fd5ef3e49c6ad1f50fdfd1472ba3990497ef57e3eb61c`, design-aesthetics `ef47bce7e1b65f9082a409e50ab67aaaf6c66e751b03132e4dfb3896d48a3018`, accessibility `4f6dba17a0026ba1971fba0bda21f35b63882a92cccf47f45a90f0f87267a246`; also AGENTS.md, PRINCIPLES.md and CARD-12 matched. Sibling security/engineering/planning lexicons were separately digest-checked. Row anchors below resolve under the pinned release's lexicons; source titles/locators are exactly the published Source cells.

| Decision | Stable row authority (Canon v0.26.2) |
| --- | --- |
| Neutral unknown/capability claim | [HAI-05] **Imperceptible AI is not ethical**, `interaction-ux.md#hai-05`; *Human-Centered AI* |
| Accepted run shows progress, next step, cancel | [INT-10] **Status–predict–stop**, `interaction-ux.md#int-10`; *Human-Centered AI* |
| Separate health recovery, run completion, evidence review | [INT-19] **One outcome per interaction**, `interaction-ux.md#int-19`; *Microinteractions, ch. 1* + *Microinteractions, ch. 3* |
| Remount/retry does not silently resubmit automatic work | [INT-20] **Manage automatic starts**, `interaction-ux.md#int-20`; *Microinteractions, ch. 2* |
| Queued/checking/completed are distinct results | [INT-22] **Explain the result**, `interaction-ux.md#int-22`; *Microinteractions, ch. 4* |
| Quiet idle and unchanged polling | [PERC-10] **Least useful feedback**, `interaction-ux.md#perc-10`; *Microinteractions, ch. 4* |
| Preserve inline recoverable save errors and stored readback | [FORM-05] **Inline actionable errors**, `interaction-ux.md#form-05`; *Designing Interfaces, 3rd ed.*; [FORM-08] **Echo-back stored interpretation**, `interaction-ux.md#form-08`; *Pattern Languages of Program Design, ch. 10* |
| Fit wide comparison and narrow stacking to actual copy/image roles | [LAY-23] **Scale the grid to complexity**; [LAY-24] **Content-and-frame grid**; [LAY-25] **Use zones and spans**, `design-aesthetics.md#lay-23` / `#lay-24` / `#lay-25`; each *Thinking with Type, ch. 3* |
| Approximate real copy lengths and proportional crops in sketches | [LAY-28] **Proportional thumbnail**, `design-aesthetics.md#lay-28`; *Grid Systems in Graphic Design, ch. 11* |
| Repeated evidence never merges identities | [GRPH-18] **Never trust the transitive closure of a raw similarity threshold**, `graph-theory.md#grph-18`; *Introduction to Information Retrieval, § 17.2* |
| Source/crop/group comparison, mechanism and alternatives | [VIZ-23] **Show the evidence path**, `interaction-ux.md#viz-23`; *Richard Feynman's Mental Models, ch. 5* + *Envisioning Information, ch. 4* |
| Inspectable selection and available pool before consequential review | [VIZ-41] **Reveal the image-selection pool**, `interaction-ux.md#viz-41`; *Visual Explanations, ch. 1* (J: applied to representative selection, not decoration) |

LAY-27's published trigger is repeated **print pages**; it was read but is not cited as a mandatory screen rule. Aligned thumbnail cells are a design interpretation using the applicable content/frame rules, not a rewritten LAY-27 trigger. GRPH-07 has no capacity-constrained agent assignment in this no-delegation lane and is inert. GRPH-09's actual conflict edges are described in the task plan. Tufte's evidence path requires inspectable relevant data and alternatives; it supplies no warrant for decoration or hidden essential evidence.

## FIR prior research boundary

Read `benchmarks/reports/fir-embeddings-dims-detectors-qa-20260723.html`, especially `#v13-caption`, `#v12`, `#v12-space`, `#v12-config`. This report is dated research and prior VM measurements, not current service readiness and not published rule authority.

- Caption comparator: Qwen3-VL-30B-A3B-Instruct Q4_K_M, profile pin abbreviated `0af19e…` in the report; raw single-view and async four-view ensemble are distinct research arms. Qwen3.8-27B UD-Q4_K_XL (`1cff33…`) is a challenger, not promoted. Florence fallback when adapter unset is configuration drift, not proof the current tenant can use CPU. EmbeddingGemma 2 is semantic ranking research, not a face recognizer or caption generator.
- SFace: 128D, L2-normalized/cosine, in-house YuNet/five-point alignment and ORT; existing isolated 128D FIR space. Do not pad vectors or infer compatibility from equal dimensions.
- AuraFace-v1: `glintr100.onnx`, publisher revision `af6d057c9b0ec4071d4c49c80e3539258798b609`; report model digest `a7933ea5330113b01c9b60351d8f4c33003f145d8470ac5f0e52ee2effe25c60`. 512D raw graph output, in-house L2 normalization/cosine; ArcFace 112 alignment, BGR crop to RGB NCHW `(pixel-127.5)/127.5`. Model identity includes numeric runtime versions (report `cv5.0.0/ort1.29`). Separate fresh 512D database/enrollment from pixels, not InsightFace runtime or reused buffalo vectors.
- Namespace contract is weights/revision + preprocessing/alignment + normalization + metric + runtime version + store, scoped by modality/model. PGVECTOR_DIM must agree with the actual space; it is not a model migration control. Incumbent InsightFace/buffalo 512D is a third space. No cross-space centroid import or implicit fallback. Semantic gte-base-en-v1.5 handoff embeddings belong to a different task-retrieval namespace; this packet supplies no dimension/normalization proof for that service.
- Candidate measurements do not establish activation, quality, successful descriptions or fresh enrollment. Detector duplicate-box/capture hypotheses and identity-recall hypotheses need separate corpus probes; no threshold tuning or re-inference is authorized here.
