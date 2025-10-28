# Face Detection Foundation Branch

**Branch:** `feature/face-detection-foundation`  
**Status:** Foundation complete, ready for v2 implementation  
**Date:** October 22, 2025

## What's In This Branch

This branch contains **only the working face detection code** cherry-picked from the v1 batch/interactive toggle experiment. All incompatible v1 components have been excluded.

### ✅ Included (Working Code)

**Frontend Detection:**

- `js/utils/mediaPipeLoader.ts` - MediaPipe Face Detector integration

  - Lazy-loaded model (4s first load, instant after)
  - Detects faces in <400ms per image
  - Returns normalized bounding boxes (0-1 coordinates)
  - Fixed: Infinite loop detection bug

- `js/hooks/useFaceDetection.ts` - React hook for face detection

  - `loadDetector()` - Load MediaPipe model
  - `detect(image)` - Run detection on HTMLImageElement
  - `unload()` - Free memory
  - Proper lifecycle management (no re-detection on re-renders)

- `js/components/workbench/FaceDetectionDisplay.tsx` - CSS bounding boxes
  - No canvas needed - uses positioned divs
  - Accessible (ARIA labels, keyboard navigation)
  - Shows confidence scores
  - Fixed: Coordinate percentage bug

**Architecture Docs:**

- `docs/architecture/rules/roadmaps/CONSOLIDATED_FACE_DETECTION_PLAN.md` - v2 plan
- `docs/architecture/frontend-uml/consolidated-detection-classes.mmd` - UML
- `docs/architecture/frontend-uml/sequence-interactive-detection.mmd` - Sequence diagram
- `docs/architecture/frontend-uml/face-recognition-workflow.mmd` - Flow

**Backend Fixes:**

- `src/Roster/RosterTaxonomy.php` - Added `update_count_callback` for proper term counting
- `.gitignore` - Python venv exclusions

### ❌ Excluded (Incompatible with v2)

**v1 Toggle Components (preserved in `feature/local-face-detection-v1-backup`):**

- `RecognitionModeSelector.tsx` - Batch/interactive toggle (wrong paradigm)
- `InteractiveFaceDetection.tsx` - v1 orchestrator (wrong flow)
- `FaceLabelingPanel.tsx` - Manual labeling form (wrong UX)
- All related tests and styles

## Why This Branch Exists

The v1 approach used a **batch/interactive toggle** which created cognitive friction. The CONSOLIDATED plan eliminates the toggle and introduces:

1. **Always-on face detection** (no mode selection)
2. **PeopleOverlay** - "Who is this?" chips on faces
3. **PeopleDrawer** - Clustered unknowns + bulk confirm
4. **Backend suggestions** - FAISS similarity search

This foundation provides the **working detection layer** that v2 will build upon.

## What Works Now

✅ **Face Detection:**

```typescript
const { loadDetector, detect } = useFaceDetection({ autoLoad: true });

const handleImageLoad = async (img: HTMLImageElement) => {
  const faces = await detect(img);
  console.log(`Found ${faces.length} faces`);
  // faces[0].boundingBox: { originX: 0.2, originY: 0.3, width: 0.15, height: 0.2 }
  // faces[0].confidence: 0.95
};
```

✅ **Display Bounding Boxes:**

```tsx
<FaceDetectionDisplay
  imageUrl="photo.jpg"
  imageAlt="Family photo"
  detections={faces}
  selectedIndex={0}
  onFaceClick={(index) => console.log(`Face ${index} clicked`)}
  showConfidence={true}
/>
```

## What's Missing (Needs Backend)

❌ **Backend Endpoints:**

- `POST /wp-json/cat/v1/recognition/identify` - Not implemented
- `POST /api/v0/suggest` (Recognition Service) - Not implemented
- `POST /api/v0/cluster-unknowns` (Recognition Service) - Not implemented

❌ **Frontend Components (v2):**

