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
 * Invalidation (BR-58): shared QueryClient, per SUGGESTION_PROJECTION_INVALIDATION_EVENTS
 * key — production-code `invalidateSuggestionProjection` only, asserted via
 * per-consumer fetch-mock call-count deltas (no circular self-invalidation of
 * cross-family keys; those target sets are pinned as map data in the BR-23 test).
 *
 * BR-23 (dismiss-invalidation divergence): CONFIRMED-AS-DESIGNED — see named test.
 */

import type { ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { resetConfigCache } from '../../../../api/config';
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
      ajaxUrl: '/wp-admin/admin-ajax.php',
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
          // BR-58: dropdown Suggested rows assert the exact identity-leg id set
          // (server order), not just a row count.
          await waitFor(() => {
            const suggested = cluster.current.options.filter((o) => o.group === 'Suggested');
            expect(suggested.map((o) => o.suggestion_id)).toEqual(
              expectedIdentityIds(matrixCase),
            );
          });
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
          const entry = SUGGESTION_PROJECTION_INVALIDATION_EVENTS[event];
          // Every event in the live map invalidates the assignment projection root.
          expect(entry.invalidatesAssignmentProjection).toBe(true);

          const identityCallsBefore = vi.mocked(recognitionApi.fetchIdentitiesSuggestions).mock
            .calls.length;
          const reviewCallsBefore = vi.mocked(recognitionApi.fetchPendingSuggestions).mock.calls
            .length;
          const mergeCallsBefore = vi.mocked(recognitionApi.fetchPendingMergeSuggestions).mock
            .calls.length;
          const nameCallsBefore = vi.mocked(recognitionApi.fetchPendingNameSuggestions).mock
            .calls.length;

          // BR-58: production-code invalidation ONLY (invalidateSuggestionProjection).
          // No self-invalidation of cross-family keys here — those target sets are
          // pinned as map data in the BR-23 test below; asserting them by firing
          // them ourselves would be circular.
          await act(async () => {
            await invalidateSuggestionProjection(queryClient);
          });

          // Per-consumer fetch-mock deltas: projection-root consumers refetch…
          if (hasMatches(matrixCase)) {
            // Inline batch + cluster dropdown share the identityBatch cache entry
            // (identityBatchIdsKey canon) → exactly one shared refetch.
            await waitFor(() =>
              expect(vi.mocked(recognitionApi.fetchIdentitiesSuggestions).mock.calls.length).toBe(
                identityCallsBefore + 1,
              ),
            );
          } else {
            expect(vi.mocked(recognitionApi.fetchIdentitiesSuggestions).mock.calls.length).toBe(
              identityCallsBefore,
            );
          }
          if (hasReviewLeg(matrixCase)) {
            await waitFor(() =>
              expect(vi.mocked(recognitionApi.fetchPendingSuggestions).mock.calls.length).toBe(
                reviewCallsBefore + 1,
              ),
            );
          } else {
            expect(vi.mocked(recognitionApi.fetchPendingSuggestions).mock.calls.length).toBe(
              reviewCallsBefore,
            );
          }
          // …and non-projection families are untouched by the projection root.
          expect(vi.mocked(recognitionApi.fetchPendingMergeSuggestions).mock.calls.length).toBe(
            mergeCallsBefore,
          );
          expect(vi.mocked(recognitionApi.fetchPendingNameSuggestions).mock.calls.length).toBe(
            nameCallsBefore,
          );

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
          // BR-58: cluster dropdown participates in reconvergence with exact id sets.
          if (hooks.cluster && hasMatches(matrixCase)) {
            await waitFor(() => {
              const suggested = hooks.cluster!.result.current.options.filter(
                (o) => o.group === 'Suggested',
              );
              expect(suggested.map((o) => o.suggestion_id)).toEqual(
                expectedIdentityIds(matrixCase),
              );
            });
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
