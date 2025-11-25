# Hybrid Face Matching Strategy Implementation

**Status:** ✅ Complete (Core Implementation)  
**Priority:** P2 (Enhancement)  
**Goal:** Implement Apple Photos-style face tagging workflow with intelligent fallback between local clustering and FAISS backend matching

## Recent Bug Fix (2024-10-24)

**Issue:** After labeling a face (e.g., "Ellyn"), subsequent detections of the same person showed empty suggestions instead of recognizing them.

**Root Cause:** When submitting labels, frontend wasn't sending embeddings to backend, so the roster entry had no embeddings stored for future matching.

**Fix:**

1. Added `embedding?: Float32Array` field to `DetectedFaceFE` type
2. Updated `mergeResponse()` in `usePeopleSuggestions` to store embeddings with each face
3. Updated `submitLabel()` to include embedding in request when available
4. Updated backend `IdentifyController.php` to use `persistLabel()` (which stores embeddings) instead of `persistLabelWithoutEmbedding()` when client provides embeddings

**Result:** Now when you label "Ellyn", her embedding is stored with the roster entry. Next time you detect a face, backend compares against stored embeddings and returns "Ellyn" as a suggestion if similarity ≥ 0.65.

---

## Background

Currently, the plugin implements local embedding-based matching (Option 2: Local Clustering). This works well for cold start (0-10 roster entries) but doesn't scale to large rosters or leverage FAISS for speed.

**Current Implementation:**

- Frontend extracts MediaPipe 512D embeddings
- Frontend sends embeddings to backend in identify request
- Backend compares against stored embeddings in WordPress using cosine similarity
- Suggestions returned for matches with similarity ≥ 0.65

**Limitations:**

- Linear search O(n\*m) doesn't scale beyond ~100 roster entries
- Limited to 10 embeddings per person (storage constraints)
- No cross-device roster sync
- Slower than FAISS approximate nearest neighbor search

## Proposed Hybrid Strategy

### Phase 1: Cold Start / Local Clustering (0-10 roster entries)

**Use local matching for instant feedback**

```
User opens media library with unlabeled faces
↓
Frontend: Extract MediaPipe embeddings
↓
Frontend: Cluster faces locally (hierarchical clustering, threshold 0.65)
↓
UI: Show clusters as "Likely same person" stacks
↓
User: Labels first cluster → "This is Ellyn"
↓
Frontend: Immediately group all similar faces in current session
Backend: Create roster entry + queue for FAISS sync (async)
↓
User: Bulk confirms all faces in cluster
Frontend: Optimistic UI update (instant feedback)
Backend: Batch upsert embeddings to FAISS
```

**Benefits:**

- Zero latency for initial grouping
- Label once, apply to many (within session)
- Backend syncs async (no blocking UI)
- Works offline / when recognition service unavailable

### Phase 2: Warm Cache (10-100 roster entries)

**Hybrid: FAISS for known people + local clustering for unknowns**

```
User opens media library (roster now has 50+ people)
↓
Frontend: Extract MediaPipe embeddings
↓
Frontend: Query backend FAISS for top-3 matches (single batch request)
Backend: Returns suggestions in <100ms using FAISS ANN search
↓
Frontend: Cache suggestions in memory for current session
↓
Frontend: Also run local clustering for faces with no suggestions
↓
UI: Shows both sections:
  - "Suggestions" (Ellyn 95%, Sarah 87%, John 81%)
  - "Unknown" (clustered groups for unlabeled people)
↓
User: Confirms suggestion OR creates new person
↓
Backend: Upsert to FAISS immediately (progressive learning)
Frontend: Updates local cache + localStorage
```

**Benefits:**

- Best of both worlds
- Fast FAISS suggestions for known people
- Local clustering for new people
- Instant UI feedback with backend consistency
- Reduces FAISS queries (cache hits in session)

### Phase 3: Large Roster (100+ entries)

**FAISS-primary with progressive learning**

```
Backend: FAISS handles millions of embeddings efficiently
Frontend: Query FAISS first, fallback to local only on failure
Cache: Session-level in-memory cache for suggestions
Offline: Graceful degradation to local matching
```

---

## Implementation Tasks

### Task 1: Keep Current Local Matching (Cold Start Path)

**Status:** ✅ Already implemented (2024-10-24)

Current implementation in `src/Recognition/IdentifyController.php`:

- `suggestLocalMatches()` - compares embeddings against `cat_roster_entries`
- `cosineSimilarity()` - PHP implementation of cosine similarity
- `addEmbeddingToRosterEntry()` - stores up to 10 embeddings per person

