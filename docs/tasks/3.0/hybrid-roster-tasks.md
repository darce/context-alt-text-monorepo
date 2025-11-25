# Context Alt Text — Hybrid Option (#1) Actionable Task List (v3 Patch)

**Scope:** Single developer. Coding-only. No scrum/meetings. Integrates `roadmap-v3.hybrid.md`, `V3_ASSISTED_FACE_IDENTIFICATION_UX`, `hybrid-face-matching-strategy.md`, and `assisted-face-id-tasks-detailed.md` into one executable checklist with clear success markers.  
**Principle:** Remote canonical roster + FAISS suggestions served exclusively by the recognition service, with local caches only reducing repeat calls (no offline matching path).  
**Last Updated:** 2025-10-30 (gap-filled revision integrating hybrid schema and WP-Cron sync requirements)

---

## A. Success Criteria (global)

- Cold start: local clustering under **50 ms** for ≤50 faces.
- Warm cache: FAISS batch suggest under **200 ms**, end-to-end.
- Cache hit rate within one labeling session: **≥80%**.
- Remote outage handling: clear admin + API messaging when recognition service is unavailable (no local fallback).
- UX: label once → cascades to all similar faces in-session and drafts high-confidence cascades for review.
- Database schema version tracked via `cat_db_version` option; idempotent installer.
- WP-Cron jobs for roster delta sync, sync-queue worker, observation purge.

---

## B. Database & Schema Tasks (SQL)

> Greenfield; create/alter directly in installer, idempotent re-run required. Reference: Appendix A in roadmap-v3.hybrid-patch.md for complete schema.

### B1) Create hybrid tables (new installation path)

**Why:** Local roster mirror for offline operation; observation tracking for review workflow; sync queue for retry/offline.  
**Files:** `src/Infrastructure/Database/RosterTableInstaller.php`, `src/Infrastructure/Database/ObservationTableInstaller.php`, `src/Infrastructure/Database/SyncQueueTableInstaller.php`, `src/Support/LifecycleManager.php` (orchestrate installers).  
**SQL Tables:**

1. **`{{prefix}}cat_roster`** — local mirror (remote is authority):

   - id (BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY)
   - remote_id (VARCHAR 64 NOT NULL UNIQUE)
   - label (VARCHAR 191 NOT NULL)
   - type (ENUM: person|brand|other, DEFAULT person)
   - avatar_url (VARCHAR 255 NULL)
   - meta (LONGTEXT NULL, JSON)
   - etag (VARCHAR 64 NULL)
   - last_sync_at (DATETIME NULL)
   - created_at (DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP)
   - updated_at (DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP)
   - deleted_at (DATETIME NULL)
   - Indices: idx_remote_id, idx_updated_at

2. **`{{prefix}}cat_observation`** — review artifacts:

   - observation_id (BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY)
   - session_id (VARCHAR 64 NOT NULL)
   - attachment_id (BIGINT UNSIGNED NOT NULL)
   - bbox (LONGTEXT NOT NULL, JSON: {x,y,width,height})
   - confidence (FLOAT NOT NULL)
   - embedding_hash (VARCHAR 64 NULL, SHA256 for dedup)
   - assigned_roster_id (BIGINT UNSIGNED NULL, FK → cat_roster.id ON DELETE SET NULL)
   - status (ENUM: pending|confirmed|rejected|deferred, DEFAULT pending)
   - review_notes (TEXT NULL)
   - created_at (DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP)
   - reviewed_at (DATETIME NULL)
   - Indices: idx_attachment, idx_roster, idx_status, idx_session
   - FK: CONSTRAINT fk_obs_roster FOREIGN KEY (assigned_roster_id) REFERENCES {{prefix}}cat_roster(id) ON DELETE SET NULL

3. **`{{prefix}}cat_sync_queue`** — retry/offline queue:
   - queue_id (BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY)
   - action (ENUM: confirm_match|create_roster|update_roster|delete_roster, NOT NULL)
   - payload (LONGTEXT NOT NULL, JSON)
   - remote_id (VARCHAR 64 NULL)
   - attempts (INT NOT NULL DEFAULT 0)
   - last_error (TEXT NULL)
   - available_at (DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP)
   - created_at (DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP)
   - Indices: idx_available, idx_action

**Charset:** utf8mb4, collation utf8mb4_unicode_520_ci  
**Done when:** Installer creates all three tables + indices on activation; `cat_db_version` option set to '1.0.0'; uninstall drops tables and option; PHPUnit tests verify idempotent re-run (run twice, assert tables not duplicated); foreign key constraints enforced; installer logs schema version on success.

### B2) Avatar generation & storage

**Why:** Local derived assets for roster UI performance.  
**Implementation:** Generate 128×128 WebP crops on roster create/update; store under `wp-content/uploads/context-alt-text/avatars/{remote_id}.webp`; persist URL in `cat_roster.avatar_url`.  
**Files:**

- `src/Services/AvatarGeneratorService.php` (crop+WebP conversion via WP image_editor)
- `src/Infrastructure/Storage/AvatarStorageAdapter.php` (handles upload directory creation and permissions)

**Dependencies:** WordPress image editor functions (`wp_get_image_editor`), GD or Imagick with WebP support.  
**Security:** `.htaccess` in avatars directory blocks direct access; only serve via controller with nonce check.  
**Done when:** Service generates valid WebP (128×128, 85% quality); regeneration triggered on roster label/primary-face change; permissions hardened; uninstall removes avatar directory recursively; PHPUnit tests verify generation + cleanup + error handling (missing GD/Imagick).

### B3) DAO/Repository layer for all tables

**Why:** Type-safe data access; consistent prepared statements; testable without DB.  
**Files:**

- `src/Infrastructure/Repositories/RosterRepository.php`
- `src/Infrastructure/Repositories/ObservationRepository.php`
- `src/Infrastructure/Repositories/SyncQueueRepository.php`

**Methods (RosterRepository):**

- `create($remoteId, $label, $type, $meta, $avatarUrl): int` — returns local id
- `findByRemoteId($remoteId): ?array` — returns row or null
- `updateByRemoteId($remoteId, $updates): bool` — updates etag, last_sync_at, meta
- `markDeleted($remoteId): bool` — soft delete (set deleted_at)
- `getAllActive(): array` — excludes soft-deleted, orders by updated_at DESC
- `purgeDeleted($olderThanDays = 90): int` — hard delete after retention period

