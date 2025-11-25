# Assisted Face Identification - Implementation Tasks

**Branch**: `subfeature/assisted-face-id` (branched from `feature/face-detection-foundation`)

**Vision**: Deliver an Apple Photos-style assisted labeling flow that groups visually similar unknown faces, guides users through confirmation, and cascades identities across the media library with minimal manual effort.

**Guiding Principles**:

- Accuracy over volume: surface high-confidence clusters first
- Explicit user control: no auto-labeling without confirmation
- Resource awareness: support throttled analysis of selected images/albums
- Progressive disclosure: start with basic grouping, phase in automation after telemetry validation

---

## 📊 Progress Overview

### Phase 0: Pre-Implementation Alignment

- ✅ Task 0.1: Architecture Review (Complete)
- ✅ Task 0.2: Data Models & API Contracts (Complete)

### Phase 1: Unknown Face Discovery & Clustering

- ✅ Task 1.1: Database Schema (Complete)
- ✅ Task 1.2: Unknown Faces Repository (Complete)
- ✅ Task 1.3: Batch Face Scanning Endpoint (Complete)
- ✅ Task 1.4: Frontend Clustering Module (Complete)
- ✅ Task 1.5: Clustering Service Abstraction (Complete)
- ✅ Task 1.6: Clusters List Endpoint (Complete)
- ✅ Task 1.7: "Unknown People" UI Panel (Complete)

**Phase 1 Status**: ✅ **Complete** (7/7 tasks done)

### Phase 2: Assisted Identification Workflow

- 🔄 Task 2.1: Cluster Detail View (In Progress - 70% complete)
- ⏳ Task 2.2: Roster Suggestion Endpoint (To Do)
- ⏳ Task 2.3: Confirmation Modal (To Do)
- ⏳ Task 2.4: Cluster Confirmation Backend (To Do)
- ⏳ Task 2.5: Cascade Update for Remaining Faces (To Do)

**Phase 2 Status**: 🔄 **In Progress** (1/5 tasks in progress, 4 pending)

### Phase 3: Bulk Review & Automation

- ⏳ All tasks pending (Phase 2 prerequisite)

### Phase 4: Performance, Quality & Accessibility

- ⏳ All tasks pending (Phase 3 prerequisite)

### Phase 5: Documentation & Operations

- ⏳ All tasks pending (Phase 4 prerequisite)

**Overall Progress**: 8/32 tasks complete (25%), 1 in progress

---

## 🎉 Recently Completed

### Latest Work (Current Branch)

- ✅ **Phase 1 Complete**: All unknown face discovery and clustering infrastructure delivered

  - Database tables, repositories, and domain entities
  - REST endpoints for scanning and cluster retrieval
  - Frontend clustering algorithm with performance benchmarks
  - Unknown People panel with cluster cards and navigation
  - Comprehensive PHPUnit and Vitest test coverage

- 🔄 **Task 2.1 Progress**: Cluster Detail View foundational work
  - Interactive face grid with keyboard navigation
  - Multi-selection with visual feedback
  - Loading, error, and retry states
  - Integration with workbench navigation

### Next Milestone

**Target**: Complete Phase 2 (Assisted Identification Workflow)

- Priority: Implement roster suggestion endpoint (Task 2.2)
- Priority: Build confirmation modal with face selection refinement (Task 2.3)
- Priority: Wire backend confirmation persistence (Task 2.4)

---

## Phase 0: Pre-Implementation Alignment

### Task 0.1: Review Architecture & Constraints

**Status**: ⏳ To Do  
**Description**: Familiarize with existing architecture before implementing new features.

**Actions**:

1. Read `docs/architecture/rules/instructions.md` for architectural guardrails
2. Review `apps/wp-context-alt-text/js/types/people-labeling.ts` for current face detection types
3. Study `src/Recognition/IdentifyController.php` for existing observation persistence patterns
4. Examine `js/hooks/useRosterSearch.ts` and `js/api/rosterApi.ts` for roster management patterns
5. Check `apps/recognition-service/analysis/workflow/` for backend clustering capabilities

**Acceptance Criteria**:

- Understand separation between frontend (MediaPipe) and backend (FAISS) processing
- Know where face embeddings are stored and how they're retrieved
- Understand current RosterPerson and FaceObservation data models

---

### Task 0.2: Define Data Models & API Contracts

**Status**: ✅ Done  
**Description**: Establish new data structures for unknown faces, clusters, and suggestions.

**Actions**:

1. Added TypeScript models in `js/types/face-clustering.ts` covering `UnknownFace`, `ClusterSummary`, `ClusterFaceDetail`, and related suggestion/sample-face types (linked to docs contracts).
2. Authored REST API contracts in `docs/architecture/contracts/clustering-api.md`, documenting scan, cluster listing/detail, confirm, and split routes with request/response samples.
3. Documented recognition-service clustering contracts in `docs/architecture/contracts/recognition-clustering.md` for FAISS `/api/v0/cluster` and `/api/v0/suggest` endpoints.

**Acceptance Criteria**:

- Interfaces exported and consumed by new hooks/components ✅
- Contracts include examples and align with implemented endpoints ✅
- Frontend/back-end teams reviewed during feature branch sync ✅

---

## Phase 1: Unknown Face Discovery & Clustering

### Task 1.1: Create Unknown Faces Database Schema

**Status**: ✅ Done  
**Description**: Add the WordPress table used to persist unknown face detections. Because the project is still greenfield, install the table directly during plugin activation (no migration history required).

**Actions**:

