/**
 * E21-5 Slice 1a — review queue driver unit tests.
 * Covers: order, KIND filter, group flattening, PR-54 index-under-removal.
 */

import { describe, expect, it } from 'vitest';

import type { PendingMergeSuggestion, PendingNameSuggestion, PendingSuggestion } from '../../../../api/recognition/types';
import type { TopUnlabeledCluster } from '../../../../api/recognition/types/cluster';
import {
  buildReviewQueue,
  clampQueueIndex,
  filterReviewQueue,
  NEXT_ACTION_CHIP_LABEL,
  NEXT_ACTION_KIND,
  nextQueueIndex,
  prevQueueIndex,
  removeAtQueueCursor,
  removeAtQueueIndex,
  REVIEW_QUEUE_FILTER,
  queueItemToNextAction,
} from '../reviewQueueDriver';
import { fromPendingRow, projectReviewQueue } from '../suggestionProjection';
import { buildSuggestionReviewItems } from '../suggestionReviewItems';
import { suggestionProjectionMatrix } from './suggestionProjection.fixtures';

const makeSuggestion = (overrides: Partial<PendingSuggestion> = {}): PendingSuggestion => ({
  id: 'sugg-1',
  identity_id: 'identity-1',
  suggested_cluster_id: 'cluster-1',
  representative_similarity: 0.8,
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
  representatives: [],
  ...overrides,
});

const sortClustersBySize = (clusters: TopUnlabeledCluster[]): TopUnlabeledCluster[] =>
  [...clusters].sort((a, b) => b.identity_count - a.identity_count);

describe('NEXT_ACTION_CHIP_LABEL (sr-007)', () => {
  it('maps ASSIGNMENT and MERGE to human chip copy only', () => {
    expect(NEXT_ACTION_CHIP_LABEL[NEXT_ACTION_KIND.ASSIGNMENT]).toBe('Close matches');
    expect(NEXT_ACTION_CHIP_LABEL[NEXT_ACTION_KIND.MERGE]).toBe('Possible duplicates');
    expect(Object.keys(NEXT_ACTION_CHIP_LABEL)).toEqual([
      NEXT_ACTION_KIND.ASSIGNMENT,
      NEXT_ACTION_KIND.MERGE,
    ]);
  });
});

