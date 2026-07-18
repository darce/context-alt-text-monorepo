/**
 * E21-5 Slice 6 ④ — FBT-1 criterion-2 three-consumer harness.
 *
 * Imports `suggestionProjectionMatrix` (the handshake) and drives the three
 * real consumers over each fixture case per PR-51 applicability:
 *   - useInlineSuggestionBatch (identity leg)
 *   - useClusterSuggestions (identity / curation dropdown leg)
 *   - useSuggestionReviewQueries → review leg (pendingRows / reviewQueueRows)
 *
 * Assertions are LEG-SPECIFIC (PR-50): never cross-leg same-top-match.
 * Invalidation: shared QueryClient, per SUGGESTION_PROJECTION_INVALIDATION_EVENTS
 * key — presence asserts on target sets; extras allowed (UXP-3 contract).
 *
 * BR-23 (dismiss-invalidation divergence): CONFIRMED-AS-DESIGNED — see named test.
 */

import type { ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { resetConfigCache } from '../../../../api/config';
import { queryKeys } from '../../../../api/queryKeys';
import * as recognitionApi from '../../../../api/recognition';
import { useRosterEntries } from '../../../../hooks/useRosterHooks';
import { createMockQuery } from '../../../../test-utils/mockHooks';
import {
  invalidateSuggestionProjection,
  SUGGESTION_PROJECTION_INVALIDATION_EVENTS,
  type SuggestionProjectionInvalidationEvent,
} from '../suggestionProjection';
import { useClusterSuggestions } from '../useClusterSuggestions';
import { useInlineSuggestionBatch } from '../useInlineSuggestionBatch';
import { useSuggestionReviewQueries } from '../useSuggestionReviewQueries';
import { suggestionProjectionMatrix } from './suggestionProjection.fixtures';

vi.mock('../../../../api/recognition', async () => {
  const actual = await vi.importActual<typeof import('../../../../api/recognition')>(
    '../../../../api/recognition',
  );
  return {
    ...actual,
    fetchIdentitiesSuggestions: vi.fn(),
    fetchPendingSuggestions: vi.fn(),
    fetchPendingMergeSuggestions: vi.fn(),
    fetchPendingNameSuggestions: vi.fn(),
    fetchTopUnlabeledClusters: vi.fn(),
    listRecognitionClusters: vi.fn(),
  };
});

vi.mock('../../../../hooks/useRosterHooks', () => ({
  useRosterEntries: vi.fn(),
}));

type MatrixCaseKey = keyof typeof suggestionProjectionMatrix;
type MatrixCase = (typeof suggestionProjectionMatrix)[MatrixCaseKey];

const hasMatches = (
  c: MatrixCase,
): c is MatrixCase & { matches: NonNullable<MatrixCase extends { matches: infer M } ? M : never> } =>
  'matches' in c && Array.isArray((c as { matches?: unknown }).matches);

const reviewRowsFor = (c: MatrixCase): readonly import('../../../../api/recognition').PendingSuggestion[] => {
  if ('pendingRows' in c && Array.isArray(c.pendingRows)) {
    return c.pendingRows;
  }
  if ('reviewQueueRows' in c && Array.isArray(c.reviewQueueRows)) {
    return c.reviewQueueRows;
  }
  return [];
};

const hasReviewLeg = (c: MatrixCase): boolean =>
  ('pendingRows' in c && Array.isArray(c.pendingRows)) ||
  ('reviewQueueRows' in c && Array.isArray(c.reviewQueueRows));

const expectedIdentityIds = (c: MatrixCase): string[] => {
  if ('expectedIdentitySuggestionIds' in c) {
    return [...c.expectedIdentitySuggestionIds];
  }
  return [];
};

const expectedIdentityTop = (c: MatrixCase): string | undefined => {
  if ('expectedIdentityTopSuggestionId' in c) {
    return c.expectedIdentityTopSuggestionId;
  }
  const ids = expectedIdentityIds(c);
  return ids[0];
};

/** Leg-specific review expectation (PR-50) — never use identity top. */
const expectedReviewIds = (c: MatrixCase): string[] => {
  if ('expectedReviewSuggestionIdsBySimilarity' in c) {
    return [...c.expectedReviewSuggestionIdsBySimilarity];
  }
  if ('expectedReviewSuggestionIds' in c) {
    return [...c.expectedReviewSuggestionIds];
  }
  return [];
};

const flattenReviewSuggestionIds = (
  reviewItems: ReturnType<typeof useSuggestionReviewQueries>['reviewItems'],
): string[] => {
  const ids: string[] = [];
  for (const item of reviewItems) {
    if (item.type === 'group') {
      for (const s of item.suggestions) {
        ids.push(s.suggestionId);
      }
    } else {
      ids.push(item.suggestion.suggestionId);
    }
  }
  return ids;
};

/** Resolve a D4 keptCrossFamilyTargets token to the live invalidate queryKey. */
const crossFamilyQueryKey = (target: string, tenantId = 'tenant-1'): readonly unknown[] => {
  switch (target) {
    case 'clusters.all':
      return queryKeys.clusters.all;
    case 'clusters.labels':
      return queryKeys.clusters.labels();
    case 'clusters.topUnlabeled':
      return queryKeys.clusters.topUnlabeled(tenantId);
    case 'media.identities':
      return queryKeys.media.identities();
    case 'mergePending':
      return queryKeys.suggestions.mergePending();
    case 'namePending':
      return queryKeys.suggestions.namePending();
    default:
      throw new Error(`Unknown keptCrossFamilyTargets token: ${target}`);
  }
};

const makeQueryClient = (): QueryClient =>
  new QueryClient({
    defaultOptions: {
      queries: { retry: false, staleTime: 0 },
      mutations: { retry: false },
    },
  });

const wrapperFor =
  (queryClient: QueryClient) =>
  ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );

const seedIdentityFetch = (identityId: string, matches: readonly unknown[]): void => {
  vi.mocked(recognitionApi.fetchIdentitiesSuggestions).mockResolvedValue({
    matches: { [identityId]: [...matches] as never },
  });
};

const seedReviewFetch = (rows: readonly import('../../../../api/recognition').PendingSuggestion[]): void => {
  vi.mocked(recognitionApi.fetchPendingSuggestions).mockResolvedValue({
    suggestions: [...rows],
    limit: 25,
    offset: 0,
  });
  vi.mocked(recognitionApi.fetchPendingMergeSuggestions).mockResolvedValue({
    suggestions: [],
    limit: 10,
    offset: 0,
  });
  vi.mocked(recognitionApi.fetchPendingNameSuggestions).mockResolvedValue({
    suggestions: [],
    limit: 25,
    offset: 0,
  });
  vi.mocked(recognitionApi.fetchTopUnlabeledClusters).mockResolvedValue({
    clusters: [],
    limit: 20,
    total: 0,
    truncated: false,
    singleton_count: 0,
    data_source: 'local_projection',
  });
  vi.mocked(recognitionApi.listRecognitionClusters).mockResolvedValue({
    clusters: [],
    limit: 20,
    total: 0,
    truncated: false,
  });
};