1. Implemented `src/Infrastructure/Database/UnknownFaceTableInstaller.php` with the schema described and wired through `ContextAltText\Support\LifecycleManager`.
2. Added domain entity `src/Domain/Clustering/UnknownFace.php` and repository coverage (`UnknownFaceRepositoryTest`) validating persistence.
3. Added installer PHPUnit coverage under `tests/Infrastructure/Database/UnknownFaceTableInstallerTest.php` to assert SQL shape and idempotency against the WPDB stub.

**Acceptance Criteria**:

- Activation installs the schema on a clean database ✅
- Installer re-run is idempotent ✅
- Domain object + repository integration covered by unit tests ✅

---

### Task 1.2: Build Unknown Faces Repository

**Status**: ✅ Done  
**Description**: Create data access layer for unknown face CRUD operations.

**Actions**:

1. Added `src/Infrastructure/Repositories/UnknownFaceRepository.php` with insert/update, cluster filters, attachment filters, and resolution helpers.
2. Normalized JSON handling and timestamp formatting; all SQL issued via `$wpdb->prepare()`.
3. Covered behaviour with `tests/Infrastructure/Repositories/UnknownFaceRepositoryTest.php` (query assertions driven by the WPDB stub).

**Acceptance Criteria**:

- Repository methods use prepared statements ✅
- Queries target the expected tables/columns ✅
- Tests cover happy path + edge cases ✅
- Implementation matches repository conventions ✅

---

### Task 1.3: Implement Batch Face Scanning Endpoint

**Status**: ✅ Done  
**Description**: Add REST endpoint to trigger face detection on selected media items.

**Actions**:

1. Added `src/Recognition/ScanController.php` with capability checks, payload validation, batch limits, and queue dispatch.
2. Registered `POST /wp-json/cat/v1/recognition/scan` in `Api::register_routes()` guarded by an `upload_files` permission callback.
3. Introduced face detection infrastructure:
   - `src/Recognition/FaceDetectionQueue.php` interface
   - `src/Jobs/FaceDetectionJob.php`
   - `src/Recognition/SynchronousFaceDetectionQueue.php`
   - `src/Recognition/FaceDetectionPipeline.php` + `NullFaceDetectionPipeline`
4. Added PHPUnit coverage:
   - `tests/Recognition/ScanControllerTest.php` (permissions, validation, queue payload)
   - `tests/Jobs/FaceDetectionJobTest.php` (pipeline-to-repository persistence)

**Files to Create**:

- `src/Recognition/ScanController.php` ✅
- `src/Jobs/FaceDetectionJob.php` ✅
- `src/Recognition/FaceDetectionQueue.php` ✅
- `src/Recognition/SynchronousFaceDetectionQueue.php` ✅
- `src/Recognition/FaceDetectionPipeline.php` ✅
- `src/Recognition/NullFaceDetectionPipeline.php` ✅
- `tests/Recognition/ScanControllerTest.php` ✅
- `tests/Jobs/FaceDetectionJobTest.php` ✅

**Files to Modify**:

- `context-alt-text.php` (wire pipeline/queue/controller)
- `src/Support/LifecycleManager.php` (already updated in previous task)
- `src/Api/Api.php` (route registration)
- `js/admin/testing/mswHandlers.ts` (add mock)

**Acceptance Criteria**:

- Endpoint validates batch size and permissions
- Jobs enqueue successfully with correct priority
- Detected faces saved to unknown_faces table with embeddings
- PHPUnit tests >90% coverage, all MSW mocks working
- Rate limiting prevents abuse (max 5 requests/minute per user)

---

### Task 1.4: Implement Frontend Clustering Module

**Status**: ✅ Done  
**Description**: Create lightweight clustering for <50 faces using MediaPipe embeddings.

**Actions**:

1. Delivered `js/utils/faceClustering.ts` with cosine similarity helpers, single-linkage clustering, deterministic cluster IDs, and merge utilities.
2. Expanded `js/utils/faceClustering.test.ts` to cover identical/dissimilar vectors, threshold sensitivity, performance (50 face benchmark), and edge cases.

**Acceptance Criteria**:

- Deterministic output + cosine reference parity verified via tests ✅
- 50-face benchmark executes within 100 ms under Vitest ✅
- Edge cases (empty input/single face) handled gracefully ✅

---

### Task 1.5: Create Clustering Service Abstraction

**Status**: ✅ Done  
**Description**: Add service layer that routes to frontend or backend clustering based on dataset size.

**Actions**:

1. Implemented `src/Domain/Clustering/ClusteringService.php` with routing logic (≤50 faces returns local payload, otherwise proxies to recognition service and persists cluster IDs).
2. Added `requestClustering()` on `src/Roster/RosterClient.php` and wired through plugin bootstrap.
3. Authored `tests/Domain/Clustering/ClusteringServiceTest.php` verifying local vs remote routing, persistence, and remote failure fallback (now also supplying attachment dimensions for thumbnails).

**Acceptance Criteria**:

- Routing + persistence confirmed in tests ✅
- Remote failure falls back to local strategy ✅
- Face metadata includes attachment dimensions for downstream thumbnailing ✅

---

### Task 1.6: Build Clusters List Endpoint

**Status**: ✅ Done  
**Description**: Add REST endpoint to retrieve unknown face clusters with metadata.

**Actions**:

1. Implemented `src/Recognition/ClusterController.php` with `listClusters()` plus thumbnail support via `FaceThumbnailProvider`.
2. Registered `GET /wp-json/cat/v1/clusters` (and legacy alias) in `Api::register_routes()`.
3. Added `src/Recognition/CachedFaceThumbnailProvider.php` and MSW handler to provide mock responses.
4. Created `tests/Recognition/ClusterControllerTest.php` to validate permissions, pagination, and payload shape.

**Files to Modify**:

- `src/Infrastructure/RestApi/RouteRegistry.php`
- `js/admin/testing/mswHandlers.ts`

