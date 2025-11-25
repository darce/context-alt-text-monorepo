# Workbench Cluster Editing Plan

_Status: Draft proposal for review_

## Goals & Requirements

- Suridentity every detected identity (clustered or unclustered) for each attachment listed in the workbench table, rendered inside the `acx-media-selection__details` cell.
- Ensure `handleScanIdentities` immediately reflects the latest detections once the scan job finishes, so operators can review clusters without leaving the page.
- Allow operators to “name this person” by merging the current cluster into an existing or newly created user-defined cluster label so every identity tied to that person reflects the curated name throughout the Workbench UI.
- Prepare for the follow-up feature where each detected identity is outlined with its bounding box; when the label is still auto-generated (e.g., `cluster-0af31e47`), prompt users to name the person directly in-context.

## Current State

- `useWorkbenchMedia` fetches `/acx/v1/workbench/media`, which currently returns attachment metadata (title, alt text status, tags, etc.) but **no** recognition context.
- Scans launched via `handleScanIdentities` trigger `POST /acx/v1/workbench/recognition/analyze`; once the async job finishes the operator must open the roster to inspect clusters.
- Cluster labels come from the recognition service (default format `cluster-<hash>`). There is no UI or API available to merge clusters or override the auto-generated label.
- `MediaSelection.tsx` simply shows two lines of text in the details cell; there is no room for identity previews or controls.

## Proposed Changes

### 1. Backend data contract (Recognition/Identity service)

1. **Recognition/Identity service** (aligning with the archived recognition nomenclature): introduce `GET /recognition/media/identities?tenant_id=<>&media_ids[]=...` returning:
   - `media_id`
   - `identities`: `{ identity_id, cluster_id, cluster_label, bbox, thumbnail_url?, confidence, similarity, detected_at }`
   - `cluster_label_is_auto`: boolean to detect default labels
2. **Cluster mutations**: add endpoints to rename and merge clusters (e.g., `PATCH /recognition/clusters/{cluster_id}` for label edits and `/recognition/clusters/{source_id}/merge` to fold one cluster into another).
3. **WordPress proxy** (`RecognitionProxyController`):
   - Forward the new batch identities endpoint (e.g., `/workbench/recognition/media-identities`).
   - Forward cluster label updates (e.g., `/workbench/recognition/clusters/{id}`).
4. **Workbench media API** (`GET /acx/v1/workbench/media`):
   - Keep this endpoint lean (attachment metadata only) and let the SPA call the proxy `GET /workbench/recognition/media-identities` endpoint directly via React Query. This avoids turning the WordPress REST layer into a heavyweight serializer on every pagination event and keeps caching responsibilities in the recognition domain.
5. **Caching**: memoize the identity lookups inside the recognition proxy/service (e.g., `wp_cache_set` at the proxy boundary plus Redis/PG caching in the prototype service) and hydrate React Query caches per attachment so pagination remains responsive without duplicating work inside PHP.

#### Auto-merge parity with archived recognition service

The legacy recognition stack (`apps/archived-wp-context-alt-text/src/Domain/Clustering/ClusteringService.php`, lines 582‑651) automatically merged clusters whose representative embeddings fell within the configured similarity threshold. We should port that behaviour to the modern recognition/identity service:

1. **Cluster similarity pass**: After `IdentityClusteringService.cluster_identities()` writes new clusters, enqueue a consolidation job (Celery/RQ or background async task) that:
   - Computes cosine distances between cluster representatives (or average embeddings).
   - Identifies cluster pairs whose distance ≤ merge threshold (reuse archived logic: iterate until no merges remain).
   - Merges member lists and updates `identity_count`, `representative_identity_id`, and `roster_id` (if either cluster was assigned).
2. **Implementation hooks**:
   - Add a `_merge_similar_clusters()` helper inside the recognition service (`apps/prototype-description-service/recognition/application/identity_clustering_service.py`) that mirrors the PHP algorithm (using SQLAlchemy queries + numpy vector math) and can be called by both the post-cluster job and a manual endpoint.
   - Expose a management endpoint (`POST /recognition/clusters/merge-similar`) so we can trigger consolidation on demand (e.g., scheduled task) in addition to automatic runs after clustering jobs.
   - Emit events/logs (or webhooks) when merges complete so the Workbench UI can invalidate caches immediately instead of waiting for polling.
3. **Data integrity**: wrap merges in transactions to keep `cluster_members` consistent, update `updated_at`, and soft-delete redundant cluster rows.

### 2. Front-end data loading

