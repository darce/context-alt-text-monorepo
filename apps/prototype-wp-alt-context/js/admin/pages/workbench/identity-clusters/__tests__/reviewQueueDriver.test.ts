/**
 * E21-5 Slice 1a — review queue driver unit tests.
 * Covers: order, KIND filter, group flattening, PR-54 index-under-removal.
 */

import { describe, expect, it } from 'vitest';

import type { PendingMergeSuggestion, PendingNameSuggestion, PendingSuggestion } from '../../../../api/recognition/types';
import type { TopUnlabeledCluster } from '../../../../api/recognition/types/cluster';
import {
  buildReviewQueue,
  bulkSelectableIdsInFilters,
  clampQueueIndex,
  CLUSTER_EVIDENCE,
  clusterEvidence,
  filterReviewQueue,
  filterReviewQueueByBand,
  filterReviewQueueComposite,
  intersectSelectionWithFilters,
  isZeroEvidenceCluster,
  matchesSimilarityBand,
  NEXT_ACTION_CHIP_LABEL,
  NEXT_ACTION_KIND,
  nextQueueIndex,
  prevQueueIndex,
  REVIEW_QUEUE_BAND,
  REVIEW_QUEUE_BAND_CHIP_LABEL,
  REVIEW_QUEUE_FILTER,
  STRONG_SIMILARITY_MIN,
  isValidQueueOrdinalPair,
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

const EVIDENCE_REPRESENTATIVE = {
  id: 'rep-1',
  media_id: 1,
  is_pinned: false,
  thumb_url: 'http://example.test/face.jpg',
};

const makeCluster = (overrides: Partial<TopUnlabeledCluster> = {}): TopUnlabeledCluster => ({
  id: 'top-1',
  tenant_id: 'test-tenant-id',
  label: null,
  is_labeled: false,
  is_auto_label: false,
  identity_count: 3,
  user_confirmed: false,
  representatives: [EVIDENCE_REPRESENTATIVE],
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
    expect(queue[2]).toEqual({
      kind: NEXT_ACTION_KIND.MERGE,
      suggestionId: 'merge-7',
      similarity: 0.9,
    });
    expect(queue[3]).toEqual({
      kind: NEXT_ACTION_KIND.NAME,
      suggestionId: 'name-9',
      clusterId: 'cluster-9',
    });
    expect(queue[4]).toEqual({ kind: NEXT_ACTION_KIND.CLUSTER, clusterId: 'large' });
    expect(queue[5]).toEqual({ kind: NEXT_ACTION_KIND.CLUSTER, clusterId: 'small' });
    // Assignment items carry ProjectedSuggestion.similarity for band filtering.
    expect(queue[0]).toMatchObject({
      kind: NEXT_ACTION_KIND.ASSIGNMENT,
      suggestionId: 'sugg-high',
      similarity: 0.95,
    });
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

describe('band filter (④) + matrix M2 composition', () => {
  it('pins STRONG_SIMILARITY_MIN (pending-band midpoint) and human band chip copy (sr-007)', () => {
    // BR-57: midpoint of the live pending band [suggestion_floor=0.35, suggestion_ceiling=0.55).
    expect(STRONG_SIMILARITY_MIN).toBe(0.45);
    expect(REVIEW_QUEUE_BAND_CHIP_LABEL[REVIEW_QUEUE_BAND.STRONG]).toBe('Strong matches');
    expect(REVIEW_QUEUE_BAND_CHIP_LABEL[REVIEW_QUEUE_BAND.WEAKER]).toBe('Weaker matches');
  });

  it('matchesSimilarityBand is a pure predicate over similarity (post-eligibility)', () => {
    expect(matchesSimilarityBand(0.5, REVIEW_QUEUE_BAND.STRONG)).toBe(true);
    expect(matchesSimilarityBand(0.45, REVIEW_QUEUE_BAND.STRONG)).toBe(true);
    expect(matchesSimilarityBand(0.44, REVIEW_QUEUE_BAND.STRONG)).toBe(false);
    expect(matchesSimilarityBand(0.44, REVIEW_QUEUE_BAND.WEAKER)).toBe(true);
    expect(matchesSimilarityBand(0.45, REVIEW_QUEUE_BAND.WEAKER)).toBe(false);
    expect(matchesSimilarityBand(undefined, REVIEW_QUEUE_BAND.STRONG)).toBe(false);
    expect(matchesSimilarityBand(undefined, REVIEW_QUEUE_BAND.ALL)).toBe(true);
    expect(matchesSimilarityBand(0.1, REVIEW_QUEUE_BAND.ALL)).toBe(true);
  });

  it('band predicate applies to ASSIGNMENT similarity only; merges excluded like name/cluster (BR-60)', () => {
    // Pending-band-realistic fixtures: 0.50 strong (upper half), 0.40 weaker (lower half).
    const queue = buildReviewQueue({
      reviewItems: makeReviewItems(
        makeSuggestion({
          id: 'a-strong',
          suggested_cluster_id: 'c-strong',
          cluster_label: 'Alice',
          representative_similarity: 0.5,
        }),
        makeSuggestion({
          id: 'a-weak',
          suggested_cluster_id: 'c-weak',
          cluster_label: 'Bob',
          representative_similarity: 0.4,
        }),
      ),
      mergeSuggestions: [
        makeMerge({ id: 'merge-high', similarity: 0.91 }),
        makeMerge({ id: 'merge-low', similarity: 0.4 }),
      ],
      nameSuggestions: [makeName({ id: 'name-1' })],
      sortedClusters: [makeCluster({ id: 'cluster-1' })],
    });

    // Merge similarity is a different domain (cluster-pair) — never banded,
    // regardless of its numeric value.
    const strong = filterReviewQueueByBand(queue, REVIEW_QUEUE_BAND.STRONG);
    expect(
      strong.map((item) => ('suggestionId' in item ? item.suggestionId : item.clusterId)),
    ).toEqual(['a-strong']);

    const weaker = filterReviewQueueByBand(queue, REVIEW_QUEUE_BAND.WEAKER);
    expect(
      weaker.map((item) => ('suggestionId' in item ? item.suggestionId : item.clusterId)),
    ).toEqual(['a-weak']);

    // Merge/name/cluster have no band similarity → only when band=all.
    expect(queue.some((item) => item.kind === NEXT_ACTION_KIND.MERGE)).toBe(true);
    expect(strong.some((item) => item.kind === NEXT_ACTION_KIND.MERGE)).toBe(false);
    expect(weaker.some((item) => item.kind === NEXT_ACTION_KIND.MERGE)).toBe(false);
    expect(strong.some((item) => item.kind === NEXT_ACTION_KIND.NAME)).toBe(false);
    expect(weaker.some((item) => item.kind === NEXT_ACTION_KIND.CLUSTER)).toBe(false);
  });

  it('BR-60: strong ∪ weaker ⊂ all — remainder is exactly the non-assignment kinds', () => {
    const queue = buildReviewQueue({
      reviewItems: makeReviewItems(
        makeSuggestion({
          id: 'a-strong',
          suggested_cluster_id: 'c-strong',
          cluster_label: 'Alice',
          representative_similarity: 0.5,
        }),
        makeSuggestion({
          id: 'a-weak',
          suggested_cluster_id: 'c-weak',
          cluster_label: 'Bob',
          representative_similarity: 0.4,
        }),
      ),
      mergeSuggestions: [
        makeMerge({ id: 'merge-high', similarity: 0.91 }),
        makeMerge({ id: 'merge-low', similarity: 0.4 }),
      ],
      nameSuggestions: [makeName({ id: 'name-1' })],
      sortedClusters: [makeCluster({ id: 'cluster-1' })],
    });

    const key = (item: (typeof queue)[number]): string =>
      'suggestionId' in item ? `${item.kind}:${item.suggestionId}` : `${item.kind}:${item.clusterId}`;
    const all = new Set(filterReviewQueueByBand(queue, REVIEW_QUEUE_BAND.ALL).map(key));
    const banded = new Set([
      ...filterReviewQueueByBand(queue, REVIEW_QUEUE_BAND.STRONG).map(key),
      ...filterReviewQueueByBand(queue, REVIEW_QUEUE_BAND.WEAKER).map(key),
    ]);

    // strong ∪ weaker is a strict subset of all…
    for (const k of banded) {
      expect(all.has(k)).toBe(true);
    }
    // …and the remainder is exactly the non-assignment kinds.
    const remainder = [...all].filter((k) => !banded.has(k)).sort();
    expect(remainder).toEqual(
      ['merge:merge-high', 'merge:merge-low', 'name:name-1', 'cluster:cluster-1'].sort(),
    );
    expect(banded).toEqual(new Set(['assignment:a-strong', 'assignment:a-weak']));
  });

  it('KIND ∩ band compose by intersection', () => {
    const queue = buildReviewQueue({
      reviewItems: makeReviewItems(
        makeSuggestion({
          id: 'a-strong',
          cluster_label: 'Alice',
          representative_similarity: 0.5,
        }),
        makeSuggestion({
          id: 'a-weak',
          suggested_cluster_id: 'c-weak',
          cluster_label: 'Bob',
          representative_similarity: 0.4,
        }),
      ),
      mergeSuggestions: [
        makeMerge({ id: 'm-high', similarity: 0.88 }),
        makeMerge({ id: 'm-low', similarity: 0.4 }),
      ],
      nameSuggestions: [],
      sortedClusters: [],
    });

    const assignmentStrong = filterReviewQueueComposite(
      queue,
      REVIEW_QUEUE_FILTER.ASSIGNMENT,
      REVIEW_QUEUE_BAND.STRONG,
    );
    expect(assignmentStrong.map((i) => ('suggestionId' in i ? i.suggestionId : null))).toEqual([
      'a-strong',
    ]);

    // BR-60: merge is band-excluded — MERGE ∩ strong/weaker is empty; MERGE ∩ all keeps both.
    for (const band of [REVIEW_QUEUE_BAND.STRONG, REVIEW_QUEUE_BAND.WEAKER]) {
      expect(filterReviewQueueComposite(queue, REVIEW_QUEUE_FILTER.MERGE, band)).toEqual([]);
    }
    expect(
      filterReviewQueueComposite(queue, REVIEW_QUEUE_FILTER.MERGE, REVIEW_QUEUE_BAND.ALL).map(
        (i) => ('suggestionId' in i ? i.suggestionId : null),
      ),
    ).toEqual(['m-high', 'm-low']);
  });

  it('matrix M2: bulk preview/commit id set is selection ∩ (KIND ∩ band) [TEST-08]', () => {
    const queue = buildReviewQueue({
      reviewItems: makeReviewItems(
        makeSuggestion({
          id: 's-strong',
          cluster_label: 'Maria',
          representative_similarity: 0.5,
        }),
        makeSuggestion({
          id: 's-weak',
          suggested_cluster_id: 'c2',
          cluster_label: 'Maria',
          representative_similarity: 0.4,
        }),
        makeSuggestion({
          id: 's-strong-other',
          suggested_cluster_id: 'c3',
          cluster_label: 'Alex',
          representative_similarity: 0.52,
        }),
      ),
      mergeSuggestions: [makeMerge({ id: 'm-high', similarity: 0.85 })],
      nameSuggestions: [],
      sortedClusters: [],
    });

    // Select everything; active filters = assignment + strong → only strong assignments.
    const selected = new Set(['s-strong', 's-weak', 's-strong-other', 'm-high', 'ghost']);
    const previewIds = intersectSelectionWithFilters(
      selected,
      queue,
      REVIEW_QUEUE_FILTER.ASSIGNMENT,
      REVIEW_QUEUE_BAND.STRONG,
    );
    // Exact id set (TEST-08) — order follows selection iteration over allowed ids.
    expect(previewIds).toEqual(['s-strong', 's-strong-other']);

    // Band-only (kind=all): strong assignments only — merge is band-excluded (BR-60).
    expect(
      bulkSelectableIdsInFilters(queue, REVIEW_QUEUE_FILTER.ALL, REVIEW_QUEUE_BAND.STRONG).sort(),
    ).toEqual(['s-strong', 's-strong-other'].sort());

    // Weaker ∩ all kinds.
    expect(
      intersectSelectionWithFilters(
        selected,
        queue,
        REVIEW_QUEUE_FILTER.ALL,
        REVIEW_QUEUE_BAND.WEAKER,
      ),
    ).toEqual(['s-weak']);

    // band=all keeps the merge id bulk-selectable (visible under all only).
    expect(
      bulkSelectableIdsInFilters(queue, REVIEW_QUEUE_FILTER.ALL, REVIEW_QUEUE_BAND.ALL).sort(),
    ).toEqual(['m-high', 's-strong', 's-strong-other', 's-weak'].sort());
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
  it('prev/next step within bounds and clamp oversized/negative inputs', () => {
    const length = 4;

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

describe('buildReviewQueue — zero-evidence cluster gate (S2)', () => {
  it('isZeroEvidenceCluster is true when identity_count === 0 even with representatives [TEST-15]', () => {
    const cluster = makeCluster({
      id: 'zero-count',
      identity_count: 0,
      representatives: [EVIDENCE_REPRESENTATIVE],
    });
    expect(isZeroEvidenceCluster(cluster)).toBe(true);
    expect(clusterEvidence(cluster)).toBe(CLUSTER_EVIDENCE.ZERO);
  });

  it('isZeroEvidenceCluster is true when representatives is empty even with identity_count > 0 [TEST-15]', () => {
    const cluster = makeCluster({
      id: 'empty-reps',
      identity_count: 4,
      representatives: [],
    });
    expect(isZeroEvidenceCluster(cluster)).toBe(true);
    expect(clusterEvidence(cluster)).toBe(CLUSTER_EVIDENCE.ZERO);
  });

  it('isZeroEvidenceCluster is true when representatives is absent [TEST-15]', () => {
    const cluster = makeCluster({ id: 'absent-reps', identity_count: 2 });
    // Simulate a wire payload that omitted representatives.
    const absent = { ...cluster, representatives: undefined };
    expect(isZeroEvidenceCluster(absent)).toBe(true);
    expect(clusterEvidence(absent)).toBe(CLUSTER_EVIDENCE.ZERO);
  });

  it('excludes identity_count=0 clusters from the queue [TEST-15: kills ungated zero-count cards]', () => {
    const queue = buildReviewQueue({
      reviewItems: [],
      mergeSuggestions: [],
      nameSuggestions: [],
      sortedClusters: [
        makeCluster({
          id: 'zero-count',
          identity_count: 0,
          representatives: [EVIDENCE_REPRESENTATIVE],
        }),
        makeCluster({ id: 'reviewable', identity_count: 5 }),
      ],
    });

    expect(queue).toEqual([{ kind: NEXT_ACTION_KIND.CLUSTER, clusterId: 'reviewable' }]);
  });

  it('excludes empty-representatives clusters from the queue [TEST-15: kills ungated empty-rep cards]', () => {
    const queue = buildReviewQueue({
      reviewItems: [],
      mergeSuggestions: [],
      nameSuggestions: [],
      sortedClusters: [
        makeCluster({ id: 'empty-reps', identity_count: 7, representatives: [] }),
        makeCluster({ id: 'reviewable', identity_count: 2 }),
      ],
    });

    expect(queue).toEqual([{ kind: NEXT_ACTION_KIND.CLUSTER, clusterId: 'reviewable' }]);
  });

  it('keeps evidence clusters and assignment/merge/name items when mixed with zero-evidence', () => {
    const queue = buildReviewQueue({
      reviewItems: makeReviewItems(makeSuggestion({ id: 'a1', cluster_label: 'Ada' })),
      mergeSuggestions: [makeMerge({ id: 'm1' })],
      nameSuggestions: [makeName({ id: 'n1' })],
      sortedClusters: [
        makeCluster({ id: 'empty-reps', representatives: [] }),
        makeCluster({ id: 'zero-count', identity_count: 0 }),
        makeCluster({ id: 'reviewable', identity_count: 6 }),
      ],
    });

    expect(queue.map((item) => ('suggestionId' in item ? item.suggestionId : item.clusterId))).toEqual([
      'a1',
      'm1',
      'n1',
      'reviewable',
    ]);
  });
});

describe('isValidQueueOrdinalPair (E21-17-R1-TS41-1)', () => {
  it.each([
    { label: '(1,2)', position: 1, total: 2, expected: true },
    { label: '(2,2)', position: 2, total: 2, expected: true },
    { label: '(1,1)', position: 1, total: 1, expected: true },
    { label: '(3,3)', position: 3, total: 3, expected: true },
    { label: '(3,2)', position: 3, total: 2, expected: false },
    { label: 'position=0', position: 0, total: 2, expected: false },
    { label: 'total=0', position: 1, total: 0, expected: false },
    { label: 'position=NaN', position: Number.NaN, total: 2, expected: false },
    { label: 'total=float', position: 1, total: 1.5, expected: false },
    { label: 'undefined total', position: 1, total: undefined, expected: false },
    { label: 'negative position', position: -1, total: 2, expected: false },
    { label: 'negative total', position: 1, total: -1, expected: false },
    { label: 'float position', position: 1.5, total: 2, expected: false },
    { label: 'NaN total', position: 1, total: Number.NaN, expected: false },
    { label: 'undefined position', position: undefined, total: 2, expected: false },
  ])('pair $label → $expected', ({ position, total, expected }) => {
    expect(isValidQueueOrdinalPair(position, total)).toBe(expected);
  });
});
