# UML & Contract Updates for v2 People Labeling

**Date:** October 22, 2025  
**Branch:** `feature/face-detection-foundation`  
**Aligns with:** `CONSOLIDATED_FACE_DETECTION_PLAN.md` and `FACE_DETECTION_FOUNDATION.md`

## Summary of Changes

All UML diagrams and contracts have been updated to reflect the **v2 unified People labeling architecture**, removing the batch/interactive toggle and introducing PeopleOverlay, PeopleDrawer, and backend suggestion/clustering endpoints.

---

## Updated Files

### Frontend UML Diagrams

#### 1. `docs/architecture/frontend-uml/consolidated-detection-classes.mmd`

**Changes:**
- Added `BoundingBox` class (extracted for clarity)
- Added `PeopleOverlay` component with face chip rendering
- Added `PeopleDrawer` component with cluster/suggestion stacks
- Added `PeoplePicker` component for roster typeahead
- Added `FaceCluster` and `SuggestionStack` domain classes
- Updated `DetectedFaceFE` with confidence, clusterId fields
- Updated `FaceObservation` with all new DB fields
- Added relationships between components and domain classes

**Key Classes:**
```
DetectedFaceFE → BoundingBox, Label, Suggestion
PeopleOverlay → DetectedFaceFE, PeoplePicker
PeopleDrawer → FaceCluster, SuggestionStack
FaceObservation → ObservationEmbedding, RosterPerson
```

#### 2. `docs/architecture/frontend-uml/sequence-interactive-detection.mmd`

**Changes:**
- Renamed from "Interactive Detection" to "Unified People Labeling Flow"
- Added 6 participants: Overlay, Drawer, Picker, Hook (usePeopleSuggestions)
- Expanded from 7 steps to 98 steps (full workflow)
- Added Phase 1: Image Load + Detection (MediaPipe)
- Added Phase 2: Backend Suggestions (Cold Start with clustering)
- Added Phase 3: User Labels First Face (create new person)
- Added Phase 4: Warm Start (suggestions appear immediately)
- Added Phase 5: Bulk Confirm (12 faces in one click)
- Added Phase 6: Misfit Correction (reassign face)

**Flow Coverage:**
- ✅ Cold start (no roster) → clustering
- ✅ Warm start (existing roster) → suggestions
- ✅ Label creation → FAISS sync
- ✅ Bulk confirm → mass update
- ✅ Correction flow → label_status update

#### 3. `docs/architecture/frontend-uml/face-recognition-workflow.mmd`

**Changes:**
- Renamed steps for clarity (Browser, WordPress, Recognition Service)
- Added decision point: Roster exists? (Cold vs Warm start)
- Split /suggest and /cluster-unknowns paths
- Added FAISS threshold (0.92) in diagram
- Added PeopleDrawer as destination for both paths
- Added user action decision (Confirm / Create / Bulk)
- Added roster sync to FAISS after labeling
- Added feedback loop: "Future suggestions improve"

**Key Flow:**
```
MediaPipe → /identify → Crop → /embeddings/batch
→ Roster exists? 
  → Yes: /suggest → FAISS search → PeopleDrawer stacks
  → No: /cluster-unknowns → DBSCAN → PeopleDrawer clusters
→ User confirms → WP persist → FAISS sync → Better suggestions
```

#### 4. `docs/architecture/frontend-uml/roster-domain-classes.mmd`

**Changes:**
- Added `updatedAt` to `RosterPerson`
- Added `quality` enum to `AugmentedEmbedding` (high/medium/low)
- Added `confirmedRosterId` to `FaceObservation`
- Changed `suggestedScore` from `decimal` to `decimal | null`
- Added `LabelStatusEnum` with all 5 states
- Added `EmbeddingSourceEnum` (OBSERVATION, CURATED)
- Added 3 note boxes explaining:
  - FaceObservation fields (cluster, suggested, status)
  - AugmentedEmbedding FAISS sync
  - LabelStatusEnum states

**Database Schema Clarity:**
```sql
-- FaceObservation now has:
clusterGroupId: string | null  -- Groups unknowns
suggestedRosterId: string | null  -- FAISS match
suggestedScore: decimal | null  -- Match confidence
confirmedRosterId: string | null  -- User-confirmed ID
labelStatus: enum  -- UNLABELED|SUGGESTED|CONFIRMED|REJECTED|CORRECTED
```

---

### Backend UML Diagrams

#### 5. `docs/architecture/backend-uml/schemas-contracts.mmd` (NEW)

