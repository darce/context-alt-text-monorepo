FINDINGS: [{"id":"GPUFLOW-1-UXSERVICE-R-01","severity":"low","file_path":"apps/prototype-wp-alt-context/docs/ux-maps/render_ux_maps.visible.json","line":16,"summary":"The delta changes a generated visible-projection snapshot outside the ux-service owned path list.","evidence":"The supplied delta changes render_ux_maps.visible.json lines 16-17, while the lane row owns only gpu-operator-control.uxmap.json and gpu-operator-control.md; render_ux_maps.py --check confirms freshness but does not transfer ownership."},{"id":"GPUFLOW-1-UXSERVICE-R-02","severity":"medium","file_path":"apps/prototype-wp-alt-context/docs/ux-maps/gpu-operator-control.uxmap.json","line":29,"summary":"The map introduces an unavailable action state and Start action that the shared status contract, fixture, and SPA cannot produce.","evidence":"The map adds unavailable to action_states and to act-gpu-start.when at lines 29 and 84. scene-gpu-status.schema.json:34-37 and gpuflow-service-states.json:2-33 define only unknown, stopped, starting, warming, ready, and degraded; description_service_unavailable is a typed Suggest 503, not a GPU status enum, and useGpuControl.ts:27-28 permits start only for stopped or degraded."},{"id":"GPUFLOW-1-UXSERVICE-R-03","severity":"medium","file_path":"apps/prototype-wp-alt-context/docs/ux-maps/gpu-operator-control.md","line":194,"summary":"The renamed stop flow still says Stop service is disabled while work is in flight, contradicting the deferred-stop contract and implementation.","evidence":"The map goal at line 10 says stop intent can be requested while busy and shutdown is deferred, but the changed flow at lines 194-198 disables Stop service on load.has_work. useGpuControl.ts:30-34 and :90-94 keep Stop available and model it as a deferred intent; the hook does not gate canStop on load.has_work."},{"id":"GPUFLOW-1-UXSERVICE-R-04","severity":"medium","file_path":"apps/prototype-wp-alt-context/docs/ux-maps/gpu-operator-control.md","line":27,"summary":"The map has one generic action sketch instead of the six state-specific A3 sketches needed to verify ETA, no-ETA, unknown, and operator-STOP behavior.","evidence":"The ux-service handoff requires six state sketches, but the delta supplies only one generic Settings sketch at lines 40-86. It lists ETA and Retry-After as data at line 27 without specifying starting-with-ETA, starting-without-ETA, ready, unknown/stale, or unavailable/operator-STOP copy and recovery in a state-specific inventory."}]
Verdict: pass_with_findings

# GPUFLOW-1 ux-service review

| scope | value |
| --- | --- |
| base | `b72d1776d` |
| tip | `7e848307b` |
| files | `apps/prototype-wp-alt-context/docs/ux-maps/gpu-operator-control.md`; `apps/prototype-wp-alt-context/docs/ux-maps/gpu-operator-control.uxmap.json`; `apps/prototype-wp-alt-context/docs/ux-maps/render_ux_maps.visible.json` (outside the owned list) |

The two canonical map sources reflect the Description Service rename and remain renderer-parity clean. The supplied delta also changes the generated visible snapshot, which is not in this lane's owned paths. The status/action review uses the shared GPU status schema, the six-state service fixture, the current settings hook, and the GPUFLOW-1 typed-error contract. The relevant canon checks are centralized state vocabulary (`[sr-007]`), distinct visual meaning for distinct states (`[PERC-02]`), status–predict–stop (`[INT-10]`/`[HAI-04]`), and visible progress for waits (`[INT-08]`).

## FINDINGS

### GPUFLOW-1-UXSERVICE-R-01 — low

- **File:line:** `apps/prototype-wp-alt-context/docs/ux-maps/render_ux_maps.visible.json:16-17`
- **Evidence:** The supplied delta changes the generated visible-projection hashes, while the lane row owns only `gpu-operator-control.uxmap.json` and `gpu-operator-control.md`. `render_ux_maps.py --check` confirms freshness but does not transfer ownership of the shared snapshot.
- **Impact:** An unlisted shared/generated path crosses the lane boundary and can create a shared-writer conflict or hide which lane is responsible for regenerating the snapshot. This is a scope/hygiene issue, not a semantic parity failure (`[REF-09]`).
- **Fix:** Keep the snapshot out of this lane's commit and have its designated writer regenerate it, or explicitly assign the snapshot and its dependency to one lane before merging.

### GPUFLOW-1-UXSERVICE-R-02 — medium

