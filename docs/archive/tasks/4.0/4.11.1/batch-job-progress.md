# Batch Job Progress Architecture

**Created**: 2026-01-25  
**Priority**: P2 (Medium)  
**Effort**: 4-5 hrs  
**Related**: [false-positive-analysis.md](./false-positive-analysis.md), [offline-cluster-persistence.md](./offline-cluster-persistence.md)

---

## 1. Problem Statement

The current progress indicator for batch recognition jobs provides insufficient feedback to users:

1. **Image transfer status** — Are images being sent to the backend? How many have been uploaded?
2. **Detection progress** — How many images have been processed for face detection?
3. **Clustering phase** — Has the system moved from detection to clustering?
4. **Queue position** — If multiple jobs are queued, where is this job?

**Current behavior**: Simple progress bar with minimal status text ("Processing...", "Clustering...")

**Expected behavior**: Granular, phase-aware progress with metrics:

```
Phase 1/3: Uploading images... (45/100 sent)
Phase 2/3: Detecting faces... (32/100 complete, 156 faces found)
Phase 3/3: Clustering identities... (analyzing 156 faces)
```

---

## 2. Production Architecture Constraint

### Why Plugin-Push is Required

The production deployment hosts the backend on **Hugging Face** (or similar cloud ML service). This creates critical constraints:

1. **Media library is not public** — Backend cannot fetch images via URL
2. **Admin WP user credentials cannot be shared** — Backend cannot authenticate to WordPress
3. **WordPress is behind firewall/NAT** — Backend cannot initiate connections to WordPress

**Conclusion**: The WordPress plugin must **push** images to the backend, not the other way around.

### Plugin-Push Architecture

```
WordPress Plugin                      Hugging Face Backend
     │                                       │
     ├── POST /scan/start ───────────────────►
     │   { image_ids: [...], tenant_id }     │
     │                                       │
     │◄── SSE: { phase: "ready",  ───────────┤
     │          upload_token: "abc123",      │
     │          images_total: 100 }          │
     │                                       │
     ├── POST /upload ───────────────────────►
     │   multipart/form-data (image + token) │
     │                                       │
     │◄── SSE: { phase: "uploading", ────────┤
     │          images_received: 1 }         │
     │       ...repeat per image...          │
     │                                       │
     │◄── SSE: { phase: "detecting", ────────┤
     │          images_processed: 32,        │
     │          faces_found: 156 }           │
     │                                       │
     │◄── SSE: { phase: "clustering" } ──────┤
     │                                       │
     │◄── SSE: { phase: "complete", ─────────┤
     │          clusters: [...],             │
     │          identities: [...] }          │
```

---

## 3. SSE Event Schema

### Phase Enumeration

```typescript
type ScanPhase =
  | "ready" // Backend ready to receive uploads
  | "uploading" // Receiving images from plugin
  | "detecting" // Running face detection
  | "clustering" // Running HDBSCAN + suggestions
  | "complete" // All done, results available
  | "error"; // Something failed
```

### Event Payload

```typescript
interface ScanProgressEvent {
  phase: ScanPhase;

  // Upload phase metrics (tracked by backend on receipt)
  images_total: number; // Total images expected
  images_received: number; // Images backend has received

  // Detection phase metrics
  images_processed: number; // Images with detection complete
  faces_found: number; // Running count of detected faces

  // Timing
  started_at: string; // ISO timestamp
  phase_started_at: string; // When current phase began

  // Error info (phase="error" only)
  error_message?: string;
  error_code?: string;
}
```

### Backend Implementation Notes

- `images_received` increments when backend confirms receipt of each upload
- `images_processed` increments as detection completes (may lag behind `images_received`)
- `faces_found` is cumulative across all processed images
- Backend should emit SSE events at reasonable intervals (every image or every 5 images)

---

## 4. Upload Protocol

### Security Requirements

1. **Short-lived upload tokens** — `/scan/start` returns a signed token valid for N minutes
2. **Tenant isolation** — Token scoped to tenant, backend validates on each upload
3. **No WP credentials shared** — Backend never accesses WordPress directly
4. **Rate limiting** — Backend can throttle uploads per tenant

### Upload Endpoint

```
POST /api/v1/scan/{job_id}/upload
Authorization: Bearer {upload_token}
Content-Type: multipart/form-data

Parts:
  - image: binary (JPEG/PNG/WebP)
  - media_id: string (WordPress attachment ID)
  - checksum: string (optional, for integrity verification)
```

### Chunked Upload Considerations

For large images (>5MB), consider chunked upload protocol:

