# Recognition Service Audit (Updated 2024-09)

The audit below replaced the earlier May 2024 findings. The InsightFace-only architecture
is now the canonical implementation:

- JSON endpoints (`/api/v0/analyze-scene`, `/api/v0/embeddings`, `/api/v0/service/info`, `/api/v0/health`) are live and tested via `tests/test_api_contract.py` and `tests/test_scene_analysis.py`.
- Only the InsightFace adapter implements the recognition port. Legacy CVLFace/AdaFace code paths and schema references were removed from the runtime codebase.
- The FastAPI app owns orchestration (`SceneAnalysisService`, `FaceRecognitionService`) while adapters reside under `analysis/adapters` and `recognition_core/adapters`, matching the UML diagrams.
- Roster CRUD remains file-based (`roster_storage`), with modernization (pagination, conflict flags) tracked in `docs/architecture/rules/tasks.md`.
- CI hooks for linting and pytest are staged to return; until then, run `pytest tests/ -v` locally.

For design changes or regressions, update this document so it continues to mirror the diagrams in `docs/architecture/backend-uml/`.
