# public-demo-describe — ASCII states, observed vs proposed, manual canon critique

Source of truth: `public-demo-describe.uxmap.json`. Sibling `public-demo-describe.md` is a hand-rendered view, not an official Design Canvas emit.

This map is the public `[acx_demo_describe]` widget. It is not the admin `describe-gpu-tier` map.

This slice is UX documentation, not UI implementation.

## Tooling receipts (do not over-claim)

| check | result |
| --- | --- |
| `command -v ux-map` / `uxmap` | absent |
| `import workbay_canvas_mcp` | `ModuleNotFoundError` (no install/upgrade in this lane) |
| Critique 10316 | ran the unchanged 8-rule pack via Pydantic `model_validate(extra=allow)` and retained local extensions |
| official strict extra=forbid | still 4 extras FAIL — local extensions, not a schema pass |
| consumer TypeScript extra=forbid | local gate only (`uxmap-parity` / `uxmap-render-parity`) |
| `.venv/bin/python …/render_ux_maps.py public-demo-describe` | exit 1 `OptionalRendererUnavailable`: workbay_canvas_mcp is not importable |
| official `ux-map critique` RULE_PACK / schema / gate | **not passed** — do not claim official critique, schema, or gate |

Unavailable capabilities remain typed follow-up, not a stall: official strict UxMap load, RULE_PACK as a merge gate, `ux-map project`, and renderer enrollment into `render_ux_maps.contracts.json` / `render_ux_maps.visible.json`. Consumer TypeScript validation supports local extensions the older official package rejects. OWNED_MAPS / REQUIRED_OWNED_MAPS / HAND_AUTHORED_MAPS enrollment is GPU-LAUNCH-1. Full-file Vitest is blocked by sibling `guided-prototype.uxmap.json` (outside this lane); do not weaken the consumer validator.

## Observed-feature vs observed-production vs proposed (read this first)

| kind | states / behaviour | where |
| --- | --- | --- |
| OBSERVED-UI | idle; queued; warming; describing; generic **Description complete.** plus alt text; HTTP 429; error/failed; 120s poll timeout; live polite; focus on result | this branch (and would be production if deployed) |
| OBSERVED-FEATURE wire | completed nonempty public envelope emits `description_tier`; parser and `pollRun` preserve `provisional_cpu` \| `final_gpu` \| `null`; missing legacy becomes explicit `null` | this feature branch only |
| OBSERVED-PRODUCTION | public demo **is deployed**; these feature changes have **not** been deployed. Prior observation: old Florence recognition image; Qwen-on-GPU entity-description proof is absent (not a fresh runtime check). | production |
| OBSERVED | instance-scoped radios `acx-demo-media-N`, submitting form only | yes |
| OBSERVED | `gpu_state` may appear and is unused by presentation | yes (telemetry, not a result tier) |
| OBSERVED | same-page retry reuses in-memory `idempotency_key`; completed run clears it | yes |
| OBSERVED | refresh drops the in-memory key and `run_id` | yes |
| PRODUCER | `DescriptionResultTier`: `provisional_cpu` \| `final_gpu` | producer enum |
| PROPOSED-UI | typed complete labels from parsed `description_tier` (below) | **no** — do not infer from `gpu_state` |
| PROPOSED INT-07 | clearly marked illustrative example before explicit live Describe | **no** — `preview_required` stays false |
| PROPOSED | refresh-safe same-run resume via existing owner + idempotency | **no** |
| DESIGN Q | durable handle to re-read a terminal run after inflight release | **no** |

Do not paint the observed map green because `preview_required` is false. That flag is current behaviour, not a shipped preview.

## Source anchors (workspace-relative)