**Acceptance Criteria**:

- Endpoint returns clusters with correct metadata ✅
- Thumbnails generated and cached through provider ✅
- Pagination works correctly ✅
- MSW mocks return realistic data for tests/stories ✅

---

### Task 1.7: Create "Unknown People" UI Panel

**Status**: ✅ Done  
**Description**: Add workbench panel showing cluster cards for unknown faces.

**Actions**:

- `js/hooks/useUnknownClusters.ts` fetches `/cat/v1/clusters`, converts payload to `ClusterSummary`, and exposes loading/error state.
- `js/components/workbench/ClusterCard.tsx` renders accessible card with thumbnail, confidence badge, and pressed state.
- `js/components/workbench/UnknownPeoplePanel.tsx` displays loading/empty/error states and integrates with `WorkbenchApp`.
- Added Vitest coverage (`UnknownPeoplePanel.test.tsx`, `useUnknownClusters.test.tsx`) and Storybook scenarios.
- Workbench now renders the panel alongside recognition actions.

**Acceptance Criteria**:

- Panel renders cluster cards with sample faces and confidence labels ✅
- Loading/empty/error states covered by tests ✅
- Clicking a card emits `onSelectCluster` and highlights selection ✅
- Storybook demonstrates default/empty/selected states ✅
- Panel participates in Workbench layout with keyboard-accessible controls ✅

---

## Phase 2: Assisted Identification Workflow

### Task 2.1: Build Cluster Detail View

**Status**: 🔄 In Progress  
**Description**: Create view showing all faces in a cluster with selection and drag-drop capabilities.

**Completed Work**:

- ✅ Created `ClusterDetailView.tsx` with basic structure, loading/error/empty states
- ✅ Implemented `useClusterDetail` hook fetching from `/wp-json/cat/v1/clusters/{id}`
- ✅ Built `FaceGrid.tsx` component with thumbnail rendering and keyboard navigation
- ✅ Added multi-selection support (click, space to toggle)
- ✅ Integrated with `WorkbenchApp` - panel switches to detail view on cluster selection
- ✅ Added retry capability when cluster loading fails
- ✅ Created component tests (`ClusterDetailView.test.tsx`, `FaceGrid.test.tsx`)
- ✅ Added interaction tests (`ClusterDetailView.interaction.test.tsx`)

**Remaining Work**:

- ⏳ Add drag-and-drop support for moving faces between clusters
- ⏳ Implement suggestion chip display when backend provides recommendations
- ⏳ Add "Label Selected" confirmation flow triggering modal
- ⏳ Add "Review Later" action for deferring ambiguous clusters
- ⏳ Create Storybook stories demonstrating all states and interactions
- ⏳ Expand test coverage for drag-drop and advanced selection patterns

**Actions**:

1. Create `js/components/workbench/ClusterDetailView.tsx`:

   ```tsx
   export function ClusterDetailView({ clusterId }: { clusterId: string }) {
     const { cluster, faces } = useClusterDetail(clusterId);
     const [selectedFaces, setSelectedFaces] = useState<Set<string>>(
       new Set(faces.map((f) => f.id))
     );

     return (
       <div className="cat-cluster-detail">
         <header>
           <h2>{cluster.face_count} Similar Faces</h2>
           {cluster.suggestion && <SuggestionChip {...cluster.suggestion} />}
         </header>

         <FaceGrid
           faces={faces}
           selectedFaces={selectedFaces}
           onSelectionChange={setSelectedFaces}
           onDragStart={handleDragStart}
         />

         <footer>
           <Button onClick={() => confirmIdentity(selectedFaces)}>
             Label Selected ({selectedFaces.size})
           </Button>
         </footer>
       </div>
     );
   }
   ```

2. Create `js/components/workbench/FaceGrid.tsx`:
   - Lazy load face thumbnails (intersection observer)
   - Checkbox for each face (keyboard accessible)
   - Drag handle for moving faces to other clusters
   - Grid layout (CSS Grid, 4-6 columns responsive)
3. Implement drag-and-drop:
   - Use React DnD or native HTML5 drag APIs
   - Show drop zones for existing clusters
   - Update selection state on drop
4. Add keyboard navigation:
   - Arrow keys to navigate grid
   - Space to toggle selection
   - Enter to confirm
   - Escape to cancel
5. Write component tests:
   - Test grid rendering with various face counts
   - Test selection (click, shift-click for range, ctrl-click for multi)
   - Test drag-drop behavior (mock DnD events)
   - Test keyboard navigation
6. Create Storybook stories for different cluster sizes

**Current Progress**:

- ✅ Delivered `useClusterDetail` hook fetching cluster details with retry logic
- ✅ Implemented REST endpoint `GET /wp-json/cat/v1/clusters/{id}` with face metadata
- ✅ Created `ClusterDetailView` component rendering thumbnails, status states, retry/close actions
- ✅ Built `FaceGrid` component with lazy thumbnail loading and keyboard-accessible multi-selection
- ✅ Integrated detail view in `WorkbenchApp` - displays when cluster selected in `UnknownPeoplePanel`
- ✅ Added comprehensive Vitest tests covering selection mechanics, keyboard navigation, and error states
- ✅ Selection persists intelligently when cluster data refreshes (preserves valid selections)

**Remaining Work**:

- ⏳ Implement drag-and-drop between clusters and cluster split functionality
- ⏳ Add suggestion chips when backend provides roster person recommendations
- ⏳ Create selection toolbar with "Label Selected ({count})" button triggering confirmation modal
- ⏳ Add "Review Later" action allowing users to defer ambiguous clusters
- ⏳ Expand keyboard shortcuts (Cmd/Ctrl+A for select all, arrow+shift for range selection)
- ⏳ Create Storybook stories for advanced selection flows and drag-drop scenarios
- ⏳ Add E2E tests covering complete review-to-confirmation workflow

