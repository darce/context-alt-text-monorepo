# Task Plan

> **Metadata**
>
> - **Date**: 2026-10-28 19:56 EDT
> - **Author**: Claude Opus 5.5 (`claude-opus-5-5`)
> - **Owning Epic**: `docs/epics/v0.4.0/public-demo-launch-readiness-epic.md`
> - **Epic Short ID**: E15
> - **Task Plan Status**: `proposed`
> - **Target Branch**: `feature/e15-38`
> - **Review Coverage Target**: 2
> - **Scope Brief**: `docs/scopes/descpick-gtm-beta-readiness-scope.md`
> - **Anchors verified at**: `43366e5d25` (2026-10-28); unchanged at main `8eece0358f`.

---

## E15-38. Public demo honest wait and beta copy

Source paths below are relative to `apps/prototype-wp-alt-context/` unless they begin with `apps/`, `docs/scopes/`, `docs/epics/`, `docs/tasks/`, `docs/adrs/` or `docs/workbay/` (repo root). Checklists, JSON and commands use full repo-relative paths.

## Objective

One honest cold-start message replaces "~2 min" and "a few minutes" on every surface. The public demo's timeout copy stops telling the visitor to refresh, and a client-only **Stop waiting** control lets them stop before the 120 s ceiling without losing their retry key. All public demo copy (PHP and JS) goes through gettext, and the workbench shows a beta expectations notice. Implements Rec 2 and Rec 5 of `docs/assessments/current/description-model-gtm-selection-assessment-2026-10-28.md` (:153-167, :182-188).

## Intake

> Include this section when a P0 scope intake pass was conducted before assessment. Omit for bug fixes, tech debt tasks, and spec-derived tasks.

- **Scope one-pager**: `docs/scopes/descpick-gtm-beta-readiness-scope.md`; eval cases GTM-SC-01 … GTM-SC-07 in `docs/scopes/descpick-gtm-beta-readiness-evals.json`.
- **Key Q&A decisions**: #20466 (intake), #20474 (Stop is client-only; quota is charged at run creation; a terminal failure resets the key; the 120 s ceiling stays), #20471 (canon), #20472 (web facts), all on `MAINT-descpick-gtm-scope-20261028`.
- **Not-Doing**: server-side cancel; refresh-safe resume; POT/JSON catalogue generation; raising the 120 s ceiling.

## Problem Statement

1. **Wait copy disagrees and over-promises.** The admin says "Will warm on start (~2 min)", "warm-up ≈2 min", "Ready in about 2 min" and "Warming up, this can take a few minutes"; the demo says "A cold start can take several minutes". The server's default describe deadline is 690 s (510 s warm-up + 180 s inference), so "~2 min" is not a promise the system keeps (assessment F6, :118-133).
2. **The timeout copy costs the visitor a second run.** At the 120 s client ceiling the demo says "refresh the page before trying again". A refresh drops the in-memory retry key, so the retry mints a new key and starts a second paid run instead of re-attaching to the first [INT-10]. Conversely, a terminal failure keeps the key today, so Describe with the same image replays the same failure (the status route answers with `replay_terminal_envelope`).
3. **No way to stop waiting before 120 s** [INT-08: past ~2 s an operation needs progress and a way to stop].
4. **Demo copy is untranslatable.** 22 controller and 8 shortcode literals bypass gettext, the image title is concatenated (`'Demo image ' . $id`), and the demo script has no i18n and builds its percent by string concatenation [sr-012, REF-27, FORM-02].
5. **No beta or AI disclosure in the workbench** [HAI-05, HAI-12, PROD-39].

## Constraints

