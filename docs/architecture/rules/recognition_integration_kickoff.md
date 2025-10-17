# Recognition Integration Kickoff

Curated task clusters required to light up end-to-end communication between the WordPress plugin and the Recognition Service. Tasks are sourced from existing planning docs to focus implementation on two near-term goals:

1. Begin sending and receiving image analysis requests to the backend recognition service.
2. Enable roster management flows in the plugin that synchronize with the recognition service roster APIs.

---

## 1. Image Recognition Request Loop

### Backend readiness (source: `recognition-service-tasks.md`)

- [x] Spin up the FastAPI app locally (`uvicorn app:app --reload`) and validate `/api/v0/analyze-scene`, `/api/v0/embeddings`, `/api/v0/service/info`, and `/api/v0/health` responses. (Service running on port 7860, all endpoints validated 2025-10-11: health ✓, service/info ✓, analyze-scene ✓, embeddings ✓, roster listing ✓)
- [ ] Prepare the Hugging Face Space deployment of `apps/recognition-service/` and confirm all endpoints behave as in local environments.
- [ ] Wire `flake8`, `mypy`, and `pytest` in CI with contract tests that compare OpenAPI fixtures against the PHP DTOs consumed by the plugin.

### WordPress backend contracts (source: `tasks.md`, `face_recognition_tasks.md`)

- [x] Add plugin settings for `recognitionBaseUrl`, `timeoutMs`, and model/profile selection. (Admin settings form now registers/stores these options.)
- [x] Harden the PHP `RecognitionClient` with retries, circuit breaker defaults, and structured error mapping for `/api/v0/analyze-scene` and `/api/v0/embeddings`. (Added bounded retry loop, exponential backoff, and JSON error parsing.)
- [x] Implement `POST /wp-json/cat/v1/recognition/analyze` (aliased as `/recognition/run` in planning) to queue recognition jobs, validate attachment IDs, and fan out to the backend client.
- [x] Persist recognition job state (pending, processing, complete, error) and expose `/wp-json/cat/v1/recognition/job/<id>` for polling results. (Transient-backed repository now tracks pending → processing → complete/error with timestamps.)
- [x] Ensure recognition results are stored as observations linked to attachments and roster entities. (Persisted via `RecognitionJobService::persistObservations()` and `RecognitionObservationRepository`.)
- [x] Add WP-CLI commands (`cat-recognition health`, `cat-recognition analyze <attachment_id>`) for operational smoke tests.

### SPA integration (source: `workbench_tasks_new.md`, `face_recognition_tasks.md`)

- [x] Wire `RecognitionActions` to trigger the new REST endpoint and surface loading/error states.
- [x] Build the recognition panel UX that shows selection summary, job progress, and per-item analysis results. (Handled in `RecognitionActions` with selection metrics, progress indicator, and per-attachment results.)
- [x] Poll the job status endpoint until completion, with retry affordances and toast notifications on failure.
  - [x] Poll job status endpoint with retry affordances (`useRecognitionJob` hook query/polling).
  - [x] Add toast notifications on failure. (`WorkbenchApp` enqueues WordPress snackbar notices on request/job errors.)
- [x] Emit recognition analytics events (`cat_workbench_recognition_triggered`, `cat_workbench_recognition_completed`, `cat_workbench_recognition_failed`). (Hooked up via `WorkbenchApp` analytics emissions.)

### Observability & testing (source: `face_recognition_tasks.md`, `tasks.md`)

- [x] Log backend errors with job correlation IDs in WordPress debug logs. (`RecognitionJobService` now emits structured log entries and actions keyed by job ID.)
- [x] Add PHPUnit coverage for recognition REST controllers (capability checks, payload validation, job lifecycle). (`tests/Api/ApiTest.php` now asserts route registration, capability checks, success/error paths.)
- [x] Align PHP DTOs with backend OpenAPI schemas via contract tests. (Recognition job service test now exercises shared `packages/shared-contracts/recognition/analyze-scene-response.sample.json` fixture.)
- [x] Add Vitest/RTL coverage for the recognition panel state machine (idle → running → success/error) and related UI hooks. (`useRecognitionJob.test.tsx` and `RecognitionActions.test.tsx` exercise the hook and UI integration.)

---

## 2. Roster Management Integration

### Backend API alignment (source: `recognition-service-tasks.md`, `tasks.md`)

