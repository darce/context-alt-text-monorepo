import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { fetchPendingSuggestions } from '../../../../api/recognition';
import { SuggestionReviewPanel } from '../SuggestionReviewPanel';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
}));

vi.mock('../../../../api/recognition', async () => {
  const actual = await vi.importActual<typeof import('../../../../api/recognition')>('../../../../api/recognition');
  return {
    ...actual,
    fetchPendingSuggestions: vi.fn(),
    acceptSuggestion: vi.fn(),
    rejectSuggestion: vi.fn(),
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

  return render(
    <QueryClientProvider client={queryClient}>
      <SuggestionReviewPanel />
    </QueryClientProvider>,
  );
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
      },
    } as unknown as NonNullable<Window['AltContextAdmin']>;
  });

  it('shows an error state and stops polling on 500 responses', async () => {
    const fetchPendingSuggestionsMock = vi.mocked(fetchPendingSuggestions);
    fetchPendingSuggestionsMock.mockRejectedValue(new Error('Server error'));

    renderPanel();

    // Wait for retries to complete (initial + 1 retry = 2 calls)
    await waitFor(() => {
      expect(fetchPendingSuggestionsMock).toHaveBeenCalledTimes(2);
    });

    // Now check for error state
    expect(await screen.findByText('Failed to load suggestions.')).toBeInTheDocument();
  });
});