**Methods (ObservationRepository):**

- `create($sessionId, $attachmentId, $bbox, $confidence, $embeddingHash): int`
- `findBySession($sessionId, $status = null): array` — filter by status if provided
- `updateStatus($observationId, $status, $reviewNotes = null): bool`
- `assignRoster($observationId, $rosterId): bool`
- `purgeOld($olderThanDays = 90): int` — delete old observations

**Methods (SyncQueueRepository):**

- `enqueue($action, $payload, $remoteId = null): int`
- `getNextBatch($limit = 10): array` — fetch available_at <= NOW(), order by created_at ASC
- `markProcessed($queueId): bool` — delete on success
- `incrementAttempts($queueId, $error, $backoffSeconds): bool` — exponential backoff
- `purgeDeadLetter($maxAttempts = 5): int` — delete after N failed attempts

**Done when:** All methods use `$wpdb->prepare()`; return types match; PHPUnit tests with `WP_Mock` stub DB calls; integration tests verify CRUD operations; repositories injected via constructor (testable).

---

## C. REST API (PHP) — Controllers & Routes

### C1) **POST** `/cat/v1/recognition/scan` (Batch Face Scan)

**Purpose:** Trigger face detection + clustering on selected images.  
**Files:** `src/Recognition/ScanController.php`, `src/Recognition/FaceDetectionPipeline.php`, `src/Jobs/FaceDetectionJob.php`.  
**Request Schema:**

```json
{
  "attachmentIds": [123, 456, 789],
  "sessionId": "uuid-v4",
  "options": {
    "clusteringThreshold": 0.6,
    "minClusterSize": 2
  }
}
```

**Response:**

```json
{
  "success": true,
  "jobId": "job-uuid",
  "message": "Face detection queued for 3 images"
}
```

**Implementation:**

- Validate `manage_options` capability
- Check attachmentIds exist and are image types
- Enqueue `FaceDetectionJob` with batch (chunked into max 25 per job)
- Return job ID for status polling

**Done when:** Permission checks pass; payload validation rejects invalid IDs/types; queue dispatch succeeds; PHPUnit tests cover permissions/validation/persistence; MSW mock returns job ID.

### C2) **GET** `/cat/v1/observations` and **GET** `/cat/v1/observations/{id}`

**Purpose:** List observations (detected faces) for review; get single observation detail.  
**Files:** `src/Recognition/ObservationController.php`, `src/Infrastructure/RestApi/RouteRegistry.php`.  
**Request Params (list):**

- `session_id` (required): filter by session
- `status` (optional): filter by status enum
- `page` (default 1), `per_page` (default 20)

**Response (list):**

```json
{
  "observations": [
    {
      "observation_id": 123,
      "attachment_id": 456,
      "bbox": { "x": 10, "y": 20, "width": 100, "height": 100 },
      "confidence": 0.95,
      "status": "pending",
      "thumbnail_url": "https://example.test/wp-content/uploads/faces/thumb-123.jpg"
    }
  ],
  "pagination": { "page": 1, "per_page": 20, "total": 50, "total_pages": 3 }
}
```

**Implementation:**

- Use `ObservationRepository::findBySession()`
- Generate face thumbnails via `FaceThumbnailProvider` (crop bbox from attachment, cache 150×150 JPEG)
- Paginate results
- Single observation endpoint returns full detail + suggestions if assigned

**Done when:** Pagination works; thumbnails cached (regenerate on 404); PHPUnit coverage; MSW mocks return paginated data.

### C3) **POST** `/cat/v1/observations/{id}/defer` (Review Later)

**Purpose:** Defer ambiguous observation for later review.  
**Files:** `src/Recognition/ObservationController.php`.  
**Request:**

```json
{
  "review_notes": "Unclear angle, need better image"
}
```

**Response:**

```json
{
  "success": true,
  "observation_id": 123,
  "status": "deferred"
}
```

**Implementation:**

- Validate observation ownership (same session or admin)
- Call `ObservationRepository::updateStatus($id, 'deferred', $notes)`
- Set reviewed_at timestamp

**Done when:** Controller validates ownership; mutation persisted; tests cover happy/edge paths (not found, wrong session); MSW mock returns success.

### C4) **POST** `/cat/v1/identify` (Strategy selection + FAISS path)

**Purpose:** Get identity suggestions for face embeddings using hybrid strategy.  
**Files:** `src/Recognition/IdentifyController.php`, `src/Recognition/RecognitionClient.php`, `src/Api/Api.php` (request schema).  
**Request:**

```json
{
  "observations": [
    {"observation_id": 123, "embedding": [0.1, 0.2, ...]},
    {"observation_id": 456, "embedding": [0.3, 0.4, ...]}
  ],
  "useRemoteMatching": true,
  "threshold": 0.65
}
```

**Response:**

```json
{
  "suggestions": [
    {
      "observation_id": 123,
      "matches": [
        {
          "remote_id": "person-ana-001",
          "label": "Ana Rodriguez",
          "score": 0.92
        },
        {
          "remote_id": "person-marta-002",
          "label": "Marta Silva",
          "score": 0.78
        }
      ]
    }
  ],
  "strategy_used": "remote_faiss"
}
```

**Implementation:**

- **Strategy gating:**
  1. If `useRemoteMatching` is false (feature flag or settings), return a 503 response explaining that recognition is disabled until remote matching is restored.
  2. If `RecognitionClient::checkHealth()` succeeds → call `/api/v0/suggest` on the backend with the provided embeddings.
  3. If embeddings are missing → call `/api/v0/embeddings` on the backend first, then immediately invoke `/api/v0/suggest`.
- Add methods to `RecognitionClient`: `checkHealth()`, `getRosterStats()`, `suggestMatches($embeddings, $threshold)`.
- If the remote call fails (timeout, 5xx), log error context, surface a 503/`service_unavailable` payload to the frontend, and skip local matching (no fallback path).
- Cache successful suggestion responses in-memory for the session to avoid redundant remote calls.

**Done when:** Remote suggestion path succeeds when healthy; outages propagate clear error messaging (no silent fallback); integration tests simulate FAISS down/timeout and assert service_unavailable responses; PHPUnit tests stub client; response still includes `strategy_used` field (`remote_faiss` on success, `remote_unavailable` when the service is down).

