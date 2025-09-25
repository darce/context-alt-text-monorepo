# Recognition Service

InsightFace-only FastAPI service that powers Context Alt Text’s face detection, embedding, and roster matching. This document consolidates all instructions (local dev + Hugging Face deployment) and supersedes the older `recognition/README.md`.

---
## 1. Architecture Overview

```
Clients (WordPress plugin, CLI, HF Space ingress)
        │
        ▼
FastAPI app (/api/v0/analyze-scene, /embeddings, /service/info, /health, /roster)
        │
        ▼
SceneAnalysisService ──► FaceRecognitionService (InsightFace) ──► EmbeddingRouter
        │                        │
        │                        └─ InsightFaceAdapter (SCRFD + ArcFace)
        └─ YOLOAdapter / Phi3CaptionAdapter (caption disabled for MVP)

RosterService ──► File storage + embeddings JSON
StartupManager ──► warms InsightFace + embeddings cache
```

- **Recognition only** for MVP: InsightFace `buffalo_l` model (detection + embeddings) with cosine similarity roster matching.
- **REST contract** preserved: WordPress client calls the same endpoints, now returning JSON payloads defined in `api/examples/`.
- **Tests** live under `tests/`; `test_api_contract.py` validates DTO examples consume the same JSON fixtures as the plugin.

### Architecture Pattern

The service retains a ports-and-adapters (hexagonal) structure:

- **Ports (interfaces)** live in `analysis/ports` and `recognition_core/domain/interfaces.py`.
- **Adapters** implement those ports (YOLO object detector, Phi-3 caption generator, InsightFace recognition, embedding router).
- **Core services** (e.g., `SceneAnalysisService`, `FaceRecognitionService`) orchestrate the adapters and expose domain logic to FastAPI routes.

Swapping inference models now requires implementing a new adapter that satisfies the relevant port—no changes to the API layer or orchestration classes. Captioning and recognition can evolve independently by introducing additional adapters and registering them through the startup factory.

---
## 2. Local Quickstart (Recognition Only)

```bash
cd apps/recognition-service

# 1. Pin pyenv to Python 3.10.17 so `python` resolves correctly
pyenv virtualenv 3.10.17 recognition-service-env   # create once
pyenv shell recognition-service-env                # activate for current session

# 2. Install dependencies and launch the API (Apple Silicon helper included)
./scripts/start_recognition_local.sh start

# Optional: skip dependency installation on subsequent runs
SKIP_INSTALL=1 ./scripts/start_recognition_local.sh start

# Optional: override defaults
# HOST=127.0.0.1 PORT=8000 LOCAL_CACHE_ROOT=/Volumes/Butter ./scripts/start_recognition_local.sh start

# Stop the service (best effort)
./scripts/start_recognition_local.sh stop
```

Offline starts are supported: the helper skips dependency installation when `pypi.org` is unreachable so previously provisioned environments boot without a network connection. Use `FORCE_INSTALL=1 ./scripts/start_recognition_local.sh install` to retry once you are back online (set `ASSUME_OFFLINE=1` to simulate the offline branch during testing).

Verify the endpoints (examples in `api/examples/`):

- `POST http://localhost:7860/api/v0/analyze-scene`
- `POST http://localhost:7860/api/v0/embeddings`
- `GET  http://localhost:7860/api/v0/service/info`
- `GET  http://localhost:7860/api/v0/health`

InsightFace weights download on first run. Adjust model/device/thresholds in `recognition_core/config/settings.yaml` or override via `RECOG_SETTINGS`.

---
## 3. Deploying to Hugging Face Spaces (Recognition MVP)

Only the recognition stack ships today. Caption generation will be enabled later.

1. **Create a Docker Space**
   ```bash
   huggingface-cli repo create <user>/context-alt-text-recognition --type space --sdk docker
   ```