**No changes needed** - this is the cold start path.

---

### Task 2: Add FAISS Query Path (Backend)

**Priority:** P2  
**Estimated effort:** 4-6 hours  
**Status:** ✅ Partially Complete (2024-10-24)

#### 2.1: Add Strategy Selection Logic ✅

**File:** `src/Recognition/IdentifyController.php`

**Implemented:**

- Added `useRemoteMatching` parameter detection from request
- Added roster size check (`get_option('cat_roster_entries')`)
- Added FAISS health check via `checkHealth()` and `getRosterStats()`
- Strategy selection logic:
  - If `useRemoteMatching` && FAISS available && FAISS has data → use FAISS
  - Otherwise → use local WP matching
- Comprehensive error logging for debugging

#### 2.2: Implement FAISS Suggestion Method ✅

**Status:** Already implemented as `suggestFaissMatches()` (fallback to local on error)

Current implementation calls `$this->recognitionClient->suggestMatches()` with fallback to local matching.

#### 2.3: Add Health Check Methods to RecognitionClient ✅

**File:** `src/Recognition/RecognitionClient.php`

**Implemented:**

```php
public function checkHealth(): array
public function getRosterStats(): array
```

Both methods gracefully handle errors and return safe defaults.

#### 2.1: Add Strategy Selection Logic

**File:** `src/Recognition/IdentifyController.php`

Add intelligent routing based on roster size and FAISS availability:

```php
// In identify() method, after validating embeddings

// Determine matching strategy
$rosterSize = $this->rosterService->getLocalRosterSize();
$faissAvailable = false;
$faissHasData = false;

try {
    $healthCheck = $this->recognitionClient->checkHealth();
    $faissAvailable = $healthCheck['status'] === 'healthy';
    $faissStats = $this->recognitionClient->getRosterStats();
    $faissHasData = ($faissStats['totalEmbeddings'] ?? 0) > 10;
} catch (RecognitionClientException $e) {
    // FAISS unavailable, will use local matching
    error_log('[IdentifyController] FAISS health check failed: ' . $e->getMessage());
}

// Choose strategy
if ($clientEmbeddings && $useRemoteMatching && $faissAvailable && $faissHasData) {
    // Strategy 1: FAISS (fast, scalable)
    error_log("[IdentifyController] Using FAISS matching (roster: {$rosterSize}, FAISS: {$faissStats['totalEmbeddings']})");
    $suggestions = $this->suggestFaissMatches($embeddings);
} elseif ($clientEmbeddings) {
    // Strategy 2: Local WP roster (cold start)
    error_log("[IdentifyController] Using local matching (roster: {$rosterSize})");
    $suggestions = $this->suggestLocalMatches($embeddings);
} else {
    // Strategy 3: Have backend extract embeddings + suggest
    error_log('[IdentifyController] Using recognition service for embedding extraction');
    $embeddingsResponse = $this->recognitionClient->embedFaces($attachmentId, $faces);
    $embeddings = $embeddingsResponse['embeddings'] ?? [];

    if ($faissAvailable && $faissHasData) {
        $suggestions = $this->suggestFaissMatches($embeddings);
    } else {
        $suggestions = $this->suggestLocalMatches($embeddings);
    }
}
```

#### 2.2: Implement FAISS Suggestion Method

**File:** `src/Recognition/IdentifyController.php`

```php
/**
 * Suggest matches using FAISS approximate nearest neighbor search
 *
 * @param array<array<float>> $embeddings Face embeddings to match
 * @return array<array<array{rosterId: string, confidence: float, displayName: string}>>
 */
private function suggestFaissMatches(array $embeddings): array
{
    error_log('[IdentifyController] suggestFaissMatches called with ' . count($embeddings) . ' embeddings');

    try {
        $response = $this->recognitionClient->suggestMatches($embeddings);
        $suggestions = $response['suggestions'] ?? [];

        error_log('[IdentifyController] FAISS returned ' . count($suggestions) . ' suggestion sets');
        return $suggestions;
    } catch (RecognitionClientException $e) {
        error_log('[IdentifyController] FAISS suggestion failed: ' . $e->getMessage());
        // Fallback to local matching
        return $this->suggestLocalMatches($embeddings);
    }
}
```

#### 2.3: Add Health Check Methods to RecognitionClient

**File:** `src/Recognition/RecognitionClient.php`

