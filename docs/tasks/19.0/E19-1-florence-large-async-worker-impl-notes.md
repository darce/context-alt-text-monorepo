# E19-1 — florence_large + async describe worker + OCI Florence: implementation notes

> **Metadata**
> - **Date**: 2026-06-15
> - **Author**: Claude Opus 4.8
> - **Task**: E19-1 (UI-wiring extension S11–S13)
> - **Status of deferred work**: design-ready, not implemented this turn

## What shipped this turn (S11–S12)

The `ACX_DESCRIPTION_ADAPTER` switch is now a 4-option profile (`scene/config/profiles.py`):

| Profile | Adapter kind | Model | This turn | Latency (OCI A1 CPU) |
| --- | --- | --- | --- | --- |
| `seeded` | `seeded` | none | **functional** (default) | <1 ms |
| `florence_small` | `local_cpu` | `microsoft/Florence-2-base-ft` @ `f6c1a258` | **functional**, inline off-thread | ~14 s mean (under 20 s) |
| `florence_large` | `local_cpu` | `microsoft/Florence-2-large-ft` | **stub** (fail-closed 503) | ~39 s (over budget) |
| `gpu_phi4` | `gpu` | `microsoft/Phi-4-multimodal-instruct` | **stub** (fail-closed 503) | ~900 s (GPU-only) |

Execution is **inline off-thread** (`VisualFactsService` runs the adapter via `asyncio.to_thread`, `visual_facts_service.py`). The WP Dashboard "Describe with AI" panel (S12) drives this through `POST acx/v1/recognition/describe`. `florence_small` (~14 s) is acceptable inline for the MVP demo; `florence_large`/`gpu_phi4` are deferred behind the work below.

This document is the implementation-ready spec for the three deferred pieces, in priority order for the demo.

---

## Part A — Run `florence_small` on the remote OCI A1 (the demo path)

The live `acx-backend:latest` image is torch-free (`Dockerfile` runtime stage installs only `.[face]`). To run Florence on the deployed A1 VM:

### A1. Add a `runtime-vlm` Docker stage (torch-bearing)

`Dockerfile` currently has `builder` → `runtime` (`.[face]`). Add a parallel torch-bearing path so the default image stays torch-free:

```dockerfile
# Stage 1b: Builder with the [vlm] extra (torch/transformers/einops/timm/accelerate)
FROM python:3.12-slim AS builder-vlm
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential cmake pkg-config libopenblas-dev liblapack-dev libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /build
COPY pyproject.toml .
RUN python -m venv /opt/venv && /opt/venv/bin/pip install --no-cache-dir --upgrade pip setuptools wheel \
    && /opt/venv/bin/pip install --no-cache-dir ".[face,vlm]"

# Stage 2b: runtime-vlm — same runtime layer, venv from builder-vlm
FROM python:3.12-slim AS runtime-vlm
# ... identical apt runtime libs + COPY app code as `runtime` ...
COPY --from=builder-vlm /opt/venv /opt/venv
# (same ENV/CMD as runtime; HF_HOME=/data/cache/huggingface_cache already set,
#  so the model downloads once to the persisted /data/cache volume)
```

Build + push the torch-bearing image under a distinct tag:

```bash
docker build --platform linux/arm64 --target runtime-vlm \
  --build-arg GIT_COMMIT_SHA=$(git rev-parse HEAD) \
  -t iad.ocir.io/idu2kqqe2jxy/acx-backend:florence .
docker push iad.ocir.io/idu2kqqe2jxy/acx-backend:florence
```

> Build cost: torch+transformers for aarch64 is large (~minutes, ~GB). Keep the default `:latest` (torch-free) as the recognition image; only the describe-serving container needs `:florence`.

### A2. Env on the deployed host (`/opt/acx-backend/.env` or demo secrets)

```bash
ACX_DESCRIPTION_ADAPTER=florence_small      # was local_cpu — renamed in S11
# Optional host caps (defaults shown):
ACX_VLM_MAX_IMAGE_EDGE_PX=1024
ACX_VLM_TIMEOUT_SECONDS=20
ACX_VLM_MAX_RSS_MB=6144
ACX_VLM_WORKER_CONCURRENCY=1
ACX_DESCRIPTION_TIMEOUT_SECONDS=180          # HTTP 504 ceiling incl. cold load
```

Model id/revision/decode-params are **not** env-driven anymore — they come from the `florence_small` `ProfileSpec`. To override the model deliberately, edit the registry, not env.

### A3. Compose + restart

Point the api container at `:florence` (e.g. `ACX_IMAGE_TAG=florence` if compose templates the tag, else edit `docker-compose.prod.yml`). `docker compose pull && up -d`. First describe request triggers a one-time ~11 s cold model load into `/data/cache/huggingface_cache` (persisted). WP needs no change — it already targets `ACX_RECOGNITION_URL` (e.g. `https://api.altcontext.com`).

### A4. Demo caveat (inline)

Inline means the HTTP request holds open ~14 s and competes with recognition on the 4-OCPU box. Acceptable for a controlled demo. Move to the async worker (Part C) before any real concurrency.

---

## Part B — Enable `florence_large` (quality ceiling, async-only)

