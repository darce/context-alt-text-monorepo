# Task Plan — GPUOPS-1

> **Metadata**
>
> - **Date**: 2026-09-06
> - **Project**: context-alt-text-monorepo
> - **Task ID**: GPUOPS-1 (epic E23 GPUOPS, [gpu-operator-control-and-named-captions-epic.md](../../epics/v0.5.0/gpu-operator-control-and-named-captions-epic.md))
> - **Branch / worktree**: `feature/gpuops-1` · `context-alt-text-monorepo-gpuops-1` · lanes `feature/gpuops-1-<lane>`
> - **Design source**: [gpu-lifecycle contract](../../workbay/contracts/gpu-lifecycle.md), [describe-gpu-tier ux-map](../../../apps/prototype-wp-alt-context/docs/ux-maps/describe-gpu-tier.md), new [gpu-operator-control ux-map](../../../apps/prototype-wp-alt-context/docs/ux-maps/gpu-operator-control.md), lane DAG [GPUOPS-1-wave1-dag.md](lanes/GPUOPS-1-wave1-dag.md)

## Objective

Give the WordPress operator explicit, safe start/stop/auto control of the A10 burst GPU from the admin SPA, keep every existing automatic lifecycle guarantee intact, make one unit own the reaper, and carry labelled face-cluster names into captions on both tiers with a single authority toggle and visible provenance.

## Problem statement

Inventory (2026-09-06, feature/gpuops-1 @ 9a13f62a3):

- The lifecycle is timer-driven only. `infra/oci/gpu_lifecycle` starts on `has_work` and reaps on idle or lease cap. No UI, PHP route, service route or CLI flag lets an operator request a start or stop. The describe-gpu-tier ux-map left this as open question HAI-04.
- The live safety net is down for operator-only reasons: the units on acx-backend still pass the retired `--load-json /run/acx/describe-load.json` path and lack the flock and running-since lease, and prod compose does not mount the load path. Both STOP arms are non-functional live. These are OPSGPU-H-01/H-02/H-03/R3-01 in handoff under MAINT-reap-20260906 and require a VM reinstall the agent may not perform.
- `infra/oci/cloud-init.yaml` still defines and enables `acx-gpu-idle-reaper.timer` while the installer defines `acx-gpu-reap.timer` (OPSGPU-R3-02). Two reapers can race on the same instance.
- Names already reach `alt_text_draft` through `describe_run_worker._apply_naming_preview`, but the gate is split across a service tenant flag with no setter and a PHP option with no UI. The GPU remote adapter yields no phrase boxes, so the positional fallback realizer is the only path on the GPU tier and it is untested there. The apply view shows no naming provenance.

## Frozen contracts (GRPH-33, GRPH-39)

Lanes implement against these; a lane that needs to change one stops and reports instead of editing it.

### C1 Operator intent file

Path `/run/acx-write/<ACX_ENV>/gpu-intent.json`, `ACX_ENV ∈ {dev, staging, prod}`. Single writer: the description service (`scene/application/gpu_intent.py`, same fence-lock + atomic-rename pattern as `describe_load.write_load_snapshot`). Mode 0o660, group-readable by the lifecycle user.

```json
{
  "schema_version": 1,
  "action": "start | stop | auto",
  "requested_at": "2026-09-06T22:10:00Z",
  "expires_at": "2026-09-06T22:40:00Z",
  "ttl_seconds": 1800,
  "requested_by": "opaque operator label",
  "nonce": "uuid4"
}
```

Lifecycle semantics (`--intent-dir /run/acx-write`, aggregate over `*/gpu-intent.json`, newest unexpired `requested_at` wins, tie → `stop`):

| intent | START arm | STOP arm |
| --- | --- | --- |
| absent / expired / malformed / `auto` | unchanged: start when `has_work` | unchanged: idle reap, lease cap, boot-failure fallback |
| `start` (unexpired) | START allowed with no work; honoured at most once per nonce (RES-01) | idle reap suppressed; **lease cap still stops** (RES-10); boot-failure fallback unchanged |
| `stop` (unexpired) | START suppressed even with work | STOP when `has_work` is false; when work is in flight publish `intent_status = blocked_work_in_flight` and re-evaluate next cycle |

Malformed intent is logged at WARNING with the parse error and treated as `auto` (AGT-10, CAL-02). TTL clamp lives in the service: default 1800 s, min 60 s, max 7200 s.

### C2 `gpu-state.json` additive fields

Writer unchanged (lifecycle only). Existing readers ignore unknown keys. Added:

