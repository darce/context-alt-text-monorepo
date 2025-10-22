HYBRID_FACE_DETECTION_PLAN.v2.md

# Context Alt Text — Hybrid Face Detection & Labeling Plan (v2)

**Status:** Draft for implementation  
**Scope:** Frontend detection (browser), backend recognition (remote), Apple-Photos-style progressive labeling UX  
**Replaces:** HYBRID_FACE_DETECTION_PLAN.md (v1)  
**Related:** `sequence-interactive-detection.v2.mmd`, `sequence-complete-workflow.v2.mmd`,
`face-recognition-workflow.v2.mmd`, `hybrid-detection-classes.v2.mmd`, `uml-class-diagram.v2.mmd`,
`roster-domain-classes.v2.mmd`

---

## 0) Executive Summary

v2 removes the “Interactive vs Batch” toggle and introduces a single, seamless **progressive People labeling** flow:

- **Detect in the browser** (fast, private bounding boxes).
- **Suggest on the backend** (embeddings + FAISS + clustering).
- **Name once, apply many:** when the user names a face, the system proposes the same person across the current selection and future imports.
- **People Drawer** groups unknowns into “likely same person” stacks; users bulk confirm/adjust.

Commercial/IP moat is preserved by keeping **all embeddings and recognition server-side**.

---

## 1) Goals & Non-Goals

### Goals

- Reduce cognitive friction by eliminating mode switching.
- Cold-start fast: a handful of labels should bootstrap high-accuracy suggestions.
- Maintain small FE bundle and accessible controls (WCAG 2.1 AA).

### Non-Goals

- No in-browser embeddings in default flow (may exist behind a lab flag).
- No change to external storage contracts (keep roster & embeddings server-side).

---

## 2) Architecture Overview

Browser (WP Admin SPA)
├─ DetectionProvider (default: MediaPipe Tasks; optional: RetinaFace via ONNXRuntime-Web)
├─ PeopleOverlay (face boxes + “Who is this?” chips)
├─ People Drawer (Unknown clusters + suggestion stacks)
└─ POST /wp-json/cat/v1/recognition/identify → WP

WordPress Plugin (REST + crops)
└─ identify: crops faces (server-side) → Recognition Service
← suggestions (top-k) + cluster ids → merges → Browser

Recognition Service (FastAPI)
├─ /embeddings/batch
├─ /suggest (FAISS search top-k + threshold)
└─ /cluster-unknowns (groups low-confidence faces)

---

## 3) Frontend: UX & Components

### 3.1 PeopleOverlay

- Draws bounding boxes; each box includes a chip: **“Who is this?”**
- Chip opens **PeoplePicker** (typeahead roster + “Create new”).
- Keyboard: focus cycles faces; `Enter` opens picker; `S` confirms suggested; `R` reassigns.

### 3.2 People Drawer (Right Rail)

- **Stacks** unknown faces by backend `clusterId`: “Likely same person (x12)” with bulk **Confirm All** / **Review**.
- **Suggestion stacks** for known persons (e.g., “John Doe? (54)”).
- One-click bulk confirm; misfits return to unknown or reassign flow.

### 3.3 DetectionProvider (pluggable)

- **Default:** MediaPipe Tasks Face Detector (lazy-loaded).
- **Experimental:** RetinaFace (ONNXRuntime-Web, WebGPU → WASM SIMD fallback). Gate behind a feature flag.
- Target perf (desktop CPU): <400 ms/image detection; first model load <4 s.

### 3.4 Data Contracts (FE ↔ WP)

