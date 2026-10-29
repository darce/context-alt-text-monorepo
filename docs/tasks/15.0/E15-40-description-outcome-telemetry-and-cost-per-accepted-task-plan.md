# Task Plan

> **Metadata**
>
> - **Date**: 2026-10-28 20:49 EDT
> - **Author**: Claude Opus 5.5 (`claude-opus-5-5`)
> - **Owning Epic**: `docs/epics/v0.4.0/public-demo-launch-readiness-epic.md`
> - **Epic Short ID**: E15
> - **Task Plan Status**: `proposed`
> - **Target Branch**: `feature/e15-40`
> - **Review Coverage Target**: 2
> - **Scope Brief**: `docs/scopes/descpick-gtm-beta-readiness-scope.md`
> - **Blocked by**: DESCAUTH-1 S3 and S7 (Slices 1, 1b, 2, 3 and 4); DESCAUTH-1 S11 for lane `e15-40-p1b`. Slice 0 is not blocked.
> - **Anchors verified at**: `43366e5d25` (2026-10-28); unchanged at main `8eece0358f`.

---

## E15-40. Description outcome telemetry and cost per accepted

Paths are repo-relative. The PHP and JS surfaces in Slices 1–3 (including 1b) sit beside code that DESCAUTH-1 S7, S8 and S11 create, so those slices name symbols and take their directory from DESCAUTH-1; they enter the Decomposition JSON once it merges.

## Objective

Learn whether beta drafts are accepted and what an accepted description costs [AIPX-03, COST-04], without a second store, free text or retraining. Slice 0 amends ADR-017 and the DESCAUTH-1 plan now [AGT-13]. After DESCAUTH-1 lands, later slices do five things. They record each draft's first presentation to a user, classify each presented draft into one of six outcome classes, and add one Report a problem action. They also export outcomes per site and compute billed GPU cost per accepted output under a sealed analysis plan.

## Intake

> Include this section when a P0 scope intake pass was conducted before assessment. Omit for bug fixes, tech debt tasks, and spec-derived tasks.

- **Scope one-pager**: `docs/scopes/descpick-gtm-beta-readiness-scope.md`; eval cases GTM-SC-12 … GTM-SC-16 and GTM-SC-21.
- **Key Q&A decisions** (on `MAINT-descpick-gtm-scope-20261028`): #20467 outcomes go in ADR-017's append-only events table, not post meta (post meta keeps only current state, so supersession, edit-after-apply and idempotent reports cannot be derived); #20469 accepted definition and floor; #20470 report control, with the FIR curriculum link not confirmed (#16800 `curriculum_t` is a per-identity threshold, not a training feed); #20472 W1 pricing.
- **Not-Doing**: post meta mirror; free-text reasons; retraining from reports; automatic telemetry upload; quoting an accuracy rate.

## Problem Statement

1. The beta keeps a model that was kept, not proven best (assessment C1). Nothing records whether a presented draft was applied, edited, discarded or replaced, so acceptance cannot be measured [AIPX-03].
2. Cost is an estimate (assessment F7), not cost per accepted output [COST-04].
3. ADR-017 (:48, :84) selects the append-only `wp_acx_description_events` table but has no report event, reason, edit ratio or idempotency key. Adding them in code would override the ADR silently [AGT-13].
4. A user cannot say a draft is wrong, and an identity error belongs to People, not to the description model (D12, `ml-systems/guidelines-human-ai-interaction.md:201`).
5. Nothing records that a person saw a draft. DESCAUTH-1's generation history (S1–S2) records generation and cache-hit time. Its curation events are only `applied`, `corrected`, `discarded` and `reset` (S3). Take two generated drafts where only the first is displayed and neither is acted on: both look the same in that data. So the denominator (displayed drafts) and the window start (first display) are not observable [MEAS-09]. Generation time is not a substitute: a draft can be opened days later, or never.

## Constraints

- Slices 1–4 and 1b dispatch only after DESCAUTH-1 S3 (schema) and S7 (`DescriptionEventRepository::append`) merge. Lane `e15-40-p1b` also waits for DESCAUTH-1 S11. That is the last DESCAUTH-1 lane to edit the draft surfaces, and by then the S2c and S8 `generation_id` sources exist. DESCAUTH-1's Wave Order (:1111) holds its own S1+ until ADR-017 is accepted (ADR-017 :3 is Proposed).
- One system of record: the events table, no post-meta copy [DATA-14] (D1, `ml-systems/manning-information-retrieval.md:161`). The first presentation is one more WordPress curation-side event: WordPress is its only writer (ADR-017 rule 2), and the service never receives or stores it.
- The denominator comes only from `presented` events. Generation, projection, cache-hit and items-read times never stand in for presentation, and a draft with no `presented` event is never counted [MEAS-09, CARD-11].
- Report reasons are concept ids with per-language labels through gettext, text domain `alt-context` (sr-012); no free text (C10, D3).
- Copy must be true today: "Reports inform which model we use next. They do not retrain the model." (D14, `ml-systems/guidelines-human-ai-interaction.md:126`).
- No accuracy rate is quoted outside the team: the sites are a convenience sample, so intervals are descriptive only [AUDIT-08].
- The analysis plan is sealed before the first counted draft [EXP-09].
- Edit ratio is computed at write time and reported in aggregate only (D11).
- Greenfield: the new columns go straight into the DESCAUTH-1 S3 schema; no migration.
- PHP: backed enums for outcome classes and reasons (sr-007); `run_transactional` for multi-statement writes (sr-009); PSR-4 filenames or an explicit `require_once` (rg-016).
- Cost is the provider-billed amount: the OCI Usage API `computedAmount` for the plan's GPU resources. The report applies no rate. The #20472 W1 price describes how the provider bills: USD 2.00 per GPU-hour, per-second billing, a 60-second minimum. It is not a report input, and the Usage API export has no GPU sessions to apply a minimum to. Cost per accepted is an internal cost measurement, not a customer price or billable unit (ADR-014).

## Workflow Principles

- Decide the schema in the ADR before any code writes it.
- Count every presented draft, including drafts nobody acted on (D2, `epistemics/trustworthy-controlled-experiments.md:114`), and no draft that was never shown.
- Fix the definitions, window and thresholds before looking at data; report the primary rate with the strict rate and a sensitivity sweep beside it (D5, D6).
- Send identity errors to the component that can fix them (D12).

## Terminology