1. Extend `WorkbenchMediaItem` type (TS) with:

```ts
type DetectedIdentity = {
  id: string;
  clusterId: string | null;
  clusterLabel: string | null;
  isAutoLabel: boolean;
  bbox: { x: number; y: number; width: number; height: number };
  thumbnailUrl: string | null;
};
```

2. Update `useWorkbenchMedia` so it passes `include_identities=1` and normalises the new identities collection, exposing it via a dedicated `useMediaIdentities` hook that calls `fetchMediaIdentities`.
3. Prefetch identities for the next page: when querying page **N**, also collect attachment IDs for page **N+1** (if it exists) and call the `media-identities` endpoint once with the combined ID list. Store the responses in react-query keyed by attachment so that when the user advances the paginator, the data is already cached. If the user skips further ahead (or backward), issue a new request for that page’s IDs on demand.
4. Add a `useClusterLabelSearch` hook (backed by `/workbench/recognition/clusters?search=...`) for the autosuggest input.
5. When `handleScanIdentities` succeeds (either immediately or after the status hook reports completion), force-refetch both the media list and the per-media identities query (TanStack `queryClient.invalidateQueries`). Longer term, stream scan progress via SSE/WebSockets so each detected identity can be pushed into the cache without a full refetch.

### 3. UI / UX updates

1. Replace the static text in `acx-media-selection__details` with:
   - Media title + alt text (existing).
   - A identity cluster list showing **one thumbnail per cluster** present in that media item. If multiple identities on the same attachment belong to the same cluster, aggregate them and show a counter badge.
   - For each cluster entry:
     - Show the cluster label if user-defined.
     - If `isAutoLabel` is true, render a “Name this person” inline button/input.
2. “Name this person” flow:
   - Clicking reveals an input with typeahead results (`useClusterLabelSearch`).
   - Selecting an existing label merges the current cluster into that target cluster (all identities now belong to the chosen cluster ID/label). Creating a new label spins up a new cluster record, then merges the current cluster into it so future detections can reuse the curated name.
   - Implement the merge via a dedicated `/recognition/clusters/{source_id}/merge` endpoint or a batched reassignment call so we avoid one-by-one identity updates while preserving historical membership.
   - On success, optimistically update the cached `identities` arrays so every row shows the merged cluster label.
3. Loading / empty states:
   - If identities are still fetching, show a skeleton or “Detecting identities…” badge inside the details cell.
   - If no identities exist for an attachment, show helper text encouraging the operator to run a scan.
4. Future prep:
   - Structure the identity list component so we can plug in bounding boxes later by layering a toggleable overlay directly on the table-row thumbnail (no modal/popover). Reuse a shared measurement pipeline (`<IdentityOverlayFrame>`) that drives both the Workbench rows and roster drawer, but render the overlay itself via CSS borders applied to transparent divs (instead of canvas) so the visuals stay crisp and lightweight.

### 4. Sequence of work

1. **Schema & type updates**: update shared JSON schema + PHPStan annotations for `WorkbenchMediaItem`.
2. **Recognition service endpoints**: implement `media-identities` GET + `cluster label PATCH`, add tests.
3. **WP proxy / REST**: expose new routes, wire config to JS (extend `window.AltContextAdmin.endpoints`).
4. **Workbench API**: update `get_workbench_media` to fetch identities when requested.
5. **Frontend hooks**: update `useWorkbenchMedia`, add hooks for cluster search & label mutations.
6. **UI components**: redesign `MediaSelection` details cell, integrate inline merge (“Name this person”) + autosuggest.
7. **Scan integration**: hook `handleScanIdentities` success + scan status completion to refetch identities.
8. **QA**: verify renaming propagates, multi-page navigation, error handling, and fallback states.

## Notes

1. The `media-identities` endpoint will return identities only for the attachments requested (including the N+1 prefetch page) so pagination never fetches content that isn’t being rendered.
2. Merge semantics are confirmed: selecting an existing label merges the current cluster into the target cluster, while new labels create-and-merge via a dedicated merge endpoint.
3. Autosuggest starts with roster entries scoped to the tenant and falls back to “Name this person” only when no roster match exists, which requires backend roster search and auto-merge support.
4. Tenant isolation must be enforced so cluster data never mixes between tenants; enforce unique user-defined labels per tenant so each recognized identity maps to a single cluster record (add composite DB constraints such as `UNIQUE(tenant_id, label)` plus RLS policies).
5. Bounding-box overlays are inline toggles layered over the table-row thumbnails (no modal/popover), with the overlay control details to be worked out during implementation.