```php
/**
 * Check if recognition service is healthy
 *
 * @return array{status: string, message?: string}
 * @throws RecognitionClientException
 */
public function checkHealth(): array
{
    return $this->request('GET', '/health');
}

/**
 * Get roster statistics from FAISS
 *
 * @return array{totalEmbeddings: int, totalPeople: int, lastSyncAt?: string}
 * @throws RecognitionClientException
 */
public function getRosterStats(): array
{
    return $this->request('GET', '/api/v0/roster/stats');
}
```

#### 2.4: Update IdentifyRequest Schema

**File:** `src/Api/Api.php` (register_recognition_routes)

Add optional `useRemoteMatching` boolean to request schema:

```php
'useRemoteMatching' => [
    'type' => 'boolean',
    'description' => 'Prefer FAISS matching over local WP roster matching',
    'default' => false,
],
```

---

### Task 3: Frontend Strategy Selection

**Priority:** P2  
**Estimated effort:** 3-4 hours  
**Status:** ✅ Complete (2024-10-24)

#### 3.1: Add Roster Size Check ✅

**File:** `js/hooks/useRosterSearch.ts`

**Implemented:**

- Added `getRosterSize()` method that fetches roster and returns total count
- Uses `getAllRoster()` API call with graceful error handling
- Returns 0 on failure (safe default)
- Added to `UseRosterSearchReturn` interface

#### 3.2: Update IdentifyRequest Type ✅

**File:** `js/types/people-labeling.ts`

**Implemented:**

- Added `useRemoteMatching?: boolean` field to `IdentifyRequest` interface
- Field is optional (defaults to false in backend)

#### 3.3: Implement Strategy Selection ✅

**File:** `js/hooks/usePeopleSuggestions.ts`

**Implemented:**

- In `identifyFaces()`, when embeddings are provided:
  - Fetches roster size using `getAllRoster()`
  - Calculates: `useRemoteMatching = rosterSize > 10`
  - Sets `request.useRemoteMatching` accordingly
  - Logs strategy decision for debugging
- Graceful fallback to local matching if roster size fetch fails
- Strategy:
  - Roster size 0-10 (Cold Start) → local matching only
  - Roster size > 10 (Warm Cache/Large) → prefer FAISS if available

---

### Task 3: Frontend Strategy Selection (ORIGINAL PLAN)

**Priority:** P2  
**Estimated effort:** 3-4 hours

#### 3.1: Add Roster Size Check (ORIGINAL PLAN)

**File:** `js/hooks/useRosterSearch.ts`

```typescript
/**
 * Get current roster size (for strategy selection)
 */
const getRosterSize = useCallback(async (): Promise<number> => {
  try {
    const response = await getAllRoster();
    return response.total || 0;
  } catch (error) {
    console.error("[useRosterSearch] Failed to get roster size:", error);
    return 0;
  }
}, [getAllRoster]);

// Add to return object
return {
  // ... existing properties
  getRosterSize,
};
```

#### 3.2: Update IdentifyRequest Type

**File:** `js/types/people-labeling.ts`

```typescript
export interface IdentifyRequest {
  /** WordPress attachment post ID */
  attachmentId: number;
  /** Array of detected faces (with optional labels) */
  faces: DetectedFaceRequest[];
  /** Coordinate system: "normalized" (0-1) or "pixels" */
  imageCoordinateSystem?: "normalized" | "pixels";
  /** Optional embeddings extracted by frontend (MediaPipe) for local matching */
  embeddings?: number[][];
  /** Prefer FAISS matching over local WP roster matching (when available) */
  useRemoteMatching?: boolean;
}
```

#### 3.3: Implement Strategy Selection

**File:** `js/hooks/usePeopleSuggestions.ts`

```typescript
const identifyFaces = useCallback(
  async (
    attachmentId: number,
    detections: RawDetection[],
    embeddings?: Float32Array[]
  ): Promise<void> => {
    setIsLoading(true);
    setError(null);
    attachmentIdRef.current = attachmentId;

    try {
      const requestFaces = rawDetectionsToRequest(detections);
      const request: IdentifyRequest = {
        attachmentId,
        faces: requestFaces,
        imageCoordinateSystem: "pixels",
      };

      // Strategy selection based on roster size
      if (embeddings && embeddings.length > 0) {
        const rosterSize = await getRosterSize(); // From useRosterSearch

        if (rosterSize > 10) {
          // Warm cache: Prefer FAISS for speed
          request.embeddings = embeddings.map((emb) => Array.from(emb));
          request.useRemoteMatching = true;
          console.log(
            `[DEBUG] Using FAISS matching strategy (roster: ${rosterSize})`
          );
        } else {
          // Cold start: Use local matching
          request.embeddings = embeddings.map((emb) => Array.from(emb));
          request.useRemoteMatching = false;
          console.log(
            `[DEBUG] Using local matching strategy (roster: ${rosterSize})`
          );
        }
      }

      console.log(
        "[DEBUG] identifyFaces - request:",
        JSON.stringify(request, null, 2)
      );
      const response = await apiIdentifyFaces(request, restNonce);

      // ... rest of implementation
    } catch (err) {
      // ... error handling
    } finally {
      setIsLoading(false);
    }
  },
  [restNonce, rawDetectionsToRequest, mergeResponse, getRosterSize]
);
```

