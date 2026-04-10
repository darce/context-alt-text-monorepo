# Identity Nomenclature Implementation Guide

> **Parent Document**: [`recognition-identity-nomenclature-update.md`](recognition-identity-nomenclature-update.md)  
> **Status**: Implementation specification  
> **Created**: 2025-11-14

## Overview

This guide provides a detailed, slice-by-slice implementation plan for renaming "face" terminology to "identity" across the recognition system. The goal is to generalize the API, database schema, and UI to support future entity types (logos, brands, custom taxonomies) without requiring another breaking change.

> **Current State (Jan 2025)**: The identity-prefixed schema (`media_identities`, `identity_clusters`, `identity_members`, `identity_scan_jobs`) already ships via `apps/prototype-description-service/db/migrations/versions/001_identity_schema.py`. The remaining work happens in the services, proxy, frontend types, UI, and tests outlined below.

**Key Principles**:

- **Break compatibility**: This is a greenfield deployment—no backwards compatibility needed
- **Database rebuild**: Drop and recreate tables with identity-prefixed names
- **Systematic renaming**: Work from backend → proxy → frontend for each concept
- **Test coverage**: Update all tests, fixtures, and mocks in parallel

---

## Implementation Slices

### Slice 1: Database Schema Verification (Backend Foundation)

**Goal**: Confirm the identity-prefixed schema that already ships with the prototype remains authoritative and document how to validate it. No new Alembic revision is required.

**Prerequisites**: Coordinate database downtime with the team if you need to rebuild the schema for testing, but otherwise rely on the existing baseline.

#### Task 1.1: Confirm Identity Baseline Migration (Status: Completed)

**Current State**:

- `apps/prototype-description-service/db/migrations/versions/001_identity_schema.py` provisions `media_identities`, `identity_clusters`, `identity_members`, and `identity_scan_jobs`.
- Alembic `head` equals `001_identity_schema` for every fresh environment.

**Actions**:

1. Cross-link the migration from the service README (and this guide) so contributors know a second migration is unnecessary.
2. Run `apps/prototype-description-service/scripts/reset_dev_db.sh` whenever you need to drop and recreate the schema locally.
3. If new constraints or indexes are discovered, edit `001_identity_schema.py` directly (greenfield policy) instead of adding a `002_*` rename migration.

**Verification**:

```bash
cd apps/prototype-description-service
poetry run alembic current  # Should report 001_identity_schema
psql prototype_description -c "\dt identity_*"
```

#### Task 1.2: Keep SQLAlchemy Models in Sync (Status: Completed, monitor for regressions)

**Reference Files**:

- `apps/prototype-description-service/db/models.py`

**Notes**:

- Model names already match the identity schema (`MediaIdentity`, `IdentityCluster`, `IdentityMember`, `IdentityScanJob`).
- Relationships (for example, `Tenant.media_identities`) should be treated as the canonical naming reference for downstream services.

**Actions**:

1. Periodically audit imports for lingering `MediaFace`/`FaceCluster` references and replace them with identity equivalents.
2. Extend the identity models directly if new attributes are needed (logos, brands, etc.) to avoid reviving face-prefixed tables.

**Verification**:

```python
from db.models import MediaIdentity, IdentityCluster, IdentityMember, IdentityScanJob
assert MediaIdentity.__tablename__ == "media_identities"
assert IdentityScanJob.identities_detected.key == "identities_detected"
```

**Estimated Time**: 1 hour (documentation + verification)

---

### Slice 2: Backend Service Layer (Application Logic)

**Goal**: Rename service classes, methods, and domain entities to use "identity" terminology.

#### Task 2.1: Rename Service Classes and Methods

**Affected Files**:

- `apps/prototype-description-service/recognition/application/face_scan_service.py`
- `apps/prototype-description-service/recognition/application/face_clustering_service.py`

**Actions**:

1. Rename `FaceScanService` → `IdentityScanService`
2. Rename methods:
   - `scan_faces()` → `scan_identities()`
   - `get_face_count()` → `get_identity_count()`
3. Update internal variable names (`face` → `identity`, `faces_detected` → `identities_detected`)
4. Rename `FaceClusteringService` → `IdentityClusteringService`
5. Update method names:
   - `cluster_faces()` → `cluster_identities()`
   - `assign_face_to_cluster()` → `assign_identity_to_cluster()`
   - `merge_similar_clusters()` remains (cluster-focused, not face-specific)