**Files to Create**:

- `js/components/workbench/FaceGrid.tsx`
- `js/components/workbench/SuggestionChip.tsx`
- `js/components/workbench/ClusterDetailView.stories.tsx`

**Acceptance Criteria**:

- Grid displays faces with lazy loading and keyboard navigation
- Selection state managed (single/multi/range)
- Drag-drop allows moving faces between clusters
- Suggestion chip visible when backend provides recommendations
- Tests cover all interaction modes

---

### Task 2.2: Add Roster Suggestion Endpoint

**Status**: 🔄 In Progress  
**Description**: Create endpoint to get roster person suggestions for a cluster.

**Actions**:

1. Create method in `src/Recognition/ClusterController.php`:

   ```php
   public function getClusterSuggestions(WP_REST_Request $request): WP_REST_Response {
     $clusterId = $request->get_param('id');
     $faces = $this->repository->findFacesByCluster($clusterId);

     // Get embeddings for all faces
     $embeddings = array_map(fn($f) => $f->getEmbedding(), $faces);

     // Call recognition service to get suggestions
     $suggestions = $this->rosterClient->getSuggestions($embeddings);

     // Calculate confidence based on embedding similarity
     return new WP_REST_Response([
       'suggestions' => array_map(function($s) {
         return [
           'roster_id' => $s['roster_id'],
           'display_name' => $s['display_name'],
           'confidence' => $s['confidence'], // 0.0 - 1.0
           'confidence_level' => $this->getConfidenceLevel($s['confidence']),
           'match_count' => $s['match_count']
         ];
       }, $suggestions)
     ]);
   }

   private function getConfidenceLevel(float $confidence): string {
     if ($confidence >= 0.9) return 'high';
     if ($confidence >= 0.7) return 'medium';
     return 'low';
   }
   ```

2. Add recognition service method in `src/Roster/RosterClient.php`:
   ```php
   public function getSuggestions(array $embeddings): array {
     // POST to /api/v0/suggest
     // Request: { embeddings: [[...], [...]] }
     // Response: [{ roster_id, display_name, confidence, match_count }]
   }
   ```
3. Register route: `GET /wp-json/cat/v1/clusters/{id}/suggestions`
4. Write PHPUnit tests:
   - Test with various confidence levels
   - Test with no matches (empty roster)
   - Test error handling (service unavailable)
5. Add MSW mock returning different confidence scenarios

**Files to Modify**:

- `src/Recognition/ClusterController.php`
- `src/Roster/RosterClient.php`
- `tests/Recognition/ClusterControllerTest.php`
- `js/admin/testing/mswHandlers.ts`

**Progress Update (mar 2025 branch)**:

- ✅ Added `ClusteringEngine::getClusterSuggestions()` with implementation in `ClusteringService` calling recognition embeddings/suggest APIs and aggregating matches per roster person.
- ✅ Registered `GET /wp-json/cat/v1/clusters/{id}` and `/wp-json/cat/v1/clusters/{id}/suggestions` REST routes returning cluster metadata and suggestion payloads.
- ✅ Expanded PHPUnit coverage (`ClusteringServiceTest`, `ClusterControllerTest`) verifying aggregation, capability checks, and response shape; new MSW handler stubs suggestions for UI tests.

**Remaining Work**:

- ⏳ Frontend hook to request `/clusters/{id}/suggestions` and surface suggestion chips inside the detail view.
- ⏳ Extend MSW fixtures/storybook scenarios to exercise multiple confidence tiers once UI consumes the endpoint.
- ⏳ Wire suggestion confidence/face match metadata into confirmation modal when implemented (Task 2.3).

**Acceptance Criteria**:

- Suggestions calculated based on embedding similarity ✅
- Confidence levels categorized correctly ✅
- Endpoint handles empty results gracefully ✅
- Tests cover high/medium/low confidence scenarios ✅
- MSW mocks support different test cases ✅

---

### Task 2.3: Build Confirmation Modal

**Status**: ⏳ To Do  
**Description**: Create modal for confirming cluster identity with face selection refinement.

**Actions**:

1. Create `js/components/workbench/ClusterConfirmationModal.tsx`:

   ```tsx
   export function ClusterConfirmationModal({
     clusterId,
     selectedFaces,
     suggestions,
     onConfirm,
     onCancel,
   }: ClusterConfirmationModalProps) {
     const [rosterId, setRosterId] = useState(suggestions[0]?.roster_id);
     const [includedFaces, setIncludedFaces] = useState(selectedFaces);

     return (
       <Modal isOpen onClose={onCancel} size="large">
         <h2>Confirm Identity</h2>

         <PeoplePicker
           value={rosterId}
           onChange={setRosterId}
           suggestions={suggestions}
         />

         <section>
           <h3>Select Faces to Label</h3>
           <p>
             {includedFaces.size} of {selectedFaces.size} faces selected
           </p>
           <FaceThumbnailGrid
             faces={Array.from(selectedFaces)}
             selectedFaces={includedFaces}
             onSelectionChange={setIncludedFaces}
           />
         </section>

         <footer>
           <Button variant="secondary" onClick={onCancel}>
             Cancel
           </Button>
           <Button
             variant="primary"
             onClick={() => onConfirm(rosterId, includedFaces)}
             disabled={!rosterId || includedFaces.size === 0}
           >
             Label {includedFaces.size} Face
             {includedFaces.size !== 1 ? "s" : ""}
           </Button>
         </footer>
       </Modal>
     );
   }
   ```