| fact | path |
| --- | --- |
| Shortcode idle / limited / empty-allowlist markup | `apps/prototype-wp-alt-context/src/public/class-public-demo-shortcode.php` (`render`, instance-scoped `$group_name = 'acx-demo-media-' . $instance`) |
| Client states, 120s ceiling, envelope parse, in-memory retry key | `apps/prototype-wp-alt-context/js/public/demo-describe.js` (`PUBLIC_DEMO_CLIENT_DEADLINE_CEILING_SECONDS`, `parsePublicDemoEnvelope`, `pollRun`, `statusPresentation`, `initializeDemo`) |
| Radio lookup is per-form checked input | `apps/prototype-wp-alt-context/js/public/demo-describe.js` (`form.querySelector('input[type="radio"]:checked')`) |
| Public REST submit/status, inflight bulkhead, 403 after release | `apps/prototype-wp-alt-context/src/api/class-public-demo-describe-controller.php` (`submit`, `status`, `public_envelope_response`) |
| Completed nonempty envelope emits `description_tier` | `apps/prototype-wp-alt-context/src/api/class-public-demo-describe-controller.php` (`public_description`, `normalize_public_description_tier`) |
| Parser/pollRun preserve known tokens and explicit null | `apps/prototype-wp-alt-context/js/public/demo-describe.js` (`DESCRIPTION_RESULT_TIERS`) |
| Rendered complete label is still generic | `apps/prototype-wp-alt-context/js/public/demo-describe.js` (`statusPresentation` → `Description complete.`) |
| Producer tier enum | `apps/prototype-description-service/scene/domain/description.py` (`DescriptionResultTier`) |
| Status tokens + icon/color | `apps/prototype-wp-alt-context/js/public/demo-describe.css` (`data-state` queued/warming/describing/completed/limited/error/failed) |
| Error vocabulary | `apps/prototype-wp-alt-context/src/public/class-public-demo-error-code.php` |

Admin `describe-gpu-tier` is a different product surface. Do not copy its GPU chip or per-item badges into this public inventory as if they shipped.

## Screen 1 — OBSERVED idle selection

```
┌ Public demo › Describe an image  [data-state=idle]  role=status polite ─┐
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
│ controls disabled                                                      │
└────────────────────────────────────────────────────────────────────────┘
        ▼
┌ data-state=warming    ◌ The description service is warming up.         ┐
│                       A cold start can take several minutes…           │
│ client poll ceiling remains 120s (not the server 690s default)         │
└────────────────────────────────────────────────────────────────────────┘
        ▼
┌ data-state=describing ◌ Describing the image… 50%                      ┐
│ gpu_state may be on the JSON; it is not shown and is not a tier        │
└────────────────────────────────────────────────────────────────────────┘
```

## Screen 3 — OBSERVED-UI complete (generic label; wire unused)

```
┌ data-state=completed  ✓ Description complete.     ← generic UI label   ┐
│ ┌ result (focus moved here) ─────────────────────────────────────────┐ │
│ │ A person walking beside a lake under a cloudy sky.                 │ │
│ │ (description text is separate from the status label)               │ │
│ └────────────────────────────────────────────────────────────────────┘ │
│ JSON may include description_tier on this branch; presentation ignores │
│ [ Describe selected image ]  next click mints a new idempotency key    │
└────────────────────────────────────────────────────────────────────────┘
```

## Screen 4 — OBSERVED 429, error, 120s timeout

```
┌ data-state=limited   ! Another description is already running… (429)   ┐
│ form re-enabled · in-memory retry key kept                             │
└────────────────────────────────────────────────────────────────────────┘
┌ data-state=failed    × The image could not be described…               ┐
│ form re-enabled · in-memory retry key kept                             │
└────────────────────────────────────────────────────────────────────────┘
┌ data-state=failed    × This description is taking longer than expected.│
│                      Please wait a moment, then refresh the page       │
│                      before trying again.   (120s client ceiling)      │
│ form re-enabled · in-memory retry key still kept until refresh         │
└────────────────────────────────────────────────────────────────────────┘
```

Same-page retry of the same media reuses the key. Refresh (exit `refresh-page-drops-retry-key`) drops it. Timeout copy currently pushes refresh. The exit node stays `kind=exit` / `states=default` (RLSE-04: do not invent extra journey states on an exit).

## Screen 5 — OBSERVED PHP substitutes (no client)

```
┌ data-state=limited  ! The image description demo is not available…     ┐
│ flag acx_public_demo_enabled is off · no form                          │
└────────────────────────────────────────────────────────────────────────┘
┌ data-state=error    ! No demo images are available right now.          ┐
│ empty/unreadable allowlist · no form                                   │
└────────────────────────────────────────────────────────────────────────┘
```

## Screen 6 — PROPOSED visible-tier labels (NOT SHIPPED UI)

Wire exists on this feature branch and has not been deployed. Production itself is deployed. Do not treat this sketch as inventory.

Keep description text in `z-result`, separate from the status label. Keep existing live polite and focus-on-result behaviour. Never infer from `gpu_state`.

```
┌ PROPOSED complete labels (NOT SHIPPED UI)                              ┐
│ description text stays in z-result, unchanged                          │
│                                                                        │
│ final_gpu       →  GPU description complete.                           │
│ provisional_cpu →  CPU fallback draft (not GPU final).                 │
│ null            →  Description complete, processing tier unavailable.  │
│                                                                        │
│ Live polite + focus stay as today. 120s ceiling stays.                 │
│ In-memory retry stays. No new paid job / history / resume weakening.   │
└────────────────────────────────────────────────────────────────────────┘
```