describe('buildReviewQueue — order (default priority)', () => {
  it('preserves historical selectNextAction priority: assignment → merge → name → cluster', () => {
    const low = makeSuggestion({
      id: 'sugg-low',
      suggested_cluster_id: 'c-low',
      representative_similarity: 0.5,
      cluster_label: 'Low',
    });
    const high = makeSuggestion({
      id: 'sugg-high',
      suggested_cluster_id: 'c-high',
      representative_similarity: 0.95,
      cluster_label: 'Grace Hopper',
    });
    const queue = buildReviewQueue({
      reviewItems: makeReviewItems(low, high),
      mergeSuggestions: [makeMerge({ id: 'merge-7' })],
      nameSuggestions: [makeName({ id: 'name-9', cluster_id: 'cluster-9' })],
      sortedClusters: sortClustersBySize([
        makeCluster({ id: 'small', identity_count: 2 }),
        makeCluster({ id: 'large', identity_count: 9 }),
      ]),
    });

    expect(queue.map((item) => item.kind)).toEqual([
      NEXT_ACTION_KIND.ASSIGNMENT,
      NEXT_ACTION_KIND.ASSIGNMENT,
      NEXT_ACTION_KIND.MERGE,
      NEXT_ACTION_KIND.NAME,
      NEXT_ACTION_KIND.CLUSTER,
      NEXT_ACTION_KIND.CLUSTER,
    ]);
    // Head matches legacy selectNextAction: highest-score assignment.
    expect(queueItemToNextAction(queue[0])).toEqual({
      kind: NEXT_ACTION_KIND.ASSIGNMENT,
      suggestionId: 'sugg-high',
      clusterId: 'c-high',
      label: 'Grace Hopper',
    });
    expect(queue[2]).toEqual({ kind: NEXT_ACTION_KIND.MERGE, suggestionId: 'merge-7' });
    expect(queue[3]).toEqual({
      kind: NEXT_ACTION_KIND.NAME,
      suggestionId: 'name-9',
      clusterId: 'cluster-9',
    });
    expect(queue[4]).toEqual({ kind: NEXT_ACTION_KIND.CLUSTER, clusterId: 'large' });
    expect(queue[5]).toEqual({ kind: NEXT_ACTION_KIND.CLUSTER, clusterId: 'small' });
  });

  it('orders assignment review leg via UXP-3 projectReviewQueue similarity (matrix fixture)', () => {
    const { pendingRows, expectedReviewSuggestionIdsBySimilarity } =
      suggestionProjectionMatrix.multiSuggestionIdentity;
    // Assert review-leg expectations only — never identity-leg ones.
    const projected = projectReviewQueue(pendingRows);
    expect(projected.map((p) => p.suggestionId)).toEqual(expectedReviewSuggestionIdsBySimilarity);

    const reviewItems = buildSuggestionReviewItems(projected);
    const queue = buildReviewQueue({
      reviewItems,
      mergeSuggestions: [],
      nameSuggestions: [],
      sortedClusters: [],
    });

    expect(queue.map((item) => ('suggestionId' in item ? item.suggestionId : null))).toEqual(
      expectedReviewSuggestionIdsBySimilarity,
    );
  });

  it('orders tied similarities by createdAt desc on the review leg (matrix fixture)', () => {
    const { pendingRows, expectedReviewSuggestionIds } = suggestionProjectionMatrix.tiedSimilarities;
    const projected = projectReviewQueue(pendingRows);
    expect(projected.map((p) => p.suggestionId)).toEqual(expectedReviewSuggestionIds);

    const queue = buildReviewQueue({
      reviewItems: buildSuggestionReviewItems(projected),
      mergeSuggestions: [],
      nameSuggestions: [],
      sortedClusters: [],
    });

    expect(queue.map((item) => ('suggestionId' in item ? item.suggestionId : null))).toEqual(
      expectedReviewSuggestionIds,
    );
  });

  it('same-cluster runs stay contiguous (group packing over pure projection order)', () => {
    // a1 (0.9) and a2 (0.5) share cluster A; b1 (0.7) is cluster B.
    // Pure projection by score: [a1, b1, a2]. Group packing packs A as a run:
    // group score max(0.9, 0.5)=0.9 > b1 0.7 → queue [a1, a2, b1].
    const rows = [
      makeSuggestion({
        id: 'a1',
        identity_id: 'id-a1',
        suggested_cluster_id: 'cluster-a',
        cluster_label: 'Alice',
        representative_similarity: 0.9,
        created_at: '2026-01-01T00:00:00.000Z',
      }),
      makeSuggestion({
        id: 'a2',
        identity_id: 'id-a2',
        suggested_cluster_id: 'cluster-a',
        cluster_label: 'Alice',
        representative_similarity: 0.5,
        created_at: '2026-01-02T00:00:00.000Z',
      }),
      makeSuggestion({
        id: 'b1',
        identity_id: 'id-b1',
        suggested_cluster_id: 'cluster-b',
        cluster_label: 'Bob',
        representative_similarity: 0.7,
        created_at: '2026-01-03T00:00:00.000Z',
      }),
    ];

    const projected = projectReviewQueue(rows);
    expect(projected.map((p) => p.suggestionId)).toEqual(['a1', 'b1', 'a2']);

    const reviewItems = buildSuggestionReviewItems(projected);
    expect(reviewItems).toHaveLength(2);
    expect(reviewItems[0].type).toBe('group');
    expect(reviewItems[1].type).toBe('single');

    const queue = buildReviewQueue({
      reviewItems,
      mergeSuggestions: [],
      nameSuggestions: [],
      sortedClusters: [],
    });

    expect(queue.map((item) => ('suggestionId' in item ? item.suggestionId : null))).toEqual([
      'a1',
      'a2',
      'b1',
    ]);
    expect(queue[0]).toMatchObject({
      suggestionId: 'a1',
      clusterId: 'cluster-a',
      runSize: 2,
      runIndex: 0,
    });
    expect(queue[1]).toMatchObject({
      suggestionId: 'a2',
      clusterId: 'cluster-a',
      runSize: 2,
      runIndex: 1,
    });
    expect(queue[2]).toMatchObject({
      suggestionId: 'b1',
      clusterId: 'cluster-b',
      runSize: 1,
      runIndex: 0,
    });
  });
});

