/**
 * L1R-02 / BR-23: assignment queryFn must use projectReviewQueue (adapt+filter+sort).
 * Reverting to `response.suggestions.map(fromPendingRow)` leaves reviewItems green
 * (buildSuggestionReviewItems re-filters) but fails these raw-item assertions.
 */

import { onlineManager, type QueryClient } from '@tanstack/react-query';
import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { resetConfigCache } from '../../../../api/config';
import { queryKeys } from '../../../../api/queryKeys';
import * as recognitionApi from '../../../../api/recognition';
import { buildTestQueryClient, createQueryWrapper } from '../../../../test-utils/queryClient';
import { createAppQueryClient } from '../../../../utils/appQueryClient';
import { AuthExpiredError, HTTPError } from '../../../../utils/http';
import { useSuggestionReviewQueries } from '../useSuggestionReviewQueries';
import { buildPendingRow } from './suggestionProjection.fixtures';

vi.mock('../../../../api/recognition', async () => {
  const actual = await vi.importActual<typeof import('../../../../api/recognition')>(
    '../../../../api/recognition',
  );
  return {
    ...actual,
    fetchPendingSuggestions: vi.fn(),
    fetchPendingMergeSuggestions: vi.fn(),
    fetchPendingNameSuggestions: vi.fn(),
    fetchTopUnlabeledClusters: vi.fn(),
  };
});

