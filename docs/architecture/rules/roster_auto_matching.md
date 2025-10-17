# Roster Auto-Matching Workflow

## Overview

When a new roster entry is created, the system automatically attempts to match it against pending recognition observations that are awaiting review. This auto-matching workflow improves efficiency by reducing manual assignment work.

## How It Works

### 1. New Roster Entry Creation

When a user creates a new roster entry via the Roster Manager:

```typescript
POST /context-alt-text/v1/roster
{
  "label": "John Doe",
  "type": "person",
  "avatarUrl": "https://example.com/john.jpg",
  // ... other fields
}
```

### 2. Auto-Match Process

The backend (`RosterObservationManager::autoAssignPending()`):

1. **Builds roster index** from the newly created entry
2. **Queries pending observations** with `status: 'needs_review'`
3. **Compares candidates** in each observation against the roster index
4. **Matches observations** where:
   - Candidate `remoteId` matches the roster entry's `remoteId`
   - Candidate `similarity` score meets threshold
   - Candidate `meetsThreshold` is `true`

5. **Updates matched observations** with:
   - `status: 'matched'`
   - Links to roster entry metadata
   - Match confidence scores

### 3. Response Structure

Backend returns enriched response:

```json
{
  "entry": {
    "remoteId": "7f69d490-b7da-4419-9ddf-ab6238001c61",
    "label": "John Doe",
    "type": "person",
    ...
  },
  "autoMatched": [
    {
      "attachmentId": 123,
      "observationId": "job-abc-1-0",
      "remoteId": "7f69d490-b7da-4419-9ddf-ab6238001c61",
      "label": "John Doe"
    },
    {
      "attachmentId": 456,
      "observationId": "job-abc-2-0",
      "remoteId": "7f69d490-b7da-4419-9ddf-ab6238001c61",
      "label": "John Doe"
    }
  ],
  "stats": { ... },
  "syncState": { ... }
}
```

### 4. Frontend Handling

The frontend (`RosterRoute.tsx`):

1. **Receives auto-match results** from `createEntry` mutation
2. **Displays notification** showing count of auto-matched observations
3. **Invalidates observation cache** to refresh the UI
4. **Removes matched items** from "needs review" queue

```typescript
const result = await createEntry(values);
const autoMatched = result?.autoMatched ?? [];

if (autoMatched.length > 0) {
  dispatchNotice(
    "success",
    sprintf(
      _n(
        "Roster entry created and %d observation auto-matched.",
        "Roster entry created and %d observations auto-matched.",
        autoMatched.length
      ),
      autoMatched.length
    )
  );
}
```

## Confidence Display Logic

### Before Fix

Match confidence was displayed for ALL observations, even those without roster matches, showing detection confidence instead of roster match confidence.

### After Fix

Match confidence is ONLY displayed when:

1. **Roster match exists** — observation has `roster.remoteId` or `match.isMatch === true`
2. **Valid candidates exist** — observation has non-empty `candidates` array

**Priority order for confidence values:**

1. `record.match.similarity` (roster match similarity)
2. `record.match.confidence` (roster match confidence)
3. `record.matchConfidence` (fallback roster confidence)
4. `topCandidate.similarity` (best candidate similarity)
5. `topCandidate.confidence` (best candidate confidence)

**Example:**

```tsx
// Before: Showed 95% for detection confidence
<span>Match confidence 95%</span>

// After: Only shows confidence when there's a roster match
<span>Match confidence 87.9%</span> // From roster similarity

// Or with no match: (nothing displayed)
```

## User Experience Flow

### Scenario: Creating First Roster Entry

1. **User uploads reference images** of "Ellyn" to create roster entry
2. **System generates embeddings** and syncs to recognition service
3. **Backend receives new roster** with `remoteId: "7f69d490..."`
4. **Auto-match process runs**:
   - Finds 3 pending observations with matching candidates
   - All 3 have `similarity > 0.80` and `meetsThreshold: true`
   - Updates all 3 to `status: 'matched'`