| field | type | meaning |
| --- | --- | --- |
| `intent` | `start\|stop\|auto` | effective intent this cycle |
| `intent_expires_at` | iso8601 or null | from the winning intent |
| `intent_status` | `none\|pending\|honoured\|blocked_work_in_flight\|expired` | what the controller did with it |
| `honoured_nonce` | string or null | idempotency marker for START |
| `lease_expires_at` | iso8601 or null | `running_since + max_lease_seconds` |
| `instance_running_since` | iso8601 or null | from the running-since lease |
| `last_transition_reason` | `work\|operator\|idle\|lease_cap\|start_failed\|unknown` | why the last actuation happened |

### C3 Service REST (`scene/interface_adapters/http/routers/gpu.py`, mounted under `/scene`)

- `GET /scene/gpu/status` → 200 `{gpu_state: {...C2 fields...}, snapshot_age_seconds, snapshot_fresh, intent: {...C1...} | null, load: {has_work, written_at, fresh}, server_time}`. Missing snapshot → `gpu_state.state = "unknown"`, `snapshot_fresh = false`, still 200 (API-06, CAL-02).
- `POST /scene/gpu/intent` body `{action, ttl_seconds?, requested_by?}` → 202 with the same status body plus the written intent. Auth: `require_write_access`; demo-tier auth → 403 `gpu_control_forbidden`. Intent dir unwritable → 503 `gpu_intent_unavailable` (fail fast, RES-03). Validation errors → 422.
- Schema: `packages/shared-contracts/schemas/scene-gpu-status.schema.json`; contract doc section in `docs/workbay/contracts/gpu-lifecycle.md` (owned by L1; L3 links to it).
- Env: `ACX_GPU_INTENT_PATH` (default: sibling of the resolved load path, `gpu-intent.json`), `ACX_GPU_STATE_PATH` reuse existing.

### C4 PHP REST (`src/api/class-gpu-control-controller.php`)

- `GET acx/v1/recognition/gpu/status`, `POST acx/v1/recognition/gpu/intent`. Capability `manage_options`. Body and status code passed through verbatim (rg-015); PHP adds `requested_by = wp_get_current_user()->user_login` on POST. HTTP timeout 10 s (RES-02). Service unreachable → 502 `gpu_status_unavailable`.

### C5 SPA Settings › Burst GPU card

Per the `gpu-operator-control` ux-map. Reuse `gpuStatePresentation` vocabulary and chip. Poll `GET status` every 15 s while mounted, 5 s while `starting|warming` (INT-10). Start GPU = primary, costly, inline preview then confirm (INT-07, CARD-15). Stop GPU disabled with visible reason while `load.has_work` (rg-003 keeps Start reachable from zero state). Return to automatic always enabled when intent ≠ `auto`. One polite live region.

### C6 Naming authority

Service tenant flag `naming_agreement_enabled` is the only gate. New service routes `GET/PUT /recognition/tenant/naming-agreement` (tenant API key, `require_write_access` for PUT). PHP `/settings` exposes `allow_person_names` by proxying those routes; `acx_description_allow_person_names` option and its `get_option` read in `build_identity_context` are deleted, and the legacy `/recognition/describe` path must gate names by the tenant flag on the service side (verify; add if missing).

### C7 Naming provenance

`provenance.naming` already carries the pydantic dump. L7 adds `status: applied|disabled|skipped_budget|no_faces`, `realizer: grounded|positional_fallback|null` and `names_applied: [..]`; L8 renders a "Names: A, B (positional)" badge in the apply view and types it in `describeApi.ts`. PHP passes provenance through unchanged.

## Defect groups → lanes (GRPH-06 components first)

| group | defects | resolution owner |
| --- | --- | --- |
| D1 live unit drift | OPSGPU-H-01, H-02, H-03, R3-01 | operator (reinstall units, redeploy compose); DAG node N12; precondition for live smoke only |
| D2 reaper dual owner | OPSGPU-R3-02 | lane L2 |
| D3 no operator control | HAI-04 open question | lanes L1, L2, L3, L4, L5 |
| D4 naming gaps | no toggle authority, GPU tier untested, no provenance UI | lanes L6, L7, L8 |

## Lanes (one wave, width 8)

