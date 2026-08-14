import { QueryClient } from '@tanstack/react-query';
import { describe, expect, it } from 'vitest';

import { queryKeys } from '../../../../api/queryKeys';
import type { ClusterSuggestion, PendingSuggestion } from '../../../../api/recognition';
import {
  AUTO_LABEL_PREFIX,
  PROJECTION_TOP_K,
  SUGGESTION_PROJECTION_INVALIDATION_EVENTS,
  SUGGESTION_RESOLUTION,
  compareSuggestions,
  fromIdentityMatch,
  fromPendingRow,
  identityBatchIdsKey,
  invalidateSuggestionProjection,
  isHumanLabeledTarget,
  isIdentityLegResolution,
  projectIdentityLegFromPending,
  projectIdentityWindow,
  projectReviewQueue,
  readIdentityBatchCacheEntry,
  readIdentityBatchUpdatedAt,
  readIdentityFromBatchCache,
  seedIdentityBatchSingles,
  type ProjectedSuggestion,
} from '../suggestionProjection';
import { buildClusterMatch, buildPendingRow, suggestionProjectionMatrix } from './suggestionProjection.fixtures';

describe('isHumanLabeledTarget', () => {
  it('accepts truthy human-format labels', () => {
    expect(isHumanLabeledTarget('Alice')).toBe(true);
    expect(isHumanLabeledTarget('Person 3')).toBe(true);
    expect(isHumanLabeledTarget('  Bob  ')).toBe(true);
  });

  it('rejects null, undefined, empty, and whitespace-only labels', () => {
    expect(isHumanLabeledTarget(null)).toBe(false);
    expect(isHumanLabeledTarget(undefined)).toBe(false);
    expect(isHumanLabeledTarget('')).toBe(false);
    expect(isHumanLabeledTarget('   ')).toBe(false);
    expect(isHumanLabeledTarget('\t\n')).toBe(false);
  });

  it(`rejects ${AUTO_LABEL_PREFIX}-prefixed auto-labels`, () => {
    expect(isHumanLabeledTarget('cluster-1234')).toBe(false);
    expect(isHumanLabeledTarget('cluster-abcdef01')).toBe(false);
    expect(isHumanLabeledTarget('  cluster-ab  ')).toBe(false);
  });

  // BR-28: PHP system-label detector accepts cluster[-_] case-insensitively (hex suffixes, ≥8).
  it('rejects case-insensitive cluster[-_] machine labels (PHP parity / hex)', () => {
    expect(isHumanLabeledTarget('Cluster-abcdef12')).toBe(false);
    expect(isHumanLabeledTarget('cluster_abcdef12')).toBe(false);
    expect(isHumanLabeledTarget('CLUSTER-ABCDEF12')).toBe(false);
    expect(isHumanLabeledTarget('  Cluster-abcdef12  ')).toBe(false);
    expect(isHumanLabeledTarget('  cluster_abcdef12  ')).toBe(false);
    // Non-prefix / missing separator must still pass as human-format.
    expect(isHumanLabeledTarget('mycluster-foo')).toBe(true);
    expect(isHumanLabeledTarget('clusterabc')).toBe(true);
  });

  // BR-34: anchored machine shape — short forms + UUID hex stay gated; human Cluster* pass.
  it('gates short and UUID-shaped cluster[-_][0-9a-f-]+ machine labels (BR-34)', () => {
    expect(isHumanLabeledTarget('cluster-7')).toBe(false);
    expect(isHumanLabeledTarget('  cluster-7')).toBe(false);
    expect(isHumanLabeledTarget('Cluster-abcdef12')).toBe(false);
    expect(isHumanLabeledTarget('cluster_abcdef12')).toBe(false);
    expect(isHumanLabeledTarget('cluster-a1b2c3d4-e5f6-7890-abcd-ef1234567890')).toBe(false);
  });

  it('passes operator-plausible human Cluster* labels that are not machine-shaped (BR-34)', () => {
    expect(isHumanLabeledTarget('Cluster-Bomb Collective')).toBe(true);
    expect(isHumanLabeledTarget('CLUSTER_HQ')).toBe(true);
    expect(isHumanLabeledTarget('Cluster_X')).toBe(true);
    expect(isHumanLabeledTarget('Cluster Nine')).toBe(true);
  });

  // BR-37/BR-38: two-shape reject — PHP-parity long hex (any case) OR lowercase machine forms.
  // BR-44: it.each so each matrix input reports independently (vitest aborts at first expect in a shared it).
  it.each([
    'cluster-xyz',
    '  cluster-xyz  ',
    'cluster-auto-1',
    'cluster-g7x2',
    'cluster_12_final',
    'cluster-dad',
  ])('gates non-hex lowercase machine shapes (BR-37/BR-38): %j', (label) => {
    expect(isHumanLabeledTarget(label)).toBe(false);
  });

  it.each([
    'cluster-7',
    'cluster-ab',
    'cluster-1234',
    'cluster-abcdef01',
    'cluster-123e4567-e89b-12d3-a456-426614174000',
    'CLUSTER-ABCDEF12',
    'Cluster-abcdef12',
    'cluster_ABCDEF1234',
  ])('gates hex machine labels across lengths and case (BR-37/BR-38): %j', (label) => {
    expect(isHumanLabeledTarget(label)).toBe(false);
  });

  it.each([
    'Cluster-Dad',
    'Cluster-ace',
    'Cluster-BEEF',
    'Cluster-Cafe',
    'Alex',
  ])('passes hex-word human Cluster* names with uppercase letters (BR-37/BR-38): %j', (label) => {
    expect(isHumanLabeledTarget(label)).toBe(true);
  });
});

