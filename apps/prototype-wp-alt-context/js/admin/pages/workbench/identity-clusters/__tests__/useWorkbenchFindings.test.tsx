import React from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  fetchPendingMergeSuggestions,
  fetchPendingNameSuggestions,
  fetchPendingSuggestions,
  fetchTopUnlabeledClusters,
} from '../../../../api/recognition';
import { resetConfigCache } from '../../../../api/config';
import { DATA_SOURCE } from '../../../../api/recognition/types';
import type {
  PendingMergeSuggestion,
  PendingNameSuggestion,
  PendingSuggestion,
  TopUnlabeledCluster,
} from '../../../../api/recognition/types';
import { fromPendingRow } from '../suggestionProjection';
import { buildSuggestionReviewItems } from '../suggestionReviewItems';
import {
  buildWorkbenchFindings,
  NEXT_ACTION_KIND,
  NONE_REASON,
  useWorkbenchFindings,
  type WorkbenchFindingsQueues,
  type WorkbenchFindingsSourceState,
} from '../useWorkbenchFindings';

vi.mock('../../../../api/recognition', async () => {
  const actual = await vi.importActual<typeof import('../../../../api/recognition')>('../../../../api/recognition');
  return {
    ...actual,
    fetchPendingSuggestions: vi.fn(),
    fetchPendingMergeSuggestions: vi.fn(),
    fetchPendingNameSuggestions: vi.fn(),
    fetchTopUnlabeledClusters: vi.fn(),
  };
});

const makeSuggestion = (overrides: Partial<PendingSuggestion> = {}): PendingSuggestion => ({
  id: 'sugg-1',
  identity_id: 'identity-1',
  suggested_cluster_id: 'cluster-1',
  representative_similarity: 0.8,
  // Human-labeled by default so buildSuggestionReviewItems keeps the row (isHumanLabeledTarget).
  cluster_label: 'Default Label',
  ...overrides,
});

const makeReviewItems = (...rows: PendingSuggestion[]) =>
  buildSuggestionReviewItems(rows.map(fromPendingRow));

const makeMerge = (overrides: Partial<PendingMergeSuggestion> = {}): PendingMergeSuggestion => ({
  id: 'merge-1',
  cluster_a_id: 'cluster-a',
  cluster_b_id: 'cluster-b',
  similarity: 0.9,
  status: 'pending',
  ...overrides,
});

const makeName = (overrides: Partial<PendingNameSuggestion> = {}): PendingNameSuggestion => ({
  id: 'name-1',
  cluster_id: 'cluster-n',
  suggested_name: 'Ada Lovelace',
  confidence_score: 0.7,
  source: 'roster',
  created_at: '2026-06-05T00:00:00Z',
  expires_at: null,
  ...overrides,
});

const makeCluster = (overrides: Partial<TopUnlabeledCluster> = {}): TopUnlabeledCluster => ({
  id: 'top-1',
  tenant_id: 'test-tenant-id',
  label: null,
  is_labeled: false,
  is_auto_label: false,
  identity_count: 3,
  user_confirmed: false,
  representatives: [{ id: 'rep-1', media_id: 1, is_pinned: false, thumb_url: 'http://example.test/face.jpg' }],
  ...overrides,
});

const makeQueues = (overrides: Partial<WorkbenchFindingsQueues> = {}): WorkbenchFindingsQueues => ({
  reviewItems: [],
  assignmentTotal: 0,
  mergeSuggestions: [],
  mergeTotal: 0,
  nameSuggestions: [],
  nameTotal: 0,
  topUnlabeledClusters: [],
  // Mirrors the hook fallback: server total defaults to the fetched page length.
  topUnlabeledTotal: overrides.topUnlabeledClusters?.length ?? 0,
  topUnlabeledTruncated: false,
  topUnlabeledRepairPending: false,
  ...overrides,
});

const makeState = (overrides: Partial<WorkbenchFindingsSourceState> = {}): WorkbenchFindingsSourceState => ({
  assignmentDataSource: DATA_SOURCE.LOCAL_PROJECTION,
  nameDataSource: DATA_SOURCE.LOCAL_PROJECTION,
  topUnlabeledDataSource: DATA_SOURCE.LOCAL_PROJECTION,
  isLoading: false,
  isError: false,
  isTopUnlabeledError: false,
  isAssignmentError: false,
  queueSettled: true,
  ...overrides,
});

