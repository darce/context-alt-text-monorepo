# Recognition Service Integration Tasks

This list tracks the outstanding work required to deliver a modular, InsightFace-driven recognition backend that plugs cleanly into the Context Alt Text WordPress plugin and can be deployed to Hugging Face Spaces.

## 0. Bring Recognition Service Online
- [ ] Spin up the local FastAPI app (`uvicorn app:app --reload`) and verify `/api/v0/analyze-scene`, `/api/v0/embeddings`, `/api/v0/service/info`, and `/api/v0/health` respond as documented in the README.
- [ ] Prepare the Docker-based Space deployment (recognition-only) by pushing `apps/recognition-service/` to a Hugging Face Space and confirming the same endpoints work in that environment.

## 1. Stabilize the InsightFace Adapter Layer
- [x] Define a `RecognitionModelPort` interface (detect + embed + metadata) and update `SceneAnalysisService` to depend on it.
- [x] Implement the port with a single InsightFace adapter, handling detection, embedding, and configuration via Pydantic settings.
- [x] Remove runtime references to CVLFace/AdaFace/ArcFace adapters; document historical context in `docs/architecture/backend-uml/` only.
- [x] Add unit tests that exercise the adapter contract with fakes to guarantee parity when swapping models later.

## 2. API Surface & Contracts
- [x] Replace multipart `/analyze-scene` with a JSON `AnalyzeSceneRequest` DTO and return `SceneAnalysisResult` as described in the UML.
- [x] Add a dedicated `/embeddings` endpoint backed by the same InsightFace adapter.
- [x] Generate and commit OpenAPI schemas + golden examples for `/analyze-scene`, `/embeddings`, `/health`, and `/service/info`.
- [ ] Wire `flake8`, `mypy`, and pytest in CI; include contract tests that compare OpenAPI fixtures with PHP DTOs consumed by the plugin.

## 3. Roster & Plugin Integration
- [ ] Refactor roster endpoints to use pagination, conflict flags, and idempotency keys compatible with the WordPress client roadmap.
- [x] Expose model metadata (version, threshold, device) through `/service/info` so the plugin can surface health diagnostics.
- [ ] Build a thin PHP client in the plugin that targets the new JSON endpoints and shares fixtures with backend contract tests.
- [ ] Document authentication expectations (API key or token flow) for secure WP <-> HF communication.

## 4. Deployment Readiness (Hugging Face Spaces)
- [ ] Strip dead dependencies from the Dockerfile and requirements files; ensure only InsightFace + supporting libs are installed.
- [ ] Add startup health checks and warmup routines compatible with Spaces GPU/CPU profiles.
- [ ] Publish a deployment checklist covering environment variables, caching directories, and monitoring hooks.
- [ ] Schedule recurring benchmarks using the InsightFace adapter and store results in `reports/` with timestamps for transparency.

## 5. Cleanup & Documentation
- [x] After adapter stabilization, archive or delete `apps/recognition-service/__archived-recognition-multi-model/` to avoid accidental imports.
- [ ] Update backend UML diagrams to reflect the single-adapter port architecture.
- [ ] Cross-link this task list from `docs/architecture/rules/tasks.md` once items begin execution.
