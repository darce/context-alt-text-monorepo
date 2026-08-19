import type { ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { resetConfigCache } from '../../../../api/config';
import { queryKeys } from '../../../../api/queryKeys';
import * as recognitionApi from '../../../../api/recognition';
import {
  SUGGESTION_PROJECTION_INVALIDATION_EVENTS,
  type SuggestionProjectionInvalidationEvent,
} from '../suggestionProjection';
import { useClusterMutations } from '../useClusterMutations';
import { useSuggestionReviewMutations } from '../useSuggestionReviewMutations';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  _n: (single: string, plural: string, count: number) => (count === 1 ? single : plural),
  sprintf: (template: string, ...args: (string | number)[]) => {
    let index = 0;
    return template.replace(/%d/g, () => String(args[index++]));
  },
}));

vi.mock('../../../../api/recognition', async () => {
  const actual = await vi.importActual<typeof import('../../../../api/recognition')>('../../../../api/recognition');
  return {
    ...actual,
    acceptSuggestion: vi.fn(),
    rejectSuggestion: vi.fn(),
    bulkAcceptSuggestions: vi.fn(),
    acceptMergeSuggestion: vi.fn(),
    rejectMergeSuggestion: vi.fn(),
    acceptNameSuggestion: vi.fn(),
    rejectNameSuggestion: vi.fn(),
    updateClusterLabel: vi.fn(),
    mergeCluster: vi.fn(),
    revertMergeCluster: vi.fn(),
    dismissCluster: vi.fn(),
    fetchTopUnlabeledClusters: vi.fn(),
    createClusterForIdentity: vi.fn(),
    fetchScanStatus: vi.fn(),
    pinRepresentative: vi.fn(),
    reassignClusterIdentity: vi.fn(),
    splitCluster: vi.fn(),
  };
});

vi.mock('../../../../hooks/useSyncOffline', () => ({
  useSyncOffline: () => false,
}));

/** Resolve a D4 keptCrossFamilyTargets token to the live invalidate/refetch queryKey. */
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

const expectProjectionInvalidated = (invalidateSpy: ReturnType<typeof vi.spyOn>): void => {
  expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: queryKeys.suggestions.projection.all });
};

const expectCrossFamilyPresent = (
  spy: ReturnType<typeof vi.spyOn>,
  event: SuggestionProjectionInvalidationEvent,
  tenantId = 'tenant-1',
): void => {
  const targets = SUGGESTION_PROJECTION_INVALIDATION_EVENTS[event].keptCrossFamilyTargets;
  for (const target of targets) {
    expect(spy).toHaveBeenCalledWith({ queryKey: crossFamilyQueryKey(target, tenantId) });
  }
};

const makeQueryClient = (): QueryClient =>
  new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

const wrapperFor =
  (queryClient: QueryClient) =>
  ({ children }: { children: ReactNode }) => <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;

