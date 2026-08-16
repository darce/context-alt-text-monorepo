/**
 * L1R-02 / BR-23: assignment queryFn must use projectReviewQueue (adapt+filter+sort).
 * Reverting to `response.suggestions.map(fromPendingRow)` leaves reviewItems green
 * (buildSuggestionReviewItems re-filters) but fails these raw-item assertions.
 */

import type { ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { resetConfigCache } from '../../../../api/config';
import * as recognitionApi from '../../../../api/recognition';
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

const createWrapper = () => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  return { wrapper, queryClient };
};

describe('useSuggestionReviewQueries queryFn (BR-23 / L1R-02)', () => {
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

    const { wrapper } = createWrapper();
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

    const { wrapper } = createWrapper();
    const { result } = renderHook(() => useSuggestionReviewQueries(), { wrapper });

    await waitFor(() => expect(result.current.topUnlabeledQuery.isSuccess).toBe(true));
    expect(result.current.topUnlabeledTruncated).toBe(true);
  });
});
