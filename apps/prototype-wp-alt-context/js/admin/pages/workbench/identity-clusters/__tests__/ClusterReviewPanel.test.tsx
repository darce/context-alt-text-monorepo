import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { fetchClusterMembers, removeClusterMember } from '../../../../api/recognition';
import { queryKeys } from '../../../../api/queryKeys';
import { ClusterReviewPanel } from '../ClusterReviewPanel';

const reactQueryState = vi.hoisted(() => ({
  useQueryOverride: null as Record<string, unknown> | null,
}));

vi.mock('@tanstack/react-query', async () => {
  const actual = await vi.importActual<typeof import('@tanstack/react-query')>('@tanstack/react-query');
  return {
    ...actual,
    useQuery: (options: unknown) => {
      const result = (actual as { useQuery: (arg: unknown) => unknown }).useQuery(options);
      if (!reactQueryState.useQueryOverride) {
        return result;
      }
      return { ...(result as object), ...reactQueryState.useQueryOverride };
    },
  };
});

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

const renderPanel = (clusterId = 'cluster-123', onClose: () => void = () => undefined) => {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  });

  const utils = render(
    <QueryClientProvider client={queryClient}>
      <ClusterReviewPanel clusterId={clusterId} onClose={onClose} />
    </QueryClientProvider>,
  );

  return { queryClient, ...utils };
};

describe('ClusterReviewPanel', () => {
  afterEach(() => {
    reactQueryState.useQueryOverride = null;
    vi.resetAllMocks();
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

    expect(screen.getByRole('img', { name: 'Cluster member' })).toHaveClass('acx-cluster-member-card__image');

    const user = userEvent.setup();
    await user.click(screen.getByLabelText('Remove from cluster'));

    await waitFor(() => {
      expect(removeClusterMemberMock).toHaveBeenCalledWith('identity-1', true);
    });

    await waitFor(() => {
      expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: queryKeys.clusters.memberList(clusterId) });
      expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: queryKeys.clusters.all });
      expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: queryKeys.suggestions.pending() });
    });
  });

  it('renders cropped face fallback when thumbnail URL is missing', async () => {
    const fetchClusterMembersMock = vi.mocked(fetchClusterMembers);

    fetchClusterMembersMock.mockResolvedValue([
      {
        identity_id: 'identity-2',
        media_id: 2,
        similarity: 0.91,
        confidence: 0.98,
        bbox: { x: 12, y: 24, width: 48, height: 48 },
        thumbnail_url: null,
        media_url: 'http://example.test/media/member-2.jpg',
      },
    ]);

    renderPanel('cluster-456');

    await waitFor(() => {
      expect(fetchClusterMembersMock).toHaveBeenCalledWith('cluster-456');
    });

    expect(screen.getByRole('img', { name: 'Cluster member' })).toHaveAttribute(
      'src',
      'http://example.test/media/member-2.jpg',
    );
    expect(screen.getByRole('img', { name: 'Cluster member' })).not.toHaveClass('acx-cluster-member-card__image');
  });

  it('shows loading state while fetching members', () => {
    const fetchClusterMembersMock = vi.mocked(fetchClusterMembers);
    fetchClusterMembersMock.mockReturnValue(new Promise(() => undefined));

    renderPanel('cluster-loading');

    expect(screen.getByText('Loading members...')).toBeInTheDocument();
  });

  it('shows error message when members cannot be loaded', async () => {
    const fetchClusterMembersMock = vi.mocked(fetchClusterMembers);
    fetchClusterMembersMock.mockResolvedValue([]);
    reactQueryState.useQueryOverride = {
      data: undefined,
      isLoading: false,
      isError: true,
    };

    renderPanel('cluster-error');

    expect(screen.getByText('Unable to load cluster members.')).toBeInTheDocument();
  });

  it('does not remove member when user cancels confirmation dialog', async () => {
    const fetchClusterMembersMock = vi.mocked(fetchClusterMembers);
    const removeClusterMemberMock = vi.mocked(removeClusterMember);
    window.confirm = vi.fn().mockReturnValue(false);
    fetchClusterMembersMock.mockResolvedValue([
      {
        identity_id: 'identity-3',
        media_id: 3,
        similarity: 0.88,
        confidence: 0.92,
        bbox: { x: 2, y: 2, width: 20, height: 20 },
        thumbnail_url: 'http://example.test/thumb-3.jpg',
      },
    ]);

    renderPanel('cluster-cancel');
    const user = userEvent.setup();

    await waitFor(() => {
      expect(fetchClusterMembersMock).toHaveBeenCalledWith('cluster-cancel');
    });

    await user.click(screen.getByLabelText('Remove from cluster'));
    expect(removeClusterMemberMock).not.toHaveBeenCalled();
  });

  it('calls onClose when close button is clicked', async () => {
    const fetchClusterMembersMock = vi.mocked(fetchClusterMembers);
    const onClose = vi.fn();
    fetchClusterMembersMock.mockResolvedValue([]);

    renderPanel('cluster-close', onClose);
    const user = userEvent.setup();

    await user.click(screen.getByLabelText('Close'));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