### C5) **POST** `/cat/v1/confirm` (Persist label + progressive learning)

**Purpose:** Confirm identity for observations; trigger cascade drafts; queue remote sync.  
**Files:** `src/Recognition/ConfirmController.php`, `src/Roster/RosterClient.php`, `src/Services/CascadeService.php`.  
**Request:**

```json
{
  "observations": [123, 456],
  "roster": {
    "remote_id": "person-ana-001",
    "label": "Ana Rodriguez"
  },
  "embeddings": [[0.1, 0.2, ...], [0.3, 0.4, ...]],
  "cascade": true
}
```

**Response:**

```json
{
  "success": true,
  "confirmed_count": 2,
  "cascade_drafts": [
    { "observation_id": 789, "similarity": 0.95, "status": "pending_review" }
  ],
  "sync_queued": true
}
```

**Implementation:**

- Validate observations exist and belong to current session/user
- If `roster.remote_id` exists locally → use it; else → call `RosterRepository::create()` and queue `create_roster` action
- Update observations: `ObservationRepository::updateStatus($id, 'confirmed')` and `assignRoster($id, $rosterId)`
- If embeddings provided: append them to the JSON collection in `cat_roster.meta` AND enqueue `SyncQueueRepository::enqueue('confirm_match', {remote_id, embeddings})`
- If `cascade` flag true: call `CascadeService::findSimilar($embeddings, $threshold)` and create draft observations with status `pending_review`
- Return draft IDs and counts

**Done when:** Subsequent detections of same person yield suggestions at threshold; cascade logic respects 0.95/0.85/0.65 tiers; unit tests verify cascade draft creation; remote sync queued; tests cover create-new-person vs existing-person paths.

### C6) **POST** `/cat/v1/roster/sync` (Manual roster delta sync)

**Purpose:** Admin-triggered roster sync from remote to local mirror.  
**Files:** `src/Roster/SyncController.php`, `src/Roster/RosterClient.php`.  
**Implementation:**

- Call `RecognitionClient::getRoster()` with `If-None-Match: {local_etag}` header
- If 304 Not Modified → return "Already up to date"
- If 200 OK → parse delta, upsert local roster via `RosterRepository`, update etags
- Conflict resolution: remote wins (overwrite local meta/label if etag mismatch)

**Done when:** Endpoint callable by admin; etag caching works; conflict resolution tested; PHPUnit tests stub client; logs sync result + row counts.

---

## D. Domain Services & Background Work (PHP)

### D1) RecognitionClient additions

**File:** `src/Recognition/RecognitionClient.php`.  
**New Methods:**

- `checkHealth(): array` — GET `/api/v0/health`, returns `{status, version, models}`
- `getRosterStats(): array` — GET `/api/v0/roster/stats`, returns `{total_entries, models}`
- `suggestMatches(array $embeddings, float $threshold): array` — POST `/api/v0/suggest`, batch suggestion call
- `getRoster(string $etag = null): array` — GET `/api/v0/roster` with `If-None-Match` header for delta sync

**Error handling:** Wrap all HTTP calls in try/catch; on timeout/5xx → log error and throw `RecognitionClientException`; caller surfaces outage messaging (no local fallback).  
**Retries:** Use exponential backoff with jitter (1s, 2s, 4s) for 5xx; respect `Retry-After` header on 429.  
**Done when:** Request/response validated against OpenAPI schema; exceptions handled; PHPUnit tests stub HTTP calls (Guzzle mock); integration tests (manual, skipped in CI) hit real backend.

### D2) CascadeService (high-confidence drafts)

**File:** `src/Services/CascadeService.php`.  
**Purpose:** After confirm, find similar unconfirmed observations and draft auto-labels.  
**Method:** `findSimilar(array $embeddings, string $sessionId, float $threshold = 0.85): array`  
**Implementation:**

- Fetch all `pending` observations for session via `ObservationRepository`
- Compute cosine similarity between confirmed embeddings and pending embeddings
- Filter by threshold (0.95 = high confidence, 0.85 = medium, 0.65 = low suggestion)
- Create draft observations with status `pending_review` and assign tentative roster ID
- Return draft observation IDs + similarity scores

**Done when:** Threshold tiers respected (0.95/0.85/0.65); tests verify draft creation for various similarity distributions; drafts appear in UI "Pending Review" section; no duplicates created (check embedding_hash).

### D3) Sync Queue Worker (WP-Cron job)

**File:** `src/Jobs/SyncQueueWorkerJob.php`.  
**Purpose:** Process queued sync actions (create/update/delete roster, confirm matches).  
**Cron Hook:** `cat_sync_queue_worker` (every 5 minutes).  
**Implementation:**

- Fetch next batch (10 items) via `SyncQueueRepository::getNextBatch()`
- For each item:
  - Parse `action` and `payload`
  - Call corresponding `RecognitionClient` method (createRoster, updateRoster, deleteRoster, confirmMatch)
  - On success → `SyncQueueRepository::markProcessed($queueId)`
  - On failure → `SyncQueueRepository::incrementAttempts($queueId, $error, $backoffSeconds)` with exponential backoff (5min, 15min, 1hr, 4hr, 12hr)
  - After 5 attempts → move to dead letter (log + alert admin)
- Log batch summary (processed, failed, remaining)

**Done when:** Job processes on schedule; CLI command `wp cat sync process` triggers manual run; errors logged and surfaced in admin status card; backoff schedule validated in tests; dead-letter purge after retention period.

### D4) Roster Delta Sync (WP-Cron job)

**File:** `src/Jobs/RosterDeltaSyncJob.php`.  
**Purpose:** Periodic roster sync from remote to local (every 15 minutes).  
**Cron Hook:** `cat_roster_delta_sync`.  
**Implementation:**

- Call `RecognitionClient::getRoster($etag)` with cached etag from last sync
- If 304 → skip, log "no changes"
- If 200 → parse roster entries, upsert via `RosterRepository`, update `last_sync_at` timestamps
- Conflict resolution: remote wins (overwrite local if etag differs)
- Prune local soft-deleted entries after 90 days

**Done when:** Runs every 15 minutes; etag caching reduces bandwidth; conflict resolution tested; logs sync stats (added/updated/deleted counts); admin can trigger manual sync via settings page.

### D5) Observation Purge (WP-Cron job)