describe('isIdentityLegResolution', () => {
  it('treats undefined and pending as identity-leg active', () => {
    expect(isIdentityLegResolution(undefined)).toBe(true);
    expect(isIdentityLegResolution(SUGGESTION_RESOLUTION.PENDING)).toBe(true);
  });

  it('excludes accepted and rejected resolutions from identity-keyed reads', () => {
    expect(isIdentityLegResolution(SUGGESTION_RESOLUTION.ACCEPTED)).toBe(false);
    expect(isIdentityLegResolution(SUGGESTION_RESOLUTION.REJECTED)).toBe(false);
  });
});

describe('compareSuggestions', () => {
  const base = (overrides: Partial<ProjectedSuggestion>): ProjectedSuggestion => ({
    identityId: 'id-1',
    clusterId: 'c-1',
    label: 'X',
    similarity: 0.5,
    ...overrides,
  });

  it('orders by similarity descending', () => {
    const high = base({ suggestionId: 'high', similarity: 0.9 });
    const low = base({ suggestionId: 'low', similarity: 0.4 });
    expect(compareSuggestions(high, low)).toBeLessThan(0);
    expect([low, high].sort(compareSuggestions).map((s) => s.suggestionId)).toEqual(['high', 'low']);
  });

  it('breaks similarity ties with createdAt descending', () => {
    const older = base({
      suggestionId: 'older',
      similarity: 0.8,
      createdAt: '2026-01-01T00:00:00.000Z',
    });
    const newer = base({
      suggestionId: 'newer',
      similarity: 0.8,
      createdAt: '2026-06-01T00:00:00.000Z',
    });
    expect(compareSuggestions(newer, older)).toBeLessThan(0);
    expect([older, newer].sort(compareSuggestions).map((s) => s.suggestionId)).toEqual(['newer', 'older']);
  });

  it('sorts missing createdAt after any defined timestamp under desc tie-break', () => {
    const missing = base({ suggestionId: 'missing', similarity: 0.8 });
    const defined = base({
      suggestionId: 'defined',
      similarity: 0.8,
      createdAt: '2020-01-01T00:00:00.000Z',
    });
    expect([missing, defined].sort(compareSuggestions).map((s) => s.suggestionId)).toEqual(['defined', 'missing']);
  });
});

