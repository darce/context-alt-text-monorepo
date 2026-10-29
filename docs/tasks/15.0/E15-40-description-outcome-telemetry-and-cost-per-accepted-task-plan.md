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
> - **Blocked by**: DESCAUTH-1 S3 and S7 (Slices 1–4). Slice 0 is not blocked.
> - **Anchors verified at**: `43366e5d25` (2026-10-28); unchanged at main `8eece0358f`.

---

## E15-40. Description outcome telemetry and cost per accepted

Paths are repo-relative. The PHP and JS surfaces in Slices 1–3 sit beside code that DESCAUTH-1 S7 and S8 create, so those slices name symbols and take their directory from DESCAUTH-1; they enter the Decomposition JSON once it merges.

## Objective

Learn whether beta drafts are accepted and what an accepted description costs [AIPX-03, COST-04], without a second store, free text or retraining. Slice 0 amends ADR-017 and the DESCAUTH-1 plan now [AGT-13]. After DESCAUTH-1 lands, later slices classify each presented draft into one of six outcome classes, add one Report a problem action, export outcomes per site, and compute cost per accepted output from GPU usage under a sealed analysis plan.

## Intake

> Include this section when a P0 scope intake pass was conducted before assessment. Omit for bug fixes, tech debt tasks, and spec-derived tasks.

- **Scope one-pager**: `docs/scopes/descpick-gtm-beta-readiness-scope.md`; eval cases GTM-SC-12 … GTM-SC-16.
- **Key Q&A decisions** (on `MAINT-descpick-gtm-scope-20261028`): #20467 outcomes go in ADR-017's append-only events table, not post meta (post meta keeps only current state, so supersession, edit-after-apply and idempotent reports cannot be derived); #20469 accepted definition and floor; #20470 report control, with the FIR curriculum link not confirmed (#16800 `curriculum_t` is a per-identity threshold, not a training feed); #20472 W1 pricing.
- **Not-Doing**: post meta mirror; free-text reasons; retraining from reports; automatic telemetry upload; quoting an accuracy rate.

## Problem Statement

1. The beta keeps a model that was kept, not proven best (assessment C1). Nothing records whether a presented draft was applied, edited, discarded or replaced, so acceptance cannot be measured [AIPX-03].
2. Cost is an estimate (assessment F7), not cost per accepted output [COST-04].
3. ADR-017 (:48, :84) selects the append-only `wp_acx_description_events` table but has no report event, reason, edit ratio or idempotency key. Adding them in code would override the ADR silently [AGT-13].
4. A user cannot say a draft is wrong, and an identity error belongs to People, not to the description model (D12, `ml-systems/guidelines-human-ai-interaction.md:201`).

## Constraints