**Changes:**
- Renamed from `EmbeddingsRequest` to `EmbeddingsBatchRequest` (supports multiple)
- Added `SuggestRequest` / `SuggestResponse` (FAISS search)
- Added `ClusterUnknownsRequest` / `ClusterUnknownsResponse` (DBSCAN)
- Added `RosterSyncRequest` / `RosterSyncResponse` (add to FAISS index)
- Added `RosterMatch` class (rosterId, display, score)
- Updated `ServiceHealth` with `faissIndexSize`
- Added 4 note boxes explaining each new endpoint

**New Endpoints:**
```
POST /api/v0/embeddings/batch  - Generate embeddings
POST /api/v0/suggest  - FAISS similarity search
POST /api/v0/cluster-unknowns  - Group similar faces
POST /api/v0/roster/sync  - Update FAISS index
```

#### 6. `docs/architecture/backend-uml/recognition-identify-flow.mmd` (NEW)

**Created:** Full sequence diagram for WordPress → Recognition Service flow

**Participants:**
- WordPress Plugin
- ImageCropUtility
- Recognition Service endpoints (Embed, Suggest, Cluster)
- FAISS Index
- WP Database

**Steps:**
1. Validate capabilities, resolve attachment
2. Crop faces server-side (GD/Imagick)
3. POST /embeddings/batch → 512-dim vectors
4. POST /suggest → FAISS search with threshold
5. POST /cluster-unknowns → DBSCAN grouping
6. Merge results per face
7. If labels provided: persist to DB + sync to FAISS
8. Return unified response

**Critical Details:**
- Image cropping to 112x112 for model
- FAISS IndexFlatIP/HNSW search
- Threshold filtering (0.92 for suggestions)
- Database transaction for label persistence
- FAISS index updates after new labels

---

### Contracts

#### 7. `docs/architecture/contracts/workbench/recognition-identify.json` (NEW)

**Created:** JSON Schema for `/wp-json/cat/v1/recognition/identify` endpoint

**Includes:**
- Request schema with `attachmentId`, `faces[]`, `imageCoordinateSystem`
- Response schema with `faces[]`, `error`
- 4 complete examples:
  - Cold start (no roster, clustering only)
  - Labeling (create new person "Ana Rodriguez")
  - Warm start (suggestions returned)
  - Bulk confirm (assign to existing rosterId)

**Validation Rules:**
- `attachmentId` must be integer ≥ 1
- `faces` must have at least 1 item
- `bbox` requires x, y, width, height (all numbers)
- `label` must have EITHER `rosterId` OR `newName` (XOR)
- `suggestions` array can be empty (below threshold)

#### 8. `docs/architecture/contracts/README.md`

**Changes:**
- Added "API Contracts (v2 People Labeling)" section
- Added 4 endpoint examples (identify, embeddings, suggest, cluster)
- Added "TypeScript Type Definitions" section
- Added "Testing Contract Compliance" section with commands
- Added links to related architecture docs

---

### TypeScript Types

#### 9. `apps/wp-context-alt-text/js/types/people-labeling.ts` (NEW)

**Created:** Comprehensive TypeScript definitions for v2 (390 lines)

**Core Detection Types:**
- `BoundingBox` - Coordinates (x, y, width, height)
- `RawDetection` - MediaPipe output (bbox + confidence)
- `DetectedFaceFE` - Frontend face with suggestions
- `Label` - User assignment (rosterId XOR newName)
- `Suggestion` - FAISS match (rosterId, display, score)

**API Types:**
- `DetectedFaceRequest` / `DetectedFaceResponse`
- `IdentifyRequest` / `IdentifyResponse`

**Component Props:**
- `PeopleOverlayProps` - Face chips over image
- `PeopleDrawerProps` - Cluster/suggestion stacks
- `PeoplePickerProps` - Roster typeahead

**Domain Types:**
- `FaceCluster` - Grouped unknowns
- `SuggestionStack` - Grouped roster matches
- `RosterPerson` - Taxonomy term data
- `FaceObservation` - Database entity
- `LabelStatus` enum

**Hook Interfaces:**
- `UsePeopleSuggestionsReturn` - identifyFaces, submitLabel, bulkConfirm
- `UseFaceDetectionReturn` - loadDetector, detect (already in foundation)

**Settings:**
- `DetectionConfig` - Provider (mediapipe/retinaface), thresholds
- `RecognitionSettings` - FAISS thresholds, topK, auto-apply

---

## Impact on Development

### Immediate Use (Foundation Branch)

These files are **ready to guide implementation**:

1. **Frontend Developers:**
   - Use `people-labeling.ts` types when building PeopleOverlay
   - Reference `sequence-interactive-detection.mmd` for phase-by-phase flow
   - Check `consolidated-detection-classes.mmd` for component relationships