**File:** `src/Jobs/ObservationPurgeJob.php`.  
**Purpose:** Delete old observations after retention period (default 90 days).  
**Cron Hook:** `cat_observation_purge` (daily).  
**Implementation:**

- Call `ObservationRepository::purgeOld(90)` — deletes observations with `created_at < NOW() - 90 days`
- Log purge count
- Configurable retention via settings (min 30 days, max 365 days)

**Done when:** Job runs daily; retention period configurable; tests verify retention logic; purge count logged; admin notification if >1000 rows purged in single run.

---

## E. Frontend (TS/TSX) — Workbench & Hooks

### E1) Unknown People Panel (complete/verify)

**Files:** `js/components/workbench/UnknownPeoplePanel.tsx`, `js/components/workbench/ObservationCard.tsx`, `js/hooks/useObservations.ts`.  
**Purpose:** List pending observations (detected faces) grouped by similarity clusters.  
**Implementation:**

- Fetch observations via `useObservations(sessionId, 'pending')`
- Group by cluster_id (if clustering enabled) or display as flat list
- Show thumbnail, confidence, attachment preview
- Actions: Select for batch labeling, View detail, Defer
- Loading/empty/error states with retry action

**Done when:** Loading/empty/error states covered; keyboard accessible (arrow navigation, space to select); Storybook stories for all states; tests verify selection/deselection.

### E2) Observation Detail View (finish remaining)

**Files:** `js/components/workbench/ObservationDetailView.tsx`, `js/components/workbench/FaceGrid.tsx`, `js/hooks/useObservationDetail.ts`.  
**Purpose:** Detailed view of single observation with suggestion chips and labeling actions.  
**Implementation:**

- Fetch observation detail via `useObservationDetail(observationId)`
- Display full-size face crop, bbox overlay on original image
- Show top-3 suggestions from FAISS/local (if available)
- Actions: **Label As...** (opens ConfirmLabelModal), **Review Later** (defer), **Split Cluster** (if clustered)
- Keyboard navigation: Tab (focus chips), Enter (select suggestion), Esc (close), Arrow keys (navigate between observations in session)
- Drag-and-drop: Allow dragging observation thumbnail to roster entry (assign identity)

**Done when:** Tests for suggestion selection, keyboard navigation, defer action; Storybook stories for various suggestion counts (0, 1, 3+); drag-and-drop functional with visual feedback.

### E3) Strategy Selection (frontend)

**Files:** `js/hooks/useRosterSearch.ts`, `js/hooks/usePeopleSuggestions.ts`, `js/types/people-labeling.ts`.  
**Purpose:** Automatically choose local vs remote matching based on roster size.  
**Implementation:**

- Add hook `useRosterStrategy()` that fetches roster size via `GET /cat/v1/roster/stats` (used only for UI hints/telemetry).
- `useRemoteMatching` flag controls whether `/cat/v1/identify` should call the remote service; when false, the hook raises an error (recognition disabled).
- When roster stats fetch fails, surface an error toast and keep remote matching enabled (no automatic fallback).
- Log strategy decision to browser console (dev mode only) when remote calls succeed.

**Type changes:**

```typescript
interface IdentifyRequest {
  observations: Array<{ observation_id: number; embedding: number[] }>;
  useRemoteMatching?: boolean;
  threshold?: number;
}

interface IdentifyResponse {
  suggestions: Array<{
    observation_id: number;
    matches: Array<{ remote_id: string; label: string; score: number }>;
  }>;
  strategy_used: "remote_faiss" | "remote_unavailable";
}
```

**Done when:** Unit tests cover roster size thresholds (0, 10, 100, 1000) and flag propagation; tests cover remote outage responses (strategy_used = "remote_unavailable"); roster stats failure surfaces error UI; strategy decision logged for successful calls.

### E4) Session cache & localStorage

**Purpose:** Reduce redundant FAISS calls within labeling session.  
**Implementation:**

- **Session cache (in-memory):** Map of `attachmentId → suggestions[]` stored in React Context or Zustand store
- **localStorage cache:** Key `cat:suggest-cache:v1:{sessionId}`, TTL 15 minutes, stores suggestions JSON
- Cache invalidation triggers: confirm action, manual refresh, session end
- Cache hit tracking: increment counter, display hit rate in dev tools

**Files:** `js/utils/suggestionCache.ts`, `js/hooks/useSuggestionCache.ts`.  
**Methods:**

- `getCachedSuggestions(observationId): Match[] | null`
- `setCachedSuggestions(observationId, matches: Match[]): void`
- `invalidateCache(observationId?: number): void` — clear specific or all
- `getCacheHitRate(): number` — for telemetry

**Done when:** Cache hit rate ≥80% in typical session; cache invalidated on confirm; tests simulate cache lifecycle (set, get, invalidate, expire); localStorage persists across page refreshes within TTL.

### E5) Confirmation Modal

**Files:** `js/components/workbench/ConfirmLabelModal.tsx`.  
**Purpose:** Refine selection, choose person (existing/new), preview cascade drafts.  
**Implementation:**

- Props: `observations: number[]`, `suggestions: Match[]`, `onConfirm`, `onCancel`
- UI sections:
  1. Face grid (selected observations with thumbnails)
  2. Person picker (searchable dropdown, "Create New Person" option)
  3. Top-3 suggestions (if available, clickable to auto-fill person picker)
  4. Cascade preview (checkbox: "Also label N similar faces", shows draft count)
  5. Actions: Confirm, Cancel
- Keyboard: Enter (confirm), Esc (cancel), Tab (navigate fields), Arrow keys (navigate suggestions)
- ARIA: role="dialog", aria-modal="true", focus trap, aria-labelledby points to modal title

**Done when:** ARIA roles/labels complete; focus trap works; keyboard flows tested; unit tests for confirm/cancel/create-new paths; Storybook stories for various observation counts and suggestion states.

### E6) Defer (Review Later) UI

**Files:** `ObservationDetailView.tsx` (button), `js/hooks/useDeferObservation.ts`.  
**Purpose:** User action to defer ambiguous observation for later review.  
**Implementation:**

- Button in ObservationDetailView: "Review Later" (icon: clock)
- Opens popover with textarea for notes (optional)
- Calls `POST /cat/v1/observations/{id}/defer` with notes
- Optimistic update: immediately mark observation as deferred in UI
- Show undo snackbar for 5 seconds (allows quick revert)
- Refresh observations list to remove deferred item