describe('SUGGESTION_PROJECTION_INVALIDATION_EVENTS per-site wiring', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.AltContextAdmin = {
      nonce: 'test-nonce',
      ajaxUrl: '/wp-admin/admin-ajax.php',
      tenant_id: 'tenant-1',
      endpoints: {
        recognitionClusters: 'http://localhost/recognition/clusters',
      },
    };
    resetConfigCache();
  });

  describe('suggestionAccept', () => {
    it('accept invalidates projection exactly and keeps clusters.all + media.identities', async () => {
      // TEST-06 predicted first failure (pre-sweep / missing accept coverage):
      // "expected invalidateQueries to have been called with { queryKey: ['suggestions','projection'] }"
      // and/or missing media.identities on accept settle.
      const queryClient = makeQueryClient();
      const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries');
      const bulkActionRef = { current: false };

      vi.mocked(recognitionApi.acceptSuggestion).mockResolvedValue({
        suggestion_id: 'sugg-a',
        resolution: 'accepted',
        identity_id: 'identity-a',
        cluster_id: 'cluster-1',
        message: 'ok',
      });

      const { result } = renderHook(() => useSuggestionReviewMutations({ queryClient, bulkActionRef }), {
        wrapper: wrapperFor(queryClient),
      });

      act(() => {
        result.current.mutations.accept.mutate('sugg-a');
      });

      await waitFor(() => {
        expect(recognitionApi.acceptSuggestion).toHaveBeenCalled();
      });

      await waitFor(() => {
        expectProjectionInvalidated(invalidateSpy);
        expectCrossFamilyPresent(invalidateSpy, 'suggestionAccept');
      });
    });
  });

  describe('suggestionReject', () => {
    it('reject invalidates projection and keeps clusters.all (no media.identities by design)', async () => {
      // TEST-06 predicted first failure (pre-split map / missing reject coverage):
      // "expected invalidateQueries to have been called with { queryKey: ['suggestions','projection'] }"
      // if reject's onSettled invalidation were dropped — previously untested.
      const queryClient = makeQueryClient();
      const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries');
      const bulkActionRef = { current: false };

      vi.mocked(recognitionApi.rejectSuggestion).mockResolvedValue({
        suggestion_id: 'sugg-a',
        resolution: 'rejected',
        identity_id: 'identity-a',
        cluster_id: null,
        message: 'ok',
      });

      const { result } = renderHook(() => useSuggestionReviewMutations({ queryClient, bulkActionRef }), {
        wrapper: wrapperFor(queryClient),
      });

      act(() => {
        result.current.mutations.reject.mutate('sugg-a');
      });

      await waitFor(() => {
        expect(recognitionApi.rejectSuggestion).toHaveBeenCalled();
      });

      await waitFor(() => {
        expectProjectionInvalidated(invalidateSpy);
        expectCrossFamilyPresent(invalidateSpy, 'suggestionReject');
      });
    });
  });

  describe('bulkAccept', () => {
    it('bulkAccept invalidates projection exactly and keeps merge/name/clusters cross-family', async () => {
      // TEST-06 predicted first failure (pre-bulk coverage):
      // "expected invalidateQueries to have been called with { queryKey: ['suggestions','projection'] }"
      // or missing mergePending/namePending/clusters.all.
      const queryClient = makeQueryClient();
      const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries');
      const bulkActionRef = { current: false };

      vi.mocked(recognitionApi.bulkAcceptSuggestions).mockResolvedValue({
        accepted_count: 2,
        skipped_count: 0,
      });

      const { result } = renderHook(() => useSuggestionReviewMutations({ queryClient, bulkActionRef }), {
        wrapper: wrapperFor(queryClient),
      });

      act(() => {
        result.current.mutations.bulkAccept.mutate({
          suggestion_type: 'assignment',
          min_confidence: 0.5,
        });
      });

      await waitFor(() => {
        expect(recognitionApi.bulkAcceptSuggestions).toHaveBeenCalled();
      });

      await waitFor(() => {
        expectProjectionInvalidated(invalidateSpy);
        expectCrossFamilyPresent(invalidateSpy, 'bulkAccept');
      });
    });
  });

  describe('clusterLabelSetClear', () => {
    it('rename invalidates projection exactly and keeps useClusterMutations cross-family set', async () => {
      // TEST-06 predicted first failure (still targeting suggestions.pending):
      // "expected invalidateQueries to have been called with { queryKey: ['suggestions','projection'] }"
      // (received pending key) — plus mergePending/clusters.labels/media.identities must stay present.
      const queryClient = makeQueryClient();
      const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries');

      vi.mocked(recognitionApi.updateClusterLabel).mockResolvedValue(undefined);

      const { result } = renderHook(
        () =>
          useClusterMutations({
            clusterId: 'cluster-label-1',
            currentLabel: null,
            derivedLabel: null,
          }),
        { wrapper: wrapperFor(queryClient) },
      );

      act(() => {
        result.current.rename('Alice');
      });

      await waitFor(() => {
        expect(recognitionApi.updateClusterLabel).toHaveBeenCalled();
      });

      await waitFor(() => {
        expectProjectionInvalidated(invalidateSpy);
        expectCrossFamilyPresent(invalidateSpy, 'clusterLabelSetClear');
      });
    });

    it('successful Library rename invalidates roster.entries (UXW2-3-R1-02)', async () => {
      // Presence assert matching ClusterLabelingPanel / PersonCommitControl:
      // after a Library write-through rename, roster.entries() must be invalidated
      // so the queue-card matcher sees the new person within staleTime.
      const queryClient = makeQueryClient();
      const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries');

      vi.mocked(recognitionApi.updateClusterLabel).mockResolvedValue(undefined);

      const { result } = renderHook(
        () =>
          useClusterMutations({
            clusterId: 'cluster-label-1',
            currentLabel: null,
            derivedLabel: null,
          }),
        { wrapper: wrapperFor(queryClient) },
      );

      act(() => {
        result.current.rename('Alice');
      });

      await waitFor(() => {
        expect(recognitionApi.updateClusterLabel).toHaveBeenCalled();
      });

      await waitFor(() => {
        expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: queryKeys.roster.entries() });
      });
    });
  });

  describe('clusterMerge', () => {
    it('merge invalidates projection exactly and keeps useClusterMutations cross-family set', async () => {
      // TEST-06 predicted first failure (still targeting suggestions.pending):
      // "expected invalidateQueries to have been called with { queryKey: ['suggestions','projection'] }"
      // (received pending key) while mergePending/clusters.* must remain.
      const queryClient = makeQueryClient();
      const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries');

      vi.mocked(recognitionApi.mergeCluster).mockResolvedValue({
        source_id: 'cluster-source',
        source_label: null,
        target_id: 'cluster-target',
        target_label: 'Alice',
        identities_moved: 1,
        moved_identity_ids: ['id-1'],
        target_identity_count: 4,
      });

      const { result } = renderHook(
        () =>
          useClusterMutations({
            clusterId: 'cluster-source',
            currentLabel: null,
            derivedLabel: null,
          }),
        { wrapper: wrapperFor(queryClient) },
      );

      act(() => {
        result.current.merge('cluster-target', 'Alice');
      });

      await waitFor(() => {
        expect(recognitionApi.mergeCluster).toHaveBeenCalled();
      });

      await waitFor(() => {
        expectProjectionInvalidated(invalidateSpy);
        expectCrossFamilyPresent(invalidateSpy, 'clusterMerge');
      });
    });
  });

  describe('clusterDismiss', () => {
    it('map requires topUnlabeled + clusters.all (live card site retired with TopClustersSection)', () => {
      // D4 contract preserved for Slice 3 skip/dismiss wiring; production site
      // was TopClustersSection (deleted BR-12). Assert the map entry only.
      expect(SUGGESTION_PROJECTION_INVALIDATION_EVENTS.clusterDismiss.invalidatesAssignmentProjection).toBe(
        true,
      );
      expect(SUGGESTION_PROJECTION_INVALIDATION_EVENTS.clusterDismiss.keptCrossFamilyTargets).toEqual([
        'clusters.topUnlabeled',
        'clusters.all',
      ]);
    });
  });

  describe('event map coverage guard', () => {
    it('enumerates the eight D4 events so missing suite keys fail loud', () => {
      // TEST-06 predicted first failure if a map key is dropped without a suite:
      // "expected […8 keys] to equal […]" length / membership mismatch.
      expect(Object.keys(SUGGESTION_PROJECTION_INVALIDATION_EVENTS).sort()).toEqual(
        [
          'bulkAccept',
          'clusterDismiss',
          'clusterLabelSetClear',
          'clusterMerge',
          'scanRecomputeCompletion',
          'suggestionAccept',
          'suggestionReject',
          'syncTrigger',
        ].sort(),
      );
    });
  });
});