`florence_large` is the quality winner on A1 (correctly IDs e.g. "dahlia"; no OD hallucination) but ~39 s/image → **must not run inline** (exceeds the 20 s bar and would block the event loop's thread pool under load). Enablement steps:

1. Pin the revision in `ProfileSpec(FLORENCE_LARGE).model_revision` (currently `None`; pin to the tested `microsoft/Florence-2-large-ft` commit at enablement for supply-chain reproducibility).
2. Flip `available=True` in the registry **only after Part C (async worker) exists** — otherwise inline 39 s will 504 / starve recognition.
3. Decode params already set in the spec: `num_beams=3`, `max_new_tokens=512`, tasks `<MORE_DETAILED_CAPTION>+<OD>`, edge 1024. (Lever: greedy `beams=1` + dropping `<OD>` cuts latency ~2× and removes the OD hallucination, at some recall cost — measure before changing.)
4. Provider provenance stays `local` (bytes never leave the boundary).

Until then, selecting `florence_large` returns a 503 whose detail names the async-worker requirement (surfaced in the WP panel).

---

## Part C — The async describe worker (deferred; the big piece)

Mirror the recognition scan worker. Reuse the pattern, **new tables** (description is media→alt-text, orthogonal to identity scan).

### C1. Pattern to mirror
- `recognition/worker/scan_worker.py` — `run_forever()` poll loop, `__aenter__/__aexit__` lifecycle, stale-reclaim + retry budget, `asyncio.Semaphore` concurrency bound. Launch: `python -m recognition.worker.scan_worker` (compose `worker` service in `docker-compose.prod.yml`).
- `recognition/infrastructure/repositories/scan_queue_repository.py` — the `WITH claimed AS (SELECT ... FOR UPDATE SKIP LOCKED LIMIT n) UPDATE ... RETURNING` claim CTE. Copy, adapt column names.
- `db/models/jobs.py` — `IdentityScanJob`/`IdentityScanJobItem` shape (status enum, attempts, started_at, last_error, pending index).

### C2. New files/seams
- `db/models/scene.py` — add `ImageDescribeJob` (parent: tenant_id, status, media_id, image_hash, profile, error, attempts, created/started/completed_at) + status index. Add to `001_identity_schema.py` baseline (greenfield — no new migration), `TENANT_TABLES`, `EXPECTED_SCHEMA_TABLES`, `DOWNGRADE_TABLE_ORDER`, RLS lists.
- `scene/application/describe_job_repository.py` — `enqueue(tenant, media_id, profile)`, `claim_pending(limit) [SKIP LOCKED]`, `mark_completed`, `mark_failed`, `reclaim_stale`.
- `scene/worker/describe_worker.py` — poll loop; on claim, build `VisualFactsService` (existing) with the configured profile adapter and persist into `image_descriptions` (existing cache table). No embedding-runtime init needed (Florence loads lazily on first describe). `worker_concurrency=1` from `VlmSettings`.
- `scene/worker/__init__.py`.
- `docker-compose.prod.yml` — add a `describe_worker` service: image `:florence`, `command: ["python","-m","scene.worker.describe_worker"]`, same env/volume as `worker`, `depends_on: postgres`.
- `scripts/start_prototype_local.sh` — optional `START_DESCRIBE_WORKER=1` nohup launcher (mirror `scan_worker`).

### C3. Route + WP contract change (enqueue/poll)
The `/scene/describe/multipart` route currently runs synchronously. For async profiles, add the deferred branch:
- Route: when the selected profile is async (`florence_large`, or `florence_small` under load), **enqueue** an `ImageDescribeJob` and return `202 Accepted` with `{ job_id, status: "pending" }` instead of the full envelope.
- New backend poll route `GET /scene/describe/jobs/{job_id}` → `{ status, result? }` where `result` is the full `VisualFactsResponse` once `completed`.
- WP: add a `describeJob` proxy + endpoint (`acx/v1/recognition/describe/jobs/{id}`); `useDescribeMedia` becomes enqueue-then-poll (React Query `useQuery` with `refetchInterval` until terminal). The `DescribePanel` already has loading/error states — add a "queued… / generating…" progress state keyed on job status.
- Keep the **synchronous** path for `seeded` (instant) and optionally `florence_small` (interactive) via a per-profile `async` flag on `ProfileSpec`.

### C4. Tests
- Repository: enqueue→claim (SKIP LOCKED, single-claim under concurrency)→complete; stale reclaim; retry budget. (aiosqlite for unit, real PG for the claim semantics.)
- Worker: claimed job → `VisualFactsService` → row persisted; failure → `mark_failed` + retry/terminal.
- Route: async profile → 202 + job_id; poll → pending then completed with the 15-field envelope; sync profile unchanged.
- WP: enqueue→poll→render; surfaces failed-job message.

---

## Part D — `gpu_phi4` (stub; needs a GPU host)

`Phi-4-multimodal-instruct` is the overall quality ceiling but ~900 s/image on A1 CPU (~60× Florence; bf16 emulated on Neoverse-N1) → **GPU-only**. Enablement is out of scope for the A1 demo:
- Needs a GPU host (the archived recognition T4 config is the reference: eager attn, `num_crops=4`, greedy, factual-alt-text prompt).
- Add a `Phi4GpuDescriptionAdapter` (kind `gpu`) behind the same protocol; flip `ProfileSpec(GPU_PHI4).available=True` once a GPU backend exists; runs through the async worker (Part C), never inline.
- Until then the profile is a fail-closed stub returning a 503 that names the GPU requirement.

---

## Config switch reference

`scene/config/profiles.py` is the single source of truth. `get_description_adapter()` (`scene/interface_adapters/http/deps.py`) resolves profile → adapter; unavailable profiles return `UnavailableDescriptionAdapter` raising `DescriptionAdapterUnavailableError` → route 503. The operator env value renamed `local_cpu` → `florence_small` (greenfield, no migration).
