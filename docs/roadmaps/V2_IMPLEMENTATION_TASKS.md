``# v2 People Labeling Implementation Tasks

**Branch:** `feature/face-detection-foundation` → `feature/people-labeling-v2`  
**Status:** Ready to start (foundation complete)  
**Date:** October 22, 2025  
**Estimated Timeline:** 66 hours (~2 months part-time)

Based on `CONSOLIDATED_FACE_DETECTION_PLAN.md` and `FACE_DETECTION_FOUNDATION.md`

---

## Phase 1: Backend Recognition Service (16 hours)

### Task 1.1: Implement /suggest Endpoint (8 hours)

**Location:** `apps/recognition-service/api/routes/`

**Requirements:**

- Accept `{embeddings: float[][], topK: int, threshold: float}`
- Load FAISS index from roster embeddings
- Normalize query embeddings (L2 norm)
- Search with IndexFlatIP or HNSW
- Filter results by threshold (default 0.92)
- Return `{suggestions: [[{rosterId, display, score}], ...]}`

**Acceptance Criteria:**

- [ ] Endpoint returns top-5 matches for single embedding
- [ ] Batch processing handles 50+ embeddings in <2s
- [ ] Threshold filtering works correctly (0.92 default)
- [ ] Returns empty array if no matches above threshold
- [ ] Handles empty roster gracefully
- [ ] Unit tests cover edge cases (empty input, no roster, all below threshold)

**Files to Create/Modify:**

```
apps/recognition-service/api/routes/suggest.py
apps/recognition-service/analysis/services/faiss_search_service.py
apps/recognition-service/tests/api/test_suggest.py
```

**Reference:** Section 4.2 of CONSOLIDATED plan

---

### Task 1.2: Implement /cluster-unknowns Endpoint (6 hours)

**Location:** `apps/recognition-service/api/routes/`

**Requirements:**

- Accept `{embeddings: float[][], threshold: float?, minSamples: int?}`
- Calculate pairwise cosine distances
- Run DBSCAN or Agglomerative clustering
- Assign cluster IDs (format: `cluster-{hash}-{index}`)
- Return `{clusterIds: string[]}`
- Noise points get unique IDs (not clustered)

**Acceptance Criteria:**

- [ ] Clusters 12 similar faces into 3 groups (cold start test)
- [ ] Distance threshold configurable (default 0.6)
- [ ] Noise points return individual cluster IDs
- [ ] Deterministic cluster IDs for same input
- [ ] Handles single embedding input
- [ ] Unit tests cover clustering edge cases

**Files to Create/Modify:**

```
apps/recognition-service/api/routes/cluster_unknowns.py
apps/recognition-service/analysis/services/clustering_service.py
apps/recognition-service/tests/api/test_cluster_unknowns.py
apps/recognition-service/shared/config/clustering_config.py
```

**Reference:** Section 4.2 of CONSOLIDATED plan

---

### Task 1.3: Add Clustering Configuration (2 hours)

**Location:** `apps/recognition-service/shared/config/`

**Requirements:**

- Add clustering section to `settings.yaml`
- Support DBSCAN and Agglomerative algorithms
- Configurable threshold, min_samples, linkage method
- Environment variable overrides

**Acceptance Criteria:**

- [ ] Settings loaded at startup
- [ ] Defaults: threshold=0.6, min_samples=2, algorithm=dbscan
- [ ] Environment vars override YAML (e.g., `CLUSTER_THRESHOLD=0.7`)
- [ ] Validation errors on invalid config

**Files to Modify:**

```
apps/recognition-service/shared/config/settings.yaml
apps/recognition-service/shared/config/config.py
apps/recognition-service/tests/config/test_clustering_config.py
```

**Reference:** Section 4.2 of CONSOLIDATED plan

---

## Phase 2: Backend WordPress Plugin (10 hours) ✅ **COMPLETE**

**Status:** All backend tasks complete. Schema migration skipped (using post_meta JSON). Progressive learning backend ready.

**Completed:**

- ✅ Task 2.1: IdentifyController (8 tests, 374 total PHP tests passing)
- ✅ Task 2.2: ImageCropUtility (8 tests)
- ✅ Task 2.3: Schema Extension (skipped - using post_meta JSON)
- ✅ Task 2.4: Progressive Learning Pipeline Backend (4 sync tests)

### Task 2.1: Implement IdentifyController (4 hours) ✅ **COMPLETE**

**Location:** `apps/wp-context-alt-text/src/Recognition/`

**Requirements:**

- Register route: `POST /wp-json/cat/v1/recognition/identify`
- Validate capabilities (`upload_files`)
- Parse request: `{attachmentId, faces[{bbox, faceId?, label?}]}`
- Call ImageCropUtility for each bbox
- Call Recognition Service endpoints (embed, suggest, cluster)
- Merge results per face
- If labels provided: persist to DB + sync to FAISS
- Return `{faces[{faceId, clusterId?, suggestions[], observationId?}]}`