describe('adapters', () => {
  describe('fromIdentityMatch', () => {
    it('maps all present fields without enrichment or fabricated suggestionId', () => {
      const match: ClusterSuggestion = {
        cluster_id: 'cluster-a',
        label: 'Alice',
        similarity: 0.91,
        identity_count: 6,
      };
      const projected = fromIdentityMatch('identity-1', match);
      expect(projected).toEqual({
        identityId: 'identity-1',
        clusterId: 'cluster-a',
        label: 'Alice',
        similarity: 0.91,
        identityCount: 6,
      });
      expect(projected).not.toHaveProperty('suggestionId');
      expect(projected.enrichment).toBeUndefined();
      expect(projected.createdAt).toBeUndefined();
    });

    it('includes suggestionId only when source provides suggestion_id', () => {
      const withId = fromIdentityMatch(
        'identity-1',
        buildClusterMatch({
          suggestion_id: 'sug-1',
          cluster_id: 'c-1',
          label: 'Alice',
          similarity: 0.5,
        }),
      );
      expect(withId.suggestionId).toBe('sug-1');
    });
  });

  describe('fromPendingRow', () => {
    it('maps core fields and enrichment without inventing identityCount or createdAt', () => {
      const row: PendingSuggestion = {
        id: 'sug-p-1',
        identity_id: 'identity-9',
        suggested_cluster_id: 'cluster-z',
        representative_similarity: 0.66,
        cluster_label: null,
        identity_media_url: 'https://example.test/id.jpg',
        representative_thumb_url: 'https://example.test/thumb.jpg',
        suggested_label: 'Zed',
        suggested_label_source: 'identity',
        suggested_label_confidence: 0.4,
      };
      const projected = fromPendingRow(row);
      expect(projected.suggestionId).toBe('sug-p-1');
      expect(projected.identityId).toBe('identity-9');
      expect(projected.clusterId).toBe('cluster-z');
      expect(projected.label).toBeNull();
      expect(projected.similarity).toBe(0.66);
      expect(projected.identityCount).toBeUndefined();
      expect(projected.createdAt).toBeUndefined();
      expect(projected.resolution).toBeUndefined();
      expect(projected.enrichment).toStrictEqual({
        identityMediaUrl: 'https://example.test/id.jpg',
        representativeThumbUrl: 'https://example.test/thumb.jpg',
        suggestedLabel: 'Zed',
        suggestedLabelSource: 'identity',
        suggestedLabelConfidence: 0.4,
      });
      expect(Object.keys(projected.enrichment ?? {})).toHaveLength(5);
    });

    it('omits enrichment entirely when the row carries no enrichment fields', () => {
      const bare = fromPendingRow(buildPendingRow({ id: 'bare', identity_id: 'i' }));
      expect(bare).not.toHaveProperty('enrichment');
    });

    it('passes resolution through and omits identityCount for non-finite values', () => {
      const resolved = fromPendingRow(
        buildPendingRow({ id: 'r', identity_id: 'i', resolution: SUGGESTION_RESOLUTION.ACCEPTED }),
      );
      expect(resolved.resolution).toBe(SUGGESTION_RESOLUTION.ACCEPTED);

      const nanCount = fromPendingRow(
        buildPendingRow({ id: 'n', identity_id: 'i', cluster_identity_count: Number.NaN }),
      );
      expect(nanCount.identityCount).toBeUndefined();
    });

    it('sets identityCount only when cluster_identity_count is a number', () => {
      const withCount = fromPendingRow(
        buildPendingRow({
          id: 'a',
          identity_id: 'i',
          cluster_identity_count: 8,
        }),
      );
      expect(withCount.identityCount).toBe(8);

      const nullCount = fromPendingRow(
        buildPendingRow({
          id: 'b',
          identity_id: 'i',
          cluster_identity_count: null,
        }),
      );
      expect(nullCount.identityCount).toBeUndefined();
    });

    it('does not attach enrichment on identity adapter (review-only)', () => {
      const identity = fromIdentityMatch('i', buildClusterMatch({ cluster_id: 'c', label: 'A', similarity: 0.1 }));
      const pending = fromPendingRow(buildPendingRow({ id: 's', identity_id: 'i', suggested_label: 'Zed' }));
      expect(identity.enrichment).toBeUndefined();
      expect(pending.enrichment).toBeDefined();
    });
  });
});

