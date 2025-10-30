# Context Alt Text — Consolidated Face Recognition Plan (2025)

**Status:** Draft for implementation  
**Scope:** Remote face detection, clustering, and labeling UX in Workbench  
**Replaces:** `HYBRID_FACE_DETECTION_PLAN.md` (all variants)  
**Related:** `sequence-complete-workflow.v3.mmd`, `backend-recognition-flow.v3.mmd`,
`cluster-lifecycle.v3.mmd`, `roster-domain-classes.v2.mmd`

---

## 0) Executive Summary

The consolidated plan removes all browser-resident face models and delegates every detection,
embedding, and clustering step to the recognition service. The WordPress plugin now treats the
recognition pipeline as a **single source of truth** while the Workbench UI focuses on triaging and
confirming server-provided results.

- **Detection-as-a-service:** All bounding boxes originate from recognition jobs or on-demand
  identify requests that call the remote service.
- **Progressive labeling:** Unknown faces surface in the People Drawer, clustered by backend ids;
  confirming one face fans out to every matching observation.
- **Offline resilience:** When the service is unavailable, the controller returns deterministic
  fallback payloads and the UI persists provisional labels locally until sync resumes.

This approach shrinks the frontend bundle, simplifies accessibility, and keeps the recognition IP
behind controlled infrastructure.

---

## 1) Goals & Non-Goals

### Goals

- Deliver a single Workbench labeling flow that always reflects the current server state.
- Reduce maintenance cost by eliminating MediaPipe/ONNX packaging from the plugin.
- Ensure consistent clustering and suggestion quality across manual labeling and automated jobs.
- Preserve privacy by keeping embeddings and model payloads on trusted servers.

### Non-Goals

- No in-browser detection, embeddings, or cosine matching (even behind feature flags).
- No changes to external API contracts for third-party roster integrations.
- No attempt to run recognition when the service is explicitly disabled in site settings.

---

## 2) Architecture Overview

```
Workbench SPA (React + WP REST)
├─ PeopleOverlay (renders boxes provided by backend)
├─ PeopleDrawer (clusters + suggestion stacks)
├─ useUnknownClusters / useClusterDetail (query server data)
└─ usePeopleSuggestions (labels + optimistic UX)

WordPress Plugin (PHP)
├─ POST /recognition/analyze → queue recognition jobs (face detection + embeddings)
├─ POST /recognition/identify → proxy to recognition service for ad-hoc suggestions
├─ GET /unknown-clusters → read-only cluster summaries
├─ GET /cluster/:id → per-cluster faces
└─ Observation persistence + offline fallbacks

Recognition Service (FastAPI)
├─ /v0/detect-and-embed (multi-face detection + embeddings)
├─ /v0/suggest (FAISS search, roster aware)
├─ /v0/cluster-unknowns (nightly + on-demand refresh)
└─ Observation sync webhooks → WordPress
```

Key change: browsers never send bounding boxes or embeddings; they request the latest observations
(faces, clusters, and suggestions) already produced server-side.

---

## 3) Frontend UX & Data Contracts

### 3.1 Workbench Surfaces

- **Unknown People Panel:** Paginated list via `GET /unknown-clusters`; shows counts and sample crop.
- **Cluster Detail Drawer:** `GET /clusters/{id}` returns every face in the cluster with bounding boxes
  and suggestion metadata. PeopleDrawer and PeopleOverlay both consume this response.
- **PeopleOverlay:** Renders `FaceObservation` data (bbox in pixel space) and delegates actions to
  `usePeopleSuggestions`.

### 3.2 People Labeling Flow

1. User opens a cluster from the Unknown People Panel.
2. SPA fetches cluster detail; faces arrive with server-generated `faceId`, `clusterId`, suggestions,
   and observation identifiers.
3. Selecting a face opens the PeoplePicker; submitting a label triggers
   `POST /recognition/identify` with **observation ids only** (no detections). The controller locks
   the observation and forwards the request to the recognition service to persist embeddings and
   suggestions.
4. Optimistic UI updates; upon success, queries invalidate to refresh cluster metrics.

### 3.3 Identify Request (new schema)

```ts
type IdentifyRequest = {
  attachmentId: number;
  observationIds: string[]; // existing observations created by detection jobs
  faces: Array<{
    faceId: string; // server-issued id for reconciliation
    label: {
      rosterId?: string;
      newName?: string;
      displayName?: string;
    };
  }>;
};

type IdentifyResponse = {
  faces: Array<{
    faceId: string;
    clusterId: string | null;
    rosterId?: string;
    observationId?: number;
    suggestions: Suggestion[];
    syncStatus: "success" | "pending" | "failed";
    syncError?: string;
  }>;
  error?: string;
};
```