```
POST /api/v1/scan/{job_id}/upload/init
  → { upload_id, chunk_size }

POST /api/v1/scan/{job_id}/upload/{upload_id}/chunk/{n}
  → { received: true }

POST /api/v1/scan/{job_id}/upload/{upload_id}/complete
  → { media_id, processed: true }
```

For MVP, simple single-request upload is sufficient.

---

## 5. Frontend Progress Component

### UI Requirements

```
┌─────────────────────────────────────────────────────────┐
│  Scanning 100 images                                     │
│                                                          │
│  ● Uploading    ○ Detecting    ○ Clustering              │
│  ═══════════════════════════════░░░░░░░░░░░░░░░░░░░░░░░  │
│  45/100 images sent                                      │
│                                                          │
│  Est. time remaining: 2m 30s                             │
└─────────────────────────────────────────────────────────┘
```

After upload phase completes:

```
┌─────────────────────────────────────────────────────────┐
│  Scanning 100 images                                     │
│                                                          │
│  ✓ Uploaded     ● Detecting    ○ Clustering              │
│  ═══════════════════════════════════════════░░░░░░░░░░░  │
│  78/100 processed · 234 faces found                      │
│                                                          │
│  Est. time remaining: 45s                                │
└─────────────────────────────────────────────────────────┘
```

### Component Props

```typescript
interface ScanProgressProps {
  jobId: string;
  progress: ScanProgressEvent;
  onCancel?: () => void;
}
```

### Time Estimation

```typescript
function estimateTimeRemaining(progress: ScanProgressEvent): number | null {
  const elapsed = Date.now() - new Date(progress.phase_started_at).getTime();

  switch (progress.phase) {
    case "uploading": {
      if (progress.images_received === 0) return null;
      const msPerImage = elapsed / progress.images_received;
      const remaining = progress.images_total - progress.images_received;
      return msPerImage * remaining;
    }
    case "detecting": {
      if (progress.images_processed === 0) return null;
      const msPerImage = elapsed / progress.images_processed;
      const remaining = progress.images_received - progress.images_processed;
      return msPerImage * remaining;
    }
    case "clustering":
      // Clustering time is harder to estimate; show indeterminate or omit
      return null;
    default:
      return null;
  }
}
```

---

## 6. Implementation Checklist

### Phase 0: Contracts (1 hr)

- [ ] Define `ScanPhase` enum in shared contracts
- [ ] Define `ScanProgressEvent` interface in shared contracts
- [ ] Add upload token schema to job response

### Phase 1: Backend SSE Events (1.5 hrs)

- [ ] Add `phase` field to existing SSE events
- [ ] Track and emit `images_received` on upload confirmation
- [ ] Track and emit `images_processed`, `faces_found` during detection
- [ ] Add `phase_started_at` timestamps

### Phase 2: Upload Endpoint (1 hr)

- [ ] Implement `POST /scan/{job_id}/upload` endpoint
- [ ] Generate and validate short-lived upload tokens
- [ ] Stream uploads to processing pipeline
- [ ] Emit SSE event on each successful upload

### Phase 3: Frontend Progress (1.5 hrs)

- [ ] Create `ScanProgress` component with phase indicators
- [ ] Subscribe to SSE stream and update progress state
- [ ] Implement time-remaining estimation
- [ ] Add cancel functionality

### Validation

- [ ] Test: Start scan, verify upload phase shows count
- [ ] Test: Verify detection phase shows faces found
- [ ] Test: Progress transitions correctly between phases
- [ ] Test: Time estimates are reasonable

---

## 7. Open Questions

### Q1: Should upload happen in parallel with detection?

**Recommendation**: Yes, for better performance.

- Backend starts detection as soon as first image arrives
- `images_processed` may be less than `images_received` during upload phase
- Frontend shows both metrics when in upload phase

### Q2: How to handle upload failures?

**Recommendation**: Retry with exponential backoff, then skip.

- Plugin retries failed uploads 3 times
- On persistent failure, log and continue with remaining images
- SSE event includes `images_failed` count
- Final results note which images were skipped

### Q3: Token expiration during long uploads?

**Recommendation**: Token refresh mechanism.

- Initial token valid for 15 minutes
- Plugin can request refresh: `POST /scan/{job_id}/token/refresh`
- Backend issues new token, invalidates old one

---

## 8. References

- [offline-cluster-persistence.md](./offline-cluster-persistence.md) — Related WordPress caching architecture
- [false-positive-analysis.md](./false-positive-analysis.md) — Parent analysis document