describe('buildReviewQueue — filter (KIND)', () => {
  const sources = {
    reviewItems: makeReviewItems(
      makeSuggestion({ id: 'a1', cluster_label: 'Alice', representative_similarity: 0.9 }),
    ),
    mergeSuggestions: [makeMerge({ id: 'm1' }), makeMerge({ id: 'm2' })],
    nameSuggestions: [makeName({ id: 'n1' })],
    sortedClusters: [makeCluster({ id: 'c1' })],
  };

  it('filters to assignment only ("Close matches" chip)', () => {
    const queue = buildReviewQueue(sources, REVIEW_QUEUE_FILTER.ASSIGNMENT);
    expect(queue).toHaveLength(1);
    expect(queue.every((item) => item.kind === NEXT_ACTION_KIND.ASSIGNMENT)).toBe(true);
    expect(queue[0]).toMatchObject({ suggestionId: 'a1' });
  });

  it('filters to merge only ("Possible duplicates" chip)', () => {
    const queue = buildReviewQueue(sources, REVIEW_QUEUE_FILTER.MERGE);
    expect(queue).toHaveLength(2);
    expect(queue.every((item) => item.kind === NEXT_ACTION_KIND.MERGE)).toBe(true);
    expect(queue.map((item) => ('suggestionId' in item ? item.suggestionId : null))).toEqual([
      'm1',
      'm2',
    ]);
  });

  it('returns full priority order when filter is all', () => {
    const queue = buildReviewQueue(sources, REVIEW_QUEUE_FILTER.ALL);
    expect(queue.map((item) => item.kind)).toEqual([
      NEXT_ACTION_KIND.ASSIGNMENT,
      NEXT_ACTION_KIND.MERGE,
      NEXT_ACTION_KIND.MERGE,
      NEXT_ACTION_KIND.NAME,
      NEXT_ACTION_KIND.CLUSTER,
    ]);
  });

  it('filterReviewQueue applies KIND filter to an already-built item list', () => {
    const full = buildReviewQueue(sources, REVIEW_QUEUE_FILTER.ALL);
    const mergesOnly = filterReviewQueue(full, REVIEW_QUEUE_FILTER.MERGE);
    expect(mergesOnly).toHaveLength(2);
    expect(mergesOnly.every((item) => item.kind === NEXT_ACTION_KIND.MERGE)).toBe(true);
    expect(filterReviewQueue(full, REVIEW_QUEUE_FILTER.ALL)).toEqual(full);
  });
});

describe('buildReviewQueue — flattening', () => {
  it('flattens a same-cluster group of N into N queue items in compareSuggestions order', () => {
    // Three suggestions, same cluster + label → buildSuggestionReviewItems makes a group.
    const rows = [
      makeSuggestion({
        id: 'g-low',
        identity_id: 'id-1',
        suggested_cluster_id: 'cluster-maria',
        cluster_label: 'Maria',
        representative_similarity: 0.7,
        created_at: '2026-01-01T00:00:00.000Z',
      }),
      makeSuggestion({
        id: 'g-high',
        identity_id: 'id-2',
        suggested_cluster_id: 'cluster-maria',
        cluster_label: 'Maria',
        representative_similarity: 0.95,
        created_at: '2026-01-02T00:00:00.000Z',
      }),
      makeSuggestion({
        id: 'g-mid',
        identity_id: 'id-3',
        suggested_cluster_id: 'cluster-maria',
        cluster_label: 'Maria',
        representative_similarity: 0.85,
        created_at: '2026-01-03T00:00:00.000Z',
      }),
    ];
    const reviewItems = makeReviewItems(...rows);
    expect(reviewItems).toHaveLength(1);
    expect(reviewItems[0].type).toBe('group');

    const queue = buildReviewQueue({
      reviewItems,
      mergeSuggestions: [],
      nameSuggestions: [],
      sortedClusters: [],
    });

    expect(queue).toHaveLength(3);
    expect(queue.every((item) => item.kind === NEXT_ACTION_KIND.ASSIGNMENT)).toBe(true);
    // Within-group order: similarity desc (compareSuggestions).
    expect(queue.map((item) => ('suggestionId' in item ? item.suggestionId : null))).toEqual([
      'g-high',
      'g-mid',
      'g-low',
    ]);
    // Cluster identity preserved for later "N more for <name>" run labels.
    for (const [i, item] of queue.entries()) {
      expect(item).toMatchObject({
        kind: NEXT_ACTION_KIND.ASSIGNMENT,
        clusterId: 'cluster-maria',
        label: 'Maria',
        runSize: 3,
        runIndex: i,
      });
    }
  });

  it('marks singles as runSize 1', () => {
    const queue = buildReviewQueue({
      reviewItems: makeReviewItems(
        makeSuggestion({ id: 'solo', suggested_cluster_id: 'c-solo', cluster_label: 'Solo' }),
      ),
      mergeSuggestions: [],
      nameSuggestions: [],
      sortedClusters: [],
    });

    expect(queue).toHaveLength(1);
    expect(queue[0]).toMatchObject({
      kind: NEXT_ACTION_KIND.ASSIGNMENT,
      suggestionId: 'solo',
      runSize: 1,
      runIndex: 0,
    });
  });
});