2. **Push the app**
   ```bash
   git remote add hf https://huggingface.co/spaces/<user>/context-alt-text-recognition
   git push hf main
   ```
3. **Configure environment variables**
   - `RECOG_SETTINGS` (optional) to point at a custom settings file.
   - Any private Hugging Face tokens if you pull gated weights.
4. **Smoke-test the deployment** using the same four endpoints above. Share the Space URL with the WP team only after `/api/v0/health` and `/api/v0/service/info` succeed.

---
## 4. Configuration (Pydantic Settings)

`recognition_core/config/__init__.py` loads `recognition_core/config/settings.yaml` (override via `RECOG_SETTINGS`). Key sections:

```yaml
insightface:
  model_name: "deepinsight/insightface-scrfd-arcface-w600k"
  device: "auto"           # auto, cpu, cuda, mps
  cache_dir: "/tmp/insightface_models"

recognition:
  default_threshold: 0.45
  max_faces_per_image: 10

embedding_router:
  embeddings_file: "/roster/data/insightface_w600k_embeddings.json"
  auto_reload: true
  reload_interval: 30

cache:
  hf_home: null
  hf_datasets_cache: null
  torch_home: null

caption_generator:
  type: phi3  # options: phi3, mock, or custom
  config:
    model_id: microsoft/Phi-3.5-vision-instruct
    device: auto
    class_path: null

# Example custom adapter (optional)
# caption_generator:
#   type: custom
#   class_path: "analysis.adapters.openai_caption_adapter.OpenAICaptionAdapter"
#   config:
#     init_kwargs:
#       api_key: "${OPENAI_API_KEY}"
#       model: "gpt-4o-mini"
```

Flash Attention + caption models are still in the tree for future phases (see the “Flash Attention Configuration” section below), but they are disabled by default.

Cache directories (`HF_HOME`, `HF_DATASETS_CACHE`, `TORCH_HOME`) must be defined either in `settings.yaml` (`cache.*`) or via environment variables (e.g., `.env`, deployment secrets). If a value is missing the service aborts during startup, ensuring configuration gaps are caught immediately.

This removes the need to hard-code cache paths in shell profiles while keeping the configuration canonical per environment.

---
## 5. API Reference (JSON version)

All DTO examples live in `api/examples/`.

| Endpoint | Description |
| --- | --- |
| `POST /api/v0/analyze-scene` | Accepts `AnalyzeSceneRequest` JSON and returns a full scene context (objects, entities, roster matches). |
| `POST /api/v0/embeddings` | Returns embeddings + similarity matches for a single image (supports roster onboarding). |
| `GET /api/v0/service/info` | Model metadata (model name, device, thresholds, loaded entities). |
| `GET /api/v0/health` | Lightweight readiness check. |
| `/api/v0/roster/*` | Roster CRUD + sync (see historical docs under `recognition_core/README` for legacy details). |

Use the JSON fixtures under `api/examples/` when wiring the WordPress client and contract tests.

### Roster API Notes

- `POST /api/v0/roster` accepts JSON payloads containing precomputed embeddings (obtained via `/api/v0/embeddings`). Each successful call recomputes the aggregate embedding and persists it for the recognition service.
- `POST /api/v0/roster/{unique_id}/embeddings` appends a new reference embedding to an existing identity. Additional embeddings are averaged, which typically reduces noise and improves InsightFace match confidence.
- `DELETE /api/v0/roster/{unique_id}` removes an identity and the embedding store is refreshed immediately so subsequent recognition calls pick up the change.

### Health & Operations

- `GET /api/v0/health` provides a lightweight readiness probe suitable for load balancers, ELB targets, or Kubernetes liveness/readiness checks.
- `GET /api/v0/service/info` returns detailed runtime metadata (model name, device, thresholds, loaded roster counts) for dashboards and incident triage.
- `POST /api/v0/service/reload-embeddings` hot-reloads roster data; call it from automation after out-of-band roster updates to confirm the cache refresh path.

