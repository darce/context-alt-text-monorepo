# public-demo-describe — ASCII states, observed vs proposed, manual canon critique

Source of truth: `public-demo-describe.uxmap.json`. Sibling `public-demo-describe.md` is owned by `render_ux_maps.py`; this lane edits only JSON and notes.

This map is the public `[acx_demo_describe]` widget. It is not the admin `describe-gpu-tier` map.

E15-38 source slice: Stop waiting, same-page retry lifecycle and localized client copy. No deployment claim follows from these changes.

## Historical tooling receipts (not current gate evidence)

| check | result |
| --- | --- |
| `command -v ux-map` / `uxmap` | absent |
| `import workbay_canvas_mcp` | `ModuleNotFoundError` (no install/upgrade in this lane) |
| Critique 10316 | ran the unchanged 8-rule pack via Pydantic `model_validate(extra=allow)` and retained local extensions |
| official strict extra=forbid | still 4 extras FAIL — local extensions, not a schema pass |
| consumer TypeScript extra=forbid | local gate only (`uxmap-parity` / `uxmap-render-parity`) |
| `.venv/bin/python …/render_ux_maps.py public-demo-describe` | exit 1 `OptionalRendererUnavailable`: workbay_canvas_mcp is not importable |
| official `ux-map critique` RULE_PACK / schema / gate | **not passed** — do not claim official critique, schema, or gate |

Current-source correction (2026-10-30): `render_ux_maps.py` is the sanctioned generated writer; it accepts an explicit map name. The old hand-rendered-only guidance is superseded by the task’s renderer-only ownership. This lane has no `ux-map`, `uxmap` or `workbay` executable on PATH and makes no fresh official critique claim. The owned action-condition validator and ASCII width check provide bounded local evidence; generated parity belongs to the coordinator render lane.

## Observed-feature vs observed-production vs proposed (read this first)

| kind | states / behaviour | where |
| --- | --- | --- |
| OBSERVED-UI | idle; static illustrative example; queued; warming; describing; typed complete labels plus alt text; HTTP 429; error/failed; 120s poll timeout; client-only Stop waiting; live polite; focus on result | this feature branch (not deployed) |
| OBSERVED-FEATURE wire | completed nonempty public envelope emits `description_tier`; parser and `pollRun` preserve `provisional_cpu` \| `final_gpu` \| `null`; missing legacy becomes explicit `null` | this feature branch only |
| OBSERVED-PRODUCTION | public demo **is deployed**; these feature changes have **not** been deployed. Prior observation: old Florence recognition image; Qwen-on-GPU entity-description proof is absent (not a fresh runtime check). | production |
| OBSERVED | instance-scoped radios `acx-demo-media-N`, submitting form only | yes |
| OBSERVED | `gpu_state` may appear and is unused by presentation | yes (telemetry, not a result tier) |
| OBSERVED | same-page retry keeps the same-media key after Stop, timeout or transient error; completion, terminal failure and 403 `run_not_available` clear it | yes |
| OBSERVED | refresh drops the in-memory key and `run_id` | yes |
| PRODUCER | `DescriptionResultTier`: `provisional_cpu` \| `final_gpu` | producer enum |
| OBSERVED-FEATURE UI | completed labels: **GPU description complete.** / **CPU fallback draft (not GPU final).** / **Description available, processing tier unavailable.** | this feature branch; never from `gpu_state` |
| OBSERVED-FEATURE INT-07 | static illustrative example before Describe; `preview_required` true because that example exists. It is **not** a preview of the selected image | this feature branch |
| PROPOSED | refresh-safe same-run resume via existing owner + idempotency | **no** |
| DESIGN Q | refresh-safe durable resume; same-page terminal capability replay already exists | refresh-safe resume: **no** |

`preview_required` is true because a pre-submit illustrative example exists. That example is not a selected-image preview and is not deployed production.

## Source anchors (workspace-relative)

