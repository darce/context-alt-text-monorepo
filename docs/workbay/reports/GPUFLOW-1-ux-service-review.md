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