Bounding boxes and embeddings are implicit because the recognition service already holds them for
the referenced observation ids.

---

## 4) WordPress Plugin Responsibilities

### 4.1 Recognition Jobs

- `/recognition/analyze` accepts attachment lists, enqueues jobs, and mirrors job state in
  `cat_recognition_jobs`.
- Each worker run calls `/v0/detect-and-embed` with media crops, stores observations (bbox, embedding
  checksum, cluster assignment) and populates `_cat_synced_to_faiss` status on posts.

### 4.2 Identify Controller

- Validates capability (`upload_files`) and ensures recognition is enabled.
- Requires either the recognition service to be **online** (health check succeeded in last N minutes)
  or immediately raises `service_unavailable` (HTTP 503). When offline, returns deterministic fallback
  payload (preserves optimistic UI) and queues a retry job.
- Calls recognition client methods:
  - `persistObservationLabel(observationId, rosterId | newName)`
  - `scheduleEmbeddingSync(rosterId, observationId)`
- Normalizes suggestion payloads and sync metadata before responding.

### 4.3 Cluster APIs

- `GET /unknown-clusters`: aggregated counts, sample thumbnails, last updated timestamp.
- `GET /clusters/{id}`: returns faces with bbox, observation id, roster suggestions, exposure history.
- `POST /clusters/{id}/confirm`: bulk applies roster id to every face in the cluster.

### 4.4 Offline Fallback

- Persist user-supplied labels to `localStorage` (already implemented in hook) and `wp_options` table
  via `cat_offline_face_labels` option keyed by attachment id.
- Background cron reconciles cached labels once recognition service is healthy again.

---

## 5) Recognition Service Responsibilities

- Single endpoint (`/v0/detect-and-embed`) returns detections and embeddings for provided media ids;
  response includes deterministic `faceId` stable across re-runs.
- `/v0/suggest` performs FAISS searches against roster embeddings with configurable thresholds.
- `/v0/cluster-unknowns` groups unsupervised faces; results stored in service DB and echoed to WP.
- Webhooks notify WP when cluster assignments change, enabling push-based cache invalidation.

Operational targets:

- Detect + embed ≤ 800 ms for 2K images on CPU (batch friendly).
- Suggest queries ≤ 150 ms P95 with 10K roster entries.
- Cluster refresh every 5 minutes while queue non-empty (tunable).

---

## 6) Data Model Changes

```
cat_observation
├─ id BIGINT UNSIGNED PK
├─ attachment_id BIGINT UNSIGNED NOT NULL
├─ bbox_x DECIMAL(10,4)
├─ bbox_y DECIMAL(10,4)
├─ bbox_w DECIMAL(10,4)
├─ bbox_h DECIMAL(10,4)
├─ cluster_group_id VARCHAR(64) NULL
├─ suggested_roster_id VARCHAR(64) NULL
├─ suggested_score DECIMAL(5,4) NULL
├─ label_status ENUM('unlabeled','suggested','confirmed','rejected','corrected') DEFAULT 'unlabeled'
├─ embedding_checksum CHAR(64) NULL -- SHA256 for dedupe
├─ recognition_job_id CHAR(36) NULL
└─ synced_to_faiss TINYINT(1) DEFAULT 0

cat_cluster_summary (new)
├─ id VARCHAR(64) PK
├─ face_count INT UNSIGNED
├─ sample_observation_id BIGINT UNSIGNED
├─ suggestion_roster_id VARCHAR(64) NULL
├─ suggestion_score DECIMAL(5,4) NULL
├─ refreshed_at DATETIME

cat_offline_face_label (new, optional)
├─ attachment_id BIGINT UNSIGNED PK
├─ payload JSON NOT NULL -- draft labels captured during outage
├─ updated_at DATETIME NOT NULL
```

---

## 7) Primary User Flows

### 7.1 Cold Start (Service Online)

1. Admin selects 100 photos and clicks **Scan for Faces**.
2. `/recognition/analyze` queues job; recognition service detects faces and pushes observations.
3. Unknown People Panel shows new clusters; user opens a cluster, confirms roster id.
4. Confirming updates observations, re-clusters remaining faces, and pushes new suggestions.

### 7.2 Warm Start (Existing Roster)

