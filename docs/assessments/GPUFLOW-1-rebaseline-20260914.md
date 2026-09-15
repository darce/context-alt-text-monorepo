# GPUFLOW-1 rebaseline 20260914

## Promotion

The operator promotion record identifies `main` as `51ff7022ac75`. The full service
commit reported by `/health` is `51ff7022ac758121c6c0a819db25c8390debe8d3`.
Production was reported running:

`iad.ocir.io/idu2kqqe2jxy/acx-backend@sha256:3ebabd367ea2c8d771721dd074456f50d741aaecc5e6e45aabb71223ac16e408`

with `image_variant=recognition`; Caddy flipped `prod-api-next` to `prod-api`,
the cutover candidate `acx-prod-next` drained, and the per-environment
describe-load deployment contract was reported fresh. No agent-initiated GPU
actuation was performed.

### Image/commit evidence by environment

| environment | observed service commit SHA | observed image digest | evidence boundary |
| --- | --- | --- | --- |
| dev | `51ff7022ac758121c6c0a819db25c8390debe8d3` | not captured | `/health` body head |
| dev-fir | not observed | not observed | every probed route returned `502` |
| staging | `51ff7022ac758121c6c0a819db25c8390debe8d3` | not captured | `/health` body head |
| prod | `51ff7022ac758121c6c0a819db25c8390debe8d3` | `sha256:3ebabd367ea2c8d771721dd074456f50d741aaecc5e6e45aabb71223ac16e408` | `/health` plus operator promotion record |

### Read-only route probe

Probe timestamp: `2026-09-14T17:40:51-04:00`.

| env | route | status / body head |
| --- | --- | --- |
| dev | `/health` | `200 {"status":"ok","timestamp":"2026-09-15T00:44:30.603031+00:00","commit_sha":"51ff7022ac758121c6c0a819db25c8390debe8d3","image_variant":"recognition","database":{"name":"database","status":"ok","detail":"reachable; pgvector_dimension=512"}}` |
| dev | `/ready` | `200 {"status":"ok","checks":[{"name":"database","status":"ok","detail":"reachable; pgvector_dimension=512"},{"name":"breaker","status":"ok","detail":"closed"},{"name":"model_cache","status":"ok","detail":"5 bundle file(s)"},{"name":"embedding_model","status":"ok","detail":"active_space=6b379956; per` |
| dev | `/scene/describe/run` | `405 HTTP Error 405: Method Not Allowed` |
| dev | `/scene/gpu/status` | `200 {"gpu_state":{"state":"stopped","instance_id":"ocid1.instance.oc1.iad.anuwcljr2mcagaqcki4d2szgsymtr4ucpc3dsqzfsvwoj2gtemrjx2dlammq","written_at":1789433056.9113438,"reason":null,"since":1789367256.9710796,"intent":"auto","intent_expires_at":null,"intent_status":"none","honoured_nonce":null,"leas` |
| dev | `/recognition/tenant/whoami` | `404 HTTP Error 404: Not Found` |
| dev | `/recognition/suggestions` | `400 HTTP Error 400: Bad Request` |
| dev-fir | `/health` | `502 HTTP Error 502: Bad Gateway` |
| dev-fir | `/ready` | `502 HTTP Error 502: Bad Gateway` |
| dev-fir | `/scene/describe/run` | `502 HTTP Error 502: Bad Gateway` |
| dev-fir | `/scene/gpu/status` | `502 HTTP Error 502: Bad Gateway` |
| dev-fir | `/recognition/tenant/whoami` | `502 HTTP Error 502: Bad Gateway` |
| dev-fir | `/recognition/suggestions` | `502 HTTP Error 502: Bad Gateway` |
| staging | `/health` | `200 {"status":"ok","timestamp":"2026-09-15T00:44:40.872041+00:00","commit_sha":"51ff7022ac758121c6c0a819db25c8390debe8d3","image_variant":"recognition","database":{"name":"database","status":"ok","detail":"reachable; pgvector_dimension=512"}}` |
| staging | `/ready` | `200 {"status":"ok","checks":[{"name":"database","status":"ok","detail":"reachable; pgvector_dimension=512"},{"name":"breaker","status":"ok","detail":"closed"},{"name":"model_cache","status":"ok","detail":"5 bundle file(s)"},{"name":"embedding_model","status":"ok","detail":"active_space=6b379956; per` |
| staging | `/scene/describe/run` | `405 HTTP Error 405: Method Not Allowed` |
| staging | `/scene/gpu/status` | `401 HTTP Error 401: Unauthorized` |
| staging | `/recognition/tenant/whoami` | `401 HTTP Error 401: Unauthorized` |
| staging | `/recognition/suggestions` | `401 HTTP Error 401: Unauthorized` |
| prod | `/health` | `200 {"status":"ok","timestamp":"2026-09-15T00:44:45.697473+00:00","commit_sha":"51ff7022ac758121c6c0a819db25c8390debe8d3","image_variant":"recognition","database":{"name":"database","status":"ok","detail":"reachable; pgvector_dimension=512"}}` |
| prod | `/ready` | `200 {"status":"ok","checks":[{"name":"database","status":"ok","detail":"reachable; pgvector_dimension=512"},{"name":"breaker","status":"ok","detail":"closed"},{"name":"model_cache","status":"ok","detail":"5 bundle file(s)"},{"name":"embedding_model","status":"ok","detail":"active_space=6b379956; per` |
| prod | `/scene/describe/run` | `405 HTTP Error 405: Method Not Allowed` |
| prod | `/scene/gpu/status` | `401 HTTP Error 401: Unauthorized` |
| prod | `/recognition/tenant/whoami` | `401 HTTP Error 401: Unauthorized` |
| prod | `/recognition/suggestions` | `401 HTTP Error 401: Unauthorized` |