describe('useSuggestionReviewQueries queryFn (BR-23 / L1R-02)', () => {
  let queryClient: ReturnType<typeof buildTestQueryClient>;
  let wrapper: ReturnType<typeof createQueryWrapper>;

  beforeEach(() => {
    queryClient = buildTestQueryClient();
    wrapper = createQueryWrapper(queryClient);
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
  });

  afterEach(() => {
    queryClient.clear();
  });

  it('assignmentQuery items are projectReviewQueue output (filter + sort), not raw fromPendingRow', async () => {
    // Predicted first failure if queryFn reverts to map(fromPendingRow):
    // - machine-label row 'auto' would remain in assignmentSuggestions
    // - order would stay arrival order [low, auto, high] instead of similarity [high, low]
    vi.mocked(recognitionApi.fetchPendingSuggestions).mockResolvedValue({
      suggestions: [
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
      ],
      limit: 25,
      offset: 0,
      data_source: 'local_projection',
    });

    const { result } = renderHook(() => useSuggestionReviewQueries(), { wrapper });

    await waitFor(() => expect(result.current.assignmentQuery.isSuccess).toBe(true));

    // Assert raw queryFn output (assignmentSuggestions), not reviewItems (which re-filters).
    expect(result.current.assignmentSuggestions?.map((s) => s.suggestionId)).toEqual([
      'high',
      'low',
    ]);
    expect(
      result.current.assignmentSuggestions?.some((s) => s.suggestionId === 'auto'),
    ).toBe(false);
  });

  // REV2-04 / TEST-15: truncated must leave the queries hook. Dropping the
  // field keeps repair copy unqualified even when the page is partial.
  it('REV2-04: surfaces topUnlabeledTruncated from the envelope', async () => {
    vi.mocked(recognitionApi.fetchPendingSuggestions).mockResolvedValue({
      suggestions: [],
      limit: 25,
      offset: 0,
      data_source: 'local_projection',
    });
    vi.mocked(recognitionApi.fetchTopUnlabeledClusters).mockResolvedValue({
      clusters: [],
      limit: 20,
      total: 42,
      truncated: true,
      singleton_count: 0,
      data_source: 'local_projection',
    });

    const { result } = renderHook(() => useSuggestionReviewQueries(), { wrapper });

    await waitFor(() => expect(result.current.topUnlabeledQuery.isSuccess).toBe(true));
    expect(result.current.topUnlabeledTruncated).toBe(true);
  });

  describe('topUnlabeledQuery retry (UXREC-1-DEMO-02)', () => {
    const topUnlabeledKey = queryKeys.clusters.topUnlabeled('tenant-1');
    let appClient: QueryClient;

    // Production QueryClient (App.tsx) with only the delay zeroed: the retry
    // predicate is the real openCooldownFromError + shouldRetryRequest.
    beforeEach(() => {
      appClient = createAppQueryClient();
      appClient.setDefaultOptions({
        queries: { ...appClient.getDefaultOptions().queries, retryDelay: 0 },
      });
      vi.mocked(recognitionApi.fetchPendingSuggestions).mockResolvedValue({
        suggestions: [],
        limit: 25,
        offset: 0,
        data_source: 'local_projection',
      });
    });

    afterEach(() => {
      onlineManager.setOnline(true);
      appClient.clear();
    });

    const renderWithAppDefaults = () =>
      renderHook(() => useSuggestionReviewQueries(), { wrapper: createQueryWrapper(appClient) });

    // REF-19: re-adding `retry: false` (or a local predicate) to the query
    // replaces the shared default and skips the cooldown seam; this pins it out.
    it('carries no retry override, so the app QueryClient default applies', async () => {
      const { result } = renderWithAppDefaults();

      await waitFor(() => expect(result.current.topUnlabeledQuery.isSuccess).toBe(true));
      const defaultRetry = appClient.getDefaultOptions().queries?.retry;
      expect(typeof defaultRetry).toBe('function');
      expect(appClient.getQueryCache().find({ queryKey: topUnlabeledKey })?.options.retry).toBe(
        defaultRetry,
      );
    });

    it('retries a timeout exactly once before surfacing isError', async () => {
      vi.mocked(recognitionApi.fetchTopUnlabeledClusters).mockRejectedValue(
        new DOMException('The operation timed out.', 'TimeoutError'),
      );

      const { result } = renderWithAppDefaults();

      await waitFor(() => expect(result.current.topUnlabeledQuery.isError).toBe(true));
      expect(recognitionApi.fetchTopUnlabeledClusters).toHaveBeenCalledTimes(2);
    });

    // Compatibility guard, not UXREC-1-DEMO-02 fix proof (TEST-15): the base's
    // per-query `retry: false` satisfies it too. The DEMO-02 retry proofs are the
    // override and timeout cases above, which the base fails (one call only).
    it('guard (E21-14, green at base): a plain 500 is still never re-fired', async () => {
      vi.mocked(recognitionApi.fetchTopUnlabeledClusters).mockRejectedValue(
        new HTTPError({
          status: 500,
          retryAfterSeconds: undefined,
          endpoint: '/acx/v1/recognition/clusters/top-unlabeled',
          bodyPreview: 'acx_projection_query_failed',
          message: 'projection query failed',
        }),
      );

      const { result } = renderWithAppDefaults();

      await waitFor(() => expect(result.current.topUnlabeledQuery.isError).toBe(true));
      expect(recognitionApi.fetchTopUnlabeledClusters).toHaveBeenCalledTimes(1);
    });

    // PERC-07: one transient blip recovers silently — the query never enters
    // the error state, so the queue never raises its role=alert for it.
    it('recovers from a single timeout without ever entering the error state', async () => {
      vi.mocked(recognitionApi.fetchTopUnlabeledClusters).mockRejectedValueOnce(
        new DOMException('The operation timed out.', 'TimeoutError'),
      );

      const { result } = renderWithAppDefaults();

      await waitFor(() => expect(result.current.topUnlabeledQuery.isSuccess).toBe(true));
      expect(recognitionApi.fetchTopUnlabeledClusters).toHaveBeenCalledTimes(2);
      expect(appClient.getQueryState(topUnlabeledKey)?.errorUpdateCount).toBe(0);
    });

    // TEST-15: removing the outage hold must fail the pending assertions, even
    // though RQ's raw isError/error have already reset to false/null.
    it('holds the top-unlabeled outage and error class through refetch failure and clears it on success', async () => {
      const authError = new AuthExpiredError({
        endpoint: '/acx/v1/recognition/clusters/top-unlabeled',
        status: 403,
      });
      const outage = new HTTPError({
        status: 500,
        retryAfterSeconds: undefined,
        endpoint: '/acx/v1/recognition/clusters/top-unlabeled',
        bodyPreview: 'acx_projection_query_failed',
        message: 'projection query failed',
      });
      const topMock = vi.mocked(recognitionApi.fetchTopUnlabeledClusters);
      topMock.mockRejectedValueOnce(authError);

      const { result } = renderWithAppDefaults();

      await waitFor(() => expect(result.current.topUnlabeledQuery.isError).toBe(true));
      expect(result.current.topUnlabeledOutage).toEqual({
        isError: true,
        isRetrying: false,
        error: authError,
      });

      let rejectRefetch!: (reason: unknown) => void;
      topMock.mockImplementationOnce(
        () => new Promise((_resolve, reject) => { rejectRefetch = reject; }),
      );
      act(() => { void result.current.topUnlabeledQuery.refetch(); });

      await waitFor(() => expect(result.current.topUnlabeledQuery.isFetching).toBe(true));
      expect(result.current.topUnlabeledQuery.data).toBeUndefined();
      expect(result.current.topUnlabeledQuery.isError).toBe(false);
      expect(result.current.topUnlabeledQuery.error).toBeNull();
      expect(result.current.topUnlabeledQuery.errorUpdateCount).toBe(1);
      expect(result.current.topUnlabeledOutage).toEqual({
        isError: true,
        isRetrying: true,
        error: authError,
      });

      await act(async () => { rejectRefetch(outage); });

      await waitFor(() => expect(result.current.topUnlabeledQuery.isFetching).toBe(false));
      expect(result.current.topUnlabeledOutage).toEqual({
        isError: true,
        isRetrying: false,
        error: outage,
      });

      type TopUnlabeledPage = Awaited<ReturnType<typeof recognitionApi.fetchTopUnlabeledClusters>>;
      let resolveRefetch!: (page: TopUnlabeledPage) => void;
      topMock.mockImplementationOnce(
        () => new Promise((resolve) => { resolveRefetch = resolve; }),
      );
      // Cache-driven/background refetches need the same hold as the Retry control.
      act(() => { void appClient.refetchQueries({ queryKey: topUnlabeledKey }); });

      await waitFor(() => expect(result.current.topUnlabeledQuery.isFetching).toBe(true));
      expect(result.current.topUnlabeledQuery.isError).toBe(false);
      expect(result.current.topUnlabeledQuery.error).toBeNull();
      expect(result.current.topUnlabeledQuery.errorUpdateCount).toBe(2);
      expect(result.current.topUnlabeledOutage).toEqual({
        isError: true,
        isRetrying: true,
        error: outage,
      });

      const page: TopUnlabeledPage = {
        clusters: [],
        limit: 20,
        total: 0,
        truncated: false,
        singleton_count: 0,
        data_source: 'local_projection',
      };
      await act(async () => { resolveRefetch(page); });

      await waitFor(() => expect(result.current.topUnlabeledQuery.isSuccess).toBe(true));
      expect(result.current.topUnlabeledOutage).toEqual({
        isError: false,
        isRetrying: false,
        error: null,
      });
      expect(topMock).toHaveBeenCalledTimes(3);
    });

    // UXREC-1-DEMOQ-G1-F1 / RLSE-04 / INT-08: offline (networkMode 'online')
    // parks the refetch at fetchStatus 'paused' after RQ has reset the
    // never-loaded query to pending/null. The outage and its exact error must
    // hold through it, but nothing is in flight, so it is not "retrying".
    it('holds the outage and latched error through an offline-paused refetch, not busy, until reconnect succeeds', async () => {
      const outage = new HTTPError({
        status: 500,
        retryAfterSeconds: undefined,
        endpoint: '/acx/v1/recognition/clusters/top-unlabeled',
        bodyPreview: 'acx_projection_query_failed',
        message: 'projection query failed',
      });
      const topMock = vi.mocked(recognitionApi.fetchTopUnlabeledClusters);
      topMock.mockRejectedValueOnce(outage);

      const { result } = renderWithAppDefaults();

      await waitFor(() => expect(result.current.topUnlabeledQuery.isError).toBe(true));
      expect(result.current.topUnlabeledOutage).toEqual({
        isError: true,
        isRetrying: false,
        error: outage,
      });

      act(() => { onlineManager.setOnline(false); });
      // The paused promise only settles on reconnect; do not await it.
      act(() => { void result.current.topUnlabeledQuery.refetch(); });

      await waitFor(() => expect(result.current.topUnlabeledQuery.isPaused).toBe(true));
      // RQ's raw state has already dropped the outage — the gap the hold covers.
      expect(result.current.topUnlabeledQuery.isFetching).toBe(false);
      expect(result.current.topUnlabeledQuery.isError).toBe(false);
      expect(result.current.topUnlabeledQuery.error).toBeNull();
      expect(result.current.topUnlabeledQuery.data).toBeUndefined();
      expect(result.current.topUnlabeledQuery.errorUpdateCount).toBe(1);
      expect(result.current.topUnlabeledOutage.isError).toBe(true);
      expect(result.current.topUnlabeledOutage.isRetrying).toBe(false);
      expect(result.current.topUnlabeledOutage.error).toBe(outage);
      expect(topMock).toHaveBeenCalledTimes(1);

      topMock.mockResolvedValueOnce({
        clusters: [],
        limit: 20,
        total: 0,
        truncated: false,
        singleton_count: 0,
        data_source: 'local_projection',
      });
      act(() => { onlineManager.setOnline(true); });

      await waitFor(() => expect(result.current.topUnlabeledQuery.isSuccess).toBe(true));
      // Reconnect ran the parked request for real; success is the only release.
      expect(topMock).toHaveBeenCalledTimes(2);
      expect(result.current.topUnlabeledOutage).toEqual({
        isError: false,
        isRetrying: false,
        error: null,
      });
    });

    it('keeps the first automatic retry silent while its response is pending', async () => {
      type TopUnlabeledPage = Awaited<ReturnType<typeof recognitionApi.fetchTopUnlabeledClusters>>;
      let resolveRetry!: (page: TopUnlabeledPage) => void;
      const topMock = vi.mocked(recognitionApi.fetchTopUnlabeledClusters);
      topMock
        .mockRejectedValueOnce(new DOMException('The operation timed out.', 'TimeoutError'))
        .mockImplementationOnce(
          () => new Promise((resolve) => { resolveRetry = resolve; }),
        );

      const { result } = renderWithAppDefaults();

      await waitFor(() => expect(topMock).toHaveBeenCalledTimes(2));
      expect(result.current.topUnlabeledQuery.isFetching).toBe(true);
      expect(result.current.topUnlabeledQuery.errorUpdateCount).toBe(0);
      expect(result.current.topUnlabeledOutage).toEqual({
        isError: false,
        isRetrying: false,
        error: null,
      });

      await act(async () => {
        resolveRetry({
          clusters: [],
          limit: 20,
          total: 0,
          truncated: false,
          singleton_count: 0,
          data_source: 'local_projection',
        });
      });

      await waitFor(() => expect(result.current.topUnlabeledQuery.isSuccess).toBe(true));
      expect(result.current.topUnlabeledOutage.isError).toBe(false);
    });
  });
});