2. **Backend Developers:**
   - Implement `recognition-identify.json` contract in IdentifyController.php
   - Reference `recognition-identify-flow.mmd` for step-by-step backend logic
   - Use `schemas-contracts.mmd` for Recognition Service endpoints

3. **Contract Testing:**
   - Validate TypeScript request matches `recognition-identify.json` schema
   - Ensure PHP response matches schema
   - Run E2E tests for cold start → warm start → bulk confirm flows

### Database Schema Changes Required

Per `roster-domain-classes.mmd`, these columns must be added:

```sql
ALTER TABLE cat_observation
  ADD COLUMN cluster_group_id VARCHAR(64) NULL,
  ADD COLUMN suggested_roster_id VARCHAR(64) NULL,
  ADD COLUMN suggested_score DECIMAL(5,4) NULL,
  ADD COLUMN confirmed_roster_id VARCHAR(64) NULL,
  ADD COLUMN label_status ENUM('unlabeled','suggested','confirmed','rejected','corrected') NOT NULL DEFAULT 'unlabeled',
  ADD COLUMN updated_at DATETIME NOT NULL;

-- Update existing rows
UPDATE cat_observation SET label_status = 'unlabeled' WHERE label_status IS NULL;
```

### Backend Endpoints To Implement

Per `schemas-contracts.mmd`:

1. **Recognition Service (Python FastAPI):**
   - `POST /api/v0/embeddings/batch` - Already exists
   - `POST /api/v0/suggest` - NEW (FAISS search)
   - `POST /api/v0/cluster-unknowns` - NEW (DBSCAN/Agglomerative)
   - `POST /api/v0/roster/sync` - NEW (update FAISS index)

2. **WordPress Plugin (PHP):**
   - `POST /wp-json/cat/v1/recognition/identify` - NEW (orchestrator)
   - `ImageCropUtility` class - NEW (server-side cropping)

### Testing Checklist

- [ ] `recognition-identify.json` schema validates against examples
- [ ] TypeScript types compile without errors
- [ ] Frontend can build `IdentifyRequest` matching schema
- [ ] Backend can parse `IdentifyRequest` and return valid `IdentifyResponse`
- [ ] E2E: Cold start (no roster) returns clusterIds
- [ ] E2E: Warm start (1 person) returns suggestions with score ≥ 0.92
- [ ] E2E: Bulk confirm updates 10+ observations in <500ms
- [ ] E2E: Misfit correction updates label_status to 'corrected'

---

## Files Ready for v2 Implementation

### ✅ Documentation (Complete)

- [x] CONSOLIDATED_FACE_DETECTION_PLAN.md (v2 plan)
- [x] FACE_DETECTION_FOUNDATION.md (what's ready now)
- [x] Frontend UML diagrams (4 updated)
- [x] Backend UML diagrams (2 updated/created)
- [x] JSON contract schema (recognition-identify.json)
- [x] TypeScript types (people-labeling.ts)
- [x] Contract README updates

### ✅ Foundation Code (In Branch)

- [x] mediaPipeLoader.ts (face detection)
- [x] useFaceDetection.ts (detection hook)
- [x] FaceDetectionDisplay.tsx (bounding boxes)
- [x] RosterTaxonomy.php (update_count_callback fix)

### ❌ Not Yet Implemented (Next Steps)

- [ ] PeopleOverlay.tsx (chips on faces)
- [ ] PeopleDrawer.tsx (cluster/suggestion stacks)
- [ ] PeoplePicker.tsx (roster typeahead)
- [ ] usePeopleSuggestions.ts (identify API hook)
- [ ] IdentifyController.php (WP REST endpoint)
- [ ] ImageCropUtility.php (server-side cropping)
- [ ] Recognition Service /suggest endpoint (FAISS)
- [ ] Recognition Service /cluster-unknowns endpoint (DBSCAN)
- [ ] Recognition Service /roster/sync endpoint
- [ ] Database migration (add clustering columns)

---

## Next Actions

1. **Review Diagrams:**
   - Render UML diagrams to verify accuracy
   - Confirm flows match consolidated plan

2. **Validate Contracts:**
   - Test JSON schema with online validator
   - Ensure TypeScript types align with schema

3. **Backend Stub:**
   - Create IdentifyController.php stub returning 501 Not Implemented
   - Add route to wp-admin API

4. **Frontend Stub:**
   - Create PeopleOverlay.tsx stub (render but don't call API)
   - Import types from people-labeling.ts

5. **Documentation Review:**
   - Ensure CONSOLIDATED plan references match updated diagrams
   - Cross-check section numbers (3.4, 4.2, 5, 6)

---

**Status:** ✅ All UML diagrams and contracts updated for v2 architecture. Ready to guide backend and frontend implementation.