- Slices 1–4 dispatch only after DESCAUTH-1 S3 (schema) and S7 (`DescriptionEventRepository::append`) merge. DESCAUTH-1's Wave Order (:1111) holds its own S1+ until ADR-017 is accepted (ADR-017 :3 is Proposed).
- One system of record: the events table, no post-meta copy [DATA-14] (D1, `ml-systems/manning-information-retrieval.md:161`).
- Report reasons are concept ids with per-language labels through gettext, text domain `alt-context` (sr-012); no free text (C10, D3).
- Copy must be true today: "Reports inform which model we use next. They do not retrain the model." (D14, `ml-systems/guidelines-human-ai-interaction.md:126`).
- No accuracy rate is quoted outside the team: the sites are a convenience sample, so intervals are descriptive only [AUDIT-08].
- The analysis plan is sealed before the first counted draft [EXP-09].
- Edit ratio is computed at write time and reported in aggregate only (D11).
- Greenfield: the new columns go straight into the DESCAUTH-1 S3 schema; no migration.
- PHP: backed enums for outcome classes and reasons (sr-007); `run_transactional` for multi-statement writes (sr-009); PSR-4 filenames or an explicit `require_once` (rg-016).
- Pricing is a flag, default USD 2.00 per GPU-hour, billed per second with a 60-second minimum per GPU session (#20472 W1).

## Workflow Principles

- Decide the schema in the ADR before any code writes it.
- Count every presented draft, including drafts nobody acted on (D2, `epistemics/trustworthy-controlled-experiments.md:114`).
- Fix the definitions, window and thresholds before looking at data; report the primary rate with the strict rate and a sensitivity sweep beside it (D5, D6).
- Send identity errors to the component that can fix them (D12).

## Terminology

| Term | Meaning |
|---|---|
| Presented draft | One `generation_id` shown to a user; the unit of analysis. |
| Window W | 14 days from presentation; later events do not count. |
| Edit ratio | Levenshtein distance over `mb_str_split` code points between the presented draft and the written text, divided by the longer length (0 when both are empty), stored as `decimal(5,4)`. |
| Lenient acceptance | (`applied_unchanged` + `applied_light_edit`) ÷ all presented drafts. Primary. |
| Strict acceptance | `applied_unchanged` ÷ all presented drafts. Reported alongside. |
| n_eff | n ÷ deff, with deff = 1 + (m̄ − 1) × ICC by site (m̄ = mean drafts per site; ICC from one-way ANOVA, floored at 0). |
| Cost per accepted | Billed GPU cost ÷ lenient accepted drafts in the same window; strict alongside. |

## Current State Analysis

| Site | Today |
|---|---|
| `docs/adrs/ADR-017-description-authority-wordpress-curation-service-generation.md` | Proposed (:3); selects `wp_acx_description_events` (:48, :84); event and retention rules follow (:86–:163) |
| `docs/tasks/v0.5.0/DESCAUTH-1-description-authority-history-and-reset-task-plan.md` | S3 schema (:359); S7 `DescriptionEventRepository::append` (:545); S8 (:564); Wave Order (:1111) |
| `scripts/gpu_cost_report.py` | `DEFAULT_HOURLY_RATE = 2.0`, `DEFAULT_TOLERANCE_PCT = 25.0`, `report_costs(usage_paths, smoke_path, *, hourly_rate, tolerance_pct)`; `CostReportError` maps to exit 2 |
| Outcome classifier, report action, outcome export, cost per accepted | None exist |

## Target Outcome

```text
Outcome of one presented draft (window W = 14 days)

  last apply or discard event within W
    apply    edit ratio of the last apply or post-apply edit within W
               = 0            -> applied_unchanged
               <= 0.20        -> applied_light_edit
               >  0.20        -> applied_heavy_edit
    discard                   -> discarded
  neither
    newer draft for the same attachment presented within W
                              -> superseded_by_regeneration
    otherwise                 -> no_outcome

A reported event is a flag on the draft, never a class.
```

Readout, from the sealed plan:

- Lenient acceptance ≥ 50% on ≥ 200 presented drafts from ≥ 5 sites → meets floor; below 50% → below floor. n_eff < 96 → inconclusive, whatever the rate.
- 95% Wilson interval computed with n_eff, labelled "descriptive; convenience sample".
- Sensitivity: lenient acceptance at light-edit cuts 0.10, 0.20 and 0.30.
- Blind audit of 50 applied drafts beside the rate [EVAL-22].
- Cost per accepted (lenient and strict) and generation latency p50/p95/p99 with n [PERF-01].

## Context Loading

> List the minimum authoritative context an agent should load before implementation.
> Prefer small, role-specific surfaces over broad repo ingestion.

- **Rules**: `docs/workbay/rules/backend-php-guidelines.md`, `docs/workbay/rules/testing-php.md`, `docs/workbay/rules/frontend-guidelines.md`, `docs/workbay/rules/testing-typescript.md`, `docs/workbay/rules/backend-python-guidelines.md`, `docs/workbay/rules/testing-python.md`; `docs/workbay/constitution.md#short-rules` (sr-007, sr-009, sr-012; rg-004, rg-016).
- **Contracts**: ADR-017 and its Slice 0 amendment; DESCAUTH-1 S3 and S7 as merged.
- **Handoff/MCP state**: the `E15-40` row; decisions #20467, #20469, #20470, #20472 and the sealed-plan decision.
- **External docs via `ctx7` only if**: a WordPress REST or WP-CLI API detail is unclear from the existing plugin code.

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
|---|---|---|---|---|---|
| `wp_acx_description_events` | ADR-017; DESCAUTH-1 S3 | Append-only events; no report, ratio or key | `reported` kind; `report_reason`, `edit_ratio`, `request_key` (unique) | No: table not built yet | Slice 0 accepted; DESCAUTH-1 S3 schema test |
| `POST /acx/v1/descriptions/{generation_id}/report` | Slice 3 | None | New; idempotent by `request_key` | No | `DescriptionReportControllerTest` |
| Outcome export `acx-description-outcomes/v1` | Slice 2 | None | New WP-CLI JSON export | No | `DescriptionOutcomeExportTest` |
| `scripts/cost_per_accepted_report.py` | Slice 4 | None | New CLI; exit 2 on bad input | No | `scripts/test_cost_per_accepted_report.py` |

Non-functional notes:

- **Latency**: a report is one insert; the review UI never waits on it beyond the request. The cost report runs offline. Generation latency is reported as p50/p95/p99 with n, never a mean.
- **Degraded behaviour**: a failed event write never loses the applied outcome (DESCAUTH-1 S7 durability rule). A failed report shows an error with Retry, reusing the same `request_key`.
- **Load and spikes**: one row per user action, no fan-out. Exports are operator-run per site.
- **Retention**: ADR-017's 180 days applies; report rows hold no text.

## Proposed Solution

1. **Slice 0 (now)**: amend ADR-017 and the DESCAUTH-1 plan with the event kind, columns and unique key.
2. **Slice 1**: `DescriptionOutcomeClassifier`, a pure function from a draft's events to one class.
3. **Slice 2**: a site-local WP-CLI export of closed-window drafts, with no text and no user ids.
4. **Slice 3**: Report a problem: one REST route, one enum, one UI action.
5. **Slice 4**: `scripts/cost_per_accepted_report.py` over usage files, site exports and the sealed plan.
6. **Operator S5**: seal the plan, run the blind audit, publish the internal readout.

## Files and Surfaces to Change

> Name the exact symbol(s) per file — the implementer should not have to grep for the edit site. Mark new symbols `(new)`. Prefer symbol names over line numbers.

| Surface | File | Symbol / Function | Change |
|---|---|---|---|
| ADR | `docs/adrs/ADR-017-description-authority-wordpress-curation-service-generation.md` | Amendment 1 (new section) | Slice 0 |
| DESCAUTH-1 plan | `docs/tasks/v0.5.0/DESCAUTH-1-description-authority-history-and-reset-task-plan.md` | S3 events schema; S7 `DescriptionEventRepository::append` | Slice 0 |
| Outcome | beside `DescriptionEventRepository` (new in DESCAUTH-1 S7) | `DescriptionOutcome` (new), `DescriptionOutcomeClassifier::classify` (new) | Slice 1 |
| Export | plugin WP-CLI registration | `wp acx description-outcomes export` (new) | Slice 2 |
| Report | beside `DescriptionEventRepository` | `DescriptionReportReason` (new), `DescriptionReportController` (new) | Slice 3 |
| Report UI | draft surface from DESCAUTH-1 S8 | Report a problem action (new) | Slice 3 |
| Cost report | `scripts/cost_per_accepted_report.py` | `main`, `report_cost_per_accepted` (new) | Slice 4 |
| Cost test | `scripts/test_cost_per_accepted_report.py` | tests listed in Slice 4 (new) | Slice 4 |
| Make targets | `Makefile` | `lint-scripts`, `test-scripts` | Slice 4 |

## Related Files

| File | Note |
|---|---|
| `scripts/gpu_cost_report.py` | Reused: rate default, usage parsing, `CostReportError` |
| `docs/scopes/descpick-gtm-beta-readiness-evals.json` | GTM-SC-12 … GTM-SC-16 |
| `docs/runbooks/evidence/` | Sealed analysis plan lands here (operator S5) |

## Verification Strategy

> Define the evidence bundle before implementation.
> Include deterministic tests first; add runtime-parity or manual verification when they are genuinely required.

- **Deterministic tests**: PHPUnit for classifier, export and report controller; vitest for the report action; pytest for the cost report.
- **Runtime-parity / environment checks**: one export from the LocalWP demo site run through the cost report before the first beta site.
- **Contract/fixture verification**: the export schema string and keys are asserted exactly; the cost report rejects any other schema.
- **Failure-mode / SLA prompts**: State p99 latency target (not average), degraded behavior when dependency X is down/slow, and spike/peak load assumptions — see planning-review-guide § Non-Functional & Failure-Mode Realism. Answered in Contract and Boundary Impact.
- **Manual verification**: operator S5 only.

```bash
python3 scripts/hooks/guard-task-plan-findings.py --scan-repo
```

```bash
env OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 timeout 300s composer --working-dir=apps/prototype-wp-alt-context test -- --filter 'DescriptionOutcomeClassifierTest|DescriptionOutcomeExportTest|DescriptionReportControllerTest' tests/Unit
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
   - event kind `reported`: one row per report, no text;
   - `report_reason varchar(32) NULL`: one `DescriptionReportReason` concept id;
   - `edit_ratio decimal(5,4) NULL`: written on apply and post-apply edit events, defined as in this plan's Terminology;
   - `request_key char(36) NULL` with `UNIQUE KEY request_key (request_key)`: a client-generated UUID; a repeated key returns the existing row and inserts nothing;
   - retention unchanged;
   - why: outcomes need history that post meta cannot hold (#20467; D1).
   Status stays Proposed; the operator accepts ADR-017 with the amendment (GTM-SC-12).
2. DESCAUTH-1 plan: S3 adds the three columns and the unique index to the events table definition. S7 `DescriptionEventRepository::append` accepts `report_reason`, `edit_ratio` and `request_key`, computes `edit_ratio` at write time, and returns the existing row on a duplicate `request_key`; S7's proof gains "a duplicate key inserts nothing". The Wave Order stays as it is.

Proof: `python3 scripts/hooks/guard-task-plan-findings.py --scan-repo` passes; `git diff --stat` shows only the two files.

### Slice 1: Outcome classifier

Lanes: `e15-40-c1r` (RED) then `e15-40-c1`. Blocked on DESCAUTH-1 S7.

**Goal**: one deterministic class per presented draft.

Functions: `DescriptionOutcome` (new backed enum: `applied_unchanged`, `applied_light_edit`, `applied_heavy_edit`, `discarded`, `superseded_by_regeneration`, `no_outcome`); `DescriptionOutcomeClassifier::classify(array $events, DateTimeImmutable $presentedAt, float $lightEditMax = 0.20): DescriptionOutcome` (new; pure, no database). Rules: the tree in Target Outcome. Apply, discard and post-apply edit are the DESCAUTH-1 S7 event kinds.

RED tests (`DescriptionOutcomeClassifierTest`):

- `testClassifiesEveryOutcomeClass`: data provider with one case per class.
- Edit ratio 0.2000 → light; 0.2001 → heavy.
- An event at presentation + 14 days + 1 second is ignored.
- Apply, then discard, both within W → `discarded` (the last one wins).
- Apply, then a post-apply edit with ratio 0.35 → `applied_heavy_edit`.
- A `reported` event does not change the class.

Proof: RED fails because the classes are missing; after `e15-40-c1` all pass. TEST-15: change the light-edit comparison from `<=` to `<` → the 0.2000 case goes red; revert.

### Slice 2: Outcome export

Lanes: `e15-40-e2r` (RED) then `e15-40-e2`. After Slice 1.

**Goal**: one site-local JSON file per site and window; nothing leaves the site automatically.

Command (new): `wp acx description-outcomes export --since=<YYYY-MM-DD> --until=<YYYY-MM-DD> --out=<path>`. Register it beside the plugin's existing WP-CLI commands; if there are none, register it in the plugin bootstrap under `defined( 'WP_CLI' ) && WP_CLI`.

Format `acx-description-outcomes/v1`:

- header: `schema`, `site_key` (the site's tenant id), `since`, `until`, `window_days` (14), `light_edit_max` (0.20), `exported_at`;
- `rows[]`: `generation_id`, `profile`, `model_revision`, `presented_at`, `outcome`, `edit_ratio` (null unless applied), `reported`, `report_reason`, `latency_ms` (null when the generation event has none);
- no text, no user ids, no attachment ids; only drafts whose window has closed (`presented_at` + 14 days ≤ `until`); timestamps ISO 8601 UTC; rows ordered by `presented_at`, then `generation_id`.

RED tests (`DescriptionOutcomeExportTest`): exact schema string and keys; open-window drafts excluded; no text field anywhere; ordering.

Proof: RED fails; after `e15-40-e2` passes.

### Slice 3: Report a problem

Lanes: `e15-40-r3r` (RED: PHP and JS tests) then `e15-40-r3a` (PHP) then `e15-40-r3b` (JS). Blocked on DESCAUTH-1 S7 and S8.

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

**Goal**: cost per accepted output computed from measured usage, refusing inconsistent inputs.

CLI (new): `python3 scripts/cost_per_accepted_report.py --usage <file>... --outcomes <export.json>... --plan <plan.json> --plan-sha256 <hex> [--hourly-rate 2.0] --out <report.json>`.

- Usage files are the ones `gpu_cost_report.report_costs` reads. Import `DEFAULT_HOURLY_RATE` and `CostReportError` from `gpu_cost_report`, the same way the existing scripts tests import their script.
- Billing: each GPU session bills max(duration in whole seconds, 60). Cost = billed seconds ÷ 3600 × rate.
- Output:
  - total cost;
  - n, sites and n_eff;
  - lenient and strict accepted counts, and cost per accepted for each;
  - the sensitivity table at 0.10, 0.20 and 0.30;
  - verdict: meets floor, below floor or inconclusive;
  - the descriptive 95% Wilson interval on n_eff;
  - latency p50/p95/p99 with n.
- Exit 2 through `CostReportError` when:
  - a file is missing;
  - the export schema is not `acx-description-outcomes/v1`;
  - the plan SHA-256 does not match;
  - an export's window or threshold disagrees with the plan;
  - the usage window does not cover the outcome window.
- Zero accepted drafts is not an error: `cost_per_accepted_usd` is null with a reason, exit 0.
- Register the script under the `lint-scripts:` and `test-scripts:` targets in `Makefile` (lane `e15-40-k4` owns it).

RED tests (`scripts/test_cost_per_accepted_report.py`):

- `test_exit_2_on_missing_or_inconsistent_inputs`: parametrized over the five refusals above.
- `test_billing_applies_per_second_with_one_minute_minimum`: sessions of 30 s and 61 s bill 121 s; at USD 2.00/h that is USD 0.0672.
- `test_inconclusive_when_n_eff_below_96`.
- `test_zero_accepted_reports_null_cost`.
- `test_latency_percentiles_report_n`.

Proof: RED fails; after `e15-40-k4` passes. TEST-15: drop the 60-second minimum → the billing test goes red; revert.

### Operator S5: sealed plan, audit, readout

1. Before the first counted draft:
   - Commit `docs/runbooks/evidence/e15-40-analysis-plan.json` with:
     - `window_days`: 14
     - `light_edit_max`: 0.20
     - `sensitivity`: [0.10, 0.20, 0.30]
     - `floor`: rate 0.50, min_drafts 200, min_sites 5, min_n_eff 96
     - `cohort_start`
     - `audit`: n 50, plus a seed
   - Record the file's SHA-256 as a decision on `E15-40`.
   - Nothing changes after the first counted draft [EXP-09].
2. Collect one export per site, then run the report.
3. Blind-audit 50 applied drafts, drawn by the seeded sample. The reviewer sees the image and text, not the model label or the class (D9). Report agreement beside the rate [EVAL-22].
4. Publish internally, labelled "descriptive; convenience sample" [AUDIT-08] (GTM-SC-16).

## Not Doing

- A post meta mirror of outcomes (DATA-14).
- Free-text report reasons; retraining from reports; a FIR curriculum link (#20470).
- Automatic telemetry upload: beta sites send their export file by hand.
- Quoting an acceptance or accuracy rate outside the team.
- A speed/quality toggle or model change based on early data before the floor's n is reached.

## Decomposition

Only Slice 0 is dispatchable now; Slices 1–4 join this block once DESCAUTH-1 fixes their directories, followed by a fresh `make lane-manifest-init`.

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
| `e15-40-e2r` | `DescriptionOutcomeExportTest.php` | `e15-40-c1` | PHPUnit (red) |
| `e15-40-e2` | export command | `e15-40-e2r` | PHPUnit |
| `e15-40-r3r` | `DescriptionReportControllerTest.php`; report action test | DESCAUTH-1 S7 and S8 merged | PHPUnit and vitest (red) |
| `e15-40-r3a` | `DescriptionReportReason`, `DescriptionReportController` | `e15-40-r3r` | PHPUnit |
| `e15-40-r3b` | report action component | `e15-40-r3a` | vitest, typecheck |
| `e15-40-k4r` | `scripts/test_cost_per_accepted_report.py` | `e15-40-e2` | pytest (red) |
| `e15-40-k4` | `scripts/cost_per_accepted_report.py`, `Makefile` | `e15-40-k4r` | pytest |

### Merge Order

A lane dispatches once every lane it depends on has merged.

1. Now: `e15-40-s0`; then the operator accepts ADR-017.
2. After DESCAUTH-1 S7 (and S8 for the report lanes): `e15-40-c1r`, `e15-40-r3r`.
3. `e15-40-c1`, `e15-40-r3a`.
4. `e15-40-e2r`, `e15-40-r3b`.
5. `e15-40-e2`, then `e15-40-k4r`, then `e15-40-k4`.
6. Operator S5 seals the plan before the first counted draft.

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

- [ ] `docs/adrs/ADR-017-description-authority-wordpress-curation-service-generation.md` carries Amendment 1 with the report event, the three columns and the unique key.
- [ ] `docs/tasks/v0.5.0/DESCAUTH-1-description-authority-history-and-reset-task-plan.md` S3 and S7 include the columns, write-time edit ratio and duplicate-key behaviour.
- [ ] `python3 scripts/hooks/guard-task-plan-findings.py --scan-repo` passes.
- [ ] Operator accepted ADR-017 with the amendment.

### Checklist for Slice 1: Outcome classifier

- [ ] RED tests cover every class, both edit-ratio boundaries, the window edge, last-action-wins and the report flag.
- [ ] The classifier is pure and passes; the boundary mutation was shown red and reverted.

### Checklist for Slice 2: Outcome export

- [ ] The export writes the v1 schema with no text, user ids or attachment ids, and only closed-window drafts.

### Checklist for Slice 3: Report a problem

- [ ] The report route is idempotent by request key, validates reason and key, and checks the attachment capability.
- [ ] The report action reuses its key on retry, shows the exact copy through gettext, and links identity reports to People.
- [ ] `npm --prefix apps/prototype-wp-alt-context run typecheck` passes.

### Checklist for Slice 4: Cost per accepted report

- [ ] `scripts/cost_per_accepted_report.py` refuses missing or inconsistent inputs with exit 2 and bills per second with a 60-second minimum.
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
