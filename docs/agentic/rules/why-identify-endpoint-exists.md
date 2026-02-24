# Detection vs Identification Boundary

## Architectural Rule

Face **detection** (locating bounding boxes) runs client-side in the browser via MediaPipe WASM. Face **identification** (who is this person?) runs server-side via the recognition service. Do not merge these concerns.

## Why the Split is Non-Negotiable

1. **Privacy** -- only bbox coordinates leave the browser; full images stay local.
2. **Persistence** -- embeddings, clusters, and roster labels live in the PostgreSQL database. Browser state is ephemeral.
3. **ML weight** -- InsightFace (buffalo_l) embedding extraction and constrained-HAC clustering are too heavy for WASM.
4. **Security** -- WordPress enforces `upload_files` capability checks before proxying to the recognition service.

## Current Data Flow

```
Browser (MediaPipe)        WordPress REST proxy        Recognition Service
  detect bboxes  ------>  POST /recognition/cluster  ------>  extract embeddings
                          (acx/v1/ namespace)                 constrained-HAC clustering
                 <------  cluster results + suggestions <---  pgvector similarity search
```

Key endpoints: see [../contracts/clustering-api.md](../contracts/clustering-api.md).

## Boundary Definition

| Responsibility          | Layer              | Tech                     |
| ----------------------- | ------------------ | ------------------------ |
| Detect face bboxes      | Browser (frontend) | MediaPipe Face Detection |
| Extract 512-d embedding | Recognition svc    | InsightFace buffalo_l    |
| Cluster unknown faces   | Recognition svc    | Constrained HAC          |
| Vector similarity       | Recognition svc    | pgvector (PostgreSQL)    |
| Persist labels/clusters | WP plugin          | WordPress REST + DB      |

## Anti-patterns

- Do NOT run identification in the browser (no persistent store, no access control, heavy models).
- Do NOT send full images to the backend (bandwidth, privacy).
- Do NOT bypass WP proxy for direct backend calls (loses permission checks + tenant isolation).
