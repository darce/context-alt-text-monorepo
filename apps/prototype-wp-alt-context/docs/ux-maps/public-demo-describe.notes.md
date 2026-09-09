# public-demo-describe — ASCII states, observed vs proposed, manual canon critique

Source of truth: `public-demo-describe.uxmap.json`. Sibling `public-demo-describe.md` is a hand-rendered view, not an official Design Canvas emit.

This map is the public `[acx_demo_describe]` widget. It is not the admin `describe-gpu-tier` map.

## Tooling receipts (do not over-claim)

| check | result |
| --- | --- |
| `command -v ux-map` / `uxmap` | absent |
| `import workbay_canvas_mcp` | `ModuleNotFoundError` (no install/upgrade in this lane) |
| `python3 -m json.tool …/public-demo-describe.uxmap.json` | syntax OK only — not schema validation (13832 bytes pretty-printed) |
| consumer extra=forbid field check (mirrors `uxmap-render-parity.test.ts` model keys) | pass |
| `render_ux_maps._validate_action_conditions` | pass |
| `.venv/bin/python …/render_ux_maps.py public-demo-describe` | exit 1 `OptionalRendererUnavailable`: workbay_canvas_mcp is not importable |
| `.venv/bin/python -m pytest …/test_render_ux_maps.py -q -p no:cacheprovider` | 21 passed, 3339 subtests passed in 36.97s (scoped renderer unit tests; they do not prove this new map's schema/critique) |
| official `ux-map critique` / RULE_PACK | unavailable — manual heuristic critique below, not a machine pack |

Unavailable capabilities (typed follow-up, not a stall): official UxMap Pydantic load, `ux-map critique` RULE_PACK, `ux-map project`, enrollment into `OWNED_MAPS` / `HAND_AUTHORED_MAPS` / `render_ux_maps.contracts.json` / `render_ux_maps.visible.json`. This lane must not edit those allowlists.

## Observed vs proposed (read this first)

| kind | states / behaviour | implemented? |
| --- | --- | --- |
| OBSERVED | idle selection; queued; warming; describing; complete generic alt text; HTTP 429 limited; error/failed; 120s poll timeout | yes |
| OBSERVED | instance-scoped radios `acx-demo-media-N`, read from the submitting form only | yes (JS form query, not a global `acx-demo-media` name) |
| OBSERVED | `gpu_state` may appear on the public envelope and is unused by `statusPresentation` | yes (telemetry, not a result tier) |
| OBSERVED | same-page retry reuses in-memory `idempotency_key`; completed run clears it | yes |
| OBSERVED | refresh drops the in-memory key and `run_id` | yes |
| OBSERVED | public complete payload is `alt_text_draft` only; `item.tier` is dropped | yes |
| PRODUCER (not public UI) | `DescriptionResultTier`: `provisional_cpu` \| `final_gpu` | producer only |
| PROPOSED | typed public complete states: CPU fallback / GPU final / unknown | **no** — do not infer from `gpu_state` |
| PROPOSED | refresh-safe same-run resume via existing owner + idempotency, not a new paid job | **no** |
| DESIGN Q | durable handle to re-read a terminal run after inflight release, without weakening 403 `run_not_available` | **no** |

## Source anchors (workspace-relative)

| fact | path |
| --- | --- |
| Shortcode idle / limited / empty-allowlist markup | `apps/prototype-wp-alt-context/src/public/class-public-demo-shortcode.php` (`render`, instance-scoped `$group_name = 'acx-demo-media-' . $instance`) |
| Client states, 120s ceiling, envelope parse, in-memory retry key | `apps/prototype-wp-alt-context/js/public/demo-describe.js` (`PUBLIC_DEMO_CLIENT_DEADLINE_CEILING_SECONDS`, `statusPresentation`, `initializeDemo`) |
| Radio lookup is per-form checked input, not `FormData(form).get('acx-demo-media')` | `apps/prototype-wp-alt-context/js/public/demo-describe.js` (`form.querySelector('input[type="radio"]:checked')`) |
| Public REST submit/status, inflight bulkhead, 403 after release | `apps/prototype-wp-alt-context/src/api/class-public-demo-describe-controller.php` (`submit`, `status`, `public_envelope_response`) |
| Complete text drops `item.tier` after run/token/media checks | `apps/prototype-wp-alt-context/src/api/class-public-demo-describe-controller.php` (`public_description`) |
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

## Screen 3 — OBSERVED complete (generic alt text, no tier)

```
┌ data-state=completed  ✓ Description complete.                          ┐
│ ┌ result (focus moved here) ─────────────────────────────────────────┐ │
│ │ A person walking beside a lake under a cloudy sky.                 │ │
│ │ (alt_text_draft only — no provisional_cpu / final_gpu / unknown)   │ │
│ └────────────────────────────────────────────────────────────────────┘ │
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

Same-page retry of the same media reuses the key. Refresh (exit `refresh-page-drops-retry-key`) drops it. Timeout copy currently pushes refresh.

## Screen 5 — OBSERVED PHP substitutes (no client)

```
┌ data-state=limited  ! The image description demo is not available…     ┐
│ flag acx_public_demo_enabled is off · no form                          │
└────────────────────────────────────────────────────────────────────────┘
┌ data-state=error    ! No demo images are available right now.          ┐
│ empty/unreadable allowlist · no form                                   │
└────────────────────────────────────────────────────────────────────────┘
```

## Screen 6 — PROPOSED only (not implemented — ASCII is a sketch, not inventory)

```
┌ PROPOSED complete with typed description tier  (NOT SHIPPED)           ┐
│ ✓ Description complete.                                                │
│   CPU fallback draft  |  GPU final  |  unknown (tier absent)           │
│ Must come from item.tier / explicit absence — never from gpu_state.    │
└────────────────────────────────────────────────────────────────────────┘
┌ PROPOSED same-run resume after refresh  (NOT SHIPPED)                  ┐
│ Bound: existing inflight owner + idempotency key. Not a new paid job.  │
│ 120s poll ceiling stays. Bulkhead, nonce, allowlist stay.              │
│ Terminal re-read after inflight release is an open authorization Q.    │
└────────────────────────────────────────────────────────────────────────┘
```

## Manual heuristic critique

Canon: https://github.com/darce/heuristics-canon (stable IDs; not pinned). Also DDIA latency, Release It!, PRINCIPLES. This is a human pass. It is not `ux-map critique` output.

### High

- **HAI-05 / HAI-08 / PROV-06 / DATA-13:** OBSERVED complete is generic alt text. Producer `DescriptionResultTier` exists (`provisional_cpu` / `final_gpu`) but `public_description` returns `alt_text_draft` only after run/token/media checks. A visitor cannot tell CPU fallback from GPU final. Map keeps proposed typed states out of the observed inventory so planning cannot treat them as shipped.

- **INT-10 vs timeout copy:** OBSERVED 120s stop re-enables the form and keeps the in-memory key, but `POLL_TIMEOUT_MESSAGE` tells the visitor to refresh, which drops that key. Recovery that would reuse the existing trigger is hidden by the copy. Same-page retry is implemented; refresh-safe resume is not.

### Medium

- **RES-02 / RES-03 / INT-08 / CARD-09 / DDIA latency:** The public contract ceiling is 120s per poll, even when `deadline_seconds` is warmup+inference (default 510+180). Warming copy says a cold start can take several minutes. The bound is real and honest as a stop; it is not a GPU-ready guarantee. Do not raise the ceiling in this map.

- **API-02 / API-04 / RLSE-03:** `GET …/runs/{run_id}` authorizes only the current inflight owner. Terminal status releases the bulkhead; a later GET is 403 `acx_public_demo_run_not_available`. That is a security bulkhead, not a missing public history page. A durable terminal-run handle is a design question; weakening that 403 is out of bounds.

- **TEST-15 / AGT-06:** Envelope `gpu_state` is accepted and unused. A later UI that maps `warming|ready` onto CPU/GPU result tiers would be a mutant of this map. Kill that inference; proposed tier is `item.tier` or explicit unknown.

### Low

- **A11Y-06 / sr-004:** Status already pairs an icon with a token color. Keep that if tier chips are ever added.

- **GRPH-31 / GRPH-33:** Public demo is one screen plus PHP substitutes plus a refresh exit. Do not graft admin Workbench GPU zones onto it.

- **RLSE-03 / Release It! bulkhead:** Rate limit, daily cap, and one inflight public run stay. Resume must not add a second paid job.

- Tooling: official schema/critique pack was not run. Enrollment of this new `*.uxmap.json` into admin parity `OWNED_MAPS` is coordinator follow-up (this lane does not edit tests or renderer allowlists).

## What this lane did not do

No UI, PHP, Python, lockfile, admin map, renderer, or test edits. No merge, deploy, or reviewer substitute.