---

### Task 4: Session-Level Suggestion Cache

**Priority:** P3 (Nice-to-have)  
**Estimated effort:** 2-3 hours

#### 4.1: Add Cache Hook

**File:** `js/hooks/useSuggestionCache.ts` (new file)

```typescript
/**
 * useSuggestionCache Hook
 *
 * Caches FAISS suggestions for current labeling session to reduce redundant queries.
 * Uses embedding fingerprint (first 8 values) as cache key.
 */

import { useRef, useCallback } from "react";
import type { RosterPerson } from "@/types/people-labeling";

interface CacheEntry {
  suggestions: RosterPerson[];
  timestamp: number;
}

const CACHE_TTL_MS = 5 * 60 * 1000; // 5 minutes

export const useSuggestionCache = () => {
  const cache = useRef<Map<string, CacheEntry>>(new Map());

  const getCacheKey = useCallback((embedding: Float32Array): string => {
    // Use first 8 values as fingerprint (good enough for session)
    return Array.from(embedding.slice(0, 8))
      .map((v) => v.toFixed(4))
      .join(",");
  }, []);

  const get = useCallback(
    (embedding: Float32Array): RosterPerson[] | null => {
      const key = getCacheKey(embedding);
      const entry = cache.current.get(key);

      if (!entry) return null;

      // Check TTL
      if (Date.now() - entry.timestamp > CACHE_TTL_MS) {
        cache.current.delete(key);
        return null;
      }

      return entry.suggestions;
    },
    [getCacheKey]
  );

  const set = useCallback(
    (embedding: Float32Array, suggestions: RosterPerson[]): void => {
      const key = getCacheKey(embedding);
      cache.current.set(key, {
        suggestions,
        timestamp: Date.now(),
      });
    },
    [getCacheKey]
  );

  const clear = useCallback((): void => {
    cache.current.clear();
  }, []);

  return { get, set, clear };
};
```

#### 4.2: Integrate Cache into usePeopleSuggestions

**File:** `js/hooks/usePeopleSuggestions.ts`

```typescript
import { useSuggestionCache } from "./useSuggestionCache";

export const usePeopleSuggestions = (
  restNonce?: string
): UsePeopleSuggestionsReturn => {
  // ... existing state
  const suggestionCache = useSuggestionCache();

  const identifyFaces = useCallback(
    async (
      attachmentId: number,
      detections: RawDetection[],
      embeddings?: Float32Array[]
    ): Promise<void> => {
      // ... before API call, check cache

      // Check if we can use cached suggestions
      if (embeddings && embeddings.length > 0) {
        const cachedSuggestions = embeddings.map((emb) =>
          suggestionCache.get(emb)
        );
        const allCached = cachedSuggestions.every((s) => s !== null);

        if (allCached) {
          console.log("[DEBUG] Using cached suggestions (cache hit)");
          // Build response from cache
          // ... merge cached data into faces state
          return;
        }
      }

      // ... make API call as usual

      // After successful response, cache suggestions
      if (embeddings && response.faces) {
        response.faces.forEach((face, index) => {
          if (face.suggestions && embeddings[index]) {
            suggestionCache.set(embeddings[index], face.suggestions);
          }
        });
      }
    },
    [restNonce, suggestionCache /* ... */]
  );

  const reset = useCallback(() => {
    // ... existing reset
    suggestionCache.clear();
  }, [suggestionCache]);

  // ... rest of hook
};
```

---

### Task 5: Progressive FAISS Sync

**Priority:** P3  
**Estimated effort:** 2-3 hours

#### 5.1: Async FAISS Sync After Label

**File:** `src/Recognition/IdentifyController.php`

Update `persistLabel()` to queue async FAISS sync instead of blocking:

