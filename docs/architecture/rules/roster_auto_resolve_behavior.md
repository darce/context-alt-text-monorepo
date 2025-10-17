# Roster Auto-Resolve Behavior

## Current Implementation (v0.0.1)

### Face Recognition Flow
1. User runs recognition on media → backend returns observations with roster candidates
2. `RosterObservationManager::autoAssignMatches()` processes results:
   - Checks candidates against local roster index
   - If `meetsThreshold` or similarity ≥ 0.85, auto-matches observation to roster entry
3. `attachReferenceToRoster()` immediately:
   - Calls `RosterService::attachReferenceImage()`
   - Generates embedding via backend `/embeddings` endpoint
   - Uploads embedding to backend `/roster/{id}/references/append`
   - **Embedding is averaged into entry's recognition model immediately**

### Trade-offs
**Pros:**
- Simple, predictable workflow
- No operator action required for high-confidence matches
- Roster entries improve automatically with each match

**Cons:**
- No operator review before embedding becomes permanent
- Incorrect auto-matches can degrade recognition quality
- No rollback mechanism for bad embeddings

## Proposed Enhancement (Future)

### Pending References System
Add `pendingReferences` array to roster entries to hold unconfirmed embeddings:

```php
[
    'remoteId' => 'abc123',
    'label' => 'Person Name',
    'referenceImages' => [...], // confirmed
    'pendingReferences' => [    // NEW: awaiting confirmation
        [
            'attachmentId' => 456,
            'imageUrl' => '...',
            'similarity' => 0.92,
            'observationId' => 'obs-789',
            'addedAt' => '2025-10-16T...',
        ],
    ],
]
```

### Workflow Changes
1. Auto-match still assigns observation → roster entry
2. **Do not** call `appendReferenceEmbedding` immediately
3. Store reference in `pendingReferences` with metadata
4. UI surfaces pending count badge on roster entry
5. Operator reviews pending references:
   - **Confirm** → generate embedding, append to backend, move to `referenceImages`
   - **Reject** → remove from pending, unlink observation
6. Bulk actions: confirm/reject all pending for an entry

### API Additions
```
POST /roster/{id}/references/confirm
  { attachmentId: 456, observationId: 'obs-789' }

POST /roster/{id}/references/reject
  { attachmentId: 456, observationId: 'obs-789' }

GET /roster/{id}/pending
  → { pending: [...] }
```

### Migration Strategy
- Add `pendingReferences` to entry schema (default `[]`)
- Existing entries unaffected (no pending refs)
- New matches after upgrade → pending mode
- Provide CLI to bulk-confirm all pending: `wp cat-roster confirm-pending --all`

## Testing Requirements (When Implemented)
1. **Similarity Stability Test:**
   - Label same face 5 times with different crops
   - Confirm each pending reference sequentially
   - Assert: similarity scores stay within ±5% tolerance
   
2. **Rejection Workflow:**
   - Auto-match observation to wrong entry
   - Reject pending reference
   - Re-match to correct entry
   - Confirm pending reference
   - Assert: original (wrong) entry has no embedding from that image

3. **Bulk Operations:**
   - Create 10 auto-matches for one entry
   - Bulk-confirm all pending
   - Assert: all 10 embeddings uploaded, `pendingReferences` empty

## Decision Log
**2025-10-16:** Deferred pending embeddings feature. Rationale:
- No production deployments yet → no risk of polluted rosters
- Backend contract changes required (`/references/confirm`, `/references/reject`)
- UI work: pending badge, review panel, bulk actions
- Can ship v0.1 with current auto-resolve, add pending mode in v0.2

Current auto-resolve acceptable for:
- Controlled testing environments
- Small rosters (<50 entries)
- High operator engagement (frequent roster audits)
