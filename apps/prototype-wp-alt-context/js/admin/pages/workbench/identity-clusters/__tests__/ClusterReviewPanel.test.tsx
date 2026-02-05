import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { fetchClusterMembers, removeClusterMember } from '../../../../api/recognition';
import { queryKeys } from '../../../../api/queryKeys';
import { ClusterReviewPanel } from '../ClusterReviewPanel';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
}));

vi.mock('../../../../api/recognition', async () => {
  const actual = await vi.importActual<typeof import('../../../../api/recognition')>('../../../../api/recognition');
  return {
    ...actual,
    fetchClusterMembers: vi.fn(),
    removeClusterMember: vi.fn(),
  };
});

const renderPanel = (clusterId = 'cluster-123') => {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: 1, retryDelay: 1 },
    },
  });

  const utils = render(
    <QueryClientProvider client={queryClient}>
      <ClusterReviewPanel clusterId={clusterId} onClose={() => undefined} />
    </QueryClientProvider>,
  );

  return { queryClient, ...utils };
};

describe('ClusterReviewPanel', () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  beforeEach(() => {
    window.confirm = vi.fn().mockReturnValue(true);
  });

  it('removes a cluster member and invalidates related queries', async () => {
    const fetchClusterMembersMock = vi.mocked(fetchClusterMembers);
    const removeClusterMemberMock = vi.mocked(removeClusterMember);
    const clusterId = 'cluster-123';

    fetchClusterMembersMock.mockResolvedValue([
      {
        identity_id: 'identity-1',
        media_id: 1,
        similarity: 0.95,
        confidence: 0.99,
        bbox: { x: 0, y: 0, width: 10, height: 10 },
        thumbnail_url: 'http://example.test/thumb.jpg',
      },
    ]);
    removeClusterMemberMock.mockResolvedValue(undefined);

    const { queryClient } = renderPanel(clusterId);
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries');

    await waitFor(() => {
      expect(fetchClusterMembersMock).toHaveBeenCalledWith(clusterId);
    });

    const user = userEvent.setup();
    await user.click(screen.getByLabelText('Remove from cluster'));

    await waitFor(() => {
      expect(removeClusterMemberMock).toHaveBeenCalledWith('identity-1', true);
    });

    await waitFor(() => {
      expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['cluster-members', clusterId] });
      expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: queryKeys.clusters.all });
      expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: queryKeys.suggestions.pending() });
    });
  });
});