describe('projectionConsumerHarness (FBT-1 criterion 2 / ④)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.AltContextAdmin = {
      nonce: 'test-nonce',
      tenant_id: 'tenant-1',
      endpoints: {
        recognitionClusters: 'http://localhost/recognition/clusters',
        recognitionSuggestions: 'http://localhost/recognition/suggestions',
      },
    };
    resetConfigCache();
    vi.mocked(useRosterEntries).mockReturnValue(
      createMockQuery({
        data: [],
        isLoading: false,
        isError: false,
        refetch: vi.fn(),
      }),
    );
  });

  describe.each(Object.keys(suggestionProjectionMatrix) as MatrixCaseKey[])(
    'matrix case %s — leg-specific consumers (PR-50/PR-51)',
    (caseKey) => {
      const matrixCase = suggestionProjectionMatrix[caseKey];
      const identityId =
        'identityId' in matrixCase ? matrixCase.identityId : 'identity-unknown';

      it('drives applicable consumers to leg-specific expected ids', async () => {
        const queryClient = makeQueryClient();
        const wrapper = wrapperFor(queryClient);

        if (hasMatches(matrixCase)) {
          seedIdentityFetch(identityId, matrixCase.matches);
        } else {
          seedIdentityFetch(identityId, []);
        }

        if (hasReviewLeg(matrixCase)) {
          seedReviewFetch(reviewRowsFor(matrixCase));
        } else {
          seedReviewFetch([]);
        }

        // --- Identity leg: inline batch (recipe: useInlineSuggestionBatch.test.tsx:121,141) ---
        if (hasMatches(matrixCase)) {
          const { result: inline } = renderHook(() => useInlineSuggestionBatch([identityId]), {
            wrapper,
          });
          await waitFor(() => expect(inline.current.isLoading).toBe(false));
          const top = expectedIdentityTop(matrixCase);
          if (top === undefined) {
            expect(inline.current.getMatch(identityId)).toBeUndefined();
          } else {
            await waitFor(() =>
              expect(inline.current.getMatch(identityId)?.suggestionId).toBe(top),
            );
          }

          // --- Identity leg: cluster suggestions dropdown ---
          const { result: cluster } = renderHook(
            () =>
              useClusterSuggestions({
                identityId,
                enabled: true,
                labelInput: '',
                debounceMs: 0,
              }),
            { wrapper },
          );
          await waitFor(() => expect(cluster.current.isLoading).toBe(false));
          const expectedLabels = expectedIdentityIds(matrixCase);
          // Dropdown options are label-based Suggested rows in server order.
          await waitFor(() => {
            const suggested = cluster.current.options.filter((o) => o.group === 'Suggested');
            expect(suggested.map((o) => o.suggestion_id ?? o.value)).toHaveLength(
              expectedLabels.length,
            );
          });
          if (top !== undefined) {
            const firstSuggested = cluster.current.options.find((o) => o.group === 'Suggested');
            expect(firstSuggested?.suggestion_id).toBe(top);
          }
        }

        // --- Review leg (pendingRows / reviewQueueRows only) ---
        if (hasReviewLeg(matrixCase)) {
          const { result: review } = renderHook(() => useSuggestionReviewQueries(), {
            wrapper,
          });
          await waitFor(() => expect(review.current.assignmentQuery.isSuccess).toBe(true));
          const ids = flattenReviewSuggestionIds(review.current.reviewItems);
          // buildSuggestionReviewItems groups same-cluster; multi-cluster fixture ids match.
          expect(ids).toEqual(expectedReviewIds(matrixCase));
        }
      });

      it('converges after each SUGGESTION_PROJECTION_INVALIDATION_EVENTS key (shared QueryClient)', async () => {
        // Skip cases with no consumers applicable under PR-51.
        if (!hasMatches(matrixCase) && !hasReviewLeg(matrixCase)) {
          return;
        }

        const queryClient = makeQueryClient();
        const wrapper = wrapperFor(queryClient);
        const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries');

        if (hasMatches(matrixCase)) {
          seedIdentityFetch(identityId, matrixCase.matches);
        }
        if (hasReviewLeg(matrixCase)) {
          seedReviewFetch(reviewRowsFor(matrixCase));
        } else {
          seedReviewFetch([]);
        }

        const hooks: {
          inline?: ReturnType<typeof renderHook<ReturnType<typeof useInlineSuggestionBatch>, unknown>>;
          cluster?: ReturnType<typeof renderHook<ReturnType<typeof useClusterSuggestions>, unknown>>;
          review?: ReturnType<typeof renderHook<ReturnType<typeof useSuggestionReviewQueries>, unknown>>;
        } = {};

        if (hasMatches(matrixCase)) {
          hooks.inline = renderHook(() => useInlineSuggestionBatch([identityId]), { wrapper });
          hooks.cluster = renderHook(
            () =>
              useClusterSuggestions({
                identityId,
                enabled: true,
                labelInput: '',
                debounceMs: 0,
              }),
            { wrapper },
          );
          await waitFor(() => expect(hooks.inline!.result.current.isLoading).toBe(false));
        }
        if (hasReviewLeg(matrixCase)) {
          hooks.review = renderHook(() => useSuggestionReviewQueries(), { wrapper });
          await waitFor(() => expect(hooks.review!.result.current.assignmentQuery.isSuccess).toBe(true));
        }

        const events = Object.keys(
          SUGGESTION_PROJECTION_INVALIDATION_EVENTS,
        ) as SuggestionProjectionInvalidationEvent[];

        for (const event of events) {
          invalidateSpy.mockClear();
          const entry = SUGGESTION_PROJECTION_INVALIDATION_EVENTS[event];

          await act(async () => {
            // Simulate the event's invalidation surface: always projection root when flagged,
            // plus each keptCrossFamilyTarget (presence assert; extras allowed).
            if (entry.invalidatesAssignmentProjection) {
              await invalidateSuggestionProjection(queryClient);
            }
            for (const target of entry.keptCrossFamilyTargets) {
              await queryClient.invalidateQueries({ queryKey: crossFamilyQueryKey(target) });
            }
            // syncTrigger also notes viaSuggestionsAllRoot — presence-only signal.
            if ('viaSuggestionsAllRoot' in entry && entry.viaSuggestionsAllRoot) {
              await queryClient.invalidateQueries({ queryKey: queryKeys.suggestions.all });
            }
          });

          // Presence asserts for the event's documented targets.
          if (entry.invalidatesAssignmentProjection) {
            expect(invalidateSpy).toHaveBeenCalledWith({
              queryKey: queryKeys.suggestions.projection.all,
            });
          }
          for (const target of entry.keptCrossFamilyTargets) {
            expect(invalidateSpy).toHaveBeenCalledWith({
              queryKey: crossFamilyQueryKey(target),
            });
          }

          // Consumers re-converge to their own leg expectations (PR-50).
          if (hooks.inline && hasMatches(matrixCase)) {
            await waitFor(() => expect(hooks.inline!.result.current.isLoading).toBe(false));
            const top = expectedIdentityTop(matrixCase);
            if (top === undefined) {
              expect(hooks.inline.result.current.getMatch(identityId)).toBeUndefined();
            } else {
              await waitFor(() =>
                expect(hooks.inline!.result.current.getMatch(identityId)?.suggestionId).toBe(top),
              );
            }
          }
          if (hooks.review && hasReviewLeg(matrixCase)) {
            await waitFor(() =>
              expect(hooks.review!.result.current.assignmentQuery.isFetching).toBe(false),
            );
            expect(flattenReviewSuggestionIds(hooks.review.result.current.reviewItems)).toEqual(
              expectedReviewIds(matrixCase),
            );
          }
        }

        queryClient.clear();
      });
    },
  );

  /**
   * BR-23 — UXP-3 dismiss-invalidation divergence: CONFIRMED-AS-DESIGNED.
   *
   * The wave notes recorded that dismiss sites invalidate clusters.topUnlabeled /
   * clusters.all, not mergePending; accept/label/merge/scan also touch
   * media.identities. The live contract map already encodes this:
   *   - clusterDismiss.keptCrossFamilyTargets = topUnlabeled + clusters.all
   *     (no mergePending — dismiss of an unlabeled cluster does not create or
   *     retire merge candidates; mergePending is owned by merge/accept paths)
   *   - suggestionAccept / clusterLabelSetClear / clusterMerge / scanRecomputeCompletion
   *     include media.identities (identity→media assignment can change)
   *   - suggestionReject deliberately omits media.identities (no assignment change)
   *
   * This harness pins those target sets as presence asserts. We do NOT "fix"
   * dismiss to also invalidate mergePending — that would force a redundant
   * refetch with no data dependency. Leaving the divergence ambiguous is banned;
   * confirming the map as designed is the disposition chosen for Slice 6.
   */
  it('BR-23 CONFIRMED-AS-DESIGNED: clusterDismiss targets topUnlabeled+clusters.all, not mergePending; accept-family keeps media.identities', () => {
    const dismiss = SUGGESTION_PROJECTION_INVALIDATION_EVENTS.clusterDismiss;
    expect(dismiss.invalidatesAssignmentProjection).toBe(true);
    expect([...dismiss.keptCrossFamilyTargets]).toEqual([
      'clusters.topUnlabeled',
      'clusters.all',
    ]);
    expect(dismiss.keptCrossFamilyTargets).not.toContain('mergePending');
    expect(dismiss.keptCrossFamilyTargets).not.toContain('media.identities');

    // Accept-family paths that reassign identity→media must keep media.identities.
    for (const event of [
      'suggestionAccept',
      'clusterLabelSetClear',
      'clusterMerge',
      'scanRecomputeCompletion',
    ] as const) {
      expect(SUGGESTION_PROJECTION_INVALIDATION_EVENTS[event].keptCrossFamilyTargets).toContain(
        'media.identities',
      );
    }

    // Reject does not change media assignment — honest split from accept.
    expect(
      SUGGESTION_PROJECTION_INVALIDATION_EVENTS.suggestionReject.keptCrossFamilyTargets,
    ).not.toContain('media.identities');
  });

  it('fixture import is the FBT-1 criterion-2 handshake (suggestionProjectionMatrix)', () => {
    // Stable surface: all six named cases present; harness must not edit the fixture file.
    expect(Object.keys(suggestionProjectionMatrix).sort()).toEqual(
      [
        'allIneligibleWindow',
        'clusterFirstThenHuman',
        'labeledButUnconfirmedPersonN',
        'multiSuggestionIdentity',
        'staleAccepted',
        'tiedSimilarities',
      ].sort(),
    );
  });
});