The original pre-promotion stale-image cause is closed as deploy skew for the
environments whose health/ready probes report the promoted commit and `200`.
`dev-fir` remains an unavailable `502` surface, and protected staging/prod
routes remain observed at `401`; neither is treated as an unobserved `200`.
VM disk usage below the 70% promotion precondition was not recorded in the
supplied evidence and remains unverified.

## Symptom classification

The eight rows below split the operator's second observation into its two
distinct defects: wrong-person assignment and duplicate suggestion avatars.

| defect | evidence | classification | slice |
| --- | --- | --- | --- |
| 0 — pre-promotion stale API image (root cause, not an additional UI symptom) | `/health` on dev, staging and prod reports commit `51ff7022ac758121c6c0a819db25c8390debe8d3`; `/ready` is `200` on all three; operator reports prod on the promoted image. | **resolved by promotion (deploy skew; close)** | promotion gate |
| 1 — name listbox opens on load | The operator reproduced `#acx-name-face-listbox-_r_27_` open on load. | **persists on current code**; suspect `NameFaceControl.tsx` initial `useState(true)` state. | C1 |
| 2 — wrong person suggested | The suggestion-card evidence records ground truth **Justin Trudeau** and suggested **Emma Watson**. | **persists on current code**; suspect the recognition suggestion assignment/threshold path. Keep threshold changes evidence-gated and send the row to C3. | C3 |
| 3 — duplicate suggestion avatars | The operator reports that the two avatars in the suggestion card are both Justin Trudeau instead of one representative thumbnail. | **persists on current code**; suspect `suggestion_repository.list_pending_with_details` stale replay and the `SuggestionCards` rendering path. | C2 |
| 4 — occluded cluster representative | The `acx-identity-cluster` uses `guided-katy-perry-2016.jpg`; the reported face is partly occluded by a microphone and has an open mouth. | **persists on current code**; suspect `compute_identity_quality` and representative selection, whose enrollment floors currently allow the occluded face. | C4 (after C3) |
| 5 — cold/bursty Suggest fails opaquely | The operator reproduced the error DOM `Could not generate a draft. Please try again.` and `POST https://demo.altcontext.com/wp-json/acx/v1/recognition/describe 500 (Internal Server Error)`. | **persists on current code**; suspect the sync multipart path in `scene/interface_adapters/http/routers/describe.py` (no demand publication and no `GpuRemoteAdapterError` passthrough). | A1, A3 |
| 6 — naming setting disabled with HTTP 404 | The operator captured a disabled `#acx-settings-allow-person-names` and `Recognition service returned HTTP 404.` after promotion. The probe did not include `/recognition/tenant/naming-agreement`; dev's different `/recognition/tenant/whoami` probe is `404`, while protected staging/prod recognition probes are `401`. | **not reproducible / needs operator re-check**; do not close the UI symptom, but verify the exact authenticated naming-agreement route and proxy target before assigning a new code defect. Suspect `class-settings-controller.php` naming-agreement read if the direct re-check still fails. | A2, A3 |
| 7 — technical “Burst GPU” wording | The settings heading is exactly `<h3 id="acx-gpu-control-title" class="acx-settings__section-title">Settings › Burst GPU</h3>`. | **persists on current code**; suspect `GpuControlCard.tsx` title/copy. | A3 |
| 8 — retention unavailable and Retry inert | The operator captured `<p>Backend unavailable — retention status cannot be loaded.</p>` and reports that Retry does nothing. | **persists on current code**; suspect the shared `AbstractRecognitionProxyController::build_circuit_breaker_key` coupling and the `RetentionPage.tsx` retry feedback path. | A2, A3 |

