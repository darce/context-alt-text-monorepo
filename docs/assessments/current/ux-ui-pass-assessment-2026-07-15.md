# UX/UI Pass Assessment — Workbench, Roster, Dashboard, Media (2026-07-15)

**Task:** UXP-1 · branch `feature/uxp-1`
**Method:** operator walkthrough (2026-07-15 session), heuristics-canon lexicons (accessibility, design-aesthetics, writing, engineering — vendored at `docs/reviews/uxp-1/lexicons/`), codemap-grounded architecture deep-dive, grok-4.5 offload lane sweep (`docs/reviews/uxp-1/grok-ux-audit-findings.md`).
**Consolidates with:** Epic E21 (`docs/epics/v0.4.1/public-mvp-ux-polish-epic.md`), E15 Phase-6 operator-UX tasks, E20 alt-text workflow epic, prior assessments in `docs/assessments/current/` (WBUX-1/WBUX-2), and live planning-review findings `UXPR-01..15` (stored in workbay-handoff MCP under review run `planrev-e21-uxui-20260712-01` — query there; not mirrored here).

All paths relative to `apps/prototype-wp-alt-context/` unless noted.

---

## 1. Executive summary

The 2026-07-15 walkthrough surfaced 16 issues. Root-causing shows they cluster into **five structural defects**, not sixteen independent papercuts:

1. **No 429/backoff discipline in the frontend fetch layer.** Every React Query poller retries status-blind; the recognition service rate-limits (60 rpm/tenant, burst 10) and the UI immediately saturates it, producing the console 429 storm.
2. **Service status is inferred from traffic, not measured.** The offline/"Waiting for service" banner reads a circuit-breaker transient that only changes when proxied requests fail; when idle, the UI can't know the OCI VM's real state (it reports healthy while down, and looks "dormant" after jobs stop).
3. **Two identity stores with a one-way seam.** Cluster labels live in the recognition service; `wp_acx_persons` rows only exist after roster commit. This single seam produces the duplicate "Flaxen Yarrow" rows, the empty Entries tab, dashboard People=0-while-Pending=17, and the typeahead's apparent failure to surface curated names.
4. **View state is transient and traffic-coupled.** Media-table collapse is a `useState` reset on a findings rising edge — no URL/localStorage persistence — so the table "disappears" after clustering and on every navigation.
5. **Copy and disclosure debt.** Data-science jargon ("Clusters", "Delta sync", "Retention posture"), an always-expanded clustering glossary, and ambiguous threshold semantics leak implementation vocabulary into an operator surface.

Most fixes have a planned home in E21/E15/E20 (consolidation matrix in §4). Genuinely **new** work: frontend 429/backoff seam, real service heartbeat, attachment-edit-page face overlays, pin-toggle removal/rework, typeahead filter fix, and a copy pass.

---

## 2. Findings

Format: observed → root cause (evidence) → heuristic → recommendation → consolidation.

### UXA-01 · 429 retry storm (blocker)
- **Observed:** console flooded with 429s for `/recognition/jobs/{id}`, `/suggestions/name`, `/identities/{id}/suggestions?top_k=1`; queries keep refetching into the limiter.
- **Root cause:** `js/admin/utils/http.ts:37-49` `fetchApi` throws a generic string `Error` — no status field, no `Retry-After` read. QueryClient (`js/admin/App.tsx:15-23`) retries status-blind (`retry: 1`, exp `retryDelay` capped 30s). Job poll fixed at 1500ms (`js/admin/hooks/useRecognitionHooks.ts:32-39`); describe-run poll 2000ms `retry: 3`; suggestion queries fan out per-identity with `top_k=1` (N parallel requests per render). The PHP layer does not rate-limit inbound REST; the 429s originate in the recognition service per-api-key sliding-window limiter (`http/deps/rate_limit.py:42-85`, 60 rpm STANDARD via `recognition/config/security.py:63-66`), which itself sends `Retry-After` + `X-RateLimit-*` (as does the per-IP demo limiter, `http/deps/ip_rate_limit.py:77-100`) — the frontend just never reads it. [Corrected 2026-07-15 per UXP-NET-1-PR-09; original text misdescribed the mechanism as a per-tenant token bucket with burst 10.]
- **Heuristic:** eng lexicon unbounded-retry/backoff rules; rg-007 analog (bounded stall detection) applied to client polling.
- **Recommendation:** one seam fix — typed `HTTPError {status, retryAfterSeconds}` in `fetchApi`; QueryClient `retry`/`retryDelay` honor `Retry-After`, never retry 4xx except 429, pause pollers while a 429 cooldown is active (shared cooldown state, not per-query). Batch the per-identity `top_k=1` suggestion fan-out into one list endpoint call.
- **Consolidation:** **NEW** (frontend seam uncovered; E20-4/E20-7 own server-side budget governance only).