**Acceptance Criteria:**

- [ ] Returns 401 for unauthenticated requests
- [ ] Returns 400 for invalid attachmentId
- [ ] Returns 400 for missing bbox coordinates
- [ ] Handles recognition service errors gracefully (503)
- [ ] Persists observations when label provided
- [ ] Creates new roster person for `label.newName`
- [ ] Updates existing roster for `label.rosterId`
- [ ] Unit tests mock recognition service calls
- [ ] Integration test with real attachment

**Files to Create/Modify:**

```
apps/wp-context-alt-text/src/Recognition/IdentifyController.php
apps/wp-context-alt-text/src/Recognition/IdentifyRequest.php (DTO)
apps/wp-context-alt-text/src/Recognition/IdentifyResponse.php (DTO)
apps/wp-context-alt-text/includes/Routes/Api.php
apps/wp-context-alt-text/tests/Recognition/IdentifyControllerTest.php
```

**Reference:** Section 4.1 of CONSOLIDATED plan, `recognition-identify.json` contract

---

### Task 2.2: Implement ImageCropUtility (3 hours) ✅ **COMPLETE**

**Status:** Complete. All 8 tests passing.

**Location:** `apps/wp-context-alt-text/src/Recognition/`

**Requirements:**

- Accept attachmentId and bbox (normalized 0-1 coordinates)
- Load image via WP_Image_Editor (GD/Imagick)
- Calculate crop coordinates from bbox
- Crop region and resize to 112x112 (model input size)
- Return base64-encoded image or temp file path
- Handle orientation metadata (EXIF)

**Acceptance Criteria:**

- [ ] Crops correct region based on normalized bbox
- [ ] Resizes to 112x112 without distortion
- [ ] Handles portrait and landscape orientations
- [ ] Respects EXIF rotation
- [ ] Returns base64 string for API transport
- [ ] Cleans up temp files
- [ ] Unit tests with mock images
- [ ] Integration test with real WordPress attachment

**Files to Create/Modify:**

```
apps/wp-context-alt-text/src/Recognition/ImageCropUtility.php
apps/wp-context-alt-text/tests/Recognition/ImageCropUtilityTest.php
```

**Reference:** Section 4.1 of CONSOLIDATED plan, `recognition-identify-flow.mmd`

---

### Task 2.3: Database Schema Migration (2 hours) ✅ **SKIPPED**

**Status:** Skipped. Using existing post_meta JSON structure for observations. Clustering fields will be added to JSON schema when needed.

**Decision:** Current `RecognitionObservationRepository` uses flexible post_meta JSON storage. No DB migration required.

**Entity Taxonomy:** Roster person entities are persisted using WordPress custom taxonomy `cat_roster_entity` (not post_tag or custom table). See `docs/architecture/rules/roster_taxonomy_guide.md` for full documentation.

**Location:** `apps/wp-context-alt-text/src/Database/`

**Requirements:**

- Add columns to `cat_observation` table:
  - `cluster_group_id` VARCHAR(64) NULL
  - `suggested_roster_id` VARCHAR(64) NULL
  - `suggested_score` DECIMAL(5,4) NULL
  - `confirmed_roster_id` VARCHAR(64) NULL
  - `label_status` ENUM('unlabeled','suggested','confirmed','rejected','corrected') DEFAULT 'unlabeled'
  - `updated_at` DATETIME NOT NULL
- Update existing rows with defaults
- Add indexes for common queries

**Acceptance Criteria:**

- [ ] Migration runs without errors
- [ ] Rollback script works correctly
- [ ] Existing observations updated with `label_status='unlabeled'`
- [ ] Index on `label_status` for filtering
- [ ] Index on `cluster_group_id` for grouping
- [ ] Index on `suggested_roster_id` for suggestions
- [ ] Schema version bumped in options table

**Files to Create/Modify:**

```
apps/wp-context-alt-text/src/Database/migrations/add_observation_clustering_fields.php
apps/wp-context-alt-text/src/Database/Schema.php
apps/wp-context-alt-text/tests/Database/MigrationTest.php
```

**SQL:**

```sql
ALTER TABLE cat_observation
  ADD COLUMN cluster_group_id VARCHAR(64) NULL,
  ADD COLUMN suggested_roster_id VARCHAR(64) NULL,
  ADD COLUMN suggested_score DECIMAL(5,4) NULL,
  ADD COLUMN confirmed_roster_id VARCHAR(64) NULL,
  ADD COLUMN label_status ENUM('unlabeled','suggested','confirmed','rejected','corrected') NOT NULL DEFAULT 'unlabeled',
  ADD COLUMN updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  ADD INDEX idx_label_status (label_status),
  ADD INDEX idx_cluster_group_id (cluster_group_id),
  ADD INDEX idx_suggested_roster_id (suggested_roster_id);
```