| fact | path |
| --- | --- |
| Shortcode idle / limited / empty-allowlist markup | `apps/prototype-wp-alt-context/src/public/class-public-demo-shortcode.php` (`render`, instance-scoped `$group_name = 'acx-demo-media-' . $instance`) |
| Client states, 120s ceiling, envelope parse, in-memory retry key | `apps/prototype-wp-alt-context/js/public/demo-describe.js` (`PUBLIC_DEMO_CLIENT_DEADLINE_CEILING_SECONDS`, `parsePublicDemoEnvelope`, `pollRun`, `statusPresentation`, `initializeDemo`) |
| Radio lookup is per-form checked input | `apps/prototype-wp-alt-context/js/public/demo-describe.js` (`form.querySelector('input[type="radio"]:checked')`) |
| Public REST submit/status, inflight bulkhead, matching terminal capability replay, 403 when unavailable | `apps/prototype-wp-alt-context/src/api/class-public-demo-describe-controller.php` (`submit`, `status`, `public_envelope_response`) |
| Completed nonempty envelope emits `description_tier` | `apps/prototype-wp-alt-context/src/api/class-public-demo-describe-controller.php` (`public_description`, `normalize_public_description_tier`) |
| Parser/pollRun preserve known tokens and explicit null | `apps/prototype-wp-alt-context/js/public/demo-describe.js` (`DESCRIPTION_RESULT_TIERS`) |
| Rendered complete labels from `description_tier` | `apps/prototype-wp-alt-context/js/public/demo-describe.js` (`statusPresentation`, `initializeDemo`) |
| Static illustrative example before submit | `apps/prototype-wp-alt-context/src/public/class-public-demo-shortcode.php` (`data-acx-demo-preview`) |
| Producer tier enum | `apps/prototype-description-service/scene/domain/description.py` (`DescriptionResultTier`) |
| Status tokens + icon/color | `apps/prototype-wp-alt-context/js/public/demo-describe.css` (`data-state` queued/warming/describing/completed/limited/error/failed/stopped) |
| Error vocabulary | `apps/prototype-wp-alt-context/src/public/class-public-demo-error-code.php` |

Admin `describe-gpu-tier` is a different product surface. Do not copy its GPU chip or per-item badges into this public inventory as if they shipped.

## Screen 1 — OBSERVED idle selection

```
┌ Public demo › Describe an image  [data-state=idle]  role=status polite ─┐
│ Illustrative example — not a live result                               │
│ Alex stands beside a bicycle outside a cafe.                           │
│ This example is not a description of your selected image.              │
│ (aside data-acx-demo-preview, before the form; not the selected image) │
│ Choose an image to describe                                            │
│ ( ) Lake          ( ) Path                                             │
│ radios name=acx-demo-media-<instance>  (this form only)                │
│ [ Describe selected image ]                                            │
│ ● Select an image, then choose Describe.                               │
└────────────────────────────────────────────────────────────────────────┘
```

Empty submit (no radio in this form): `data-state=error`, "Choose an image before requesting a description." Other instances' radios do not leak.

Allowlist thumbnails here are **input choices**, not an outcome sample (INT-07; canon interaction-ux.md ~164; adjudication 10317).

## Screen 2 — OBSERVED queued → warming → describing

```
┌ data-state=queued     ◌ Your image is queued for description…          ┐
│ controls disabled · Stop waiting shown in every in-flight phase        │
└────────────────────────────────────────────────────────────────────────┘
        ▼
┌ data-state=warming    ◌ The first description after a quiet period     ┐
│                       starts the GPU and can take several minutes.     │
│                       After that, each image takes seconds.            │
│ client poll ceiling remains 120s                                       │
│ [ Stop waiting ] secondary, outside the form                           │
└────────────────────────────────────────────────────────────────────────┘
        ▼
┌ data-state=describing ◌ Describing the image… 50%                      ┐
│ gpu_state may be on the JSON; it is not shown and is not a tier        │
└────────────────────────────────────────────────────────────────────────┘
```