5. **UI updates**:
   - Shows: **"Roster entry created and 3 observations auto-matched."**
   - Recognition observations panel refreshes
   - "Needs review" count decreases from 3 to 0
   - Matched observations appear in "Matched" section

### Scenario: Partial Auto-Match

1. **User creates roster entry** for "John"
2. **5 observations pending review**:
   - 2 have high-confidence match for John → Auto-matched
   - 3 have low-confidence or different faces → Still need review

3. **UI feedback**:
   - Shows: **"Roster entry created and 2 observations auto-matched."**
   - "Needs review" count: 5 → 3
   - User can manually review remaining 3 observations

## Implementation Details

### Backend: `Api.php`

```php
public function post_roster_entry(WP_REST_Request $request)
{
    // ... create roster entry ...
    
    $entry = $remoteId !== null ? $this->get_normalized_roster_entry($remoteId) : null;
    
    // Auto-match pending observations
    $autoMatches = $entry !== null
        ? $this->rosterObservationManager->autoAssignPending([$entry])
        : [];
    
    return rest_ensure_response([
        'entry' => $entry,
        'autoMatched' => $autoMatches,
        // ...
    ]);
}
```

### Backend: `RosterObservationManager.php`

```php
public function autoAssignPending(array $entries, int $limit = self::MAX_AUTO_RETRY_ATTACHMENTS): array
{
    $rosterIndex = $this->buildRosterIndex($entries);
    
    $attachmentIds = $this->observations->findAttachmentIdsNeedingReview(null, $limit * 5);
    
    foreach ($records as $record) {
        foreach ($observations as $observation) {
            // Attempt match from primary candidate
            if ($this->attemptMatchFromPrimaryCandidate(...)) {
                continue;
            }
            
            // Try additional candidates
            foreach ($candidates as $candidate) {
                if ($this->attemptMatchFromCandidate(...)) {
                    break;
                }
            }
        }
    }
    
    return $assignments;
}
```

### Frontend: `useRoster.ts`

```typescript
const createEntry = useMutation({
    mutationFn: async (values: RosterFormValues) => {
        const response = await fetch(rosterEndpoint, {
            method: "POST",
            body: JSON.stringify(encodeRosterBody(values)),
        });
        
        const payload = await handleJsonResponse(await ensureOk(response));
        const entry = normalizeRosterEntry(payload.entry);
        
        // Invalidate observations cache if auto-matches found
        invalidateObservations(payload);
        
        return {
            entry,
            autoMatched: payload.autoMatched ?? [],
        };
    },
});
```

### Frontend: `RosterRoute.tsx`

```typescript
const result = await createEntry(values);
const autoMatched = result?.autoMatched ?? [];

if (autoMatched.length > 0) {
    dispatchNotice(
        "success",
        sprintf(
            _n(
                "Roster entry created and %d observation auto-matched.",
                "Roster entry created and %d observations auto-matched.",
                autoMatched.length
            ),
            autoMatched.length
        )
    );
}
```

## Configuration

### Auto-Match Limits

Configured in `RosterObservationManager.php`:

```php
private const MAX_AUTO_RETRY_ATTACHMENTS = 20;
```

This limits auto-matching to **20 attachments** to prevent performance issues with large observation queues.

### Matching Thresholds

Configured in recognition service backend (Python):

```python
SIMILARITY_THRESHOLD = 0.50  # 50% minimum similarity
```

Observations must have `similarity >= 0.50` AND `meetsThreshold: true` to auto-match.

## Testing

### Unit Tests

**Frontend (`RosterRoute.test.tsx`):**

```typescript
it("displays auto-match notification when observations are matched", async () => {
    const createEntryMock = vi.fn().mockResolvedValue({
        entry: createSampleEntry(),
        autoMatched: [
            { attachmentId: 123, observationId: "obs-1", remoteId: "remote-1" },
            { attachmentId: 456, observationId: "obs-2", remoteId: "remote-1" },
        ],
    });
    
    // ... test auto-match notification appears
});
```

