import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  acceptNameSuggestion,
  acceptSuggestion,
  bulkAcceptSuggestions,
  dismissCluster,
  fetchPendingMergeSuggestions,
  fetchPendingNameSuggestions,
  fetchPendingSuggestions,
  fetchTopUnlabeledClusters,
  mergeCluster,
  rejectNameSuggestion,
  rejectSuggestion,
  updateClusterLabel,
} from '../../../../api/recognition';
import { DATA_SOURCE } from '../../../../api/recognition/types';
import { resetConfigCache } from '../../../../api/config';
import { queryKeys } from '../../../../api/queryKeys';
import { SuggestionReviewPanel } from '../SuggestionReviewPanel';
import type { PendingSuggestionsResponse } from '../../../../api/recognition/types';
import type { TopUnlabeledCluster, TopUnlabeledClustersResponse } from '../../../../api/recognition/types';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  _n: (single: string, plural: string, number: number) => (number === 1 ? single : plural),
  sprintf: (text: string) => text,
}));

// Radix Avatar's Image uses Image.onload which never fires in JSDOM.
// Render plain elements so test selectors can find the <img>.
vi.mock('@radix-ui/react-avatar', async () => {
  const React = await import('react');
  return {
    Root: React.forwardRef(function MockRoot({ children, ...props }: Record<string, unknown>, ref: unknown) {
      return React.createElement(
        'span',
        { ...props, ref } as React.HTMLAttributes<HTMLSpanElement>,
        children as React.ReactNode,
      );
    }),
    Image: React.forwardRef(function MockImage(props: Record<string, unknown>, ref: unknown) {
      return React.createElement('img', { ...props, ref } as React.ImgHTMLAttributes<HTMLImageElement>);
    }),
    Fallback: React.forwardRef(function MockFallback() {
      return null;
    }),
  };
});

vi.mock('../../../../api/recognition', async () => {
  const actual = await vi.importActual<typeof import('../../../../api/recognition')>('../../../../api/recognition');
  return {
    ...actual,
    fetchPendingSuggestions: vi.fn(),
    fetchPendingMergeSuggestions: vi.fn(),
    fetchPendingNameSuggestions: vi.fn(),
    acceptSuggestion: vi.fn(),
    acceptMergeSuggestion: vi.fn(),
    acceptNameSuggestion: vi.fn(),
    rejectSuggestion: vi.fn(),
    rejectMergeSuggestion: vi.fn(),
    rejectNameSuggestion: vi.fn(),
    bulkAcceptSuggestions: vi.fn(),
    fetchTopUnlabeledClusters: vi.fn(),
    dismissCluster: vi.fn().mockResolvedValue(undefined),
    mergeCluster: vi.fn().mockResolvedValue(undefined),
    updateClusterLabel: vi.fn().mockResolvedValue(undefined),
  };
});

const renderPanel = () => {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        retryDelay: 0,
      },
    },
  });

  const utils = render(
    <QueryClientProvider client={queryClient}>
      <SuggestionReviewPanel />
    </QueryClientProvider>,
  );

  return { queryClient, ...utils };
};

const topUnlabeledResponse = (clusters: TopUnlabeledCluster[], singletonCount = 0): TopUnlabeledClustersResponse => ({
  clusters,
  limit: 20,
  total: clusters.length,
  truncated: false,
  singleton_count: singletonCount,
  data_source: DATA_SOURCE.LOCAL_PROJECTION,
});