### UXA-02 · Service status banner lies when idle (blocker)
- **Observed:** "Working offline / Waiting for service… / Retry sync" persists or appears incorrectly; user asks whether status is coupled to GPU/job activity instead of pinging the OCI VM.
- **Root cause:** confirmed — there is no health ping. `useSyncHealth.ts:6-14` polls WP-local `sync/health` every 15s, which only reads the proxy circuit-breaker transient (`src/api/class-sync-health-controller.php:54-89`); the breaker opens after 2 failed proxied requests and auto-expires in 60s (`class-abstract-recognition-proxy-controller.php:428-436`). With no traffic, state reverts to closed regardless of actual service health. "Waiting for service…" is a post-job sync-failure string (`useJobStateMachineEffects.ts:183`), also traffic-derived. The only real probe is Settings → Test connection (`GET {base}/health/detailed`).
- **Heuristic:** visibility of system status must reflect measured state, not inferred state (eng/a11y honest-status rules; GTM AIPX-07/10 "honest state" requirement).
- **Recommendation:** authenticated lightweight heartbeat (reuse the settings probe path) feeding the same breaker/health transient — either piggybacked on the 15s `sync/health` read (server-side cached ping, e.g. 60s TTL) or a WP-cron heartbeat. Banner then distinguishes: *offline (measured)* / *degraded (breaker)* / *idle-unknown* honestly.
- **Consolidation:** extends **E21-1/E21-7/E21-13** (shipped banner/breaker surfaces); the heartbeat itself is **NEW**.

### UXA-03 · Bulk-accept panel: unclear semantics, questionable granularity (major)
- **Observed:** slider "Minimum confidence 60%" + three buttons (assignments/names/merges); unclear whether it affects the next clustering turn or retroactively changes cluster membership.
- **Root cause / answer:** bulk accept applies the threshold to *currently pending suggestions* at accept time — a one-shot filter, not a clustering parameter and not retroactive re-clustering. The UI gives no such explanation, and percent-granularity implies precision the operation doesn't have.
- **Heuristic:** design-aesthetics judgment rows (thrift of controls; every affordance must answer "what happens next"); writing lexicon ambiguity rules.
- **Recommendation:** per the user's heuristic question — this component is **not needed in its current form**. Fold bulk accept into the E21-5 unified review queue as a single "Accept all above high confidence" action with preset bands (conservative/balanced/aggressive) and one sentence of consequence copy ("Accepts N pending suggestions now; does not re-cluster existing groups."). Show live preview count N before commit.
- **Consolidation:** **E21-5** (unified review queue owns accept flows) — add these acceptance criteria there.

### UXA-04 · Media table disappears after clustering (major)
- **Observed:** table vanishes when a clustering job completes; reads as a rendering bug. Also not shown when navigating back to workbench.
- **Root cause:** deliberate auto-collapse on the findings rising edge — `ScanTabContent.tsx:46-51` resets `userExpandedMedia=false` when `findings.hasFindings` turns true; state is a transient `useState` (`:43`), so remounts also wipe it. Collapsed renders a stub (`MediaSelection.tsx:94`).
- **Heuristic:** user control & freedom; no destructive-looking implicit state changes (design lexicon layout/continuity rows).
- **Recommendation:** persist expansion in a URL param (workbench already has `useTabParam`/`useOverlayParam`); collapse only on the rising edge with an explicit affordance ("Media list collapsed — expand" inline control), never on remount/navigation.
- **Consolidation:** **E21-10** (cross-surface link/URL-state contract) — add media-table state to its param inventory.

### UXA-05 · "Analyze selected media" only at page bottom — and hidden when collapsed (major)
- **Observed:** primary action lives below the fold of a long table.
- **Root cause:** `MediaAnalyzeCta.tsx` is composed only under the media-table footer; worse, when the table auto-collapses to `MediaSummaryBar` (UXA-04) the analyze CTA **disappears entirely** — the primary scan action is unreachable until the user finds "Show media table" (grok UXG-03/04).
- **Heuristic:** rg-003 (primary controls reachable from zero state); CTA hierarchy.
- **Recommendation:** sticky action bar or duplicated top placement; keep the CTA visible in the collapsed summary bar; exactly one visual-primary CTA per state.
- **Consolidation:** **E21-5** explicitly owns the "Analyze selected"/"Describe with AI" CTA hierarchy — fold in.