- **File:line:** `apps/prototype-wp-alt-context/docs/ux-maps/gpu-operator-control.uxmap.json:29,84` (Markdown projection: `gpu-operator-control.md:29,165`)
- **Evidence:** The map adds `unavailable` to `action_states` and advertises `Start service` for it. The shared `scene-gpu-status.schema.json:34-37` and the read-only `gpuflow-service-states.json:2-33` define only `unknown`, `stopped`, `starting`, `warming`, `ready`, and `degraded`. The GPUFLOW-1 contract uses `description_service_unavailable` as a typed Suggest 503 (`docs/workbay/contracts/image-description-api.md:279-289`), not as a `gpu_state.state`; `useGpuControl.ts:27-28` also permits Start only for `stopped` or `degraded`.
- **Impact:** The canonical map promises a Settings branch and action that no shared wire value, fixture, or current SPA state machine can render or exercise. This violates the centralized status vocabulary rule (`[sr-007]`) and makes downstream UI/QA parity over-claim an operator recovery path.
- **Fix:** Either keep unavailable as the typed Suggest error/recovery state owned by the Suggest/public maps, or add it consistently to the shared status contract, centralized presentation enum, fixture, and Settings implementation before mapping it. Do not add an isolated map-only state (`[PERC-02]`, `rg-015`).

### GPUFLOW-1-UXSERVICE-R-03 — medium

- **File:line:** `apps/prototype-wp-alt-context/docs/ux-maps/gpu-operator-control.md:194-198` (JSON source: `gpu-operator-control.uxmap.json:110-113`)
- **Evidence:** The map goal says “Stop intent can be requested while busy and shutdown is deferred until idle” at line 10, but the renamed flow says `load.has_work → Stop service disabled with reason` and waits for the run to finish. The current hook keeps Stop available for `starting|warming|ready|degraded` (`useGpuControl.ts:30-34`) and models STOP as an intent that “can be deferred by active work” (`:90-94`); it does not gate `canStop` on `load.has_work`.
- **Impact:** The map directs the downstream UI and operator smoke toward blocking the safe override precisely during active work, contradicting the stated lifecycle behavior and `[INT-10]`/`[HAI-04]` status–predict–stop contract.
- **Fix:** Document Stop service as available while work is in flight, with confirmation copy that it will be honored after the run becomes idle and a pending intent shown until then; test the deferred path rather than a disabled control.

### GPUFLOW-1-UXSERVICE-R-04 — medium

- **File:line:** `apps/prototype-wp-alt-context/docs/ux-maps/gpu-operator-control.md:27,40-86`
- **Evidence:** The ux-service handoff requires six state sketches, but the delta supplies only one generic Settings sketch with action rows. It says ETA and Retry-After are data at line 27 without a state-specific inventory for starting-with-ETA, starting-without-ETA, ready, unknown/stale, or unavailable/operator-STOP copy and recovery. A long warm-up needs visible progress and a predictable next action (`[INT-08]`), while distinct critical states need distinct cues (`[PERC-02]`).
- **Impact:** The canonical map remains too underspecified for downstream QA to verify A3's warming ETA/no-ETA behavior and the unknown-versus-operator-STOP distinction; a generic action table can pass parity while missing the required operator copy.
- **Fix:** Add the six canonical state sketches (or an equivalent machine-readable state matrix plus Markdown projection), including the wire-backed ETA/Retry-After behavior, explicit no-ETA unavailable copy, stale/unknown refresh recovery, and the action available in each state.

## Re-review r4 (7e848307b..5655adc8f)

