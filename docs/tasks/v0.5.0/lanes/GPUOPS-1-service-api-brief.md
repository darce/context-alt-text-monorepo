# GPUOPS-1 lane L3 — description service: intent writer and GPU status API

Branch `feature/gpuops-1-service-api`, worktree `context-alt-text-monorepo-gpuops-1-service-api`. Owns `apps/prototype-description-service/scene/application/gpu_intent.py`, `apps/prototype-description-service/scene/interface_adapters/http/routers/gpu.py`, the one `include_router` line in `apps/prototype-description-service/api/main.py`, `packages/shared-contracts/schemas/scene-gpu-status.schema.json`, and your new tests.

## Goal

Implement contract C3: `GET /scene/gpu/status` and `POST /scene/gpu/intent`, backed by a single-writer intent file (contract C1) written with the same fence-lock and atomic-rename discipline as the load snapshot.

## Current anchors

- `scene/application/describe_load.py`: `_open_load_snapshot_fence` :59 (lock file `<name>.lock`, mode 0o660), `write_load_snapshot` :181 (threading lock + fcntl flock + atomic rename), `resolve_load_path` :83. Mirror this exactly for the intent writer; do not import private helpers, copy the pattern.
- `api/main.py` :301-309: `app.include_router(...)` block; scene routers are mounted with `prefix="/scene"`.
- `scene/interface_adapters/http/routers/describe.py`: `require_write_access` dependency, demo-quota dependency `maybe_consume_demo_quota` and `auth` object; find how the auth object exposes the demo tier and reuse it for the 403.
- The existing `gpu_state` reader used by describe runs (grep `gpu-state.json` / `GPU_STATE` under `scene/`) — reuse it, do not write a second parser.

## Deliverables

1. `gpu_intent.py`: `IntentAction(StrEnum)`, `write_gpu_intent(path, *, action, ttl_seconds, requested_by, now) -> OperatorIntent` (uuid4 nonce, `schema_version: 1`, clamp TTL to [60, 7200], default 1800, mode 0o660, fence lock, atomic rename), `read_gpu_intent(path) -> OperatorIntent | None` (malformed → `None` plus WARNING). Path from `ACX_GPU_INTENT_PATH`, default `gpu-intent.json` beside the resolved load path.
2. `routers/gpu.py`: `GET /gpu/status` (any authenticated key) returning `{gpu_state, snapshot_age_seconds, snapshot_fresh (≤120 s), intent, load: {has_work, written_at, fresh}, server_time}`; missing snapshot → `gpu_state.state = "unknown"`, still 200 (API-06, CAL-02). `POST /gpu/intent` body `{action, ttl_seconds?, requested_by?}` → 202 with the same body plus the written intent; `require_write_access`; demo tier → 403 `gpu_control_forbidden`; unwritable dir → 503 `gpu_intent_unavailable`; invalid action or TTL type → 422. Pydantic response models; no ad-hoc dicts.
3. `api/main.py`: one line, `app.include_router(gpu_router, prefix="/scene")`, adjacent to the existing scene router.
4. `packages/shared-contracts/schemas/scene-gpu-status.schema.json` describing the status body, with `gpu_state.state` enum reusing the vocabulary in `scene-describe-run.schema.json` :79.

## Tests

Place them beside the existing scene router tests (find with `grep -rl "describe/run" apps/prototype-description-service/tests`). Cover: write/read round trip and clamp; malformed file → None + warning; GET with missing snapshot, stale snapshot, fresh snapshot; POST start/stop/auto → 202 and file content; demo key → 403; unwritable dir → 503; 422 on bad body. Run with `cd apps/prototype-description-service && python -m pytest <your test files> -q -p no:cacheprovider`.

## Non-goals

Lifecycle consumption of the file (L1), PHP (L4), SPA (L5), tenant naming routes (L6).
