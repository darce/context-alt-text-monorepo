# Face Recognition Workflow — Implementation Tasks

This plan unifies the Workbench recognition flow with the roster-oriented diagrams (`frontend-uml/sequence-face-tagging-remote.mmd`, `frontend-uml/sequence-reference-upload.mmd`) and Roadmap v3 (Epic C: Recognition Pipeline).

## REST & Job Dispatch

- [ ] **POST `/recognition/run` endpoint**
  - Namespace `context-alt-text/v1`, capability `manage_options`.
  - Payload: `{ mediaIds: string[], mode?: 'faces'|'brands', force?: boolean }`.
  - Validate IDs exist & user can edit each attachment.
  - Response: `{ jobId, accepted: number, rejected: string[] }`.
  - Enqueue async job (Action Scheduler/cron) that calls `RecognitionClient->analyzeScene()` for each media item.
- [ ] **Job result callback**
  - Persist interim job state (`pending`, `processing`, `complete`, `error`) in custom table or transients keyed by jobId.
  - Register endpoint `/recognition/job/(?P<id>[\w-]+)` to poll status + payload.

## Backend Integration

- [ ] **Recognition client orchestration**
  - Implement PHP client using Roadmap Epic C retry/backoff rules to call backend `/analyze-scene`.
  - Map backend response into DTO `{ mediaId, observations: [{ faceId, rosterId|null, confidence, thumbnailUrl }] }`.
  - Store recognized faces with linkage to roster (existing or new) and flag unknown observations for review.
- [ ] **Roster sync**
  - When backend returns new `rosterId`, ensure local roster entity is created or updated with remote ID (see `sequence-reference-upload`).
  - Unresolved faces create `FaceObservation` records awaiting user labeling.

## Workbench UI

- [ ] **Recognition panel UX**
  - Surface selection summary, queued job state, and per-media recognition results.
  - Show separate lists for Recognized (roster match) and Needs Review (unknown/low confidence).
  - Provide affordance to jump into Roster Manager for unresolved faces (deep link carrying media + observation IDs).
- [ ] **Status polling & failure handling**
  - Poll job endpoint until `complete` or `error`; display progress indicator.
  - Retry CTA on network failure; show toast notifications using shared bus.
- [ ] **Labeling workflow**
  - For unknown faces, allow inline association with existing roster entries or creation of a new entry (launches roster reference upload flow).
  - Upon labeling, call backend to confirm match and refresh Workbench data (update queue + roster counts).

## Observation Queue & Roster Integration

- [ ] Re-rank unresolved observations by highest recognition similarity and display the top roster candidate using the model-provided confidence percentage (avoid falling back to raw detection score).
- [ ] Persist roster match similarity separately from detection confidence in storage and update Workbench copy so the distinction is clear; suppress detection fallback when roster scores exist.
- [ ] Update auto-resolve so new embeddings stay pending until an operator confirms them; store pending references per roster entry instead of averaging immediately.
- [ ] Add regression coverage (Python recognition job + WP resolver) that repeatedly labels the same face and asserts similarity remains within tolerance after the auto-resolve adjustment.
- [ ] Register dedicated taxonomy `cat_roster_entity` for attachments and roster storage, expose it via REST/UI, and document required capabilities for roster operations.
- [ ] Migrate existing `cat_roster_` post tags into the dedicated taxonomy, re-link attachment relationships, and leave an optional setting to retain legacy tags for editorial discovery.
- [ ] Update recognition tag syncing to write to `cat_roster_entity`, provide a CLI repair utility, refresh Storybook fixtures, and ensure REST payloads surface the new taxonomy values.

## Telemetry & Notifications

- [ ] Emit `cat_workbench_recognition_triggered` with `{ ids, count, mode }`.
- [ ] Emit `cat_workbench_recognition_completed`/`failed` events once job resolves (include counts of recognized vs unresolved).
- [ ] Log backend errors to `wp_debug_log` with jobId for traceability.
- [ ] Display success/error notices in the Workbench panel and add entry to Automation Queue when recognition jobs run longer than N minutes (exact threshold TBD).

## Testing

- [ ] PHPUnit tests for recognition endpoints (capabilities, payload validation, job status flow).
- [ ] Contract tests ensuring PHP DTOs match backend OpenAPI schema for `/analyze-scene`.
- [ ] Vitest/RTL coverage for recognition panel state machine (idle → running → success/error) and labeling actions.