### UXA-06 · "Advanced: jobs & recovery" disclosure + glossary bloat (minor)
- **Observed:** dictionary-style "What is Clustering?" paragraph permanently occupies screen space inside the drawer; section usefulness questioned; "Latest job — No job yet / Status — Pending" contradictory zero state.
- **Heuristic:** progressive disclosure; writing lexicon — explain at point of need, not permanently.
- **Recommendation:** keep the drawer (E21-3 shipped it; job history/recovery has operator value) but move the clustering definition to a help tooltip/`?` popover; fix the zero state ("No jobs run yet" single line, no fake Pending status).
- **Consolidation:** residual copy/zero-state polish on the shipped **E21-3** surface — small **NEW** polish item.

### UXA-07 · Pin/"Pinned" toggle overlays avatar (minor, uncovered)
- **Observed:** `.acx-identity-cluster__pin-toggle--pinned` button renders on top of the face thumbnail; purpose ("pin representative") unclear; possibly unnecessary.
- **Root cause:** `ClusterPreview.tsx:58-70` drops a full WordPress `button button-small` inside the 40×40 `position: relative` preview box, and **no `__pin-toggle` CSS exists anywhere in styles/** — an unstyled button painting over the avatar (grok UXG-05; also a hit-target/a11y fail).
- **Heuristic:** thrift of accent / minimal primary surface (design lexicon); every control must earn its place; A11Y target-size.
- **Recommendation:** remove the pin control from the compact cluster card entirely; if representative-pinning is retained, move it into the cluster detail/split view as an icon-button with tooltip, never overlapping the image.
- **Consolidation:** **NEW** — no planned item covers the pin toggle (confirmed gap).

### UXA-08 · Naming typeahead doesn't surface curated labels (major)
- **Observed:** under "Name this person", typing a person's name that was already curated doesn't suggest it → looks like a duplicate entity gets created.
- **Root cause:** the panel *does* load roster persons (`ClusterLabelingPanel.tsx:110-114` via `useRosterEntries`), but persons only exist after roster **commit** — labeled-but-uncommitted clusters never appear as options (see UXA-09), so a just-named person looks absent. Two secondary defects: `ClusterEditForm.tsx:67-68` slices the first 5 options (verify filter-before-slice ordering at implementation), and the duplicate-label lookup is best-effort with a short timeout that silently falls back to plain save (`ClusterLabelingPanel.tsx:138-166`). Grok note (UXG-09): the combobox and the duplicate-merge path query two different ontologies (persons vs labeled clusters).
- **Recommendation:** unify suggestion source to persons **plus labeled clusters**; filter by input before any slice; make the duplicate-label check blocking-with-warning rather than silent fallback.
- **Consolidation:** filter/slice fix is **NEW (quick win)**; suggestion-source unification belongs to **E21-9 / E15-17**.

### UXA-09 · Roster duplicates; Entries vs Clusters split (blocker, structural)
- **Observed:** "Flaxen Yarrow" appears twice with separate identity counts; unmerged; "Entries" tab exists but renders empty; "Clusters" is data-science vocabulary.
- **Root cause:** two stores. Entries = WP `wp_acx_persons` projection (`GET acx/v1/roster/entries`, `class-api.php:158-162`); Clusters = recognition-service data via proxy. Cluster labels are free text per cluster; nothing groups same-label clusters into one person until commit (`class-api.php:359,511` dedupes person rows by exact name only at create/commit). Empty Entries = no commits yet — the same seam that zeroes the dashboard People count.
- **Heuristic:** sr-007 analog (single canonical definition of domain state); match system vocabulary to operator vocabulary (writing lexicon).
- **Recommendation:** person-first roster: group clusters by resolved person/label server-side (cluster read service or recognition query), retire the Clusters tab as an operator surface, and make label-curation create/attach the person projection so Entries is never empty after naming.
- **Consolidation:** **E21-9** (person-first roster, Clusters-tab retirement) + **E15-13/E15-17** (person projection & curation-loop contracts). Add the "label ⇒ projection write-through" acceptance criterion explicitly.

### UXA-10 · Dashboard counts stale/contradictory (major, same seam as UXA-09)
- **Observed:** People 0 / Assigned 0 / Pending Review 17 right after a curation session; page doesn't reflect what was just done.
- **Root cause:** `dashboard/stats` computes from WP-local tables only (`class-api.php:944-988`); label curation writes to the recognition service and never touches `wp_acx_persons`; plus `staleTime: 30_000` (`useIdentityStats.ts:10`) and no invalidation from cluster mutations.
- **Recommendation:** count curated (labeled) identities in the stats SQL or write through the projection on label-commit; invalidate `queryKeys.dashboard.stats()` in cluster-mutation `onSuccess`.
- **Consolidation:** **E15-15/E15-16** (dashboard triage/diagnostics) with the projection dependency on **E21-9**.

### UXA-11 · "Retention posture" card (minor)
- **Observed:** "Retention posture — Retention status is unavailable right now." Operator has no idea what retention means here.
- **Root cause:** renders whenever `retentionPolicy` is falsy (`DashboardPage.tsx:226-240`) — breaker-gated 2s-timeout proxy failure, loading, **or the retention endpoint simply missing from boot config**, which returns `{available:false}` silently with no remediation hint (`retentionApi.ts:69-78`, grok UXG-11); jargon title; E21-13 explicitly deferred retention remote-op offline gating (finding RES-03).
- **Recommendation:** rename to operator language ("Data retention"), collapse the card entirely when unavailable (or show "Requires service connection" with the honest status from UXA-02), and pick up the deferred RES-03 gating.
- **Consolidation:** **RES-03 deferred follow-up** + copy pass (**NEW**).

### UXA-12 · Sync banner copy incoherent (major)
- **Observed:** stacked fragments — "i / Local changes are waiting to sync. / … / Queued / Delta sync / Pending changes: 3" — no actionable meaning; dashboard Sync Health simultaneously shows "3 Pending changes / 0 Conflicts".
- **Root cause:** status strip renders raw state-machine vocabulary ("Queued", "Delta sync") from the sync view-model (E21-1 surface) without operator translation.
- **Heuristic:** writing lexicon — status copy must state consequence + next action; one message per state.
- **Recommendation:** single-sentence states: "3 changes saved locally — they'll sync when the service reconnects." with one action (Retry). "Delta sync"/"Queued" become internal only.
- **Consolidation:** copy layer on shipped **E21-1/E21-13** surfaces — part of the **NEW copy pass** work package.

### UXA-13 · Attachment edit page: no face overlays (feature gap)
- **Observed (user expectation):** on `post.php?post=…` for an attachment, curated faces should render as positioned overlays with names; uncurated faces show bounding box on hover + a list in the right pane under metadata.
- **Root cause:** no integration exists — zero hooks into `attachment_fields_to_edit`/`edit_attachment` (`src/` grep clean); bbox math exists only in the React `FaceThumbnail` (`js/components/ui/FaceThumbnail.tsx:1-30`) and XMP writer (`src/media/class-image-xmp-writer.php:172-180`); media-identities endpoint already serves the data (`src/api/class-media-identities-controller.php`).
- **Recommendation:** new bounded feature: `attachment_fields_to_edit` panel + small enqueue reusing `FaceThumbnail` bbox math over the full-size image; curated = named overlay always on, uncurated = hover bbox + right-pane list.
- **Consolidation:** **NEW** work package (no epic owner; closest neighbor E20-5 review/history workspace).

### UXA-14 · Media table lacks alt-text/caption columns (minor)
- **Observed:** alt text appears only as inline "No alt text yet" detail (`MediaSelectionTableBody.tsx:121`); no caption; user wants the table to "carve out room" for both.
- **Recommendation:** dedicated truncated alt + caption columns with missing-state chips; pairs with E20-2 (missing-alt query) and E20-5 (inline edit).
- **Consolidation:** **E20-2/E20-5**.

### UXA-15 · A11y notes (cross-cutting)
- Pin toggle overlaying the image is also a focus/hit-target hazard; status conveyed by color+text in banners is mostly OK post-E21-4, but new states from UXA-02/12 must ship with `aria-live` announcements per the E21-1 harness. Bulk-accept preset copy (UXA-03) must be announced with result counts. Sweep detail in grok findings doc §D.

### UXA-16 · Copy/vocabulary debt (cross-cutting)
- "Clusters", "identities", "Delta sync", "Retention posture", "awaiting_projection"-flavored states leak into operator UI. One copy pass across banner/roster/dashboard/advanced-drawer strings, governed by the writing lexicon; inventory table in grok findings doc §C.

---

## 3. Answers to the user's direct questions

| Question | Answer |
| --- | --- |
| Is service status linked to GPU/job activity? | Effectively yes — it is derived from proxied-request failures (circuit breaker transient, 60s expiry), so it goes dormant/incorrect when no jobs run. It never pings the OCI VM. Fix = UXA-02 heartbeat. |
| Is the bulk-accept component needed? | Not in its current form. Threshold applies one-shot to pending suggestions (not retroactive, not next-turn). Replace slider with preset bands + consequence copy inside E21-5 (UXA-03). |
| Should the media table disappear after clustering? | No — it's an intentional auto-collapse that reads as a bug; persist state in URL and add explicit expand affordance (UXA-04). |
| Is "Advanced: jobs & recovery" useful? | Yes (job history/recovery), but the glossary must become on-demand help and the zero state must stop showing "Pending" (UXA-06). |
| Is "pin" needed? | No planned owner and weak value on the card; remove or relocate to detail view (UXA-07). |
| Why "Entries" and "Clusters" both? | Two data stores; Entries is the committed-persons projection (empty until commits happen). E21-9 retires Clusters as an operator surface (UXA-09). |
| What is "Retention"? | Recognition-service data-retention policy status; card is jargon + fails closed into a useless message; rename/collapse + RES-03 follow-up (UXA-11). |

---

## 4. Consolidation matrix

| Finding | Existing owner | Action for /scope |
| --- | --- | --- |
| UXA-01 429/backoff | — | **NEW task** (frontend fetch seam + poller cooldown + suggestion batching) |
| UXA-02 heartbeat | E21-1/7/13 (shipped surfaces) | **NEW task** (server heartbeat + honest idle state) |
| UXA-03 bulk accept | E21-5 (planned) | amend E21-5 acceptance criteria |
| UXA-04 table persistence | E21-10 (planned) | amend E21-10 param inventory |
| UXA-05 CTA placement | E21-5 (planned) | already owned; verify criteria |
| UXA-06 drawer copy/zero state | E21-3 (shipped) | fold into copy-pass task |
| UXA-07 pin toggle | — | **NEW task** (remove/relocate) — can batch with UXA-08 quick win |
| UXA-08 typeahead filter | E21-9/E15-17 partial | **NEW quick-win** (filter-before-slice) + criteria in E21-9 |
| UXA-09 person-first roster | E21-9 + E15-13/17 | amend E21-9 (label ⇒ projection write-through) |
| UXA-10 dashboard counts | E15-15/16 | amend with invalidation + projection dependency |
| UXA-11 retention card | RES-03 deferred | **NEW task** (RES-03 pickup + rename/collapse) |
| UXA-12 sync copy | E21-1/13 (shipped) | fold into copy-pass task |
| UXA-13 attachment overlays | — | **NEW task** (feature, medium) |
| UXA-14 alt/caption columns | E20-2/5 | amend E20-5 |
| UXA-15 a11y | E21 cross-cutting gate | acceptance criteria on every new task |
| UXA-16 copy pass | — | **NEW task** (single copy pass, lexicon-governed) |

**Proposed new-task groupings for /scope:** (1) UXP-net: 429/backoff + heartbeat + honest status (UXA-01/02); (2) UXP-roster-quick: pin toggle + typeahead filter (UXA-07/08); (3) UXP-copy: copy/disclosure pass (UXA-06/11/12/16); (4) UXP-overlay: attachment-edit face overlays (UXA-13); plus amendments to E21-5/9/10, E15-15/16, E20-5.

---

## 5. Verification pointers

- Grok lane mechanical inventory (polling table, copy inventory, heuristic sweep UXG-*): `docs/reviews/uxp-1/grok-ux-audit-findings.md` (lane `uxp-1-grok-audit`).
- Live planning-review findings UXPR-01..15: workbay-handoff MCP, review run `planrev-e21-uxui-20260712-01`.
- Prior assessments this extends: `workbench-ui-refactor-assessment-2026-07-04.md`, `roster-dashboard-workbench-ux-assessment-2026-07-04.md`.
- Lane-only artifacts to drop before merge: root `pyproject.toml` shim (commit `627a5399`).