**Reference:** Section 5 of CONSOLIDATED plan, `roster-domain-classes.mmd`

---

### Task 2.4: Progressive Learning Pipeline (3 hours) ✅ **BACKEND COMPLETE**

**Status:** Backend implementation complete. Frontend integration (toasts, UI feedback) deferred to Phase 3 (usePeopleSuggestions hook doesn't exist yet).

**Completed:**

- ✅ Recognition Service: `/roster/{id}/augment` endpoint with duplicate detection (7 tests passing)
- ✅ WordPress: `RecognitionClient::addRosterEmbedding()` method
- ✅ WordPress: `IdentifyController` inline sync on user confirmation
- ✅ Sync status tracked in post_meta (`_cat_synced_to_faiss`)
- ✅ All 92 Recognition Service tests + 374 WordPress tests passing

**Location:** `apps/recognition-service/api/routes/` and `apps/wp-context-alt-text/src/Recognition/`

**Requirements:**

**Recognition Service (Backend):**

- Implement `POST /api/v0/roster/{id}/augment` endpoint
  - Accept `{rosterId: string, observationId: string, embedding: float[], metadata?: object}`
  - Append embedding to FAISS index (IndexFlatIP or HNSW)
  - Track observationId to prevent duplicates
  - Return `{success: bool, message: string}`
  - Persist updated index to disk atomically (temp file + rename)
- Implement `POST /api/v0/roster/bulk-sync` endpoint (future enhancement)
  - Accept `{entries: [{rosterId, observationId, embedding}]}`
  - Batch append to FAISS index
  - Return summary with success/failure counts

**WordPress Plugin (Frontend):**

- Update IdentifyController to sync on user confirmation:
  - After user creates new person: sync embedding to `/roster/{id}/augment`
  - After user confirms suggestion: sync embedding to `/roster/{id}/augment`
  - After user corrects misidentification: sync embedding to `/roster/{id}/augment`
  - Provide immediate feedback via response (success toast or error message)
- Implement deduplication logic:
  - Check if observationId already synced before calling endpoint
  - Store sync status in observation metadata (post_meta: `synced_to_faiss: true|false`)
- Handle sync failures gracefully:
  - Log error with observationId and rosterId
  - Do NOT queue retry automatically (user must manually retry)
  - Show error toast to user: "Failed to sync face to roster. Please try again."

**User Consent & Feedback:**

- **No automatic syncing**: User must explicitly confirm identity (click button) before sync occurs
- **Immediate feedback**: Show toast notification on sync success ("Face added to Ana Rodriguez's profile")
- **Error transparency**: Show clear error message if sync fails with retry option
- **Dropdown selection**: Users select from dropdown of recognized entities; prevent duplicate roster entries via frontend validation

**Acceptance Criteria:**

- [x] `/roster/{id}/augment` endpoint appends to FAISS index successfully ✅
- [x] Duplicate observationIds are rejected (409 Conflict response) ✅
- [x] IdentifyController syncs embedding after user confirms identity (create/confirm/correct) ✅
- [ ] Frontend shows success toast: "Face added to [Person Name]'s profile" (Deferred to Phase 3)
- [ ] Frontend shows error toast on network failure with clear message (Deferred to Phase 3)
- [ ] Frontend prevents duplicate roster entities in PeoplePicker dropdown (Deferred to Phase 3)
- [x] Sync status tracked in observation metadata (`synced_to_faiss: true`) ✅
- [ ] Integration test: User confirms face → FAISS updates → next image auto-suggests that person (Deferred to Phase 4)
- [x] Unit tests cover duplicate detection, network failures, atomic index writes ✅

**Files to Create/Modify:**

```
# Recognition Service (Backend) - ✅ COMPLETE
apps/recognition-service/api/routes/roster.py (UPDATED - added /roster/{id}/augment endpoint)
apps/recognition-service/tests/api/test_roster_add_embedding.py (CREATED - 7 tests)

# WordPress Plugin (Frontend) - ✅ COMPLETE
apps/wp-context-alt-text/src/Recognition/IdentifyController.php (UPDATED - inline sync)
apps/wp-context-alt-text/src/Recognition/RecognitionClient.php (UPDATED - addRosterEmbedding method)
apps/wp-context-alt-text/tests/Recognition/IdentifyControllerTest.php (UPDATED - 4 sync tests added)
```

**Architecture Decisions:**

1. **Roster Index Strategy**: Append-only with user confirmation (no automatic bulk rebuild)
   - Each user confirmation immediately appends to FAISS index
   - Future enhancement: periodic rebuild after N embeddings for index optimization
2. **Deduplication**: Prevent same observationId from syncing twice

   - Recognition Service maintains set of observationIds per rosterId
   - WordPress tracks sync status in observation metadata
   - Frontend validates roster dropdown to prevent duplicate person creation

3. **No Background Jobs Required**: All operations are user-initiated

   - Face detection happens in browser (MediaPipe - instant, no backend job)
   - Recognition (embeddings/suggest/cluster) triggered on-demand when user views images via `/identify`
   - FAISS sync happens inline on user confirmation (~200ms latency acceptable for immediate feedback)
   - No silent scanning of media library (privacy + resource concerns align with CONSOLIDATED plan)
   - Existing `RecognitionJobService` remains for batch alt-text generation (separate workflow)

4. **Sync Timing**: Immediate sync on confirm with feedback
   - User confirms identity → WordPress calls `/roster/{id}/augment` → Shows toast
   - Adds latency but provides immediate feedback loop (Apple Photos-style progressive learning)
   - User sees instant confirmation that face was added to person's profile

**Reference:** Section 4.1 of CONSOLIDATED plan, `sequence-interactive-detection.mmd` (steps 56-62)

---

## Phase 3: Frontend v2 Components (30 hours)

### Task 3.1: Create Type Definitions (Already Complete ✅)

**Location:** `apps/wp-context-alt-text/js/types/people-labeling.ts`

**Status:** Created in foundation branch with 390 lines of TypeScript definitions

**Includes:**

- Core detection types (DetectedFaceFE, BoundingBox, Label, Suggestion)
- API types (IdentifyRequest, IdentifyResponse)
- Component props (PeopleOverlayProps, PeopleDrawerProps, PeoplePickerProps)
- Domain types (FaceCluster, SuggestionStack, RosterPerson, FaceObservation)
- Hook interfaces (UsePeopleSuggestionsReturn, UseFaceDetectionReturn)

---

### Task 3.2: Create usePeopleSuggestions Hook (6 hours)

**Location:** `apps/wp-context-alt-text/js/hooks/`

**Requirements:**

- Manage identify API calls to `/wp-json/cat/v1/recognition/identify`
- Convert RawDetection[] to IdentifyRequest
- Merge IdentifyResponse into DetectedFaceFE[]
- Handle loading/error states
- Support single label submission
- Support bulk confirm (multiple labels)
- Optimistic updates for better UX

**Acceptance Criteria:**

- [ ] `identifyFaces()` posts detections and updates state
- [ ] `submitLabel()` sends single label and updates face
- [ ] `bulkConfirm()` sends multiple labels in batch
- [ ] Loading state prevents duplicate requests
- [ ] Error state shows user-friendly message
- [ ] Optimistic updates revert on failure
- [ ] Unit tests with mock API responses
- [ ] Integration tests with MSW (Mock Service Worker)

**Files to Create:**

```
apps/wp-context-alt-text/js/hooks/usePeopleSuggestions.ts
apps/wp-context-alt-text/js/hooks/usePeopleSuggestions.test.ts
apps/wp-context-alt-text/js/api/recognitionApi.ts
apps/wp-context-alt-text/js/api/recognitionApi.test.ts
```

**Reference:** Section 3.4 of CONSOLIDATED plan, `sequence-interactive-detection.mmd`

---

### Task 3.3: Create PeopleOverlay Component (8 hours)

**Location:** `apps/wp-context-alt-text/js/components/workbench/`

**Requirements:**

- Render bounding boxes over image (reuse FaceDetectionDisplay positioning)
- Add "Who is this?" chip on each face
- Click chip opens PeoplePicker modal
- Show suggested name if available (e.g., "Ana Rodriguez?")
- Show confirmed name after labeling
- Keyboard navigation (Tab cycles faces, Enter opens picker)
- Focus indicator on selected face
- ARIA labels for accessibility

**Acceptance Criteria:**

- [ ] Bounding boxes position correctly (reuse FaceDetectionDisplay logic)
- [ ] Chips render with correct text ("Unknown", "Ana?", "Ana Rodriguez")
- [ ] Click chip opens PeoplePicker with correct context
- [ ] Tab key cycles through faces
- [ ] Enter key opens picker for focused face
- [ ] Escape key closes picker
- [ ] Screen reader announces face count and names
- [ ] Visual focus indicator (border + shadow)
- [ ] Works on touch devices (tap chip)
- [ ] Unit tests with React Testing Library
- [ ] Storybook stories for all states

**Files to Create:**

```
apps/wp-context-alt-text/js/components/workbench/PeopleOverlay.tsx
apps/wp-context-alt-text/js/components/workbench/PeopleOverlay.scss
apps/wp-context-alt-text/js/components/workbench/PeopleOverlay.test.tsx
apps/wp-context-alt-text/js/components/workbench/PeopleOverlay.stories.tsx
apps/wp-context-alt-text/js/components/workbench/FaceChip.tsx
apps/wp-context-alt-text/js/components/workbench/FaceChip.scss
```

**Reference:** Section 3.1 of CONSOLIDATED plan, `consolidated-detection-classes.mmd`

---

### Task 3.4: Create PeopleDrawer Component (8 hours) [COMPLETE]

**Status:** [x] Implementation complete (tests pending)

**Location:** `apps/wp-context-alt-text/js/components/workbench/`

**Requirements:**

- Right rail drawer (collapsible)
- Show clustered unknowns: "Likely same person (x12)" stacks
- Show suggestion stacks: "Ana Rodriguez? (54)" with confidence
- Each stack shows representative face thumbnail
- "Confirm All" button on suggestion stacks
- "Review" button on unknown clusters (shows all faces)
- Clicking stack highlights faces in PeopleOverlay
- Drag/drop face between stacks (reassign) - DEFERRED to Phase 4

**Acceptance Criteria:**

- [x] Drawer slides in from right (320px width)
- [x] Toggle button collapses/expands drawer
- [x] Unknown clusters render with count badge
- [x] Suggestion stacks render with avatar + score
- [x] "Confirm All" triggers bulk confirm action
- [x] "Review" expands stack to show all faces
- [x] Click stack highlights faces in overlay
- [ ] Drag face between stacks reassigns label (DEFERRED - click-based reassignment via PeoplePicker instead)
- [x] Keyboard navigation (Enter, Space on stacks and buttons)
- [x] Screen reader announces stack counts with proper ARIA labels
- [ ] Unit tests with drag/drop simulation (pending)
- [ ] Storybook stories for empty, cold start, warm start (pending)

**Files Created:**

```
[x] apps/wp-context-alt-text/js/components/workbench/PeopleDrawer.tsx (286 lines)
[x] apps/wp-context-alt-text/js/components/workbench/PeopleDrawer.scss (423 lines)
[x] apps/wp-context-alt-text/js/components/workbench/ClusterStack.tsx (122 lines)
[x] apps/wp-context-alt-text/js/components/workbench/SuggestionStack.tsx (146 lines)
[ ] apps/wp-context-alt-text/js/components/workbench/PeopleDrawer.test.tsx (pending)
[ ] apps/wp-context-alt-text/js/components/workbench/PeopleDrawer.stories.tsx (pending)
```

**Implementation Notes:**

- Follows RADIX_UI_COMPONENT_GUIDE.md patterns (no Radix primitives needed)
- Uses design tokens from `_tokens.scss` for consistent styling
- 4-space indentation enforced per instructions.md
- Arrow functions used throughout for consistency
- Responsive design: Desktop right rail, mobile bottom sheet
- High contrast mode and reduced motion support included
- Empty state messaging for zero detections
- Groups faces by clusterId (unknowns) and top suggestion rosterId
- Sorts by descending count (clusters) and confidence (suggestions)
- Placeholder avatar shows first letter of name when no image available

**Reference:** Section 3.2 of CONSOLIDATED plan, `consolidated-detection-classes.mmd`

---

### Task 3.5: Create PeoplePicker Component (6 hours) [COMPLETE]

**Status:** [x] Implementation complete (tests pending)

**Location:** `apps/wp-context-alt-text/js/components/workbench/`

**Requirements:**

- Modal/popover positioned near clicked chip
- Typeahead search input (debounced 300ms)
- Search roster by display name and aliases
- Show avatar thumbnails in results
- "Create new person" option (always visible)
- Keyboard navigation (arrow keys, Enter selects)
- Escape to close
- Show current label if correcting

**Acceptance Criteria:**

- [x] Input field auto-focused on open
- [x] Debounced search triggers after 300ms
- [x] Results filter by display name (aliases support in backend)
- [x] Avatar thumbnails load correctly with placeholder fallback
- [x] "Create new" always at top of results
- [x] Enter key selects highlighted option
- [x] Escape key closes picker
- [x] Arrow keys cycle through options (with scroll into view)
- [x] Shows "Currently: Ana Rodriguez" when correcting
- [x] Loading spinner during roster fetch
- [ ] Unit tests with debounced input simulation (pending)
- [ ] Storybook stories for empty roster, search results (pending)

**Files Created:**

```
[x] apps/wp-context-alt-text/js/components/workbench/PeoplePicker.tsx (348 lines)
[x] apps/wp-context-alt-text/js/components/workbench/PeoplePicker.scss (329 lines)
[x] apps/wp-context-alt-text/js/hooks/useRosterSearch.ts (203 lines)
[x] apps/wp-context-alt-text/js/api/rosterApi.ts (89 lines)
[ ] apps/wp-context-alt-text/js/components/workbench/PeoplePicker.test.tsx (pending)
[ ] apps/wp-context-alt-text/js/hooks/useRosterSearch.test.ts (pending)
[ ] apps/wp-context-alt-text/js/components/workbench/PeoplePicker.stories.tsx (pending)
```

**Implementation Notes:**

- Follows RADIX_UI_COMPONENT_GUIDE.md patterns (no Radix Dialog needed - custom modal)
- Uses design tokens from `_tokens.scss` for consistent styling
- 4-space indentation enforced per instructions.md
- Arrow functions used throughout for consistency
- Debouncing implemented with useRef timers (300ms default)
- Search hook automatically fetches all roster on mount
- Abort controller cancels previous requests on new search
- Modal centered with overlay backdrop (fixed positioning)
- Keyboard navigation with scrollIntoView for highlighted items
- Avatar fallback shows first letter of name
- "Create new" option highlighted with "+" icon
- Loading state with spinner animation
- Empty states for "Start typing" and "No results found"
- High contrast mode and reduced motion support

**Reference:** Section 3.1 of CONSOLIDATED plan, `sequence-interactive-detection.mmd`

---

### Task 3.6: Integrate into WorkbenchApp [COMPLETE] ✅

**Location:** `apps/wp-context-alt-text/js/components/workbench/`

**Requirements:**

- Add PeopleOverlay and PeopleDrawer to WorkbenchApp
- Wire up usePeopleSuggestions hook
- Connect face detection (useFaceDetection) to identify flow
- Remove v1 RecognitionModeSelector component
- Update routing (no mode toggle needed)

**Acceptance Criteria:**

- [x] Face detection triggers on image selection
- [x] PeopleOverlay renders over image
- [x] PeopleDrawer appears in right rail
- [x] Labels persist correctly
- [x] Bulk confirm works end-to-end
- [x] v1 components removed (RecognitionModeSelector, InteractiveFaceDetection, FaceLabelingPanel)
- [x] No console errors
- [ ] E2E test covers full flow (deferred to Task 4.1)

**Implementation Summary:**

Created `PeopleLabelingView.tsx` (284 lines) as a full-screen single-image labeling interface that integrates:

- useFaceDetection hook for MediaPipe face detection
- usePeopleSuggestions hook for face identification state
- PeopleOverlay component for face chips display
- PeopleDrawer component for clusters and suggestions
- PeoplePicker component for selecting/creating persons

Modified `WorkbenchApp.tsx` to conditionally render PeopleLabelingView when `labelingItem` state is set.

Modified `MediaList.tsx` to add "Label People" button in actions cell that triggers labeling view.

Created `PeopleLabelingView.scss` (204 lines) with full-screen fixed positioning, loading/error states, and responsive layout.

**Key Technical Details:**

- Converts MediaPipe `FaceDetection` to `RawDetection` format for identify API
- Parses `item.id` (string) to `attachmentId` (number) for API calls
- Uses `item.thumbnailUrl` for image display
- Gets `restNonce` from `window.catAltText.restNonce` global
- Wires all callbacks: face click, picker select/create, cluster/suggestion clicks, bulk confirm

**Files Created:**

```
apps/wp-context-alt-text/js/components/workbench/PeopleLabelingView.tsx (284 lines)
apps/wp-context-alt-text/js/components/workbench/PeopleLabelingView.scss (204 lines)
```

**Files Modified:**

```
apps/wp-context-alt-text/js/components/workbench/WorkbenchApp.tsx
apps/wp-context-alt-text/js/components/workbench/MediaList.tsx
```

**Files to Delete:**

```
(No v1 components existed to delete)
```

**Reference:** Section 14 of CONSOLIDATED plan

---

## Phase 4: Testing & Validation (10 hours)

### Task 4.1: Component Unit Tests [COMPLETE] ✅

**Location:** `apps/wp-context-alt-text/js/components/workbench/`

**Requirements:**

- Unit tests for PeoplePicker component
- Search functionality (typeahead, debouncing)
- User interactions (select person, create new, keyboard navigation)
- Roster loading and error states
- Avatar display and positioning
- MSW for API mocking

**Implementation Summary:**

Created comprehensive unit test suite for PeoplePicker component with 19 tests covering:

- Basic rendering (modal, search input, keyboard hints)
- Roster loading (initial fetch, error handling)
- Search functionality (filtering, debouncing, create new option)
- User interactions (select person, create new, keyboard navigation, backdrop close)
- Current person display (showing existing label when correcting)
- Avatar display (placeholder vs image)
- Custom positioning

All tests use MSW (Mock Service Worker) for API mocking instead of mocking hooks, providing more realistic integration testing. Tests verify:

- Correct API calls to `/wp-json/cat/v1/roster` and `/wp-json/cat/v1/roster/search`
- Proper debouncing (300ms delay) on search input
- Keyboard navigation (↑↓ arrows, Enter to select, Escape to close)
- "Create new:" option appears when typing and no exact match found
- Avatar images display when `avatarUrl` provided, fallback to initials otherwise
- Custom positioning via `position` prop applies inline styles

**Files Created:**

```
apps/wp-context-alt-text/js/components/workbench/PeoplePicker.test.tsx (465 lines, 19 tests)
```

**Test Results:** ✅ All 19 tests passing

---

### Task 4.2: Additional Component Tests (2 hours)

**Requirements:**

- Unit tests for remaining v2 components
- PeopleOverlay: face chip rendering, click handlers, positioning
- PeopleDrawer: cluster/suggestion stacks, drawer toggle, bulk confirm
- ClusterStack: unknown face grouping, click handlers
- SuggestionStack: FAISS matches, confidence display, bulk actions
- FaceChip: label display, state variations (unknown, suggested, confirmed)

**Files to Create:**

```
apps/wp-context-alt-text/js/components/workbench/PeopleOverlay.test.tsx
apps/wp-context-alt-text/js/components/workbench/PeopleDrawer.test.tsx
apps/wp-context-alt-text/js/components/workbench/ClusterStack.test.tsx
apps/wp-context-alt-text/js/components/workbench/SuggestionStack.test.tsx
apps/wp-context-alt-text/js/components/workbench/FaceChip.test.tsx
```

---

### Task 4.3: Hook Integration Tests (2 hours)

**Requirements:**

- Integration tests for custom hooks
- usePeopleSuggestions: identify flow, label submission, state management
- useRosterSearch: debouncing, API integration, error handling
- Test with MSW for realistic API mocking

**Files to Create:**

```
apps/wp-context-alt-text/js/hooks/usePeopleSuggestions.test.tsx
apps/wp-context-alt-text/js/hooks/useRosterSearch.test.tsx
```

---

### Task 4.4: Contract Tests (3 hours)

**Requirements:**

- Frontend IdentifyRequest matches JSON schema
- Backend IdentifyResponse matches JSON schema
- TypeScript types align with PHP DTOs
- Recognition Service responses match expected format

**Files to Create:**

```
apps/wp-context-alt-text/tests/contract/identify-request.test.ts
apps/wp-context-alt-text/tests/contract/identify-response.test.ts
apps/wp-context-alt-text/tests/Recognition/IdentifyContractTest.php
```

---

### Task 4.5: Manual E2E Test Documentation (1 hour)

**Requirements:**

Document manual testing scenarios for:

- Cold start flow (no roster, create first person, FAISS sync, suggestions appear)
- Warm start flow (existing roster, immediate suggestions, bulk confirm, corrections)
- Error scenarios (network failures, detection errors, API unavailable)
- Edge cases (no faces detected, empty roster, large batch operations)

**Files to Create:**

```
docs/testing/manual-e2e-test-scenarios.md
```

---

### Task 4.2: E2E Test - Warm Start Flow (2 hours)

**Requirements:**

- Roster has 5 people
- User selects 30 images
- Suggestions appear immediately
- User bulk confirms 12 faces
- User corrects 2 misfits
- All labels persist correctly

**Files to Create:**

```
apps/wp-context-alt-text/tests/e2e/people-labeling-warm-start.spec.ts
```

---

### Task 4.3: Contract Tests (3 hours)

**Requirements:**

- Frontend IdentifyRequest matches JSON schema
- Backend IdentifyResponse matches JSON schema
- TypeScript types align with PHP DTOs
- Recognition Service responses match expected format

**Files to Create:**

```
apps/wp-context-alt-text/tests/contract/identify-request.test.ts
apps/wp-context-alt-text/tests/contract/identify-response.test.ts
apps/wp-context-alt-text/tests/Recognition/IdentifyContractTest.php
```

---

### Task 4.4: Performance Tests (2 hours)

**Requirements:**

- FAISS search with 1k roster entries: <100ms
- FAISS search with 10k roster entries: <500ms
- Clustering 50 faces: <2s
- Identify endpoint (50 faces): <5s total
- Bulk confirm 100 faces: <1s

**Files to Create:**

```
apps/recognition-service/tests/performance/test_faiss_search.py
apps/recognition-service/tests/performance/test_clustering.py
apps/wp-context-alt-text/tests/Performance/IdentifyPerformanceTest.php
```

---

## Phase 5: Polish & Documentation (4 hours)

### Task 5.1: Accessibility Audit (2 hours)

**Requirements:**

- Keyboard navigation works in all components
- Screen reader announces all actions
- Focus indicators visible
- Color contrast meets WCAG 2.1 AA
- Touch targets ≥44px
- Live regions announce bulk actions

**Checklist:**

- [ ] axe DevTools scan passes
- [ ] VoiceOver testing on macOS
- [ ] NVDA testing on Windows
- [ ] Keyboard-only navigation test
- [ ] High contrast mode test
- [ ] Focus trap in PeoplePicker modal

---

### Task 5.2: Update Documentation (2 hours)

**Requirements:**

- Update README with v2 features
- Add user guide for People labeling
- Document API endpoints (OpenAPI spec)
- Add migration guide from v1

**Files to Create/Modify:**

```
apps/wp-context-alt-text/docs/user-guide/people-labeling.md
apps/wp-context-alt-text/docs/api/recognition-identify.md
apps/wp-context-alt-text/docs/migration/v1-to-v2.md
apps/wp-context-alt-text/README.md
```

---

## Critical Path Dependencies

```
Backend Recognition Service (16h)
  ↓
Backend WordPress Plugin (10h)
  ↓
Database Migration (included in WP phase)
  ↓
Frontend Types (DONE ✅)
  ↓
[Parallel] usePeopleSuggestions (6h) + PeopleOverlay (8h) + PeopleDrawer (8h) + PeoplePicker (6h)
  ↓
WorkbenchApp Integration (2h)
  ↓
Testing (10h)
  ↓
Polish (4h)
```

**Total Estimated Time:** 66 hours

---

## Success Metrics

### Performance

- [ ] MediaPipe detection: <400ms per image (DONE ✅)
- [ ] First model load: <4s (DONE ✅)
- [ ] FAISS search (1k roster): <100ms
- [ ] Identify endpoint (50 faces): <5s
- [ ] Bulk confirm (100 faces): <1s

### UX Metrics (vs v1 baseline)

- [ ] Avg clicks per labeled person: –40%
- [ ] Time to first 10 named persons (cold start): –50%
- [ ] Suggestion acceptance after 20 labels: ≥85%
- [ ] Abandonment on first run: –30%

### Quality

- [ ] All unit tests passing (>90% coverage)
- [ ] E2E tests passing (cold start + warm start)
- [ ] Contract tests passing (FE ↔ BE alignment)
- [ ] Performance tests passing (all thresholds met)
- [ ] Accessibility audit passing (WCAG 2.1 AA)
- [ ] No console errors in production build

---

## Risk Mitigation

### Technical Risks

**Risk:** FAISS search too slow with large roster (10k+ entries)  
**Mitigation:** Use HNSW index instead of Flat, benchmark early, optimize threshold

**Risk:** Clustering produces too many groups (noise)  
**Mitigation:** Tune DBSCAN parameters, provide UI to merge clusters manually

**Risk:** Server-side cropping fails with malformed images  
**Mitigation:** Validate image format, graceful degradation, error logging

**Risk:** Frontend bundle size increases >1.5MB  
**Mitigation:** Lazy load PeopleDrawer, code-split PeoplePicker, optimize MediaPipe loader

### UX Risks

**Risk:** Users confused by automatic suggestions  
**Mitigation:** Add tooltip on first use, "Learn more" link, clear visual indicators

**Risk:** Bulk confirm too aggressive (high misfit rate)  
**Mitigation:** Require manual review for score <0.95, show confidence badges

**Risk:** Cold start takes too long (>10 minutes to label 50 faces)  
**Mitigation:** Prioritize clustering quality, suggest "name representative faces first"

---

## Next Steps (Immediate)

1. **Create feature branch:**

   ```bash
   git checkout feature/face-detection-foundation
   git checkout -b feature/people-labeling-v2
   ```

2. **Start with backend (critical path):**

   - Task 1.1: Implement /suggest endpoint
   - Task 1.2: Implement /cluster-unknowns endpoint

3. **Parallel track (if multiple developers):**

   - Backend: Tasks 1.1-1.3 (Recognition Service)
   - WordPress: Tasks 2.1-2.4 (Plugin endpoints + DB)
   - Frontend: Tasks 3.2-3.5 (Components, can stub API responses)

4. **Daily standup questions:**

   - What did you complete yesterday?
   - What are you working on today?
   - Any blockers? (API contract mismatches, performance issues, etc.)

5. **Weekly milestones:**
   - Week 1: Backend Recognition Service complete + tested
   - Week 2: WordPress Plugin complete + DB migration
   - Week 3: Frontend components complete + integrated
   - Week 4: Testing complete + polish
   - Week 5: Production deployment + monitoring

---

**Status:** ✅ Task list ready. Foundation complete. Ready to begin Phase 1.