describe('buildWorkbenchFindings', () => {
  it('summarizes counts from queue totals and unlabeled cluster list', () => {
    const model = buildWorkbenchFindings(
      makeQueues({
        reviewItems: makeReviewItems(makeSuggestion()),
        assignmentTotal: 3,
        mergeSuggestions: [makeMerge()],
        mergeTotal: 2,
        nameSuggestions: [makeName()],
        nameTotal: 1,
        topUnlabeledClusters: [makeCluster(), makeCluster({ id: 'top-2', identity_count: 5 })],
      }),
      makeState(),
    );

    expect(model.counts).toEqual({
      assignments: 3,
      merges: 2,
      names: 1,
      unlabeledClusters: 2,
      total: 8,
    });
    expect(model.hasFindings).toBe(true);
  });

  // REV-A-01: counts must use server total, not the capped page length (TOP_UNLABELED_LIMIT=20).
  it('reports the server-side unlabeled total when it exceeds the fetched page', () => {
    const model = buildWorkbenchFindings(
      makeQueues({
        topUnlabeledClusters: [makeCluster()],
        topUnlabeledTotal: 25,
      }),
      makeState(),
    );

    expect(model.counts.unlabeledClusters).toBe(25);
    expect(model.counts.total).toBe(25);
    // Next action still targets the loaded page.
    expect(model.nextAction).toEqual({ kind: NEXT_ACTION_KIND.CLUSTER, clusterId: 'top-1' });
  });

  // E21-20-REV1-01 / TEST-15: page-local zeros must not be subtracted from the
  // server-wide total. Goes red against `topUnlabeledTotal - zeroEvidenceClusterCount`.
  it('does not subtract page-local zero-evidence clusters from the server unlabeled total', () => {
    const loadedPage = [
      makeCluster({ id: 'zero-a', identity_count: 0 }),
      makeCluster({ id: 'zero-b', representatives: [] }),
      makeCluster({ id: 'zero-c', identity_count: 0, representatives: [] }),
      ...Array.from({ length: 17 }, (_, index) =>
        makeCluster({ id: `reviewable-${index}`, identity_count: 4 + index }),
      ),
    ];
    const model = buildWorkbenchFindings(
      makeQueues({
        topUnlabeledClusters: loadedPage,
        topUnlabeledTotal: 42,
      }),
      makeState(),
    );

    expect(model.zeroEvidenceClusterCount).toBe(3);
    expect(model.counts.unlabeledClusters).toBe(42);
    expect(model.counts.total).toBe(42);
    expect(model.hasFindings).toBe(true);
    expect(model.queue).toHaveLength(17);
  });

  it('R2-12: repair_pending from the envelope drives the resync gate', () => {
    const model = buildWorkbenchFindings(
      makeQueues({
        topUnlabeledClusters: [],
        topUnlabeledTotal: 5,
        topUnlabeledTruncated: true,
        topUnlabeledRepairPending: true,
      }),
      makeState(),
    );

    expect(model.repairPending).toBe(true);
    expect(model.zeroEvidenceClusterCount).toBe(0);
    expect(model.counts.unlabeledClusters).toBe(5);
  });

  it('R2-12: empty served page with server total remaining is repair, not drain', () => {
    const model = buildWorkbenchFindings(
      makeQueues({
        topUnlabeledClusters: [],
        topUnlabeledTotal: 5,
        topUnlabeledTruncated: true,
        topUnlabeledRepairPending: false,
      }),
      makeState(),
    );

    expect(model.repairPending).toBe(true);
    expect(model.counts.unlabeledClusters).toBe(5);
  });

  it('prioritizes the highest-score assignment suggestion as next action', () => {
    const low = makeSuggestion({ id: 'sugg-low', suggested_cluster_id: 'c-low', representative_similarity: 0.5 });
    const high = makeSuggestion({
      id: 'sugg-high',
      suggested_cluster_id: 'c-high',
      representative_similarity: 0.95,
      cluster_label: 'Grace Hopper',
    });
    const model = buildWorkbenchFindings(
      makeQueues({
        reviewItems: makeReviewItems(low, high),
        assignmentTotal: 2,
        mergeSuggestions: [makeMerge()],
        mergeTotal: 1,
        nameSuggestions: [makeName()],
        nameTotal: 1,
        topUnlabeledClusters: [makeCluster()],
      }),
      makeState(),
    );

    expect(model.nextAction).toEqual({
      kind: NEXT_ACTION_KIND.ASSIGNMENT,
      suggestionId: 'sugg-high',
      clusterId: 'c-high',
      label: 'Grace Hopper',
    });
  });

  it('falls back to merge review when no assignment suggestions remain', () => {
    const model = buildWorkbenchFindings(
      makeQueues({
        mergeSuggestions: [makeMerge({ id: 'merge-7' })],
        mergeTotal: 1,
        nameSuggestions: [makeName()],
        nameTotal: 1,
        topUnlabeledClusters: [makeCluster()],
      }),
      makeState(),
    );

    expect(model.nextAction).toEqual({ kind: NEXT_ACTION_KIND.MERGE, suggestionId: 'merge-7' });
  });

  it('falls back to name suggestion when assignment and merge queues are empty', () => {
    const model = buildWorkbenchFindings(
      makeQueues({
        nameSuggestions: [makeName({ id: 'name-9', cluster_id: 'cluster-9' })],
        nameTotal: 1,
        topUnlabeledClusters: [makeCluster()],
      }),
      makeState(),
    );

    expect(model.nextAction).toEqual({
      kind: NEXT_ACTION_KIND.NAME,
      suggestionId: 'name-9',
      clusterId: 'cluster-9',
    });
  });

  it('targets the unlabeled cluster with the highest identity_count last', () => {
    const model = buildWorkbenchFindings(
      makeQueues({
        topUnlabeledClusters: [
          makeCluster({ id: 'small', identity_count: 2 }),
          makeCluster({ id: 'large', identity_count: 9 }),
        ],
      }),
      makeState(),
    );

    expect(model.nextAction).toEqual({ kind: NEXT_ACTION_KIND.CLUSTER, clusterId: 'large' });
  });

  it('returns a disabled empty action when no findings exist', () => {
    const model = buildWorkbenchFindings(makeQueues(), makeState());

    expect(model.nextAction).toEqual({ kind: NEXT_ACTION_KIND.NONE, reason: NONE_REASON.EMPTY });
    expect(model.hasFindings).toBe(false);
    expect(model.counts.total).toBe(0);
  });

  it('reports loading state while initial queue data is pending', () => {
    const model = buildWorkbenchFindings(makeQueues(), makeState({ isLoading: true }));

    expect(model.isLoading).toBe(true);
    expect(model.nextAction).toEqual({ kind: NEXT_ACTION_KIND.NONE, reason: NONE_REASON.LOADING });
  });

  it('reports error state when the primary queues fail', () => {
    const model = buildWorkbenchFindings(makeQueues(), makeState({ isError: true }));

    expect(model.isError).toBe(true);
    expect(model.nextAction).toEqual({ kind: NEXT_ACTION_KIND.NONE, reason: NONE_REASON.ERROR });
  });

  // UI-03: empty primary queues + top-unlabeled 500 is ERROR, not EMPTY.
  it('UI-03: top-unlabeled error with empty queues is isError / isTopUnlabeledError, not empty', () => {
    const model = buildWorkbenchFindings(makeQueues(), makeState({ isTopUnlabeledError: true }));

    expect(model.isTopUnlabeledError).toBe(true);
    expect(model.isError).toBe(true);
    expect(model.hasFindings).toBe(false);
    expect(model.nextAction).toEqual({ kind: NEXT_ACTION_KIND.NONE, reason: NONE_REASON.ERROR });
  });

  // UI-06: partial findings keep loading; unlabeled outage is flagged separately.
  it('UI-06: top-unlabeled error with other findings keeps hasFindings and flags isTopUnlabeledError', () => {
    const model = buildWorkbenchFindings(
      makeQueues({
        reviewItems: makeReviewItems(makeSuggestion()),
        assignmentTotal: 1,
      }),
      makeState({ isTopUnlabeledError: true }),
    );

    expect(model.isTopUnlabeledError).toBe(true);
    expect(model.isError).toBe(false);
    expect(model.hasFindings).toBe(true);
    expect(model.counts.unlabeledClusters).toBe(0);
  });

  it('reports unavailable state when the suggestion source is unavailable', () => {
    const model = buildWorkbenchFindings(
      makeQueues(),
      makeState({
        assignmentDataSource: DATA_SOURCE.UNAVAILABLE,
        topUnlabeledDataSource: DATA_SOURCE.UNAVAILABLE,
      }),
    );

    expect(model.isUnavailable).toBe(true);
    expect(model.nextAction).toEqual({ kind: NEXT_ACTION_KIND.NONE, reason: NONE_REASON.UNAVAILABLE });
  });

  // REV-A-03: name (and merge) outages must not hide the panel — only assignment + top-unlabeled
  // are canonical availability signals (partial summary is preferred over empty unavailable UI).
  it('does not mark unavailable when only the name data source is unavailable', () => {
    const model = buildWorkbenchFindings(
      makeQueues({
        topUnlabeledClusters: [makeCluster({ id: 'still-visible' })],
        topUnlabeledTotal: 1,
      }),
      makeState({ nameDataSource: DATA_SOURCE.UNAVAILABLE }),
    );

    expect(model.isUnavailable).toBe(false);
    expect(model.hasFindings).toBe(true);
    expect(model.nextAction).toEqual({ kind: NEXT_ACTION_KIND.CLUSTER, clusterId: 'still-visible' });
  });

  it('marks findings read-only under backend-proxy projection while keeping the next action visible', () => {
    const model = buildWorkbenchFindings(
      makeQueues({
        topUnlabeledClusters: [makeCluster({ id: 'proxy-cluster', identity_count: 4 })],
      }),
      makeState({ topUnlabeledDataSource: DATA_SOURCE.BACKEND_PROXY }),
    );

    expect(model.isReadOnly).toBe(true);
    expect(model.nextAction).toEqual({ kind: NEXT_ACTION_KIND.CLUSTER, clusterId: 'proxy-cluster' });
  });

  it('collects representative previews in priority order and drops entries without imagery', () => {
    const model = buildWorkbenchFindings(
      makeQueues({
        reviewItems: makeReviewItems(
          makeSuggestion({ identity_thumb_url: 'http://example.test/assign-thumb.jpg' }),
        ),
        assignmentTotal: 1,
        mergeSuggestions: [makeMerge({ cluster_a_representative_thumb_url: 'http://example.test/merge-thumb.jpg' })],
        mergeTotal: 1,
        nameSuggestions: [makeName()],
        nameTotal: 1,
        topUnlabeledClusters: [
          makeCluster({
            id: 'with-face',
            identity_count: 6,
            representatives: [
              { id: 'rep-1', media_id: 11, thumb_url: 'http://example.test/cluster-thumb.jpg', is_pinned: false },
            ],
          }),
          makeCluster({ id: 'no-face', identity_count: 2, representatives: [] }),
        ],
      }),
      makeState(),
    );

    expect(model.previews.map((preview) => preview.key)).toEqual([
      'assignment-sugg-1',
      'merge-merge-1',
      'cluster-with-face',
    ]);
    expect(model.previews[0].thumbUrl).toBe('http://example.test/assign-thumb.jpg');
  });

  it('keeps a preview whose only imagery is an attachment URL and still drops rows with no imagery', () => {
    const assignmentOnly = 'http://example.test/assign-attachment.jpg';
    const clusterOnly = 'http://example.test/cluster-attachment.jpg';

    const assignmentModel = buildWorkbenchFindings(
      makeQueues({
        reviewItems: makeReviewItems(
          makeSuggestion({
            id: 'attach-only',
            identity_id: 'identity-attach',
            suggested_cluster_id: 'cluster-attach',
            identity_attachment_url: assignmentOnly,
          }),
        ),
        assignmentTotal: 1,
        nameSuggestions: [makeName()],
        nameTotal: 1,
      }),
      makeState(),
    );

    expect(assignmentModel.previews.map((preview) => preview.key)).toEqual(['assignment-attach-only']);
    expect(assignmentModel.previews[0].thumbUrl).toBeNull();
    expect(assignmentModel.previews[0].mediaUrl).toBeNull();
    expect(assignmentModel.previews[0].attachmentUrl).toBe(assignmentOnly);

    const clusterModel = buildWorkbenchFindings(
      makeQueues({
        topUnlabeledClusters: [
          makeCluster({
            id: 'attach-only',
            identity_count: 4,
            representatives: [
              {
                id: 'rep-attach',
                media_id: 12,
                thumb_url: null,
                media_url: null,
                attachment_url: clusterOnly,
                is_pinned: false,
              },
            ],
          }),
          makeCluster({
            id: 'no-imagery',
            identity_count: 3,
            representatives: [{ id: 'rep-empty', media_id: 13, thumb_url: null, media_url: null, is_pinned: false }],
          }),
        ],
      }),
      makeState(),
    );

    expect(clusterModel.previews.map((preview) => preview.key)).toEqual(['cluster-attach-only']);
    expect(clusterModel.previews[0].thumbUrl).toBeNull();
    expect(clusterModel.previews[0].mediaUrl).toBeNull();
    expect(clusterModel.previews[0].attachmentUrl).toBe(clusterOnly);
  });

  const FACE_BBOX = { x: 12, y: 24, width: 80, height: 96 };

  // HAI-01: every preview source must retain its bbox so the strip can crop to a face.
  it('threads bbox onto previews from assignment, merge, name, and cluster sources', () => {
    const model = buildWorkbenchFindings(
      makeQueues({
        reviewItems: makeReviewItems(
          makeSuggestion({
            id: 'assign-1',
            identity_media_url: 'http://example.test/assign-media.jpg',
            identity_bbox: FACE_BBOX,
          }),
        ),
        assignmentTotal: 1,
        mergeSuggestions: [
          makeMerge({
            id: 'merge-1',
            cluster_a_representative_media_url: 'http://example.test/merge-media.jpg',
            cluster_a_representative_bbox: FACE_BBOX,
          }),
        ],
        mergeTotal: 1,
        nameSuggestions: [
          makeName({
            id: 'name-1',
            representatives: [
              {
                id: 'name-rep',
                media_id: 21,
                media_url: 'http://example.test/name-media.jpg',
                bbox: FACE_BBOX,
                is_pinned: false,
              },
            ],
          }),
        ],
        nameTotal: 1,
        topUnlabeledClusters: [
          makeCluster({
            id: 'cluster-1',
            representatives: [
              {
                id: 'cluster-rep',
                media_id: 31,
                media_url: 'http://example.test/cluster-media.jpg',
                bbox: FACE_BBOX,
                is_pinned: false,
              },
            ],
          }),
        ],
      }),
      makeState(),
    );

    expect(model.previews).toHaveLength(4);
    expect(model.previews.map((preview) => preview.key)).toEqual([
      'assignment-assign-1',
      'merge-merge-1',
      'name-name-1',
      'cluster-cluster-1',
    ]);
    for (const preview of model.previews) {
      expect(preview.bbox).toEqual(FACE_BBOX);
      expect(preview.mediaUrl).toBeTruthy();
    }
  });

  it('preserves honest absence when a source carries no bbox', () => {
    const model = buildWorkbenchFindings(
      makeQueues({
        reviewItems: makeReviewItems(
          makeSuggestion({ identity_thumb_url: 'http://example.test/assign-thumb.jpg' }),
        ),
        assignmentTotal: 1,
      }),
      makeState(),
    );

    expect(model.previews).toHaveLength(1);
    expect(model.previews[0].bbox).toBeNull();
  });

  // HAI-17: duplicate captures must not consume two PREVIEW_LIMIT slots.
  // Fixture: first PREVIEW_LIMIT (=6) rows collapse to one capture; a distinct
  // capture appears only after that window — proves dedupe-before-slice, not
  // slice-then-dedupe.
  it('dedupes previews that resolve to the same capture before applying the preview limit', () => {
    const sharedMedia = 'http://example.test/same-capture.jpg';
    const sharedBbox = { x: 5, y: 6, width: 40, height: 50 };
    const duplicateAssignments = Array.from({ length: 6 }, (_, index) =>
      makeSuggestion({
        id: `assign-dup-${index}`,
        identity_id: `identity-dup-${index}`,
        // Distinct cluster ids so buildSuggestionReviewItems keeps six singles
        // (same cluster would collapse into one group before collectPreviews).
        suggested_cluster_id: `cluster-dup-${index}`,
        cluster_label: `Dup Label ${index}`,
        identity_media_url: sharedMedia,
        identity_bbox: sharedBbox,
      }),
    );
    const model = buildWorkbenchFindings(
      makeQueues({
        reviewItems: makeReviewItems(...duplicateAssignments),
        assignmentTotal: 6,
        topUnlabeledClusters: [
          makeCluster({
            id: 'cluster-late',
            identity_count: 2,
            representatives: [
              {
                id: 'rep-late',
                media_id: 99,
                media_url: 'http://example.test/late-distinct-capture.jpg',
                bbox: { x: 1, y: 2, width: 10, height: 10 },
                is_pinned: false,
              },
            ],
          }),
        ],
      }),
      makeState(),
    );

    expect(model.previews.map((preview) => preview.key)).toEqual([
      'assignment-assign-dup-0',
      'cluster-cluster-late',
    ]);
    expect(model.previews.some((preview) => preview.key === 'cluster-cluster-late')).toBe(true);
    expect(model.previews).toHaveLength(2);
  });

  // FIX-1 / BR-12: no upgrade pre-pass — early null-bbox keeps its slot uncropped.
  it('keeps an early null-bbox photo when its boxed twin is past the preview cap', () => {
    const photoX = 'http://example.test/photo-x.jpg';
    const bboxX = { x: 5, y: 6, width: 40, height: 50 };
    const earlyNull = makeSuggestion({
      id: 'assign-x-null',
      identity_id: 'identity-x',
      suggested_cluster_id: 'cluster-x',
      cluster_label: 'Photo X',
      identity_media_url: photoX,
      identity_thumb_url: 'http://example.test/x-thumb.jpg',
      identity_bbox: null,
    });
    // Eight distinct fillers push the boxed twin to overall index 9 (past PREVIEW_LIMIT).
    const fillers = Array.from({ length: 8 }, (_, index) =>
      makeSuggestion({
        id: `assign-filler-${index}`,
        identity_id: `identity-filler-${index}`,
        suggested_cluster_id: `cluster-filler-${index}`,
        cluster_label: `Filler ${index}`,
        identity_media_url: `http://example.test/filler-${index}.jpg`,
        identity_bbox: { x: index, y: index, width: 20, height: 20 },
      }),
    );
    const model = buildWorkbenchFindings(
      makeQueues({
        reviewItems: makeReviewItems(earlyNull, ...fillers),
        assignmentTotal: 9,
        mergeSuggestions: [
          makeMerge({
            id: 'merge-x-boxed',
            cluster_a_representative_media_url: photoX,
            cluster_a_representative_bbox: bboxX,
          }),
        ],
        mergeTotal: 1,
      }),
      makeState(),
    );

    const photoXPreview = model.previews.find((preview) => preview.mediaUrl === photoX);
    expect(photoXPreview).toBeDefined();
    expect(photoXPreview?.key).toBe('assignment-assign-x-null');
    // Anti-merge: must not borrow the later boxed twin's crop (HAI-01).
    expect(photoXPreview?.bbox).toBeNull();
    expect(model.previews).toHaveLength(6);
  });

  // FIX-1 / HAI-01: same mediaUrl + different labels must not copy bbox onto the early row.
  it('does not copy a later croppable bbox onto an earlier null-bbox row for the same mediaUrl', () => {
    const sharedMedia = 'http://example.test/group-shot.jpg';
    const bboxB = { x: 200, y: 10, width: 40, height: 50 };
    const model = buildWorkbenchFindings(
      makeQueues({
        reviewItems: makeReviewItems(
          makeSuggestion({
            id: 'person-a',
            cluster_label: 'Person A',
            identity_media_url: sharedMedia,
            identity_thumb_url: 'http://example.test/person-a-thumb.jpg',
            identity_bbox: null,
          }),
        ),
        assignmentTotal: 1,
        mergeSuggestions: [
          makeMerge({
            id: 'person-b',
            cluster_a_label: 'Person B',
            cluster_a_representative_media_url: sharedMedia,
            cluster_a_representative_bbox: bboxB,
          }),
        ],
        mergeTotal: 1,
      }),
      makeState(),
    );

    const personA = model.previews.find((preview) => preview.key === 'assignment-person-a');
    expect(personA).toBeDefined();
    expect(personA?.label).toBe('Person A');
    expect(personA?.bbox).toBeNull();
  });

  // FIX-3: PHP {0,0,0,0} sentinel and null are the same non-croppable capture.
  it('collapses null-bbox and zero-extent sentinel bbox on the same mediaUrl to one preview', () => {
    const sharedMedia = 'http://example.test/same-photo.jpg';
    const model = buildWorkbenchFindings(
      makeQueues({
        reviewItems: makeReviewItems(
          makeSuggestion({
            id: 'null-bbox',
            identity_media_url: sharedMedia,
            identity_thumb_url: 'http://example.test/null-thumb.jpg',
            identity_bbox: null,
          }),
          makeSuggestion({
            id: 'zero-bbox',
            identity_id: 'identity-zero',
            suggested_cluster_id: 'cluster-zero',
            cluster_label: 'Zero Bbox',
            identity_media_url: sharedMedia,
            identity_thumb_url: 'http://example.test/zero-thumb.jpg',
            identity_bbox: { x: 0, y: 0, width: 0, height: 0 },
          }),
        ),
        assignmentTotal: 2,
      }),
      makeState(),
    );

    expect(model.previews).toHaveLength(1);
    expect(model.previews[0].key).toBe('assignment-null-bbox');
    expect(model.previews[0].bbox).toBeNull();
  });

  // FIX-A / diversity-first: duplicate must not steal a slot from a distinct photograph.
  it('gives the seventh distinct photograph a slot instead of an early same-photo duplicate', () => {
    const photoA = 'http://example.test/photo-a.jpg';
    const rows = [
      makeSuggestion({
        id: 'assign-a',
        identity_id: 'identity-a',
        suggested_cluster_id: 'cluster-a',
        cluster_label: 'A',
        identity_media_url: photoA,
        identity_bbox: { x: 1, y: 1, width: 10, height: 10 },
      }),
      makeSuggestion({
        id: 'assign-a-dup',
        identity_id: 'identity-a-dup',
        suggested_cluster_id: 'cluster-a-dup',
        cluster_label: 'A dup',
        // Distinct bbox so exact-capture key differs — diversity must still prefer photos.
        identity_media_url: photoA,
        identity_bbox: { x: 50, y: 50, width: 10, height: 10 },
      }),
      ...['b', 'c', 'd', 'e', 'f'].map((letter, index) =>
        makeSuggestion({
          id: `assign-${letter}`,
          identity_id: `identity-${letter}`,
          suggested_cluster_id: `cluster-${letter}`,
          cluster_label: letter.toUpperCase(),
          identity_media_url: `http://example.test/photo-${letter}.jpg`,
          identity_bbox: { x: index + 2, y: index + 2, width: 10, height: 10 },
        }),
      ),
    ];
    const model = buildWorkbenchFindings(
      makeQueues({
        reviewItems: makeReviewItems(...rows),
        assignmentTotal: 7,
      }),
      makeState(),
    );

    expect(model.previews).toHaveLength(6);
    expect(model.previews.map((preview) => preview.mediaUrl)).toEqual([
      photoA,
      'http://example.test/photo-b.jpg',
      'http://example.test/photo-c.jpg',
      'http://example.test/photo-d.jpg',
      'http://example.test/photo-e.jpg',
      'http://example.test/photo-f.jpg',
    ]);
    expect(model.previews.some((preview) => preview.key === 'assignment-assign-a-dup')).toBe(false);
  });

  // FIX-A / BR-15: dedicated face-thumb + boxed twin must not crowd out a distinct seventh.
  it('prefers a distinct seventh capture over a same-photo face-thumb + boxed pair', () => {
    const sharedMedia = 'http://example.test/shared-photo.jpg';
    const faceThumb =
      'http://example.test/wp-content/uploads/recognition/face-thumbs/shared.jpg';
    const rows = [
      makeSuggestion({
        id: 'assign-ft',
        identity_id: 'identity-ft',
        suggested_cluster_id: 'cluster-ft',
        cluster_label: 'FT',
        identity_thumb_url: faceThumb,
        identity_media_url: sharedMedia,
        identity_bbox: null,
      }),
      makeSuggestion({
        id: 'assign-boxed',
        identity_id: 'identity-boxed',
        suggested_cluster_id: 'cluster-boxed',
        cluster_label: 'Boxed',
        identity_media_url: sharedMedia,
        identity_bbox: { x: 5, y: 6, width: 40, height: 50 },
      }),
      ...['b', 'c', 'd', 'e', 'f'].map((letter, index) =>
        makeSuggestion({
          id: `assign-${letter}`,
          identity_id: `identity-${letter}`,
          suggested_cluster_id: `cluster-${letter}`,
          cluster_label: letter.toUpperCase(),
          identity_media_url: `http://example.test/photo-${letter}.jpg`,
          identity_bbox: { x: index + 2, y: index + 2, width: 10, height: 10 },
        }),
      ),
    ];
    const model = buildWorkbenchFindings(
      makeQueues({
        reviewItems: makeReviewItems(...rows),
        assignmentTotal: 7,
      }),
      makeState(),
    );

    expect(model.previews).toHaveLength(6);
    expect(model.previews.filter((preview) => preview.mediaUrl === sharedMedia)).toHaveLength(1);
    expect(model.previews.some((preview) => preview.mediaUrl === 'http://example.test/photo-f.jpg')).toBe(
      true,
    );
    expect(model.previews.some((preview) => preview.key === 'assignment-assign-boxed')).toBe(false);
  });

  // FIX-6 / FIX-B: distinct non-null bboxes stay distinct; same-key sibling proves dedupe landed.
  it('keeps two distinct non-null bboxes on the same mediaUrl as separate previews', () => {
    const sharedMedia = 'http://example.test/group-shot.jpg';
    const model = buildWorkbenchFindings(
      makeQueues({
        reviewItems: makeReviewItems(
          makeSuggestion({
            id: 'face-a',
            identity_media_url: sharedMedia,
            identity_bbox: { x: 10, y: 10, width: 40, height: 50 },
          }),
          makeSuggestion({
            id: 'face-a-dup',
            identity_id: 'identity-a-dup',
            suggested_cluster_id: 'cluster-a-dup',
            cluster_label: 'Face A dup',
            identity_media_url: sharedMedia,
            identity_bbox: { x: 10, y: 10, width: 40, height: 50 },
          }),
        ),
        assignmentTotal: 2,
        mergeSuggestions: [
          makeMerge({
            id: 'face-b',
            cluster_a_representative_media_url: sharedMedia,
            cluster_a_representative_bbox: { x: 200, y: 10, width: 40, height: 50 },
          }),
        ],
        mergeTotal: 1,
      }),
      makeState(),
    );

    expect(model.previews.map((preview) => preview.key)).toEqual(['assignment-face-a', 'merge-face-b']);
    expect(model.previews).toHaveLength(2);
  });

  // FIX-6 / FIX-B: dedicated face-thumbs key on thumb URL; same-key sibling proves dedupe landed.
  it('keeps two dedicated face-thumb URLs distinct even when mediaUrl matches and bbox is null', () => {
    const sharedMedia = 'http://example.test/group-shot.jpg';
    const thumbA =
      'http://example.test/wp-content/uploads/recognition/face-thumbs/a.jpg';
    const thumbB =
      'http://example.test/wp-content/uploads/recognition/face-thumbs/b.jpg';
    const model = buildWorkbenchFindings(
      makeQueues({
        reviewItems: makeReviewItems(
          makeSuggestion({
            id: 'face-thumb-a',
            identity_thumb_url: thumbA,
            identity_media_url: sharedMedia,
          }),
          makeSuggestion({
            id: 'face-thumb-a-dup',
            identity_id: 'identity-ft-a-dup',
            suggested_cluster_id: 'cluster-ft-a-dup',
            cluster_label: 'FT A dup',
            identity_thumb_url: thumbA,
            identity_media_url: sharedMedia,
          }),
        ),
        assignmentTotal: 2,
        mergeSuggestions: [
          makeMerge({
            id: 'face-thumb-b',
            cluster_a_representative_thumb_url: thumbB,
            cluster_a_representative_media_url: sharedMedia,
          }),
        ],
        mergeTotal: 1,
      }),
      makeState(),
    );

    expect(model.previews.map((preview) => preview.key)).toEqual([
      'assignment-face-thumb-a',
      'merge-face-thumb-b',
    ]);
    expect(model.previews).toHaveLength(2);
  });

  // FIX-2 / A11Y-02 / HAI-01: cluster source never reads cluster.label (top-unlabeled contract).
  it('marks labelIsSuggested from suggested fields and clears it for confirmed labels', () => {
    const model = buildWorkbenchFindings(
      makeQueues({
        // Confirmed assignment via the normal review-item builder.
        reviewItems: [
          ...makeReviewItems(
            makeSuggestion({
              id: 'assign-confirmed',
              cluster_label: 'Confirmed Name',
              identity_thumb_url: 'http://example.test/assign.jpg',
            }),
          ),
          // Suggested-only assignment: bypass eligibility filter so collectPreviews
          // can be pinned when label falls through to enrichment.suggestedLabel.
          {
            type: 'single',
            score: 0.5,
            suggestion: {
              suggestionId: 'assign-suggested',
              identityId: 'identity-sug',
              clusterId: 'cluster-sug',
              label: null,
              similarity: 0.5,
              enrichment: {
                suggestedLabel: 'Maybe Name',
                identityThumbUrl: 'http://example.test/assign-sug.jpg',
              },
            },
          },
        ],
        assignmentTotal: 2,
        mergeSuggestions: [
          makeMerge({
            id: 'merge-1',
            cluster_a_label: 'Merge Label',
            cluster_a_representative_thumb_url: 'http://example.test/merge.jpg',
          }),
        ],
        mergeTotal: 1,
        nameSuggestions: [
          makeName({
            id: 'name-1',
            suggested_name: 'Suggested Person',
            representatives: [
              {
                id: 'name-rep',
                media_id: 21,
                thumb_url: 'http://example.test/name.jpg',
                is_pinned: false,
              },
            ],
          }),
        ],
        nameTotal: 1,
        topUnlabeledClusters: [
          makeCluster({
            id: 'cluster-placeholder',
            label: 'cluster-7',
            is_labeled: false,
            is_auto_label: true,
            user_confirmed: false,
            suggested_label: null,
            representatives: [
              {
                id: 'rep-c',
                media_id: 31,
                thumb_url: 'http://example.test/cluster-c.jpg',
                is_pinned: false,
              },
            ],
          }),
          makeCluster({
            id: 'cluster-suggested',
            label: null,
            suggested_label: 'Cluster Maybe',
            identity_count: 1,
            representatives: [
              {
                id: 'rep-s',
                media_id: 32,
                thumb_url: 'http://example.test/cluster-s.jpg',
                is_pinned: false,
              },
            ],
          }),
        ],
      }),
      makeState(),
    );

    const byKey = Object.fromEntries(model.previews.map((preview) => [preview.key, preview]));
    expect(byKey['assignment-assign-confirmed']).toMatchObject({
      label: 'Confirmed Name',
      labelIsSuggested: false,
    });
    expect(byKey['assignment-assign-suggested']).toMatchObject({
      label: 'Maybe Name',
      labelIsSuggested: true,
    });
    expect(byKey['merge-merge-1']).toMatchObject({
      label: 'Merge Label',
      labelIsSuggested: false,
    });
    expect(byKey['name-name-1']).toMatchObject({
      label: 'Suggested Person',
      labelIsSuggested: true,
    });
    expect(byKey['cluster-cluster-placeholder']).toMatchObject({
      label: null,
      labelIsSuggested: false,
    });
    expect(byKey['cluster-cluster-suggested']).toMatchObject({
      label: 'Cluster Maybe',
      labelIsSuggested: true,
    });
  });

  // FIX-1 / A11Y-02 / HAI-01: merge cluster_a_label is raw — null placeholders via isHumanLabeledTarget.
  it('nulls merge cluster_a_label auto-placeholders including whitespace-padded prefix', () => {
    const model = buildWorkbenchFindings(
      makeQueues({
        mergeSuggestions: [
          makeMerge({
            id: 'merge-auto',
            cluster_a_label: 'cluster-7',
            cluster_a_representative_thumb_url: 'http://example.test/merge-auto.jpg',
          }),
          makeMerge({
            id: 'merge-padded',
            cluster_a_label: '  cluster-7',
            cluster_a_representative_thumb_url: 'http://example.test/merge-padded.jpg',
          }),
        ],
        mergeTotal: 2,
      }),
      makeState(),
    );

    const byKey = Object.fromEntries(model.previews.map((preview) => [preview.key, preview]));
    expect(byKey['merge-merge-auto']).toMatchObject({
      label: null,
      labelIsSuggested: false,
    });
    // Discriminates isHumanLabeledTarget (trims) from isMeaningfulMergeLabel (no trim).
    expect(byKey['merge-merge-padded']).toMatchObject({
      label: null,
      labelIsSuggested: false,
    });
  });

  // BR-28: findings merge preview must null case/underscore auto-labels (same predicate).
  it('nulls merge cluster_a_label for Cluster- and cluster_ auto-labels', () => {
    const model = buildWorkbenchFindings(
      makeQueues({
        mergeSuggestions: [
          makeMerge({
            id: 'merge-case',
            cluster_a_label: 'Cluster-abcdef12',
            cluster_a_representative_thumb_url: 'http://example.test/merge-case.jpg',
          }),
          makeMerge({
            id: 'merge-underscore',
            cluster_a_label: 'cluster_abcdef12',
            cluster_a_representative_thumb_url: 'http://example.test/merge-underscore.jpg',
          }),
        ],
        mergeTotal: 2,
      }),
      makeState(),
    );

    const byKey = Object.fromEntries(model.previews.map((preview) => [preview.key, preview]));
    expect(byKey['merge-merge-case']).toMatchObject({
      label: null,
      labelIsSuggested: false,
    });
    expect(byKey['merge-merge-underscore']).toMatchObject({
      label: null,
      labelIsSuggested: false,
    });
  });

  // BR-34: operator-plausible human Cluster* labels must survive the findings merge path.
  it('keeps merge cluster_a_label for human CLUSTER_HQ (BR-34)', () => {
    const model = buildWorkbenchFindings(
      makeQueues({
        mergeSuggestions: [
          makeMerge({
            id: 'merge-hq',
            cluster_a_label: 'CLUSTER_HQ',
            cluster_a_representative_thumb_url: 'http://example.test/merge-hq.jpg',
          }),
        ],
        mergeTotal: 1,
      }),
      makeState(),
    );

    expect(model.previews.find((preview) => preview.key === 'merge-merge-hq')).toMatchObject({
      label: 'CLUSTER_HQ',
      labelIsSuggested: false,
    });
  });

  // FIX-2 / BR-26 / A11Y-02 / HAI-01: assignments provenance — upstream isHumanLabeledTarget
  // is the single gate; findings layer must not surface auto-label rows that slip past it.
  it('produces no assignment preview for auto cluster_* labels (upstream gate provenance)', () => {
    const model = buildWorkbenchFindings(
      makeQueues({
        reviewItems: makeReviewItems(
          makeSuggestion({
            id: 'assign-auto',
            cluster_label: 'cluster-7',
            identity_thumb_url: 'http://example.test/assign-auto.jpg',
            identity_media_url: 'http://example.test/assign-auto-media.jpg',
            identity_bbox: { x: 12, y: 24, width: 80, height: 96 },
          }),
        ),
        assignmentTotal: 1,
      }),
      makeState(),
    );

    expect(model.previews.filter((preview) => preview.key.startsWith('assignment-'))).toHaveLength(0);
    // Findings-layer stand-in for rendered alt: no preview label may carry the auto-id.
    expect(model.previews.every((preview) => !String(preview.label ?? '').includes('cluster-7'))).toBe(
      true,
    );
  });

  it('ignores cluster.label placeholder and only surfaces suggested_label for cluster previews', () => {
    const model = buildWorkbenchFindings(
      makeQueues({
        topUnlabeledClusters: [
          makeCluster({
            id: 'cluster-placeholder',
            label: 'cluster-7',
            is_labeled: false,
            is_auto_label: true,
            user_confirmed: false,
            suggested_label: null,
            identity_count: 3,
            representatives: [
              {
                id: 'rep-ph',
                media_id: 33,
                thumb_url: 'http://example.test/cluster-ph.jpg',
                is_pinned: false,
              },
            ],
          }),
          makeCluster({
            id: 'cluster-suggested',
            label: 'cluster-9',
            is_labeled: false,
            is_auto_label: true,
            user_confirmed: false,
            suggested_label: 'Ada Lovelace',
            identity_count: 2,
            representatives: [
              {
                id: 'rep-sug',
                media_id: 34,
                thumb_url: 'http://example.test/cluster-sug.jpg',
                is_pinned: false,
              },
            ],
          }),
        ],
      }),
      makeState(),
    );

    const byKey = Object.fromEntries(model.previews.map((preview) => [preview.key, preview]));
    expect(byKey['cluster-cluster-placeholder']).toMatchObject({
      label: null,
      labelIsSuggested: false,
    });
    expect(byKey['cluster-cluster-suggested']).toMatchObject({
      label: 'Ada Lovelace',
      labelIsSuggested: true,
    });
  });
});