The classifications for defects 3, 5, 7 and 8 are based directly on the
recorded DOM/console evidence above; no live actuation or inferred route result
was used.

## Live suggestion row

The operator explicitly recorded the Trudeau/Watson row numbers as **NOT
CAPTURED**. The table therefore preserves those values verbatim rather than
inventing similarity, identity, quality or occlusion data. The configured
suggestion band discussed by the plan is `0.35–0.55`, but it is not a captured
value for this row.

| candidate → suggested | similarity | band | representative identity id | quality | occlusion score | status |
| --- | --- | --- | --- | --- | --- | --- |
| Justin Trudeau → Emma Watson | **NOT CAPTURED** | **NOT CAPTURED** | **NOT CAPTURED** | **NOT CAPTURED** | **NOT CAPTURED** | **PENDING** operator capture for C3 calibration |

The only captured identity evidence is the DOM description: the ground-truth
candidate is Justin Trudeau, the suggested person is Emma Watson, and both
displayed avatars are Justin Trudeau. No representative identity ID appears in
the supplied evidence.

## Dispatch recommendation

### Slice decision matrix

| slice | decision | basis from rebaseline | lane(s) |
| --- | --- | --- | --- |
| A1 | run | Defect 5 is reproduced as a sync Suggest `500`; current analysis identifies missing demand registration and typed `GpuRemoteAdapterError` handling. | `contracts`, `svc-demand`, `svc-cold-gpu` |
| A2 | run | Defect 8 persists; the route-family breaker and passthrough are the planned fix. Defect 6 remains a direct-route re-check. | `php-breaker-passthrough` |
| A3 | run | Defects 5 and 7 persist, and the UI must expose warming/retry state; Defect 6 remains unclosed pending route re-check. | `spa-description-service`, `spa-describe-client`, `spa-suggest-warming-timing`, UX consumers |
| B1 | run | No measured cold-start, queue, readiness or per-image timing was captured; the plan identifies this as an unimplemented acceptance metric, so it remains open work rather than a passed slice. | `contracts`, `timing-models`, `timing-repository`, `svc-instrumentation`, `svc-cold-gpu`, `svc-run-timing` |
| B2 | run | No timing evidence exists for Suggest or runs; timing display and evidence mapping remain open. | `php-breaker-passthrough`, `spa-describe-client`, `spa-suggest-warming-timing`, `spa-bulk-timing` |
| C1 | run | Defect 1 is reproduced on load. | `spa-naming-control` |
| C2 | run | Defect 3 is reproduced with the candidate rendered as its own representative. | `svc-suggestion-rep`, `spa-suggestion-cards` |
| C3 | run | Defect 2 is a recorded wrong-person suggestion; the required numeric row is pending and must be captured for calibration. | `calibration` |
| C4 | run after C3 acceptance | Defect 4 is a recorded occluded representative; calibrated factors must precede ranking changes. | `svc-rep-settings`, `svc-rep-quality` |
| D1 | drop pending operator re-check | No anchor-picker or undo-persistence observation is present in the supplied evidence, so this slice is not classified as a persisting live defect. | `spa-picker-undo` |
| D2 | drop pending contract acceptance | The plan explicitly blocks dispatch until API-R-23 supplies the numeric cap, bounded field, scope, typed error and boundary cases; no cap is inferred here. | `php-merge-cap` |

### Wave 1

Dispatch these lanes after this artifact is committed: `contracts`,
`spa-naming-control`, `svc-suggestion-rep`, `spa-description-service` and
`calibration`. Hold `php-merge-cap` until the accepted API-R-23 brief exists.
The later timing, service, PHP, SPA and representative-quality lanes follow the
slice matrix and artifact DAG; C4 remains downstream of accepted C3 evidence.

PERSISTING: A1,A2,A3,B1,B2,C1,C2,C3,C4
DROPPED: D1,D2