```php
// After creating observation...

// Queue async FAISS sync (non-blocking)
wp_schedule_single_event(time(), 'cat_sync_embedding_to_faiss', [
    'rosterId' => $rosterId,
    'observationId' => (string) $observationId,
    'embedding' => $embedding,
    'metadata' => [
        'attachmentId' => $attachmentId,
        'bbox' => $bbox,
        'source' => 'wordpress-plugin',
    ],
]);

// Mark as pending sync
update_post_meta($observationId, '_cat_synced_to_faiss', false);
update_post_meta($observationId, '_cat_sync_status', 'queued');
```

#### 5.2: Add Sync Worker

**File:** `src/Recognition/FaissSyncWorker.php` (new)

```php
<?php
declare(strict_types=1);

namespace ContextAltText\Recognition;

/**
 * FAISS Sync Worker
 *
 * Handles async embedding sync to FAISS index.
 * Registered as WordPress cron action.
 */
class FaissSyncWorker
{
    private RecognitionClient $client;

    public function __construct(RecognitionClient $client)
    {
        $this->client = $client;
    }

    public function syncEmbedding(
        string $rosterId,
        string $observationId,
        array $embedding,
        array $metadata
    ): void {
        try {
            $result = $this->client->addRosterEmbedding(
                $rosterId,
                $observationId,
                $embedding,
                $metadata
            );

            if (is_wp_error($result)) {
                throw new \Exception($result->get_error_message());
            }

            // Mark as synced
            update_post_meta((int) $observationId, '_cat_synced_to_faiss', true);
            update_post_meta((int) $observationId, '_cat_sync_status', 'success');
            delete_post_meta((int) $observationId, '_cat_sync_error');

            error_log("[FaissSyncWorker] Successfully synced observation {$observationId} to FAISS");
        } catch (\Exception $e) {
            // Mark as failed, will retry later
            update_post_meta((int) $observationId, '_cat_sync_status', 'failed');
            update_post_meta((int) $observationId, '_cat_sync_error', $e->getMessage());

            error_log("[FaissSyncWorker] Failed to sync observation {$observationId}: {$e->getMessage()}");
        }
    }
}
```

---

## Testing Strategy

### Test Case 1: Cold Start (Empty Roster)

1. Clear roster: `wp cat-roster nuclear-reset --yes`
2. Clear localStorage: Run JS snippet in console
3. Open media library with unlabeled faces
4. Verify: Local clustering groups similar faces
5. Label first cluster "Person A"
6. Verify: Other similar faces show suggestion "Person A"
7. Verify: Backend queues FAISS sync (check wp_options for cron)

### Test Case 2: Warm Cache (10-50 roster entries)

1. Create roster with 20 labeled people
2. Open new image with mix of known/unknown faces
3. Verify: FAISS returns suggestions for known faces (<200ms)
4. Verify: Local clustering groups unknown faces
5. Confirm suggestion for known person
6. Verify: FAISS updates immediately (progressive learning)

### Test Case 3: Large Roster (100+ entries)

1. Import roster with 150+ people
2. Sync embeddings to FAISS
3. Open new image
4. Verify: FAISS-primary strategy used
5. Verify: Sub-100ms response times
6. Verify: Cache prevents redundant FAISS queries

### Test Case 4: Offline / FAISS Down

1. Stop recognition service
2. Open image with faces
3. Verify: Graceful fallback to local matching
4. Verify: UI shows suggestions from WordPress roster
5. Verify: Labels queue for sync when service returns

---

## Success Metrics

- **Cold Start Latency:** <50ms for local clustering (no network)
- **Warm Cache Latency:** <200ms for FAISS batch query
- **Cache Hit Rate:** >80% for faces within same labeling session
- **FAISS Scalability:** Handle 10,000+ roster entries with <100ms query time
- **Offline Support:** 100% functionality when recognition service unavailable
- **User Experience:** Label once, apply to many (batch confirmation)

---

## References

- [Apple Photos Face Recognition](https://support.apple.com/en-gb/guide/iphone/iph9c7ee918c/ios)
- [FAISS: A library for efficient similarity search](https://github.com/facebookresearch/faiss)
- [MediaPipe Face Landmarker](https://developers.google.com/mediapipe/solutions/vision/face_landmarker)
- Current implementation: `src/Recognition/IdentifyController.php` (local matching)

---

## Related Tasks

- [ ] Add WP-CLI command to trigger manual FAISS sync
- [ ] Add admin UI to view FAISS sync status
- [ ] Implement batch FAISS upsert for bulk imports
- [ ] Add telemetry for strategy selection (local vs FAISS usage)
- [ ] Document roster size thresholds in settings

---

**Created:** 2024-10-24  
**Last Updated:** 2024-10-24  
**Owner:** @darce
