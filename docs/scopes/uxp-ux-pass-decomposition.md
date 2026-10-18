# UXP Scope — UX/UI Pass Decomposition (2026-07-15)

**Source assessment:** `docs/assessments/current/ux-ui-pass-assessment-2026-07-15.md` (UXA-01..16)
**Mechanical inventory:** `docs/reviews/uxp-1/grok-ux-audit-findings.md` (UXG-01..16)
**Intake decisions (recorded in handoff, `claude_uxp1_scope_intake_v1`):** UXP-net ships first · amend existing epics rather than duplicate · overlay = full spec · roster dedupe lands in E21-9.

Priority order: **UXP-2 → UXP-3 → UXP-4 → UXP-5**, amendments applied opportunistically alongside. Full task plans are authored on-branch at `make task-start TASK=<id>`; each must cite current engineering-heuristics IDs and pass `/planning-review` before implementation.

---

## UXP-2 · Network discipline: 429 backoff + honest service status (UXA-01, UXA-02)

**Objective:** stop the 429 storm at one seam and make the offline banner reflect measured service health.

**Scope:**
- Typed `HTTPError {status, retryAfterSeconds}` in `js/admin/utils/http.ts` `fetchApi`.
- QueryClient policy (`js/admin/App.tsx`): honor `Retry-After`; never retry 4xx except 429; shared 429 cooldown that pauses hot pollers (job status 1.5s, media identities 3s, clusters 30s, sync health 15s).
- Batch the per-card `InlineSuggestionPrompt` `top_k=1` fan-out into one list call.
- Authenticated lightweight heartbeat feeding the sync-health breaker (server-side cached ping on `sync/health` or WP-cron writing the circuit transient), so `breaker.state` is meaningful when idle.
- Banner states: offline (measured) / degraded (breaker) / idle-unknown — copy per UXP-4 vocabulary.

**Success:** with the recognition service rate-limiting, console shows zero repeated-429 loops (pollers cool down and resume); stopping the OCI service flips the banner offline within one heartbeat interval *without any job running*; restart flips it back.
**Non-functional:** heartbeat ≤1 req/60s per site; degrade = fail-fast to cached state, never block admin render.
**Not doing:** server-side rate-limit redesign (E20-7/E20-11), SSE migration of job polling, outbox/dispatcher retry changes.

## UXP-3 · Roster quick wins: pin toggle + naming typeahead (UXA-07, UXA-08)

**Objective:** kill the avatar-overlapping pin button and make "Name this person" reliably surface known names.

**Scope:**
- Remove pin control from `ClusterPreview.tsx` compact card; if product wants representative-pinning, relocate to cluster detail/split view as a styled icon button (it currently has zero CSS).
- Typeahead: one suggestion source = roster persons ∪ labeled clusters; filter before slicing; duplicate-label check becomes blocking-with-warning (no silent fallback) in `ClusterLabelingPanel.tsx`.

**Success:** no control overlaps a face thumbnail anywhere; typing a previously used name always surfaces it (person or labeled cluster) before creating a new entity.
**Not doing:** person merge/write-through (E21-9 amendment), roster IA changes.

## UXP-4 · Copy & disclosure pass (UXA-06, UXA-11, UXA-12, UXA-16)

**Objective:** one lexicon-governed pass over operator-facing strings and disclosure.

**Scope (string inventory: grok findings §C):**
- Sync strip/banner: one sentence per state with consequence + action; "Delta sync", "Queued", "Machine sync", "Sync backlog" become internal-only.
- "Retention posture" → operator language; unavailable state gets remediation copy or the card collapses (per UXP-2 honest status); endpoint-missing no longer renders a dead card.
- Advanced drawer: "What is Clustering?" → on-demand help popover; fix "Latest job — No job yet / Status — Pending" zero state.
- Vocabulary map (Clusters/identities/entries → people-first terms) applied consistently across roster/dashboard/workbench; keep `syncVocabulary.ts` as the single copy source (UXG-15 lockstep risk).

**Success:** every status string names consequence + next action; no data-science or ops jargon on primary surfaces; copy sourced from one module per surface.
**Not doing:** i18n extraction, visual redesign, new components.

## UXP-5 · Attachment-edit face overlays (UXA-13, full spec)

**Objective:** on the attachment edit screen (`post.php`), curated faces render as always-on named overlays; uncurated faces show bbox on hover plus a list in the right pane below image metadata.

**Scope:**
- New PHP surface: `attachment_fields_to_edit` (+ small enqueue) — nothing exists today.
- Reuse `FaceThumbnail` bbox math over the full-size image; data from `class-media-identities-controller.php`.
- Right-pane list: uncurated faces with "Name this person" deep link into the workbench flow (uses E21-10 link contract if landed).
- A11y: overlays are focusable with accessible names; hover-bbox has keyboard equivalent.

**Success:** open an attachment with curated + uncurated faces → names visible in place, uncurated listed and reachable by keyboard; zero layout breakage on core media modal.
**Not doing:** editing/curation inside post.php beyond deep links; media list-table columns (E20-5 amendment); front-end/theme rendering.

---

## Amendments to existing plans (policy: amend, don't duplicate)

| Target plan | Amendment (source finding) |
| --- | --- |
| **E21-5** unified review queue | Bulk accept: replace percent slider with preset bands + consequence copy + preview count (UXA-03). CTA hierarchy: "Analyze selected media" sticky/top placement and visible in collapsed summary bar (UXA-05/UXG-03). |
| **E21-9** person-first roster | Label-curation ⇒ person-projection write-through; server-side same-label grouping so duplicate person rows cannot render; Entries never empty after naming (UXA-09, dedupe decision). |
| **E21-10** link/URL-state contract | Media-table expand state as URL param; auto-collapse only on findings rising edge, never on remount (UXA-04, UXA-12/UXG-12). |
| **E15-15/16** dashboard triage | Stats SQL counts labeled-but-uncommitted identities (or reads projection); cluster mutations invalidate `dashboard.stats`; staleness ≤ one mutation cycle (UXA-10). |
| **E20-5** review/history workspace | Media table alt-text + caption columns with missing-state chips (UXA-14). |
| **RES-03 follow-up** (E21-13 deferral) | Retention remote ops breaker-gated; pairs with UXP-4 retention copy (UXA-11). |

## Assumptions & risks
- Recognition-service endpoints (suggestions list batching, health) accept additive changes; no schema breaks (greenfield policy applies).
- E21-9/E21-10 are planned-not-started; amendments land in their plans at task-start, tracked via this scope note + handoff decisions (not pasted findings — Review Findings Placement rule).
- Lane-only artifacts on `feature/uxp-1` to drop before merge: root `pyproject.toml` shim (`627a5399`).

## Not-doing (global)
Server-side rate-limiter redesign · SSE/websocket job streaming · roster IA beyond E21-9 · i18n · WP media list-table columns beyond E20-5 · retention feature work beyond RES-03 gating + copy.
