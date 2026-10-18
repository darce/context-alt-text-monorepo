# GPUOPS-1 wave-1 lane DAG (GRPH-01 toposort, GRPH-31 critical path)

Generated 2026-09-06 from feature/gpuops-1 @ 9a13f62a3. 14 nodes, 14 edges, acyclic (GRPH-02 check passed). Two connected components (GRPH-06): the implementation component N0–N11 and the operator component N12; they join only at N13.

Edges exist only where an artifact moves between nodes (GRPH-32). Parallel lanes have frozen file-ownership contracts C1–C7 (GRPH-33/39) in the task plan.

```
N0 freeze contracts C1–C7 + briefs
├─ N1 L1 lifecycle: intent.py, controller/reaper/state_snapshot ─┐
├─ N2 L2 installer: --intent-dir, intent.path, single reaper ────┤
├─ N3 L3 service: gpu_intent.py writer, /scene/gpu/* ────────────┤
├─ N4 L4 PHP: acx/v1/recognition/gpu/* pass-through ─────────────┼─ N9 merge → feature/gpuops-1 ─ N10 review-slice ─ N11 close+merge main ─┐
├─ N5 L5 SPA: Settings › Burst GPU card + ux-map parity ─────────┤                                                                          ├─ N13 live smoke (operator)
├─ N6 L6 naming toggle: tenant flag authority, PHP proxy, form ──┤                                                                          │
├─ N7 L7 naming on GPU tier: worker + realizer provenance ───────┤   N12 operator reinstall units + redeploy compose (H-01/02/03/R3-01) ───┘
└─ N8 L8 naming provenance UI: apply view badge + types ─────────┘
```

| wave | nodes (width) |
|---|---|
| W0 | N0, N12 (2) |
| W1 | N1, N2, N3, N4, N5, N6, N7, N8 (8) |
| W2 | N9 (1) |
| W3 | N10 (1) |
| W4 | N11 (1) |
| W5 | N13 (1) |

Topological order: N0 -> N12 -> N1 -> N2 -> N3 -> N4 -> N5 -> N6 -> N7 -> N8 -> N9 -> N10 -> N11 -> N13

Critical path (GRPH-31, est. minutes): N0 -> N5 -> N9 -> N10 -> N11 -> N13 = 260 min (N1 and N7 tie N5 at 90). Serial sum 800 min; parallel speedup 3.08x; max width 8 (one detached codex-remote process per lane, timeout 3400 s each).

| node | est min | owner | label |
|---|---|---|---|
| N0 | 15 | coordinator/local | freeze C1–C7, briefs, manifest, dispatch (this turn) |
| N1 | 90 | codex-remote gpt-5.6-luna max | L1 intent reader + controller semantics + state fields + contract doc |
| N2 | 75 | codex-remote gpt-5.6-luna max | L2 installer `--intent-dir`, `acx-gpu-intent.path`, drop cloud-init idle reaper, both-enabled test |
| N3 | 75 | codex-remote gpt-5.6-luna max | L3 intent writer, `/scene/gpu/status` + `/scene/gpu/intent`, schema |
| N4 | 45 | codex-remote gpt-5.6-luna max | L4 PHP controller + registration + unit tests |
| N5 | 90 | codex-remote gpt-5.6-luna max | L5 SPA card, hook, api module, mount, vitest, ux-map render |
| N6 | 75 | codex-remote gpt-5.6-luna max | L6 tenant naming routes, settings proxy field, option delete, form toggle |
| N7 | 90 | codex-remote gpt-5.6-luna max | L7 GPU-tier naming path pinned by tests, realizer provenance, dedup check |
| N8 | 60 | codex-remote gpt-5.6-luna max | L8 apply-view naming badge, types, PHP pass-through test |
| N9 | 20 | coordinator/local | merge L1–L8 into feature/gpuops-1 (`--no-ff`, autoStash off) |
| N10 | 60 | mixed | /wb-review-slice (1 local + N remote luna max, canon lenses per plan) |
| N11 | 15 | coordinator/local | close_check(enforce) + slice decision + merge main |
| N12 | 30 | operator | reinstall gpu-lifecycle units with aggregate load path + intent dir, redeploy prod/dev compose |
| N13 | 60 | operator + coordinator | live smoke: SPA Start → ready → named describe → Stop; EVID-1 bundle; `test_result` on merge SHA |

Edge rationale (GRPH-32): N0->N1..N8: frozen contracts + briefs; N1..N8->N9: lane diffs; N9->N10: merged branch under review; N10->N11: findings closed; N11->N13: deployed code; N12->N13: live units that can honour intents.

Non-overlap contracts (GRPH-33): N1 owns `infra/oci/gpu_lifecycle/**` + `docs/workbay/contracts/gpu-lifecycle.md`; N2 owns `scripts/deploy/gpu-lifecycle-install.sh`, `infra/oci/cloud-init.yaml`, `scripts/deploy/tests/test_gpu_lifecycle_*.py`, `test_cloud_init_*.py`; N3 owns `scene/application/gpu_intent.py`, `scene/interface_adapters/http/routers/gpu.py`, `api/main.py`, `packages/shared-contracts/schemas/scene-gpu-status.schema.json`; N4 owns `src/api/class-gpu-control-controller.php`, `src/api/class-api.php`, `tests/Unit/GpuControlControllerTest.php`; N5 owns `js/admin/api/gpuApi.ts`, `js/admin/pages/settings/GpuControlCard.tsx`, `useGpuControl.ts`, `js/admin/pages/SettingsPage.tsx`, `docs/ux-maps/gpu-operator-control.*`; N6 owns tenant naming routes under `recognition/interface_adapters/http/routers/`, `src/api/class-settings-controller.php`, `src/api/services/class-describe-media-service.php`, `js/admin/pages/settings/SettingsForm.tsx`, `settingsConstants.ts`, `useSettingsPageState.ts`, the settings API module; N7 owns `scene/application/describe_run_worker.py`, `naming_preview_service.py`, `scene/application/identity_merge/**`; N8 owns `js/admin/pages/DescribeRunApplyView.tsx`, `js/admin/api/describeApi.ts`. Shared frozen contract for all: C1 intent path `/run/acx-write/<ACX_ENV>/gpu-intent.json`, lifecycle flag `--intent-dir /run/acx-write`, C2 state fields, C3 routes.