- **sr-012**: literal first argument to `__()`; text domain `alt-context`; a `/* translators: … */` comment immediately before any `__(` whose string has placeholders; ordered placeholders (`%1$d`) when there is more than one (phpcs `WordPress.WP.I18n` is active in `phpcs.xml.dist`).
- The demo script calls `__()` at call time, never at module scope, so tests can stub `wp.i18n` after the hoisted import. The admin `GPU_STATE_VOCABULARY` stays module-scope (existing idiom).
- Numbers go through `Intl.NumberFormat` with the page language (`document.documentElement.lang`).
- English shortcode output stays byte-identical: `js/public/__tests__/fixtures/public-demo-radio/two-instances.html` must not change.
- **sr-004**: `--acx-*` tokens only; the new `stopped` state pairs its colour with the ■ icon.
- **sr-007**: add `RUN_NOT_AVAILABLE` to `PUBLIC_DEMO_ERROR_CODE`; no bare code strings in logic.
- **Greenfield**: delete `POLL_TIMEOUT_MESSAGE` and `stoppedNotice`; no aliases.
- No server change. Stop is client-only and sends no request (#20474: quota is charged when the run is created, so a cancel endpoint would refund nothing). The 120 s client ceiling stays.
- Never call `__()` inside `public_deadline_seconds()` (controller :1153-1168): a `php -r` subprocess test (`tests/Unit/PublicDemoDescribeControllerTest.php:1028-1060`) loads the file without a `__` stub. Adding `__` to the `use function` block is safe because it binds only at call time.
- Generated ux-map files (`docs/ux-maps/public-demo-describe.md`, `docs/ux-maps/gpu-operator-control.md`, `docs/ux-maps/render_ux_maps.visible.json`) change only in lane `e15-38-l8`, only through the renderer. Never hand-edit them.
- RED lanes edit tests only. Implementation lanes do not rewrite the RED tests.
- UXREC-1 overlap: E15-38 renames `stoppedNotice` to `coldStartWait`; UXREC-1 (`docs/tasks/uxrec/UXREC-1-workbench-recovery-task-plan.md` :103, :842) plans to delete `gpuStateNotice`. Whichever lands second rebases; E15-38 does not delete `gpuStateNotice`.
- Plugin boundary: only files in this repo.

## Workflow Principles

- One owner per message: C1 lives once in the admin vocabulary and once in the demo script; lane `e15-38-l6` pins them equal.
- RED first, dispatched as its own lane; the implementation lane inherits tests it cannot renegotiate.
- Every green-on-arrival guard gets a TEST-15 mutation run: make the temporary edit, see red, run `git checkout -- <file>`, then `git status --short` shows only owned paths.
- Delete over flag. Honest over reassuring.

## Terminology

| Term | Meaning |
|---|---|
| C1 | "The first description after a quiet period starts the GPU and can take several minutes. After that, each image takes seconds." |
| Timeout copy | "This is taking longer than expected. The description may still finish: choose Describe again with the same image to check on it." |
| Stopped copy | "Stopped waiting. The image may still be described: choose Describe again with the same image to see the result." |
| Stop waiting | Secondary button, outside the form, visible only while a request is in flight. Client-only: aborts the local fetch or backoff; sends nothing. |
| Retry key | The in-memory `idempotency_key` the demo reuses when the visitor describes the same image again on the same page. |
| Re-attach | A submit with the same key and media returns the existing run (controller idempotency) instead of starting a new one. |
| Terminal failure | A `PublicDemoClientError` with `terminal === true` (failed, cancelled, completed_with_errors, or completed without a description) or a 403 `acx_public_demo_run_not_available`. Clears the key. Everything else (timeout, Stop, 429, invalid envelope, network) keeps it. |
| Beta expectations notice | Informational notice at the top of the workbench (Slice 4). |

## Current State Analysis

At `43366e5d25`:

**Demo client (`js/public/demo-describe.js`, 404 lines)**

- :1-2 `POLL_TIMEOUT_MESSAGE` = "This description is taking longer than expected. Please wait a moment, then refresh the page before trying again." It is exported (`js/public/demo-describe.d.ts:1`) and imported by `js/public/__tests__/demo-describe.test.ts:8` (used :116, :135, :294, :409).
- :171-224 `requestJson` owns an AbortController with two abort kinds, `deadline` and `navigation`; an abort surfaces as `timeoutError()` or `requestAbortedError()`. A Stop that calls `navigation.abort()` therefore surfaces as `requestAbortedError()`, so the catch must check a `userStopped` flag first.
- :141-169 `waitForBackoff` races the sleep against the deadline and the navigation abort.
- :225 `terminalFailure`; `pollRun` throws it for `completed_with_errors`, `failed` and `cancelled`, and throws INCOMPLETE_RESULT (:266) when a completed run has no description. Today none of these is distinguishable from a timeout in the catch.
- :282-302 `statusPresentation`: warming copy at :284; percent by template literal at :291.
- :301-393 `initializeDemo`: guard :310; icon map :319; submit handler :323; `navigation` AbortController :343; success clears `retryKey` and `retryMedia` (:382-383); catch :384 (limited if 429, else failed); finally :389 removes the pagehide listener and re-enables the controls.
- No i18n at all. The 17 user-facing strings are listed in Slice 2.

**Shortcode (`src/public/class-public-demo-shortcode.php`)**

- :63-69 `wp_enqueue_script( self::SCRIPT_HANDLE, …, array(), ACX_VERSION, true )`; :70 `wp_script_add_data( …, 'type', 'module' )`. No `wp-i18n` dependency and no `wp_set_script_translations`.
- 8 bare literals (:55, :60, :101-103 via `esc_html( '…' )`, :110, :112, :113) and `'Demo image ' . $id` at :141.
- The status `<p data-acx-demo-status role="status" aria-live="polite">` (:113) sits outside the form.

**Controller (`src/api/class-public-demo-describe-controller.php`, 1206 lines)**: 22 bare literals (Slice 1 table); the `use function` block (:16-51) has no `__`; :497 uses `sprintf( '… %d-%d …', MIN, MAX )`.

**Module filter (`src/admin/class-admin.php:98-118` `filter_module_script_tag`)**: adds `type="module"` only to the first `<script` that has a `src` (lookahead), so a classic translations inline printed before it stays classic. Its comment says no module handle has a `before` inline today; Slice 1 makes that false.

**Admin wait copy**

| Site | Today | Slice |
|---|---|---|
| `js/admin/pages/workbench/gpuStatePresentation.ts:138` | `stoppedNotice: __('Will warm on start (~2 min)', 'alt-context')` | 3 |
| `js/admin/pages/workbench/gpuStatePresentation.ts:227` | `gpuStateNotice` returns `stoppedNotice` | 3 |
| `js/admin/pages/workbench/ActivityStatusStrip.tsx:82` | `return GPU_STATE_VOCABULARY.stoppedNotice;` | 3 |
| `js/admin/pages/settings/GpuControlCard.tsx:486` | "Cost: ≈$2.00 / service-hour · warm-up ≈2 min · never runs longer than the 60-minute maximum" | 3 |
| `js/admin/pages/settings/GpuControlCard.tsx:502` | `gpu-warmup-eta`: "Warming up, this can take a few minutes" | 3 |
| `js/admin/pages/settings/GpuControlCard.tsx:566-567` | "Starts the description service now (≈$2.00/h). Ready in about 2 min. …" | 3 |
| `js/admin/pages/settings/testConnectionBanner.ts:183` | "Warming up, this can take a few minutes" | 3 |
| `js/public/demo-describe.js:284` | "The description service is warming up. A cold start can take several minutes…" | 2 |

Tests pinning the old copy: `gpuStatePresentation.test.ts:76`, `GpuControlCard.test.tsx:205`, `testConnectionBanner.test.ts:54`, `demo-describe.test.ts:257`. `MediaSelection.statusAnnouncement.test.tsx:515` and `:536` assert `not.toHaveTextContent('about 2 min')` and stay green.

**Workbench (`js/admin/pages/WorkbenchPage.tsx:184-192`)**: `<h1 id="acx-workbench-title">` ("Review Queue") is followed directly by `<div className="acx-workbench__panels">`. Informational notices use `<div className="acx-notice acx-notice--info">` (:213, :238, :287) with no icon.

## Target Outcome

Public demo end states (these rows land in `docs/ux-maps/public-demo-describe.notes.md` in Slice 6):

```text
┌ data-state=warming    ◌ The first description after a quiet period     ┐
│                       starts the GPU and can take several minutes.     │
│                       After that, each image takes seconds.            │
│ client poll ceiling remains 120s (not the server 690s default)         │
│ [ Stop waiting ] secondary, outside the form; sends no request         │
└────────────────────────────────────────────────────────────────────────┘
┌ data-state=failed    × This is taking longer than expected. The        ┐
│                      description may still finish: choose Describe     │
│                      again with the same image to check on it.         │
│                      (120s client ceiling)                             │
│ form re-enabled · in-memory retry key kept for the same image          │
└────────────────────────────────────────────────────────────────────────┘
┌ data-state=stopped   ■ Stopped waiting. The image may still be         ┐
│                      described: choose Describe again with the         │
│                      same image to see the result.                     │
│ client-only: no request sent · key kept · focus returns to Describe    │
└────────────────────────────────────────────────────────────────────────┘
```

- Admin: every stopped and warming surface shows C1; the cost line and the start preview carry no time estimate.
- Workbench: the beta notice sits between the h1 and the panels, details closed by default.
- Every demo string is translatable. English shortcode output is byte-identical; the demo script's English changes only in the warming, timeout and stopped messages and the new button.

## Context Loading

> List the minimum authoritative context an agent should load before implementation.
> Prefer small, role-specific surfaces over broad repo ingestion.

- **Rules**: `docs/workbay/rules/frontend-guidelines.md` and `docs/workbay/rules/testing-typescript.md` (JS/TS lanes); `docs/workbay/rules/backend-php-guidelines.md` and `docs/workbay/rules/testing-php.md` (PHP lanes); `docs/workbay/constitution.md#short-rules` (sr-004, sr-007, sr-012).
- **Contracts**: there is no standalone public-demo contract doc. The envelope is owned by `src/api/class-public-demo-describe-controller.php` and `src/public/class-public-demo-error-code.php`; the ux-map render contract is `docs/ux-maps/render_ux_maps.contracts.json`.
- **Handoff/MCP state**: the `E15-38` row; decisions #20466 and #20474 on `MAINT-descpick-gtm-scope-20261028`.
- **External docs via `ctx7` only if**: `@wordpress/i18n` or `wp_set_script_translations` behaviour with module scripts is in doubt.

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
|---|---|---|---|---|---|
| REST error envelope of `acx/v1/public/demo/describe` and its status route | `src/api/class-public-demo-describe-controller.php` | `{code, message, data.status}`, English messages | Codes and statuses unchanged; messages localized. English text unchanged (the :497 placeholders become `%1$d-%2$d`, which renders the same) | No: codes are the contract; greenfield | L1R literal provider + `PublicDemoDescribeControllerTest` |
| Script `acx-public-demo-describe` | `src/public/class-public-demo-shortcode.php` | module, no deps | deps `wp-i18n`; `alt-context` translations from `public/languages` | No | L1R tests 4 and 5; `AdminEnqueueTest` |
| `js/public/demo-describe.d.ts` | demo client | exports `POLL_TIMEOUT_MESSAGE` | removed; `RUN_NOT_AVAILABLE` and `terminal` added | No (greenfield) | typecheck |
| ux-map render contract | `docs/ux-maps/render_ux_maps.contracts.json` | gpu-operator-control sketch says "warm-up about 2 min" | C1 sketch rows | No | `make lint-ux-maps` + parity tests |

Non-functional notes:

- **Latency**: the 120 s client ceiling stays below the 690 s server deadline on purpose; the copy now says the run may still finish instead of promising a time. p99 time to description is measured by E15-40, not here [PERF-01].
- **Degraded behaviour**: Stop and the timeout abort only the local fetch or backoff; the server run continues, and Describe with the same image re-attaches (idempotent). GPU unavailable consumes no demo quota (pinned by E15-39, GTM-SC-20).
- **Load and spikes**: no new requests. Stop sends nothing; re-attach reuses the existing inflight owner and idempotency row.

## Proposed Solution

1. **Slice 1**: wrap every demo PHP literal in gettext, make the title a translatable `sprintf`, give the demo script a `wp-i18n` dependency and `alt-context` translations, and pin English output to the existing radio fixture.
2. **Slice 2**: add the Stop waiting button and the stopped state, replace the timeout copy, clear the retry key only on terminal failures, and route all demo script copy through a call-time `__()` and `Intl` percent.
3. **Slice 3**: one admin vocabulary entry, `coldStartWait` (C1), replaces `stoppedNotice` and every hard-coded wait estimate.
4. **Slice 4**: a `BetaExpectationsNotice` component under the workbench title.
5. **Slice 5**: a parity test pins the demo's warming copy to the admin C1 and bans "2 min" and "few minutes" from the four copy sources.
6. **Slice 6**: ux-map JSON and notes describe the new states; one lane re-renders the generated maps.

## Files and Surfaces to Change

> Name the exact symbol(s) per file — the implementer should not have to grep for the edit site. Mark new symbols `(new)`. Prefer symbol names over line numbers.

| Surface | File | Symbol / Function | Change |
|---|---|---|---|
| PHP test | `tests/Unit/PublicDemoUserFacingMessagesTranslatableTest.php` (new) | `PublicDemoUserFacingMessagesTranslatableTest` (new), `literalProvider` (new) | Slice 1 RED + guards |
| Shortcode | `src/public/class-public-demo-shortcode.php` | `PublicDemoShortcode` enqueue and render, title fallback | gettext, `wp-i18n` dep, translations |
| Controller | `src/api/class-public-demo-describe-controller.php` | 22 literal sites; `invalid_idempotency_key_error` | gettext; ordered placeholders |
| Admin | `src/admin/class-admin.php` | `filter_module_script_tag` | comment only |
| Demo client | `js/public/demo-describe.js` | `__` (new), `sprintf` (new), `PUBLIC_DEMO_ERROR_CODE`, `PublicDemoClientError`, `timeoutError`, `terminalFailure`, `pollRun`, `statusPresentation`, `initializeDemo`; delete `POLL_TIMEOUT_MESSAGE` | Slice 2 |
| Demo styles | `js/public/demo-describe.css` | `.acx-demo__stop` (new), stopped state rule (new) | Slice 2 |
| Demo types | `js/public/demo-describe.d.ts` | `PUBLIC_DEMO_ERROR_CODE`, `PublicDemoClientError`; delete `POLL_TIMEOUT_MESSAGE` | Slice 2 |
| Demo test | `js/public/__tests__/demo-describe.test.ts` | new describes: Stop waiting, retry key lifecycle, demo copy is translatable | Slice 2 RED |
| Admin vocabulary | `js/admin/pages/workbench/gpuStatePresentation.ts` | `GPU_STATE_VOCABULARY.coldStartWait` (new), `gpuStateNotice` | Slice 3 |
| Activity strip | `js/admin/pages/workbench/ActivityStatusStrip.tsx` | `idleHeadline` | Slice 3 |
| GPU card | `js/admin/pages/settings/GpuControlCard.tsx` | cost zone, `gpu-warmup-eta`, start preview | Slice 3 |
| Connection banner | `js/admin/pages/settings/testConnectionBanner.ts` | STARTING case | Slice 3 |
| Beta notice | `js/admin/pages/workbench/BetaExpectationsNotice.tsx` (new) | `BetaExpectationsNotice` (new) | Slice 4 |
| Workbench | `js/admin/pages/WorkbenchPage.tsx` | `WorkbenchPage` render | Slice 4 |
| Parity test | `js/public/__tests__/coldStartWaitParity.test.ts` (new) | — | Slice 5 |
| ux-maps | `docs/ux-maps/public-demo-describe.uxmap.json`, `docs/ux-maps/public-demo-describe.notes.md`, `docs/ux-maps/gpu-operator-control.uxmap.json`, `docs/ux-maps/gpu-operator-control.notes.md`, `docs/ux-maps/render_ux_maps.contracts.json` | — | Slice 6 |
| Generated ux-maps | `docs/ux-maps/public-demo-describe.md`, `docs/ux-maps/gpu-operator-control.md`, `docs/ux-maps/render_ux_maps.visible.json` | — | Slice 6, renderer only |

## Related Files

| File | Note |
|---|---|
| `src/public/class-public-demo-error-code.php:21` | `RUN_NOT_AVAILABLE = 'acx_public_demo_run_not_available'`, mirrored by the JS code map |
| `js/public/__tests__/fixtures/public-demo-radio/two-instances.html` | English render oracle; must not change |
| `js/public/__tests__/fixtures/public-demo-radio/source-anchors.json` | Line numbers are stale; only its literals are asserted; not refreshed here |
| `tests/Unit/PublicDemoDescribeControllerTest.php:1028-1060` | `php -r` subprocess test; reason `__` must not run in `public_deadline_seconds()` |
| `tests/Unit/AdminEnqueueTest.php:283-294`, `:364` | Module tag and translations test idioms to copy |
| `tests/stubs/wp.php` :700, :708, :722, :2488, :2536, :2608 | `esc_html` escapes; `esc_html__` and `__` return text; script, script data and translations recorders |
| `tests/TestCase.php:100`, `:106` | Already resets `__ac_scripts` and `__ac_script_translations` |
| `js/admin/pages/workbench/__tests__/ActivityStatusStrip.test.tsx` | Run after Slice 3; no copy literal to change |
| `js/admin/hooks/useGpuStateToasts.ts` | Imports the vocabulary; no change |
| `js/admin/pages/workbench/__tests__/MediaSelection.statusAnnouncement.test.tsx` | `:515`, `:536` stay green |
| `phpcs.xml.dist` | `WordPress.WP.I18n` rules |
| `docs/tasks/uxrec/UXREC-1-workbench-recovery-task-plan.md` | :103, :426, :842 overlap |

## Verification Strategy

> Define the evidence bundle before implementation.
> Include deterministic tests first; add runtime-parity or manual verification when they are genuinely required.

- **Deterministic tests**: PHPUnit (Slice 1), Vitest (Slices 2–5), ux-map lint and parity tests (Slice 6). Every RED lane shows its new tests failing for the stated reason before the implementation lane starts.
- **Runtime-parity / environment checks**: typecheck (`npm --prefix apps/prototype-wp-alt-context run typecheck`); `js/public/__tests__/demo-tokens-coverage.test.ts` and `js/admin/styles/components/__tests__/productionCssBundle.test.ts` for the new CSS.
- **Contract/fixture verification**: `git diff --exit-code apps/prototype-wp-alt-context/js/public/__tests__/fixtures/public-demo-radio/` after Slice 1; `make lint-ux-maps` after Slice 6.
- **Failure-mode / SLA prompts**: State p99 latency target (not average), degraded behavior when dependency X is down/slow, and spike/peak load assumptions — see planning-review-guide § Non-Functional & Failure-Mode Realism. Answered in Contract and Boundary Impact: no new latency target (E15-40 measures p99); Stop and timeout abort only the client; no new requests.
- **Manual verification**: on the LocalWP site, describe one image with the GPU stopped, press Stop waiting, then Describe again and confirm the network panel shows the same `idempotency_key`. Optional; the tests carry the proof.

Commands (from the repo root):

```bash
env OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 timeout 300s composer --working-dir=apps/prototype-wp-alt-context test -- --filter 'PublicDemoUserFacingMessagesTranslatableTest|PublicDemoDescribeControllerTest|PublicDemoShortcodeTest|AdminEnqueueTest' tests/Unit
```

```bash
npx vitest run --root apps/prototype-wp-alt-context js/public/__tests__/demo-describe.test.ts js/public/__tests__/demo-tokens-coverage.test.ts js/public/__tests__/coldStartWaitParity.test.ts js/admin/styles/components/__tests__/productionCssBundle.test.ts
```

```bash
npx vitest run --root apps/prototype-wp-alt-context js/admin/pages/workbench/__tests__/gpuStatePresentation.test.ts js/admin/pages/workbench/__tests__/ActivityStatusStrip.test.tsx js/admin/pages/settings/__tests__/GpuControlCard.test.tsx js/admin/pages/settings/__tests__/testConnectionBanner.test.ts js/admin/pages/workbench/__tests__/BetaExpectationsNotice.test.tsx js/admin/pages/__tests__/WorkbenchPage.control-composition.test.tsx
```

```bash
npm --prefix apps/prototype-wp-alt-context run typecheck
```

```bash
make lint-ux-maps
```

## Slice Delivery

> Each slice must name the **files and functions** it touches (`path:symbol`) and the **proof** that closes it — enough for a junior agent to implement the slice from this block alone.

### Slice 1: Demo server and shortcode copy

Lanes: `e15-38-l1r` (RED, test only) then `e15-38-l1`.

**Goal**: every user-facing string the demo's PHP emits goes through gettext, the demo script loads `alt-context` translations, and English output stays byte-identical.

Files/functions:

- `tests/Unit/PublicDemoUserFacingMessagesTranslatableTest.php` (new): lane `e15-38-l1r` only.
- `src/public/class-public-demo-shortcode.php`: the enqueue block (:63-70), render markup (:55, :60, :101-103, :110, :112, :113), title fallback (:141), `use function` block (:9-29).
- `src/api/class-public-demo-describe-controller.php`: the 22 literal sites below; `invalid_idempotency_key_error` (:488-505); `use function` block (:16-51).
- `src/admin/class-admin.php:filter_module_script_tag` (:98-118): comment only.

Literals — controller (count = occurrences; wrap every one):

| # | Literal | Lines |
|---|---|---|
| 1 | 'One attachment ID from the configured public demo allowlist.' | :108 |
| 2 | 'Required client-generated key (16-128 chars, [A-Za-z0-9_-]) in the JSON or form body, or the Idempotency-Key header, for retrying one user-initiated trigger.' | :112 |
| 3 | 'The public description demo is not enabled.' | :134 |
| 4 | 'This demo page token is missing or expired. Refresh the page and try again.' | :143 |
| 5 | 'That image is not available in this demo.' | :156 |
| 6 | 'The demo is temporarily busy. Please retry.' | :180, :200, :246, :681 |
| 7 | 'That retry key is already associated with another demo image.' | :189 |
| 8 | 'Another description is already running. Please try again shortly.' | :211 |
| 9 | 'The demo state is temporarily unavailable. Please retry.' | :232, :305, :670 |
| 10 | 'The description started but its status could not be tracked safely.' | :292 |
| 11 | 'That public demo run is not available.' | :319, :333 |
| 12 | 'The demo could not identify this client safely.' | :420 |
| 13 | 'idempotency_key is required for describe run submissions.' | :485 |
| 14 | 'Too many demo requests. Please wait and try again.' | :695 |
| 15 | 'The demo rate limiter is unavailable. Please retry.' | :699 |
| 16 | 'The demo usage counter is temporarily unavailable.' | :932 |
| 17 | 'The demo usage counter could not be updated safely.' | :946 |
| 18 | 'The description did not complete successfully. Please try another image.' | :1125 |
| 19 | 'The image could not be described. Please try again later.' | :1130 |
| 20 | 'The description service returned an invalid response. Please try again later.' | :1173 |
| 21 | 'The description service is temporarily unavailable. Please try again later.' | :1190 |
| 22 | 'idempotency_key must be %1$d-%2$d characters using only letters, digits, underscore, or hyphen.' (today `%d-%d`) | :497 |

Literals — shortcode (one occurrence each): 'The image description demo is not available right now.' (:55), 'No demo images are available right now.' (:60), 'Illustrative example — not a live result' (:101), 'Alex stands beside a bicycle outside a cafe.' (:102), 'This example is not a description of your selected image. Your live result may differ.' (:103), 'Choose an image to describe' (:110), 'Describe selected image' (:112), 'Select an image, then choose Describe.' (:113). Plus the title 'Demo image %d' (:141).

Changes — lane `e15-38-l1r` (new test file only; header idiom from `tests/Unit/PublicDemoShortcodeTest.php`, plus `use AltContext\Admin\Admin;` and `use PHPUnit\Framework\Attributes\DataProvider;`; read sources with `file_get_contents( ACX_PLUGIN_DIR . 'src/…' )`):

1. `testLiteralIsTranslatedAtEveryOccurrence` with `#[DataProvider('literalProvider')]`. `literalProvider` (new) yields `[relative path, literal, occurrences]` for the 22 + 8 rows above. Assert the count of `/(?:esc_html__|esc_attr__|__)\(\s*'<preg_quote(literal, '/')>'\s*,\s*'alt-context'\s*\)/` equals `occurrences`, and `substr_count( $src, $literal )` equals `occurrences`. RED today.
2. `testDemoImageTitleIsATranslatableSprintf`: the shortcode source contains no `'Demo image ' .`, matches `__\(\s*'Demo image %d'\s*,\s*'alt-context'\s*\)` and contains `/* translators: %d: attachment ID. */`. The controller source contains `/* translators: 1: minimum key length, 2: maximum key length. */`. RED today.
3. `testUntitledAttachmentFallsBackToDemoImageId`: render with attachment 41 untitled; output contains `<span>Demo image 41</span>`. Green on arrival; TEST-15 mutation `'Demo image #' . $id` turns it red.
4. `testDemoScriptDependsOnWpI18nAndLoadsTranslations`: after render, the recorded deps for `acx-public-demo-describe` are exactly `['wp-i18n']`, and the recorded translations are `['domain' => 'alt-context', 'path' => ACX_PLUGIN_DIR . 'public/languages']` (recorder shapes: `tests/stubs/wp.php:2488`, `:2608`; assertion idiom: `tests/Unit/AdminEnqueueTest.php:364`). RED today.
5. `testModuleFilterKeepsDemoTranslationsInlineClassic`: copy the module-tag test at `tests/Unit/AdminEnqueueTest.php:283-294` (its manifest helper, WHY comment and `phpcs:ignore WordPress.WP.EnqueuedResources.NonEnqueuedScript`) with handle `acx-public-demo-describe` and this tag: `<script id="acx-public-demo-describe-js-translations">wp.i18n.setLocaleData({}, "alt-context");</script>` + `"\n"` + `<script id="acx-public-demo-describe-js" src="http://example.test/demo-describe.js"></script>`. Assert exactly one `type="module"`, the translations tag unchanged, and the output contains `<script type="module" id="acx-public-demo-describe-js"`. Green on arrival; mutation: change the filter regex to `'/<script\b/'`.
6. `testEnglishRenderMatchesRadioFixture`: set up the two demo images exactly as the fixture shows (ids 41 and 42, titles Lake and Path, the fixture's URLs), render twice the way `PublicDemoShortcodeTest` renders, join as `$a . "\n" . $b . "\n"`, replace `/acx-demo-media-\d+/` with `acx-demo-media-N` on both sides, and `assertSame` against `js/public/__tests__/fixtures/public-demo-radio/two-instances.html`. Green on arrival; mutation: add a space before `</button>` in the shortcode.

Changes — lane `e15-38-l1`:

1. Shortcode: add `__`, `esc_html__`, `sprintf` and `wp_set_script_translations` to the `use function` block. Enqueue with `array( 'wp-i18n' )` and add `wp_set_script_translations( self::SCRIPT_HANDLE, 'alt-context', ACX_PLUGIN_DIR . 'public/languages' );` after `wp_enqueue_script`. Markup literals become `'…' . esc_html__( '…', 'alt-context' ) . '…'`; :101-103 change `esc_html( '…' )` to `esc_html__( '…', 'alt-context' )`. Title: `sprintf( /* translators: %d: attachment ID. */ __( 'Demo image %d', 'alt-context' ), $id )`.
2. Controller: add `use function __;` (alphabetical, before `absint`). Wrap all 22 literals at every occurrence with `__( '…', 'alt-context' )`. At :497: `sprintf( /* translators: 1: minimum key length, 2: maximum key length. */ __( 'idempotency_key must be %1$d-%2$d characters using only letters, digits, underscore, or hyphen.', 'alt-context' ), self::IDEMPOTENCY_KEY_MIN_LENGTH, self::IDEMPOTENCY_KEY_MAX_LENGTH )`. Do not touch `public_deadline_seconds()`.
3. `class-admin.php`: replace the "No module handle uses a `before` inline today…" comment with: "Module handles that call `wp_set_script_translations` (`alt-context-admin`, `acx-public-demo-describe`) get a classic translations inline once a JSON catalogue exists; the lookahead keeps `type=module` off it [RES-01]." No code change.

Proof: the RED run shows tests 1, 2 and 4 failing on missing gettext and tests 3, 5 and 6 passing, each guard with its mutation red-then-reverted; after `e15-38-l1`, the PHPUnit command in Verification Strategy passes and `git diff --exit-code apps/prototype-wp-alt-context/js/public/__tests__/fixtures/public-demo-radio/` is clean. Run `vendor/bin/phpcs src/public/class-public-demo-shortcode.php src/api/class-public-demo-describe-controller.php` from `apps/prototype-wp-alt-context`; violations are recorded as `lint(phpcs):` low findings and do not block (sr-011).

### Slice 2: Stop waiting, timeout copy and demo client i18n

Lanes: `e15-38-l2r` (RED, test only) then `e15-38-l2`.

**Goal**: the visitor can stop waiting at any point without losing the retry key, the timeout copy points to Describe instead of refresh, only terminal failures clear the key, and every demo string is translatable.

Files/functions: `js/public/__tests__/demo-describe.test.ts` (lane `e15-38-l2r` only); `js/public/demo-describe.js` (`POLL_TIMEOUT_MESSAGE` deleted, `__` (new), `sprintf` (new), `PUBLIC_DEMO_ERROR_CODE`, `PublicDemoClientError`, `timeoutError`, `terminalFailure`, `pollRun`, `statusPresentation`, `initializeDemo`); `js/public/demo-describe.css`; `js/public/demo-describe.d.ts`.

User-facing strings after the change (17 strings, 19 call sites; wrap each in `__( '…', 'alt-context' )`):

| # | String | Site today |
|---|---|---|
| 1 | Timeout copy (new; replaces `POLL_TIMEOUT_MESSAGE`) | :1-2, used by `timeoutError` |
| 2 | 'The demo returned an invalid response. Please refresh the page and try again.' (wrap only; text unchanged) | :32 |
| 3 | 'The demo request was stopped because the page is closing.' | :37 |
| 4 | 'The demo request could not be completed.' | :206, :387 |
| 5 | 'The image could not be described. Please try again later.' | :231, :302 |
| 6 | 'The description finished without a usable result. Please try another image.' | :266 |
| 7 | C1 (replaces the warming copy) | :284 |
| 8 | 'Your image is queued for description…' | :287 |
| 9 | 'Describing the image…' | :291 |
| 10 | 'Describing the image… %s' (new form of the percent message) | :291 |
| 11 | 'GPU description complete.' | completed labels, :293-299 |
| 12 | 'CPU fallback draft (not GPU final).' | completed labels, :293-299 |
| 13 | 'Description available, processing tier unavailable.' | :300 |
| 14 | 'Choose an image before requesting a description.' | :329 |
| 15 | 'Starting the description…' | :342 |
| 16 | Stopped copy (new) | — |
| 17 | 'Stop waiting' (new) | — |

Do not wrap `'The request was aborted.'` (:182): it is an internal `DOMException` reason, never shown.

Changes — lane `e15-38-l2r` (test file only; use literal code strings, not imported constants; fresh local helpers in each new describe; fake timers with `advanceTimersByTimeAsync`; DOM from `ACTUAL_SHORTCODE_TWO_INSTANCES.split('\n')[0]`; `vi.stubGlobal('fetch', fetchImpl)`; reuse the helper shapes of the key-reuse test at :302-370 — `submitButton`, `calls`, `keyOf(index)` — but drive time with `advanceTimersByTimeAsync`, not the setTimeout-based `settle`):

1. `describe('Stop waiting')`:
   - the `.acx-demo__stop` button is hidden after init, visible while a poll is pending, and hidden after completion;
   - clicking it during a pending poll sets `data-state="stopped"`, shows the stopped copy with the ■ icon, aborts the poll (`fetchImpl.mock.calls[1]?.[1]?.signal?.aborted === true`), makes no further fetch, focuses the submit button and hides itself;
   - the next Describe sends the same key (`keyOf(2) === keyOf(0)`);
   - a click during backoff, followed by `advanceTimersByTimeAsync(10_000)`, still leaves exactly 2 fetch calls.
2. `describe('retry key lifecycle')`:
   - at the 120 s ceiling the status shows the timeout copy and the next submit reuses the key;
   - a terminal `failed` poll makes the next submit mint a new key;
   - a 403 poll with body `{code:'acx_public_demo_run_not_available', message:'That public demo run is not available.', data:{status:403}}` makes the next submit mint a new key.
3. `describe('demo copy is translatable')`:
   - with `vi.stubGlobal('wp', { i18n: { __: (text) => '«' + text + '»', sprintf: (format, value) => format.replace('%s', String(value)) } })`, a warming envelope's `statusPresentation(…).message` is `'«' + C1 + '»'`;
   - with `document.documentElement.lang = 'fr-FR'`, a describing envelope with `progress: {done: 1, total: 2}` produces a message containing `50` but not `50%`; reset `lang` afterwards;
   - the source of `js/public/demo-describe.js` (read the way the CSS test at :538-544 reads the stylesheet) has no `/\b__\(\s*(?!['"])/` match and at least 17 matches of `/\b__\(\s*'/g`.
4. Edits to existing tests: replace the `POLL_TIMEOUT_MESSAGE` import with a local `TIMEOUT_COPY` constant at its four uses; add `import * as demoModule from '../demo-describe.js'` and assert `'POLL_TIMEOUT_MESSAGE' in demoModule` is false; change :257 from `toContain('warming up')` to `toBe(C1)`; set `document.documentElement.lang = 'en-US'` in the :258 percent test; extend the CSS test to require `.acx-demo__stop` and `.acx-demo__stop[hidden]` rules.

Changes — lane `e15-38-l2`:

1. Delete `POLL_TIMEOUT_MESSAGE` (:1-2). Add module-level helpers (they read `wp.i18n` at call time):

   ```js
   const __ = (text, domain) => globalThis.wp?.i18n?.__?.(text, domain) ?? text;
   const sprintf = (format, value) => globalThis.wp?.i18n?.sprintf?.(format, value) ?? format.replace('%s', String(value));
   ```

2. `PUBLIC_DEMO_ERROR_CODE`: add `RUN_NOT_AVAILABLE: 'acx_public_demo_run_not_available'`.
3. `PublicDemoClientError`: constructor `(code, message, status = 0, terminal = false)`; set `this.terminal = terminal`.
4. `timeoutError()` uses `__( <timeout copy>, 'alt-context' )`. `terminalFailure` (both branches) and the INCOMPLETE_RESULT throw in `pollRun` (:266) pass `0, true`.
5. Wrap the strings in the table. `statusPresentation` warming returns C1. For the percent, keep the existing done/total guard, then format the ratio: `new Intl.NumberFormat(globalThis.document?.documentElement?.lang || undefined, { style: 'percent', maximumFractionDigits: 0 }).format(done / total)` and return `sprintf( /* translators: %s: share of the image description already done, formatted for the page locale (for example 50%). */ __('Describing the image… %s', 'alt-context'), percent)`.
6. `initializeDemo`:
   - icon map (:319): add `stopped: '■'`;
   - after the guard (:310), create the button once:

     ```js
     const stop = document.createElement('button');
     stop.type = 'button';
     stop.className = 'acx-demo__stop';
     stop.hidden = true;
     stop.textContent = __('Stop waiting', 'alt-context');
     (root.querySelector('[data-acx-demo-status]') ?? statusMessage).after(stop);
     ```

   - in the submit handler, after `setState('queued', …)` and the `navigation` AbortController (:342-343), and before `try`:

     ```js
     let userStopped = false;
     const stopWaiting = () => {
       userStopped = true;
       navigation.abort();
     };
     stop.addEventListener('click', stopWaiting);
     stop.hidden = false;
     ```

   - catch: if `userStopped`, `setState('stopped', __( <stopped copy>, 'alt-context' ))` and keep the key. Otherwise, if the error is a `PublicDemoClientError` and (`error.terminal` or `error.status === 403 && error.code === PUBLIC_DEMO_ERROR_CODE.RUN_NOT_AVAILABLE`), clear `retryKey` and `retryMedia` exactly as the success path does (:382-383); then run the existing limited/failed branch with its fallback wrapped in `__()`;
   - finally, in this order: remove the pagehide listener (existing), `stop.removeEventListener('click', stopWaiting)`, `stop.hidden = true`, re-enable the controls (existing), then, if `userStopped`, focus `form.querySelector('button[type="submit"]')`.
7. `js/public/demo-describe.d.ts`: delete `POLL_TIMEOUT_MESSAGE`; add `RUN_NOT_AVAILABLE` to `PUBLIC_DEMO_ERROR_CODE`; `PublicDemoClientError` gains an optional fourth constructor argument `terminal?: boolean` and a `terminal: boolean` field.
8. `js/public/demo-describe.css`:

   ```css
   .acx-demo__stop {
     margin-top: var(--acx-space-8);
     padding: var(--acx-space-8) var(--acx-space-16);
     border: 1px solid var(--acx-color-accent);
     border-radius: var(--acx-radius-md);
     background: transparent;
     color: var(--acx-color-accent);
     font-weight: var(--acx-font-weight-semibold);
   }

   .acx-demo__stop[hidden] {
     display: none;
   }

   .acx-demo[data-state='stopped'] .acx-demo__status {
     color: var(--acx-color-text);
   }
   ```

Proof: the RED run shows the new describes and the edited assertions failing (not erroring on import); after `e15-38-l2`, `demo-describe.test.ts`, `demo-tokens-coverage.test.ts` and `productionCssBundle.test.ts` pass and typecheck is clean.

### Slice 3: Cold-start message in the admin

Lanes: `e15-38-l4r` (RED, tests only), then `e15-38-l4a`, then `e15-38-l4b`.

**Goal**: one vocabulary entry, `coldStartWait` (C1), is the only admin wait message; no admin surface promises a time.

Files/functions: `js/admin/pages/workbench/__tests__/gpuStatePresentation.test.ts`, `js/admin/pages/settings/__tests__/GpuControlCard.test.tsx`, `js/admin/pages/settings/__tests__/testConnectionBanner.test.ts` (lane `e15-38-l4r`); `js/admin/pages/workbench/gpuStatePresentation.ts:GPU_STATE_VOCABULARY`, `:gpuStateNotice` and `js/admin/pages/workbench/ActivityStatusStrip.tsx:idleHeadline` (lane `e15-38-l4a`); `js/admin/pages/settings/GpuControlCard.tsx` and `js/admin/pages/settings/testConnectionBanner.ts` (lane `e15-38-l4b`).

Changes — lane `e15-38-l4r`:

1. `gpuStatePresentation.test.ts` (runs in node with the real `@wordpress/i18n`): :76 expects C1; import `GPU_STATE_VOCABULARY` and assert `toHaveProperty('coldStartWait', C1)` and `.not.toHaveProperty('stoppedNotice')`.
2. `GpuControlCard.test.tsx`: in the stopped zero-state test (:151-162), assert the element already matched by `/\$2\.00 \/ service-hour/` does not match `/warm-up/i`; in the start-preview test (:178-191), assert the preview contains "It can take several minutes to be ready." and does not match `/2 min/`; :205 expects C1 (the :206 `not.toHaveTextContent(/\d/)` stays).
3. `testConnectionBanner.test.ts:54` expects C1 (the :55 `.not.toMatch(/\d/)` stays).

Changes — lane `e15-38-l4a`:

1. `gpuStatePresentation.ts:138`: replace `stoppedNotice` with `coldStartWait: __('The first description after a quiet period starts the GPU and can take several minutes. After that, each image takes seconds.', 'alt-context'),`.
2. `gpuStateNotice` (:227) and `ActivityStatusStrip.tsx:82` read `GPU_STATE_VOCABULARY.coldStartWait`.

Changes — lane `e15-38-l4b`:

1. `GpuControlCard.tsx:486`: 'Cost: ≈$2.00 / service-hour · never runs longer than the 60-minute maximum'.
2. `GpuControlCard.tsx:502`: render `{GPU_STATE_VOCABULARY.coldStartWait}`; add `GPU_STATE_VOCABULARY` to the :13 import.
3. `GpuControlCard.tsx:566-567`: 'Starts the description service now (≈$2.00/h). It can take several minutes to be ready. ' + 'Returns to automatic after 30 min unless work keeps it busy; the 60-minute maximum still applies.' (both halves stay inside the existing `__()` calls).
4. `testConnectionBanner.ts:183`: return `GPU_STATE_VOCABULARY.coldStartWait`, imported with `import { GPU_STATE_VOCABULARY } from '../workbench/gpuStatePresentation';`.

Proof: the RED run fails on the C1 and estimate assertions; after `e15-38-l4a`, `gpuStatePresentation.test.ts` and `ActivityStatusStrip.test.tsx` pass; after `e15-38-l4b`, `GpuControlCard.test.tsx` and `testConnectionBanner.test.ts` pass and typecheck is clean.

### Slice 4: Beta expectations notice

Lanes: `e15-38-l5r` (RED, tests only) then `e15-38-l5`. Depends on Slice 3's `coldStartWait`.

**Goal**: the workbench tells the user, in place, that drafts are AI-generated proposals to review, what errors to expect, how the wait works and why the beta uses the faster model [HAI-05, HAI-12, PROD-39].

Files/functions: `js/admin/pages/workbench/__tests__/BetaExpectationsNotice.test.tsx` (new) and `js/admin/pages/__tests__/WorkbenchPage.control-composition.test.tsx` (lane `e15-38-l5r`); `js/admin/pages/workbench/BetaExpectationsNotice.tsx` (new, `BetaExpectationsNotice`) and `js/admin/pages/WorkbenchPage.tsx` (lane `e15-38-l5`).

Changes — lane `e15-38-l5r`:

1. `BetaExpectationsNotice.test.tsx` (new): hoisted `vi.mock('@wordpress/i18n', …)` with `__` returning `'«' + text + '»'`, plus `_n` and `sprintf`; static `import { BetaExpectationsNotice } from '../BetaExpectationsNotice';` (RED: `Failed to resolve import "../BetaExpectationsNotice"`). Assert: test id `beta-expectations-notice`; first paragraph is the wrapped beta sentence; the `details` element is closed; the summary reads «What to expect»; the details hold three paragraphs, the second equal to `GPU_STATE_VOCABULARY.coldStartWait`; no `role="alert"`.
2. `WorkbenchPage.control-composition.test.tsx`: under the `describe` at :118, add a test that renders `<WorkbenchPage />`, gets the h1 by role and name "Review Queue" and the notice by test id, asserts `h1.compareDocumentPosition(notice) & Node.DOCUMENT_POSITION_FOLLOWING` is truthy and `notice.nextElementSibling` has class `acx-workbench__panels`. The file's i18n mock (:7-12) has no `_n`; add `_n` only if Vitest reports `No "_n" export`.

Changes — lane `e15-38-l5`:

1. `BetaExpectationsNotice.tsx` (new), following the component idiom `export const X = (): React.JSX.Element =>`:

   ```tsx
   import React from 'react';
   import { __ } from '@wordpress/i18n';
   import { GPU_STATE_VOCABULARY } from './gpuStatePresentation';

   export const BetaExpectationsNotice = (): React.JSX.Element => (
     <div className="acx-notice acx-notice--info" data-testid="beta-expectations-notice">
       <p>{__('Beta: descriptions are AI-generated drafts to review before publishing.', 'alt-context')}</p>
       <details>
         <summary>{__('What to expect', 'alt-context')}</summary>
         <p>
           {__(
             "Expect to correct some drafts, especially unsupported details, who does what, counts and attributes, text in the image, and people's names.",
             'alt-context',
           )}
         </p>
         <p>{GPU_STATE_VOCABULARY.coldStartWait}</p>
         <p>
           {__(
             'Larger models were tested. On current hardware they took minutes per image with no measured accuracy gain, so the beta uses the faster model.',
             'alt-context',
           )}
         </p>
       </details>
     </div>
   );
   ```

2. `WorkbenchPage.tsx`: import it next to the other workbench imports (:11-13) and render `<BetaExpectationsNotice />` between the closing `</h1>` (:187) and `<div className="acx-workbench__panels">` (:188).

Proof: both RED tests fail for the stated reasons; after `e15-38-l5`, both pass and typecheck is clean.

### Slice 5: Cold-start parity guard

Lane: `e15-38-l6`, after Slices 2 and 3.

**Goal**: the demo warming copy and the admin C1 cannot drift apart, and the old estimates cannot come back.

Files/functions: `js/public/__tests__/coldStartWaitParity.test.ts` (new).

Changes: first line `// @vitest-environment jsdom` (the demo module touches `document` at import). Assert `statusPresentation(parsePublicDemoEnvelope({ run_id: 'run-1', status: 'running', phase: 'warming', gpu_state: 'starting', progress: { done: 0, total: 1 } })).message` equals `GPU_STATE_VOCABULARY.coldStartWait` (import from `../../admin/pages/workbench/gpuStatePresentation`). Read four sources and assert none matches `/(~|about |≈)\s?2 min/` or `/few minutes/`: `../demo-describe.js`, `../../admin/pages/workbench/gpuStatePresentation.ts`, `../../admin/pages/settings/GpuControlCard.tsx`, `../../admin/pages/settings/testConnectionBanner.ts`.

Proof: green on arrival; TEST-15 mutations: change one word of C1 in `demo-describe.js` (red), revert; put "~2 min" back in `testConnectionBanner.ts` (red), revert; `git status --short` shows only the new test.

### Slice 6: UX maps

Lanes: `e15-38-l3` (public demo map, after Slice 2) and `e15-38-l7` (GPU operator map, after Slice 3), then `e15-38-l8` (render).

**Goal**: the maps describe the shipped states; generated files come only from the renderer.

Files: `docs/ux-maps/public-demo-describe.uxmap.json` and `docs/ux-maps/public-demo-describe.notes.md` (lane `e15-38-l3`); `docs/ux-maps/gpu-operator-control.uxmap.json`, `docs/ux-maps/gpu-operator-control.notes.md` and `docs/ux-maps/render_ux_maps.contracts.json` (lane `e15-38-l7`); `docs/ux-maps/public-demo-describe.md`, `docs/ux-maps/gpu-operator-control.md` and `docs/ux-maps/render_ux_maps.visible.json` (lane `e15-38-l8`). Lanes `e15-38-l3` and `e15-38-l7` leave `make lint-ux-maps` and the parity tests red until `e15-38-l8` runs; that is expected.

Changes — lane `e15-38-l3`, `public-demo-describe.uxmap.json`:

- :7 goal: "complete" → "available".
- :25 purpose: "idle selection and Stop waiting (stopped) = default;".
- :33 `action_states`: add `stopped`; `submit-describe.when` (:112-124): add `stopped`.
- New action: `{"id":"stop-waiting","verb":"Stop waiting","target":"client-only (no request)","hierarchy":"secondary","costly":false,"irreversible":false,"preview_required":false,"screen_id":"public-demo-describe","when":["in_flight"]}`.
- `domain_state_mappings` default → `["idle","completed","stopped"]`.
- New zone: `{"id":"z-stop","label":"OBSERVED secondary Stop waiting — visible only in in_flight; client-only (no request); stops polling, keeps the key, returns focus to Describe.","role":"job","states":["loading"]}`.
- `z-submit` label: "OBSERVED primary Describe selected image — enabled in idle, completed, failed, limited, timeout and stopped; disabled in in_flight. Same control retries and re-attaches with the same image; key reuse is in-memory only."
- `z-status` (:55): add ", stopped"; its null label becomes "Description available, processing tier unavailable."
- :94 exit purpose: delete "Timeout copy currently tells the visitor to refresh."
- `open_questions[0]`: "PROPOSED, not implemented: same-run resume after refresh. Same-page resume after the 120s poll ceiling or Stop waiting is implemented by E15-38 (kept key, same image). Bound remains existing inflight owner + idempotency; not a new paid job; 120s per-poll ceiling stays; bulkhead and nonce/allowlist stay."
- `slices[0]`: "PROPOSED follow-up, not this map: same-run resume after refresh using existing owner plus idempotency only. Same-page re-attach after timeout or Stop waiting is implemented (E15-38). Keep the 120s ceiling, inflight bulkhead, nonce, and allowlist."
- Flow `observed-error-or-timeout` steps: "failed / incomplete (terminal) → data-state=failed; form re-enabled; key cleared. Invalid envelope → data-state=failed; key kept"; "120s client ceiling → timeout copy (same image re-attaches); form re-enabled; in-memory key kept"; "visitor refreshes anyway → key dropped (refresh-safe resume not implemented)".
- Flow `observed-same-page-retry` steps: "limited, timeout, stopped or non-terminal failure on the same page with the same media → same idempotency_key"; "completed run, terminal failure or run_not_available clears the key; the next submit mints a new one".
- New flow: `{"id":"stop-waiting","job":"describe-allowlisted-image","label":"OBSERVED: Stop waiting is client-only and keeps the key","steps":[{"screen_id":"public-demo-describe","branch_label":"in_flight → Stop waiting (secondary) → polling stops; no request; data-state=stopped"},{"screen_id":"public-demo-describe","branch_label":"Describe again with the same image → same idempotency_key re-attaches to the run"}]}`.

Changes — lane `e15-38-l3`, `public-demo-describe.notes.md` (box rows are 74 characters wide):

| Line | Edit |
|---|---|
| :35 | "**Description complete, processing tier unavailable.**" → "**Description available, processing tier unavailable.**" |
| :55 | Status tokens: add `/stopped` |
| :84 | `│ controls disabled · Stop waiting shown in every in-flight phase        │` |
| :87-90 | Replace the warming box with the first box of Target Outcome (6 rows) |
| :102 | `│                   or  ✓ Description available, processing tier         │` (keep :101 and :103) |
| :113 | Heading: append ", Stop waiting" |
| :120 | `│ form re-enabled · key cleared (terminal failure)                       │` |
| :122-126 | Replace the timeout box with the second and third boxes of Target Outcome (11 rows) |
| :129 | "Same-page retry of the same media reuses the key after limited, timeout, Stop waiting or a non-terminal failure; a completed run, a terminal failure or `run_not_available` clears it. Refresh (exit `refresh-page-drops-retry-key`) drops it; the timeout and stopped copy point to Describe on the same page instead. The exit node stays `kind=exit` / `states=default` (RLSE-04: do not invent extra journey states on an exit)." |
| :147 | `│ null / legacy   →  Description available, processing tier unavailable. │` |
| :175 | "- **INT-10 / INT-08 (E15-38):** the 120s ceiling and Stop waiting both re-enable the form and keep the in-memory key; the timeout and stopped copy send the visitor to Describe with the same image, which re-attaches to the run. Stop waiting is client-only (no request). Same-page re-attach is implemented; refresh-safe resume is not." |

Changes — lane `e15-38-l7`:

- `gpu-operator-control.uxmap.json` :23: replace "starting/warming without eta → Warming up, this can take a few minutes; ready →" with "starting/warming without eta → “The first description after a quiet period starts the GPU and can take several minutes. After that, each image takes seconds.”; ready →"; :37 "warm-up time" → "the 60-minute maximum"; :48 "the warm-up time" → "that the service can take several minutes to be ready (no fixed estimate)"; :55 "warm-up estimate" → "several-minutes readiness note (no fixed estimate)".
- `gpu-operator-control.notes.md` (rows 84 wide): :16 → `│ Cost: ≈$2.00 / GPU-hour · never runs longer than the 60 min cap                  │`; replace :27-28 with these three rows (keep :29 and :79):

  ```text
  │ │ Starts the A10 now (≈$2.00/h). It can take several minutes to be ready.    │   │
  │ │ Returns to automatic after 30 min unless work keeps it busy; the 60 min    │   │
  │ │ lease cap still applies.                                                   │   │
  ```

- `render_ux_maps.contracts.json`, `maps['gpu-operator-control']` sketch (rows 62 wide): `'| Cost: about $2/hour · warm-up about 2 min                  |'` → `'| Cost: about $2/hour                                        |'`; replace `'| Warming up, this can take a few minutes                    |'` with three rows `'| The first description after a quiet period starts the GPU  |'`, `'| and can take several minutes. After that, each image takes |'`, `'| seconds.                                                   |'`. Keep "Warming up, about 48 s left". Edit only this map: the `dashboard` map contains the same phrases and is out of scope.

Changes — lane `e15-38-l8`: from `apps/prototype-wp-alt-context`, run `"${ACX_UXMAP_PYTHON:-../../.venv/bin/python}" docs/ux-maps/render_ux_maps.py public-demo-describe gpu-operator-control`, then the lint and parity commands below. On an ImportError, stop and report; never hand-edit generated files.

Proof:

- `e15-38-l3`: the validator and width check below pass; `public-demo-describe.uxmap.json` and `public-demo-describe.notes.md` contain no `POLL_TIMEOUT_MESSAGE`, no "currently tells the visitor to refresh" and no "Description complete, processing".
- `e15-38-l7`: the notes width check below reports 4 rows, none bad (it reports 2 before the edit); every `render_ux_maps.contracts.json` row starting with `|` or `+` is 62 wide; the JSON parses; `_validate_action_conditions` passes on `gpu-operator-control.uxmap.json`; no "2 min" or "few minutes" in the gpu-operator-control map, its notes or `maps['gpu-operator-control']`.
- `e15-38-l8`: `make lint-ux-maps` and both parity tests pass.

```bash
cd apps/prototype-wp-alt-context && python3 -I -c 'import json, sys; sys.path.insert(0, "docs/ux-maps"); import render_ux_maps as r; d = json.load(open("docs/ux-maps/public-demo-describe.uxmap.json", encoding="utf-8")); r._validate_action_conditions(d); print("ok")'
```

```bash
python3 -I -c "import sys; L=[l for l in open(sys.argv[1],encoding='utf-8').read().split('\n') if l and l[0] in '┌│└' and not l.startswith('┌ Public demo ›')]; bad=[l for l in L if len(l)!=74]; print(len(L),'box lines;',len(bad),'bad'); [print(len(l),l) for l in bad]; sys.exit(1 if bad else 0)" apps/prototype-wp-alt-context/docs/ux-maps/public-demo-describe.notes.md
```

```bash
python3 -I -c 'import sys; L=open(sys.argv[1],encoding="utf-8").read().split("\n"); keys=("Cost: ≈$2.00 / GPU-hour","It can take several minutes to be ready.","Returns to automatic after 30 min","lease cap still applies."); hit=[l for l in L if any(k in l for k in keys)]; bad=[l for l in hit if len(l)!=84]; print(len(hit),"rows,",len(bad),"bad"); sys.exit(1 if len(hit)!=4 or bad else 0)' apps/prototype-wp-alt-context/docs/ux-maps/gpu-operator-control.notes.md
```

```bash
npx vitest run --root apps/prototype-wp-alt-context js/admin/__tests__/uxmap-parity.test.ts js/admin/__tests__/uxmap-render-parity.test.ts
```

## Not Doing

- POT or JSON catalogue generation: there is no make-pot target and `public/languages` does not exist yet; translations load once a catalogue ships.
- Server-side cancel of a demo run (#20474).
- Refresh-safe resume (sessionStorage key).
- Raising the 120 s client ceiling.
- Deleting `gpuStateNotice` (UXREC-1 stretch goal, :842).
- `formatStoppedWait` (`js/admin/pages/workbench/GpuTierStatus.tsx:119`), `describe-gpu-tier.notes.md:27`, `src/api/class-describe-controller.php:1634`.
- Comments in `JobPipelineContext.tsx:90` and `JobPipelineContext.scanAndWait.test.tsx:382`, `:600`.
- Changing the invalid-response copy (wrapped only).
- "Reports inform which model we use next…" copy (E15-40).
- Styling or icons for `acx-notice`.
- The ✓/! drift in Screen 3 of `public-demo-describe.notes.md`.
- Refreshing `source-anchors.json` line numbers.

## Decomposition

Machine-checked by `plan_decomposer`; ids map to lanes in the table below.

```json
{
  "version": 1,
  "items": [
    {"id": "s1", "title": "L1R RED: demo PHP copy is translatable", "independent": true, "owns": ["apps/prototype-wp-alt-context/tests/Unit/PublicDemoUserFacingMessagesTranslatableTest.php"], "depends": [], "blast": "none", "anchors": []},
    {"id": "s2", "title": "L1: gettext in shortcode and controller", "independent": false, "owns": ["apps/prototype-wp-alt-context/src/public/class-public-demo-shortcode.php", "apps/prototype-wp-alt-context/src/api/class-public-demo-describe-controller.php", "apps/prototype-wp-alt-context/src/admin/class-admin.php"], "depends": ["s1"], "blast": "none", "anchors": []},
    {"id": "s3", "title": "L2R RED: Stop waiting, key lifecycle, demo i18n", "independent": true, "owns": ["apps/prototype-wp-alt-context/js/public/__tests__/demo-describe.test.ts"], "depends": [], "blast": "none", "anchors": []},
    {"id": "s4", "title": "L2: Stop waiting and demo client i18n", "independent": false, "owns": ["apps/prototype-wp-alt-context/js/public/demo-describe.js", "apps/prototype-wp-alt-context/js/public/demo-describe.css", "apps/prototype-wp-alt-context/js/public/demo-describe.d.ts"], "depends": ["s3"], "blast": "full", "anchors": ["POLL_TIMEOUT_MESSAGE", "PUBLIC_DEMO_ERROR_CODE", "PublicDemoClientError"]},
    {"id": "s5", "title": "L3: public demo ux-map JSON and notes", "independent": false, "owns": ["apps/prototype-wp-alt-context/docs/ux-maps/public-demo-describe.uxmap.json", "apps/prototype-wp-alt-context/docs/ux-maps/public-demo-describe.notes.md"], "depends": ["s4"], "blast": "none", "anchors": []},
    {"id": "s6", "title": "L4R RED: admin cold-start copy", "independent": true, "owns": ["apps/prototype-wp-alt-context/js/admin/pages/workbench/__tests__/gpuStatePresentation.test.ts", "apps/prototype-wp-alt-context/js/admin/pages/settings/__tests__/GpuControlCard.test.tsx", "apps/prototype-wp-alt-context/js/admin/pages/settings/__tests__/testConnectionBanner.test.ts"], "depends": [], "blast": "none", "anchors": []},
    {"id": "s7", "title": "L4a: coldStartWait vocabulary", "independent": false, "owns": ["apps/prototype-wp-alt-context/js/admin/pages/workbench/gpuStatePresentation.ts", "apps/prototype-wp-alt-context/js/admin/pages/workbench/ActivityStatusStrip.tsx"], "depends": ["s6"], "blast": "full", "anchors": ["GPU_STATE_VOCABULARY", "gpuStateNotice"]},
    {"id": "s8", "title": "L4b: GPU card and connection banner copy", "independent": false, "owns": ["apps/prototype-wp-alt-context/js/admin/pages/settings/GpuControlCard.tsx", "apps/prototype-wp-alt-context/js/admin/pages/settings/testConnectionBanner.ts"], "depends": ["s6", "s7"], "blast": "none", "anchors": []},
    {"id": "s9", "title": "L5R RED: beta expectations notice", "independent": true, "owns": ["apps/prototype-wp-alt-context/js/admin/pages/workbench/__tests__/BetaExpectationsNotice.test.tsx", "apps/prototype-wp-alt-context/js/admin/pages/__tests__/WorkbenchPage.control-composition.test.tsx"], "depends": [], "blast": "none", "anchors": []},
    {"id": "s10", "title": "L5: BetaExpectationsNotice in the workbench", "independent": false, "owns": ["apps/prototype-wp-alt-context/js/admin/pages/workbench/BetaExpectationsNotice.tsx", "apps/prototype-wp-alt-context/js/admin/pages/WorkbenchPage.tsx"], "depends": ["s9", "s7"], "blast": "none", "anchors": []},
    {"id": "s11", "title": "L6: cold-start parity guard", "independent": false, "owns": ["apps/prototype-wp-alt-context/js/public/__tests__/coldStartWaitParity.test.ts"], "depends": ["s4", "s7", "s8"], "blast": "none", "anchors": []},
    {"id": "s12", "title": "L7: GPU operator ux-map and render contract", "independent": false, "owns": ["apps/prototype-wp-alt-context/docs/ux-maps/gpu-operator-control.uxmap.json", "apps/prototype-wp-alt-context/docs/ux-maps/gpu-operator-control.notes.md", "apps/prototype-wp-alt-context/docs/ux-maps/render_ux_maps.contracts.json"], "depends": ["s8"], "blast": "none", "anchors": []},
    {"id": "s13", "title": "L8: render generated ux-maps", "independent": false, "owns": ["apps/prototype-wp-alt-context/docs/ux-maps/public-demo-describe.md", "apps/prototype-wp-alt-context/docs/ux-maps/gpu-operator-control.md", "apps/prototype-wp-alt-context/docs/ux-maps/render_ux_maps.visible.json"], "depends": ["s5", "s12"], "blast": "none", "anchors": []}
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
| `e15-38-l1r` | `tests/Unit/PublicDemoUserFacingMessagesTranslatableTest.php` | None | PHPUnit filter `PublicDemoUserFacingMessagesTranslatableTest` (tests 1, 2, 4 red; 3, 5, 6 green + mutations) |
| `e15-38-l1` | `src/public/class-public-demo-shortcode.php`, `src/api/class-public-demo-describe-controller.php`, `src/admin/class-admin.php` | `e15-38-l1r` | PHPUnit command in Verification Strategy; fixture diff clean |
| `e15-38-l2r` | `js/public/__tests__/demo-describe.test.ts` | None | Vitest on that file (new describes red) |
| `e15-38-l2` | `js/public/demo-describe.js`, `js/public/demo-describe.css`, `js/public/demo-describe.d.ts` | `e15-38-l2r` | Vitest on `demo-describe.test.ts`, `demo-tokens-coverage.test.ts`, `productionCssBundle.test.ts`; typecheck |
| `e15-38-l3` | `docs/ux-maps/public-demo-describe.uxmap.json`, `docs/ux-maps/public-demo-describe.notes.md` | `e15-38-l2` | Validator + 74-wide check |
| `e15-38-l4r` | `js/admin/pages/workbench/__tests__/gpuStatePresentation.test.ts`, `js/admin/pages/settings/__tests__/GpuControlCard.test.tsx`, `js/admin/pages/settings/__tests__/testConnectionBanner.test.ts` | None | Vitest on the three files (red) |
| `e15-38-l4a` | `js/admin/pages/workbench/gpuStatePresentation.ts`, `js/admin/pages/workbench/ActivityStatusStrip.tsx` | `e15-38-l4r` | Vitest on `gpuStatePresentation.test.ts`, `ActivityStatusStrip.test.tsx`; typecheck |
| `e15-38-l4b` | `js/admin/pages/settings/GpuControlCard.tsx`, `js/admin/pages/settings/testConnectionBanner.ts` | `e15-38-l4r`, `e15-38-l4a` | Vitest on `GpuControlCard.test.tsx`, `testConnectionBanner.test.ts`; typecheck |
| `e15-38-l5r` | `js/admin/pages/workbench/__tests__/BetaExpectationsNotice.test.tsx`, `js/admin/pages/__tests__/WorkbenchPage.control-composition.test.tsx` | None | Vitest on both (red) |
| `e15-38-l5` | `js/admin/pages/workbench/BetaExpectationsNotice.tsx`, `js/admin/pages/WorkbenchPage.tsx` | `e15-38-l5r`, `e15-38-l4a` | Vitest on both; typecheck |
| `e15-38-l6` | `js/public/__tests__/coldStartWaitParity.test.ts` | `e15-38-l2`, `e15-38-l4a`, `e15-38-l4b` | Vitest on the file + two mutations |
| `e15-38-l7` | `docs/ux-maps/gpu-operator-control.uxmap.json`, `docs/ux-maps/gpu-operator-control.notes.md`, `docs/ux-maps/render_ux_maps.contracts.json` | `e15-38-l4b` | 84-wide and 62-wide checks; JSON parse; validator |
| `e15-38-l8` | `docs/ux-maps/public-demo-describe.md`, `docs/ux-maps/gpu-operator-control.md`, `docs/ux-maps/render_ux_maps.visible.json` | `e15-38-l3`, `e15-38-l7` | `make lint-ux-maps`; both parity tests |

### Merge Order

A lane dispatches once every lane it depends on has merged.

1. Wave 1: `e15-38-l1r`, `e15-38-l2r`, `e15-38-l4r`, `e15-38-l5r`.
2. Wave 2: `e15-38-l1`, `e15-38-l2`, `e15-38-l4a`.
3. Wave 3: `e15-38-l3`, `e15-38-l4b`, `e15-38-l5`.
4. Wave 4: `e15-38-l6`, `e15-38-l7`.
5. Wave 5: `e15-38-l8`.

### Manifest

```bash
make lane-manifest-init TASK=E15-38 LANE_IDS='e15-38-l1r e15-38-l1 e15-38-l2r e15-38-l2 e15-38-l3 e15-38-l4r e15-38-l4a e15-38-l4b e15-38-l5r e15-38-l5 e15-38-l6 e15-38-l7 e15-38-l8' TASK_PLAN=docs/tasks/15.0/E15-38-public-demo-honest-wait-and-beta-copy-task-plan.md
```

### Orchestration Mode

- **Codex subagent (preferred when available)**: Use MCP worker lifecycle tools with the declared lane ownership and verification boundaries. Implementation and RED lanes run on remote codex `gpt-6.1-sol`, high effort, FAST tier; one lane per dispatch; each brief embeds its slice block from this plan.
- **Shell fallback**: Use repo lane helpers or manual worktrees while preserving the same ownership and evidence requirements.

---

## Consolidated Checklist

**Checklist scope rule:** Describe work being delivered, not finding status. Finding status is queried from the handoff DB via `review_findings(review={"operation":"list","status":"open","task_ref":"E15-38"})` or read from `DASHBOARD.txt`.

## Context and Ownership

- [ ] Loaded the minimum authoritative rules, contracts, and handoff state before editing.
- [ ] Confirmed whether external dependency context requires `ctx7`.
- [ ] Recorded boundary ownership and compatibility expectations if any contract is touched.

### Checklist for Slice 1: Demo server and shortcode copy

- [ ] RED lane adds `apps/prototype-wp-alt-context/tests/Unit/PublicDemoUserFacingMessagesTranslatableTest.php`; tests 1, 2 and 4 fail on missing gettext; tests 3, 5 and 6 pass and each was shown red by its mutation, then reverted.
- [ ] `apps/prototype-wp-alt-context/src/public/class-public-demo-shortcode.php` wraps all 8 literals, uses a translatable title with a translators comment, depends on wp-i18n and loads alt-context translations.
- [ ] `apps/prototype-wp-alt-context/src/api/class-public-demo-describe-controller.php` wraps all 22 literals at every occurrence, with ordered placeholders and a translators comment for the key-length message; the deadline helper is untouched.
- [ ] `apps/prototype-wp-alt-context/src/admin/class-admin.php` carries the new module-filter comment and no code change.
- [ ] `env OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 timeout 300s composer --working-dir=apps/prototype-wp-alt-context test -- --filter 'PublicDemoUserFacingMessagesTranslatableTest|PublicDemoDescribeControllerTest|PublicDemoShortcodeTest|AdminEnqueueTest' tests/Unit` passes.
- [ ] `git diff --exit-code apps/prototype-wp-alt-context/js/public/__tests__/fixtures/public-demo-radio/` is clean.

### Checklist for Slice 2: Stop waiting, timeout copy and demo client i18n

- [ ] RED lane extends `apps/prototype-wp-alt-context/js/public/__tests__/demo-describe.test.ts` with the Stop waiting, retry key lifecycle and translatable-copy describes; they fail without import errors.
- [ ] `apps/prototype-wp-alt-context/js/public/demo-describe.js` adds the Stop waiting button and stopped state, the new timeout copy, terminal-only key reset, call-time gettext for all 17 strings and the Intl percent; the old timeout constant is deleted.
- [ ] `apps/prototype-wp-alt-context/js/public/demo-describe.d.ts` matches the new exports.
- [ ] `apps/prototype-wp-alt-context/js/public/demo-describe.css` styles the button and the stopped state with tokens only.
- [ ] `npx vitest run --root apps/prototype-wp-alt-context js/public/__tests__/demo-describe.test.ts js/public/__tests__/demo-tokens-coverage.test.ts js/admin/styles/components/__tests__/productionCssBundle.test.ts` passes.
- [ ] `npm --prefix apps/prototype-wp-alt-context run typecheck` passes.

### Checklist for Slice 3: Cold-start message in the admin

- [ ] RED lane updates `apps/prototype-wp-alt-context/js/admin/pages/workbench/__tests__/gpuStatePresentation.test.ts`, `apps/prototype-wp-alt-context/js/admin/pages/settings/__tests__/GpuControlCard.test.tsx` and `apps/prototype-wp-alt-context/js/admin/pages/settings/__tests__/testConnectionBanner.test.ts`; they fail on the new copy.
- [ ] `apps/prototype-wp-alt-context/js/admin/pages/workbench/gpuStatePresentation.ts` replaces the stopped notice with the coldStartWait entry; `apps/prototype-wp-alt-context/js/admin/pages/workbench/ActivityStatusStrip.tsx` reads it.
- [ ] `apps/prototype-wp-alt-context/js/admin/pages/settings/GpuControlCard.tsx` and `apps/prototype-wp-alt-context/js/admin/pages/settings/testConnectionBanner.ts` carry no time estimate and render the vocabulary entry.
- [ ] `npx vitest run --root apps/prototype-wp-alt-context js/admin/pages/workbench/__tests__/gpuStatePresentation.test.ts js/admin/pages/workbench/__tests__/ActivityStatusStrip.test.tsx js/admin/pages/settings/__tests__/GpuControlCard.test.tsx js/admin/pages/settings/__tests__/testConnectionBanner.test.ts` passes.

### Checklist for Slice 4: Beta expectations notice

- [ ] RED lane adds `apps/prototype-wp-alt-context/js/admin/pages/workbench/__tests__/BetaExpectationsNotice.test.tsx` and the composition test in `apps/prototype-wp-alt-context/js/admin/pages/__tests__/WorkbenchPage.control-composition.test.tsx`; both fail.
- [ ] `apps/prototype-wp-alt-context/js/admin/pages/workbench/BetaExpectationsNotice.tsx` renders the notice with closed details and the shared cold-start entry.
- [ ] `apps/prototype-wp-alt-context/js/admin/pages/WorkbenchPage.tsx` renders the notice between the title and the panels.
- [ ] `npx vitest run --root apps/prototype-wp-alt-context js/admin/pages/workbench/__tests__/BetaExpectationsNotice.test.tsx js/admin/pages/__tests__/WorkbenchPage.control-composition.test.tsx` passes.

### Checklist for Slice 5: Cold-start parity guard

- [ ] `apps/prototype-wp-alt-context/js/public/__tests__/coldStartWaitParity.test.ts` pins the demo warming copy to the admin entry and bans the old estimates in four sources.
- [ ] Both TEST-15 mutations were shown red and reverted; `git status --short` shows only the new test.

### Checklist for Slice 6: UX maps

- [ ] `apps/prototype-wp-alt-context/docs/ux-maps/public-demo-describe.uxmap.json` and `apps/prototype-wp-alt-context/docs/ux-maps/public-demo-describe.notes.md` describe Stop waiting, the stopped state and the key lifecycle; the validator and the 74-wide check pass.
- [ ] `apps/prototype-wp-alt-context/docs/ux-maps/gpu-operator-control.uxmap.json`, `apps/prototype-wp-alt-context/docs/ux-maps/gpu-operator-control.notes.md` and `apps/prototype-wp-alt-context/docs/ux-maps/render_ux_maps.contracts.json` carry C1 and no estimate; the 84-wide and 62-wide checks pass.
- [ ] The render lane regenerates `apps/prototype-wp-alt-context/docs/ux-maps/public-demo-describe.md`, `apps/prototype-wp-alt-context/docs/ux-maps/gpu-operator-control.md` and `apps/prototype-wp-alt-context/docs/ux-maps/render_ux_maps.visible.json` with the renderer only.
- [ ] `make lint-ux-maps` passes.
- [ ] `npx vitest run --root apps/prototype-wp-alt-context js/admin/__tests__/uxmap-parity.test.ts js/admin/__tests__/uxmap-render-parity.test.ts` passes.

## Review Readiness

- [ ] No boundary-touching implementation is left without matching contract/doc/fixture evidence.
- [ ] Runtime-parity checks are included where tests can mask real behavior.
- [ ] Handoff decision records the change, verification, and any contract implications.

## Stretch Goals

- Pair every `acx-notice` tone with an icon across the workbench (sr-004), as its own task.
- Refresh the line numbers in `js/public/__tests__/fixtures/public-demo-radio/source-anchors.json`.

## Success Criteria

| Eval case | Proof |
|---|---|
| GTM-SC-01 | `tests/Unit/PublicDemoUserFacingMessagesTranslatableTest.php` passes |
| GTM-SC-02 | `demo-describe.test.ts` › Stop waiting passes |
| GTM-SC-03 | `demo-describe.test.ts` › retry key lifecycle passes |
| GTM-SC-04 | `demo-describe.test.ts` › demo copy is translatable passes |
| GTM-SC-05 | `coldStartWaitParity.test.ts` passes, with both mutations shown red |
| GTM-SC-06 | `BetaExpectationsNotice.test.tsx` and the composition test pass |
| GTM-SC-07 | `make lint-ux-maps` and both ux-map parity tests pass |

## Canon authority (Canon v0.26.2)

| ID | Rule | Applied in |
|---|---|---|
| INT-08 | Past ~1 s show progress; past ~2 s let the user stop | Slice 2 Stop waiting |
| INT-10 | Tell the user the status, what will happen and how to stop | Timeout and stopped copy; key kept for re-attach |
| A11Y-21 | Announce status changes without moving focus (WCAG 4.1.3) | Stopped copy in the existing live region; focus returns to Describe only after Stop |
| RLSE-04 | An undesigned state is a bug | Stopped state designed with copy, icon, focus and map entries |
| HAI-05 | Disclose that output is AI-generated | Beta notice |
| HAI-12 | Present output as a proposal to review | Beta notice wording |
| PROD-39 | Communicate the product stage | "Beta:" lead |
| REF-27 | No unstated environment assumptions, including locale | Gettext; page-language Intl |
| FORM-02 | Locale-aware formats, not hand-built strings | Intl percent; translatable title sprintf |
| TEST-15 | Prove a green test can go red | Mutation runs for every green-on-arrival guard |