VERIFIED: {"GPUFLOW-1-UXSERVICE-R-02":"fixed","GPUFLOW-1-UXSERVICE-R-03":"fixed","GPUFLOW-1-UXSERVICE-R-04":"partially_fixed"}
FINDINGS: [{"id":"GPUFLOW-1-UXSERVICE-R-05","severity":"high","file_path":"apps/prototype-wp-alt-context/docs/ux-maps/gpu-operator-control.md","line":10,"summary":"The fix maps Retry-After onto description_service_unavailable on degraded/unknown Settings states even though the typed API contract forbids that header on unavailable errors.","evidence":"The fix adds 'degraded copy may include typed description_service_unavailable Retry-After' at gpu-operator-control.md:10 and repeats it at :27 and :337; image-description-api.md:287-296 says Retry-After is required only for description_service_starting and must be absent on every other typed error, including description_service_unavailable."},{"id":"GPUFLOW-1-UXSERVICE-R-06","severity":"medium","file_path":"apps/prototype-wp-alt-context/docs/ux-maps/gpu-operator-control.md","line":10,"summary":"The deferred-stop map promises a pending count that the GPU load wire contract and current card do not carry.","evidence":"The fix requires 'Stopping after current work (N items left)' at gpu-operator-control.md:10,34,203,207,282-287 and gpu-operator-control.uxmap.json:32,111-113, but GpuLoadSnapshot exposes only has_work/written_at/fresh at gpuApi.ts:66-70 and intentLabel renders only a boolean-work message at GpuControlCard.tsx:86-105; no N is available to render without inventing metadata (rg-015)."},{"id":"GPUFLOW-1-UXSERVICE-R-07","severity":"medium","file_path":"apps/prototype-wp-alt-context/docs/ux-maps/gpu-operator-control.uxmap.json","line":89,"summary":"The fix splits Refresh into a primary unknown-state action and a tertiary live-state action, but the SPA still renders one unconditional tertiary Refresh button.","evidence":"The changed action rows gpu-operator-control.uxmap.json:89-90 assign primary to unknown and tertiary to other states; GpuControlCard.tsx:311-313 always renders one Refresh button with acx-button--tertiary and no state-specific hierarchy, so the new action matrix is not implementable/parity-verifiable."},{"id":"GPUFLOW-1-UXSERVICE-R-08","severity":"medium","file_path":"apps/prototype-wp-alt-context/js/admin/pages/settings/__tests__/GpuControlCard.test.tsx","line":50,"summary":"The deferred-stop fix is not covered by the representative card test: its helper still disables Stop during work and the test asserts the superseded behavior.","evidence":"The fix says Stop stays available and never disabled in gpu-operator-control.md:203-208 and gpu-operator-control.uxmap.json:58-65, but the existing test helper sets canStop to false when load.has_work at GpuControlCard.test.tsx:50-56 and the test at :179-188 asserts aria-disabled=true. The test therefore bypasses the production hook's deferred-stop behavior and cannot protect the fixed map contract."}]

| finding | verdict | evidence |
| --- | --- | --- |
| GPUFLOW-1-UXSERVICE-R-02 | fixed | The JSON hunk removes `unavailable` from `action_states` and from `act-gpu-start.when` (`gpu-operator-control.uxmap.json:29,84`); the Markdown hunk also states that `gpu_state` has no unavailable member and treats the typed error as copy, not a state (`gpu-operator-control.md:337`). |
| GPUFLOW-1-UXSERVICE-R-03 | fixed | The goal, stop confirmation, flow, and JSON steps now keep Stop available during `load.has_work` and describe a deferred intent (`gpu-operator-control.md:10,203-207,282-287`; `.uxmap.json:111-113`), removing the old disabled/wait-for-run branch. |
| GPUFLOW-1-UXSERVICE-R-04 | partially_fixed | The fix adds six sketches (`gpu-operator-control.md:84-173`) covering stopped, ETA/no-ETA startup, ready, unknown/stale, and degraded, but it supplies no state-specific unavailable/operator-STOP sketch; it only says operator STOP is a reason (`:337`). The new unavailable/Retry-After wording is also invalid as recorded in R-05. |

### FINDINGS

#### GPUFLOW-1-UXSERVICE-R-05 — high

- **File:line:** `apps/prototype-wp-alt-context/docs/ux-maps/gpu-operator-control.md:10,27,337` (JSON source: `gpu-operator-control.uxmap.json:9,21,135`)
- **Evidence:** The fix says degraded/unknown Settings copy may include typed `description_service_unavailable` plus `Retry-After`, and the degraded sketch says “retry in 15s.” The shared API contract says `Retry-After` is required only on `description_service_starting` and must be absent on all other typed errors, including `description_service_unavailable` (`docs/workbay/contracts/image-description-api.md:287-296`).
- **Impact:** The canonical map now teaches the SPA to consume a header the unavailable contract explicitly forbids, creating a release-facing error-contract break and an impossible recovery branch (`rg-015`).
- **Fix:** Keep `description_service_unavailable` copy separate from Retry-After; reserve the header/countdown for `description_service_starting` and document operator-STOP/stale recovery without inventing a retry value.

#### GPUFLOW-1-UXSERVICE-R-06 — medium

- **File:line:** `apps/prototype-wp-alt-context/docs/ux-maps/gpu-operator-control.md:10,34,203,207,282-287` (JSON source: `gpu-operator-control.uxmap.json:32,111-113`)
- **Evidence:** The new deferred-stop copy promises `Stopping after current work (N items left)`. The read-only GPU load contract contains only `has_work`, `written_at`, and `fresh` (`js/admin/api/gpuApi.ts:66-70`), while `intentLabel` can only render the generic boolean-work message (`GpuControlCard.tsx:86-105`).
- **Impact:** The map requires a count that cannot arrive from the wire, so a downstream UI must either omit required copy or fabricate metadata, violating `rg-015`.
- **Fix:** Use the available boolean copy (“stops after the current work finishes”) or add and contract-test an upstream count before mapping it.

