# Recognition Service Implementation Summary (2024-09)

The recognition service now runs a single InsightFace pipeline with a lean
port-adapter layout. Use this document as a snapshot of the current structure.

```
apps/recognition-service/
├── analysis/                   # Object + caption orchestration
│   ├── adapters/               # YOLO + caption adapters
│   ├── entities/               # Scene DTOs
│   ├── ports/                  # Adapter interfaces
│   └── services/               # SceneAnalysisService
├── recognition_core/           # InsightFace recognition engine
│   ├── adapters/               # InsightFace + embedding router adapters
│   ├── config/                 # recognition_core/config/settings.yaml
│   ├── domain/                 # Ports & entities for recognition
│   ├── services/               # RecognitionService
│   └── utils/                  # Helper functions (face utils, conversion)
├── roster/                     # Roster storage + DTOs
├── shared/                     # Shared startup, config, and infrastructure
├── api/                        # FastAPI routes (JSON DTOs)
├── scripts/                    # Local dev helpers (install/start)
└── tests/                      # Contract + scene analysis tests
```

## Active API Endpoints

- `POST /api/v0/analyze-scene`
- `POST /api/v0/embeddings`
- `GET /api/v0/service/info`
- `GET /api/v0/health`
- `GET /api/v0/roster/...` CRUD endpoints

## Key Characteristics

- **Ports/Adapters**: Adapters are injected via `shared/startup/adapter_factory.py`, keeping the core services independent of model implementations.
- **Recognition Service**: `recognition_core/services/recognition_service.py` is the single orchestration layer for InsightFace and embedding routing.
- **Configuration**: `recognition_core/config/settings.yaml` controls InsightFace, cache, and embedding settings. `shared/config/settings.yaml` handles API/startup runtime settings.
- **Tests**: Run `pytest tests/test_api_contract.py -v` and `pytest tests/test_scene_analysis.py -v` to validate the integration surface.

Legacy CVLFace/AdaFace pipelines, quality-weighted roster scripts, and
`recognition/pipelines` were removed. Historical notes live in
`docs/ADAFACE_CLEANUP_SUMMARY.md` for reference.