describe('matrix fixture outcomes', () => {
  it('multi-suggestion identity: preserves server order and exposes top-1', () => {
    const { multiSuggestionIdentity: caseData } = suggestionProjectionMatrix;
    const projected = projectIdentityWindow(caseData.identityId, caseData.matches);
    expect(projected.map((p) => p.suggestionId)).toEqual(caseData.expectedIdentitySuggestionIds);
    expect(projected[0]?.suggestionId).toBe(caseData.expectedIdentityTopSuggestionId);

    const review = projectReviewQueue(caseData.pendingRows);
    expect(review.map((p) => p.suggestionId)).toEqual(caseData.expectedReviewSuggestionIdsBySimilarity);
  });

  it('cluster-*-first-then-human: filters auto-labels inside the top-K window', () => {
    const { clusterFirstThenHuman: caseData } = suggestionProjectionMatrix;
    expect(caseData.matches.length).toBeLessThanOrEqual(PROJECTION_TOP_K);
    const projected = projectIdentityWindow(caseData.identityId, caseData.matches);
    expect(projected.map((p) => p.suggestionId)).toEqual(caseData.expectedIdentitySuggestionIds);
    expect(projected[0]?.suggestionId).toBe(caseData.expectedIdentityTopSuggestionId);
    expect(projected[0]?.label).toBe('Bob');
  });

  it('all-ineligible window with an eligible 6th beyond it: yields no prompt', () => {
    const { allIneligibleWindow: caseData } = suggestionProjectionMatrix;
    expect(caseData.matches).toHaveLength(PROJECTION_TOP_K + 1);
    expect(isHumanLabeledTarget(caseData.matches[PROJECTION_TOP_K]?.label)).toBe(true);
    const projected = projectIdentityWindow(caseData.identityId, caseData.matches);
    expect(projected).toEqual([]);
    expect(caseData.expectedIdentityTopSuggestionId).toBeUndefined();
  });

  it('Person N labeled-but-unconfirmed: eligible inline/dropdown, absent from the review queue', () => {
    const { labeledButUnconfirmedPersonN: caseData } = suggestionProjectionMatrix;
    expect(isHumanLabeledTarget('Person 3')).toBe(true);
    const projected = projectIdentityWindow(caseData.identityId, caseData.matches);
    expect(projected.map((p) => p.suggestionId)).toEqual(caseData.expectedIdentitySuggestionIds);
    const review = projectReviewQueue(caseData.reviewQueueRows);
    expect(review.map((p) => p.suggestionId)).toEqual(caseData.expectedReviewSuggestionIds);
    expect(review).toEqual([]);
  });

  it('tied similarities: identity preserves arrival order; review uses createdAt desc', () => {
    const { tiedSimilarities: caseData } = suggestionProjectionMatrix;
    const identityProjected = projectIdentityWindow(caseData.identityId, caseData.matches);
    expect(identityProjected.map((p) => p.suggestionId)).toEqual(caseData.expectedIdentitySuggestionIds);

    // BR-23: projectReviewQueue is the live assignment queryFn adapter.
    const reviewProjected = projectReviewQueue(caseData.pendingRows);
    expect(reviewProjected.map((p) => p.suggestionId)).toEqual(caseData.expectedReviewSuggestionIds);
  });

  it('stale-accepted rows are review-only (excluded from identity leg)', () => {
    const { staleAccepted: caseData } = suggestionProjectionMatrix;
    const identityProjected = projectIdentityLegFromPending(caseData.pendingRows);
    expect(identityProjected.map((p) => p.suggestionId)).toEqual(caseData.expectedIdentitySuggestionIds);

    // BR-23: live path (useSuggestionReviewQueries) calls projectReviewQueue in queryFn.
    const reviewProjected = projectReviewQueue(caseData.pendingRows);
    expect(reviewProjected.map((p) => p.suggestionId)).toEqual(caseData.expectedReviewSuggestionIds);
    const staleRow = reviewProjected.find((p) => p.suggestionId === 'sug-stale-accepted');
    expect(staleRow?.resolution).toBe(SUGGESTION_RESOLUTION.ACCEPTED);
  });
});

describe('projectReviewQueue is the live review-page adapter (BR-23)', () => {
  it('adapt + human-label filter + sort matches the assignment queryFn contract', () => {
    const rows = [
      buildPendingRow({
        id: 'low',
        identity_id: 'i1',
        suggested_cluster_id: 'c-low',
        cluster_label: 'Low',
        representative_similarity: 0.4,
        created_at: '2026-06-01T00:00:00.000Z',
      }),
      buildPendingRow({
        id: 'auto',
        identity_id: 'i2',
        suggested_cluster_id: 'c-auto',
        cluster_label: 'cluster-abcdef12',
        representative_similarity: 0.99,
      }),
      buildPendingRow({
        id: 'high',
        identity_id: 'i3',
        suggested_cluster_id: 'c-high',
        cluster_label: 'High',
        representative_similarity: 0.9,
        created_at: '2026-01-01T00:00:00.000Z',
      }),
    ];
    const projected = projectReviewQueue(rows);
    expect(projected.map((p) => p.suggestionId)).toEqual(['high', 'low']);
    expect(projected.every((p) => isHumanLabeledTarget(p.label))).toBe(true);
  });
});