## Screen 3 — OBSERVED-FEATURE complete (typed labels)

```
┌ data-state=completed  ✓ GPU description complete.                      ┐
│                   or  ✓ CPU fallback draft (not GPU final).            │
│                   or  ✓ Description available, processing tier         │
│                         unavailable.                                   │
│ ┌ result (focus moved here) ─────────────────────────────────────────┐ │
│ │ A person walking beside a lake under a cloudy sky.                 │ │
│ │ (description text is separate from the status label)               │ │
│ └────────────────────────────────────────────────────────────────────┘ │
│ Labels from description_tier only — never from gpu_state               │
│ [ Describe selected image ]  next click mints a new idempotency key    │
└────────────────────────────────────────────────────────────────────────┘
```

## Screen 4 — OBSERVED 429, error, 120s timeout, Stop waiting

```
┌ data-state=limited   ! Another description is already running… (429)   ┐
│ form re-enabled · in-memory retry key kept                             │
└────────────────────────────────────────────────────────────────────────┘
┌ data-state=failed    × The image could not be described…               ┐
│ form re-enabled · key cleared (terminal failure)                       │
└────────────────────────────────────────────────────────────────────────┘
┌ data-state=failed    × This is taking longer than expected. The        ┐
│                      description may still finish: choose Describe     │
│                      again with the same image to check on it.         │
│ form re-enabled · same-image retry key kept · 120s client ceiling      │
└────────────────────────────────────────────────────────────────────────┘
┌ data-state=stopped   ■ Stopped waiting. The image may still be         ┐
│                      described: choose Describe again with the         │
│                      same image to see the result.                     │
│ form re-enabled · key kept · focus returns to Describe                 │
│ client observation stops; no backend cancellation or refund            │
└────────────────────────────────────────────────────────────────────────┘
```

Same-page retry of the same media keeps the key after limited, timeout, Stop waiting or a non-terminal failure. Completion, terminal failure (failed, cancelled, completed_with_errors or completed without a usable description) and 403 `run_not_available` clear it. Choosing different media mints a new key. Refresh drops the in-memory key; refresh-safe resume remains unimplemented. Timeout and stopped copy point to Describe on the same page. Stop cancels local submit/poll fetch, body reading or backoff only; it sends no request and leaves the run and quota unchanged. Controls re-enable before focus returns to Describe. Normal progress uses the existing polite live region without moving focus; completion still focuses the result. The refresh exit stays `kind=exit` / `states=default`.

## Screen 5 — OBSERVED PHP substitutes (no client)

```
┌ data-state=limited  ! The image description demo is not available…     ┐
│ flag acx_public_demo_enabled is off · no form                          │
└────────────────────────────────────────────────────────────────────────┘
┌ data-state=error    ! No demo images are available right now.          ┐
│ empty/unreadable allowlist · no form                                   │
└────────────────────────────────────────────────────────────────────────┘
```

## Screen 6 — OBSERVED-FEATURE complete labels (this branch; not deployed)

```
┌ final_gpu       →  GPU description complete.                           ┐
│ provisional_cpu →  CPU fallback draft (not GPU final).                 │
│ null / legacy   →  Description available, processing tier unavailable. │
│ Description text stays in z-result. Never infer from gpu_state.        │
└────────────────────────────────────────────────────────────────────────┘
```

## Screen 7 — OBSERVED-FEATURE INT-07 illustrative example (this branch; not deployed)

`preview_required` is true because this static example exists. It is **not** a preview of the selected image, not a saved result, not Qwen evidence, and not a GPU receipt. Live result stays in `data-acx-demo-result`.

```
┌ Illustrative example — not a live result                               ┐
│ Alex stands beside a bicycle outside a cafe.                           │
│ This example is not a description of your selected image.              │
│ Your live result may differ.                                           │
│ Shown before Describe. Thumbnails remain input choices.                │
└────────────────────────────────────────────────────────────────────────┘
```