**Done when:** Button calls API endpoint; optimistic update renders immediately; undo snackbar functional (reverts status); tests cover defer, undo, and API error handling; accessibility verified (focus management, screen reader announcements).

---

## F. Settings & Telemetry

### F1) Thresholds & knobs (Settings UI)

**Purpose:** Allow admins to tune recognition behavior without code changes.  
**Files:** `src/Admin/SettingsPage.php`, `js/components/settings/RecognitionSettings.tsx`.  
**Settings to add:**

1. **Suggestion Threshold** (float, 0.0-1.0, default 0.65) — minimum similarity for match suggestion
2. **Cascade Threshold** (float, 0.0-1.0, default 0.85) — minimum similarity for auto-draft
3. **Cache TTL** (int, minutes, default 15) — localStorage suggestion cache expiration
4. **Roster Size Cutoff** (int, default 10) — threshold for switching to remote matching
5. **Observation Retention** (int, days, default 90) — how long to keep old observations
6. **Sync Queue Retry Attempts** (int, default 5) — max retries before dead letter

**Implementation:**

- Store in WP options: `cat_recognition_settings` (JSON)
- Sanitize/validate on save (e.g., threshold must be 0-1, retention ≥30 days)
- Load on backend (hook into RecognitionClient initialization) and frontend (REST endpoint `/cat/v1/settings`)
- Settings page with form inputs, help text, reset to defaults button

**Done when:** Unit tests for validation (reject invalid values); e2e tests verify settings persistence (save, reload page, values retained); settings flow documented in user guide.

### F2) Status & Health Dashboard

**Purpose:** Admin visibility into recognition system health and roster state.  
**Files:** `src/Admin/StatusPage.php`, `js/components/admin/StatusDashboard.tsx`.  
**Metrics to display:**

1. **FAISS Health:** Status (up/down), response time, last checked timestamp
2. **Roster Stats:** Total people, total embeddings, last sync time
3. **Sync Queue:** Pending actions count, failed actions count, dead letter count
4. **Observations:** Total pending, total deferred, avg confidence
5. **Cache Performance:** Hit rate, avg response time (local vs remote)

**Implementation:**

- Backend endpoint: `GET /cat/v1/status` aggregates metrics from RecognitionClient, repositories
- Frontend fetches every 30s via React Query (manual refresh button available)
- Error states visible (e.g., "FAISS unreachable since 2hrs ago")
- Action buttons: "Sync Now", "Retry Failed", "Clear Cache"

**Done when:** `RecognitionClient.getRosterStats()` wired; error states render properly (red badge, error message); refresh button functional; PHPUnit tests stub metrics aggregation.

### F3) CLI & Ops Commands

**Purpose:** Admin/ops tooling for manual sync and diagnostics.  
**Files:** `src/CLI/SyncCommand.php`, `src/CLI/StatusCommand.php`.  
**Commands to add:**

1. **`wp cat sync roster`** — Trigger manual roster delta sync (bypasses WP-Cron)
2. **`wp cat sync process`** — Process sync queue immediately (bypasses WP-Cron)
3. **`wp cat sync status`** — Print sync queue stats (pending, failed, dead letter counts)
4. **`wp cat status health`** — Check FAISS health and print roster stats
5. **`wp cat observations purge`** — Manually trigger observation purge job
6. **`wp cat roster list`** — List local roster entries with sync timestamps

**Implementation:**

- Use `WP_CLI::add_command()` to register commands
- Commands call corresponding services (no duplicate logic)
- Output formatted tables (use `WP_CLI\Utils\format_items()`)
- Support `--format=json` for scripting

**Done when:** Commands registered; output verified (human-readable tables, JSON format works); docs updated with command examples; PHPUnit tests verify command registration.

---

## G. Testing Matrix

### G1) PHPUnit (Backend)

**Coverage targets:**

- Controllers: ScanController, ObservationController, ConfirmController, SyncController (permissions, validation, happy/error paths)
- Services: CascadeService (similarity thresholds), AvatarGeneratorService (WebP generation, error handling)
- Repositories: RosterRepository, ObservationRepository, SyncQueueRepository (CRUD, prepared statements)
- Jobs: SyncQueueWorkerJob, RosterDeltaSyncJob, ObservationPurgeJob (backoff schedule, retention logic)
- Installers: RosterTableInstaller, ObservationTableInstaller, SyncQueueTableInstaller (idempotent re-run, foreign keys)

**Mocking:**

- `WP_Mock` for WordPress functions (`$wpdb`, `get_option`, `update_option`)
- Guzzle mock for RecognitionClient HTTP calls (stub responses, timeouts, 5xx)
- Image editor mocks for AvatarGeneratorService (return fake WebP resource)

**Done when:** >90% code coverage; all tests green; CI runs tests on PHP 8.1/8.2.

### G2) Vitest (Frontend)

**Coverage targets:**

- Hooks: useObservations, usePeopleSuggestions, useRosterStrategy, useSuggestionCache, useDeferObservation (loading, success, error states)
- Components: UnknownPeoplePanel, ObservationDetailView, FaceGrid, ConfirmLabelModal (rendering, interactions, keyboard navigation)
- Utils: suggestionCache (set, get, invalidate, expire, hit rate tracking)

**Mocking:**

- MSW (Mock Service Worker) for API endpoints (`/cat/v1/observations`, `/cat/v1/identify`, `/cat/v1/confirm`, `/cat/v1/observations/{id}/defer`)
- localStorage mock for cache tests
- React Testing Library for user interactions (fireEvent, userEvent)

**Done when:** >85% code coverage; all tests green; Storybook stories exist for all components; interaction tests verify keyboard navigation and screen reader announcements.

### G3) MSW Handlers

**File:** `js/admin/testing/mswHandlers.ts`.  
**Endpoints to mock:**

- `GET /cat/v1/observations` → paginated list
- `GET /cat/v1/observations/:id` → single observation detail
- `POST /cat/v1/observations/:id/defer` → success response
- `POST /cat/v1/identify` → suggestions with strategy_used
- `POST /cat/v1/confirm` → success with cascade_drafts
- `GET /cat/v1/roster/stats` → roster size and sync timestamp
- `GET /cat/v1/status` → health metrics

**Done when:** Handlers return realistic payloads (match API contracts); tests use handlers via `setupServer()`; handlers support error injection (simulate 500, timeout, 429).