- `PeopleOverlay.tsx` - Face chips with suggestions
- `PeopleDrawer.tsx` - Right rail with clusters
- `PeoplePicker.tsx` - Typeahead roster selection
- `usePeopleSuggestions.ts` - Identify API integration

❌ **Database Schema:**

```sql
-- Not yet added to cat_observation table:
ALTER TABLE cat_observation
  ADD COLUMN cluster_group_id VARCHAR(64) NULL,
  ADD COLUMN suggested_roster_id VARCHAR(64) NULL,
  ADD COLUMN suggested_score DECIMAL(5,4) NULL,
  ADD COLUMN label_status ENUM('unlabeled','suggested','confirmed','rejected','corrected') NOT NULL DEFAULT 'unlabeled';
```

## Next Steps (When Backend Ready)

### Phase 1: Backend Recognition Service

1. Implement `/api/v0/suggest` endpoint (FAISS search)
2. Implement `/api/v0/cluster-unknowns` endpoint (DBSCAN/Agglomerative)
3. Add clustering configuration (threshold, min_samples)

### Phase 2: Backend WordPress

1. Implement `/wp-json/cat/v1/recognition/identify` controller
2. Server-side image cropping (WP_Image_Editor)
3. Database schema migration (add clustering columns)
4. Call recognition service endpoints

### Phase 3: Frontend v2 Components

1. Create `PeopleOverlay.tsx` - Face chips over images
2. Create `PeopleDrawer.tsx` - Clustered unknowns UI
3. Create `PeoplePicker.tsx` - Roster dropdown
4. Create `usePeopleSuggestions.ts` - Identify API hook
5. Integrate into WorkbenchApp (remove old toggle)

### Phase 4: Testing

1. E2E tests: Cold start (no roster) → Label faces → Suggestions appear
2. E2E tests: Warm start (existing roster) → Immediate suggestions
3. Contract tests: Frontend types ↔ Backend DTOs
4. Performance tests: FAISS search at 1k/10k entries

## Branch Relationships

```
main (production)
├── feature/local-face-detection-v1-backup (preserved for reference)
│   └── Complete v1 toggle work (49 files, 4795 insertions)
│       - RecognitionModeSelector, InteractiveFaceDetection, FaceLabelingPanel
│       - All tests and styles
│       - Documented bugs and fixes
│
└── feature/face-detection-foundation (THIS BRANCH)
    └── Clean foundation (12 files, 1617 insertions)
        - Only working detection code
        - Ready for v2 implementation
        - No incompatible components
```

## Testing the Foundation

```bash
cd apps/wp-context-alt-text
npm run build
npm test -- useFaceDetection.test
npm test -- FaceDetectionDisplay.test
```

All tests should pass. The detection works, the display works, the infinite loop is fixed.

## Key Insights from v1 Experiment

**What We Learned:**

1. ✅ MediaPipe detection is fast enough (<400ms)
2. ✅ CSS bounding boxes work better than canvas
3. ✅ Infinite loop caused by `useEffect` dependencies (fixed with ref)
4. ✅ Coordinate percentages need careful handling
5. ❌ Batch/interactive toggle adds cognitive friction (REMOVE)
6. ❌ Manual labeling per face is tedious (REPLACE with suggestions)

**What We're Changing in v2:**

- No mode selector → Always-on detection
- No manual form → Smart suggestions + bulk confirm
- No separate flows → One unified People labeling experience

## References

- **v2 Plan:** `docs/architecture/rules/roadmaps/CONSOLIDATED_FACE_DETECTION_PLAN.md`
- **UML Diagrams:** `docs/architecture/frontend-uml/consolidated-detection-classes.mmd`
- **Sequence Flow:** `docs/architecture/frontend-uml/sequence-interactive-detection.mmd`
- **v1 Backup:** `feature/local-face-detection-v1-backup` branch

---

**Status:** ✅ Foundation complete. Waiting for backend `/recognition/identify` endpoint before building v2 components.