2. Reuse `PeoplePicker` component from existing implementation
3. Create `js/components/workbench/FaceThumbnailGrid.tsx`:
   - Show small thumbnails with checkboxes
   - Support select all / deselect all
   - Visual indication of which faces match suggestion
4. Wire up confirmation handler:

   ```typescript
   const handleConfirm = async (rosterId: string, faceIds: Set<string>) => {
     await confirmCluster({
       cluster_id: clusterId,
       roster_id: rosterId,
       face_ids: Array.from(faceIds),
     });

     // Refresh clusters list
     queryClient.invalidateQueries(["unknownClusters"]);

     // Show success toast
     showToast("success", `Labeled ${faceIds.size} faces as ${displayName}`);
   };
   ```

5. Write component tests:
   - Test roster selection
   - Test face inclusion/exclusion
   - Test validation (must select roster and at least 1 face)
   - Test cancel behavior
6. Add Storybook story

**Files to Create**:

- `js/components/workbench/ClusterConfirmationModal.tsx`
- `js/components/workbench/FaceThumbnailGrid.tsx`
- `js/components/workbench/ClusterConfirmationModal.test.tsx`
- `js/components/workbench/ClusterConfirmationModal.stories.tsx`

**Acceptance Criteria**:

- Modal allows roster selection and face refinement
- Validation prevents invalid confirmations
- Component is keyboard accessible
- Tests cover all user interactions
- Integrates with existing PeoplePicker component

---

### Task 2.4: Implement Cluster Confirmation Backend

**Status**: ⏳ To Do  
**Description**: Add endpoint to persist confirmed identities and update observations.

**Actions**:

1. Add method to `src/Recognition/ClusterController.php`:

   ```php
   public function confirmCluster(WP_REST_Request $request): WP_REST_Response {
     $clusterId = $request->get_param('id');
     $rosterId = $request->get_param('roster_id');
     $faceIds = $request->get_param('face_ids');

     // Validate inputs
     if (empty($rosterId) || empty($faceIds)) {
       return new WP_Error('invalid_request', 'Missing required fields', ['status' => 400]);
     }

     // Get roster person details
     $person = $this->rosterService->getEntry($rosterId);
     if (!$person) {
       return new WP_Error('roster_not_found', 'Roster person not found', ['status' => 404]);
     }

     // For each face:
     foreach ($faceIds as $faceId) {
       $face = $this->repository->findFaceById($faceId);

       // 1. Create observation linking face to attachment
       $this->identifyController->createObservation(
         $face->getAttachmentId(),
         $rosterId,
         $person->getDisplayName(),
         $face->getBbox()
       );

       // 2. Add embedding to roster via recognition service
       $this->rosterClient->addEmbedding($rosterId, $face->getEmbedding());

       // 3. Mark face as resolved
       $this->repository->markFaceAsResolved($faceId, $rosterId);
     }

     // Re-cluster remaining unresolved faces
     $this->clusteringService->reclusterUnresolvedFaces();

     return new WP_REST_Response([
       'success' => true,
       'labeled_count' => count($faceIds),
       'roster_person' => [
         'id' => $rosterId,
         'display_name' => $person->getDisplayName()
       ]
     ]);
   }
   ```

2. Register route: `POST /wp-json/cat/v1/clusters/{id}/confirm`
3. Add `addEmbedding` method to `src/Roster/RosterClient.php`:
   ```php
   public function addEmbedding(string $rosterId, array $embedding): bool {
     // POST to /api/v0/roster/{rosterId}/embeddings
     // Add embedding to person's FAISS index for future matching
   }
   ```
4. Write PHPUnit tests:
   - Test successful confirmation flow
   - Test with invalid roster_id
   - Test with empty face_ids array
   - Test error handling (recognition service down)
   - Verify observations created correctly
   - Verify faces marked as resolved
5. Add MSW mock

**Files to Modify**:

- `src/Recognition/ClusterController.php`
- `src/Roster/RosterClient.php`
- `tests/Recognition/ClusterControllerTest.php`
- `js/admin/testing/mswHandlers.ts`

**Acceptance Criteria**:

- Confirmation creates observations for all selected faces
- Embeddings sent to recognition service
- Faces marked as resolved in database
- Remaining faces re-clustered automatically
- Error handling prevents partial updates
- Tests verify entire flow end-to-end

---

### Task 2.5: Implement Cascade Update for Remaining Faces

**Status**: ⏳ To Do  
**Description**: After confirming a cluster, automatically label other similar faces with high confidence.

**Actions**:

1. Add method to `src/Domain/Clustering/ClusteringService.php`:

   ```php
   public function findSimilarUnresolvedFaces(string $rosterId, float $threshold = 0.85): array {
     // Get all embeddings for roster person
     $rosterEmbeddings = $this->rosterClient->getEmbeddings($rosterId);

     // Get all unresolved faces
     $unresolvedFaces = $this->repository->findUnresolvedFaces();

     // Compare each unresolved face to roster embeddings
     $matches = [];
     foreach ($unresolvedFaces as $face) {
       $maxSimilarity = 0;
       foreach ($rosterEmbeddings as $rosterEmbedding) {
         $similarity = $this->cosineSimilarity($face->getEmbedding(), $rosterEmbedding);
         $maxSimilarity = max($maxSimilarity, $similarity);
       }

       if ($maxSimilarity >= $threshold) {
         $matches[] = [
           'face' => $face,
           'confidence' => $maxSimilarity
         ];
       }
     }

     return $matches;
   }
   ```

2. Call this method after cluster confirmation in `ClusterController::confirmCluster()`
3. For high-confidence matches (>0.9), create draft observations:
   ```php
   foreach ($similarFaces as $match) {
     if ($match['confidence'] >= 0.9) {
       // Create observation but mark as needs_review
       $this->identifyController->createDraftObservation(
         $match['face']->getAttachmentId(),
         $rosterId,
         $person->getDisplayName(),
         $match['face']->getBbox(),
         $match['confidence']
       );
     }
   }
   ```