describe('identityBatchIdsKey', () => {
  it('normalizes order and duplicates to one canonical key', () => {
    expect(identityBatchIdsKey(['id-b', 'id-a'])).toBe('id-a,id-b');
    expect(identityBatchIdsKey(['id-a', 'id-b', 'id-a'])).toBe('id-a,id-b');
    expect(identityBatchIdsKey(['id-b', 'id-a'])).toBe(identityBatchIdsKey(['id-a', 'id-b']));
    expect(identityBatchIdsKey([])).toBe('');
  });
});

describe('seedIdentityBatchSingles (L1R-04)', () => {
  it('does not seed [] for ids absent from response.matches', () => {
    // Predicted first failure: id-b gets an authoritative empty single-id entry
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const matchA = buildClusterMatch({
      suggestion_id: 'sug-a',
      cluster_id: 'c-a',
      label: 'Ada',
      similarity: 0.9,
    });
    seedIdentityBatchSingles(
      queryClient,
      { matches: { 'id-a': [matchA] } },
      ['id-a', 'id-b'],
    );

    const keyA = queryKeys.suggestions.projection.identityBatch(identityBatchIdsKey(['id-a']));
    const keyB = queryKeys.suggestions.projection.identityBatch(identityBatchIdsKey(['id-b']));
    expect(queryClient.getQueryData(keyA)).toEqual({ matches: { 'id-a': [matchA] } });
    expect(queryClient.getQueryData(keyB)).toBeUndefined();
  });
});

describe('readIdentityBatchCacheEntry (L1R-03)', () => {
  it('returns data and dataUpdatedAt from the same first matching batch', () => {
    // Predicted first failure of split readers: data from batch-1, updatedAt from later batch-2
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const staleMatch = buildClusterMatch({
      suggestion_id: 'stale',
      cluster_id: 'c-stale',
      label: 'Stale',
      similarity: 0.5,
    });
    const freshMatch = buildClusterMatch({
      suggestion_id: 'fresh',
      cluster_id: 'c-fresh',
      label: 'Fresh',
      similarity: 0.9,
    });
    const multiKey1 = queryKeys.suggestions.projection.identityBatch(identityBatchIdsKey(['id-x', 'id-y']));
    const multiKey2 = queryKeys.suggestions.projection.identityBatch(identityBatchIdsKey(['id-x', 'id-z']));
    queryClient.setQueryData(multiKey1, { matches: { 'id-x': [staleMatch], 'id-y': [] } });
    // Force an older dataUpdatedAt on the first batch, newer on the second.
    const state1 = queryClient.getQueryState(multiKey1);
    if (state1) {
      state1.dataUpdatedAt = 1_000;
    }
    queryClient.setQueryData(multiKey2, { matches: { 'id-x': [freshMatch], 'id-z': [] } });
    const state2 = queryClient.getQueryState(multiKey2);
    if (state2) {
      state2.dataUpdatedAt = 9_000;
    }

    const entry = readIdentityBatchCacheEntry(queryClient, 'id-x');
    expect(entry?.data.matches['id-x']?.[0]?.suggestion_id).toBe('stale');
    expect(entry?.dataUpdatedAt).toBe(1_000);
    // Paired helpers must agree with the single entry (not latest-across-batches).
    expect(readIdentityFromBatchCache(queryClient, 'id-x')?.matches['id-x']?.[0]?.suggestion_id).toBe(
      'stale',
    );
    expect(readIdentityBatchUpdatedAt(queryClient, 'id-x')).toBe(1_000);
  });
});

describe('PROJECTION_TOP_K window depth', () => {
  it('only considers the first PROJECTION_TOP_K server rows before filtering', () => {
    const identityId = 'identity-window';
    const matches: ClusterSuggestion[] = [
      ...Array.from({ length: PROJECTION_TOP_K }, (_, i) =>
        buildClusterMatch({
          suggestion_id: `auto-${i}`,
          cluster_id: `c-auto-${i}`,
          label: `cluster-${i}`,
          similarity: 0.99 - i * 0.01,
        }),
      ),
      buildClusterMatch({
        suggestion_id: 'human-beyond-window',
        cluster_id: 'c-human',
        label: 'Human Beyond',
        similarity: 0.5,
      }),
    ];
    const projected = projectIdentityWindow(identityId, matches);
    expect(projected).toEqual([]);
    expect(matches).toHaveLength(PROJECTION_TOP_K + 1);
  });
});

