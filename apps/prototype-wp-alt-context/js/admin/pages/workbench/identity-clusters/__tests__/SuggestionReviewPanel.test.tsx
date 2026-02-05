import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  acceptSuggestion,
  fetchPendingMergeSuggestions,
  fetchPendingSuggestions,
  rejectSuggestion,
} from '../../../../api/recognition';
import { resetConfigCache } from '../../../../api/config';
import { queryKeys } from '../../../../api/queryKeys';
import { SuggestionReviewPanel } from '../SuggestionReviewPanel';
import type { PendingSuggestionsResponse } from '../../../../api/recognition/types';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
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
  };
});

const renderPanel = () => {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: 1,
        retryDelay: 1,
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
    window.AltContextAdmin = {
      nonce: 'test-nonce',
      endpoints: {
        recognitionSuggestions: 'http://localhost/recognition/suggestions',
        recognitionMergeSuggestions: 'http://localhost/recognition/suggestions/merge',
      },
    } as unknown as NonNullable<Window['AltContextAdmin']>;
    resetConfigCache();
  });

  it('hides panel on initial load failure (cold start friendly)', async () => {
    const fetchPendingSuggestionsMock = vi.mocked(fetchPendingSuggestions);
    const fetchPendingMergeSuggestionsMock = vi.mocked(fetchPendingMergeSuggestions);
    fetchPendingSuggestionsMock.mockRejectedValue(new Error('Server error'));
    fetchPendingMergeSuggestionsMock.mockRejectedValue(new Error('Server error'));

    const { container } = renderPanel();

    await waitFor(() => {
      expect(fetchPendingSuggestionsMock).toHaveBeenCalledTimes(2);
      expect(fetchPendingMergeSuggestionsMock).toHaveBeenCalledTimes(2);
    });

    expect(container.querySelector('.acx-suggestion-panel')).not.toBeInTheDocument();
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
});
