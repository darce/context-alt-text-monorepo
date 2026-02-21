import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  acceptSuggestion,
  dismissCluster,
  fetchPendingMergeSuggestions,
  fetchPendingSuggestions,
  fetchTopUnlabeledClusters,
  mergeCluster,
  rejectSuggestion,
  updateClusterLabel,
} from '../../../../api/recognition';
import { resetConfigCache } from '../../../../api/config';
import { queryKeys } from '../../../../api/queryKeys';
import { SuggestionReviewPanel } from '../SuggestionReviewPanel';
import type { PendingSuggestionsResponse } from '../../../../api/recognition/types';
import type { TopUnlabeledCluster } from '../../../../api/recognition/types';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  _n: (single: string, plural: string, number: number) => (number === 1 ? single : plural),
  sprintf: (text: string) => text,
}));

vi.mock('../../../../api/recognition', async () => {
  const actual = await vi.importActual<typeof import('../../../../api/recognition')>('../../../../api/recognition');
  return {
    ...actual,
    fetchPendingSuggestions: vi.fn(),
    fetchPendingMergeSuggestions: vi.fn(),
    acceptSuggestion: vi.fn(),
    acceptMergeSuggestion: vi.fn(),
    rejectSuggestion: vi.fn(),
    rejectMergeSuggestion: vi.fn(),
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
        recognitionClusters: 'http://localhost/recognition/clusters',
      },
      tenant_id: 'test-tenant-id',
    } as unknown as NonNullable<Window['AltContextAdmin']>;

    fetchTopUnlabeledClustersMock.mockResolvedValue([]);
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
      total: 1,
      limit: 10,
      offset: 0,
    };
    fetchPendingSuggestionsMock.mockResolvedValue(pendingResponse);
    fetchPendingMergeSuggestionsMock.mockResolvedValue({
      suggestions: [],
      total: 0,
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
      total: 3,
      limit: 10,
      offset: 0,
    });
    fetchPendingMergeSuggestionsMock.mockResolvedValue({
      suggestions: [],
      total: 0,
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
        total: 3,
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
        total: 1,
        limit: 10,
        offset: 0,
      });
    fetchPendingMergeSuggestionsMock.mockResolvedValue({
      suggestions: [],
      total: 0,
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
      total: 1,
      limit: 10,
      offset: 0,
    };
    fetchPendingSuggestionsMock.mockResolvedValue(pendingResponse);
    fetchPendingMergeSuggestionsMock.mockResolvedValue({
      suggestions: [],
      total: 0,
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
      total: 2,
      limit: 10,
      offset: 0,
    });
    fetchPendingMergeSuggestionsMock.mockResolvedValue({
      suggestions: [],
      total: 0,
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
      total: 2,
      limit: 10,
      offset: 0,
    });
    fetchPendingMergeSuggestionsMock.mockResolvedValue({
      suggestions: [],
      total: 0,
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

  it('renders face grid when cluster thumbnails are present', async () => {
    const fetchPendingSuggestionsMock = vi.mocked(fetchPendingSuggestions);
    const fetchPendingMergeSuggestionsMock = vi.mocked(fetchPendingMergeSuggestions);
    const pendingResponse: PendingSuggestionsResponse = {
      suggestions: [
        {
          id: 'sugg-grid',
          identity_id: 'identity-g',
          suggested_cluster_id: 'cluster-g',
          representative_similarity: 0.95,
          avg_member_similarity: 0.9,
          cluster_label: 'Grid Cluster',
          cluster_identity_count: 10,
          cluster_thumbnails: [
            'http://example.com/1.jpg',
            'http://example.com/2.jpg',
            'http://example.com/3.jpg',
            'http://example.com/4.jpg',
          ],
        },
      ],
      total: 1,
      limit: 10,
      offset: 0,
    };
    fetchPendingSuggestionsMock.mockResolvedValue(pendingResponse);
    fetchPendingMergeSuggestionsMock.mockResolvedValue({ suggestions: [], total: 0, limit: 10, offset: 0 });

    const { container } = renderPanel();

    await waitFor(() => {
      expect(fetchPendingSuggestionsMock).toHaveBeenCalled();
    });

    expect(container.querySelector('.acx-face-grid-preview')).toBeInTheDocument();
    const gridImages = container.querySelectorAll('.acx-face-grid-preview img');
    expect(gridImages.length).toBe(4);
  });

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
          cluster_thumbnails: [],
        },
      ],
      total: 1,
      limit: 10,
      offset: 0,
    };
    fetchPendingSuggestionsMock.mockResolvedValue(pendingResponse);
    fetchPendingMergeSuggestionsMock.mockResolvedValue({ suggestions: [], total: 0, limit: 10, offset: 0 });

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
          cluster_thumbnails: [],
        },
      ],
      total: 1,
      limit: 10,
      offset: 0,
    };
    fetchPendingSuggestionsMock.mockResolvedValue(pendingResponse);
    fetchPendingMergeSuggestionsMock.mockResolvedValue({ suggestions: [], total: 0, limit: 10, offset: 0 });

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
          cluster_thumbnails: [],
        },
      ],
      total: 1,
      limit: 10,
      offset: 0,
    };
    fetchPendingSuggestionsMock.mockResolvedValue(pendingResponse);
    fetchPendingMergeSuggestionsMock.mockResolvedValue({ suggestions: [], total: 0, limit: 10, offset: 0 });

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
      total: 1,
      limit: 10,
      offset: 0,
    });
    fetchPendingMergeSuggestionsMock.mockResolvedValue({ suggestions: [], total: 0, limit: 10, offset: 0 });

    const { container } = renderPanel();

    await waitFor(() => {
      expect(fetchPendingSuggestionsMock).toHaveBeenCalled();
    });

    expect(container.querySelector('.acx-suggestion-card--low-confidence')).toBeInTheDocument();
    expect(await screen.findByText('Low confidence')).toBeInTheDocument();
  });

  it('allows collapsing and expanding the suggestion panel', async () => {
    const fetchPendingSuggestionsMock = vi.mocked(fetchPendingSuggestions);
    const fetchPendingMergeSuggestionsMock = vi.mocked(fetchPendingMergeSuggestions);

    fetchPendingSuggestionsMock.mockResolvedValue({
      suggestions: [
        {
          id: 'sugg-collapse',
          identity_id: 'identity-collapse',
          suggested_cluster_id: 'cluster-collapse',
          representative_similarity: 0.9,
          avg_member_similarity: 0.85,
          cluster_label: 'Collapse Test',
          cluster_identity_count: 2,
        },
      ],
      total: 1,
      limit: 10,
      offset: 0,
    });
    fetchPendingMergeSuggestionsMock.mockResolvedValue({ suggestions: [], total: 0, limit: 10, offset: 0 });

    renderPanel();

    await waitFor(() => {
      expect(fetchPendingSuggestionsMock).toHaveBeenCalled();
    });
    expect(await screen.findByText(/Is this/)).toBeInTheDocument();

    const panelToggle = screen.getByRole('button', { name: /Review Suggestions/i });
    expect(panelToggle).toHaveAttribute('aria-expanded', 'true');

    await userEvent.click(panelToggle);

    await waitFor(() => {
      expect(panelToggle).toHaveAttribute('aria-expanded', 'false');
      expect(screen.queryByText(/Is this/)).not.toBeInTheDocument();
    });

    await userEvent.click(panelToggle);

    await waitFor(() => {
      expect(panelToggle).toHaveAttribute('aria-expanded', 'true');
    });
    expect(await screen.findByText(/Is this/)).toBeInTheDocument();
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
      total: 1,
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
      total: 1,
      limit: 10,
      offset: 0,
    });

    // 3. Setup top unlabeled clusters (Naming Queue)
    fetchTopUnlabeledClustersMock.mockResolvedValue([
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
    ]);

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

  it('renders top cluster thumbnails from legacy thumbnail_url field', async () => {
    const fetchPendingSuggestionsMock = vi.mocked(fetchPendingSuggestions);
    const fetchPendingMergeSuggestionsMock = vi.mocked(fetchPendingMergeSuggestions);
    const fetchTopUnlabeledClustersMock = vi.mocked(fetchTopUnlabeledClusters);
    const legacyRepresentative = {
      id: 'rep-1',
      media_id: 101,
      thumbnail_url: 'http://example.test/media/face-101.jpg',
      is_pinned: false,
    } as TopUnlabeledCluster['representatives'][number];

    fetchPendingSuggestionsMock.mockResolvedValue({ suggestions: [], total: 0, limit: 10, offset: 0 });
    fetchPendingMergeSuggestionsMock.mockResolvedValue({ suggestions: [], total: 0, limit: 10, offset: 0 });
    fetchTopUnlabeledClustersMock.mockResolvedValue([
      {
        id: 'cluster-top-1',
        label: null,
        identity_count: 3,
        representatives: [legacyRepresentative],
        tenant_id: 'test-tenant-id',
        user_confirmed: false,
        is_labeled: false,
        is_auto_label: true,
      },
    ]);

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

  it('renders top-cluster inferred name prompt with yes/no and confirms by merging into suggested target', async () => {
    const fetchPendingSuggestionsMock = vi.mocked(fetchPendingSuggestions);
    const fetchPendingMergeSuggestionsMock = vi.mocked(fetchPendingMergeSuggestions);
    const mergeClusterMock = vi.mocked(mergeCluster);
    const fetchTopUnlabeledClustersMock = vi.mocked(fetchTopUnlabeledClusters);

    fetchPendingSuggestionsMock.mockResolvedValue({ suggestions: [], total: 0, limit: 10, offset: 0 });
    fetchPendingMergeSuggestionsMock.mockResolvedValue({ suggestions: [], total: 0, limit: 10, offset: 0 });
    fetchTopUnlabeledClustersMock.mockResolvedValue([
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
    ]);

    const { container } = renderPanel();

    await waitFor(() => {
      expect(fetchPendingSuggestionsMock).toHaveBeenCalled();
      expect(fetchPendingMergeSuggestionsMock).toHaveBeenCalled();
    });

    expect(await screen.findByText('Is this Coral Osborne?')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Yes' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'No' })).toBeInTheDocument();

    const thumbImages = container.querySelectorAll<HTMLImageElement>('.acx-top-cluster-card__thumb img');
    expect(thumbImages).toHaveLength(1);
    expect(thumbImages[0]?.getAttribute('src')).toContain('pinned.jpg');

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

    fetchPendingSuggestionsMock.mockResolvedValue({ suggestions: [], total: 0, limit: 10, offset: 0 });
    fetchPendingMergeSuggestionsMock.mockResolvedValue({ suggestions: [], total: 0, limit: 10, offset: 0 });
    fetchTopUnlabeledClustersMock.mockResolvedValue([
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
    ]);

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

    fetchPendingSuggestionsMock.mockResolvedValue({ suggestions: [], total: 0, limit: 10, offset: 0 });
    fetchPendingMergeSuggestionsMock.mockResolvedValue({ suggestions: [], total: 0, limit: 10, offset: 0 });

    let resolveDismiss: (() => void) | null = null;
    dismissClusterMock.mockImplementation(
      () =>
        new Promise<void>((resolve) => {
          resolveDismiss = resolve;
        }),
    );

    // Top-unlabeled fetch returns multiple clusters.
    fetchTopUnlabeledClustersMock.mockResolvedValue([
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
    ]);

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
});