**Backend (`ApiTest.php`):**

```php
public function test_post_roster_entry_returns_auto_matched_observations(): void
{
    $response = $this->api->post_roster_entry($request);
    $data = $response->get_data();
    
    $this->assertIsArray($data['autoMatched']);
    $this->assertCount(2, $data['autoMatched']);
}
```

### Integration Testing

1. **Upload multiple test images** with same person
2. **Run recognition** on all images → creates observations with `needs_review`
3. **Create roster entry** for that person
4. **Verify**:
   - Auto-match notification appears
   - Observations move from "needs review" to "matched"
   - Correct remoteId linkage

## Performance Considerations

### Optimization Strategies

1. **Batch processing** — Processes up to 20 attachments at once
2. **Index building** — Creates efficient lookup structure for roster entries
3. **Early termination** — Stops checking candidates once match found
4. **Cache invalidation** — Only refreshes UI when matches occur

### Scalability

For large observation queues (> 100 attachments):

- Auto-matching processes **first 20 attachments** with needs_review status
- Remaining observations can be processed via:
  - Manual retry button
  - Background job (future enhancement)
  - Next roster entry creation triggers another batch

## Future Enhancements

### 1. Re-Embedding After Auto-Match

**Goal:** Send newly matched observations back to recognition service to augment embeddings

**Implementation:**

```php
// After auto-matching
foreach ($autoMatches as $match) {
    $this->rosterService->augmentEmbedding(
        $match['remoteId'],
        $match['attachmentId'],
        $match['observationId']
    );
}
```

### 2. Background Job Processing

Process auto-matching asynchronously for large queues:

```php
wp_schedule_single_event(time() + 10, 'cat_roster_auto_match', [$remoteId]);
```

### 3. Confidence Threshold UI

Allow administrators to configure matching threshold:

```php
$threshold = get_option('cat_roster_match_threshold', 0.50);
```

## Troubleshooting

### Auto-Matching Not Working

**Symptoms:** New roster entry created but no observations matched

**Causes:**

1. **No pending observations** — All observations already matched or no recognitions run
2. **Low similarity scores** — Candidates don't meet threshold
3. **Missing remoteId** — Roster entry creation failed to get remoteId from backend
4. **Index mismatch** — Candidate remoteIds don't match roster index keys
5. **Stale candidates** — Observations don't have the new roster entry in their candidates array yet

**Important:** Auto-matching only works if observations already have the roster entry as a candidate. When you create a NEW roster entry:

- The system calls `retryPendingForEntry()` to re-submit observations for recognition
- Recognition jobs are asynchronous and may take seconds/minutes to complete
- Once recognition completes, observations will have the new entry in candidates
- Future roster actions (sync, update) will then be able to auto-match those observations

**Workaround for immediate matching:**

- Click "Refresh queue" button after creating roster entry (once recognition jobs complete)
- Or manually create the roster entry FROM an observation (which immediately matches that specific observation)

**Debug Steps:**

```bash
# Check pending observations
wp eval 'context_alt_text_observation_repository()->findAttachmentIdsNeedingReview(null, 100);'

# Verify roster entry has remoteId
wp option get cat_roster_entries --format=json | jq '.[].remoteId'

# Check candidate data in observations
wp post meta get 164 _cat_recognition_observations
```

### Confidence Not Displaying

**Symptoms:** Match confidence shows even without roster match

**Solution:** Updated in this implementation — confidence now requires:

- `roster.remoteId` OR `match.isMatch === true` OR
- Non-empty `candidates` array

## See Also

- [`roster_taxonomy_guide.md`](./roster_taxonomy_guide.md) — Taxonomy integration
- [`face_recognition_tasks.md`](./face_recognition_tasks.md) — Recognition workflow
- [`roster_auto_resolve_behavior.md`](./roster_auto_resolve_behavior.md) — Auto-resolve vs auto-match