describe('PR-54 index semantics under removal', () => {
  const ids = ['a', 'b', 'c', 'd'] as const;

  it('successful commit keeps the cursor (no-increment) via removeAtQueueCursor', () => {
    // Head commit: cursor stays 0; former next item slides into the slot.
    let cursor = 0;
    let queue: string[] = [...ids];

    let next = removeAtQueueCursor(queue, cursor);
    expect(next.index).toBe(cursor);
    expect(next.items[next.index]).toBe('b');
    expect(next.items).toEqual(['b', 'c', 'd']);
    queue = next.items;
    cursor = next.index;

    // Mid commit: still no-increment — same cursor now points at former next.
    cursor = 1; // on 'c'
    next = removeAtQueueCursor(queue, cursor);
    expect(next.index).toBe(cursor);
    expect(next.items).toEqual(['b', 'd']);
    expect(next.items[next.index]).toBe('d');
  });

  it('removeAtQueueCursor clamps after tail removal and empties safely', () => {
    // Tail removal: cursor was on last item → lands on new last item.
    const tail = removeAtQueueCursor(['a', 'b', 'c'], 2);
    expect(tail.items).toEqual(['a', 'b']);
    expect(tail.index).toBe(1);
    expect(tail.items[tail.index]).toBe('b');

    // Emptying the queue: index is 0; empty-state handling is a caller obligation.
    const emptied = removeAtQueueCursor(['only'], 0);
    expect(emptied.items).toEqual([]);
    expect(emptied.index).toBe(0);

    // Out-of-bounds: no-op copy; cursor clamped to current length.
    const oobHigh = removeAtQueueCursor(['a', 'b'], 5);
    expect(oobHigh.items).toEqual(['a', 'b']);
    expect(oobHigh.index).toBe(1);

    const oobNeg = removeAtQueueCursor(['a', 'b'], -1);
    expect(oobNeg.items).toEqual(['a', 'b']);
    expect(oobNeg.index).toBe(0);

    // Items-only helper still returns the filtered array.
    expect(removeAtQueueIndex(['a', 'b', 'c'], 1)).toEqual(['a', 'c']);
  });

  it('prev/next step within bounds and clamp oversized/negative inputs', () => {
    const length = ids.length;

    // Happy-path stepping.
    expect(nextQueueIndex(0, length)).toBe(1);
    expect(nextQueueIndex(1, length)).toBe(2);
    expect(prevQueueIndex(2, length)).toBe(1);
    expect(prevQueueIndex(1, length)).toBe(0);

    // Bound at start / end.
    expect(prevQueueIndex(0, length)).toBe(0);
    expect(nextQueueIndex(length - 1, length)).toBe(length - 1);

    // Negative / oversized inputs clamp before stepping (BR-02).
    expect(nextQueueIndex(-2, length)).toBe(1); // clamp → 0, then +1
    expect(prevQueueIndex(10, 3)).toBe(1); // clamp → 2, then -1
    expect(nextQueueIndex(99, 3)).toBe(2); // clamp → 2, stay at last
    expect(prevQueueIndex(-5, 3)).toBe(0); // clamp → 0, stay at first

    // Empty queue: stay non-negative.
    expect(nextQueueIndex(0, 0)).toBe(0);
    expect(prevQueueIndex(0, 0)).toBe(0);
    expect(prevQueueIndex(5, 0)).toBe(0);
  });

  it('restored index clamps to min(index, length-1); empty queue → empty state (no negative)', () => {
    expect(clampQueueIndex(0, 4)).toBe(0);
    expect(clampQueueIndex(3, 4)).toBe(3);
    expect(clampQueueIndex(5, 4)).toBe(3);
    expect(clampQueueIndex(99, 1)).toBe(0);
    // Empty queue: empty state, never negative, never crash.
    expect(clampQueueIndex(0, 0)).toBe(0);
    expect(clampQueueIndex(5, 0)).toBe(0);
    expect(clampQueueIndex(-3, 0)).toBe(0);
    expect(clampQueueIndex(-1, 4)).toBe(0);
  });
});