### G4) Integration Test Scenarios

**Scenarios to cover:**

1. **FAISS-primary (150+ people):** Local roster size = 200 → `useRemoteMatching = true` → identify endpoint calls `/api/v0/suggest` → suggestions returned <200ms → cache hit on subsequent call.
2. **FAISS outage:** Backend unreachable → identify endpoint returns `503 remote_unavailable` with remediation hints → UI surfaces outage banner and queues confirmations for later once service recovers.
3. **Cold start (≤10 people):** Local roster size = 5 → remote suggestion still executes (`remote_faiss`) within target latency → caches warm quickly.
4. **Cascade drafts:** Confirm 3 observations → CascadeService finds 5 similar pending observations → drafts created with status `pending_review` → drafts appear in UI "Pending Review" section.
5. **Sync queue retry:** Confirm action enqueued → backend returns 503 → queue worker retries with backoff → succeeds on 3rd attempt → queue item removed.

**Done when:** All scenarios pass in local test environment; integration tests skip in CI (manual run only); test setup documented (requires local recognition service running).

---

## H. Definition of Done (per epic slice)

### H1) Code Quality

- All acceptance tests green (PHPUnit + Vitest)
- PHPCS clean (WordPress Coding Standards)
- ESLint/Prettier clean (no warnings)
- Type coverage >95% (TypeScript strict mode)
- No `$wpdb->query()` without `$wpdb->prepare()` (security audit)

### H2) Database

- Installer idempotent (run twice, no errors)
- Activation on clean DB creates all tables/indices successfully
- Uninstall drops tables, removes options, deletes avatar directory
- Foreign key constraints enforced
- Schema version tracked via `cat_db_version` option

### H3) Accessibility

- Modal focus management (focus trap, restore focus on close)
- Keyboard navigation across grids (arrow keys, tab, enter, esc)
- ARIA labels/roles complete (dialog, button, listbox, etc.)
- Screen reader announcements for state changes (loading, error, success)
- Color contrast ≥4.5:1 (WCAG AA)

### H4) Documentation

- Request/response examples updated under `docs/architecture/contracts/`
- API endpoint documentation (purpose, params, response, error codes)
- Settings documentation (what each setting controls, acceptable values)
- CLI command examples (usage, output samples)
- Storybook stories deployed (all components, all states)

---

## I. Concrete File Touch List

### I1) PHP Files (New/Modified)

**Database/Installers:**

- `src/Infrastructure/Database/RosterTableInstaller.php` (NEW)
- `src/Infrastructure/Database/ObservationTableInstaller.php` (NEW)
- `src/Infrastructure/Database/SyncQueueTableInstaller.php` (NEW)
- `src/Support/LifecycleManager.php` (MODIFY: orchestrate installers)

**Repositories:**

- `src/Infrastructure/Repositories/RosterRepository.php` (NEW)
- `src/Infrastructure/Repositories/ObservationRepository.php` (NEW)
- `src/Infrastructure/Repositories/SyncQueueRepository.php` (NEW)

**Controllers:**

- `src/Recognition/ScanController.php` (NEW)
- `src/Recognition/ObservationController.php` (NEW)
- `src/Recognition/ConfirmController.php` (NEW)
- `src/Roster/SyncController.php` (NEW)

**Services:**

- `src/Recognition/RecognitionClient.php` (MODIFY: add health, stats, suggest methods)
- `src/Services/AvatarGeneratorService.php` (NEW)
- `src/Services/CascadeService.php` (NEW)
- `src/Infrastructure/Storage/AvatarStorageAdapter.php` (NEW)

**Jobs:**

- `src/Jobs/FaceDetectionJob.php` (NEW)
- `src/Jobs/SyncQueueWorkerJob.php` (NEW)
- `src/Jobs/RosterDeltaSyncJob.php` (NEW)
- `src/Jobs/ObservationPurgeJob.php` (NEW)

**API/Routes:**

- `src/Infrastructure/RestApi/RouteRegistry.php` (MODIFY: register new routes)
- `src/Api/Api.php` (MODIFY: add request/response schemas)

**Admin/Settings:**

- `src/Admin/SettingsPage.php` (MODIFY: add recognition settings section)
- `src/Admin/StatusPage.php` (NEW: health dashboard)

**CLI:**

- `src/CLI/SyncCommand.php` (NEW)
- `src/CLI/StatusCommand.php` (NEW)

**Bootstrap:**

- `context-alt-text.php` (MODIFY: wire services/queues, register WP-Cron hooks)

### I2) TypeScript/TSX Files (New/Modified)

**Components:**

- `js/components/workbench/UnknownPeoplePanel.tsx` (NEW)
- `js/components/workbench/ObservationCard.tsx` (NEW)
- `js/components/workbench/ObservationDetailView.tsx` (NEW)
- `js/components/workbench/FaceGrid.tsx` (NEW)
- `js/components/workbench/ConfirmLabelModal.tsx` (NEW)
- `js/components/admin/StatusDashboard.tsx` (NEW)
- `js/components/settings/RecognitionSettings.tsx` (NEW)

**Hooks:**

- `js/hooks/useObservations.ts` (NEW)
- `js/hooks/useObservationDetail.ts` (NEW)
- `js/hooks/usePeopleSuggestions.ts` (MODIFY: add remote strategy)
- `js/hooks/useRosterStrategy.ts` (NEW)
- `js/hooks/useSuggestionCache.ts` (NEW)
- `js/hooks/useDeferObservation.ts` (NEW)

**Utils:**

- `js/utils/suggestionCache.ts` (NEW)

**API:**

- `js/api/observationApi.ts` (NEW)
- `js/api/rosterApi.ts` (MODIFY: add stats endpoint)

**Types:**

- `js/types/people-labeling.ts` (MODIFY: add IdentifyRequest/Response types)
- `js/types/observation.ts` (NEW)
- `js/types/roster.ts` (MODIFY: add stats types)

**Testing:**

- `js/admin/testing/mswHandlers.ts` (MODIFY: add observation endpoints)

### I3) Test Files (New)

**PHPUnit:**