## Screen 7 — PROPOSED INT-07 illustrative example (NOT SHIPPED)

Current `submit-describe.preview_required` is **false** and must stay false until this is implemented. Do not mark the observed map complete by flipping that flag.

Test intent when implemented: the example is labeled illustrative; it appears before the visitor explicitly chooses Describe; it is not a live or GPU receipt; the result zone still shows the actual description, never the example.

```
┌ PROPOSED illustrative example (NOT SHIPPED; INT-07)                    ┐
│ [Example — not a live description] A path beside a lake at dusk.       │
│ Shown before the visitor explicitly chooses Describe.                  │
│ Never a GPU receipt. Never substitutes for the actual result.          │
│ Thumbnails above remain input choices, not this example.               │
└────────────────────────────────────────────────────────────────────────┘
```

## Manual heuristic critique

Canon: https://github.com/darce/heuristics-canon (stable IDs; not pinned). Also DDIA latency, Release It!, PRINCIPLES. This is documentation of prior findings, not a claim that official `ux-map critique` passed.

### High

- **INT-07:** `submit-describe.preview_required` is false. Adjudication 10317: allowlist thumbnails are input, not an outcome sample (canon interaction-ux.md ~164). A costly live Describe still has no implemented preview of the *result*. Proposed fix is a clearly marked illustrative example before explicit Describe — documented above, not shipped. Do not set `preview_required` true on the observed action until that ships.

- **HAI-05 / HAI-08 / PROV-06 / DATA-13:** OBSERVED-UI complete is still the generic label. OBSERVED-FEATURE wire now carries `description_tier` on this branch (PHP 2090, parser 2093) and has not been deployed. A visitor still cannot tell CPU fallback from GPU final in the rendered UI. Production is deployed; prior observation used the old Florence recognition image; Qwen-on-GPU entity-description proof is absent (not a fresh runtime check). Proposed typed labels stay out of the observed inventory.

- **INT-10 vs timeout copy:** OBSERVED 120s stop re-enables the form and keeps the in-memory key, but `POLL_TIMEOUT_MESSAGE` tells the visitor to refresh, which drops that key. Same-page retry is implemented; refresh-safe resume is not.

### Medium

- **RLSE-04:** critique warned that the refresh exit only has `states=default`. That is a **scope mismatch**, not a missing journey: `refresh-page-drops-retry-key` is `kind=exit`. Retain `exit` / `default` and explain; do not invent loading/error states for a page unload.

- **RES-02 / RES-03 / INT-08 / CARD-09 / DDIA latency:** The public contract ceiling is 120s per poll, even when `deadline_seconds` is warmup+inference (default 510+180). Warming copy says a cold start can take several minutes. Do not raise the ceiling in this map.

- **API-02 / API-04 / RLSE-03:** `GET …/runs/{run_id}` authorizes only the current inflight owner. Terminal status releases the bulkhead; a later GET is 403 `acx_public_demo_run_not_available`. Refresh-safe authorization remains an open design question. Weakening that 403 is out of bounds.

- **TEST-15 / AGT-06:** Envelope `gpu_state` is accepted and unused. A later UI that maps `warming|ready` onto CPU/GPU result tiers would be a mutant of this map. Kill that inference; proposed tier copy is parsed `description_tier` only.

### Low

- **A11Y-06 / sr-004:** Status already pairs an icon with a token color. Keep that if tier chips are ever added.

- **GRPH-31 / GRPH-33:** Public demo is one screen plus PHP substitutes plus a refresh exit. Do not graft admin Workbench GPU zones onto it.

- **RLSE-03 / Release It! bulkhead:** Rate limit, daily cap, and one inflight public run stay. Resume must not add a second paid job.

- Tooling: official schema/critique pack is **not** a pass. Critique 10316 retained extensions under extra=allow; official strict still fails 4 extras. Consumer TypeScript validation is the machine gate used here. Renderer `visible.json` / `contracts.json` stay unchanged. Full-file Vitest is blocked by sibling `guided-prototype.uxmap.json` (outside this lane).

## What this lane did not do

No UI, PHP, public JS, lockfile, renderer source, snapshot, or validator edits. No merge, deploy, or reviewer substitute. This is UX documentation of on-feature wire vs still-generic UI vs deployed production that does not yet include these feature changes.
