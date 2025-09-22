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
SceneAnalysisService ──► RecognitionService (InsightFace) ──► EmbeddingRouter
        │                        │
        │                        └─ InsightFaceAdapter (SCRFD + ArcFace)
        └─ YOLOAdapter / Phi3CaptionAdapter (caption disabled for MVP)

RosterService ──► File storage + embeddings JSON
StartupManager ──► warms InsightFace + embeddings cache
```

- **Recognition only** for MVP: InsightFace `buffalo_l` model (detection + embeddings) with cosine similarity roster matching.
- **REST contract** preserved: WordPress client calls the same endpoints, now returning JSON payloads defined in `api/examples/`.
- **Tests** live under `tests/`; `test_api_contract.py` validates DTO examples consume the same JSON fixtures as the plugin.

---
## 2. Local Quickstart (Recognition Only)

```bash
cd apps/recognition-service

# 1. Pin pyenv to Python 3.10.17 so `python` resolves correctly
pyenv virtualenv 3.10.17 recognition-service-env   # create once
pyenv shell recognition-service-env                # activate for current session

# 2. Install dependencies needed for the backend API
pip install --upgrade pip
pip install -r requirements_local_dev.txt

# Optional: use a custom config file (defaults to recognition/config/settings.yaml)
export RECOG_SETTINGS=${PWD}/recognition/config/settings.yaml

# Optional: pin local cache root when running on a developer machine
export LOCAL_CACHE_ROOT=/Volumes/Butter

# 3. Launch the FastAPI server
uvicorn app:app --host 0.0.0.0 --port 7860 --reload
```

Verify the endpoints (examples in `api/examples/`):

- `POST http://localhost:7860/api/v0/analyze-scene`
- `POST http://localhost:7860/api/v0/embeddings`
- `GET  http://localhost:7860/api/v0/service/info`
- `GET  http://localhost:7860/api/v0/health`

InsightFace weights download on first run. Adjust model/device/thresholds in `recognition/config/settings.yaml` or override via `RECOG_SETTINGS`.

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

`recognition/config/__init__.py` loads `recognition/config/settings.yaml` (override via `RECOG_SETTINGS`). Key sections:

```yaml
insightface:
  model_name: "deepinsight/insightface-scrfd-arcface-w600k"
  device: "auto"           # auto, cpu, cuda, mps
  cache_dir: "/tmp/insightface_models"

recognition:
  default_threshold: 0.45
  max_faces_per_image: 10

embedding_router:
  embeddings_file: "/roster/data/insightface_embeddings.json"
  auto_reload: true
  reload_interval: 30

cache:
  hf_home: null
  hf_datasets_cache: null
  torch_home: null
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
| `/api/v0/roster/*` | Roster CRUD + sync (see `recognition/README` sections below for details). |

Use the JSON fixtures under `api/examples/` when wiring the WordPress client and contract tests.

---
## 6. Development Guide

### Running Tests

```bash
# ensure pyenv env is active
pyenv shell recognition-service-env

# run contract + unit tests
pytest tests/test_api_contract.py -v
pytest recognition/tests/test_api_smoke.py -v

# (optional) accuracy / performance suites
pytest recognition/tests/test_top1_micro.py -v
pytest recognition/tests/bench_latency_micro.py -v
```

### Hexagonal Layout

- `analysis/services/scene_analysis_service.py` – orchestrates YOLO + recognition, outputs `SceneContext`.
- `recognition/services/recognition_service.py` – wraps InsightFace adapter + embedding router.
- `recognition/adapters/insightface_adapter.py` – detection + embeddings.
- `recognition/adapters/embedding_router_adapter.py` – cosine similarity over JSON roster embeddings.
- `recognition/domain/interfaces.py` – ports (`RecognitionModelPort`, `EmbeddingRouterPort`, `RecognitionServicePort`).
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

The older `recognition/README.md` has been superseded by this document and will be removed in a future cleanup to avoid drift.