describe('invalidateSuggestionProjection', () => {
  it('invalidates only the projection subtree, leaving sibling suggestion keys intact', async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });

    const identityKey = queryKeys.suggestions.projection.identityBatch('ids-a,ids-b');
    const reviewKey = queryKeys.suggestions.projection.reviewPage(0);
    const mergeKey = queryKeys.suggestions.mergePending();

    queryClient.setQueryData(identityKey, [{ id: 'projection-identity' }]);
    queryClient.setQueryData(reviewKey, [{ id: 'projection-review' }]);
    queryClient.setQueryData(mergeKey, [{ id: 'merge-sibling' }]);

    await invalidateSuggestionProjection(queryClient);

    const identityState = queryClient.getQueryState(identityKey);
    const reviewState = queryClient.getQueryState(reviewKey);
    const mergeState = queryClient.getQueryState(mergeKey);

    expect(identityState?.isInvalidated).toBe(true);
    expect(reviewState?.isInvalidated).toBe(true);
    expect(mergeState?.isInvalidated).toBe(false);
    expect(queryClient.getQueryData(mergeKey)).toEqual([{ id: 'merge-sibling' }]);
  });
});

describe('SUGGESTION_PROJECTION_INVALIDATION_EVENTS', () => {
  it('enumerates exactly eight event rows', () => {
    expect(Object.keys(SUGGESTION_PROJECTION_INVALIDATION_EVENTS)).toHaveLength(8);
  });

  it('marks every event as invalidating the assignment projection', () => {
    for (const event of Object.values(SUGGESTION_PROJECTION_INVALIDATION_EVENTS)) {
      expect(event.invalidatesAssignmentProjection).toBe(true);
    }
  });

  it('preserves the live-verified cross-family targets per event', () => {
    expect(SUGGESTION_PROJECTION_INVALIDATION_EVENTS.suggestionAccept.keptCrossFamilyTargets).toEqual([
      'clusters.all',
      'media.identities',
    ]);
    expect(SUGGESTION_PROJECTION_INVALIDATION_EVENTS.suggestionReject.keptCrossFamilyTargets).toEqual(['clusters.all']);
    expect(SUGGESTION_PROJECTION_INVALIDATION_EVENTS.bulkAccept.keptCrossFamilyTargets).toEqual([
      'mergePending',
      'namePending',
      'clusters.all',
    ]);
    expect(SUGGESTION_PROJECTION_INVALIDATION_EVENTS.clusterLabelSetClear.keptCrossFamilyTargets).toEqual([
      'mergePending',
      'clusters.all',
      'clusters.labels',
      'media.identities',
    ]);
    expect(SUGGESTION_PROJECTION_INVALIDATION_EVENTS.clusterMerge.keptCrossFamilyTargets).toEqual([
      'mergePending',
      'clusters.all',
      'clusters.labels',
      'media.identities',
    ]);
    expect(SUGGESTION_PROJECTION_INVALIDATION_EVENTS.clusterDismiss.keptCrossFamilyTargets).toEqual([
      'clusters.topUnlabeled',
      'clusters.all',
    ]);
    expect(SUGGESTION_PROJECTION_INVALIDATION_EVENTS.scanRecomputeCompletion.keptCrossFamilyTargets).toEqual([
      'mergePending',
      'namePending',
      'media.identities',
      'clusters.topUnlabeled',
    ]);
    expect(SUGGESTION_PROJECTION_INVALIDATION_EVENTS.syncTrigger.keptCrossFamilyTargets).toEqual([]);
    expect(SUGGESTION_PROJECTION_INVALIDATION_EVENTS.syncTrigger.viaSuggestionsAllRoot).toBe(true);
  });
});

describe('queryKeys.suggestions.projection nesting', () => {
  it('nests projection.all under suggestions.all', () => {
    expect(queryKeys.suggestions.projection.all).toEqual([...queryKeys.suggestions.all, 'projection']);
  });

  it('nests identityBatch and reviewPage under projection.all', () => {
    expect(queryKeys.suggestions.projection.identityBatch('k1')).toEqual([
      ...queryKeys.suggestions.projection.all,
      'identity-batch',
      'k1',
    ]);
    expect(queryKeys.suggestions.projection.reviewPage(20)).toEqual([
      ...queryKeys.suggestions.projection.all,
      'review-page',
      20,
    ]);
  });
});