## Manual heuristic critique

Canon v0.26.2: https://github.com/darce/heuristics-canon/tree/v0.26.2 (published release; all 53 manifest digests verified on 2026-10-30). Also DDIA latency, Release It!, PRINCIPLES. This is documentation of prior findings, not a claim that official `ux-map critique` passed.

### High

- **INT-07:** Adjudication 10317: allowlist thumbnails are input, not an outcome sample. This branch adds a static illustrative example before Describe (`preview_required` true). That example is not a preview of the selected image and must not be read as a GPU receipt. These feature changes have not been deployed.

- **HAI-05 / HAI-08 / PROV-06 / DATA-13:** OBSERVED-FEATURE completed UI now labels `final_gpu` / `provisional_cpu` / null from parsed `description_tier` (GREEN 2103). Never from `gpu_state`. Production is deployed; these feature changes have not been deployed. Prior observation used the old Florence recognition image; Qwen-on-GPU entity-description proof is absent (not a fresh runtime check).

- **E15-38 resolved:** [INT-08] **Wait state and cancel** (*Designing Interfaces, 3rd ed.*) and [INT-10] **Status–predict–stop** (*Human-Centered AI*): Stop waiting ends local observation, and stopped/timeout recovery describes same-image retry. Tests exercise submit, body read, poll, backoff and restart, with no cancellation endpoint. [A11Y-21] **Announce status (4.1.3)** (*Web Content Accessibility Guidelines 2.2, SC 4.1.3*): status stays in the polite live region; explicit Stop restores focus after controls re-enable. [RLSE-04] **Undesigned state is a bug** (practice label: bootstrap): stopped has a ■ icon, token color, focus and retry path. These are source implementation claims, not live acceptance.

### Medium

- **RLSE-04:** critique warned that the refresh exit only has `states=default`. That is a **scope mismatch**, not a missing journey: `refresh-page-drops-retry-key` is `kind=exit`. Retain `exit` / `default` and explain; do not invent loading/error states for a page unload.

- **RES-02 / RES-03 / INT-08 / CARD-09 / DDIA latency:** The public contract ceiling is 120s per poll, even when `deadline_seconds` is warmup+inference (default 510+180). Warming copy is canonical C1; percentages use the page language via Intl.NumberFormat. Do not raise the ceiling in this map.

- **API-02 / API-04 / RLSE-03:** `GET …/runs/{run_id}` first attempts matching terminal capability replay (`replay_terminal_envelope`); otherwise it checks the inflight owner and returns 403 `acx_public_demo_run_not_available` when absent or mismatched. This corrects the old unconditional-403 anchor against current controller source. Refresh-safe authorization remains an open design question. Weakening that 403 is out of bounds.

- **TEST-15 / AGT-06:** Envelope `gpu_state` is accepted and unused. A later UI that maps `warming|ready` onto CPU/GPU result tiers would be a mutant of this map. Kill that inference; proposed tier copy is parsed `description_tier` only.

### Low

- **A11Y-06 / sr-004:** Status already pairs an icon with a token color. Keep that if tier chips are ever added.

- **GRPH-31 / GRPH-33:** Public demo is one screen plus PHP substitutes plus a refresh exit. Do not graft admin Workbench GPU zones onto it.

- **RLSE-03 / Release It! bulkhead:** Rate limit, daily cap, and one inflight public run stay. Resume must not add a second paid job.

- Tooling: historical critique 10316 retained extensions under extra=allow; its strict four-extra failure was not rerun here. This lane claims only owned action-condition and ASCII-width validation. Generated Markdown/visible/contracts are outside this lane; render parity awaits the coordinator render lane.

## Validation boundary

The owned map action conditions and 74-character ASCII rows are validated locally. Generated map files are left to the coordinator render lane. Official package schema/critique receipts above are historical; this lane makes no fresh official-tool claim. No deployment or independent review is implied.
