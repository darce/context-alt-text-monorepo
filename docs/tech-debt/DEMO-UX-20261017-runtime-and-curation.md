# Demo UX debt — runtime and curation (2026-10-17)

**Scope:** CURUX-1 follow-up classification of newly reported runtime and curation issues. This is a source-coverage audit, not an ADR-019 adjudication or product implementation.

**Source identifier supplied for this audit:** `08a1d066950911c98a0eb2e9080cd45873d7c3f4`. The mounted checkout is `635c48b1eb9843305d6398da5090d5d539384eaf`; the requested source commit is absent from the stripped object database, so its identity cannot be independently checked here. Anchors below refer to source files present in the mounted checkout.

**Evidence policy:** findings are `SOURCE-READ` unless explicitly identified as user-provided evidence. No browser/live reproduction, API call, database access, scan, GPU actuation, deploy, or test was performed. Source merged or present here is not evidence that it is deployed or fixed. The optional `workbay_canvas_mcp` package was unavailable, so the map CLI could not run; its local formatting helpers synchronized the changed sections in the owned Markdown only. The shared visible-projection snapshot was not changed, so renderer parity was not verified.

**Canon:** v0.26.2. This record uses stable rows [RLSE-04](https://github.com/darce/heuristics-canon/blob/v0.26.2/lexicons/engineering.md#rlse-04), [CAL-02](https://github.com/darce/heuristics-canon/blob/v0.26.2/lexicons/ml-systems.md#cal-02), [PROV-01](https://github.com/darce/heuristics-canon/blob/v0.26.2/lexicons/ml-systems.md#prov-01), [FORM-09](https://github.com/darce/heuristics-canon/blob/v0.26.2/lexicons/interaction-ux.md#form-09), [FORM-11](https://github.com/darce/heuristics-canon/blob/v0.26.2/lexicons/interaction-ux.md#form-11), [HAI-01](https://github.com/darce/heuristics-canon/blob/v0.26.2/lexicons/interaction-ux.md#hai-01), [INT-20](https://github.com/darce/heuristics-canon/blob/v0.26.2/lexicons/interaction-ux.md#int-20), and [GRPH-18](https://github.com/darce/heuristics-canon/blob/v0.26.2/lexicons/graph-theory.md#grph-18). Rule tiers remain specific to their source domains; priority below is a separate user-impact ordering.

## Final source classification

| ID | Reported issue | State | Priority | Canonical owner / existing coverage | Canon rule at use |
| --- | --- | --- | --- | --- | --- |
| U1-01 | Person-name combobox remains at “Loading people” while suggestions load | NEW_DEBT | P1 | CURUX-2 / ADR-019 proposed; WBTRUST-3 S3 owns advisory suggestion failure and usable Save, but not the current loading lock | [FORM-09](https://github.com/darce/heuristics-canon/blob/v0.26.2/lexicons/interaction-ux.md#form-09) |
| U1-02 | Review Queue shows “Unable to load unlabeled faces” and Retry in a zero state | COVERED_NOT_VERIFIED | P1 | WBTRUST-1 and E21-14-R3-GOLDENS-01 cover zero-member/queue trust; verify zero-result versus fetch-error classification | [RLSE-04](https://github.com/darce/heuristics-canon/blob/v0.26.2/lexicons/engineering.md#rlse-04) |
| U1-03 | “Description Service status unavailable” appears while service is dormant and no scan is active | COVERED_NOT_VERIFIED | P2 | GPUFLOW-3 `spa-activity-status` / `spa-activity-toasts` own status and edge copy; WBTRUST-5 owns placement only; no live reproduction was done | [RLSE-04](https://github.com/darce/heuristics-canon/blob/v0.26.2/lexicons/engineering.md#rlse-04), [CAL-02](https://github.com/darce/heuristics-canon/blob/v0.26.2/lexicons/ml-systems.md#cal-02) |
| U1-04 | URL/API-key save flow needs reliable local autosave, health sequencing, and secret-draft retention | NEW_DEBT | P1 | GPUOPS-1 L5/L6 split owns `SettingsPage.tsx` and `SettingsForm.tsx`; source has blur/Enter autosave, but partial-save failure clears the in-memory API-key draft | [FORM-11](https://github.com/darce/heuristics-canon/blob/v0.26.2/lexicons/interaction-ux.md#form-11), [INT-20](https://github.com/darce/heuristics-canon/blob/v0.26.2/lexicons/interaction-ux.md#int-20) |
| U1-05 | First cold GPU run may lose continuity when navigating away and back | COVERED_NOT_VERIFIED | P1 | GPUFLOW-3 `spa-run-resume`, GPUFLOW-2 operation context, and DESCAUTH-1 S15 cover the browser recovery path; infrastructure is separately FIXED_USER_EVIDENCE | [RES-19](https://github.com/darce/heuristics-canon/blob/v0.26.2/lexicons/engineering.md#res-19), [PROV-01](https://github.com/darce/heuristics-canon/blob/v0.26.2/lexicons/ml-systems.md#prov-01) |
| U1-06 | Retention says backend/service unavailable when endpoint may be dormant; Retry may do no request | COVERED_NOT_VERIFIED | P2 | GPUFLOW-3 S1/S2 and `spa-unavailable-reason` cover typed service/reason/fix/last-checked copy; client-side missing-endpoint branch still needs its own repro | [RLSE-04](https://github.com/darce/heuristics-canon/blob/v0.26.2/lexicons/engineering.md#rlse-04) |
| U1-07 | Settings service status reports unavailable; 15-second Retry/Refresh appears ineffective | COVERED_NOT_VERIFIED | P2 | GPUOPS-1 C5 and `useGpuControl`; source calls `refetch`, but request/cache/cooldown behavior was not observed live | [RLSE-04](https://github.com/darce/heuristics-canon/blob/v0.26.2/lexicons/engineering.md#rlse-04), [INT-20](https://github.com/darce/heuristics-canon/blob/v0.26.2/lexicons/interaction-ux.md#int-20) |
| U1-08 | Four July 8 failed cluster-label updates remain in a stale timeline | COVERED_NOT_VERIFIED | P2 | GPUFLOW-2 outbox recovery/history owns the rows; DESCAUTH-1 covers separate description history/reset behavior | [RES-19](https://github.com/darce/heuristics-canon/blob/v0.26.2/lexicons/engineering.md#res-19), [HAI-06](https://github.com/darce/heuristics-canon/blob/v0.26.2/lexicons/interaction-ux.md#hai-06) |
| U1-09 | Tribeca / Trudeau / Katy labels appear on wrong or repeated groups | NEW_DEBT | P1 | Extend GPUFLOW-3 identity integrity (`svc-scan-lock` / `spa-person-card`); WBTRUST-2 curation and WBTRUST-3 naming are partial coverage, not identity-lineage acceptance | [PROV-01](https://github.com/darce/heuristics-canon/blob/v0.26.2/lexicons/ml-systems.md#prov-01), [CAL-02](https://github.com/darce/heuristics-canon/blob/v0.26.2/lexicons/ml-systems.md#cal-02), [GRPH-18](https://github.com/darce/heuristics-canon/blob/v0.26.2/lexicons/graph-theory.md#grph-18) |
| U1-10 | `emma_watson_14-scaled.jpeg` appears three times with the same crop for one person | COVERED_NOT_VERIFIED | P2 | GPUFLOW-3 one-card-per-person / identity-integrity acceptance and GPUFLOW-2 singleton recovery cover the class; cross-link E15-17 finding 8472, E21-19 finding 8760, E21-15 finding 7867 / decision 4412, and E21-14 finding 7699 | [GRPH-18](https://github.com/darce/heuristics-canon/blob/v0.26.2/lexicons/graph-theory.md#grph-18), [PROV-01](https://github.com/darce/heuristics-canon/blob/v0.26.2/lexicons/ml-systems.md#prov-01) |

`COVERED_NOT_VERIFIED` means an existing source or plan has a matching behavior contract; it does not establish current deployed behavior. `FIXED_USER_EVIDENCE` is used only for the GPU infrastructure outcome supplied by the user. Source-only claims are tagged `SOURCE-READ`; there was no browser/live reproduction.

## Source anchors and missing acceptance

### U1-01 — naming input while suggestions load

**Evidence — SOURCE-READ:** `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/NameFaceControl.tsx:355-377,550-568` announces “Loading people”, disables the input through `isInputDisabled`, and returns before resolving/committing while `isLoading`. `docs/adrs/ADR-019-person-anchored-curation-surfaces.md:3,215-220` is Proposed, and its loading split says the text input stays enabled while suggestions load; only “Add as a new person” waits for the roster read. `docs/tasks/v0.5.0/WBTRUST-3-naming-ux-and-persistence-task-plan.md:113-118` says failed advisory reads leave the field and Save usable, but that is separate from the proposed ADR-019 distinction between free typing and roster-dependent “Add as a new person.”

**Missing acceptance:** with a deliberately slow or failed suggestion request, a user can type a new human name and complete the valid name action without waiting for suggestions; suggestions remain visibly pending/unavailable with Retry; controls that require the roster prerequisite remain disabled with a reason ([FORM-09](https://github.com/darce/heuristics-canon/blob/v0.26.2/lexicons/interaction-ux.md#form-09)). Do not treat the loading state as permission to create an unreviewed identity.

### U1-02 — zero-result queue versus top-unlabeled fetch error

**Evidence — SOURCE-READ:** `ReviewQueue.tsx:773-794,1548-1568,1627-1645` branches on `data.isTopUnlabeledError`: the alert and Retry render on error, while successful empty results use the empty/caught-up branch. `docs/tasks/v0.5.0/WBTRUST-1-review-queue-trust-task-plan.md` and E21-14-R3-GOLDENS-01 cover zero-member groups remaining visible; they do not prove the current top-unlabeled request classifies the reported zero state correctly.

**Missing acceptance:** a successful zero-face response renders a truthful empty/degraded state; a transport/server failure renders an error; clicking Retry issues the top-unlabeled request and presents its settled result ([RLSE-04](https://github.com/darce/heuristics-canon/blob/v0.26.2/lexicons/engineering.md#rlse-04)). Keep genuine failure visible and do not hide auth/API errors as dormancy.

### U1-03 — idle GPU status versus unavailable-service toast

**Evidence — SOURCE-READ:** `ActivityStatusStrip.tsx:87-95` maps `GPU_STATUS_UNAVAILABLE` to the reported copy. `useActivityStatus.ts:363-382` returns `IDLE` with `GPU_STATE.UNKNOWN` when the GPU status query errors without an active scan/run. GPUFLOW-3 rows `:594,600` assign the single activity-status authority and edge toasts; WBTRUST-5 owns placement/layout, not that state producer. This source path appears to separate a dormant status-read failure from an active run failure; no browser reproduction establishes which path produced the reported toast.

**Missing acceptance:** with no scan/run, dormant/not-checked service state stays idle and does not emit an outage toast. A real status failure during an active operation remains an explicit error with a useful next step. Preserve unknown as distinct from stopped, ready, and service outage ([RLSE-04](https://github.com/darce/heuristics-canon/blob/v0.26.2/lexicons/engineering.md#rlse-04), [CAL-02](https://github.com/darce/heuristics-canon/blob/v0.26.2/lexicons/ml-systems.md#cal-02)).

### U1-04 — URL/API-key autosave and health-check sequencing

**Evidence — SOURCE-READ:** `SettingsForm.tsx:237-273` commits URL and API key on blur or Enter. `SettingsPage.tsx:526-555` snapshots both dirty routing fields into one settings POST. Thus the report that only the distant global Save writes these fields is not confirmed by this source: a local blur/Enter path exists. On success, `SettingsPage.tsx:344-365` refreshes persisted Settings before scheduling the health check; probe generations and credential bindings are invalidated on edits (`SettingsPage.tsx:105-156,432-490,665-672`). However, `onSuccess` treats `result !== ok` as failure and refetches; `useSettingsPageState.ts:53-64` then clears `apiKey` on `syncFromSettings`, so a failed/partial save can discard the unsaved secret. Also, `commitRoutingFields` returns without queuing when another save is pending (`SettingsPage.tsx:526-530`).

**Missing acceptance:** local URL/key autosave works without requiring the distant global Save; commit the changed URL and new key together after a deliberate field boundary (blur/Enter); show local saving/saved/failed status; retain the typed key in memory on every failed or partial save without ever echoing or persisting it locally; retain or queue edits made during an in-flight save; run automatic health check only after a fresh GET confirms the persisted target; reject stale health responses after credential/target changes ([FORM-11](https://github.com/darce/heuristics-canon/blob/v0.26.2/lexicons/interaction-ux.md#form-11), [INT-20](https://github.com/darce/heuristics-canon/blob/v0.26.2/lexicons/interaction-ux.md#int-20)). Do not probe with an unsaved or partially typed key and do not re-run old-key tests. `SettingsPage.tsx:351` clears the API key after a fully successful save, so success feedback must not render the value.

The URL comparison between `fir.dev.api.altcontext.com` and the user-supplied proven `api.altcontext.com` is a **hypothesis to check**, not a verified configuration mismatch.

#### Settings routing state sketch

```text
Settings › Recognition service
  edit URL / type new API key (secret stays in memory; never echo it)
       │ blur or Enter with either field dirty
       ▼
  Saving URL + key together ── newer edit during save ──> keep dirty / queue latest pair
       │
       ├─ save failed or partial ──> show failure; retain typed key; offer repair/retry
       │
       └─ save OK ──> GET persisted Settings ──> automatic health check using persisted credentials
                                        │
                                        ├─ current probe: show result
                                        └─ stale probe after newer edit: discard result
```

The existing `gpu-operator-control` map now models this routing/autosave state cluster in the same Settings screen. Its owned Markdown includes the matching state zones and save/health flows; no second map was added.

### U1-05 — cold-start run continuity

**Evidence — SOURCE-READ:** `MediaSelection.tsx:78-98,255-310,1094-1129` retains run/selection context and renders queued/warming states. `useActivityStatus.ts:402-512` connects active and pending run identifiers. `GPUFLOW-3 ...task-plan.md:191` names reload recovery using `sessionStorage`, `GET /describe/run/{id}`, and warm-hook remount as browser acceptance. These source/task paths do not prove the reported browser route-away/back behavior.

**User-provided infrastructure evidence — FIXED_USER_EVIDENCE:** AD1 has been out of host capacity since July 16; AD2 is available and supplies the AD2-first candidate endpoints/winner route. GPUFAIL2 main commit `d25922fa5` is reported deployed to dev/staging/prod with `ACX_GPU_ROUTING_MODE=winner` and environment suite 847 passing. After the `beta_active` entitlement fix, PublicAPI `POST /scene/describe/run` with a demo key created run `1f957ad7`, which completed with persisted Qwen3-VL-30B `final_gpu` Coachella output; production `/ready` and demo request returned healthy responses. Demand cleared and idle-reaped. The two identity stores were wiped while keys/tenants were preserved; the prior 22-v-5 generation mismatch was gone at reset. This is user-supplied evidence and was not independently re-executed. It supersedes the prior infrastructure blocker; Polarbilling is separate.

**Residual acceptance:** navigate away during cold start and return without the original component state; recover the same run and review its persisted completed output. After the reported reset, a later authorized clean-generation scan should produce and discover the current generation; no scan was performed here. Keep endpoint/configuration, entitlement, readiness, and run errors distinct ([RES-19](https://github.com/darce/heuristics-canon/blob/v0.26.2/lexicons/engineering.md#res-19), [PROV-01](https://github.com/darce/heuristics-canon/blob/v0.26.2/lexicons/ml-systems.md#prov-01)). Do not reset, start GPUs, grant entitlements, or reimplement failover. Do not claim the saved `fir.dev.api.altcontext.com` URL is the deployed target; verify it against the proven production `api.altcontext.com` as a hypothesis.

### U1-06 — retention endpoint dormant versus unavailable

**Evidence — SOURCE-READ:** `retentionApi.ts:120-134` returns `{available:false}` without a request when `retentionStatus` is not configured; otherwise it performs GET. The source exposes `fetchRetentionStatus()` and the `retentionStatus` endpoint; there is no `descriptionAPI` symbol in these files. `RetentionPage.tsx:91-95,137-170` maps generic missing/error state to “Recognition service unavailable” and its Retry calls `retentionQuery.refetch()`. Thus Retry can repeat a local no-endpoint result when the endpoint is dormant. No configured endpoint or live request was inspected. **Existing coverage:** GPUFLOW-3 task plan `:73-80,217-233,529,532` owns the typed unavailable reason, service name, fix, and checked-at value across retention PHP and SPA lanes, including `not_configured`; it does not prove the client-side missing-endpoint branch makes a request or communicates that no request was sent.

**Missing acceptance:** name the Recognition/Description API and the `retentionStatus` dependency; distinguish endpoint not configured or feature dormant from a request that failed; show whether Retry will issue a request, and when configured prove the click refetches and updates the state ([RLSE-04](https://github.com/darce/heuristics-canon/blob/v0.26.2/lexicons/engineering.md#rlse-04)). Keep real auth/API failures visible.

### U1-07 — Settings Description Service refresh appears ineffective

**Evidence — SOURCE-READ:** `useGpuControl.ts:14-25,68-77` polls the GPU status query every 15 seconds normally and every 5 seconds while starting/warming, with React Query retry disabled. `GpuControlCard.tsx:325-343` wires both Refresh/Retry controls to `refetch()`; unavailable status renders around lines 360-414 and 626-630. The query key is `queryKeys.gpu.status()` and query function is `fetchGpuStatus`.

**Missing acceptance:** while reproducing the report, observe whether each click emits GET, whether the request is suppressed by `isFetching`, whether a server `Retry-After`/service cooldown applies, and which cached/error timestamp advances ([RLSE-04](https://github.com/darce/heuristics-canon/blob/v0.26.2/lexicons/engineering.md#rlse-04), [INT-20](https://github.com/darce/heuristics-canon/blob/v0.26.2/lexicons/interaction-ux.md#int-20)). Do not prescribe a cache or cooldown fix before that trace.

### U1-08 — old failed cluster-label operations in the timeline

**Evidence — SOURCE-READ:** `docs/tasks/v0.5.0/GPUFLOW-2-durable-describe-roster-identity-and-cluster-recovery-task-plan.md:40` records four failed “Cluster label update” outbox rows from 2026-07-08 and says failed rows remain until individually discarded. `apps/prototype-wp-alt-context/js/admin/pages/workbench/DeadLetterPanel.tsx` owns failed-change recovery UI. DESCAUTH-1 covers description generations/history and reset replay safety; that is adjacent, not authorization to replay cluster-label writes. The exact live rows were not queried.

**Missing acceptance:** render immutable old failures as history with timestamp and outcome, separately from actionable pending work; make retry/discard/archive effects explicit; preserve the original evidence/event IDs; do not blindly replay an obsolete label or generation ([RES-19](https://github.com/darce/heuristics-canon/blob/v0.26.2/lexicons/engineering.md#res-19), [HAI-06](https://github.com/darce/heuristics-canon/blob/v0.26.2/lexicons/interaction-ux.md#hai-06)). Add an archive/filter or another explicit terminal-history view to the existing owner plan rather than cloning a task.

### U1-09 — wrong or repeated named groups

**Evidence — SOURCE-READ:** `NameFaceControl.tsx:550-615` keys options by option value; `useClusterSuggestions.ts:47-118` composes person and cluster options by labels while retaining cluster IDs and suggestion identity IDs. `ClusterReviewPanel.tsx:148-169` operates on `member.identity_id`; `ClusterDrawerPanel.tsx:418-445` also keys face rows by `identity_id`. These are UI references, not proof that all group/member/generation lineage is presented or that a displayed name is curated. The reported Tribeca/Trudeau/Katy grouping was not live-reproduced.

**Missing acceptance:** before naming, show the relation from curated person (`identity_uuid`) to group (`cluster_uuid`), source face IDs, and producing generation; distinguish user-curated from machine labels; stale or unknown lineage must abstain rather than accept ([PROV-01](https://github.com/darce/heuristics-canon/blob/v0.26.2/lexicons/ml-systems.md#prov-01), [CAL-02](https://github.com/darce/heuristics-canon/blob/v0.26.2/lexicons/ml-systems.md#cal-02), [GRPH-18](https://github.com/darce/heuristics-canon/blob/v0.26.2/lexicons/graph-theory.md#grph-18)). Do not infer identity from filename, merge by display name, or treat similarity as proof. Extend GPUFLOW-3 identity integrity and cross-link WBTRUST-2/3 curation/naming; do not re-open their already covered UI slices.

### U1-10 — same-person duplicate cards for one image

**Evidence — SOURCE-READ:** GPUFLOW-2 `:39` documents same-person singleton residue turning one `emma_watson_14-scaled.jpeg` into three “Unnamed person” cards. GPUFLOW-3 target outcome `:57` and `spa-person-card` lane `:598` own one-card-per-person; `svc-scan-lock` `:584` owns one persisted identity row per physical face. The supplied prior findings identify distinct mechanisms to keep separate: E15-17 finding 8472 (seen set scoped per cluster), E21-19 finding 8760 (media-ID fallback can alias two faces), E21-15 finding 7867 / decision 4412 (null-bbox key and a refuted bbox-copy repair), and E21-14 finding 7699 (stale denormalized member count). Current review components use `identity_id` for face/member keys (`ClusterReviewPanel.tsx:148-169`, `ClusterDrawerPanel.tsx:418-426`), but this does not settle all card/dedup paths or prove the one-card contract is deployed.

**Missing acceptance:** same verified face is not duplicated across groups/cards; two different faces in the same image remain distinct; repeated identical crops for the same person resolve to one curated person view; use face/identity IDs and generation lineage for identity, never thumbnail URL alone ([GRPH-18](https://github.com/darce/heuristics-canon/blob/v0.26.2/lexicons/graph-theory.md#grph-18), [PROV-01](https://github.com/darce/heuristics-canon/blob/v0.26.2/lexicons/ml-systems.md#prov-01)). Preserve the user's ground truth that the three appearances are one person; do not merge by name/image alone or copy a bbox from another face.

## Follow-up ownership DAG (proposed sequencing, no new task rows)

```text
U1 classification / source-only record
  ├─ Settings state contract: GPUOPS-1 L5 owns SettingsPage.tsx save/probe sequencing
  │    └─ GPUOPS-1 L6 owns SettingsForm.tsx controls/rendering after the state contract
  ├─ Name suggestions: CURUX-2 / ADR-019 proposal → WBTRUST-3 S3 advisory behavior
  ├─ Queue empty/error: WBTRUST-1 zero-member contract → top-unlabeled request classification
  ├─ Activity strip: GPUFLOW-3 `spa-activity-status` / `spa-activity-toasts` → WBTRUST-5 placement/layout → browser no-scan + active-run check
  ├─ Run recovery: GPUFLOW-2 operation context → DESCAUTH-1 S15 browser recovery evidence
  ├─ Retention status: GPUFLOW-3 S1 typed reason → S2 copy/checked-at; separately verify client no-endpoint branch
  ├─ GPU status refresh: GPUOPS-1 C5 → trace refetch/cooldown before any change
  ├─ Failed label history: GPUFLOW-2 outbox history; DESCAUTH-1 reset/history remains separate
  └─ Identity lineage/dedup: GPUFLOW-3 `svc-scan-lock` + `spa-person-card` → WBTRUST-2 curation → WBTRUST-3 naming display
```

The DAG keeps each existing task as the canonical owner of its covered surface. New acceptance belongs in those artifacts through an authorized follow-up; this audit does not create duplicate task plans. Parallel work must remain on disjoint artifacts. The local map/document/report edits here are serial because JSON owns rendering and only one Markdown view is authorized.

## Explicit boundaries

- No product code, tests, deployments, credentials, database access, network/API calls, scans, resets, GPU calls, or entitlement grants.
- Do not amend ADR-019. It remains Proposed on this branch.
- Do not claim infrastructure as blocked: the user supplied GPUFAIL2 evidence supersedes prior infrastructure blockers. Browser final behavior remains unverified.
- Keep Polarbilling as a separate issue.