4. Add notification for user:
   ```php
   // After cascade update
   add_user_meta(
     get_current_user_id(),
     'cat_pending_face_reviews',
     [
       'roster_id' => $rosterId,
       'draft_count' => count($draftObservations),
       'created_at' => current_time('mysql')
     ]
   );
   ```
5. Write tests verifying cascade logic

**Files to Modify**:

- `src/Domain/Clustering/ClusteringService.php`
- `src/Recognition/ClusterController.php`
- `tests/Domain/Clustering/ClusteringServiceTest.php`

**Acceptance Criteria**:

- High-confidence matches automatically drafted
- User notified of pending reviews
- Similarity calculation uses correct threshold
- Tests verify cascade behavior with various confidence levels

---

## Phase 3: Bulk Review & Automation

### Task 3.1: Create "Review Later" Queue

**Status**: ⏳ To Do  
**Description**: Allow users to defer ambiguous clusters for later review.

**Actions**:

1. Add `review_status` column to `cat_unknown_faces` table:
   ```sql
   ALTER TABLE {$wpdb->prefix}cat_unknown_faces
   ADD COLUMN review_status VARCHAR(20) DEFAULT 'pending',
   ADD COLUMN review_notes TEXT,
   ADD COLUMN deferred_at DATETIME;
   ```
2. Create endpoint: `POST /wp-json/cat/v1/clusters/{id}/defer`
3. Add UI button in `ClusterDetailView`:
   ```tsx
   <Button onClick={() => deferCluster(clusterId, notes)}>Review Later</Button>
   ```
4. Create "Review Later" panel in workbench showing deferred clusters
5. Add filters: by confidence, by person suggestion, by deferral date

**Files to Create**:

- `js/components/workbench/ReviewLaterPanel.tsx`
- Migration for review_status column

**Files to Modify**:

- `src/Recognition/ClusterController.php`
- `js/components/workbench/ClusterDetailView.tsx`

**Acceptance Criteria**:

- Users can defer clusters with optional notes
- Deferred clusters hidden from main view
- Review Later panel shows all deferred clusters
- Filters work correctly

---

### Task 3.2: Implement Prioritization Service

**Status**: ⏳ To Do  
**Description**: Order clusters by confidence, user preferences, and recency.

**Actions**:

1. Create `src/Domain/Clustering/ClusterPrioritizer.php`:

   ```php
   class ClusterPrioritizer {
     public function prioritizeClusters(array $clusters, array $options): array {
       $scored = array_map(function($cluster) use ($options) {
         $score = 0;

         // High confidence suggestions boost score
         if ($cluster['suggestion']['confidence'] >= 0.9) {
           $score += 100;
         }

         // Larger clusters (more faces) get priority
         $score += $cluster['face_count'] * 2;

         // Recent detections get priority
         $daysSinceDetection = $this->getDaysSince($cluster['created_at']);
         $score += max(0, 30 - $daysSinceDetection);

         // User favorites boost score
         if (in_array($cluster['suggestion']['roster_id'], $options['favorite_people'])) {
           $score += 50;
         }

         return ['cluster' => $cluster, 'score' => $score];
       }, $clusters);

       usort($scored, fn($a, $b) => $b['score'] <=> $a['score']);

       return array_column($scored, 'cluster');
     }
   }
   ```

2. Apply prioritization in `ClusterController::listClusters()`
3. Add user preference endpoint: `POST /wp-json/cat/v1/settings/favorites`
4. Write tests for scoring logic

**Files to Create**:

- `src/Domain/Clustering/ClusterPrioritizer.php`
- `tests/Domain/Clustering/ClusterPrioritizerTest.php`

**Acceptance Criteria**:

- Clusters ordered by calculated priority score
- User favorites influence ordering
- Tests verify scoring edge cases

---

### Task 3.3: Add Background Auto-Draft Job

**Status**: ⏳ To Do  
**Description**: Periodically create draft observations for very high confidence matches.

**Actions**:

1. Create `src/Jobs/AutoDraftJob.php`:

   ```php
   class AutoDraftJob {
     public function execute() {
       // Get feature flag
       if (!get_option('cat_auto_draft_enabled', false)) {
         return;
       }

       // Find unresolved faces with very high confidence suggestions
       $threshold = get_option('cat_auto_draft_threshold', 0.95);
       $clusters = $this->clusteringService->getClustersWithHighConfidence($threshold);

       foreach ($clusters as $cluster) {
         // Create draft observations (not confirmed)
         $this->createDraftObservations($cluster);

         // Log for audit trail
         error_log("Auto-drafted {$cluster['face_count']} faces for {$cluster['suggestion']['display_name']}");
       }
     }
   }
   ```

2. Schedule with WP Cron: daily at 2 AM
3. Add kill switch: `cat_auto_draft_enabled` option (default: false)
4. Add settings UI in admin panel
5. Write tests verifying job behavior

**Files to Create**:

- `src/Jobs/AutoDraftJob.php`
- `tests/Jobs/AutoDraftJobTest.php`

**Acceptance Criteria**:

- Job only runs when feature flag enabled
- Respects confidence threshold
- Creates audit log entries
- Tests verify job doesn't auto-confirm (only drafts)

---

## Phase 4: Performance, Quality & Accessibility

### Task 4.1: Optimize Thumbnail Generation & Caching

**Status**: ⏳ To Do  
**Description**: Improve face thumbnail loading performance.

**Actions**:

1. Implement lazy thumbnail generation:
   - Generate thumbnails on-demand, not during scan
   - Cache generated crops in `/wp-content/uploads/cat-face-crops/`
   - Use attachment_id + bbox hash as cache key