6. Update all references to renamed models (`MediaFace` → `MediaIdentity`, etc.)

**Sample Changes**:

```python
# face_scan_service.py - Before
class FaceScanService:
    async def scan_faces(self, media_items: list[MediaItem]) -> FaceScanJob:
        faces_detected = 0
        for item in media_items:
            faces = await self.detector.detect_faces(item.image_url)
            faces_detected += len(faces)
        # ...

# After
class IdentityScanService:
    async def scan_identities(self, media_items: list[MediaItem]) -> IdentityScanJob:
        identities_detected = 0
        for item in media_items:
            identities = await self.detector.detect_faces(item.image_url)  # Still uses face detector
            identities_detected += len(identities)
        # ...
```

**Verification**:

```bash
cd apps/prototype-description-service
python -c "from recognition.application.identity_scan_service import IdentityScanService; print('Import successful')"
```

**Estimated Time**: 4 hours

---

#### Task 2.2: Update HTTP Router and API Models

**Affected Files**:

- `apps/prototype-description-service/recognition/interface_adapters/http/recognition_router.py`

**Actions**:

1. Rename request/response models:
   - `AnalyzeRequest` stays (generic enough)
   - `AnalyzeResponse.faces_detected` → `identities_detected`
   - `ScanStatusResponse.faces_detected` → `identities_detected`
   - `ClusterResponse.total_faces_clustered` → `total_identities_clustered`
   - `MediaFacesResponse` → `MediaIdentitiesResponse`
   - `MediaFaceDetail` → `MediaIdentityDetail`