Container health checks can curl the readiness endpoint directly:

```yaml
healthcheck:
  test: ["CMD", "curl", "-f", "http://localhost:8000/api/v0/health"]
  interval: 30s
  timeout: 10s
  retries: 3
```

Monitoring systems ingesting JSON (Prometheus pushgateway sidecars, lightweight cron jobs, etc.) can re-use these endpoints without additional dependencies. For smoke testing, run `pytest tests/integration/test_api_endpoints.py -v` and `pytest tests/unit/test_scene_analysis_service.py -v` after setting `CACHE_DIR` so the service can locate model caches.

---
## 6. Development Guide

### Dependency management (pip-tools)

- Install pip-tools once per environment: `python -m pip install pip-tools`.
- Sync the local runtime + dev tooling with `./scripts/sync_local_env.sh`. The helper:
  - Invokes `scripts/install_insightface_mac.sh` automatically on Apple Silicon so `insightface` builds with the correct SDK headers.
  - Runs `pip-sync requirements_local.txt requirements_local_dev.txt`, keeping the virtualenv aligned with the checked-in requirement files.
- Pass alternative requirement files if needed (for example, `./scripts/sync_local_env.sh requirements_remote_main.txt`). The script validates paths relative to `apps/recognition-service/` before delegating to `pip-sync`.

`pip install -r …` continues to work for ad-hoc installs, but the pip-tools flow is preferred because it removes packages that are no longer declared and catches version drift earlier.

### Running Tests

```bash
# ensure pyenv env is active
pyenv shell recognition-service-env

# run core integration + unit tests
pytest tests/integration/test_api_endpoints.py -v
pytest tests/unit/test_scene_analysis_service.py -v
```

### Hexagonal Layout

- `analysis/services/scene_analysis_service.py` – orchestrates YOLO + recognition, outputs `SceneContext`.
- `recognition_core/services/face_recognition_service.py` – wraps InsightFace adapter + embedding router.
- `recognition_core/adapters/insightface_adapter.py` – detection + embeddings.
- `recognition_core/adapters/embedding_router_adapter.py` – cosine similarity over JSON roster embeddings.
- `recognition_core/domain/interfaces.py` – ports (`RecognitionModelPort`, `EmbeddingRouterPort`, `RecognitionServicePort`).
- `api/routes/main.py` – JSON-first REST surface consumed by the plugin.

Remove of legacy multi-model stack completed; only InsightFace code remains.

---
## 7. Flash Attention & Captioning (Deferred)

Flash Attention 2 is available for the Phi-3.5 caption pathway. It remains disabled until we switch the caption service on.

```yaml
caption_generator:
  config:
    model_settings:
      flash_attention:
        enabled: false
        force_disable_devices: ["cpu", "mps"]
```

To experiment locally, enable Flash Attention in settings and install the wheel referenced in the Dockerfile snippet (CUDA-only).

---
## 8. Troubleshooting

| Issue | Fix |
| --- | --- |
| `python` points to wrong interpreter | Run `pyenv shell recognition-service-env` before pip/pytest. |
| InsightFace download fails | Check network access; run a one-off `python -c "import insightface; app=insightface.app.FaceAnalysis(); app.prepare()"`. |
| No roster matches | Verify embeddings JSON path (`embedding_router.embeddings_file`) and format. |
| CUDA errors | Force CPU via `insightface.device: "cpu"` in settings. |

---
## 9. Roadmap Hooks

- WordPress plugin consumes the JSON DTOs defined here; keep `api/examples/` in sync with frontend fixtures.
- Hugging Face deployment runs the same Docker image; maintain parity between local and remote configs.
- Caption generation, Flash Attention, and multi-model extensions are deferred until after MVP recognition stability.

---
## 10. Legacy README

The older `recognition_core/README.md` has been superseded by this document and will be removed in a future cleanup to avoid drift.
