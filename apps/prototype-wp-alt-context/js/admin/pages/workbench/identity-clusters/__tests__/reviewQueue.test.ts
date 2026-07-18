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
  NEXT_ACTION_CHIP_LABEL,
  NEXT_ACTION_KIND,
  nextQueueIndex,
  prevQueueIndex,
  removeAtQueueIndex,
  REVIEW_QUEUE_FILTER,
  queueItemToNextAction,
} from '../reviewQueue';
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

  it('successful commit does not increment the index — removal advances the head slot', () => {
    // User is at index 0 (head). Commit removes the head without index++.
    const index = 0;
    let queue = [...ids];

    queue = removeAtQueueIndex(queue, index);
    // Index stays 0; former [1] is now at the head slot.
    expect(index).toBe(0);
    expect(queue[index]).toBe('b');
    expect(queue).toEqual(['b', 'c', 'd']);

    // Commit again at head — still no index increment.
    queue = removeAtQueueIndex(queue, index);
    expect(index).toBe(0);
    expect(queue[index]).toBe('c');
  });

  it('prev and next are the only index mutations', () => {
    let index = 0;
    const length = ids.length;

    index = nextQueueIndex(index, length);
    expect(index).toBe(1);
    index = nextQueueIndex(index, length);
    expect(index).toBe(2);
    index = prevQueueIndex(index);
    expect(index).toBe(1);
    index = prevQueueIndex(index);
    expect(index).toBe(0);
    // Bound at start / end.
    expect(prevQueueIndex(0)).toBe(0);
    expect(nextQueueIndex(length - 1, length)).toBe(length - 1);
    // removeAtQueueIndex never touches the caller's index variable.
    const afterRemoval = removeAtQueueIndex(ids, 1);
    expect(afterRemoval).toEqual(['a', 'c', 'd']);
    expect(index).toBe(0);
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
    // next/prev on empty also stay non-negative.
    expect(nextQueueIndex(0, 0)).toBe(0);
    expect(prevQueueIndex(0)).toBe(0);
  });
});