2. Update endpoint paths:
   - `/recognition/media/faces` → `/recognition/media/identities`
   - Keep cluster endpoints as-is (they're cluster-focused)
3. Update docstrings and variable names in route handlers
4. Update service instantiation (`FaceScanService` → `IdentityScanService`)

**Sample Changes**:

```python
# Before
class AnalyzeResponse(BaseModel):
    job_id: str
    status: str
    total_media: int
    faces_detected: int = 0

@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze_media(request: AnalyzeRequest) -> AnalyzeResponse:
    service = FaceScanService(...)
    job = await service.scan_faces(...)

# After
class AnalyzeResponse(BaseModel):
    job_id: str
    status: str
    total_media: int
    identities_detected: int = 0

@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze_media(request: AnalyzeRequest) -> AnalyzeResponse:
    service = IdentityScanService(...)
    job = await service.scan_identities(...)
```

**Verification**:

```bash
# Start service and test endpoints
cd apps/prototype-description-service
uvicorn app:app --reload &
curl http://localhost:8000/docs  # Check OpenAPI schema
```

**Estimated Time**: 3 hours

---

### Slice 3: WordPress Proxy Layer

**Goal**: Update WordPress REST controller to match backend's identity terminology.

#### Task 3.1: Rename Proxy Endpoint Paths and Parameters

**Affected Files**:

- `apps/prototype-wp-alt-context/src/api/class-recognition-proxy-controller.php`
- `apps/prototype-wp-alt-context/src/api/class-recognition-controller.php`

**Actions**:

1. Update `register_routes()`:
   - `/workbench/recognition/media-faces` → `/workbench/recognition/media-identities`
   - Add endpoint description updates
2. Rename method `get_media_faces()` → `get_media_identities()`
3. Update `reassign_cluster_face()` → `reassign_cluster_identity()` (both proxy + primary controller)
4. Update internal variable names (`$face_id` → `$identity_id`, `face_count` → `identity_count`)
5. Update `proxy_request()` calls to match new backend paths

**Sample Changes**:

```php
// Before
public function register_routes(): void {
    register_rest_route(
        'acx/v1',
        '/workbench/recognition/media-faces',
        [
            'callback' => [ $this, 'get_media_faces' ],
        ]
    );
}

public function get_media_faces( WP_REST_Request $request ): WP_REST_Response|WP_Error {
    return $this->proxy_request( 'GET', '/recognition/media/faces', null, $query_params );
}

// After
public function register_routes(): void {
    register_rest_route(
        'acx/v1',
        '/workbench/recognition/media-identities',
        [
            'callback' => [ $this, 'get_media_identities' ],
        ]
    );
}

public function get_media_identities( WP_REST_Request $request ): WP_REST_Response|WP_Error {
    return $this->proxy_request( 'GET', '/recognition/media/identities', null, $query_params );
}
```

**Verification**:

```bash
# Test endpoint registration
wp rest route list | grep media-identities
```

**Estimated Time**: 2 hours

---

#### Task 3.2: Update Admin Localization

**Affected Files**:

- `apps/prototype-wp-alt-context/src/admin/class-admin.php`

**Actions**:

1. Update `enqueue_admin_assets()` localized script data:
   - `workbenchRecognitionMediaFaces` → `workbenchRecognitionMediaIdentities`
   - `workbenchRecognitionReassignFace` → `workbenchRecognitionReassignIdentity`
   - Any other handles keyed to "face" (e.g., `workbenchFaceScan`, `workbenchFaceClusters`) should become `workbenchIdentityScan`, `workbenchIdentityClusters`.
2. Add comments explaining identity vs face terminology for future developers

**Sample Changes**:

```php
// Before
wp_localize_script(
    'acx-admin-app',
    'acxConfig',
    [
        'endpoints' => [
            'workbenchRecognitionMediaFaces' => rest_url( 'acx/v1/workbench/recognition/media-faces' ),
        ],
    ]
);

// After
wp_localize_script(
    'acx-admin-app',
    'acxConfig',
    [
        'endpoints' => [
            // Identity terminology allows future support for logos, brands, etc.
            'workbenchRecognitionMediaIdentities' => rest_url( 'acx/v1/workbench/recognition/media-identities' ),
        ],
    ]
);
```

**Verification**:

```javascript
// In browser console
console.log(window.acxConfig.endpoints.workbenchRecognitionMediaIdentities);
```

**Estimated Time**: 1 hour

---

### Slice 4: Frontend Types and API Layer

**Goal**: Rename TypeScript types, API functions, and hooks to use "identity" terminology.

#### Task 4.1: Update Type Definitions

**Affected Files**:

- `apps/prototype-wp-alt-context/js/admin/api/recognitionApi.ts`
- `apps/prototype-wp-alt-context/js/admin/hooks/useWorkbenchMedia.ts` (if `DetectedFace` type exists there)

**Actions**:

1. Rename types:
   - `ClusterFace` → `ClusterIdentity`
   - `DetectedFace` → `DetectedIdentity`
   - `MediaFacesResponse` → `MediaIdentitiesResponse`
2. Update type properties:
   - `ScanStatus.faces_detected` → `identities_detected`
   - `ScanStatus.total_faces_clustered` → `total_identities_clustered`
   - `ClusterSummary.sample_faces` → `sample_identities`
   - `ClusterSummary.face_count` → `identity_count`
   - `ClusterSummary.representative_face` → `representative_identity`
3. Export renamed types and update every import site:
   - `useClusterMediaMap`, drag/drop hooks, and roster utilities should import `ClusterIdentity`
   - Update mock data under `js/admin/pages/__tests__` and MSW handlers to use the new property names

**Sample Changes**:

```typescript
// Before
export type ScanStatus = {
  job_id: string;
  status: "pending" | "running" | "completed" | "failed";
  faces_detected: number;
  total_faces_clustered?: number;
};

export type ClusterFace = {
  id: string;
  media_id: number;
  bbox: { x: number; y: number; width: number; height: number };
  confidence: number;
  similarity: number | null;
};

export type ClusterSummary = {
  cluster_id: string;
  label: string;
  face_count: number;
  sample_faces: string[];
  representative_face: string | null;
};

// After
export type ScanStatus = {
  job_id: string;
  status: "pending" | "running" | "completed" | "failed";
  identities_detected: number;
  total_identities_clustered?: number;
};

export type ClusterIdentity = {
  id: string;
  media_id: number;
  bbox: { x: number; y: number; width: number; height: number };
  confidence: number;
  similarity: number | null;
};

export type ClusterSummary = {
  cluster_id: string;
  label: string;
  identity_count: number;
  sample_identities: string[];
  representative_identity: string | null;
};
```

**Verification**:

```bash
cd apps/prototype-wp-alt-context
npm run type-check
```

**Estimated Time**: 2 hours

---

#### Task 4.2: Rename API Functions

**Affected Files**:

- `apps/prototype-wp-alt-context/js/admin/api/recognitionApi.ts`

**Actions**:

1. Update endpoint keys in `getEndpoint()` calls:
   - `'workbenchRecognitionMediaFaces'` → `'workbenchRecognitionMediaIdentities'`
2. Rename functions:
   - `fetchMediaFaces()` → `fetchMediaIdentities()`
   - `reassignClusterFace()` → `reassignClusterIdentity()`
3. Keep `scanFaces()` and `clusterFaces()` as-is (describe actions, not just entities)
4. Update JSDoc comments to explain identity terminology

**Sample Changes**:

```typescript
// Before
export const fetchMediaFaces = async (
  mediaIds: number[]
): Promise<MediaFacesResponse> => {
  const endpoint = getEndpoint("workbenchRecognitionMediaFaces");
  // ...
};

export const reassignClusterFace = async (
  faceId: string,
  targetClusterId: string | null
): Promise<void> => {
  // ...
};

// After
/**
 * Fetch detected identities (faces, future: logos/brands) for given media IDs.
 */
export const fetchMediaIdentities = async (
  mediaIds: number[]
): Promise<MediaIdentitiesResponse> => {
  const endpoint = getEndpoint("workbenchRecognitionMediaIdentities");
  // ...
};

/**
 * Reassign a detected identity to a different cluster or create new cluster.
 */
export const reassignClusterIdentity = async (
  identityId: string,
  targetClusterId: string | null
): Promise<void> => {
  // ...
};
```

**Verification**:

```bash
npm run build
# Check for TypeScript errors
```

**Estimated Time**: 2 hours

---

#### Task 4.3: Update React Query Hooks

**Affected Files**:

- `apps/prototype-wp-alt-context/js/admin/hooks/useRecognitionHooks.ts`
- `apps/prototype-wp-alt-context/js/admin/hooks/useMediaFaces.ts` (rename to `useMediaIdentities.ts`)

**Actions**:

1. Rename hooks:
   - `useScanFaces()` → `useScanIdentities()`
   - `useClusterFaces()` → `useClusterIdentities()`
   - `useMediaFaces()` → `useMediaIdentities()`
2. Update query keys:
   - `['media-faces', ...]` → `['media-identities', ...]`
3. Update function references to match renamed API functions
4. Keep cluster-focused hooks as-is (`useRecognitionClusters`, `useRecognitionCluster`)

**Sample Changes**:

```typescript
// Before
export const useScanFaces = (options?: UseMutationOptions<...>) =>
  useMutation<AnalyzeResponse, Error, number[]>({
    mutationFn: (mediaIds) => scanFaces({ mediaIds }),
    ...options,
  });

export const useMediaFaces = (mediaIds: number[], enabled = true) =>
  useQuery<MediaFacesResponse>({
    queryKey: ['media-faces', mediaIds],
    queryFn: () => fetchMediaFaces(mediaIds),
    // ...
  });

// After
export const useScanIdentities = (options?: UseMutationOptions<...>) =>
  useMutation<AnalyzeResponse, Error, number[]>({
    mutationFn: (mediaIds) => scanFaces({ mediaIds }),  // Function name stays
    ...options,
  });

export const useMediaIdentities = (mediaIds: number[], enabled = true) =>
  useQuery<MediaIdentitiesResponse>({
    queryKey: ['media-identities', mediaIds],
    queryFn: () => fetchMediaIdentities(mediaIds),
    // ...
  });
```

**Verification**:

```bash
npm run test -- useRecognitionHooks.test
```

**Estimated Time**: 2 hours

---

### Slice 5: Frontend Components (UI Layer)

**Goal**: Update React components to use identity terminology in props, state, and rendering logic.

#### Task 5.1: Update Roster Page Components

**Affected Files**:

- `apps/prototype-wp-alt-context/js/admin/pages/RosterPage.tsx`
- `apps/prototype-wp-alt-context/js/admin/pages/roster/ClusterGrid.tsx`
- `apps/prototype-wp-alt-context/js/admin/pages/roster/ClusterDrawerPanel.tsx`
- `apps/prototype-wp-alt-context/js/admin/pages/roster/FaceThumbnail.tsx` (rename to `IdentityThumbnail.tsx`)

**Actions**:

1. Update RosterPage:
   - `useScanFaces()` → `useScanIdentities()`
   - `useClusterFaces()` → `useClusterIdentities()`
   - Variable names: `faces` → `identities`, `faceCount` → `identityCount`
2. Update ClusterGrid props:
   - `sample_faces` → `sample_identities`
   - `face_count` → `identity_count`
3. Update ClusterDrawerPanel:
   - `faces` prop → `identities`
   - `handleRescanCluster(faces)` → `handleRescanCluster(identities)`
4. Rename and update FaceThumbnail:
   - Rename file to `IdentityThumbnail.tsx`
   - Update component name and props
   - Keep internal `bbox` logic (physical face crop still relevant)

**Sample Changes**:

```tsx
// RosterPage.tsx - Before
const scanMutation = useScanFaces({
  onSuccess: (data) => {
    // ...
  },
});

const clusterMutation = useClusterFaces({
  onSuccess: (data) => {
    setClusterMessage(
      sprintf(
        __("%d identities clustered into %d groups", "alt-context"),
        data.total_identities_clustered,
        data.cluster_count
      )
    );
  },
});

// After
const scanMutation = useScanIdentities({
  onSuccess: (data) => {
    // ...
  },
});

const clusterMutation = useClusterIdentities({
  onSuccess: (data) => {
    setClusterMessage(
      sprintf(
        __("%d identities clustered into %d groups", "alt-context"),
        data.total_identities_clustered,
        data.cluster_count
      )
    );
  },
});
```

```tsx
// ClusterDrawerPanel.tsx - Before
type Props = {
  cluster: ClusterSummary | null;
  faces: ClusterFace[];
  isDetailLoading: boolean;
  // ...
};

const facesToDisplay = faces.slice(0, 20);

// After
type Props = {
  cluster: ClusterSummary | null;
  identities: ClusterIdentity[];
  isDetailLoading: boolean;
  // ...
};

const identitiesToDisplay = identities.slice(0, 20);
```

**Verification**:

```bash
npm run dev
# Manual testing: navigate to Roster page, verify clusters display correctly
```

**Estimated Time**: 4 hours

---

#### Task 5.2: Update Workbench Components

**Affected Files**:

- `apps/prototype-wp-alt-context/js/admin/pages/WorkbenchPage.tsx`
- `apps/prototype-wp-alt-context/js/admin/pages/workbench/MediaSelection.tsx`
- `apps/prototype-wp-alt-context/js/admin/pages/workbench/FaceClusterList.tsx` (rename to `IdentityClusterList.tsx`)

**Actions**:

1. Update WorkbenchPage:
   - `useMediaFaces()` → `useMediaIdentities()`
   - `facesQuery` → `identitiesQuery`
   - `mediaWithFaces` → `mediaWithIdentities`
   - Query key invalidation: `['media-faces']` → `['media-identities']`
2. Update MediaSelection to pass `identities` prop
3. Rename and update FaceClusterList:
   - File: `FaceClusterList.tsx` → `IdentityClusterList.tsx`
   - Component name: `FaceClusterList` → `IdentityClusterList`
   - Props: `faces` → `identities`
   - Internal logic: `clusterFaces` → `clusterIdentities`

**Sample Changes**:

```tsx
// WorkbenchPage.tsx - Before
const facesQuery = useMediaFaces(
  currentPageIds,
  activeSection === TAB_IDS.scan
);

const mediaWithFaces = React.useMemo(() => {
  const facesByMedia = facesQuery.data?.faces_by_media ?? {};
  return mediaItems.map((item) => ({
    ...item,
    faces: facesByMedia[String(item.id)] ?? [],
  }));
}, [mediaItems, facesQuery.data]);

React.useEffect(() => {
  if (scanStatusQuery.data?.status === "completed") {
    queryClient.invalidateQueries({ queryKey: ["media-faces"] });
  }
}, [scanStatusQuery.data?.status]);

// After
const identitiesQuery = useMediaIdentities(
  currentPageIds,
  activeSection === TAB_IDS.scan
);

const mediaWithIdentities = React.useMemo(() => {
  const identitiesByMedia = identitiesQuery.data?.identities_by_media ?? {};
  return mediaItems.map((item) => ({
    ...item,
    identities: identitiesByMedia[String(item.id)] ?? [],
  }));
}, [mediaItems, identitiesQuery.data]);

React.useEffect(() => {
  if (scanStatusQuery.data?.status === "completed") {
    queryClient.invalidateQueries({ queryKey: ["media-identities"] });
  }
}, [scanStatusQuery.data?.status]);
```

**Verification**:

```bash
npm run build
npm run test -- MediaSelection.test
```

**Estimated Time**: 3 hours

---

### Slice 6: SCSS and Localization

**Goal**: Update CSS class names and translation strings to use identity terminology.

#### Task 6.1: Rename SCSS Classes

**Affected Files**:

- `apps/prototype-wp-alt-context/js/admin/styles/components/_cluster-grid.scss`
- `apps/prototype-wp-alt-context/js/admin/styles/components/_media-selection.scss`

**Actions**:

1. Rename CSS custom properties:
   - `--acx-cluster-card-thumb-size` can stay (refers to visual representation)
   - Add comment explaining "face" in styles refers to visual thumbnail, not data model
2. Rename BEM classes if they reference "face":
   - `.acx-face-clusters` → `.acx-identity-clusters`
   - `.acx-face-cluster` → `.acx-identity-cluster`
   - `.acx-face-cluster__thumb` → `.acx-identity-cluster__thumb`
3. Update component className references to match

**Sample Changes**:

```scss
// Before
.acx-face-clusters {
  display: flex;
  gap: 0.5rem;
}

.acx-face-cluster {
  &__preview {
    /* ... */
  }
  &__thumb {
    /* ... */
  }
}

// After
.acx-identity-clusters {
  display: flex;
  gap: 0.5rem;
}

.acx-identity-cluster {
  &__preview {
    /* ... */
  }
  &__thumb {
    /* ... */
  }
  // Note: "thumb" refers to visual thumbnail, not data entity
}
```

**Verification**:

```bash
npm run build:css
# Visual regression testing
```

**Estimated Time**: 2 hours

---

#### Task 6.2: Update Translation Strings

**Affected Files**:

- `apps/prototype-wp-alt-context/js/admin/pages/**/*.tsx` (all components with `__()` calls)

**Actions**:

1. Find and replace translation strings:
   - `'%d faces detected'` → `'%d identities detected'`
   - `'%d faces clustered'` → `'%d identities clustered'`
   - `'Face from %s'` → `'Identity from %s'`
   - Keep user-facing copy natural (consider "person" for face-specific contexts if needed)
2. Regenerate POT file:
   ```bash
   wp i18n make-pot apps/prototype-wp-alt-context \
     apps/prototype-wp-alt-context/languages/alt-context.pot \
     --domain=alt-context
   ```
3. Update any existing `.po` translation files

**Sample Changes**:

```typescript
// Before
__("Face recognition scan completed", "alt-context");
sprintf(
  __("%d faces detected in %d images", "alt-context"),
  faceCount,
  imageCount
);

// After
__("Identity recognition scan completed", "alt-context");
sprintf(
  __("%d identities detected in %d images", "alt-context"),
  identityCount,
  imageCount
);
```

**Verification**:

```bash
# Check POT file for old strings
grep -i "face" apps/prototype-wp-alt-context/languages/alt-context.pot
```

**Estimated Time**: 2 hours

---

### Slice 7: Tests and Fixtures

**Goal**: Update all test files, fixtures, and mock data to use identity terminology.

#### Task 7.1: Update Backend Tests

**Affected Files**:

- `apps/prototype-description-service/tests/**/*.py`

**Actions**:

1. Rename test fixtures:
   - `face_fixture` → `identity_fixture`
   - `face_cluster_fixture` → `identity_cluster_fixture`
2. Update test data factories to use new model names
3. Update assertions to check `identities_detected`, `identity_count`, etc.
4. Update test names to reflect identity terminology

**Sample Changes**:

```python
# Before
@pytest.fixture
def face_fixture(db_session):
    return MediaFace(
        tenant_id=uuid4(),
        media_id=123,
        bbox_x=100,
        # ...
    )

def test_scan_faces_detects_multiple(face_scan_service):
    result = await face_scan_service.scan_faces([...])
    assert result.faces_detected == 3

# After
@pytest.fixture
def identity_fixture(db_session):
    return MediaIdentity(
        tenant_id=uuid4(),
        media_id=123,
        bbox_x=100,
        # ...
    )

def test_scan_identities_detects_multiple(identity_scan_service):
    result = await identity_scan_service.scan_identities([...])
    assert result.identities_detected == 3
```

**Verification**:

```bash
cd apps/prototype-description-service
pytest tests/ -v
```

**Estimated Time**: 4 hours

---

#### Task 7.2: Update Frontend Tests

**Affected Files**:

- `apps/prototype-wp-alt-context/js/admin/**/*.test.{ts,tsx}`

**Actions**:

1. Update MSW handlers to use new endpoint paths and response shapes
2. Rename mock data variables (`mockFaces` → `mockIdentities`)
3. Update test expectations for renamed props/types
4. Update Storybook stories if they exist

**Sample Changes**:

```typescript
// Before
const mockFaces: ClusterFace[] = [
  { id: '1', media_id: 123, bbox: {...}, confidence: 0.9, similarity: 0.8 },
];

server.use(
  http.get('/wp-json/acx/v1/workbench/recognition/media-faces', () => {
    return HttpResponse.json({ faces_by_media: { '123': mockFaces } });
  })
);

// After
const mockIdentities: ClusterIdentity[] = [
  { id: '1', media_id: 123, bbox: {...}, confidence: 0.9, similarity: 0.8 },
];

server.use(
  http.get('/wp-json/acx/v1/workbench/recognition/media-identities', () => {
    return HttpResponse.json({ identities_by_media: { '123': mockIdentities } });
  })
);
```

**Verification**:

```bash
npm run test
npm run test:ui  # Vitest UI for visual inspection
```

**Estimated Time**: 3 hours

---

### Slice 8: Documentation and Configuration

**Goal**: Update docs, config files, and environment variable references.

#### Task 8.1: Update Configuration Files

**Affected Files**:

- `apps/prototype-description-service/config/settings.yaml`
- `apps/prototype-description-service/recognition/config/settings.py`
- `.env` / `.env.example` entries that document recognition payloads

**Actions**:

1. Rename the `recognition` YAML section to `identity_detection`, add `max_identities_per_image`, and introduce new identity-aware clustering limits (`min_identity_cluster_size`, `max_identity_cluster_size`).
2. Update `recognition/config/settings.py` to expose `IdentityDetectionSettings`/`IdentityClusteringSettings` while keeping legacy aliases (e.g., `RecognitionSettings`, `ClusteringSettings`, `RecognitionConfig.recognition`) for downstream code.
3. Document the new names in the environment example files and note that old keys remain supported through aliases during the transition.

**Sample Changes**:

```yaml
# After
identity_detection:
  default_threshold: 0.45
  max_identities_per_image: 999
  embedding_dimension: 1024
  max_candidates: 10

clustering:
  similarity_threshold: 0.6
  min_identity_cluster_size: 2
  max_identity_cluster_size: 1000
```

**Verification**:

```bash
cd apps/prototype-description-service
/Users/daniel/.pyenv/versions/description-service/bin/python -c "from recognition.config.settings import get_settings; print(get_settings().identity_detection)"
```

**Estimated Time**: 2 hours

---

#### Task 8.2: Update Implementation Guides

**Affected Files**:

- `docs/tasks/4.0/face-scan-implementation-guide.md` → rename to `identity-scan-implementation-guide.md`
- `docs/tasks/4.0/workbench-cluster-editing-implementation.md`
- Other task docs referencing face terminology

**Actions**:

1. Search and replace "face" with "identity" where semantically appropriate
2. Add migration notes explaining the rename
3. Update code samples to match new naming
4. Add a "Legacy Terminology" section explaining that "face" may appear in older commits

**Sample Changes**:

```markdown
<!-- Before -->

## Phase 7: Roster Face Management

Implement cluster grid showing detected faces with drag/drop support.

### Tasks

- [ ] Fetch face metadata for clusters
- [ ] Render face thumbnails in 2x2 grid

<!-- After -->

## Phase 7: Roster Identity Management

Implement cluster grid showing detected identities with drag/drop support.

### Legacy Note

Prior to v4.0, the system used "face" terminology. This was renamed to "identity"
to support future entity types (logos, brands, custom classifiers).

### Tasks

- [ ] Fetch identity metadata for clusters
- [ ] Render identity thumbnails in 2x2 grid
```

**Verification**:

```bash
grep -r "MediaFace\|ClusterFace" docs/tasks/4.0/
# Should return no matches
```

**Estimated Time**: 3 hours

---

## Implementation Schedule

### Week 1: Backend Foundation

- **Day 1-2**: Slice 1 (Database schema rebuild)
  - Create migration, update models, test locally
- **Day 3-4**: Slice 2 (Service layer)
  - Rename services, update routers, test endpoints
- **Day 5**: Buffer for backend integration testing

### Week 2: Proxy and Frontend Types

- **Day 1**: Slice 3 (WordPress proxy)
  - Update controllers, localization
- **Day 2-3**: Slice 4 (Frontend types and API)
  - Rename types, API functions, hooks
- **Day 4**: Buffer for type checking and build validation

### Week 3: UI and Tests

- **Day 1-2**: Slice 5 (UI components)
  - Update Roster and Workbench components
- **Day 3**: Slice 6 (SCSS and i18n)
  - Rename classes, regenerate POT
- **Day 4-5**: Slice 7 (Tests)
  - Update backend and frontend tests

### Week 4: Documentation and QA

- **Day 1**: Slice 8 (Docs and config)
  - Update guides, config files
- **Day 2-3**: End-to-end testing
  - Full workflow validation (scan → cluster → roster)
- **Day 4-5**: Bug fixes and polish

**Total Duration**: ~4 weeks (80 hours development, 16 hours buffer)

---

## Testing Checklist

- [x] All migrations apply cleanly on fresh database (baseline is `001_identity_schema`; run via `apps/prototype-description-service/scripts/reset_dev_db.sh`)
- [x] SQLAlchemy models match table schema (MediaFace → MediaIdentity, etc.)
- [x] Service methods handle renamed fields correctly
- [x] API endpoints return identity-prefixed JSON
- [x] Unit tests pass with new fixtures
- [ ] Integration tests validate end-to-end flow

### WordPress Proxy

- [ ] Proxy routes registered at correct paths
- [ ] Admin localization exposes new endpoint keys
- [ ] Proxy correctly forwards to backend identity endpoints
- [ ] Capability checks still enforce permissions

### Frontend

- [ ] TypeScript compiles without errors
- [ ] All hooks use renamed API functions
- [ ] Components render identity data correctly
- [ ] Query cache invalidation works with new keys
- [ ] Translation strings display correctly
- [ ] SCSS classes apply properly

### Integration

- [ ] Scan workflow detects identities and updates job status
- [ ] Clustering groups identities into clusters
- [ ] Roster page displays identity counts accurately
- [ ] Workbench shows inline identity previews
- [ ] Drag/drop reassignment updates identity memberships
- [ ] Merge operations consolidate identities correctly

---

## Rollback Plan

If critical issues arise:

1. **Revert database migration**:

   ```bash
   cd apps/prototype-description-service
   alembic downgrade -1
   ```

2. **Revert code changes**:

   ```bash
   git revert <commit-range>
   ```

3. **Clear frontend caches**:

   ```bash
   cd apps/prototype-wp-alt-context
   npm run build
   wp cache flush
   ```

4. **Notify team**: Document blocking issues in rollback commit message

---

## Post-Implementation Tasks

1. **Update API documentation**: Regenerate OpenAPI schema with new identity models
2. **Announce in team channels**: Explain identity abstraction and migration steps
3. **Monitor logs**: Watch for errors related to old "face" references
4. **Archive old docs**: Move `face-scan-implementation-guide.md` to `docs/archive/`
5. **Plan future entity types**: Design logo/brand detection pipeline using identity framework

---

## References

- [recognition-identity-nomenclature-update.md](recognition-identity-nomenclature-update.md)
- [SQLAlchemy Migration Guide](https://alembic.sqlalchemy.org/en/latest/tutorial.html)
- [WordPress i18n Documentation](https://developer.wordpress.org/apis/internationalization/)
- [TanStack Query Migration Guide](https://tanstack.com/query/latest/docs/framework/react/guides/migrating-to-v5)