- `tests/Infrastructure/Database/RosterTableInstallerTest.php`
- `tests/Infrastructure/Database/ObservationTableInstallerTest.php`
- `tests/Infrastructure/Database/SyncQueueTableInstallerTest.php`
- `tests/Infrastructure/Repositories/RosterRepositoryTest.php`
- `tests/Infrastructure/Repositories/ObservationRepositoryTest.php`
- `tests/Infrastructure/Repositories/SyncQueueRepositoryTest.php`
- `tests/Recognition/ScanControllerTest.php`
- `tests/Recognition/ObservationControllerTest.php`
- `tests/Recognition/ConfirmControllerTest.php`
- `tests/Recognition/RecognitionClientTest.php`
- `tests/Services/AvatarGeneratorServiceTest.php`
- `tests/Services/CascadeServiceTest.php`
- `tests/Jobs/SyncQueueWorkerJobTest.php`
- `tests/Jobs/RosterDeltaSyncJobTest.php`
- `tests/Jobs/ObservationPurgeJobTest.php`

**Vitest:**

- `js/hooks/useObservations.test.ts`
- `js/hooks/useObservationDetail.test.ts`
- `js/hooks/usePeopleSuggestions.test.ts`
- `js/hooks/useRosterStrategy.test.ts`
- `js/hooks/useSuggestionCache.test.ts`
- `js/hooks/useDeferObservation.test.ts`
- `js/components/workbench/UnknownPeoplePanel.test.tsx`
- `js/components/workbench/ObservationDetailView.test.tsx`
- `js/components/workbench/FaceGrid.test.tsx`
- `js/components/workbench/ConfirmLabelModal.test.tsx`
- `js/utils/suggestionCache.test.ts`

---

## J. Cutover Plan (Feature Flag)

### J1) Feature Flag Implementation

**Setting:** `cat_enable_remote_matching` (boolean, default true in production, false in dev)  
**Purpose:** Allow safe rollout of FAISS remote matching; fallback to local-only if disabled.  
**Files:** `src/Admin/SettingsPage.php`, `js/hooks/useRosterStrategy.ts`.

**Implementation:**

- Add checkbox in Settings > Recognition: "Prefer remote matching when available"
- Store in option `cat_recognition_settings['enable_remote_matching']`
- Backend: `RecognitionClient` checks flag before calling `/api/v0/suggest`
- Frontend: `useRosterStrategy()` respects flag (overrides roster size threshold)
- If disabled: plugin runs local-only (no remote API calls except /roster sync)

**Done when:** Flag toggleable in admin UI; backend respects flag (skips remote calls when disabled); frontend respects flag (forces local strategy); no errors when flag disabled; tests verify both states (enabled/disabled).

### J2) Telemetry & Monitoring

**Purpose:** Track strategy selection, latency, error rates for remote vs local paths.  
**Metrics to log:**

- `cat_identify_strategy` (gauge: remote_faiss | local_cosine | hybrid)
- `cat_identify_latency_ms` (histogram, labels: strategy, cache_hit)
- `cat_identify_error_rate` (counter, labels: strategy, error_type)
- `cat_suggest_cache_hit_rate` (gauge: 0-1)
- `cat_sync_queue_depth` (gauge: pending action count)

**Implementation:**

- Log to browser console in dev mode
- Option to send to external service (e.g., Sentry, Datadog) via filter hook
- Admin dashboard displays aggregated metrics (last 7 days)

**Done when:** Metrics logged on every identify call; cache hit rate calculated and displayed; error rates tracked by strategy; telemetry opt-out available in settings.

### J3) Rollback Plan

**Scenario:** Remote FAISS service unstable or latency unacceptable.  
**Action:**

1. Disable feature flag via admin UI (Settings > Recognition > uncheck "Prefer remote matching")
2. OR add to `wp-config.php`: `define('CAT_FORCE_LOCAL_MATCHING', true);`
3. Plugin immediately switches to local-only (no code deployment required)
4. Sync queue continues to process in background (eventual consistency)

**Communication:** Admin notice displayed: "Remote matching disabled, using local fallback. Sync queue will process when service recovers."

**Done when:** Rollback tested (toggle flag, verify local-only path works); admin notice renders; telemetry shows strategy switch; no data loss (queue preserves pending syncs).

---

## K. Missing Pieces Checklist (Gap Analysis)

### K1) ETag/If-None-Match Implementation

**Status:** Mentioned in roadmap, not detailed in tasks.  
**Gap:** Need concrete HTTP header handling in RecognitionClient.  
**Action:** Add to D1 (RecognitionClient):

- `getRoster()` method sends `If-None-Match: {last_etag}` header
- Parse `ETag` from 200 response, store in `cat_roster.etag` column
- Return 304 handler (skip parsing, return "up to date" message)

### K2) Offline Queue Backoff Schedule

**Status:** Mentioned "exponential backoff", not specified.  
**Gap:** Exact backoff intervals and max attempts undefined.  
**Action:** Document in D3 (SyncQueueWorkerJob):

- Backoff schedule: 5min, 15min, 1hr, 4hr, 12hr (total 5 attempts over ~17 hours)
- After 5 attempts → move to dead letter (admin alert)
- Formula: `backoff_seconds = min(300 * (3 ^ attempts), 43200)` (cap at 12 hours)

### K3) Conflict Resolution Logic

**Status:** "Remote wins" stated, not implemented.  
**Gap:** No code for comparing local vs remote state.  
**Action:** Add to D4 (RosterDeltaSyncJob):

- Compare `cat_roster.updated_at` with remote `updated_at` timestamp
- If remote newer → overwrite local (`label`, `type`, `meta`, `etag`)
- If local newer AND not synced → queue `update_roster` action (send local changes)
- If etags differ → log conflict warning, prefer remote (avoid split-brain)

### K4) Embedding Storage (Up to 10 per Person)

**Status:** Mentioned in roadmap, not in tasks.  
**Gap:** No table/column for storing multiple embeddings locally.  
**Action:** Add to B1 (schema):

- Option 1: JSON column in `cat_roster.meta` → `{embeddings: [[...], [...]]}`
- Option 2: Separate table `cat_roster_embeddings` (roster_id FK, embedding BLOB, created_at)
- Recommendation: Use Option 1 (JSON) for simplicity; append every confirmed embedding (no artificial cap).

### K5) Session Management

**Status:** `session_id` used in observations, not defined.  
**Gap:** No specification for session ID generation or lifecycle.  
**Action:** Add to C1 (ScanController):

- Generate UUID v4 on first scan in current admin session
- Store in `$_SESSION['cat_scan_session_id']` or transient `cat_session_{user_id}`
- TTL: 24 hours (expires after inactivity)
- Observations tied to session for scoped review workflow