```ts
// POST /wp-json/cat/v1/recognition/identify
{
  attachmentId: number,
  faces: Array<{
    bbox: {x:number, y:number, width:number, height:number},
    faceId?: string,                         // FE temp id for reconciliation
    label?: { rosterId?: string, newName?: string } // present only when user labeled
  }>
}

// Response
{
  faces: Array<{
    faceId: string,
    clusterId?: string,
    suggestions: Array<{ rosterId: string, display: string, score: number }>
  }>
}

4) Backend: WP REST + Recognition Service
4.1 WP REST Endpoint

POST /wp-json/cat/v1/recognition/identify

Validates capability, resolves attachment, crops faces server-side (GD/Imagick).

Sends crops to Recognition Service:

/embeddings/batch → embeddings

/suggest → top-k matches for roster

/cluster-unknowns → cluster ids for low-confidence faces

Persists labeled observations when label is present.

Returns unified suggestions[] and clusterId.

4.2 Recognition Service Endpoints

POST /api/v0/embeddings/batch: { images[] } → { embeddings[] }

POST /api/v0/suggest: { embeddings[], topK, threshold } → { suggestions[][] }

FAISS (IndexFlatIP / HNSW) with normalized vectors; configurable threshold (default 0.92).

POST /api/v0/cluster-unknowns: { embeddings[] } → { clusterIds[] }

DBSCAN/Agglomerative; tunables in config.

5) Data Model (DB)

Extend observations to support suggestion/cluster UX.

-- cat_observation (new/extended columns)
ALTER TABLE cat_observation
  ADD COLUMN cluster_group_id VARCHAR(64) NULL,
  ADD COLUMN suggested_roster_id VARCHAR(64) NULL,
  ADD COLUMN suggested_score DECIMAL(5,4) NULL,
  ADD COLUMN label_status ENUM('unlabeled','suggested','confirmed','rejected','corrected') NOT NULL DEFAULT 'unlabeled';

-- cat_roster unchanged (id, display_name, metadata, avatar, etc.)

-- cat_observation_embedding (unchanged if it already exists; else:)
CREATE TABLE IF NOT EXISTS cat_observation_embedding (
  observation_id BIGINT UNSIGNED NOT NULL,
  model VARCHAR(64) NOT NULL,
  vec MEDIUMBLOB NOT NULL,
  created_at DATETIME NOT NULL,
  PRIMARY KEY (observation_id, model)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

6) Primary User Flows
6.1 Cold Start (no roster)

User selects 50–200 images in Workbench.

FE detects faces; posts all bboxes to identify.

Backend clusters unknowns → Drawer shows “3 likely people groups”.

User names Group A (“Ana”) and Group B (“Marta”); bulk applies.

Suggestions ramp; user Confirm All on remaining stacks.

6.2 Warm Start (existing roster)

Import 200 new photos.

Suggestions arrive immediately (“John Doe? (54)”).

Confirm All then fix a few misfits.

7) Settings

Smart Labeling: ON (not surfaced as a mode).

Auto-apply threshold: default 0.92 (UI slider in Advanced).

Detection engine: Auto (MediaPipe) | RetinaFace (Experimental).

Performance budget: FE bundle delta ≤ 1.5 MB gz (lazy-loaded).

8) Accessibility

Face chips are buttons with ARIA: “Unknown face 2 of 7. Press Enter to name.”

Drawer lists use roving tabindex; Home/End jump stacks; live regions announce bulk actions.

Color not sole indicator; large hit targets (≥44px).

9) Telemetry KPIs

Avg clicks per labeled person: –40% vs v1

Time to first 10 named persons (cold start): –50%

Suggestion acceptance after 20 labels: ≥85%

Abandonment on first run: –30%

10) TDD & QA

FE unit/integration: Detection hooks, Overlay focus cycle, Drawer bulk confirm/reassign.

Contract tests: FE DTOs ↔ WP Controller ↔ RecSvc OpenAPI.

BE perf tests: FAISS top-k @ 1k/10k; clustering latency; cache reload TTL.

E2E: Cold start happy path, mis-suggest correction, screen reader checks.

11) Rollout Plan

RecSvc: add /suggest, /cluster-unknowns; verify FAISS + thresholds.

WP: implement identify, cropper, persistence of labels & suggestion hints.

FE: DetectionProvider abstraction; PeopleOverlay + Drawer; background identify loop.

Polish: Remove v1 toggle; add short explainer tooltip; Storybook + a11y audit.

12) Security & Privacy

No embeddings computed in browser by default.

Crops sent over TLS to self-hosted RecSvc; roster & vectors never exposed publicly.

Fine-grained capabilities on WP endpoints; audit logging for label changes.

13) Changelog (v2 vs v1)

Removed “Interactive vs Batch” UI.

Added /suggest, /cluster-unknowns service endpoints.

New DB fields for cluster/suggestion/label status.

Introduced People Drawer + bulk Confirm All.

Clarified default vs experimental detection providers.

14) File structure (delta)
apps/wp-context-alt-text/
├── js/
│   ├── components/workbench/
│   │   ├── PeopleOverlay.tsx
│   │   ├── PeopleDrawer.tsx
│   │   └── PeopleSuggestionChip.tsx
│   ├── hooks/useFaceDetection.ts
│   ├── hooks/usePeopleSuggestions.ts
│   └── utils/detectors/
│       ├── mediapipe.ts (default)
│       └── retinaface.ts (experimental)
└── src/Recognition/
    ├── IdentifyController.php            // /recognition/identify
    ├── ImageCropUtility.php
    └── ObservationRepository.php         // add cluster/suggestion fields

15) Optional: WP Route & DTO Stubs (drop-in)
// includes/Routes/Api.php
Route::prefix( '/cat/v1', function( Route $route ) {
    $route->post( '/recognition/identify', '\ContextAltText\Controllers\Recognition\IdentifyController@handle' );
});

// src/Recognition/IdentifyController.php
namespace ContextAltText\Controllers\Recognition;

class IdentifyController {
    public function handle( \WP_REST_Request $req ) {
        $payload = json_decode( $req->get_body(), true );
        // 1) validate caps, resolve attachment
        // 2) crop faces by bbox (server-side)
        // 3) call RecSvc: /embeddings/batch → /suggest → /cluster-unknowns
        // 4) persist labeled observations if present
        // 5) return per-face {faceId, clusterId?, suggestions[]}
        return rest_ensure_response([ 'faces' => /* ... */ ]);
    }
}

// js/types/identify.ts
export type IdentifyRequest = {
  attachmentId: number;
  faces: Array<{
    bbox: { x:number; y:number; width:number; height:number };
    faceId?: string;
    label?: { rosterId?: string; newName?: string };
  }>;
};

export type IdentifyResponse = {
  faces: Array<{
    faceId: string;
    clusterId?: string;
    suggestions: Array<{ rosterId: string; display: string; score: number }>;
  }>;
};

```