#### GPUFLOW-1-UXSERVICE-R-07 — medium

- **File:line:** `apps/prototype-wp-alt-context/docs/ux-maps/gpu-operator-control.uxmap.json:89-90` (Markdown projection: `gpu-operator-control.md:257-258`)
- **Evidence:** The fix introduces `act-gpu-refresh` as a primary action for `unknown` and `act-gpu-refresh-live` as a tertiary action for live states. The SPA still renders one unconditional tertiary Refresh button (`js/admin/pages/settings/GpuControlCard.tsx:311-313`) with no state-dependent hierarchy.
- **Impact:** The new action matrix is not represented by the implementation; parity can pass while the unknown recovery is not the promised primary action.
- **Fix:** Either document one shared Refresh hierarchy or implement/test the unknown-versus-live hierarchy before retaining two action IDs.

#### GPUFLOW-1-UXSERVICE-R-08 — medium

- **File:line:** `apps/prototype-wp-alt-context/js/admin/pages/settings/__tests__/GpuControlCard.test.tsx:50-56,179-188`
- **Evidence:** The fix explicitly says Stop remains available while work is in flight and is never disabled (`gpu-operator-control.md:203-208`; `.uxmap.json:58-65`). The card test helper still computes `canStop` as false when `load.has_work`, and its test asserts `aria-disabled=true`, bypassing the production hook's deferred-stop behavior.
- **Impact:** The existing representative test encodes the superseded blocked-stop UX, so it cannot detect regression to the fixed deferred intent and may force downstream implementations back to the old behavior.
- **Fix:** Drive the card test through the real hook or update its fixture to keep Stop actionable and assert the deferred/pending copy after confirmation.

Verdict: fail

## Re-review r5 (5655adc8f..64b8ce929)

VERIFIED: {"GPUFLOW-1-UXSERVICE-R-04":"fixed","GPUFLOW-1-UXSERVICE-R-05":"fixed","GPUFLOW-1-UXSERVICE-R-06":"fixed","GPUFLOW-1-UXSERVICE-R-07":"fixed"}
FINDINGS: []

| finding | verdict | evidence |
| --- | --- | --- |
| GPUFLOW-1-UXSERVICE-R-04 | fixed | The Markdown purpose hunk expands the inventory to seven sketches and the added `stopped by operator` block is followed by the existing starting-with-ETA, starting-without-ETA, ready, unknown/stale, and degraded sketches (`gpu-operator-control.md:27,100-185`); the JSON purpose hunk mirrors the same state-specific inventory (`gpu-operator-control.uxmap.json:21`). This supplies the explicit long-wait and state-cue surfaces required by `[INT-08]` and `[PERC-02]`. |
| GPUFLOW-1-UXSERVICE-R-05 | fixed | The fix removes the degraded/unknown `Retry-After` wording and the invented retry countdown, replacing it with `Service unavailable. Start service to retry.` (`gpu-operator-control.md:10,27,173-185`; JSON `:9,21`). The closing contract note now reserves `Retry-After` for `description_service_starting` (`gpu-operator-control.md:348`; JSON `:134`), so the map no longer teaches the forbidden unavailable-error header. |
| GPUFLOW-1-UXSERVICE-R-06 | fixed | Every deferred-stop phrase in the Markdown and JSON hunks drops `N items left` and now says `Stopping after the current work finishes until idle` (`gpu-operator-control.md:10,34,203-207,293-298,330,337`; JSON `:9,32,58,111-113`). The map therefore asks only for the boolean work signal available on the wire, rather than inventing a count (`[INT-10]`). |
| GPUFLOW-1-UXSERVICE-R-07 | fixed | The JSON hunk removes the separate live Refresh action and makes one `act-gpu-refresh` tertiary action apply always (`gpu-operator-control.uxmap.json:89-90`); the Markdown action table and parity index make the same one-action change (`gpu-operator-control.md:269,325`). This matches the SPA's single unconditional tertiary Refresh control (`GpuControlCard.tsx:311-313`) and removes the prior split-action parity mismatch (`[INT-10]`). |

### FINDINGS

No new findings in this fix delta after excluding the already-open generated-registry, stale/unknown action, operator-STOP presentation, ETA wire, and test-coverage items from the handoff context.

Verdict: pass
