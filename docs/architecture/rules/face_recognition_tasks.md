# Face Recognition Workflow — Implementation Tasks

This plan unifies the Workbench recognition flow with the roster-oriented diagrams (`frontend-uml/sequence-face-tagging-remote.mmd`, `frontend-uml/sequence-reference-upload.mmd`) and Roadmap v3 (Epic C: Recognition Pipeline).

## Progress Summary

- ✅ **REST & Job Dispatch**: Recognition analyze endpoint and job polling implemented
- ✅ **Backend Integration**: Client orchestration with retry logic and roster sync complete
- ✅ **Observation Queue & Roster Integration**: Taxonomy system, confidence scoring, and test fixtures complete
- ✅ **Workbench UI**: Recognition panel UX and polling complete; inline labeling workflow deferred
- ✅ **Telemetry & Notifications**: Event emission and error logging complete; automation queue integration deferred
- ✅ **Testing**: PHPUnit and Vitest coverage complete; contract test schema validation partial

## REST & Job Dispatch

- [x] **POST `/recognition/analyze` endpoint** (implemented as `/recognition/analyze` instead of `/recognition/run`)
  - Namespace `cat/v1`, capability `manage_options`.
  - Payload: `{ attachment_ids: number[] }`. Mode/force parameters omitted in current implementation.
  - Validates IDs exist & user can edit each attachment via `RecognitionJobService`.
  - Response: `{ jobId, status, accepted: number, rejected: string[], deferred: string[] }`.
  - Enqueues async job that calls `RecognitionClient->analyzeScene()` for each media item.
- [x] **Job result callback** — `/recognition/job/:id` endpoint
  - Job state (`queued`, `processing`, `complete`, `error`) persisted via `RecognitionJobRepository`.
  - Endpoint `/recognition/job/(?P<id>[a-zA-Z0-9\-]+)` registered for polling status + payload.
  - Returns full job details including progress, observations, and error messages.

## Backend Integration

- [x] **Recognition client orchestration**
  - PHP `RecognitionClient` implements retry logic with exponential backoff (MAX_ATTEMPTS=3, BASE_RETRY_DELAY_MS=200).
  - Maps backend `/analyze-scene` response (`detected_entities`, `roster_match`, `face_data`) into observation records.
  - `RecognitionJobService` stores observations in `RecognitionObservationRepository` with linkage to roster entries.
  - Unknown/low-confidence faces flagged as `needs_review` status for operator labeling.
- [x] **Roster sync**
  - `RosterService->createAndSync()` persists local entry and syncs with backend, storing `remoteId`.
  - Backend roster matches (`roster_entry.unique_id`) automatically linked to local roster via `RosterObservationManager`.
  - Unresolved observations stored with `status=needs_review` awaiting user assignment in Roster Manager.

## Workbench UI

- [x] **Recognition panel UX**
  - Surface selection summary, queued job state, and per-media recognition results. ✅ Implemented in `RecognitionActions.tsx`.
  - Show separate lists for Recognized (roster match) and Needs Review (unknown/low confidence). ✅ `RecognitionResultRow` now splits observations into separate sections.
  - Provide affordance to jump into Roster Manager for unresolved faces (deep link carrying media + observation IDs). ✅ Deep linking implemented with query params.
- [x] **Status polling & failure handling**
  - Poll job endpoint until `complete` or `error`; display progress indicator. ✅ `useRecognitionJob` hook handles polling with progress UI.
  - Retry CTA on network failure; show toast notifications using shared bus. ✅ Retry button added to error UI; snackbar notifications working.
- [ ] **Labeling workflow**
  - For unknown faces, allow inline association with existing roster entries or creation of a new entry (launches roster reference upload flow).
  - Upon labeling, call backend to confirm match and refresh Workbench data (update queue + roster counts). **Note**: Deep links to Roster Manager work; inline workflow deferred.

## Observation Queue & Roster Integration

- [x] Re-rank unresolved observations by highest recognition similarity and display the top roster candidate using the model-provided confidence percentage (avoid falling back to raw detection score).
- [x] Persist roster match similarity separately from detection confidence in storage and update Workbench copy so the distinction is clear; suppress detection fallback when roster scores exist.
- [x] Fix `getRosterConfidenceValue` to include `record.confidence` as fallback when roster match data is zero or unavailable.
- [x] Document current auto-resolve behavior (embeddings averaged immediately). Pending embeddings feature deferred to v0.2—requires backend API changes (`/references/confirm`, `/references/reject`), UI review panel, and migration strategy. See `roster_auto_resolve_behavior.md`.
- [ ] Add regression coverage (Python recognition job + WP resolver) that repeatedly labels the same face and asserts similarity remains within tolerance after the auto-resolve adjustment. **Deferred:** implement when pending embeddings feature ships.
- [x] Register dedicated taxonomy `cat_roster_entity` for attachments and roster storage (REST exposure enabled, capabilities locked to `manage_options`).
- [x] Document roster taxonomy capabilities and update admin/ops guides accordingly. See `roster_taxonomy_guide.md`.
- [x] Migrate existing `cat_roster_` post tags into the dedicated taxonomy, re-link attachment relationships, and leave an optional setting to retain legacy tags for editorial discovery.
- [x] Update recognition tag syncing to write to `cat_roster_entity` and ship a CLI repair utility (`wp cat-roster migrate-tags`).
- [x] Refresh Storybook fixtures and REST payloads to surface the new taxonomy values. Added comprehensive roster and observation fixtures to `adminPayloads.ts`.

## Telemetry & Notifications

- [x] Emit `cat_workbench_recognition_triggered` with `{ ids, count, mode }`. ✅ Emitted in `WorkbenchApp` with selection and retry flag.
- [x] Emit `cat_workbench_recognition_completed`/`failed` events once job resolves (include counts of recognized vs unresolved). ✅ Both events emit full observation summaries.
- [x] Log backend errors to `wp_debug_log` with jobId for traceability. ✅ `RecognitionJobService::logFailure()` logs errors with job context.
- [ ] Display success/error notices in the Workbench panel and add entry to Automation Queue when recognition jobs run longer than N minutes (exact threshold TBD). **Partial**: Error/success notices working via snackbar; automation queue integration deferred.

## Testing

- [x] PHPUnit tests for recognition endpoints (capabilities, payload validation, job status flow). ✅ `ApiTest.php` includes: capability checks (`manage_options`), route registration, job queueing, job hydration, observation storage, deferred/rejected flows.
- [ ] Contract tests ensuring PHP DTOs match backend OpenAPI schema for `/analyze-scene`. **Partial**: `RecognitionJobServiceTest` validates backend response structure using shared sample JSON.
- [x] Vitest/RTL coverage for recognition panel state machine (idle → running → success/error) and labeling actions. ✅ `RecognitionActions.test.tsx` covers: disabled state, submission flow, polling, success state with observations, error handling with retry. `useRecognitionJob.test.tsx` covers: hook disabled state, submission→polling→complete cycle, polling errors.