describe('SuggestionReviewPanel', () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  beforeEach(() => {
    const fetchTopUnlabeledClustersMock = vi.mocked(fetchTopUnlabeledClusters);

    window.AltContextAdmin = {
      nonce: 'test-nonce',
      endpoints: {
        recognitionSuggestions: 'http://localhost/recognition/suggestions',
        recognitionMergeSuggestions: 'http://localhost/recognition/suggestions/merge',
        recognitionNameSuggestions: 'http://localhost/recognition/suggestions/name',
        recognitionBulkAcceptSuggestions: 'http://localhost/recognition/suggestions/bulk-accept',
        recognitionClusters: 'http://localhost/recognition/clusters',
      },
      tenant_id: 'test-tenant-id',
    };

    vi.mocked(fetchPendingNameSuggestions).mockResolvedValue({ suggestions: [], limit: 25, offset: 0 });
    fetchTopUnlabeledClustersMock.mockResolvedValue(topUnlabeledResponse([]));
    resetConfigCache();
  });

  it('hides panel on initial load failure (cold start friendly)', async () => {
    const fetchPendingSuggestionsMock = vi.mocked(fetchPendingSuggestions);
    const fetchPendingMergeSuggestionsMock = vi.mocked(fetchPendingMergeSuggestions);
    fetchPendingSuggestionsMock.mockRejectedValue(new Error('Server error'));
    fetchPendingMergeSuggestionsMock.mockRejectedValue(new Error('Server error'));

    renderPanel();

    await waitFor(
      () => {
        expect(fetchPendingSuggestionsMock).toHaveBeenCalledTimes(1);
        expect(fetchPendingMergeSuggestionsMock).toHaveBeenCalledTimes(1);
      },
      { timeout: 3000 },
    );

    expect(screen.queryByText('Failed to load suggestions.')).not.toBeInTheDocument();
  });

  it('renders unconfigured guidance instead of a false empty state when suggestions are unavailable', async () => {
    vi.mocked(fetchPendingSuggestions).mockResolvedValue({
      suggestions: [],
      limit: 10,
      offset: 0,
      data_source: DATA_SOURCE.UNAVAILABLE,
    });
    vi.mocked(fetchPendingMergeSuggestions).mockResolvedValue({
      suggestions: [],
      limit: 10,
      offset: 0,
      data_source: DATA_SOURCE.UNAVAILABLE,
    });

    renderPanel();

    await waitFor(() => {
      expect(fetchPendingSuggestions).toHaveBeenCalled();
    });

    expect(screen.getByText('Suggestion service not configured')).toBeInTheDocument();
    expect(
      screen.getByText('Check the recognition service connection, then retry loading suggestions.'),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();
    expect(screen.queryByText('No suggestions to review yet.')).not.toBeInTheDocument();
  });

  it('renders endpoint error guidance when the backend returns a server error envelope', async () => {
    vi.mocked(fetchPendingSuggestions).mockResolvedValue({
      suggestions: [],
      limit: 10,
      offset: 0,
      data_source: DATA_SOURCE.ENDPOINT_ERROR,
    });
    vi.mocked(fetchPendingMergeSuggestions).mockResolvedValue({
      suggestions: [],
      limit: 10,
      offset: 0,
      data_source: DATA_SOURCE.ENDPOINT_ERROR,
    });

    renderPanel();

    await waitFor(() => {
      expect(fetchPendingSuggestions).toHaveBeenCalled();
    });

    expect(screen.getByText('Suggestion service error')).toBeInTheDocument();
    expect(
      screen.getByText('The recognition service responded with an error. Retry now or check the service logs.'),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();
    expect(screen.queryByText('No suggestions to review yet.')).not.toBeInTheDocument();
  });

  it('renders assignment zero-pending guidance when clusters exist but no review suggestions are pending', async () => {
    vi.mocked(fetchPendingSuggestions).mockResolvedValue({
      suggestions: [],
      limit: 10,
      offset: 0,
      data_source: DATA_SOURCE.LOCAL_PROJECTION,
    });
    vi.mocked(fetchPendingMergeSuggestions).mockResolvedValue({
      suggestions: [],
      limit: 10,
      offset: 0,
      data_source: DATA_SOURCE.LOCAL_PROJECTION,
    });
    vi.mocked(fetchTopUnlabeledClusters).mockResolvedValue({
      clusters: [],
      limit: 20,
      total: 0,
      truncated: false,
      singleton_count: 0,
      has_clusters: true,
      data_source: DATA_SOURCE.LOCAL_PROJECTION,
    });

    renderPanel();

    await waitFor(() => {
      expect(fetchPendingSuggestions).toHaveBeenCalled();
      expect(fetchTopUnlabeledClusters).toHaveBeenCalled();
    });

    expect(screen.getByText('No assignment suggestions are waiting right now.')).toBeInTheDocument();
    expect(
      screen.getByText('Review the naming queue below or run another scan after new photos arrive.'),
    ).toBeInTheDocument();
    expect(screen.queryByText('No suggestions to review yet.')).not.toBeInTheDocument();
  });

  it('renders an unavailable warning when suggested names cannot be loaded', async () => {
    vi.mocked(fetchPendingSuggestions).mockResolvedValue({
      suggestions: [],
      limit: 10,
      offset: 0,
    });
    vi.mocked(fetchPendingMergeSuggestions).mockResolvedValue({
      suggestions: [],
      limit: 10,
      offset: 0,
    });
    vi.mocked(fetchPendingNameSuggestions).mockResolvedValue({
      suggestions: [],
      limit: 25,
      offset: 0,
      data_source: DATA_SOURCE.UNAVAILABLE,
    });

    renderPanel();

    await waitFor(() => {
      expect(fetchPendingNameSuggestions).toHaveBeenCalled();
    });

    expect(screen.getByText('Suggested names unavailable')).toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: 'Retry' }).length).toBeGreaterThan(0);
  });

  it('renders suggestions and accepts a suggestion', async () => {
    const fetchPendingSuggestionsMock = vi.mocked(fetchPendingSuggestions);
    const fetchPendingMergeSuggestionsMock = vi.mocked(fetchPendingMergeSuggestions);
    const acceptSuggestionMock = vi.mocked(acceptSuggestion);
    const pendingResponse: PendingSuggestionsResponse = {
      suggestions: [
        {
          id: 'sugg-1',
          identity_id: 'identity-1',
          suggested_cluster_id: 'cluster-1',
          representative_similarity: 0.9,
          avg_member_similarity: 0.85,
          cluster_label: 'Alex',
          cluster_identity_count: 3,
        },
      ],
      limit: 10,
      offset: 0,
    };
    fetchPendingSuggestionsMock.mockResolvedValue(pendingResponse);
    fetchPendingMergeSuggestionsMock.mockResolvedValue({
      suggestions: [],
      limit: 10,
      offset: 0,
    });
    acceptSuggestionMock.mockResolvedValue({
      suggestion_id: 'sugg-1',
      resolution: 'accepted',
      identity_id: 'identity-1',
      cluster_id: 'cluster-1',
      message: 'ok',
    });

    const { queryClient } = renderPanel();
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries');

    await waitFor(() => {
      expect(fetchPendingSuggestionsMock).toHaveBeenCalled();
    });

    await screen.findByRole('button', { name: 'Yes' });

    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: 'Yes' }));

    await waitFor(() => {
      expect(acceptSuggestionMock).toHaveBeenCalledWith('sugg-1', expect.anything());
    });

    await waitFor(() => {
      expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: queryKeys.suggestions.pending() });
      expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: queryKeys.media.identities() });
      expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: queryKeys.clusters.all });
    });
  });

  it('groups suggestions by target cluster and accepts only that group with "Yes all"', async () => {
    const fetchPendingSuggestionsMock = vi.mocked(fetchPendingSuggestions);
    const fetchPendingMergeSuggestionsMock = vi.mocked(fetchPendingMergeSuggestions);
    const acceptSuggestionMock = vi.mocked(acceptSuggestion);

    fetchPendingSuggestionsMock.mockResolvedValue({
      suggestions: [
        {
          id: 'sugg-group-1',
          identity_id: 'identity-group-1',
          suggested_cluster_id: 'cluster-maria',
          representative_similarity: 0.68,
          avg_member_similarity: 0.6,
          cluster_label: 'Maria Correonero',
          cluster_identity_count: 13,
        },
        {
          id: 'sugg-group-2',
          identity_id: 'identity-group-2',
          suggested_cluster_id: 'cluster-maria',
          representative_similarity: 0.63,
          avg_member_similarity: 0.57,
          cluster_label: 'Maria Correonero',
          cluster_identity_count: 13,
        },
        {
          id: 'sugg-other-1',
          identity_id: 'identity-other-1',
          suggested_cluster_id: 'cluster-other',
          representative_similarity: 0.92,
          avg_member_similarity: 0.88,
          cluster_label: 'Alex',
          cluster_identity_count: 6,
        },
      ],
      limit: 10,
      offset: 0,
    });
    fetchPendingMergeSuggestionsMock.mockResolvedValue({
      suggestions: [],
      limit: 10,
      offset: 0,
    });
    acceptSuggestionMock.mockImplementation((suggestionId: string) =>
      Promise.resolve({
        suggestion_id: suggestionId,
        resolution: 'accepted',
        identity_id: `identity-for-${suggestionId}`,
        cluster_id: 'cluster-any',
        message: 'ok',
      }),
    );

    const { container } = renderPanel();

    await waitFor(() => {
      expect(fetchPendingSuggestionsMock).toHaveBeenCalled();
    });

    expect(await screen.findByText(/candidates may be/i)).toBeInTheDocument();
    expect(container.querySelector('[data-cluster-id="cluster-maria"]')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Yes all' })).toBeInTheDocument();

    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: 'Yes all' }));

    await waitFor(() => {
      expect(acceptSuggestionMock).toHaveBeenCalledWith('sugg-group-1', expect.anything());
      expect(acceptSuggestionMock).toHaveBeenCalledWith('sugg-group-2', expect.anything());
    });

    expect(acceptSuggestionMock).not.toHaveBeenCalledWith('sugg-other-1', expect.anything());
  });

  it('renders suggestion thumbnails from media urls when bbox data is missing', async () => {
    const fetchPendingSuggestionsMock = vi.mocked(fetchPendingSuggestions);
    const fetchPendingMergeSuggestionsMock = vi.mocked(fetchPendingMergeSuggestions);

    fetchPendingSuggestionsMock.mockResolvedValue({
      suggestions: [
        {
          id: 'sugg-thumb-1',
          identity_id: 'identity-thumb-1',
          suggested_cluster_id: 'cluster-thumb-1',
          representative_similarity: 0.78,
          avg_member_similarity: 0.74,
          cluster_label: 'Laura Sampliner',
          identity_media_url: 'http://example.test/media/candidate.jpg',
          representative_media_url: 'http://example.test/media/representative.jpg',
        },
      ],
      limit: 10,
      offset: 0,
    });
    fetchPendingMergeSuggestionsMock.mockResolvedValue({
      suggestions: [],
      limit: 10,
      offset: 0,
    });

    const { container } = renderPanel();

    await waitFor(() => {
      expect(fetchPendingSuggestionsMock).toHaveBeenCalled();
    });

    const thumbImages = container.querySelectorAll<HTMLImageElement>('.acx-suggestion-card__thumb img');
    expect(thumbImages).toHaveLength(2);
    expect(thumbImages[0]?.getAttribute('src')).toBe('http://example.test/media/candidate.jpg');
    expect(thumbImages[1]?.getAttribute('src')).toBe('http://example.test/media/representative.jpg');
    expect(container.querySelectorAll('.acx-suggestion-card__thumb--placeholder')).toHaveLength(0);
  });

  it('groups suggestions by target cluster and rejects only that group with "No all"', async () => {
    const fetchPendingSuggestionsMock = vi.mocked(fetchPendingSuggestions);
    const fetchPendingMergeSuggestionsMock = vi.mocked(fetchPendingMergeSuggestions);
    const rejectSuggestionMock = vi.mocked(rejectSuggestion);

    fetchPendingSuggestionsMock
      .mockResolvedValueOnce({
        suggestions: [
          {
            id: 'sugg-group-reject-1',
            identity_id: 'identity-group-reject-1',
            suggested_cluster_id: 'cluster-maria',
            representative_similarity: 0.58,
            avg_member_similarity: 0.56,
            cluster_label: 'Maria Correonero',
            cluster_identity_count: 13,
          },
          {
            id: 'sugg-group-reject-2',
            identity_id: 'identity-group-reject-2',
            suggested_cluster_id: 'cluster-maria',
            representative_similarity: 0.53,
            avg_member_similarity: 0.5,
            cluster_label: 'Maria Correonero',
            cluster_identity_count: 13,
          },
          {
            id: 'sugg-group-reject-other',
            identity_id: 'identity-group-reject-other',
            suggested_cluster_id: 'cluster-other',
            representative_similarity: 0.87,
            avg_member_similarity: 0.84,
            cluster_label: 'Alex',
            cluster_identity_count: 7,
          },
        ],
        limit: 10,
        offset: 0,
      })
      .mockResolvedValue({
        suggestions: [
          {
            id: 'sugg-group-reject-other',
            identity_id: 'identity-group-reject-other',
            suggested_cluster_id: 'cluster-other',
            representative_similarity: 0.87,
            avg_member_similarity: 0.84,
            cluster_label: 'Alex',
            cluster_identity_count: 7,
          },
        ],
        limit: 10,
        offset: 0,
      });
    fetchPendingMergeSuggestionsMock.mockResolvedValue({
      suggestions: [],
      limit: 10,
      offset: 0,
    });
    rejectSuggestionMock.mockImplementation((suggestionId: string) =>
      Promise.resolve({
        suggestion_id: suggestionId,
        resolution: 'rejected',
        identity_id: `identity-for-${suggestionId}`,
        cluster_id: null,
        message: 'ok',
      }),
    );

    const { container } = renderPanel();

    await waitFor(() => {
      expect(fetchPendingSuggestionsMock).toHaveBeenCalled();
    });

    const groupedCard = container.querySelector('[data-cluster-id="cluster-maria"]');
    if (!(groupedCard instanceof HTMLElement)) {
      throw new Error('Expected grouped card for cluster-maria');
    }
    expect(within(groupedCard).getByRole('button', { name: 'No all' })).toBeInTheDocument();

    const user = userEvent.setup();
    await user.click(within(groupedCard).getByRole('button', { name: 'No all' }));

    await waitFor(() => {
      expect(rejectSuggestionMock).toHaveBeenCalledWith('sugg-group-reject-1', expect.anything());
      expect(rejectSuggestionMock).toHaveBeenCalledWith('sugg-group-reject-2', expect.anything());
    });

    expect(rejectSuggestionMock).not.toHaveBeenCalledWith('sugg-group-reject-other', expect.anything());
  });

  it('rejects a suggestion and invalidates pending suggestions', async () => {
    const fetchPendingSuggestionsMock = vi.mocked(fetchPendingSuggestions);
    const fetchPendingMergeSuggestionsMock = vi.mocked(fetchPendingMergeSuggestions);
    const rejectSuggestionMock = vi.mocked(rejectSuggestion);
    const pendingResponse: PendingSuggestionsResponse = {
      suggestions: [
        {
          id: 'sugg-2',
          identity_id: 'identity-2',
          suggested_cluster_id: 'cluster-2',
          representative_similarity: 0.8,
          avg_member_similarity: 0.75,
          cluster_label: 'Jordan',
          cluster_identity_count: 5,
        },
      ],
      limit: 10,
      offset: 0,
    };
    fetchPendingSuggestionsMock.mockResolvedValue(pendingResponse);
    fetchPendingMergeSuggestionsMock.mockResolvedValue({
      suggestions: [],
      limit: 10,
      offset: 0,
    });
    rejectSuggestionMock.mockResolvedValue({
      suggestion_id: 'sugg-2',
      resolution: 'rejected',
      identity_id: 'identity-2',
      cluster_id: null,
      message: 'ok',
    });

    const { queryClient } = renderPanel();
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries');

    await waitFor(() => {
      expect(fetchPendingSuggestionsMock).toHaveBeenCalled();
    });

    await screen.findByRole('button', { name: 'No' });

    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: 'No' }));

    await waitFor(() => {
      expect(rejectSuggestionMock).toHaveBeenCalledWith('sugg-2', expect.anything());
    });

    await waitFor(() => {
      expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: queryKeys.suggestions.pending() });
    });
  });

  it('accepting one suggestion card does not trigger batch-wide accepts', async () => {
    const fetchPendingSuggestionsMock = vi.mocked(fetchPendingSuggestions);
    const fetchPendingMergeSuggestionsMock = vi.mocked(fetchPendingMergeSuggestions);
    const acceptSuggestionMock = vi.mocked(acceptSuggestion);
    fetchPendingSuggestionsMock.mockResolvedValue({
      suggestions: [
        {
          id: 'sugg-accept-1',
          identity_id: 'identity-accept-1',
          suggested_cluster_id: 'cluster-accept-1',
          representative_similarity: 0.82,
          avg_member_similarity: 0.8,
          cluster_label: 'Alex One',
          cluster_identity_count: 4,
        },
        {
          id: 'sugg-accept-2',
          identity_id: 'identity-accept-2',
          suggested_cluster_id: 'cluster-accept-2',
          representative_similarity: 0.79,
          avg_member_similarity: 0.75,
          cluster_label: 'Jordan Two',
          cluster_identity_count: 5,
        },
      ],
      limit: 10,
      offset: 0,
    });
    fetchPendingMergeSuggestionsMock.mockResolvedValue({
      suggestions: [],
      limit: 10,
      offset: 0,
    });
    acceptSuggestionMock.mockResolvedValue({
      suggestion_id: 'sugg-accept-1',
      resolution: 'accepted',
      identity_id: 'identity-accept-1',
      cluster_id: 'cluster-accept-1',
      message: 'ok',
    });

    const { container } = renderPanel();

    await waitFor(() => {
      expect(fetchPendingSuggestionsMock).toHaveBeenCalled();
    });

    const cards = container.querySelectorAll('.acx-suggestion-card');
    expect(cards.length).toBe(2);
    const alexCard = cards[0] as HTMLElement;

    const user = userEvent.setup();
    await user.click(within(alexCard).getByRole('button', { name: 'Yes' }));

    await waitFor(() => {
      expect(acceptSuggestionMock).toHaveBeenCalledTimes(1);
      expect(acceptSuggestionMock).toHaveBeenCalledWith('sugg-accept-1', expect.anything());
    });
    expect(acceptSuggestionMock).not.toHaveBeenCalledWith('sugg-accept-2', expect.anything());
    expect(container.querySelectorAll('.acx-suggestion-card').length).toBeGreaterThan(0);
  });

  it('rejecting one suggestion card does not trigger batch-wide rejects', async () => {
    const fetchPendingSuggestionsMock = vi.mocked(fetchPendingSuggestions);
    const fetchPendingMergeSuggestionsMock = vi.mocked(fetchPendingMergeSuggestions);
    const rejectSuggestionMock = vi.mocked(rejectSuggestion);
    fetchPendingSuggestionsMock.mockResolvedValue({
      suggestions: [
        {
          id: 'sugg-reject-1',
          identity_id: 'identity-reject-1',
          suggested_cluster_id: 'cluster-reject-1',
          representative_similarity: 0.67,
          avg_member_similarity: 0.64,
          cluster_label: 'Taylor One',
          cluster_identity_count: 3,
        },
        {
          id: 'sugg-reject-2',
          identity_id: 'identity-reject-2',
          suggested_cluster_id: 'cluster-reject-2',
          representative_similarity: 0.65,
          avg_member_similarity: 0.6,
          cluster_label: 'Casey Two',
          cluster_identity_count: 3,
        },
      ],
      limit: 10,
      offset: 0,
    });
    fetchPendingMergeSuggestionsMock.mockResolvedValue({
      suggestions: [],
      limit: 10,
      offset: 0,
    });
    let resolveReject: ((value: Awaited<ReturnType<typeof rejectSuggestion>>) => void) | null = null;
    const pendingReject = new Promise<Awaited<ReturnType<typeof rejectSuggestion>>>((resolve) => {
      resolveReject = resolve;
    });
    rejectSuggestionMock.mockReturnValue(pendingReject);

    const { container } = renderPanel();

    await waitFor(() => {
      expect(fetchPendingSuggestionsMock).toHaveBeenCalled();
    });

    const cards = container.querySelectorAll('.acx-suggestion-card');
    expect(cards.length).toBe(2);
    const taylorCard = cards[0] as HTMLElement;

    const user = userEvent.setup();
    await user.click(within(taylorCard).getByRole('button', { name: 'No' }));

    await waitFor(() => {
      expect(rejectSuggestionMock).toHaveBeenCalledTimes(1);
      expect(rejectSuggestionMock).toHaveBeenCalledWith('sugg-reject-1', expect.anything());
      expect(screen.getAllByRole('button', { name: 'No' })).toHaveLength(1);
    });
    expect(rejectSuggestionMock).not.toHaveBeenCalledWith('sugg-reject-2', expect.anything());

    await act(async () => {
      resolveReject?.({
        suggestion_id: 'sugg-reject-1',
        resolution: 'rejected',
        identity_id: 'identity-reject-1',
        cluster_id: null,
        message: 'ok',
      });
      await pendingReject;
    });
  });

  // Case removed: "renders face grid when cluster thumbnails are present"
  // as cluster_thumbnails is deprecated and grid rendering was removed in favor of representatives.

  it('renders "Is this {label}?" when a suggested label is present', async () => {
    const fetchPendingSuggestionsMock = vi.mocked(fetchPendingSuggestions);
    const fetchPendingMergeSuggestionsMock = vi.mocked(fetchPendingMergeSuggestions);

    // Suggestion with explicit suggested label (inferred)
    const pendingResponse: PendingSuggestionsResponse = {
      suggestions: [
        {
          id: 'sugg-inferred',
          identity_id: 'identity-inf',
          suggested_cluster_id: 'cluster-inf',
          representative_similarity: 0.92,
          avg_member_similarity: 0.88,
          cluster_label: null, // Unlabeled cluster
          suggested_label: 'Inferred Name',
          suggested_label_source: 'identity',
          cluster_identity_count: 4,
        },
      ],
      limit: 10,
      offset: 0,
    };
    fetchPendingSuggestionsMock.mockResolvedValue(pendingResponse);
    fetchPendingMergeSuggestionsMock.mockResolvedValue({ suggestions: [], limit: 10, offset: 0 });

    renderPanel();

    await waitFor(() => {
      expect(fetchPendingSuggestionsMock).toHaveBeenCalled();
    });

    // Check for specific copy (split across elements, check parts)
    // "Inferred Name" appears in both the face label and the question
    const items = await screen.findAllByText(/Inferred Name/);
    expect(items.length).toBeGreaterThan(0);
    expect(screen.getByText(/Is this/)).toBeInTheDocument();
  });

  it('renders "Name this person" for unlabeled clusters without inference', async () => {
    const fetchPendingSuggestionsMock = vi.mocked(fetchPendingSuggestions);
    const fetchPendingMergeSuggestionsMock = vi.mocked(fetchPendingMergeSuggestions);

    // Suggestion for unlabeled cluster, no inference
    const pendingResponse: PendingSuggestionsResponse = {
      suggestions: [
        {
          id: 'sugg-unknown',
          identity_id: 'identity-unk',
          suggested_cluster_id: 'cluster-unk',
          representative_similarity: 0.95,
          avg_member_similarity: 0.9,
          cluster_label: null,
          suggested_label: null,
          suggested_label_source: 'none',
          cluster_identity_count: 2,
        },
      ],
      limit: 10,
      offset: 0,
    };
    fetchPendingSuggestionsMock.mockResolvedValue(pendingResponse);
    fetchPendingMergeSuggestionsMock.mockResolvedValue({ suggestions: [], limit: 10, offset: 0 });

    renderPanel();

    await waitFor(() => {
      expect(fetchPendingSuggestionsMock).toHaveBeenCalled();
    });

    expect(await screen.findByText('Name this person')).toBeInTheDocument();

    expect(screen.queryByRole('button', { name: 'Yes' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'No' })).not.toBeInTheDocument();

    expect(screen.getByRole('button', { name: 'Name Person' })).toBeInTheDocument();
  });

  it('renders "Review cluster" button', async () => {
    const fetchPendingSuggestionsMock = vi.mocked(fetchPendingSuggestions);
    const fetchPendingMergeSuggestionsMock = vi.mocked(fetchPendingMergeSuggestions);

    // Any suggestion should show "Review cluster"
    const pendingResponse: PendingSuggestionsResponse = {
      suggestions: [
        {
          id: 'sugg-review',
          identity_id: 'identity-rev',
          suggested_cluster_id: 'cluster-rev',
          representative_similarity: 0.9,
          avg_member_similarity: 0.85,
          cluster_label: 'Review Me',
          cluster_identity_count: 5,
        },
      ],
      limit: 10,
      offset: 0,
    };
    fetchPendingSuggestionsMock.mockResolvedValue(pendingResponse);
    fetchPendingMergeSuggestionsMock.mockResolvedValue({ suggestions: [], limit: 10, offset: 0 });

    renderPanel();

    await waitFor(() => {
      expect(fetchPendingSuggestionsMock).toHaveBeenCalled();
    });

    expect(await screen.findByRole('button', { name: 'Review details' })).toBeInTheDocument();
  });

  it('highlights low-confidence suggestions', async () => {
    const fetchPendingSuggestionsMock = vi.mocked(fetchPendingSuggestions);
    const fetchPendingMergeSuggestionsMock = vi.mocked(fetchPendingMergeSuggestions);

    fetchPendingSuggestionsMock.mockResolvedValue({
      suggestions: [
        {
          id: 'sugg-low-confidence',
          identity_id: 'identity-low',
          suggested_cluster_id: 'cluster-low',
          representative_similarity: 0.52,
          avg_member_similarity: 0.5,
          cluster_label: 'Maria Correonero',
          cluster_identity_count: 4,
        },
      ],
      limit: 10,
      offset: 0,
    });
    fetchPendingMergeSuggestionsMock.mockResolvedValue({ suggestions: [], limit: 10, offset: 0 });

    const { container } = renderPanel();

    await waitFor(() => {
      expect(fetchPendingSuggestionsMock).toHaveBeenCalled();
    });

    expect(container.querySelector('.acx-suggestion-card--low-confidence')).toBeInTheDocument();
    expect(await screen.findByText('Low confidence')).toBeInTheDocument();
  });

  it('renders all queues flat without a top-level accordion and keeps bulk accept last', async () => {
    const fetchPendingSuggestionsMock = vi.mocked(fetchPendingSuggestions);
    const fetchPendingMergeSuggestionsMock = vi.mocked(fetchPendingMergeSuggestions);
    const fetchTopUnlabeledClustersMock = vi.mocked(fetchTopUnlabeledClusters);

    fetchPendingSuggestionsMock.mockResolvedValue({
      suggestions: [
        {
          id: 'sugg-flat',
          identity_id: 'identity-flat',
          suggested_cluster_id: 'cluster-flat',
          representative_similarity: 0.9,
          avg_member_similarity: 0.85,
          cluster_label: 'Flat Test',
          cluster_identity_count: 2,
        },
      ],
      limit: 10,
      offset: 0,
    });
    fetchPendingMergeSuggestionsMock.mockResolvedValue({ suggestions: [], limit: 10, offset: 0 });
    fetchTopUnlabeledClustersMock.mockResolvedValue(
      topUnlabeledResponse([
        {
          id: 'top-flat',
          tenant_id: 'test-tenant-id',
          label: null,
          is_labeled: false,
          is_auto_label: false,
          identity_count: 3,
          user_confirmed: false,
          representatives: [],
        },
      ]),
    );

    const { container } = renderPanel();

    await waitFor(() => {
      expect(fetchPendingSuggestionsMock).toHaveBeenCalled();
    });
    expect(await screen.findByText(/Is this/)).toBeInTheDocument();

    // The top-level accordion is retired: the title is a static heading, not a toggle.
    expect(screen.queryByRole('button', { name: /Review Suggestions/i })).not.toBeInTheDocument();
    expect(screen.getByText('Review Suggestions')).toBeInTheDocument();

    // Assignment queue renders before the bulk-accept controls.
    const assignmentQueue = container.querySelector('.acx-suggestion-queue');
    const bulkAccept = container.querySelector('.acx-bulk-accept');
    expect(assignmentQueue).toBeInTheDocument();
    expect(bulkAccept).toBeInTheDocument();
    expect(assignmentQueue!.compareDocumentPosition(bulkAccept!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();

    // The naming queue (top clusters) also renders before bulk accept.
    await screen.findByText('Name These People');
    const namingQueue = container.querySelector('.acx-naming-queue:not(.acx-naming-queue--suggestions)');
    expect(namingQueue).toBeInTheDocument();
    expect(namingQueue!.compareDocumentPosition(bulkAccept!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('renders naming queue alongside suggestions (Unified View)', async () => {
    const fetchPendingSuggestionsMock = vi.mocked(fetchPendingSuggestions);
    const fetchPendingMergeSuggestionsMock = vi.mocked(fetchPendingMergeSuggestions);
    const fetchTopUnlabeledClustersMock = vi.mocked(fetchTopUnlabeledClusters);

    // 1. Setup pending suggestions (Assignment)
    fetchPendingSuggestionsMock.mockResolvedValue({
      suggestions: [
        {
          id: 'sugg-1',
          identity_id: 'i1',
          suggested_cluster_id: 'c1',
          representative_similarity: 0.9,
          avg_member_similarity: 0.85,
          cluster_label: 'Alice',
          cluster_identity_count: 5,
        },
      ],
      limit: 10,
      offset: 0,
    });

    // 2. Setup pending merge suggestions (Merge Queue)
    fetchPendingMergeSuggestionsMock.mockResolvedValue({
      suggestions: [
        {
          id: 'merge-1',
          cluster_a_id: 'c1',
          cluster_b_id: 'c2',
          similarity: 0.95,
          cluster_a_label: 'Alice A',
          cluster_b_label: 'Alice B',
          cluster_a_identity_count: 5,
          cluster_b_identity_count: 3,
          status: 'pending',
        },
      ],
      limit: 10,
      offset: 0,
    });

    // 3. Setup top unlabeled clusters (Naming Queue)
    fetchTopUnlabeledClustersMock.mockResolvedValue(
      topUnlabeledResponse([
        {
          id: 'c-unlabeled',
          label: 'cluster-123',
          identity_count: 5, // Non-singleton
          representatives: [],
          tenant_id: 'test-tenant',
          user_confirmed: false,
          is_labeled: false,
          is_auto_label: true,
        },
      ]),
    );

    renderPanel();

    // 4. Verify Suggestions are present
    await waitFor(() => {
      expect(fetchPendingSuggestionsMock).toHaveBeenCalled();
    });

    expect(await screen.findByText(/Is this/)).toBeInTheDocument();

    // 5. Verify Naming Queue is ALSO present
    expect(await screen.findByText('Name These People')).toBeInTheDocument();

    // 6. Verify Merge Queue is present but Collapsed
    expect(await screen.findByText('Merge Candidates')).toBeInTheDocument();
    expect(screen.getByText('1', { selector: '.acx-badge--count' })).toBeInTheDocument(); // Badge count
    // Content should NOT be visible yet
    expect(screen.queryByText(/Are these the same person/)).not.toBeInTheDocument();

    // 7. Click to Expand Merge Queue
    await userEvent.click(screen.getByText('Merge Candidates'));
    expect(await screen.findByText(/Are these the same person/)).toBeInTheDocument();
  });

  it('renders top cluster thumbnails from thumb_url field', async () => {
    const fetchPendingSuggestionsMock = vi.mocked(fetchPendingSuggestions);
    const fetchPendingMergeSuggestionsMock = vi.mocked(fetchPendingMergeSuggestions);
    const fetchTopUnlabeledClustersMock = vi.mocked(fetchTopUnlabeledClusters);
    const representative = {
      id: 'rep-1',
      media_id: 101,
      thumb_url: 'http://example.test/media/face-101.jpg',
      is_pinned: false,
    } as TopUnlabeledCluster['representatives'][number];

    fetchPendingSuggestionsMock.mockResolvedValue({ suggestions: [], limit: 10, offset: 0 });
    fetchPendingMergeSuggestionsMock.mockResolvedValue({ suggestions: [], limit: 10, offset: 0 });
    fetchTopUnlabeledClustersMock.mockResolvedValue(
      topUnlabeledResponse([
        {
          id: 'cluster-top-1',
          label: null,
          identity_count: 3,
          representatives: [representative],
          tenant_id: 'test-tenant-id',
          user_confirmed: false,
          is_labeled: false,
          is_auto_label: true,
        },
      ]),
    );

    const { container } = renderPanel();

    await waitFor(() => {
      expect(fetchPendingSuggestionsMock).toHaveBeenCalled();
      expect(fetchPendingMergeSuggestionsMock).toHaveBeenCalled();
    });
    await waitFor(() => {
      expect(screen.queryByText('Loading suggestions...')).not.toBeInTheDocument();
    });

    expect(await screen.findByText('Name These People')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Name this person' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Label' })).not.toBeInTheDocument();
    expect(fetchTopUnlabeledClustersMock).toHaveBeenCalledWith('test-tenant-id', 20);

    const thumbImage = container.querySelector<HTMLImageElement>('.acx-top-cluster-card__thumb img');
    if (!thumbImage) {
      throw new Error('Expected top cluster thumbnail image');
    }
    expect(thumbImage.getAttribute('src')).toContain('face-101.jpg');
  });

  it('renders the singleton-only naming message for auto-labeled cluster rows', async () => {
    const fetchPendingSuggestionsMock = vi.mocked(fetchPendingSuggestions);
    const fetchPendingMergeSuggestionsMock = vi.mocked(fetchPendingMergeSuggestions);
    const fetchPendingNameSuggestionsMock = vi.mocked(fetchPendingNameSuggestions);
    const fetchTopUnlabeledClustersMock = vi.mocked(fetchTopUnlabeledClusters);

    fetchPendingSuggestionsMock.mockResolvedValue({ suggestions: [], limit: 10, offset: 0 });
    fetchPendingMergeSuggestionsMock.mockResolvedValue({ suggestions: [], limit: 10, offset: 0 });
    fetchPendingNameSuggestionsMock.mockResolvedValue({ suggestions: [], limit: 25, offset: 0 });
    fetchTopUnlabeledClustersMock.mockResolvedValue(topUnlabeledResponse([], 1));

    renderPanel();

    await waitFor(() => {
      expect(fetchPendingSuggestionsMock).toHaveBeenCalled();
      expect(fetchPendingMergeSuggestionsMock).toHaveBeenCalled();
      expect(fetchPendingNameSuggestionsMock).toHaveBeenCalled();
    });

    expect(await screen.findByText('Name These People')).toBeInTheDocument();
    expect(fetchTopUnlabeledClustersMock).toHaveBeenCalledWith('test-tenant-id', 20);
    expect(
      screen.getByText(
        'All detected groups contain only a single photo. Groups with multiple photos will appear here.',
      ),
    ).toBeInTheDocument();
  });

  it('renders top-cluster inferred name prompt with yes/no and confirms by merging into suggested target', async () => {
    const fetchPendingSuggestionsMock = vi.mocked(fetchPendingSuggestions);
    const fetchPendingMergeSuggestionsMock = vi.mocked(fetchPendingMergeSuggestions);
    const mergeClusterMock = vi.mocked(mergeCluster);
    const fetchTopUnlabeledClustersMock = vi.mocked(fetchTopUnlabeledClusters);

    fetchPendingSuggestionsMock.mockResolvedValue({ suggestions: [], limit: 10, offset: 0 });
    fetchPendingMergeSuggestionsMock.mockResolvedValue({ suggestions: [], limit: 10, offset: 0 });
    fetchTopUnlabeledClustersMock.mockResolvedValue(
      topUnlabeledResponse([
        {
          id: 'cluster-top-suggested',
          label: null,
          identity_count: 6,
          suggested_label: 'Coral Osborne',
          suggested_label_source: 'similar_cluster',
          suggested_label_confidence: 0.93,
          suggested_target_cluster_id: 'cluster-known-coral',
          representatives: [
            {
              id: 'rep-not-pinned',
              media_id: 101,
              thumb_url: 'http://example.test/media/not-pinned.jpg',
              is_pinned: false,
            },
            {
              id: 'rep-pinned',
              media_id: 102,
              thumb_url: 'http://example.test/media/pinned.jpg',
              is_pinned: true,
            },
          ],
          tenant_id: 'test-tenant-id',
          user_confirmed: false,
          is_labeled: false,
          is_auto_label: true,
        },
      ]),
    );

    const { container } = renderPanel();

    await waitFor(() => {
      expect(fetchPendingSuggestionsMock).toHaveBeenCalled();
      expect(fetchPendingMergeSuggestionsMock).toHaveBeenCalled();
    });

    expect(await screen.findByText('Is this Coral Osborne?')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Yes' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'No' })).toBeInTheDocument();

    const thumbImages = container.querySelectorAll<HTMLImageElement>(
      '.acx-top-cluster-card__thumb img, .acx-top-cluster-card__thumb [role="img"]',
    );
    expect(thumbImages).toHaveLength(1);
    // FaceThumbnail might render a div with background-image or a canvas, but here it's simple fallback img
    const srcAttr = thumbImages[0]?.getAttribute('src') ?? thumbImages[0]?.style.backgroundImage;
    expect(srcAttr).toContain('pinned.jpg');

    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: 'Yes' }));

    await waitFor(() => {
      expect(mergeClusterMock).toHaveBeenCalledWith('cluster-top-suggested', 'cluster-known-coral', 'Coral Osborne');
    });
    expect(vi.mocked(updateClusterLabel)).not.toHaveBeenCalled();
  });

  it('renders top cluster representative crop from media_url and bbox', async () => {
    const fetchPendingSuggestionsMock = vi.mocked(fetchPendingSuggestions);
    const fetchPendingMergeSuggestionsMock = vi.mocked(fetchPendingMergeSuggestions);
    const fetchTopUnlabeledClustersMock = vi.mocked(fetchTopUnlabeledClusters);

    fetchPendingSuggestionsMock.mockResolvedValue({ suggestions: [], limit: 10, offset: 0 });
    fetchPendingMergeSuggestionsMock.mockResolvedValue({ suggestions: [], limit: 10, offset: 0 });
    fetchTopUnlabeledClustersMock.mockResolvedValue(
      topUnlabeledResponse([
        {
          id: 'cluster-top-2',
          label: null,
          identity_count: 3,
          representatives: [
            {
              id: 'rep-crop-1',
              media_id: 101,
              media_url: 'http://example.test/media/face-source-101.jpg',
              bbox: { x: 12, y: 8, width: 40, height: 30 },
              is_pinned: false,
            },
          ],
          tenant_id: 'test-tenant-id',
          user_confirmed: false,
          is_labeled: false,
          is_auto_label: true,
        },
      ]),
    );

    const { container } = renderPanel();

    await waitFor(() => {
      expect(fetchPendingSuggestionsMock).toHaveBeenCalled();
      expect(fetchPendingMergeSuggestionsMock).toHaveBeenCalled();
    });
    await waitFor(() => {
      expect(screen.queryByText('Loading suggestions...')).not.toBeInTheDocument();
    });

    const thumbImage = container.querySelector<HTMLImageElement>('.acx-top-cluster-card__thumb img');
    if (!thumbImage) {
      throw new Error('Expected top cluster cropped image');
    }
    expect(thumbImage.getAttribute('src')).toContain('face-source-101.jpg');
    expect(thumbImage.getAttribute('style')).toContain('transform: translate(');
  });

  it('dismisses only the selected top cluster card and keeps other Skip buttons interactive', async () => {
    const fetchPendingSuggestionsMock = vi.mocked(fetchPendingSuggestions);
    const fetchPendingMergeSuggestionsMock = vi.mocked(fetchPendingMergeSuggestions);
    const fetchTopUnlabeledClustersMock = vi.mocked(fetchTopUnlabeledClusters);
    const dismissClusterMock = vi.mocked(dismissCluster);

    fetchPendingSuggestionsMock.mockResolvedValue({ suggestions: [], limit: 10, offset: 0 });
    fetchPendingMergeSuggestionsMock.mockResolvedValue({ suggestions: [], limit: 10, offset: 0 });

    let resolveDismiss: (() => void) | null = null;
    dismissClusterMock.mockImplementation(
      () =>
        new Promise<void>((resolve) => {
          resolveDismiss = resolve;
        }),
    );

    // Top-unlabeled fetch returns multiple clusters.
    fetchTopUnlabeledClustersMock.mockResolvedValue(
      topUnlabeledResponse([
        {
          id: 'cluster-skip-1',
          label: null,
          identity_count: 4,
          representatives: [],
          tenant_id: 'test-tenant-id',
          user_confirmed: false,
          is_labeled: false,
          is_auto_label: true,
        },
        {
          id: 'cluster-skip-2',
          label: null,
          identity_count: 3,
          representatives: [],
          tenant_id: 'test-tenant-id',
          user_confirmed: false,
          is_labeled: false,
          is_auto_label: true,
        },
      ]),
    );

    renderPanel();

    await waitFor(() => {
      expect(fetchPendingSuggestionsMock).toHaveBeenCalled();
    });
    expect(await screen.findByText('Name These People')).toBeInTheDocument();

    const initialSkipButtons = screen.getAllByRole('button', { name: 'Skip' });
    expect(initialSkipButtons).toHaveLength(2);
    expect(initialSkipButtons[0]).not.toBeDisabled();
    expect(initialSkipButtons[1]).not.toBeDisabled();

    const user = userEvent.setup();
    await user.click(initialSkipButtons[0]);

    await waitFor(() => {
      expect(dismissClusterMock).toHaveBeenCalledWith('cluster-skip-1');
    });

    // Dismissed card should be optimistically removed while mutation is pending.
    await waitFor(() => {
      const remainingSkipButtons = screen.getAllByRole('button', { name: 'Skip' });
      expect(remainingSkipButtons).toHaveLength(1);
      expect(remainingSkipButtons[0]).not.toBeDisabled();
    });

    await act(async () => {
      resolveDismiss?.();
      await Promise.resolve();
    });
  });

  it('renders name suggestions section when suggestions are returned', async () => {
    const fetchPendingSuggestionsMock = vi.mocked(fetchPendingSuggestions);
    const fetchPendingMergeSuggestionsMock = vi.mocked(fetchPendingMergeSuggestions);
    const fetchPendingNameSuggestionsMock = vi.mocked(fetchPendingNameSuggestions);

    fetchPendingSuggestionsMock.mockResolvedValue({ suggestions: [], limit: 25, offset: 0 });
    fetchPendingMergeSuggestionsMock.mockResolvedValue({ suggestions: [], limit: 10, offset: 0 });
    fetchPendingNameSuggestionsMock.mockResolvedValue({
      suggestions: [
        {
          id: 'name-sugg-1',
          cluster_id: 'cluster-ns-1',
          suggested_name: 'Alice Lemon',
          confidence_score: 0.85,
          source: 'machine',
          created_at: '2026-01-01T00:00:00Z',
          expires_at: null,
        },
        {
          id: 'name-sugg-2',
          cluster_id: 'cluster-ns-2',
          suggested_name: 'Bob Apricot',
          confidence_score: 0.45,
          source: 'machine',
          created_at: '2026-01-01T00:00:00Z',
          expires_at: null,
        },
      ],
      limit: 25,
      offset: 0,
    });

    renderPanel();

    await waitFor(() => {
      expect(fetchPendingNameSuggestionsMock).toHaveBeenCalled();
    });

    expect(await screen.findByText('Alice Lemon')).toBeInTheDocument();
    expect(screen.getByText('Bob Apricot')).toBeInTheDocument();
    // High-confidence badge: 85%
    expect(screen.getByText('85%')).toBeInTheDocument();
    // Low-confidence class present for 45%
    const lowBadge = screen.getByText('45%');
    expect(lowBadge).toHaveClass('acx-suggestion-confidence--low');
  });

  it('accepts a name suggestion and invalidates namePending query', async () => {
    const fetchPendingSuggestionsMock = vi.mocked(fetchPendingSuggestions);
    const fetchPendingMergeSuggestionsMock = vi.mocked(fetchPendingMergeSuggestions);
    const fetchPendingNameSuggestionsMock = vi.mocked(fetchPendingNameSuggestions);
    const acceptNameSuggestionMock = vi.mocked(acceptNameSuggestion);

    fetchPendingSuggestionsMock.mockResolvedValue({ suggestions: [], limit: 25, offset: 0 });
    fetchPendingMergeSuggestionsMock.mockResolvedValue({ suggestions: [], limit: 10, offset: 0 });
    fetchPendingNameSuggestionsMock.mockResolvedValue({
      suggestions: [
        {
          id: 'name-accept-1',
          cluster_id: 'cluster-na-1',
          suggested_name: 'Carol Mint',
          confidence_score: 0.78,
          source: 'machine',
          created_at: '2026-01-01T00:00:00Z',
          expires_at: null,
        },
      ],
      limit: 25,
      offset: 0,
    });
    acceptNameSuggestionMock.mockResolvedValue({} as Awaited<ReturnType<typeof acceptNameSuggestion>>);

    const { queryClient } = renderPanel();
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries');

    await waitFor(() => {
      expect(fetchPendingSuggestionsMock).toHaveBeenCalled();
    });
    await waitFor(() => {
      expect(fetchPendingMergeSuggestionsMock).toHaveBeenCalled();
    });

    await screen.findByText('Carol Mint');

    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: 'Accept' }));

    await waitFor(() => {
      expect(acceptNameSuggestionMock).toHaveBeenCalledWith('name-accept-1', expect.anything());
    });
    await waitFor(() => {
      expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: queryKeys.suggestions.namePending() });
    });
  });

  it('rejects a name suggestion and invalidates namePending query', async () => {
    const fetchPendingSuggestionsMock = vi.mocked(fetchPendingSuggestions);
    const fetchPendingMergeSuggestionsMock = vi.mocked(fetchPendingMergeSuggestions);
    const fetchPendingNameSuggestionsMock = vi.mocked(fetchPendingNameSuggestions);
    const rejectNameSuggestionMock = vi.mocked(rejectNameSuggestion);

    fetchPendingSuggestionsMock.mockResolvedValue({ suggestions: [], limit: 25, offset: 0 });
    fetchPendingMergeSuggestionsMock.mockResolvedValue({ suggestions: [], limit: 10, offset: 0 });
    fetchPendingNameSuggestionsMock.mockResolvedValue({
      suggestions: [
        {
          id: 'name-reject-1',
          cluster_id: 'cluster-nr-1',
          suggested_name: 'Dana Peach',
          confidence_score: 0.72,
          source: 'machine',
          created_at: '2026-01-01T00:00:00Z',
          expires_at: null,
        },
      ],
      limit: 25,
      offset: 0,
    });
    rejectNameSuggestionMock.mockResolvedValue({} as Awaited<ReturnType<typeof rejectNameSuggestion>>);

    const { queryClient } = renderPanel();
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries');

    await waitFor(() => {
      expect(fetchPendingSuggestionsMock).toHaveBeenCalled();
    });
    await waitFor(() => {
      expect(fetchPendingMergeSuggestionsMock).toHaveBeenCalled();
    });

    await screen.findByText('Dana Peach');

    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: 'Reject' }));

    await waitFor(() => {
      expect(rejectNameSuggestionMock).toHaveBeenCalledWith('name-reject-1', expect.anything());
    });
    await waitFor(() => {
      expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: queryKeys.suggestions.namePending() });
    });
  });

  it('renders bulk accept section with slider and two buttons', async () => {
    const fetchPendingSuggestionsMock = vi.mocked(fetchPendingSuggestions);
    const fetchPendingMergeSuggestionsMock = vi.mocked(fetchPendingMergeSuggestions);

    fetchPendingSuggestionsMock.mockResolvedValue({ suggestions: [], limit: 25, offset: 0 });
    fetchPendingMergeSuggestionsMock.mockResolvedValue({ suggestions: [], limit: 10, offset: 0 });

    renderPanel();

    await waitFor(() => {
      expect(fetchPendingSuggestionsMock).toHaveBeenCalled();
    });

    expect(await screen.findByText('Bulk accept')).toBeInTheDocument();
    expect(screen.getByRole('slider')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Bulk accept assignments' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Bulk accept names' })).toBeInTheDocument();
  });

  it('bulk accept assignments button calls bulkAcceptSuggestions with assignment type', async () => {
    const fetchPendingSuggestionsMock = vi.mocked(fetchPendingSuggestions);
    const fetchPendingMergeSuggestionsMock = vi.mocked(fetchPendingMergeSuggestions);
    const bulkAcceptSuggestionsMock = vi.mocked(bulkAcceptSuggestions);

    fetchPendingSuggestionsMock.mockResolvedValue({ suggestions: [], limit: 25, offset: 0 });
    fetchPendingMergeSuggestionsMock.mockResolvedValue({ suggestions: [], limit: 10, offset: 0 });
    bulkAcceptSuggestionsMock.mockResolvedValue({ accepted_count: 2, skipped_count: 0 });

    const { queryClient } = renderPanel();
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries');

    await waitFor(() => {
      expect(fetchPendingSuggestionsMock).toHaveBeenCalled();
    });
    await waitFor(() => {
      expect(fetchPendingMergeSuggestionsMock).toHaveBeenCalled();
    });

    const assignBtn = await screen.findByRole('button', { name: 'Bulk accept assignments' });

    const user = userEvent.setup();
    await user.click(assignBtn);

    await waitFor(() => {
      expect(bulkAcceptSuggestionsMock).toHaveBeenCalledWith(
        expect.objectContaining({ suggestion_type: 'assignment' }),
        expect.anything(),
      );
    });
    await waitFor(() => {
      expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: queryKeys.suggestions.pending() });
      expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: queryKeys.suggestions.namePending() });
    });
  });

  it('bulk accept names button calls bulkAcceptSuggestions with name type', async () => {
    const fetchPendingSuggestionsMock = vi.mocked(fetchPendingSuggestions);
    const fetchPendingMergeSuggestionsMock = vi.mocked(fetchPendingMergeSuggestions);
    const bulkAcceptSuggestionsMock = vi.mocked(bulkAcceptSuggestions);

    fetchPendingSuggestionsMock.mockResolvedValue({ suggestions: [], limit: 25, offset: 0 });
    fetchPendingMergeSuggestionsMock.mockResolvedValue({ suggestions: [], limit: 10, offset: 0 });
    bulkAcceptSuggestionsMock.mockResolvedValue({ accepted_count: 1, skipped_count: 0 });

    const { queryClient } = renderPanel();
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries');

    await waitFor(() => {
      expect(fetchPendingSuggestionsMock).toHaveBeenCalled();
    });
    await waitFor(() => {
      expect(fetchPendingMergeSuggestionsMock).toHaveBeenCalled();
    });

    const namesBtn = await screen.findByRole('button', { name: 'Bulk accept names' });

    const user = userEvent.setup();
    await user.click(namesBtn);

    await waitFor(() => {
      expect(bulkAcceptSuggestionsMock).toHaveBeenCalledWith(
        expect.objectContaining({ suggestion_type: 'name' }),
        expect.anything(),
      );
    });
    await waitFor(() => {
      expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: queryKeys.suggestions.namePending() });
      expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: queryKeys.clusters.all });
    });
  });
});