- [x] Refactor recognition-service roster endpoints to support pagination, conflict flags, and idempotency keys compatible with the plugin roadmap. (Implemented in `api/routes/roster.py` with idempotency cache, conflict reporting, and paginated listing.)
- [x] Document authentication expectations (API key or token flow) for secure communication between WordPress and the recognition service. (See `docs/architecture/rules/recognition_service_auth.md`.)
- [x] Expose model metadata, thresholds, and device info through `/api/v0/service/info` (for dashboard diagnostics). (Service now returns structured model, recognition, router, performance, and cache sections with contract fixtures.)

### WordPress roster client & persistence (source: `tasks.md`)

- [x] Extend the PHP roster client to call `/api/v0/roster` create/update/delete endpoints and the embeddings helper. (Implemented `RosterClient` with PHPUnit coverage verifying POST/PATCH/DELETE and embeddings flows.)
- [x] Expose WordPress REST endpoints for roster listing, mutations, and manual sync to relay data to the recognition service.
- [ ] Implement create/update flows:
  - [x] On create, call `/api/v0/embeddings` for reference images, then `POST /api/v0/roster`, storing the returned `remote_id` locally. (`RosterService::createAndSync()` now requests embeddings before invoking the remote create endpoint and records sync metrics.)
  - [x] On update, `PATCH /api/v0/roster/{remote_id}` with label/type changes and additional reference images. (`RosterService::updateAndSync()` applies the same embeddings helper for new reference images and tracks metrics.)
- [x] Handle conflict policies: remote embeddings are source of truth; resolve label/type conflicts using `updated_at`, logging overrides. (`RosterService::syncFromRemote()` compares timestamps, merges newer records, and logs conflicts + metrics.)
- [x] Persist sync metrics and last sync timestamps in `cat_roster_sync_state`. (`RosterService::recordSyncMetrics()` now logs created/updated/error counts with ISO timestamps.)
- [x] Provide WP-CLI utilities for roster sync health checks if required. (`cat-roster status` and `cat-roster sync` commands now available.)

### Frontend roster experience (source: `tasks.md`, `workbench_tasks_new.md`, `face_recognition_tasks.md`, `dashboard_tasks.md`)

- [x] Ship the Roster Manager route in the admin SPA with CRUD UI, sync badges (LOCAL, SYNCED, CONFLICT), and avatar thumbnails.
- [x] Localize roster REST endpoints, feature flags, and bootstrap data to the admin SPA.
- [x] Render the roster admin menu page via the SPA mount point to reuse the dashboard bundle.
- [x] Add modal workflow to select/upload avatar images, capture `avatarId`, and display remote sync status.
- [x] Support debounced search across roster label/type with result counts and last synced metadata.
- [x] Provide deep links from recognition results (Workbench recognition panel, dashboard recognition insights) into the roster manager for unresolved faces.
- [x] Surface roster metrics in the dashboard Recognition Insights card, including pending matches and last sync timestamp.

### Sync automation & testing (source: `tasks.md`)

- [x] Schedule periodic roster sync via WP-Cron and expose a manual "Sync from Remote" action in the admin UI.
- [x] Prevent duplicate label+type combinations and surface friendly errors when the backend returns 409 conflicts.
- [x] Add PHPUnit and contract tests covering roster sync flows (create locally → remote ID assigned; remote updates reflected locally; remote deletes handled as archives).
- [x] Seed shared fixtures for roster round-trip tests across frontend and backend repos.

---

---

## Local Integration Testing

### End-to-End Testing Guide

Comprehensive guide for local WordPress ↔ Recognition Service integration:
- **Documentation:** `docs/architecture/rules/local_integration_guide.md`
- **Smoke Test Script:** `scripts/smoke-test-local-integration.sh`
- **PHPUnit Integration Tests:** `apps/wp-context-alt-text/tests/Integration/RecognitionServiceIntegrationTest.php`

### Quick Start

```bash
# 1. Start recognition service
cd apps/recognition-service
./scripts/start_recognition_local.sh start

# 2. Configure WordPress plugin
wp option update context_alt_text_recognition_settings \
  '{"base_url":"http://localhost:7860","timeout_ms":"30000"}' --format=json

# 3. Run smoke tests
chmod +x scripts/smoke-test-local-integration.sh
./scripts/smoke-test-local-integration.sh

# 4. Run PHPUnit integration tests
cd apps/wp-context-alt-text
composer test -- --group integration
```

---

## Next Steps

Once the above task groups are underway, update the source planning documents (`tasks.md`, `face_recognition_tasks.md`, etc.) to reference this kickoff checklist and track progress centrally.