1. Recognition jobs run nightly or on upload; suggestions already computed.
2. Workbench immediately lists suggestion stacks with high confidence.
3. User bulk confirms or corrects; `identify` ensures roster embeddings stay in sync.

### 7.3 Service Outage

1. Identify controller health check fails and returns 503 with fallback faces.
2. UI stores provisional labels locally and shows “Pending sync” state.
3. Background task retries once service is up; UI invalidates caches when sync completes.

---

## 8) Settings & Feature Flags

- **Recognition → Enable labeling:** toggles availability of Workbench people features.
- **Auto-confirm threshold:** stored in `cat_recognition_settings`, controls FAISS acceptance.
- **Cluster refresh cadence:** server-side, but surfaced as read-only telemetry in settings panel.
- **Telemetry opt-in:** gating aggregated performance metrics.

No user-facing toggle for detection engines; MediaPipe/RetinaFace artifacts removed.

---

## 9) Accessibility Commitments

- PeopleOverlay chips remain button elements with screen-reader announcements including position,
  cluster, and pending sync status.
- Drawer stacks support roving tabindex; bulk actions emit polite live-region updates.
- Error and offline banners use role="alert" and persist until dismissed.

---

## 10) Telemetry & KPIs

- Time from scan completion to first confirmed label (target ≤ 90 seconds P50).
- Suggestion acceptance rate after 20 confirmations (target ≥ 85%).
- Retry volume due to recognition outages (monitor for spikes > 2% of requests).
- Average cluster size variance (ensures clustering quality remains stable).

---

## 11) Testing Strategy

- **PHP unit tests:** IdentifyController failure modes (capability, offline fallback, roster creation).
- **API contract tests:** JSON schema snapshots for `/unknown-clusters`, `/clusters/{id}`,
  `/recognition/identify`.
- **React tests:** PeopleDrawer grouping, PeopleOverlay focus cycle, optimistic label rollback.
- **Integration:** Emulate recognition service outage to verify local persistence + retry.
- **Load tests:** Recognition service detection batches (1k media) and suggestion latency at scale.

---

## 12) Rollout Plan

1. Ship recognition service endpoints (`detect-and-embed`, `suggest`, `cluster-unknowns`).
2. Update WP plugin data model migrations and background job workers.
3. Remove MediaPipe artifacts from repo (hooks, utils, tests, bundle config).
4. Deliver new Workbench UX with cluster + observation-driven flow.
5. Enable progressive rollout via feature flag; monitor telemetry dashboards.
6. Once stable, delete legacy detection documentation and close follow-up tickets.

---

## 13) Security & Privacy

- All recognition traffic remains server-to-server; SPA only consumes sanitized observation data.
- Capability checks enforced on every endpoint; IdentifyController re-verifies `upload_files`.
- Observations include audit metadata (who labeled, when) stored in post meta for compliance.
- No embeddings or crops persist in browser storage beyond temporary fallbacks.

---

## 14) Changelog (vs. Hybrid Plan)

- Removed DetectionProvider abstraction and MediaPipe/RetinaFace dependencies.
- Identify request now references existing observations instead of raw detections.
- Introduced cluster + observation APIs to drive Workbench UI.
- Added offline persistence + retry strategy for recognition outages.

---

## 15) File Structure (Delta)

```
apps/wp-context-alt-text/
├── js/
│   ├── components/workbench/
│   │   ├── PeopleOverlay.tsx
│   │   ├── PeopleDrawer.tsx
│   │   ├── ClusterDetailView.tsx
│   │   └── WorkbenchApp.tsx
│   ├── hooks/
│   │   ├── usePeopleSuggestions.ts
│   │   ├── useUnknownClusters.ts
│   │   └── useFaceScan.ts
│   └── utils/ (no detectors)
└── src/Recognition/
    ├── IdentifyController.php
    ├── RecognitionClient.php
    └── Observations/
        ├── ObservationRepository.php
        └── ClusterRepository.php
```

Legacy files (`useFaceDetection.ts`, `faceEmbeddings.ts`, MediaPipe loader) are removed during rollout.

---

## 16) Open Questions

1. Do we require real-time health checks, or is cached status (e.g., cron heartbeat) sufficient for
   gating IdentifyController?
2. Should offline labels queue per observation (granular) or per attachment (current draft)?
3. What retention policy applies to cluster summaries once all faces in the cluster are labeled?

Document owner: `@darce`  
Last updated: 2025-10-29