describe('useWorkbenchFindings', () => {
  let queryClient: QueryClient | undefined;

  beforeEach(() => {
    window.AltContextAdmin = {
      nonce: 'test-nonce',
      ajaxUrl: '/wp-admin/admin-ajax.php',
      endpoints: {
        recognitionSuggestions: 'http://example.test/recognition/suggestions',
        recognitionMergeSuggestions: 'http://example.test/recognition/suggestions/merge',
        recognitionNameSuggestions: 'http://example.test/recognition/suggestions/name',
        recognitionBulkAcceptSuggestions: 'http://example.test/recognition/suggestions/bulk-accept',
        recognitionClusters: 'http://example.test/recognition/clusters',
      },
      tenant_id: 'test-tenant-id',
    };
    resetConfigCache();
  });

  afterEach(() => {
    void queryClient?.cancelQueries();
    queryClient?.clear();
    cleanup();
    vi.clearAllMocks();
  });

  it('derives the view model from live suggestion review queries', async () => {
    vi.mocked(fetchPendingSuggestions).mockResolvedValue({
      suggestions: [makeSuggestion({ id: 'live-sugg', suggested_cluster_id: 'live-cluster' })],
      limit: 25,
      offset: 0,
      data_source: DATA_SOURCE.LOCAL_PROJECTION,
    });
    vi.mocked(fetchPendingMergeSuggestions).mockResolvedValue({
      suggestions: [],
      limit: 10,
      offset: 0,
      data_source: DATA_SOURCE.LOCAL_PROJECTION,
    });
    vi.mocked(fetchPendingNameSuggestions).mockResolvedValue({
      suggestions: [],
      limit: 25,
      offset: 0,
      data_source: DATA_SOURCE.LOCAL_PROJECTION,
    });
    vi.mocked(fetchTopUnlabeledClusters).mockResolvedValue({
      clusters: [makeCluster()],
      limit: 20,
      total: 1,
      truncated: false,
      singleton_count: 0,
      has_clusters: true,
      data_source: DATA_SOURCE.LOCAL_PROJECTION,
    });

    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    queryClient = client;
    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );

    const { result } = renderHook(() => useWorkbenchFindings(), { wrapper });

    expect(result.current.isLoading).toBe(true);

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    expect(result.current.counts).toEqual({
      assignments: 1,
      merges: 0,
      names: 0,
      unlabeledClusters: 1,
      total: 2,
    });
    expect(result.current.nextAction).toEqual({
      kind: NEXT_ACTION_KIND.ASSIGNMENT,
      suggestionId: 'live-sugg',
      clusterId: 'live-cluster',
      label: 'Default Label',
    });
    expect(result.current.isReadOnly).toBe(false);
  });

  // REV-A-01 (hook path): total-backed count must flow from useSuggestionReviewQueries
  // through useWorkbenchFindings — page length alone under-reports the backlog.
  it('uses topUnlabeledQuery total for unlabeledClusters when total exceeds the fetched page', async () => {
    vi.mocked(fetchPendingSuggestions).mockResolvedValue({
      suggestions: [],
      limit: 25,
      offset: 0,
      data_source: DATA_SOURCE.LOCAL_PROJECTION,
    });
    vi.mocked(fetchPendingMergeSuggestions).mockResolvedValue({
      suggestions: [],
      limit: 10,
      offset: 0,
      data_source: DATA_SOURCE.LOCAL_PROJECTION,
    });
    vi.mocked(fetchPendingNameSuggestions).mockResolvedValue({
      suggestions: [],
      limit: 25,
      offset: 0,
      data_source: DATA_SOURCE.LOCAL_PROJECTION,
    });
    // Fetched page is capped (1 item here); server total is higher.
    vi.mocked(fetchTopUnlabeledClusters).mockResolvedValue({
      clusters: [makeCluster({ id: 'page-head', identity_count: 8 })],
      limit: 20,
      total: 42,
      truncated: true,
      singleton_count: 0,
      has_clusters: true,
      data_source: DATA_SOURCE.LOCAL_PROJECTION,
    });

    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    queryClient = client;
    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );

    const { result } = renderHook(() => useWorkbenchFindings(), { wrapper });

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    // Would fail against old code that used topUnlabeledClusters.length (page size).
    expect(result.current.counts.unlabeledClusters).toBe(42);
    expect(result.current.counts.total).toBe(42);
    expect(result.current.topUnlabeledTruncated).toBe(true);
    expect(result.current.nextAction).toEqual({ kind: NEXT_ACTION_KIND.CLUSTER, clusterId: 'page-head' });
  });

  // UI-03 (hook path): top-unlabeled reject with empty primary queues surfaces
  // isTopUnlabeledError + isError so the panel cannot launder into empty.
  it('UI-03: top-unlabeled query rejection sets isTopUnlabeledError on the view model', async () => {
    vi.mocked(fetchPendingSuggestions).mockResolvedValue({
      suggestions: [],
      limit: 25,
      offset: 0,
      data_source: DATA_SOURCE.LOCAL_PROJECTION,
    });
    vi.mocked(fetchPendingMergeSuggestions).mockResolvedValue({
      suggestions: [],
      limit: 10,
      offset: 0,
      data_source: DATA_SOURCE.LOCAL_PROJECTION,
    });
    vi.mocked(fetchPendingNameSuggestions).mockResolvedValue({
      suggestions: [],
      limit: 25,
      offset: 0,
      data_source: DATA_SOURCE.LOCAL_PROJECTION,
    });
    vi.mocked(fetchTopUnlabeledClusters).mockRejectedValue(new Error('acx_projection_query_failed'));

    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    queryClient = client;
    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );

    const { result } = renderHook(() => useWorkbenchFindings(), { wrapper });

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    expect(result.current.isTopUnlabeledError).toBe(true);
    expect(result.current.isError).toBe(true);
    expect(result.current.hasFindings).toBe(false);
    expect(result.current.nextAction).toEqual({ kind: NEXT_ACTION_KIND.NONE, reason: NONE_REASON.ERROR });
  });

  // REV-A-03 (isError): Locks the !hasAnyData guard — BOTH primary queries
  // (assignment + merge) fail, so without the guard isError would flip true, but
  // top-unlabeled data still renders as a partial summary.
  it('degrades gracefully on partial query failure instead of surfacing an error', async () => {
    vi.mocked(fetchPendingSuggestions).mockRejectedValue(new Error('assignment endpoint down'));
    vi.mocked(fetchPendingMergeSuggestions).mockRejectedValue(new Error('merge endpoint down'));
    vi.mocked(fetchPendingNameSuggestions).mockResolvedValue({
      suggestions: [],
      limit: 25,
      offset: 0,
      data_source: DATA_SOURCE.LOCAL_PROJECTION,
    });
    vi.mocked(fetchTopUnlabeledClusters).mockResolvedValue({
      clusters: [makeCluster()],
      limit: 20,
      total: 1,
      truncated: false,
      singleton_count: 0,
      has_clusters: true,
      data_source: DATA_SOURCE.LOCAL_PROJECTION,
    });

    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    queryClient = client;
    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );

    const { result } = renderHook(() => useWorkbenchFindings(), { wrapper });

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    expect(result.current.isError).toBe(false);
    expect(result.current.hasFindings).toBe(true);
    expect(result.current.counts.unlabeledClusters).toBe(1);
    expect(result.current.nextAction).toEqual({ kind: NEXT_ACTION_KIND.CLUSTER, clusterId: 'top-1' });
  });

  // REV-A-02: useWorkbenchFindings must not wrap buildWorkbenchFindings in useMemo over
  // freshly-allocated query fallback arrays (that memo was a no-op). Rebuild is cheap;
  // the hook still returns a coherent view model every render.
  it('rebuilds a coherent view model each render without relying on unstable memo deps', async () => {
    vi.mocked(fetchPendingSuggestions).mockResolvedValue({
      suggestions: [makeSuggestion({ id: 'memo-sugg', suggested_cluster_id: 'memo-cluster' })],
      limit: 25,
      offset: 0,
      data_source: DATA_SOURCE.LOCAL_PROJECTION,
    });
    vi.mocked(fetchPendingMergeSuggestions).mockResolvedValue({
      suggestions: [],
      limit: 10,
      offset: 0,
      data_source: DATA_SOURCE.LOCAL_PROJECTION,
    });
    vi.mocked(fetchPendingNameSuggestions).mockResolvedValue({
      suggestions: [],
      limit: 25,
      offset: 0,
      data_source: DATA_SOURCE.LOCAL_PROJECTION,
    });
    vi.mocked(fetchTopUnlabeledClusters).mockResolvedValue({
      clusters: [makeCluster({ id: 'memo-cluster-top' })],
      limit: 20,
      total: 3,
      truncated: true,
      singleton_count: 0,
      has_clusters: true,
      data_source: DATA_SOURCE.LOCAL_PROJECTION,
    });

    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    queryClient = client;
    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );

    const { result, rerender } = renderHook(() => useWorkbenchFindings(), { wrapper });

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    rerender();
    const second = result.current;

    // REV-A-02 (no-op useMemo) is enforced by review, not by this test: a no-op
    // memo is behaviorally invisible, and pinning object identity would
    // spuriously fail if a correctly-stable memo were ever added. This test
    // only pins rerender consistency of the view model.
    expect(second.counts).toEqual({
      assignments: 1,
      merges: 0,
      names: 0,
      unlabeledClusters: 3,
      total: 4,
    });
    expect(second.nextAction).toEqual({
      kind: NEXT_ACTION_KIND.ASSIGNMENT,
      suggestionId: 'memo-sugg',
      clusterId: 'memo-cluster',
      label: 'Default Label',
    });
  });

  // Carry-over / TEST-15: panel tests mock useWorkbenchFindings, so
  // `const isAssignmentError = false` stays green there. This hook test fails
  // if that assignmentQuery.isError wiring is dropped.
  it('REV2-01 carry-over: wires isAssignmentError from assignmentQuery.isError', async () => {
    vi.mocked(fetchPendingSuggestions).mockRejectedValue(new Error('assignment endpoint down'));
    vi.mocked(fetchPendingMergeSuggestions).mockResolvedValue({
      suggestions: [],
      limit: 10,
      offset: 0,
      data_source: DATA_SOURCE.LOCAL_PROJECTION,
    });
    vi.mocked(fetchPendingNameSuggestions).mockResolvedValue({
      suggestions: [],
      limit: 25,
      offset: 0,
      data_source: DATA_SOURCE.LOCAL_PROJECTION,
    });
    vi.mocked(fetchTopUnlabeledClusters).mockResolvedValue({
      clusters: [],
      limit: 20,
      total: 0,
      truncated: false,
      singleton_count: 0,
      has_clusters: false,
      data_source: DATA_SOURCE.LOCAL_PROJECTION,
    });

    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    queryClient = client;
    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );

    const { result } = renderHook(() => useWorkbenchFindings(), { wrapper });

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    expect(result.current.isAssignmentError).toBe(true);
    expect(result.current.isError).toBe(false);
    expect(result.current.hasFindings).toBe(false);
  });
});