### K6) Face Thumbnail Generation

**Status:** Mentioned in C2, not detailed.  
**Gap:** No caching strategy or storage location specified.  
**Action:** Add service `FaceThumbnailProvider`:

- Crop face bbox from original attachment
- Resize to 150×150 JPEG (80% quality)
- Store under `wp-content/uploads/context-alt-text/faces/{observation_id}.jpg`
- Cache URL in transient `cat_face_thumb_{observation_id}` (TTL: 7 days)
- Regenerate on 404 or cache miss

### K7) Capability Checks (Security)

**Status:** "manage_options" mentioned, not consistently applied.  
**Gap:** Some endpoints missing capability requirements.  
**Action:** Add to all controllers:

- Scan/Confirm/Defer: require `manage_context_alt_text` capability (custom cap)
- Roster sync: require `manage_options` (admin only)
- Observations list: require `edit_posts` (editors can review)
- Register custom cap in activation: `$role->add_cap('manage_context_alt_text');`

### K8) CLI Command Output Formatting

**Status:** "formatted tables" mentioned, not detailed.  
**Gap:** No examples of table structure or JSON format.  
**Action:** Add to F3 (CLI):

- Use `WP_CLI\Utils\format_items($items, $format, $fields)` for consistent output
- Support `--format=table` (default), `--format=json`, `--format=csv`
- Example: `wp cat roster list --format=json --fields=remote_id,label,last_sync_at`

---

## L. Priority Order for Implementation

### Phase 1: Foundation (Week 1-2)

1. B1 - Database schema (tables, installers)
2. B3 - DAO/Repository layer
3. D1 - RecognitionClient additions (health, stats, suggest)
4. I1 - Wire services in bootstrap

### Phase 2: Core API (Week 3-4)

1. C1 - Scan endpoint
2. C2 - Observations list endpoint
3. C4 - Identify endpoint (strategy selection)
4. C5 - Confirm endpoint (cascade logic)

### Phase 3: Background Jobs (Week 5)

1. D3 - Sync queue worker
2. D4 - Roster delta sync
3. D5 - Observation purge

### Phase 4: Frontend (Week 6-7)

1. E1 - Unknown People Panel
2. E2 - Observation Detail View
3. E3 - Strategy selection hook
4. E4 - Session cache
5. E5 - Confirmation Modal

### Phase 5: Polish (Week 8)

1. B2 - Avatar generation
2. F1 - Settings UI
3. F2 - Status dashboard
4. F3 - CLI commands

### Phase 6: Testing & Docs (Week 9-10)

1. G1-G4 - Test suite completion
2. H4 - Documentation
3. J1-J3 - Feature flag & cutover

---

## M. Success Metrics (Post-Launch)

### Performance

- Cold start clustering: <50ms for ≤50 faces (measured via browser perf API)
- Warm cache suggestions: <200ms end-to-end (measured via APM)
- Cache hit rate: ≥80% within session (logged to telemetry)

### Reliability

- Sync queue success rate: ≥95% (failed actions <5%)
- Outage handling: 100% of remote failures surfaced with actionable messaging (no silent degradation)
- Dead letter rate: <1% (well-tuned backoff prevents most failures)

### User Experience

- Label once → cascade to N similar faces (≥3 cascaded labels per confirmation)
- Time to confirm 50 faces: <5 minutes (vs 15+ minutes without cascade)
- Admin satisfaction: ≥4.5/5 (post-launch survey)

### Code Health

- Test coverage: ≥90% PHP, ≥85% TS
- Zero security vulnerabilities (PHPCS, ESLint security rules)
- Zero accessibility regressions (axe-core, manual testing)

---

## N. Architecture Documentation Updates

### N1) Update Backend UML ERD

**Files:** `docs/architecture/backend-uml/database-entities.mmd`, `docs/architecture/contracts/`

- Model remote roster storage (`roster_person`, `augmented_embedding`, `observation_embedding`) and relationships to WordPress mirrors.
- Capture metadata fields (embedding source, quality tier, created_at) and retention strategy for augmented embeddings.
- Document payload examples for augmented embeddings under `docs/architecture/contracts/` to keep frontend/backends aligned.
- Validate Mermaid syntax locally (no code fences, renders in Mermaid preview).

### N2) Extend Roster Service Diagram

**Files:** `docs/architecture/backend-uml/roster_service.mermaid`

- Introduce `AugmentedEmbedding` domain entity and persistence interfaces storing progressive-learning vectors.
- Add propagation service/component responsible for publishing FAISS index updates (including retry/backoff path).
- Reflect distinction between curated reference images and progressive embeddings supplied by WordPress confirmations.
- Ensure diagram legend/note clarifies how many embeddings per person are retained and eviction rules.

### N3) Amend Recognition Service Diagram

**Files:** `docs/architecture/backend-uml/recognition_service.mermaid`

- Illustrate flow from roster persistence → embedding storage → FAISS index reload (background worker or hot-reload watcher).
- Document failure handling (retry intervals, dead-letter behaviour, operator alerting) for embedding refresh pipeline.
- Show configuration knobs (auto-reload toggle, max embeddings per refresh) to mirror roadmap guardrails.
- Cross-link to recognition jobs that consume refreshed indices for `/api/v0/suggest`.

### N4) Revise Identify/Confirm Sequence

**Files:** `docs/architecture/backend-uml/recognition-identify-flow.mmd`

- Add progressive-learning loop: WordPress confirmation → `/api/v0/roster/augment` call → backend persistence update → FAISS refresh → acknowledgement payload.
- Depict queue-based propagation when backend unavailable (enqueue → worker → retry) and response semantics back to WordPress.
- Highlight caching strategy (session cache/localStorage) and how acknowledgement toggles cascade drafts on the frontend.
- Re-render sequence diagram to verify numbering and participant labels remain consistent with revised flow.

### N5) Review & Publish

**Files:** Updated UML + contracts listed above

- Run Mermaid lint/render checks after edits; fix any warnings before merge.
- Share updated diagrams with backend/WordPress leads for sign-off (note discussion outcome in PR description).
- Update `docs/architecture/backend-uml/recognition-service-audit.md` with summary of the diagram changes and version timestamp.
- Mark Epic G (roadmap) as [DONE] only after review feedback addressed and diagrams merged.

---

### End of Task List