| Term | Meaning |
|---|---|
| Presented draft | One `generation_id` that has a `presented` event: its text was shown in a draft review surface to a user who can edit the attachment (Slice 1b). This is the unit of analysis. A generation without that event is not a presented draft, wherever else it appears: generation history, a projection row, an unselected version, a CLI write or the public demo. |
| Presentation time (`presented_at`) | `occurred_at` of the draft's only `presented` event. This is the server's UTC time when the first presentation write was accepted. It is never the generation, projection, cache-hit or items-read time. |
| Window W | Up to 14 days after `presented_at`; later events do not count. An event on the draft recorded before `presented_at` still counts, because the presentation write can land after the Apply that followed the display. |
| Edit ratio | Levenshtein distance over `mb_str_split` code points between the presented draft and the written text, divided by the longer length (0 when both are empty), stored as `decimal(5,4)`. |
| Lenient acceptance | (`applied_unchanged` + `applied_light_edit`) ÷ all presented drafts. Primary. |
| Strict acceptance | `applied_unchanged` ÷ all presented drafts. Reported alongside. |
| n_eff | n ÷ deff, with deff = 1 + (m̄ − 1) × ICC by site (m̄ = mean drafts per site; ICC from one-way ANOVA, floored at 0). |
| Cohort period | The sealed `[cohort_start, cohort_end)`, both at 00:00:00Z. Drafts count when their `presented_at` falls in it, and billed cost counts when its Usage API bucket does. |
| Cost per accepted | Billed GPU cost (Usage API `computedAmount` for the plan's GPU resources over the cohort period) ÷ lenient accepted drafts first presented in that period; strict alongside. |

## Current State Analysis

| Site | Today |
|---|---|
| `docs/adrs/ADR-017-description-authority-wordpress-curation-service-generation.md` | Proposed (:3); selects `wp_acx_description_events` (:48, :84); event and retention rules follow (:86–:163) |
| `docs/tasks/v0.5.0/DESCAUTH-1-description-authority-history-and-reset-task-plan.md` | S1–S2 generation history records generation and cache-hit time only. S2b puts `generation_id` into run-item `provenance`, and S2c adds `VisualFactsResponse.generation_id`. S3 schema (:359): the event types are `applied`, `corrected`, `discarded`, `reset`, with no presentation event. S7 `DescriptionEventRepository::append` (:545); S8 (:564) whitelists `generation_id` in saved provenance; S11 Regenerate UI; Wave Order (:1111) |
| Draft surfaces | `js/admin/pages/workbench/QueueDraftCell.tsx` renders only the selected "Description version" of a Review Queue row (`MediaSelectionTableBody.tsx`), and many rows mount cells. `MediaAltSuggest.tsx` shows the Generate/Regenerate draft. `DescribePanel.tsx` shows a draft with no apply action. None records that a draft was shown. |
| `scripts/gpu_cost_report.py` | `DEFAULT_HOURLY_RATE = 2.0`, `DEFAULT_TOLERANCE_PCT = 25.0`, `report_costs(usage_paths, smoke_path, *, hourly_rate, tolerance_pct)`; `CostReportError` maps to exit 2. Usage API items supply `computedAmount`, bucket `timeFrom`/`timeTo` and `resourceId` (`_usage_items`, `_usage_window`, `_usage_resource_id`). Running time per GPU session comes only from the separate required `--smoke-report` transitions. |
| First-presentation record, outcome classifier, report action, outcome export, cost per accepted | None exist |

## Target Outcome

```text
Outcome of one presented draft G (first `presented` event at P; W ends at P + 14 days)

  no `presented` event for G  -> not a row; never counted

  last apply or discard event on G within W
    apply    edit ratio of the last apply or post-apply edit within W
               = 0            -> applied_unchanged
               <= 0.20        -> applied_light_edit
               >  0.20        -> applied_heavy_edit
    discard                   -> discarded
  neither
    another generation for the same attachment first presented
    after P (by `occurred_at`, then event `id`) and within W
                              -> superseded_by_regeneration
    otherwise                 -> no_outcome

A reported event is a flag on the draft, never a class.
A regenerated draft that was never presented supersedes nothing.
```

Readout, from the sealed plan:

- Lenient acceptance ≥ 50% on ≥ 200 presented drafts from ≥ 5 sites → meets floor; below 50% → below floor. n_eff < 96 → inconclusive, whatever the rate.
- 95% Wilson interval computed with n_eff, labelled "descriptive; convenience sample".
- Sensitivity: lenient acceptance at light-edit cuts 0.10, 0.20 and 0.30.
- Blind audit of 50 applied drafts beside the rate [EVAL-22].
- Cost per accepted (lenient and strict) and generation latency p50/p95/p99 with n [PERF-01].
- `curated_without_presentation` beside the rate. This counts drafts that were curated but have no `presented` event: lost presentation writes, CLI writes, and bulk applies of drafts nobody displayed. They stay out of the denominator; the count shows how much the instrument missed [CARD-11].

## Context Loading

> List the minimum authoritative context an agent should load before implementation.
> Prefer small, role-specific surfaces over broad repo ingestion.

- **Rules**: `docs/workbay/rules/backend-php-guidelines.md`, `docs/workbay/rules/testing-php.md`, `docs/workbay/rules/frontend-guidelines.md`, `docs/workbay/rules/testing-typescript.md`, `docs/workbay/rules/backend-python-guidelines.md`, `docs/workbay/rules/testing-python.md`; `docs/workbay/constitution.md#short-rules` (sr-007, sr-009, sr-012; rg-004, rg-016).
- **Contracts**: ADR-017 and its Slice 0 amendment; DESCAUTH-1 S3 and S7 as merged; the `generation_id` sources in DESCAUTH-1 S2b, S2c and S8; the draft surfaces as DESCAUTH-1 S6 and S11 leave them; ADR-014 (GPU cost is an internal measurement).
- **Handoff/MCP state**: the `E15-40` row; decisions #20467, #20469, #20470, #20472 and the sealed-plan decision.
- **External docs via `ctx7` only if**: a WordPress REST or WP-CLI API detail is unclear from the existing plugin code.

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
|---|---|---|---|---|---|
| `wp_acx_description_events` | ADR-017; DESCAUTH-1 S3 | Append-only events; no presentation, report, ratio or key | `presented` and `reported` kinds; `report_reason`, `edit_ratio`, `request_key` with `UNIQUE (event_type, request_key)` | No: table not built yet | Slice 0 accepted; DESCAUTH-1 S3 schema test |
| `POST /acx/v1/descriptions/{generation_id}/presented` | Slice 1b | None | New; one `presented` row per `generation_id`; repeats insert nothing | No | `DescriptionPresentationControllerTest` |
| `POST /acx/v1/descriptions/{generation_id}/report` | Slice 3 | None | New; idempotent by `request_key` | No | `DescriptionReportControllerTest` |
| Outcome export `acx-description-outcomes/v1` | Slice 2 | None | New WP-CLI JSON export; cohort = `presented` events | No | `DescriptionOutcomeExportTest` |
| `scripts/cost_per_accepted_report.py` | Slice 4 | None | New CLI over billed Usage API amounts; exit 2 on bad input | No | `scripts/test_cost_per_accepted_report.py` |

Non-functional notes:

- **Latency**: a report is one insert, and the review UI never waits on it beyond the request. A presentation write is at most one insert. It is fire-and-forget and never delays or disables Apply, Edit or Dismiss. The cost report runs offline. Generation latency is reported as p50/p95/p99 with n, never a mean.
- **Degraded behaviour**: a failed event write never loses the applied outcome (DESCAUTH-1 S7 durability rule). A failed report shows an error with Retry, reusing the same `request_key`. A failed presentation write retries up to 3 times and then gives up silently. The draft then stays out of the denominator and shows up in `curated_without_presentation` if it is curated.
- **Load and spikes**: one row per user action and one per presented draft, no fan-out. The client sends at most one presentation request per `generation_id` per page load, and the server dedupes the rest. Exports are operator-run per site.
- **Retention**: ADR-017's 180 days applies to every event, `presented` included. Report and presentation rows hold no text, and presentation rows hold no user id. An export refuses a `--since` more than 180 days before it runs, because those `presented` rows may already be gone.

## Proposed Solution

1. **Slice 0 (now)**: amend ADR-017 and the DESCAUTH-1 plan with the two event kinds, the columns and the unique key.
2. **Slice 1**: `DescriptionOutcomeClassifier`, a pure function from a draft's events to one class.
3. **Slice 1b**: record each draft's first presentation: one REST route, one hook on the two draft surfaces.
4. **Slice 2**: a site-local WP-CLI export of closed-window presented drafts, with no text and no user ids.
5. **Slice 3**: Report a problem: one REST route, one enum, one UI action.
6. **Slice 4**: `scripts/cost_per_accepted_report.py` over billed Usage API amounts, site exports and the sealed plan.
7. **Operator S5**: seal the plan, run the blind audit, publish the internal readout.

## Files and Surfaces to Change

> Name the exact symbol(s) per file — the implementer should not have to grep for the edit site. Mark new symbols `(new)`. Prefer symbol names over line numbers.

| Surface | File | Symbol / Function | Change |
|---|---|---|---|
| ADR | `docs/adrs/ADR-017-description-authority-wordpress-curation-service-generation.md` | Amendment 1 (new section) | Slice 0 |
| DESCAUTH-1 plan | `docs/tasks/v0.5.0/DESCAUTH-1-description-authority-history-and-reset-task-plan.md` | S3 events schema; S7 `DescriptionEventRepository::append` | Slice 0 |
| Outcome | beside `DescriptionEventRepository` (new in DESCAUTH-1 S7) | `DescriptionOutcome` (new), `DescriptionOutcomeClassifier::classify` (new) | Slice 1 |
| Presentation route | beside `DescriptionEventRepository` | `DescriptionPresentationController` (new) | Slice 1b |
| Presentation client | `js/admin/api/describeApi.ts`; `js/admin/hooks/` | `recordDescriptionPresentation` (new), `useRecordDraftPresentation` (new) | Slice 1b |
| Presentation call sites | `js/admin/hooks/useQueueDrafts.ts`; `js/admin/pages/workbench/QueueDraftCell.tsx`; `js/admin/pages/workbench/MediaAltSuggest.tsx` (as DESCAUTH-1 S6 and S11 leave them) | `QueueDraft.generationId` (new); hook calls | Slice 1b |
| Export | plugin WP-CLI registration | `wp acx description-outcomes export` (new) | Slice 2 |
| Report | beside `DescriptionEventRepository` | `DescriptionReportReason` (new), `DescriptionReportController` (new) | Slice 3 |
| Report UI | draft surface from DESCAUTH-1 S8 | Report a problem action (new) | Slice 3 |
| Cost report | `scripts/cost_per_accepted_report.py` | `main`, `report_cost_per_accepted` (new) | Slice 4 |
| Cost test | `scripts/test_cost_per_accepted_report.py` | tests listed in Slice 4 (new) | Slice 4 |
| Make targets | `Makefile` | `lint-scripts`, `test-scripts` | Slice 4 |

## Related Files

| File | Note |
|---|---|
| `scripts/gpu_cost_report.py` | Reused: usage parsing (`_usage_items`, `_usage_window`, `_usage_resource_id`) and `CostReportError`. Not reused: the hourly rate and the smoke-session estimate. |
| `docs/adrs/ADR-014-payment-processor-merchant-of-record-selection.md` | GPU cost is an internal cost measurement, not a customer unit; nothing here touches payments |
| `docs/scopes/descpick-gtm-beta-readiness-evals.json` | GTM-SC-12 … GTM-SC-16 |
| `docs/runbooks/evidence/` | Sealed analysis plan lands here (operator S5) |

## Verification Strategy

> Define the evidence bundle before implementation.
> Include deterministic tests first; add runtime-parity or manual verification when they are genuinely required.

- **Deterministic tests**: PHPUnit for classifier, presentation route, export and report controller; vitest for the presentation hook and the report action; pytest for the cost report.
- **Runtime-parity / environment checks**: one export from the LocalWP demo site run through the cost report before the first beta site.
- **Contract/fixture verification**: the export schema string and keys are asserted exactly; the cost report rejects any other schema.
- **Failure-mode / SLA prompts**: State p99 latency target (not average), degraded behavior when dependency X is down/slow, and spike/peak load assumptions — see planning-review-guide § Non-Functional & Failure-Mode Realism. Answered in Contract and Boundary Impact.
- **Manual verification**: operator S5 only.

```bash
python3 scripts/hooks/guard-task-plan-findings.py --scan-repo
```

```bash
env OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 timeout 300s composer --working-dir=apps/prototype-wp-alt-context test -- --filter 'DescriptionOutcomeClassifierTest|DescriptionPresentationControllerTest|DescriptionOutcomeExportTest|DescriptionReportControllerTest' tests/Unit
```

```bash
env OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 timeout 300s apps/prototype-wp-alt-context/node_modules/.bin/vitest run --root apps/prototype-wp-alt-context --maxWorkers=1 --no-file-parallelism js/admin/hooks/__tests__/useRecordDraftPresentation.test.tsx
```

```bash
LC_ALL=C uv run --no-project --with pytest python -m pytest scripts/test_cost_per_accepted_report.py -q -p no:cacheprovider
```

```bash
npm --prefix apps/prototype-wp-alt-context run typecheck
```

## Slice Delivery

> Each slice must name the **files and functions** it touches (`path:symbol`) and the **proof** that closes it — enough for a junior agent to implement the slice from this block alone.

### Slice 0: ADR-017 and DESCAUTH-1 amendment

Lane: `e15-40-s0` (docs only; not blocked).

**Goal**: the schema E15-40 needs is decided in the ADR, not in code [AGT-13].

Files: `docs/adrs/ADR-017-description-authority-wordpress-curation-service-generation.md`, `docs/tasks/v0.5.0/DESCAUTH-1-description-authority-history-and-reset-task-plan.md`.

Changes:

1. ADR-017: append `## Amendment 1 (E15-40, 2026-10-28)`:
   - event kind `presented`: one row per `generation_id`, written when the draft's text is first shown in a draft review surface (Slice 1b). `occurred_at` is the server's UTC time of the first accepted write, and `request_key` is the row's `generation_id`. It holds no text, and `actor_user_id` is 0. Rule 2 adds this kind to the WordPress-only curation event log, and the service never receives it;
   - event kind `reported`: one row per report, no text;
   - `report_reason varchar(32) NULL`: one `DescriptionReportReason` concept id;
   - `edit_ratio decimal(5,4) NULL`: written on apply and post-apply edit events, defined as in this plan's Terminology;
   - `request_key char(36) NULL` with `UNIQUE KEY uq_event_request (event_type, request_key)`. For `reported` it is a client-generated UUID. For `presented` it is the `generation_id`, set by the server and never by the client. A repeated `(event_type, request_key)` returns the existing row and inserts nothing;
   - retention unchanged: 180 days for every event kind, `presented` included;
   - why: outcomes need history that post meta cannot hold (#20467; D1). The denominator and the window start need a presentation fact that generation and curation history do not record [MEAS-09].
   Status stays Proposed; the operator accepts ADR-017 with the amendment (GTM-SC-12).
2. DESCAUTH-1 plan: S3 adds `presented` and `reported` to `DescriptionEventType`, and adds the three columns and the composite unique index to the events table definition. S7 `DescriptionEventRepository::append` accepts `report_reason`, `edit_ratio` and `request_key`, and computes `edit_ratio` at write time. On a duplicate `(event_type, request_key)` it returns the existing row. S7's proof gains "a duplicate key inserts nothing; a second `presented` row for one generation inserts nothing". The Wave Order stays as it is.

Proof: `python3 scripts/hooks/guard-task-plan-findings.py --scan-repo` passes; `git diff --stat` shows only the two files.

### Slice 1: Outcome classifier

Lanes: `e15-40-c1r` (RED) then `e15-40-c1`. Blocked on DESCAUTH-1 S7.

**Goal**: one deterministic class per presented draft.

Functions: `DescriptionOutcome` (new backed enum: `applied_unchanged`, `applied_light_edit`, `applied_heavy_edit`, `discarded`, `superseded_by_regeneration`, `no_outcome`); `DescriptionOutcomeClassifier::classify(string $generationId, DateTimeImmutable $presentedAt, array $mediaEvents, float $lightEditMax = 0.20): DescriptionOutcome` (new; pure, no database).

- `$presentedAt` is the `occurred_at` of the draft's `presented` event. The caller (Slice 2) only classifies generations that have one.
- `$mediaEvents` holds every event row for the draft's attachment, ordered by `occurred_at` and then `id`. That covers the draft's own curation and `reported` events plus the `presented` rows of other generations, which decide supersession.
- Rules: the tree in Target Outcome. Apply, discard and post-apply edit are the DESCAUTH-1 S7 event kinds. "First presented after P" compares `(occurred_at, id)`, because `occurred_at` has one-second resolution.

RED tests (`DescriptionOutcomeClassifierTest`):

- `testClassifiesEveryOutcomeClass`: data provider with one case per class.
- Edit ratio 0.2000 → light; 0.2001 → heavy.
- An event at presentation + 14 days + 1 second is ignored.
- An `applied` event one second before `$presentedAt` counts, because the presentation write landed after the Apply.
- Apply, then discard, both within W → `discarded` (the last one wins).
- Apply, then a post-apply edit with ratio 0.35 → `applied_heavy_edit`.
- A `reported` event does not change the class.
- Regeneration ordering, with no apply or discard on G1:
  - G2's `presented` row after G1's, within W → G1 `superseded_by_regeneration`;
  - G2 first presented before G1 → G1 `no_outcome`;
  - G2 first presented at P + 14 days + 1 second → G1 `no_outcome`;
  - G2 generated but with no `presented` row → G1 `no_outcome`;
  - G1 and G2 `presented` in the same second → the higher event `id` is the later one.

Proof: RED fails because the classes are missing; after `e15-40-c1` all pass. TEST-15: change the light-edit comparison from `<=` to `<` → the 0.2000 case goes red; revert.

### Slice 1b: First-presentation record

Lanes: `e15-40-p1r` (RED: PHP and JS tests) then `e15-40-p1a` (PHP) then `e15-40-p1b` (JS). `e15-40-p1r` and `e15-40-p1a` are blocked on DESCAUTH-1 S7. `e15-40-p1b` is also blocked on DESCAUTH-1 S11.

**Goal**: each draft's first presentation to a user becomes one durable, idempotent `presented` event. That event alone is the unit of analysis and the window origin [MEAS-09, GRPH-33].

Produced by the client and persisted by WordPress, the only writer (ADR-017 rule 2). Slice 2 consumes it. The description service is never called.

PHP (`e15-40-p1a`):

- `DescriptionPresentationController` (new): `POST /acx/v1/descriptions/{generation_id}/presented`, body `{ "media_id": int }`.
  - Permission: the attachment exists and `current_user_can( 'edit_post', $media_id )`, else 403.
  - `generation_id` must pass `wp_is_uuid` (else 400). It is passed through verbatim and never synthesized (ADR-017 guardrail).
  - Write: inside `run_transactional`, one `presented` event through `DescriptionEventRepository::append`. It sets `generation_id`, `media_id`, `request_key` = `generation_id`, `occurred_at` = `current_time( 'mysql', true )` (UTC) and `actor_user_id` = 0. It stores no text and no hashes.
  - Repeat: an existing `presented` row for that `generation_id` returns 200 with that row, `created: false` and its original `presented_at`. Nothing is inserted, so repeated display never moves `presented_at`. A concurrent first write that loses on `uq_event_request` is treated as a repeat. If the existing row has a different `media_id`, return 409 `acx_presentation_media_mismatch` and insert nothing.
  - Response: `event_id`, `generation_id`, `presented_at`, `created` (bool).

JS (`e15-40-p1b`):

- `recordDescriptionPresentation(generationId, mediaId)` (new) in `describeApi.ts`.
- `useRecordDraftPresentation(elementRef, { generationId, mediaId })` (new hook).
  - It records when the element holding the draft text is at least half in the viewport (`IntersectionObserver`, threshold 0.5) and `document.visibilityState` is `visible`. Mounting alone is not presentation, because Review Queue rows mount many cells.
  - It sends at most one request per `generationId` per page load (a module-level set).
  - A failed request retries up to 3 times with backoff, then logs and stops. It never shows UI or blocks Apply, Edit or Dismiss.
  - A null `generationId` records nothing.
- Call sites:
  - `QueueDraftCell`, for the selected "Description version" only. Versions that are only listed in the selector are never recorded. `QueueDraft` gains `generationId`, read from the run item's `provenance.generation_id` (DESCAUTH-1 S2b) or from saved provenance (S8).
  - `MediaAltSuggest`, for each draft that Generate or Regenerate returns, using `VisualFactsResponse.generation_id` (DESCAUTH-1 S2c). A Regenerate draft records its own generation only once it is displayed.
- `DescribePanel` (no apply action), the public demo and the CLI record nothing.

RED tests:

- `DescriptionPresentationControllerTest::testFirstPresentationIsRecordedOnce`: two calls for one generation give one row, and the second returns `created: false` with the first call's `presented_at`.
- No capability → 403; a non-UUID `generation_id` → 400; the same generation with another `media_id` → 409 and no row. The stored row has no text and `actor_user_id` 0.
- Vitest (`js/admin/hooks/__tests__/useRecordDraftPresentation.test.tsx`), with a stubbed `IntersectionObserver`:
  - one request once the draft is half visible;
  - none on mount while off-screen or while the document is hidden;
  - none again on re-render, remount or a second visibility;
  - none for a null `generationId` or an unselected version;
  - a Regenerate draft records its own new `generationId` after display;
  - a failed request leaves Apply enabled.

Proof: RED fails; after both implementation lanes everything passes, including the typecheck. TEST-15: skip the existing-row lookup → `testFirstPresentationIsRecordedOnce` goes red; revert.

### Slice 2: Outcome export

Lanes: `e15-40-e2r` (RED) then `e15-40-e2`. After Slice 1. The tests seed `presented` rows through `DescriptionEventRepository::append`, so they do not wait for Slice 1b. Live counting does (Operator S5).

**Goal**: one site-local JSON file per site and window; nothing leaves the site automatically.

Command (new): `wp acx description-outcomes export --since=<YYYY-MM-DD> --until=<YYYY-MM-DD> --out=<path>`. Register it beside the plugin's existing WP-CLI commands; if there are none, register it in the plugin bootstrap under `defined( 'WP_CLI' ) && WP_CLI`.

Input: `wp_acx_description_events` only, plus the projection item that carries the same `generation_id`, when one exists, for `profile`, `model_revision` and `latency_ms`.

- Cohort: one row per `presented` event with `presented_at` in [`since`, `until` − 14 days]. `presented_at` is that event's `occurred_at`; no other timestamp is used.
- A generation with no `presented` event is never a row.
- Each row is classified with `DescriptionOutcomeClassifier::classify` over that attachment's events.
- `--since` earlier than 180 days before the export runs is an error (`WP_CLI::error`), because ADR-017 retention may already have deleted those `presented` rows.

Format `acx-description-outcomes/v1`:

- header: `schema`, `site_key` (the site's tenant id), `since`, `until`, `window_days` (14), `light_edit_max` (0.20), `exported_at`, `curated_without_presentation`. That last field counts generations with a curation event in [`since`, `until`] and no `presented` event; they are never rows;
- `rows[]`: `generation_id`, `profile`, `model_revision`, `presented_at`, `outcome`, `edit_ratio` (null unless applied), `reported`, `report_reason`, `latency_ms`. `profile`, `model_revision` and `latency_ms` come from the projection item's `provenance` and `processing_ms`, and are null when WordPress holds no projection item for that generation;
- no text, no user ids, no attachment ids; only drafts whose window has closed (`presented_at` + 14 days ≤ `until`); timestamps ISO 8601 UTC; rows ordered by `presented_at`, then `generation_id`.

RED tests (`DescriptionOutcomeExportTest`): exact schema string and keys; open-window drafts excluded; no text field anywhere; ordering; plus:

- `testCohortIsFirstPresentation`: two generations for one attachment, both with projection rows, a `presented` row for the first only, and no curation events. Result: exactly one row, for the first, with outcome `no_outcome`. The undisplayed second generation is absent.
- Repeated display: two presentation writes for one generation give one row, whose `presented_at` is the first write's time.
- Delayed first display: generation and projection on day 0, `presented` on day 5.
  - `presented_at` is day 5;
  - an `applied` on day 18 classifies as applied;
  - an `applied` only on day 20 gives `no_outcome`;
  - with `until` on day 15 the draft is excluded as open-window, even though day 0 + 14 ≤ day 15.
- Regeneration ordering, with no actions:
  - G1 presented on day 1 and G2 on day 2: G1 is `superseded_by_regeneration` and G2 is `no_outcome`;
  - G2 generated but never presented: G1 is `no_outcome` and G2 has no row.
- An `applied` generation with no `presented` row adds 1 to `curated_without_presentation` and is not a row.
- `--since` more than 180 days back is refused.

Proof: RED fails; after `e15-40-e2` passes.

### Slice 3: Report a problem

Lanes: `e15-40-r3r` (RED: PHP and JS tests) then `e15-40-r3a` (PHP) then `e15-40-r3b` (JS). Blocked on DESCAUTH-1 S7 and S8. `e15-40-r3b` also waits for `e15-40-p1b`, which edits the same draft components first.

**Goal**: one report action per draft, idempotent, with no free text.

PHP (`e15-40-r3a`):

- `DescriptionReportReason` (new backed enum): `unsupported_detail`, `action_relation`, `count_attribute`, `text_in_image`, `identity`.
- `DescriptionReportController` (new): `POST /acx/v1/descriptions/{generation_id}/report`, following how DESCAUTH-1 exposes `generation_id`.
  - Permission: `current_user_can( 'edit_post', $attachment_id )` for the draft's attachment, else 403.
  - Body: `request_key` is required and must pass `wp_is_uuid( $key, 4 )` (else 400). `reason` is optional and parsed with `DescriptionReportReason::tryFrom`; an unknown value returns 400 `acx_invalid_report_reason`.
  - Write: one `reported` event through `DescriptionEventRepository::append`, inside `run_transactional`. A duplicate `request_key` returns 200 with the existing event and inserts no row.
  - Response: `event_id`, `generation_id`, `reason`, `created` (bool).

JS (`e15-40-r3b`): a "Report a problem" button on each draft.

- It opens a controlled dialog that wires `onOpenChange` (rg-004). The dialog has an optional radio group with the five reasons and a "Send report" button.
- `crypto.randomUUID()` runs once per dialog open; Retry reuses that key.
- On success, show the confirmation copy and switch the button to a disabled "Reported". On failure, show an error with Retry.

Copy, all through gettext with text domain `alt-context`:

| Concept | English source string |
|---|---|
| button | Report a problem |
| `unsupported_detail` | Describes something not in the image |
| `action_relation` | Wrong action or relationship |
| `count_attribute` | Wrong count, color or other detail |
| `text_in_image` | Misreads text in the image |
| `identity` | Wrong person |
| confirmation | Thanks. Reports inform which model we use next. They do not retrain the model. |
| identity helper, linking to People | Fixes recognition for this site. |

RED tests:

- `DescriptionReportControllerTest::testReportIsIdempotentByRequestKey`: the same key twice gives one row, and the second response has `created: false`.
- An unknown reason → 400; no capability → 403; an invalid key → 400.
- Vitest beside the component: Retry reuses the key; `identity` shows the People link; the copy strings are exact.

Proof: RED fails; after both implementation lanes everything passes, including the typecheck.

### Slice 4: Cost per accepted report

Lanes: `e15-40-k4r` (RED) then `e15-40-k4`. After Slice 2.

**Goal**: cost per accepted output computed from the provider-billed amount, refusing inconsistent inputs.

CLI (new): `python3 scripts/cost_per_accepted_report.py --usage-request <usage-request.json> --usage <usage.json>... --outcomes <export.json>... --plan <plan.json> --plan-sha256 <hex> --out <report.json>`.

- Cost basis: billed amounts only. A session-based estimate is not computed (Not Doing).
  - `--usage` files are OCI Usage API exports of the kind `gpu_cost_report` reads (`queryType` `COST`, grouped by `resourceId`).
  - All of them answer the one `--usage-request` body, the request shape in `gpu_cost_report`'s docstring.
  - Parse items with `gpu_cost_report._usage_items`, `_usage_window` and `_usage_resource_id`. Import those and `CostReportError` the same way the existing scripts tests import their script.
- Cost = the sum of `computedAmount` over items whose `resourceId` is in the plan's `gpu_resource_ids`, in the export's currency.
  - No hourly rate, per-second rule or 60-second minimum is applied, and there is no `--hourly-rate` flag. The amount is already billed, and the export has no GPU sessions.
- Cohort and window matching:
  - the usage request's `timeFrom` and `timeTo` equal the plan's `cohort_start` and `cohort_end` (UTC midnights), and every kept item's [`timeFrom`, `timeTo`) lies inside that period. Prorating a bucket that crosses the boundary would turn a billed amount back into an estimate;
  - the denominator is the export rows with `presented_at` in [`cohort_start`, `cohort_end`);
  - every export has `since` ≤ `cohort_start` and `until` ≥ `cohort_end` + 14 days, so each counted draft's window has closed;
  - there is one export per `site_key`.
- The numerator is fully loaded [COST-04].
  - It includes generations never presented, regenerations, idle running time and any other use of those resources in the period. The report subtracts nothing, and the readout lists known other use (for example a DESCPICK-5 S2 window) beside the figure.
  - Edge effect: a draft generated just before `cohort_start` but first presented inside the period counts without its generation cost, and the converse happens at `cohort_end`. The readout states the period length.
- Output:
  - billed cost, labelled "internal cost measurement" (ADR-014);
  - n, sites and n_eff;
  - lenient and strict accepted counts, and cost per accepted for each;
  - the sensitivity table at 0.10, 0.20 and 0.30;
  - verdict: meets floor, below floor or inconclusive;
  - the descriptive 95% Wilson interval on n_eff;
  - latency p50/p95/p99 with n (rows with a non-null `latency_ms`);
  - the summed `curated_without_presentation`;
  - the SHA-256 of every input file.
- Exit 2 through `CostReportError` when:
  - a file is missing;
  - the export schema is not `acx-description-outcomes/v1`;
  - the plan SHA-256 does not match;
  - an export's window or threshold disagrees with the plan, or does not cover the cohort period plus 14 days;
  - the usage request window is not the cohort period, or a kept usage item lies outside it;
  - two exports share a `site_key`;
  - no usage item matches the plan's `gpu_resource_ids`.
- Zero accepted drafts is not an error: `cost_per_accepted_usd` is null with a reason, exit 0.
- Register the script under the `lint-scripts:` and `test-scripts:` targets in `Makefile` (lane `e15-40-k4` owns it).

RED tests (`scripts/test_cost_per_accepted_report.py`):

- `test_exit_2_on_missing_or_inconsistent_inputs`: parametrized over the seven refusals above.
- `test_cost_is_sum_of_billed_amounts_for_plan_resources`: items of 0.40 and 0.25 for the plan's resource and 1.00 for another resource, all inside the period. Cost is 0.65, and `--hourly-rate` is rejected as an unknown argument.
- `test_usage_item_crossing_period_boundary_exits_2`: an item from `cohort_end` − 1 h to `cohort_end` + 1 h → exit 2.
- `test_denominator_counts_only_drafts_first_presented_in_period`: rows with `presented_at` before `cohort_start` or at or after `cohort_end` are not counted.
- `test_inconclusive_when_n_eff_below_96`.
- `test_zero_accepted_reports_null_cost`.
- `test_latency_percentiles_report_n`.

Proof: RED fails; after `e15-40-k4` passes. TEST-15: keep items that merely overlap the period → the boundary test goes red; revert.

### Operator S5: sealed plan, audit, readout

1. Before the first counted draft:
   - Commit `docs/runbooks/evidence/e15-40-analysis-plan.json` with:
     - `window_days`: 14
     - `light_edit_max`: 0.20
     - `sensitivity`: [0.10, 0.20, 0.30]
     - `floor`: rate 0.50, min_drafts 200, min_sites 5, min_n_eff 96
     - `cohort_start` and `cohort_end`: UTC midnights. `cohort_start` is no earlier than the first midnight after lanes `e15-40-p1a` and `e15-40-p1b` are live on every counted site, because drafts shown before then have no `presented` event. `cohort_end` is less than 166 days after `cohort_start`, so every `presented` row is still inside ADR-017's 180-day retention when the export runs at `cohort_end` + 14 days.
     - `gpu_resource_ids`: the OCI resource ids of the GPU instances that generate beta drafts
     - `audit`: n 50, plus a seed
   - Record the file's SHA-256 as a decision on `E15-40` [CARD-06, CARD-05].
   - Nothing changes after the first counted draft [EXP-09].
2. After `cohort_end` + 14 days, and before `cohort_start` + 180 days:
   - write `usage-request.json` for [`cohort_start`, `cohort_end`), with `queryType` `COST` and grouped by `resourceId`, and export its Usage API answer as `gpu_cost_report`'s docstring shows;
   - collect one export per site with `--since` ≤ `cohort_start` and `--until` ≥ `cohort_end` + 14 days;
   - run the report, and record the usage request's and the report's SHA-256 on `E15-40`.
3. Blind-audit 50 applied drafts, drawn by the seeded sample. The reviewer sees the image and text, not the model label or the class (D9). Report agreement beside the rate [EVAL-22].
4. Publish internally, labelled "descriptive; convenience sample" [AUDIT-08] (GTM-SC-16).

## Not Doing

- A post meta mirror of outcomes (DATA-14).
- Free-text report reasons; retraining from reports; a FIR curriculum link (#20470).
- Automatic telemetry upload: beta sites send their export file by hand.
- Counting generation, projection or items-read time as presentation. Presentation records from the public demo, the CLI or the dashboard Describe panel.
- Recording who saw a draft: `presented` rows keep `actor_user_id` 0.
- A session-based GPU cost estimate. The Usage API export has no sessions, and `gpu_cost_report` already compares a smoke session's estimate with the bill.
- Any customer price, billable unit or payment change: cost per accepted stays an internal measurement (ADR-014).
- Quoting an acceptance or accuracy rate outside the team.
- A speed/quality toggle or model change based on early data before the floor's n is reached.

## Decomposition

Only Slice 0 is dispatchable now; Slices 1–4 and 1b join this block once DESCAUTH-1 fixes their directories, followed by a fresh `make lane-manifest-init`.

```json
{
  "version": 1,
  "items": [
    {"id": "s1", "title": "S0: ADR-017 and DESCAUTH-1 amendment", "independent": true, "owns": ["docs/adrs/ADR-017-description-authority-wordpress-curation-service-generation.md", "docs/tasks/v0.5.0/DESCAUTH-1-description-authority-history-and-reset-task-plan.md"], "depends": [], "blast": "none", "anchors": []}
  ]
}
```

## Lane Decomposition (Multi-Agent)

> Include this section only when the task naturally splits into independent lanes.
> Omit for single-lane work that one agent can complete in a bounded session.
> Prefer the machine-checked `## Decomposition` JSON block above when lanes will
> be compiled through `plan_decomposer` → `work_graph_compiler`.

### Lanes

| Lane ID | Owned Paths | Upstream Dependencies | Required Tests |
|---|---|---|---|
| `e15-40-s0` | ADR-017; DESCAUTH-1 plan | None | Task-plan findings scan |
| `e15-40-c1r` | `DescriptionOutcomeClassifierTest.php` | DESCAUTH-1 S7 merged | PHPUnit (red) |
| `e15-40-c1` | `DescriptionOutcome`, `DescriptionOutcomeClassifier` | `e15-40-c1r` | PHPUnit |
| `e15-40-p1r` | `DescriptionPresentationControllerTest.php`; `useRecordDraftPresentation.test.tsx` | DESCAUTH-1 S7 merged | PHPUnit and vitest (red) |
| `e15-40-p1a` | `DescriptionPresentationController` | `e15-40-p1r` | PHPUnit |
| `e15-40-p1b` | `recordDescriptionPresentation`, `useRecordDraftPresentation`, `QueueDraft.generationId`, the `QueueDraftCell` and `MediaAltSuggest` call sites | `e15-40-p1a`; DESCAUTH-1 S11 merged | vitest, typecheck |
| `e15-40-e2r` | `DescriptionOutcomeExportTest.php` | `e15-40-c1` | PHPUnit (red) |
| `e15-40-e2` | export command | `e15-40-e2r` | PHPUnit |
| `e15-40-r3r` | `DescriptionReportControllerTest.php`; report action test | DESCAUTH-1 S7 and S8 merged | PHPUnit and vitest (red) |
| `e15-40-r3a` | `DescriptionReportReason`, `DescriptionReportController` | `e15-40-r3r` | PHPUnit |
| `e15-40-r3b` | report action component | `e15-40-r3a`; `e15-40-p1b` (shared draft components) | vitest, typecheck |
| `e15-40-k4r` | `scripts/test_cost_per_accepted_report.py` | `e15-40-e2` | pytest (red) |
| `e15-40-k4` | `scripts/cost_per_accepted_report.py`, `Makefile` | `e15-40-k4r` | pytest |

### Merge Order

A lane dispatches once every lane it depends on has merged.

1. Now: `e15-40-s0`; then the operator accepts ADR-017.
2. After DESCAUTH-1 S7 (and S8 for the report lanes): `e15-40-c1r`, `e15-40-p1r`, `e15-40-r3r`.
3. `e15-40-c1`, `e15-40-p1a`, `e15-40-r3a`.
4. `e15-40-e2r`; `e15-40-p1b` once DESCAUTH-1 S11 has merged.
5. `e15-40-e2`, then `e15-40-k4r`, then `e15-40-k4`; `e15-40-r3b` after `e15-40-p1b`.
6. Operator S5 seals the plan before the first counted draft. No draft counts before `e15-40-p1a` and `e15-40-p1b` are live on its site.

### Manifest

```bash
make lane-manifest-init TASK=E15-40 LANE_IDS='e15-40-s0' TASK_PLAN=docs/tasks/15.0/E15-40-description-outcome-telemetry-and-cost-per-accepted-task-plan.md
```

### Orchestration Mode

- **Codex subagent (preferred when available)**: Use MCP worker lifecycle tools with the declared lane ownership and verification boundaries. Implementation and RED lanes run on remote codex `gpt-6.1-sol`, high effort, FAST tier; one lane per dispatch; each brief embeds its slice block from this plan.
- **Shell fallback**: Use repo lane helpers or manual worktrees while preserving the same ownership and evidence requirements.

---

## Consolidated Checklist

**Checklist scope rule:** Describe work being delivered, not finding status. Finding status is queried from the handoff DB via `review_findings(review={"operation":"list","status":"open","task_ref":"E15-40"})` or read from `DASHBOARD.txt`.

## Context and Ownership

- [ ] Loaded the minimum authoritative rules, contracts, and handoff state before editing.
- [ ] Confirmed whether external dependency context requires `ctx7`.
- [ ] Recorded boundary ownership and compatibility expectations if any contract is touched.

### Checklist for Slice 0: ADR-017 and DESCAUTH-1 amendment

- [ ] `docs/adrs/ADR-017-description-authority-wordpress-curation-service-generation.md` carries Amendment 1 with the presentation and report events, the three columns and the composite unique key.
- [ ] `docs/tasks/v0.5.0/DESCAUTH-1-description-authority-history-and-reset-task-plan.md` S3 and S7 include the two event types, the columns, write-time edit ratio and duplicate-key behaviour.
- [ ] `python3 scripts/hooks/guard-task-plan-findings.py --scan-repo` passes.
- [ ] Operator accepted ADR-017 with the amendment.

### Checklist for Slice 1: Outcome classifier

- [ ] RED tests cover every class, both edit-ratio boundaries, the window edge, an apply recorded before presentation, last-action-wins, the report flag and regeneration ordering.
- [ ] The classifier is pure and passes; the boundary mutation was shown red and reverted.

### Checklist for Slice 1b: First-presentation record

- [ ] The presentation route writes one `presented` row per generation with server UTC time. Repeats return the first row, and it checks capability, UUID and media match.
- [ ] The hook records once per generation when the selected draft is half visible, never for off-screen, hidden, unselected or null-id drafts, and never blocks Apply.
- [ ] `npm --prefix apps/prototype-wp-alt-context run typecheck` passes.

### Checklist for Slice 2: Outcome export

- [ ] The export writes the v1 schema with no text, user ids or attachment ids, and only closed-window drafts.
- [ ] Its cohort is the `presented` events only: a displayed untouched draft is `no_outcome`, while a never-displayed one, a repeat display and a delayed first display behave as tested.

### Checklist for Slice 3: Report a problem

- [ ] The report route is idempotent by request key, validates reason and key, and checks the attachment capability.
- [ ] The report action reuses its key on retry, shows the exact copy through gettext, and links identity reports to People.
- [ ] `npm --prefix apps/prototype-wp-alt-context run typecheck` passes.

### Checklist for Slice 4: Cost per accepted report

- [ ] `scripts/cost_per_accepted_report.py` refuses missing or inconsistent inputs with exit 2. It sums billed Usage API `computedAmount` for the plan's resources over the cohort period, applies no rate, and counts only drafts first presented in that period.
- [ ] `LC_ALL=C uv run --no-project --with pytest python -m pytest scripts/test_cost_per_accepted_report.py -q -p no:cacheprovider` passes.
- [ ] The script is registered under the lint and test script targets in `Makefile`.

### Checklist for Operator S5

- [ ] `docs/runbooks/evidence/e15-40-analysis-plan.json` was committed and its hash recorded before the first counted draft.
- [ ] Blind audit and internal readout published with the descriptive label.

## Review Readiness

- [ ] No boundary-touching implementation is left without matching contract/doc/fixture evidence.
- [ ] Runtime-parity checks are included where tests can mask real behavior.
- [ ] Handoff decision records the change, verification, and any contract implications.

## Stretch Goals

- A per-profile split of acceptance once a second served profile exists.

## Success Criteria

| Eval case | Proof |
|---|---|
| GTM-SC-12 | ADR-017 Amendment 1 accepted by the operator |
| GTM-SC-13 | `DescriptionOutcomeClassifierTest::testClassifiesEveryOutcomeClass` passes |
| GTM-SC-14 | `DescriptionReportControllerTest::testReportIsIdempotentByRequestKey` passes |
| GTM-SC-15 | `scripts/test_cost_per_accepted_report.py::test_exit_2_on_missing_or_inconsistent_inputs` passes |
| GTM-SC-16 | Sealed plan hash recorded before the first counted draft; readout published |
| GTM-SC-21 | `DescriptionPresentationControllerTest::testFirstPresentationIsRecordedOnce` and `DescriptionOutcomeExportTest::testCohortIsFirstPresentation` pass |

## Canon authority (Canon v0.26.2)

| ID | Rule | Applied in |
|---|---|---|
| AIPX-03 | Instrument the feedback flywheel | Outcome events and classes |
| COST-04 | Measure cost per accepted output | Slice 4 |
| EVAL-22 | Validate the offline proxy against the product metric | Blind audit beside the rate |
| AUDIT-08 | Probability sample before a design-based interval | Descriptive label; no quoted rate |
| EXP-09 | No peeking: fix the analysis before the data | Operator S5 seal |
| DATA-14 | No dual writes; one system of record | Events table only |
| AGT-13 | No silent ADR override | Slice 0 amendment |
| PERF-01 | Percentiles, not averages | Latency p50/p95/p99 with n |
| MEAS-09 | Factor must be defined, observable, and decision-linked (`lexicons/epistemics.md#meas-09`) | `presented` event as the observable denominator and window origin |
| GRPH-33 | A node without a contract cannot be parallelised (`lexicons/graph-theory.md#grph-33`) | Slice 1b names the producer, store and consumer of `presented_at`; Slice 4 names its usage input |
| CARD-11 | Measurement integrity (`reasoning/measurement-integrity.md`) | Denominator fixed by `presented` events; `curated_without_presentation` reported |
| CARD-06 | Evidence before commitment (`reasoning/evidence-before-commitment.md`) | Cohort period and GPU resources sealed before the first counted draft |
| CARD-05 | Durable decision memory (`reasoning/durable-decision-memory.md`) | Plan, usage request and report hashes recorded on `E15-40` |