2. Add CDN support:
   - Filter hook for CDN URL rewriting
   - Documentation for CDN configuration
3. Add image optimization:
   - Generate multiple sizes (75x75, 150x150)
   - Use WebP format when supported
4. Write performance tests:
   - Measure thumbnail generation time
   - Test cache hit rates
   - Benchmark with 1000+ faces

**Files to Modify**:

- `src/Recognition/ClusterController.php` (thumbnail generation)

**Acceptance Criteria**:

- Thumbnails generate <50ms each
- Cache hit rate >90% after initial generation
- CDN integration documented
- Performance benchmarks pass

---

### Task 4.2: Implement Offline Fallback

**Status**: ⏳ To Do  
**Description**: Gracefully handle recognition service unavailability.

**Actions**:

1. Add service health check:

   ```typescript
   export function useRecognitionServiceStatus() {
     const { data: isOnline } = useQuery({
       queryKey: ["recognitionServiceStatus"],
       queryFn: async () => {
         try {
           await fetchApi("/wp-json/cat/v1/recognition/health");
           return true;
         } catch {
           return false;
         }
       },
       refetchInterval: 30000, // Check every 30 seconds
     });

     return { isOnline: isOnline ?? false };
   }
   ```

2. Show banner when offline:
   ```tsx
   {
     !isOnline && (
       <div className="cat-offline-banner" role="alert">
         <Icon name="warning" />
         <p>
           Face recognition service is unavailable. Using local processing only.
         </p>
       </div>
     );
   }
   ```
3. Disable features requiring service:
   - Batch scanning disabled (show tooltip explaining why)
   - Large cluster processing disabled (>50 faces)
   - Auto-draft job paused
4. Fall back to frontend clustering for small datasets
5. Write E2E tests with service mocked as unavailable

**Files to Create**:

- `js/hooks/useRecognitionServiceStatus.ts`
- `js/components/workbench/OfflineBanner.tsx`

**Acceptance Criteria**:

- Status checked periodically
- Clear user communication when offline
- Functionality degrades gracefully
- E2E tests verify offline behavior

---

### Task 4.3: Accessibility Audit & Fixes

**Status**: ⏳ To Do  
**Description**: Ensure all clustering UI is fully accessible.

**Actions**:

1. Run axe-core on all components:
   ```bash
   npm run test:a11y
   ```
2. Fix violations:
   - Add ARIA labels to all interactive elements
   - Ensure keyboard navigation works everywhere
   - Add focus indicators
   - Test with screen reader (VoiceOver/NVDA)
3. Specific checks:
   - FaceGrid: keyboard navigation with arrow keys
   - ClusterConfirmationModal: trap focus, Escape to close
   - PeoplePicker: announce suggestions to screen reader
   - All buttons have accessible names
4. Document keyboard shortcuts in UI and docs

**Acceptance Criteria**:

- Zero axe-core violations
- All features usable with keyboard only
- Screen reader announces state changes
- Focus management works correctly in modals

---

### Task 4.4: Expand Test Coverage

**Status**: ⏳ To Do  
**Description**: Comprehensive testing for clustering features.

**Actions**:

1. MSW integration tests:
   - Complete clustering workflow (scan → cluster → confirm)
   - Error scenarios (service down, invalid data)
   - Pagination and filtering
2. Load tests:
   - Python script to generate 10,000 test embeddings
   - Test clustering performance at scale
   - Test database query performance
3. E2E tests (Playwright):
   - User flow: scan → review clusters → confirm identity
   - Drag-drop between clusters
   - Review later workflow
4. Ensure >90% coverage for all new code

**Files to Create**:

- `tests/integration/ClusteringWorkflowTest.php`
- `scripts/generate-test-embeddings.py`
- `e2e/clustering.spec.ts`

**Acceptance Criteria**:

- All critical paths covered by E2E tests
- Load tests pass with 10,000+ embeddings
- Code coverage >90% for clustering features

---

## Phase 5: Documentation & Operations

### Task 5.1: Update Architecture Diagrams

**Status**: ⏳ To Do  
**Description**: Document clustering architecture in UML diagrams.

**Actions**:

1. Update `docs/architecture/backend-uml/clustering-sequence.mmd`:
   - Show scan → detection → clustering → confirmation flow
   - Include recognition service interactions
2. Update `docs/architecture/frontend-uml/clustering-components.mmd`:
   - Component hierarchy for clustering UI
   - State management (React Query, local state)
3. Update `docs/architecture/contracts/clustering-api.md`:
   - Document all REST endpoints
   - Request/response schemas
   - Error codes and handling
4. Follow existing mermaid syntax (no code fences)

**Files to Create/Modify**:

- `docs/architecture/backend-uml/clustering-sequence.mmd`
- `docs/architecture/frontend-uml/clustering-components.mmd`
- `docs/architecture/contracts/clustering-api.md`

**Acceptance Criteria**:

- Diagrams render correctly in GitHub
- Matches existing diagram style
- Accurately represents implementation

---

### Task 5.2: Write User Documentation

**Status**: ⏳ To Do  
**Description**: Create user guide for assisted face identification.

**Actions**:

1. Add section to `docs/user-guide.md`:
   - "Assisted Face Identification"
   - How to scan media for faces
   - Understanding clusters and suggestions
   - Confirming identities
   - Reviewing later
   - Managing favorites
2. Add troubleshooting section:
   - "No faces detected" → Check image quality
   - "Low confidence suggestions" → Need more reference images
   - "Recognition service unavailable" → Check server status
3. Add screenshots/GIFs showing workflow
4. Document keyboard shortcuts

**Files to Create/Modify**:

- `docs/user-guide.md`
- `docs/troubleshooting.md`

**Acceptance Criteria**:

- Clear step-by-step instructions
- Screenshots for each major step
- Common issues documented with solutions

---

### Task 5.3: Create Developer Handbook Section

**Status**: ⏳ To Do  
**Description**: Document clustering implementation for future developers.

**Actions**:

1. Create `docs/developer/clustering-implementation.md`:
   - Architecture overview
   - Data models and relationships
   - Clustering algorithm details
   - Extending threshold configuration
   - Recognition service contract
2. Document configuration options:
   - `cat_clustering_threshold` (default 0.65)
   - `cat_auto_draft_threshold` (default 0.95)
   - `cat_auto_draft_enabled` (default false)
3. Add code examples for common tasks:
   - Adding custom clustering algorithm
   - Customizing prioritization logic
   - Extending suggestion confidence calculation

**Files to Create**:

- `docs/developer/clustering-implementation.md`

**Acceptance Criteria**:

- Clear architectural overview
- Code examples are correct and tested
- Configuration options documented with defaults

---

### Task 5.4: Implement Telemetry & Monitoring

**Status**: ⏳ To Do  
**Description**: Add tracking for clustering feature usage and performance.

**Actions**:

1. Add telemetry events:

   ```typescript
   trackEvent("cluster_confirmed", {
     cluster_id: string,
     face_count: number,
     roster_id: string,
     confidence: number,
     time_to_confirm_ms: number,
   });

   trackEvent("cluster_deferred", {
     cluster_id: string,
     face_count: number,
     has_notes: boolean,
   });

   trackEvent("suggestion_accepted", {
     confidence: number,
     suggestion_rank: number, // 1 = top suggestion
   });

   trackEvent("suggestion_rejected", {
     confidence: number,
     suggestion_rank: number,
   });
   ```

2. Create monitoring dashboard query:
   ```sql
   -- Suggestion acceptance rate by confidence level
   SELECT
     confidence_bucket,
     COUNT(*) as total,
     SUM(CASE WHEN accepted THEN 1 ELSE 0 END) as accepted,
     SUM(CASE WHEN accepted THEN 1 ELSE 0 END) * 100.0 / COUNT(*) as acceptance_rate
   FROM clustering_events
   GROUP BY confidence_bucket;
   ```
3. Add performance metrics:
   - Average clustering time by dataset size
   - Average confirmation time (user behavior)
   - Queue depth over time
4. Create alerting rules:
   - Alert if suggestion acceptance rate <70%
   - Alert if clustering queue depth >1000
   - Alert if recognition service error rate >5%

**Files to Create**:

- `src/Infrastructure/Telemetry/ClusteringTelemetry.php`
- `docs/operations/monitoring.md`

**Acceptance Criteria**:

- All key events tracked with relevant metadata
- Dashboard queries return meaningful insights
- Alerts trigger for actionable conditions

---

### Task 5.5: Feature Flag & Rollout Plan

**Status**: ⏳ To Do  
**Description**: Prepare for staged rollout of clustering features.

**Actions**:

1. Add feature flag: `cat_clustering_enabled` (default: false)
2. Gate all clustering UI behind flag:
   ```php
   if (!get_option('cat_clustering_enabled', false)) {
     return; // Don't render clustering features
   }
   ```
3. Create rollout plan document:
   - Phase 1: Enable for admin testing (1 week)
   - Phase 2: Enable for pilot sites (5-10 sites, 2 weeks)
   - Phase 3: Enable for all if metrics look good
4. Define success metrics:
   - Suggestion acceptance rate >80%
   - Average time to label 50 faces <5 minutes
   - No P0/P1 bugs in pilot phase
5. Create rollback procedure documentation

**Files to Create**:

- `docs/operations/clustering-rollout.md`

**Acceptance Criteria**:

- Feature flag properly gates all clustering features
- Rollout plan includes metrics and timelines
- Rollback procedure documented and tested

---

## Definition of Done

A task is complete when:

1. **Code Quality**:

   - ✅ All code follows existing patterns in the codebase
   - ✅ TypeScript types are correct (no `any` without justification)
   - ✅ PHP follows WordPress coding standards
   - ✅ No ESLint or PHPStan errors

2. **Testing**:

   - ✅ Unit tests written with >90% coverage
   - ✅ Integration tests cover happy path and error cases
   - ✅ MSW mocks provided for all new endpoints
   - ✅ All tests pass in CI

3. **Documentation**:

   - ✅ Code comments explain "why" not "what"
   - ✅ API contracts documented
   - ✅ User-facing features have user guide entries
   - ✅ Architecture diagrams updated if structure changed

4. **Accessibility**:

   - ✅ No axe-core violations
   - ✅ Keyboard navigation works
   - ✅ Screen reader tested
   - ✅ ARIA attributes correct

5. **Performance**:

   - ✅ No N+1 queries (explain EXPLAIN results)
   - ✅ Images lazy loaded
   - ✅ No unnecessary re-renders
   - ✅ Bundle size impact <50KB

6. **Review**:
   - ✅ Code reviewed by team
   - ✅ Design reviewed by UX (for UI changes)
   - ✅ Security reviewed (for auth/data handling)

---

## Final Checklist Before Rollout

- [ ] All Phase 1-4 tasks complete
- [ ] Documentation complete and reviewed
- [ ] Telemetry verified working in staging
- [ ] Load tests pass with realistic data volumes
- [ ] Accessibility audit passes (zero violations)
- [ ] Feature flag ready for toggle
- [ ] Rollback plan documented and tested
- [ ] Success metrics defined and measurable
- [ ] Pilot sites identified
- [ ] User guide published
- [ ] Team trained on troubleshooting