| lane | branch | owned surface | est |
| --- | --- | --- | --- |
| L1 `gpuops-1-lifecycle` | `feature/gpuops-1-lifecycle` | `infra/oci/gpu_lifecycle/{controller,reaper,state_snapshot}.py`, new `intent.py`, its tests, `docs/workbay/contracts/gpu-lifecycle.md` | 90 |
| L2 `gpuops-1-installer` | `feature/gpuops-1-installer` | `scripts/deploy/gpu-lifecycle-install.sh` (`--intent-dir`, `acx-gpu-intent.path`), `infra/oci/cloud-init.yaml` (remove idle-reaper), `scripts/deploy/tests/*gpu_lifecycle*`, `test_cloud_init*` | 75 |
| L3 `gpuops-1-service-api` | `feature/gpuops-1-service-api` | `scene/application/gpu_intent.py`, `scene/interface_adapters/http/routers/gpu.py`, `api/main.py` include line, schema, service tests | 75 |
| L4 `gpuops-1-php` | `feature/gpuops-1-php` | `src/api/class-gpu-control-controller.php`, `class-api.php` registration, `tests/Unit/GpuControlControllerTest.php` | 45 |
| L5 `gpuops-1-spa` | `feature/gpuops-1-spa` | `js/admin/api/gpuApi.ts`, `pages/settings/{GpuControlCard.tsx,useGpuControl.ts}`, `SettingsPage.tsx` mount, vitest, ux-map render parity | 90 |
| L6 `gpuops-1-naming-toggle` | `feature/gpuops-1-naming-toggle` | service tenant naming routes, `class-settings-controller.php`, `class-describe-media-service.php`, `settings/SettingsForm.tsx`, `settingsConstants.ts`, settings api module, tests | 75 |
| L7 `gpuops-1-naming-gpu-tier` | `feature/gpuops-1-naming-gpu-tier` | `describe_run_worker.py`, `naming_preview_service.py`, `identity_merge/*`, worker tests with GPU adapter fake | 90 |
| L8 `gpuops-1-naming-provenance-ui` | `feature/gpuops-1-naming-provenance-ui` | `DescribeRunApplyView.tsx`, `api/describeApi.ts` naming types, vitest, PHP provenance pass-through test | 60 |

Shared-file rule: no two lanes own the same file. `api/main.py` belongs to L3 only; `SettingsPage.tsx` to L5 only; `SettingsForm.tsx` to L6 only. Lane briefs: `docs/tasks/v0.5.0/lanes/GPUOPS-1-<lane>-brief.md`.

## Canon validation

| step | rule | how it is satisfied |
| --- | --- | --- |
| intent file | DATA-14 no dual writes | one writer per file; lifecycle never writes intent, service never writes state |
| intent TTL | RES-07 steady-state reclaimer | every intent expires; `auto` is the fixed point |
| start override | RES-10 fencing / lease | lease cap stops regardless of intent; nonce honoured once (RES-01) |
| stop with work | FLOW-08 late policy, HAI-04 override | stop is deferred not dropped; status shows `blocked_work_in_flight` |
| controller I/O | RES-02, RES-03, RES-13 | OCI CLI and readiness probe keep their timeouts; intent read has a named parse-failure path |
| path unit | RES-14 handshaking | `PathChanged` triggers one start cycle; flock serialises with the timer |
| single reaper | ARCH-13 architecture hoisting | test asserts cloud-init and installer cannot both enable a reaper |
| dead snapshot | OBS-08, CAL-02 | stale snapshot renders `unknown` with age, never last-known-good as fresh |
| SPA card | INT-07, INT-08, INT-10, CARD-09, CARD-15, COST-10, A11Y-18 | preview before commit, bounded waits with ETA, status–predict–stop, confirm on cost/irreversibility |
| naming gate | REF-09, DATA-14 | one authority flag; PHP option deleted |
| naming output | PROV-06, HAI-05, HAI-08, BOUND-* | provenance names the realizer; UI distinguishes grounded vs positional |
| tests | TEST-03, RES-16 | existing lifecycle behaviour pinned before intent logic; fallback paths exercised with fakes |

## Review gate (per lane, then branch)

`/wb-review-slice`: 1 local reviewer + remote codex-remote gpt-5.6-luna effort max reviewers, one per lens: `batch_or_stream_worker`+`concurrency_or_async_code` (L1, L3, L7), `release_or_deploy_change` (L2), `php_or_wordpress_change`+`security_sensitive_change` (L4, L6), `ui_or_frontend_change`+`ai_review_or_curation_ui` (L5, L8), `image_description_or_alt_text_change` (L7, L8). Prior-art packet from `find_related_prior_work` attached via `dispatch_lane_work(include_context_packet=True)`. Then `handoff_close_check(enforce=True)`, slice-complete decision, `git -c merge.autoStash=false merge --no-ff`.

## Non-goals

- Reinstalling units or redeploying compose on acx-backend (operator only).
- Any agent-initiated live START/STOP of the A10.
- DS-2B shared demo compute budget (partially landed as `DS2B-PM-S2-01`; separate task).
- Multi-instance GPU pools; the contract is single-instance today.
- Editing the four dirty config files on `main` or any peer-session branch.

## Checklist

- [ ] C1–C7 frozen and briefs written
- [ ] L1–L8 dispatched (codex-remote gpt-5.6-luna max, detached, one process per lane)
- [ ] each lane: tests green, review-slice pass, close_check(enforce) pass, merged to `feature/gpuops-1`
- [ ] branch review-slice, merge `main`
- [ ] operator precondition D1 confirmed done
- [ ] live smoke recorded as `test_result` on merge SHA
